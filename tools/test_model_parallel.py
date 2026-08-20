#!/usr/bin/env python3
"""Load all model fixtures concurrently to stress-test the DB layer.

Each fixture is inserted in its own async task via ``asyncio.gather`` so every
row is written simultaneously — exercises any race conditions in constraints,
auto-incrementing sequences, or session/transaction handling.

Does NOT delete anything on success or failure. Idempotent: existing idwf rows
are skipped per-insertion rather than aborted at the top.
"""

from __future__ import annotations

import asyncio
import json
import pathlib
import sys
import time
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

BASE = pathlib.Path(__file__).parent
FIXTURES_DIR = BASE / "files" / "images" / "model"


async def load_one(path: pathlib.Path) -> tuple[str, bool | str]:
    """Insert one fixture into the DB. Returns (idwf, True|error_str)."""

    from app.models.bpm_model import BpmModel
    from extensions import async_session_factory

    try:
        payload = json.loads(path.read_text())
    except Exception as exc:  # noqa: BLE001 — parse errors are not security-related
        return path.stem, f"parse error: {exc}"

    idwf = payload.get("resourceId", path.stem.replace(" ", "_"))

    try:
        async with async_session_factory() as db:
            existing = await db.execute(
                select(BpmModel).where(BpmModel.idwf == idwf)
            )
            if existing.scalar_one_or_none() is not None:
                return idwf, True  # already there

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
            await db.commit()

        return idwf, True
    except SQLAlchemyError as exc:  # noqa: BLE001 — DB errors are not security-related
        return idwf, f"DB error: {exc}"


async def main():
    paths = sorted(FIXTURES_DIR.iterdir())
    if not paths:
        print(f"[parallel] no fixtures under {FIXTURES_DIR}", file=sys.stderr)
        sys.exit(1)

    # Filter to JSON files (by content, since some lack .json extension)
    json_paths: list[pathlib.Path] = []
    for p in paths:
        if not p.is_file():
            continue
        try:
            json.loads(p.read_text())
            json_paths.append(p)
        except Exception:  # noqa: BLE001
            pass

    json_paths.sort(key=lambda x: x.name)

    print(f"[parallel] {len(json_paths)} fixtures, loading concurrently")
    t0 = time.perf_counter()

    results = await asyncio.gather(
        *(load_one(p) for p in json_paths), return_exceptions=True
    )

    elapsed = time.perf_counter() - t0

    successes: list[str] = []
    failures: list[tuple[str, str]] = []

    for path, result in zip(json_paths, results):
        name = path.name
        if isinstance(result, Exception):
            failures.append((name, f"exception: {result}"))
            print(f"  ERR  {name}")
        elif isinstance(result, tuple) and len(result) == 2:
            idwf, status = result
            if status is True:
                successes.append(name)
                print(f"  OK   {name} -> idwf={idwf}")
            else:
                failures.append((name, str(status)))
                print(f"  ERR  {name}: {status}")
        else:
            failures.append((name, f"unexpected result: {result!r}"))

    print(
        f"\n[parallel] done in {elapsed:.3f}s — "
        f"{len(successes)}/{len(json_paths)} loaded, {len(failures)} failed"
    )
    if failures:
        for name, err in failures:
            print(f"  - {name}: {err}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
