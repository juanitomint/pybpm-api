"""Populate Token.tasktype from BPMN model shape properties.

Reads every BpmModel's ``data`` JSON, walks ``childShapes`` recursively,
extracts ``properties.tasktype`` for each shape whose stencil is ``Task``,
then updates the ``tokens`` table to match.

Usage:
    uv run tools/seed_tasktype.py
"""

from __future__ import annotations

import asyncio
import sys

import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from extensions import async_session_factory


def _extract_tasktypes(data: dict, result: dict[str, str] | None = None) -> dict[str, str]:
    """Recursively walk childShapes and collect resourceId -> tasktype."""
    if result is None:
        result = {}

    def _walk(node):
        if not isinstance(node, dict):
            return
        props = node.get("properties") or {}
        stencil = (node.get("stencil") or {}).get("id", "")
        rid = node.get("resourceId", "")

        if stencil == "Task" and rid and props.get("tasktype"):
            result[rid] = str(props["tasktype"])

        for child in node.get("childShapes") or []:
            _walk(child)

    _walk(data)
    return result


async def seed(db: AsyncSession):
    """Populate Token.tasktype from all stored BpmModel data."""
    from app.models.bpm_model import BpmModel
    from app.models.token import Token

    stmt = select(BpmModel.idwf, BpmModel.data)
    result = await db.execute(stmt)
    rows = result.all()

    # Build resource_id -> tasktype map across all models
    tasktype_map: dict[str, str] = {}
    models_with_tasks: dict[str, dict[str, str]] = {}

    for row in rows:
        idwf: str = row.idwf
        data: dict | None = row.data
        if not data or not isinstance(data, dict):
            continue

        shape_map = _extract_tasktypes(data)
        if shape_map:
            models_with_tasks[idwf] = shape_map
            tasktype_map.update(shape_map)

    if not tasktype_map:
        print("[seed_tasktype] No task shapes found in any model.")
        return

    print(f"[seed_tasktype] Found {len(tasktype_map)} unique task shapes across {len(models_with_tasks)} models")

    # Update tokens that have a matching resourceId
    update_stmt = (
        sa.update(Token)
        .where(Token.resource_id.in_(tasktype_map.keys()))
        .values(tasktype=sa.case(
            *(
                (Token.resource_id == rid, tt)
                for rid, tt in tasktype_map.items()
            ),
            else_=None,
        ))
    )
    result = await db.execute(update_stmt)
    await db.commit()

    updated = result.rowcount if hasattr(result, "rowcount") else "?"
    print(f"[seed_tasktype] Updated {updated} tokens with tasktype values")

    # Summary by model
    for idwf, shape_map in sorted(models_with_tasks.items()):
        task_count = len(shape_map)
        types = set(shape_map.values())
        print(f"  {idwf}: {task_count} tasks, types={sorted(types)}")


async def main():
    async with async_session_factory() as db:
        await seed(db)


if __name__ == "__main__":
    asyncio.run(main())
