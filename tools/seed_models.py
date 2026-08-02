"""Seed the bpm_models table from the JSON fixtures under files/images/model/.

Uses SQLAlchemy directly (no HTTP, no auth) so it can run without Step 1's
save endpoint being implemented. Inserts each fixture as a fresh model row at
version=0 with created_by=NULL.
"""

from __future__ import annotations

import asyncio
import json
import pathlib
import sys
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

BASE = pathlib.Path(__file__).parent
FIXTURES_DIR = BASE / "files" / "images" / "model"


async def seed(db: AsyncSession):
    from app.models.bpm_model import BpmModel

    paths = sorted(p for p in FIXTURES_DIR.glob("*.json"))
    print(f"[seed] {len(paths)} fixtures to load")

    successes, failures = 0, []
    for path in paths:
        payload = json.loads(path.read_text())
        idwf = payload.get("resourceId") or path.stem.replace(" ", "_")

        try:
            existing = await db.execute(select(BpmModel).where(BpmModel.idwf == idwf))
            if existing.scalar_one_or_none() is not None:
                print(f"  SKIP {path.name} -> idwf={idwf} (already exists)")
                continue

            now = datetime.now(UTC)
            model = BpmModel(
                idwf=idwf,
                folder="General",
                version=0,
                data=payload,
                created_at=now,
                updated_at=now,
            )
            db.add(model)
            await db.flush()
            print(f"  OK   {path.name} -> idwf={idwf}")
            successes += 1
        except Exception as exc:
            print(f"  ERR  {path.name} -> idwf={idwf}: {exc}")
            failures.append((str(path.name), str(exc)))

    await db.commit()
    print(f"\n[seed] done. {successes}/{len(paths)} loaded, {len(failures)} failed")
    if failures:
        for name, err in failures:
            print(f"  - {name}: {err}")
        sys.exit(1)


async def main():
    from extensions import async_session_factory

    async with async_session_factory() as db:
        await seed(db)


if __name__ == "__main__":
    asyncio.run(main())
