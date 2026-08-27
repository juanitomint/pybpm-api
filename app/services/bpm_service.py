"""BPM Service — case lifecycle helpers for subprocess orchestration.

Wraps ``gen_case`` (create child case) and ``startcase`` (clear tokens + seed
pending start tokens on a child model). These mirror the legacy PHP
``Bpm::gen_case()`` and ``Engine::Startcase()`` methods that the subprocess
handler calls to delegate work to separate child cases.

Usage is internal only — called by shape handlers, not exposed as API endpoints.
"""

from __future__ import annotations

import logging
import random
import string
from typing import Any

import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bpm_model import BpmModel
from app.models.case import BpmCase
from app.models.token import Token

logger = logging.getLogger(__name__)


async def gen_case(
    db: AsyncSession,
    idwf: str,
    parent_id: str | None = None,
    parent_data: dict[str, Any] | None = None,
) -> str:
    """Create a new child case row.

    Mirrors legacy ``Bpm::gen_case($child_idwf, $idcase, $data)`` from PHP model.

    Args:
        db: AsyncSession for DB operations.
        idwf: The child model's workflow identifier (from shape.properties.entry).
        parent_id: Parent case id — stored in ``parent_json`` column.
        parent_data: Parent case data dict — stored under ``data['parent_data']``.

    Returns:
        The new case id string (4 uppercase letters, collision-checked).
    """
    # Generate a unique 4-letter case ID with retry loop (mirrors PHP L935-961)
    for _ in range(10):
        candidate = "".join(random.choices(string.ascii_uppercase, k=4))
        stmt = select(BpmCase).where(
            BpmCase.idcase == candidate,
            BpmCase.idwf == idwf,
        )
        result = await db.execute(stmt)
        if result.scalar_one_or_none() is None:
            break
    else:
        raise RuntimeError(
            f"Could not allocate free case ID in '{idwf}' after 10 attempts"
        )

    child = BpmCase(
        idcase=candidate,
        idwf=idwf,
        status="open",
    )
    if parent_id is not None:
        child.parent_json = {"token": {}, "case": parent_id, "idwf": idwf}
    data_patch: dict[str, Any] = {}
    if parent_data is not None:
        data_patch["parent_data"] = parent_data
    case_stmt = (
        sa.update(BpmCase).where(BpmCase.idcase == candidate).values(**data_patch)
    )  # type: ignore[arg-type]
    db.add(child)
    await db.flush()
    if data_patch:
        await db.execute(case_stmt)
    logger.debug("gen_case: created child case %s for model %s", candidate, idwf)
    return candidate


async def startcase(
    db: AsyncSession,
    idwf: str,
    case_id: str,
    silent: bool = False,
) -> None:
    """Clear existing tokens on a child case and seed pending start tokens.

    Mirrors legacy ``Engine::Startcase($model, $idwf, $idcase, $silent)`` from PHP controller.

    Steps:
        1. Delete all existing tokens for (idwf, case_id).
        2. Load the child model's shape tree to find StartNoneEvent shapes.
        3. Set pending token on each start shape so engine.run can pick them up.

    Args:
        db: AsyncSession for DB operations.
        idwf: Child model identifier.
        case_id: Child case id.
        silent: If True, skip inbox message creation (used for subprocess child cases).
    """
    # Step 1: Clear existing tokens on target case
    clear_stmt = sa.delete(Token).where(
        Token.idwf == idwf,
        Token.case_id == case_id,
    )
    await db.execute(clear_stmt)

    # Step 2: Load child model to find start shapes
    stmt = select(BpmModel.data).where(BpmModel.idwf == idwf)
    result = await db.execute(stmt)
    data = result.scalar_one_or_none()

    if not data or "childShapes" not in data:
        logger.warning(
            "startcase: no shape tree for model %s — cannot seed start tokens", idwf
        )
        return

    # Step 3: Find all StartNoneEvent shapes and set pending tokens on them
    def _walk_starts(node: dict):
        if not isinstance(node, dict):
            return
        stencil = node.get("stencil") or {}
        if stencil.get("id") == "StartNoneEvent":
            rid = node.get("resourceId") or node.get("id")
            if rid:
                token = Token(
                    idwf=idwf,
                    case_id=case_id,
                    resource_id=str(rid),
                    type="StartNoneEvent",
                    status="pending",
                )
                db.add(token)

        for key in ("childShapes", "shapes"):
            children = node.get(key, []) or []
            if isinstance(children, list):
                for child in children:
                    _walk_starts(child)

    _walk_starts(data)


async def load_start_shapes(db: AsyncSession, idwf: str) -> list[dict]:
    """Find all StartNoneEvent shapes in a model's shape tree.

    Thin wrapper around engine service logic — used by subprocess handler to seed
    child cases after gen_case() creates them.

    Args:
        db: AsyncSession for DB operations.
        idwf: Model identifier.

    Returns:
        List of shape dicts (each with resourceId, stencil.id, properties).
    """
    stmt = select(BpmModel.data).where(BpmModel.idwf == idwf)
    result = await db.execute(stmt)
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
            children = node.get(key, []) or []
            if isinstance(children, list):
                for child in children:
                    _walk(child)

    _walk(data)
    return starts
