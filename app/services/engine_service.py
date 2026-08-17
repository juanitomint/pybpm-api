"""Engine Service — business logic for BPM case execution.

This module contains all the core engine methods that manage token lifecycle,
shape dispatch, and workflow advancement. The legacy PHP code had these as
methods on the `Bpm` model class; we've extracted them into a dedicated service
for better separation of concerns.

Key responsibilities:
- Token creation/deletion/lookup
- Shape tree traversal (find shapes by resourceId/stencil ID)
- movenext() — advance tokens through outgoing flows
- Signal/trigger/subprocess handling (deferred)
"""

from collections.abc import Sequence
from datetime import UTC, datetime
import logging
import sqlalchemy as sa
from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from extensions import get_async_db
from app.models.bpm_model import BpmModel
from app.models.token import Token, TokenHistory


class EngineService:
    """Core engine service for BPM case execution.

    This service wraps all database operations needed to run a workflow.
    It's called by the FastAPI router endpoints in `app/api/bpm/engine.py`.
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    # -- Token lifecycle ----------------------------------------------------- #

    async def create_token(
        self,
        idwf: str,
        case_id: str,
        resource_id: str,
        type_: str,
        status: str = "pending",
    ) -> None:
        """Insert a new token for a shape in a case."""
        token = Token(
            idwf=idwf,
            case_id=case_id,
            resource_id=resource_id,
            type=type_,
            status=status,
            assign=[],  # empty assignment initially
        )
        self.db.add(token)
        await self.db.flush()

    async def delete_tokens(self, idwf: str, case_id: str) -> None:
        """Delete all tokens for a case (used before restart)."""
        stmt = select(Token).where(
            Token.idwf == idwf,
            Token.case_id == case_id,
        )
        result = await self.db.execute(stmt)
        tokens = result.scalars().all()
        for token in tokens:
            await self.db.delete(token)

    async def get_token(
        self, idwf: str, case_id: str, resource_id: str
    ) -> Token | None:
        """Fetch a single token by (idwf, case_id, resourceId)."""
        stmt = select(Token).where(
            Token.idwf == idwf,
            Token.case_id == case_id,
            Token.resource_id == resource_id,
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_pending_tokens(
        self, idwf: str, case_id: str, status_filter: list[str] | None = None
    ) -> Sequence[Token]:
        """Fetch pending/waiting tokens for a case.

        Optional `status_filter` limits results to specific statuses (e.g., ['pending', 'waiting']).
        Defaults to all non-finished statuses if not provided.
        """
        stmt = select(Token).where(
            Token.idwf == idwf,
            Token.case_id == case_id,
        )
        if status_filter:
            stmt = stmt.where(Token.status.in_(status_filter))
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def mark_token_finished(self, token: Token) -> None:
        """Mark a token as finished and record history."""
        token.status = "finished"
        token.run_count += 1
        token.updated_at = datetime.now(UTC)
        await self.db.flush()

        # Record in history table
        history = TokenHistory(
            idwf=token.idwf,
            case_id=token.case_id,
            resource_id=token.resource_id,
            type=token.type,
            status="finished",
            check_date=datetime.now(UTC),
            run_count=token.run_count,
        )
        self.db.add(history)
    async def _set_token_status(
        self, idwf: str, case_id: str, resource_id: str, status_: str, data: dict | None = None
    ) -> None:
        """Update a token's status and/or external_data.

        Looks up the token by (idwf, case_id, resourceId) — same lookup used by
        ``get_token`` — then mutates its status and/or external_data columns.
        Mirrors legacy ``updateToken()`` behavior where status changes are paired
        with optional data transport on the same call.
        """
        token = await self.get_token(idwf, case_id, resource_id)
        if not token:
            return  # Token doesn't exist — silently skip (e.g., racing handler).

        changed = False
        if status_ is not None and token.status != status_:
            token.status = status_
            changed = True

        if data is not None:
            token.external_data = data
            changed = True

        if changed:
            token.updated_at = datetime.now(UTC)
            await self.db.flush()
    # -- Event schedule management ------------------------------------------- #

    async def _create_timer_event_schedule(
        self,
        case_id: str,
        idwf: str,
        resource_id: str,
        trigger_time: datetime,
        data_json: dict | None = None,
        idu: int | None = None,
    ) -> int:
        """Create an event_schedules row for a timer event that entered 'waiting' state.

        The scheduler polls this table to find events whose ``trigger_time`` has
        arrived and fires them by advancing the corresponding waiting token.

        Returns the new schedule's idschedule.
        """
        from app.models.event_schedule import EventSchedule as ScheduleModel

        entry = ScheduleModel(
            case_id=case_id,
            idwf=idwf,
            resource_id=resource_id,
            trigger_time=trigger_time,
            schedule_type="timer",
            status="pending",
            data_json=data_json or {},
            idu=idu,
        )
        self.db.add(entry)
        await self.db.flush()
        logger = logging.getLogger(__name__)
        logger.debug(
            "Created event_schedule: type=timer resource=%s trigger=%s",
            resource_id, trigger_time.isoformat(),
        )
        return entry.idschedule  # type: ignore[return-value]

    # -- Shape parent lookup & case close ------------------------------------ #
    async def get_shape_parent(self, resource_id: str, idwf: str) -> dict | None:
        """Find the container parent shape of a given shape in the model tree.

        First checks ``shape.properties.subproc_parent`` (explicit parent reference),
        then walks the childShapes tree to find which shape has this resourceId as a
        direct childShape. Returns None if no parent found.

        Mirrors legacy ``run_EndNoneEvent()`` logic that checks $shape->properties->subproc_parent
        before falling back to get_shape_parent($shape->resourceId, $wf).
        """
        # Step 1: Check shape's own subproc_parent property.
        shape = await self.get_shape(resource_id, idwf)
        if not shape:
            return None
        props = shape.get("properties") or {}
        parent_rid = props.get("subproc_parent")
        if parent_rid and isinstance(parent_rid, str):
            parent = await self.get_shape(parent_rid, idwf)
            if parent:
                return parent

        # Step 2: Walk tree to find which shape contains this resourceId as a child.
        stmt = select(BpmModel.data).where(BpmModel.idwf == idwf)
        result = await self.db.execute(stmt)
        data = result.scalar_one_or_none()
        if not data or "childShapes" not in data:
            return None

        def _walk(node: dict):
            if not isinstance(node, dict):
                return None
            for key in ("childShapes", "shapes"):
                children = node.get(key, [])
                if isinstance(children, list):
                    for child in children:
                        if not isinstance(child, dict):
                            continue
                        rid = child.get("resourceId") or child.get("id")
                        if rid == resource_id:
                            return node  # found parent!
                        found = _walk(child)
                        if found:
                            return found
            return None

        return _walk(data)
    async def close_case_if_empty(
        self, idwf: str, case_id: str, closer_resource_id: str | None = None
    ) -> bool:
        """Close the case if there are no active tokens (user/waiting/pending).

        Counts tokens with status in ['user', 'waiting', 'pending']. If zero, updates
        the case record to status='closed' and records closer + checkoutdate.

        Returns True if the case was closed, False otherwise.
        Mirrors legacy ``run_EndNoneEvent()`` L139-154.
        """
        from app.models.case import BpmCase

        stmt = select(Token).where(
            Token.idwf == idwf,
            Token.case_id == case_id,
            Token.status.in_(["user", "waiting", "pending"]),
        )
        result = await self.db.execute(stmt)
        active_tokens = result.scalars().all()

        if len(active_tokens) > 0:
            return False

        # No active tokens — close the case.
        update_stmt = (
            sa.update(BpmCase)
            .where(
                BpmCase.idcase == case_id,
                BpmCase.idwf == idwf,
            )
            .values(
                status="closed",
                closer=closer_resource_id or "",
                checkoutdate=datetime.now(UTC),
            )
        )
        await self.db.execute(update_stmt)  # type: ignore[misc]
        return True
    # -- Shape tree traversal ------------------------------------------------ #

    async def get_shape(self, resource_id: str, idwf: str) -> dict | None:
        """Fetch a single shape from the model by resourceId."""
        stmt = select(BpmModel.data).where(BpmModel.idwf == idwf)
        result = await self.db.execute(stmt)
        data = result.scalar_one_or_none()

        if not data or "childShapes" not in data:
            return None

        # Walk shape tree to find matching resourceId
        def _walk(node: dict) -> dict | None:
            if not isinstance(node, dict):
                return None
            if node.get("resourceId") == resource_id or node.get("id") == resource_id:
                return node
            for key in ("childShapes", "shapes"):
                children = node.get(key, [])
                if isinstance(children, list):
                    for child in children:
                        found = _walk(child)
                        if found:
                            return found
            return None

        return _walk(data)

    async def get_start_shapes(self, idwf: str) -> list[dict]:
        """Find all start shapes (StartNoneEvent stencils) in a model."""
        stmt = select(BpmModel.data).where(BpmModel.idwf == idwf)
        result = await self.db.execute(stmt)
        data = result.scalar_one_or_none()

        if not data or "childShapes" not in data:
            return []

        starts: list[dict] = []

        def _walk(node: dict):
            if not isinstance(node, dict):
                return
            stencil = node.get("stencil") or {}
            if stencil.get("id") == "StartNoneEvent":
                starts.append(node)
            for key in ("childShapes", "shapes"):
                children = node.get(key, [])
                if isinstance(children, list):
                    for child in children:
                        _walk(child)

        _walk(data)
        return starts

    async def get_previous(self, resource_id: str, idwf: str) -> list[dict]:
        """Find all inbound shapes (predecessors) for a given shape."""
        stmt = select(BpmModel.data).where(BpmModel.idwf == idwf)
        result = await self.db.execute(stmt)
        data = result.scalar_one_or_none()

        if not data or "childShapes" not in data:
            return []

        previous: list[dict] = []

        def _walk(node: dict):
            if not isinstance(node, dict):
                return
            outgoing = node.get("outgoing", []) or []
            for pointer in outgoing:
                if not isinstance(pointer, dict):
                    continue
                rid = pointer.get("resourceId") or pointer.get("id")
                if rid == resource_id:
                    previous.append(node)
                    break
            for key in ("childShapes", "shapes"):
                children = node.get(key, [])
                if isinstance(children, list):
                    for child in children:
                        _walk(child)

        _walk(data)
        return previous

    # -- movenext ------------------------------------------------------------ #

    async def movenext(self, resource_id: str, idwf: str, case_id: str) -> None:
        """Advance token through outgoing flows.

        Marks current token as finished and creates pending tokens on all outgoing
        sequence flow shapes (skipping ignored stencils like TextAnnotation).
        This is the core primitive for engine execution — every shape handler either
        calls movenext directly or returns a boolean to control it.
        """
        # Mark current token as finished
        token = await self.get_token(idwf, case_id, resource_id)
        if not token:
            return

        await self.mark_token_finished(token)

        # Find outgoing shapes and create pending tokens on them
        shape = await self.get_shape(resource_id, idwf)
        if not shape or "outgoing" not in shape:
            return

        ignored_shapes = {"TextAnnotation", "Association_Undirected"}

        for pointer in shape["outgoing"]:
            if not isinstance(pointer, dict):
                continue
            out_rid = pointer.get("resourceId") or pointer.get("id")
            if not out_rid:
                continue

            out_shape = await self.get_shape(out_rid, idwf)
            if not out_shape:
                continue

            out_stencil = (out_shape.get("stencil") or {}).get("id", "")
            if out_stencil in ignored_shapes:
                continue

            # Check if token already exists for this shape
            existing = await self.get_token(idwf, case_id, out_rid)
            if not existing:
                await self.create_token(
                    idwf=idwf,
                    case_id=case_id,
                    resource_id=out_rid,
                    type_=out_stencil,
                    status="pending",
                )

    # -- Utility methods ----------------------------------------------------- #

    @staticmethod
    def _url_decode(value: str) -> str:
        """URL-decode a string (mirrors legacy PHP urldecode())."""
        from urllib.parse import unquote_plus

        return unquote_plus(value)


def get_engine_service(db: AsyncSession = Depends(get_async_db)):
    """FastAPI dependency that yields a bound ``EngineService``.

    Usage in router endpoints::

        from fastapi import Depends
        @router.post("/...")
        async def endpoint(..., service: EngineService = Depends(get_engine_service)):
            ...

    The `db` parameter is resolved by FastAPI via dependency injection.
    """
    return EngineService(db)
