"""Service layer for BpmModel CRUD operations."""

from __future__ import annotations

import copy as _copy_module
from typing import Any

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bpm_model import BpmModel
from extensions import get_async_db


class ModelService:
    """Encapsulates business logic for model persistence.

    Each method receives an already-open ``AsyncSession`` so that callers
    (FastAPI dependencies) control transaction boundaries.
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def duplicate(self, source_idwf: str, new_idwf: str) -> dict[str, Any]:
        """Clone a model to a new idwf (raw insert — no version bump)."""
        # 1. Load source
        result = await self.db.execute(
            select(BpmModel).where(BpmModel.idwf == source_idwf)
        )
        source = result.scalar_one_or_none()

        if source is None:
            return {"ok": False, "msg": f"source model '{source_idwf}' not found"}

        # 2. Check for conflict on new idwf
        check = await self.db.execute(select(BpmModel).where(BpmModel.idwf == new_idwf))
        if check.scalar_one_or_none() is not None:
            return {"ok": False, "msg": f"model '{new_idwf}' already exists"}

        # 3. Deep-copy data; strip legacy _id just in case
        data = _copy_module.deepcopy(source.data) or {}
        data.pop("_id", None)
        data["resourceId"] = new_idwf

        # 4. Persist as raw insert — no version bump, no SVG I/O
        new_model = BpmModel(
            idwf=new_idwf,
            folder=source.folder,
            version=0,
            data=data,
            created_by=source.created_by,
        )

        self.db.add(new_model)
        await self.db.flush()

        return {"ok": True, "msg": f"created id: {new_idwf}"}

    async def model_exists(self, idwf: str) -> bool:
        """Return ``True`` if a model with the given ``idwf`` exists."""
        result = await self.db.execute(
            select(BpmModel.idwf).where(BpmModel.idwf == idwf).limit(1)
        )
        return result.scalar_one_or_none() is not None


async def get_model_service(db: AsyncSession = Depends(get_async_db)):
    """FastAPI dependency that yields a bound ``ModelService``."""
    return ModelService(db)
