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

from app.models.bpm_model import BpmModel
from app.models.token import Token, TokenHistory
from extensions import get_async_db


class EngineService:
    """Core engine service for BPM case execution.

    This service wraps all database operations needed to run a workflow.
    It's called by the FastAPI router endpoints in `app/api/bpm/engine.py`.
    """

    @classmethod
    async def create(
        cls, db: AsyncSession, idwf: str | None = None, idcase: str | None = None
    ) -> "EngineService":
        """Async factory — loads the flat model eagerly so it's available immediately."""
        self = cls.__new__(cls)
        self.db = db
        self._idwf = idwf
        self._idcase = idcase
        if idwf:
            from app.services.model_service import ModelService

            service = ModelService(db)
            self._flat_model = await service.get_flat_model(idwf)
        else:
            self._flat_model = {}
        return self

    def __init__(
        self, db: AsyncSession, idwf: str | None = None, idcase: str | None = None
    ):
        self.db = db
        self._idwf = idwf
        self._idcase = idcase
        self._flat_model: dict[str, Any] = {}

    # -- Token lifecycle ----------------------------------------------------- #

    async def create_token(
        self,
        idwf: str,
        case_id: str,
        resource_id: str,
        type_: str,
        status: str = "pending",
        title: str | None = None,
    ) -> None:
        """Insert a new token for a shape in a case."""
        token = Token(
            idwf=idwf,
            case_id=case_id,
            resource_id=resource_id,
            type=type_,
            status=status,
            assign=[],
            title=title,
        )
        self.db.add(token)
        await self.db.flush()

    async def upsert_token(
        self,
        idwf: str,
        case_id: str,
        resource_id: str,
        type_: str,
        status: str = "pending",
    ) -> None:
        """Create a new token or reset an existing one to the given status.

        When a token already exists for this (idwf, case_id, resource_id),
        its status and updated_at are reset — used by ``movenext`` to
        re-activate tokens that were consumed by a gateway's synchronization.
        """
        # Look up shape to extract title for UI display.
        shape = await self.get_shape(resource_id, idwf)
        title = None
        if shape:
            title = (shape.get("properties") or {}).get("name")

        existing = await self.get_token(idwf, case_id, resource_id)
        if existing is not None:
            existing.status = status
            if title:
                existing.title = title
            existing.updated_at = datetime.now(UTC)
            await self.db.flush()
            return

        await self.create_token(
            idwf=idwf,
            case_id=case_id,
            resource_id=resource_id,
            type_=type_,
            status=status,
            title=title,
        )

    async def delete_tokens(self, idwf: str, case_id: str) -> None:
        """Delete all tokens for a case (used before restart)."""
        stmt = sa.delete(Token).where(
            Token.idwf == idwf,
            Token.case_id == case_id,
        )
        await self.db.execute(stmt)  # type: ignore[misc]
        await self.db.flush()

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
        self,
        idwf: str,
        case_id: str,
        resource_id: str,
        status_: str,
        data: dict | None = None,
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

    async def _check_token_finished(
        self, idwf: str, case_id: str, resource_id: str
    ) -> bool:
        """Return True if a token is finished (or doesn't exist).

        Used by boundary-event logic to decide whether the parent activity has
        completed before canceling or advancing. Mirrors legacy PHP's check on
        ``$token['status'] !== 'finished'``.
        """
        from app.models.token import Token as _Token  # lazy import

        stmt = sa.select(_Token).where(
            _Token.idwf == idwf,
            _Token.case_id == case_id,
            _Token.resource_id == resource_id,
        )
        result = await self.db.execute(stmt)  # type: ignore[misc]
        token = result.scalar_one_or_none()
        return token is not None and token.status == "finished"

    async def _cancel_subprocess_children(
        self, resource_id: str, idwf: str, case_id: str
    ) -> int:
        """Cancel all non-finished tokens inside a Subprocess container shape.

        Uses the flat model to find the container (O(1)) then walks its
        ``childShapes`` / ``shapes`` arrays to find descendant shapes, marking
        their tokens as 'canceled'. Recurses into nested Subprocess /
        CollapsedSubprocess children. Returns count of canceled tokens.

        Mirrors legacy ``run_IntermediateEventCatching()`` L307-316 plus the
        TODO-dive-deeper comment for nested subprocesses.
        """
        container = self._flat_model.get(resource_id)
        if not container:
            return 0

        canceled_count = 0

        async def _cancel_descendants(node: dict) -> None:
            nonlocal canceled_count
            for key in ("childShapes", "shapes"):
                children = node.get(key, []) or []
                if not isinstance(children, list):
                    continue
                for child in children:
                    if not isinstance(child, dict):
                        continue
                    rid = child.get("resourceId") or child.get("id", "")
                    if not rid:
                        continue
                    token = await self.get_token(idwf, case_id, rid)
                    if token and token.status != "finished":
                        cancel_data = {
                            "canceledBy": resource_id,
                            "canceledName": (
                                (child.get("properties") or {}).get("name", "")
                            ),
                        }
                        await self._set_token_status(
                            idwf, case_id, rid, "canceled", data=cancel_data
                        )
                        canceled_count += 1
                    child_stencil = (child.get("stencil") or {}).get("id", "")
                    if child_stencil in ("Subprocess", "CollapsedSubprocess"):
                        # For nested subprocesses, look up their shape in the
                        # flat model to get their childShapes.
                        nested = flat.get(rid)
                        if nested:
                            await _cancel_descendants(nested)

        await _cancel_descendants(container)
        return canceled_count

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
            resource_id,
            trigger_time.isoformat(),
        )
        return entry.idschedule  # type: ignore[return-value]

    async def _create_signal_event_schedule(
        self,
        case_id: str,
        idwf: str,
        resource_id: str,
        signal_name: str,
        data_json: dict | None = None,
        idu: int | None = None,
    ) -> int:
        """Create an event_schedules row for a signal catch event that entered 'waiting' state.

        The scheduler polls this table to find pending signal schedules and fires them when matching signals exist.

        Returns the new schedule's idschedule.
        """
        from app.models.event_schedule import EventSchedule as ScheduleModel

        entry = ScheduleModel(
            case_id=case_id,
            idwf=idwf,
            resource_id=resource_id,
            trigger_time=datetime.now(
                UTC
            ),  # Signal schedules don't have a future time; they fire when signal arrives.
            schedule_type="signal",
            status="pending",
            data_json=data_json or {"name": signal_name},
            idu=idu,
        )
        self.db.add(entry)
        await self.db.flush()
        logger = logging.getLogger(__name__)
        logger.debug(
            "Created event_schedule: type=signal resource=%s name='%s'",
            resource_id,
            signal_name,
        )
        return entry.idschedule  # type: ignore[return-value]

    async def get_shape_parent(self, resource_id: str, idwf: str) -> dict | None:
        """Find the container parent shape of a given shape in the model tree.

        First checks ``shape.properties.subproc_parent`` (explicit parent reference),
        then scans the flat model to find which shape has this resourceId as a
        direct childShape. Returns None if no parent found.
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

        # Step 2: Scan flat model for the shape that contains this resourceId.
        for candidate in self._flat_model.values():
            for key in ("childShapes", "shapes"):
                for child in candidate.get(key) or []:
                    if isinstance(child, dict):
                        rid = child.get("resourceId") or child.get("id")
                        if rid == resource_id:
                            return candidate

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
        return self._flat_model.get(resource_id)

    async def get_start_shapes(self, idwf: str) -> list[dict]:
        """Find all start shapes (StartNoneEvent stencils) in a model."""
        return [
            shape
            for shape in self._flat_model.values()
            if (shape.get("stencil") or {}).get("id") == "StartNoneEvent"
        ]

    async def get_previous(self, resource_id: str, idwf: str) -> list[dict]:
        """Find all inbound shapes (predecessors) for a given shape."""
        previous: list[dict] = []
        for shape in self._flat_model.values():
            for pointer in shape.get("outgoing") or []:
                if not isinstance(pointer, dict):
                    continue
                rid = pointer.get("resourceId") or pointer.get("id")
                if rid == resource_id:
                    previous.append(shape)
                    break
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

            await self.upsert_token(
                idwf=idwf,
                case_id=case_id,
                resource_id=out_rid,
                type_=out_stencil,
                status="pending",
            )

    # -- Engine loop --------------------------------------------------------- #

    async def run_engine(
        self,
        idwf: str,
        idcase: str,
        max_iterations: int = 100,
    ) -> None:
        """Execute the engine loop for a case instance.

        Fetches pending/waiting tokens, dispatches each to its registered
        shape handler (or falls back to movenext), and repeats until no more
        work remains or the iteration cap is hit.

        Mirrors legacy ``Engine::Run($model, $idwf, $case)`` (L183-301).
        """
        # Validate model exists
        stmt = select(BpmModel).where(BpmModel.idwf == idwf)
        result = await self.db.execute(stmt)
        model_row = result.scalar_one_or_none()
        if model_row is None:
            return

        pending_statuses = ["pending", "waiting"]
        iteration = 0
        filter_statuses: list[str] = pending_statuses.copy()

        while iteration < max_iterations:
            iteration += 1

            # Fetch tokens matching current status filter.
            tokens = await self.get_pending_tokens(idwf, idcase, filter_statuses)
            if not tokens:
                break

            # Legacy line 278: after first pass, only look at 'pending' (not 'waiting').
            filter_statuses = ["pending"]

            for token in tokens:
                shape = await self.get_shape(token.resource_id, idwf)
                if not shape:
                    continue

                stencil_id = (shape.get("stencil") or {}).get("id", "")
                handler_cls = self._get_handler(stencil_id)
                if handler_cls:
                    instance = handler_cls()
                else:
                    await self.movenext(token.resource_id, idwf, idcase)
                    continue
                if isinstance(instance, type):
                    instance = instance()
                await instance.handle(token, shape, self)

        await self.db.flush()
        await self.db.commit()

    def _get_handler(self, stencil_id: str) -> type | None:
        """Look up a registered handler for a stencil ID.

        Imported lazily to avoid circular imports.
        """
        from app.api.bpm.engine import ENGINE_HANDLER_REGISTRY

        return ENGINE_HANDLER_REGISTRY.get(stencil_id)

    # -- Utility methods ----------------------------------------------------- #

    @staticmethod
    def _url_decode(value: str) -> str:
        """URL-decode a string (mirrors legacy PHP urldecode())."""
        from urllib.parse import unquote_plus

        return unquote_plus(value)


async def get_engine_service(
    db: AsyncSession = Depends(get_async_db),
    idwf: str | None = None,
    idcase: str | None = None,
) -> EngineService:
    """FastAPI dependency that yields a bound ``EngineService``.

    Usage in router endpoints::

        from fastapi import Depends
        @router.post("/...")
        async def endpoint(..., service: EngineService = Depends(get_engine_service)):
            ...

    The `db` parameter is resolved by FastAPI via dependency injection.
    `idwf` and `idcase` are passed from the path when available.
    """
    return await EngineService.create(db, idwf=idwf, idcase=idcase)
