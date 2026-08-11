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

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bpm_model import BpmModel
from app.models.case import BpmCase
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
        self, idwf: str, case_id: str, resource_id: str, type_: str, status: str = "pending"
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

    async def get_token(self, idwf: str, case_id: str, resource_id: str) -> Token | None:
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
    ) -> list[Token]:
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
        token.updated_at = datetime.now(timezone.utc)
        await self.db.flush()

        # Record in history table
        history = TokenHistory(
            idwf=token.idwf,
            case_id=token.case_id,
            resource_id=token.resource_id,
            type=token.type,
            status="finished",
            check_date=datetime.now(timezone.utc),
            run_count=token.run_count,
        )
        self.db.add(history)

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
            if isinstance(stencil, dict) and "start" in str(stencil.get("id", "")).lower():
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
