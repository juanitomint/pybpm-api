"""Service layer for BpmModel CRUD operations."""

from __future__ import annotations

import copy as _copy_module
import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bpm_model import BpmModel
from extensions import get_async_db

SVG_DIR = Path(__file__).parent.parent.parent / "static" / "svg"
MODEL_DIR = SVG_DIR.parent / "model"
ZIP_DIR = SVG_DIR.parent / "zip"


class ModelService:
    """Encapsulates business logic for model persistence.

    Each method receives an already-open ``AsyncSession`` so that callers
    (FastAPI dependencies) control transaction boundaries.
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def save(
        self,
        idwf: str,
        data: dict[str, Any],
        svg: str | None = None,
    ) -> tuple[BpmModel, bool]:
        """Save a model (upsert). Bumps version on update; writes SVG to disk.

        Returns ``(model, was_created)`` — ``was_created`` is True for inserts,
        False for updates. The caller maps this to 201/200.
        """
        now = datetime.now(UTC)
        data["properties"] = data.get("properties") or {}
        data["properties"]["modificationdate"] = now.strftime("%Y-%m-%dT%H:%M:%S")

        if svg is not None:
            SVG_DIR.mkdir(parents=True, exist_ok=True)
            (SVG_DIR / f"{idwf}.svg").write_text(svg, encoding="utf-8")

        stmt = select(BpmModel).where(BpmModel.idwf == idwf)
        existing = await self.db.execute(stmt)
        model = existing.scalar_one_or_none()

        was_created = False
        if model is None:
            model = BpmModel(
                idwf=idwf,
                folder="General",
                version=1,
                data=data,
                created_at=now,
                updated_at=now,
            )
            self.db.add(model)
            was_created = True
        else:
            model.data = data
            model.version += 1
            model.updated_at = now

        await self.db.flush()
        await self.db.commit()
        return model, was_created

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
        await self.db.commit()

        return {"ok": True, "msg": f"created id: {new_idwf}"}

    async def model_exists(self, idwf: str) -> bool:
        """Return ``True`` if a model with the given ``idwf`` exists."""
        result = await self.db.execute(
            select(BpmModel.idwf).where(BpmModel.idwf == idwf).limit(1)
        )
        return result.scalar_one_or_none() is not None

    def _write_model_file(self, idwf: str, data: dict[str, Any]) -> Path:
        """Write the model JSON payload to ``static/model/{idwf}.json``."""
        MODEL_DIR.mkdir(parents=True, exist_ok=True)
        path = MODEL_DIR / f"{idwf}.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def _create_zip(
        self, idwf: str, data: dict[str, Any], svg_path: Path | None
    ) -> Path:
        """Create a zip archive containing the model JSON + optional SVG.

        Mirrors legacy ``Bpm::zip_model`` — only adds files that actually exist
        on disk so an unsaved thumbnail or missing svg doesn't blow up the call.
        """
        ZIP_DIR.mkdir(parents=True, exist_ok=True)
        zip_path = ZIP_DIR / f"{idwf}.zip"

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(f"images/model/{idwf}.json", json.dumps(data))
            if svg_path is not None and svg_path.exists():
                zf.write(svg_path, f"images/svg/{idwf}.svg")
        return zip_path

    async def save_model(
        self, idwf: str, data: dict[str, Any], svg: str | None = None
    ) -> tuple[BpmModel, Path, Path]:
        """Save a model with the editor's "save" contract (data + svg POST).

        The Oryx editor ships ``data`` (BPMN JSON) and ``svg`` (graphical
        representation) together. We persist both — row upsert via :meth:`save`
        plus auxiliary artefacts (model JSON file + zip archive), mirroring the
        legacy ``Bpm::save`` behaviour.

        Returns ``(model, model_file_path, zip_path)`` so the caller can report
        which artefacts were produced.
        """
        # 1. Persist row + write SVG to disk (via shared ``save``).
        model, _was_created = await self.save(idwf, data, svg=svg)

        # 2. Auxiliary artefacts: model JSON + zip archive
        model_file = self._write_model_file(idwf, data)
        svg_path = SVG_DIR / f"{idwf}.svg" if svg else None
        zip_path = self._create_zip(idwf, data, svg_path)

        return model, model_file, zip_path


async def get_model_service(db: AsyncSession = Depends(get_async_db)):
    """FastAPI dependency that yields a bound ``ModelService``."""
    return ModelService(db)
