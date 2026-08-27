#!/usr/bin/env python3
"""Reusable CLI entry point to exercise any BPMN model through the live engine.

Usage:
    .venv/bin/python scripts/test_model.py <idwf> [--no-import]

Reads Config from config.py (all env vars), generates its own JWT for auth,
and drives the engine endpoints end-to-end. No new dependencies — uses only
existing packages already in pybpm-api's uv lock file.

The API server must be running on port 5000 (default). Override with:
    API_BASE_URL=http://host:port .venv/bin/python scripts/test_model.py <idwf>
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import argparse
import asyncio
import datetime as dt
import json

import httpx
from jose import jwt
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bpm_model import BpmModel
from app.models.token import Token, TokenHistory
from config import Config
from extensions import async_session_factory

MAX_POST_ITERATIONS = 10

DEFAULT_API_BASE = "http://localhost:5000"

STENCIL_LABELS = {
    "StartNoneEvent": "Start",
    "EndNoneEvent": "End",
    "ParallelGateway": "Gateway",
    "ExclusiveGateway": "Gateway",
    "Task": "User Task",
    "ServiceTask": "Service Task",
    "ScriptTask": "Script Task",
    "SendTask": "Send Task",
}

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def get_api_base() -> str:
    return getattr(Config, "API_BASE_URL", None) or DEFAULT_API_BASE


def create_admin_token() -> str:
    """Generate a JWT for the admin user (idu=1). Mirrors auth._create_token."""
    expire = dt.datetime.now(dt.UTC) + dt.timedelta(hours=Config.JWT_EXPIRATION_HOURS)
    payload = {"sub": "1", "exp": expire, "iat": dt.datetime.now(dt.UTC)}
    return jwt.encode(payload, Config.SECRET_KEY, algorithm="HS256")


def stencil_label(stencil_id: str) -> str:
    return STENCIL_LABELS.get(stencil_id, stencil_id)


# --------------------------------------------------------------------------- #
# Step 1 — Ensure model is in DB
# --------------------------------------------------------------------------- #


async def ensure_model_in_db(idwf: str) -> bool:
    """Return True if the model was loaded (False = already present)."""
    async with async_session_factory() as session:
        result = await session.execute(select(BpmModel).where(BpmModel.idwf == idwf))
        existing = result.scalar_one_or_none()

    if existing is not None:
        print(
            f"[model] already present in DB (idwf={idwf}, version={existing.version})"
        )
        return False

    candidates = [Path("files/images/model", f"{idwf}.json"), Path(idwf + ".json")]
    source = next((c for c in candidates if c.is_file()), None)

    if source is None:
        print(f"[model] ERROR: no JSON file found for idwf={idwf}")
        sys.exit(1)

    try:
        data = json.loads(source.read_text())
    except json.JSONDecodeError as exc:
        print(f"[model] ERROR: failed to parse {source}: {exc}")
        sys.exit(1)

    if "resourceId" not in data and "stencil" not in data:
        print(
            "[model] WARNING: file doesn't look like a BPMN diagram; importing anyway"
        )

    async with async_session_factory() as session:
        model = BpmModel(
            idwf=idwf, folder="General", version=0, data=data, created_by=1
        )
        session.add(model)
        await session.commit()

    print(f"[model] loaded from {source} (idwf={idwf})")
    return True


# --------------------------------------------------------------------------- #
# Step 2-8 — HTTP-driven engine flow + DB-based inspection
# --------------------------------------------------------------------------- #


async def _fetch_tokens(session: AsyncSession, idwf: str, case_id: str) -> list[Token]:
    result = await session.execute(
        select(Token).where(and_(Token.idwf == idwf, Token.case_id == case_id))
    )
    return list(result.scalars().all())


async def _fetch_history(
    session: AsyncSession, idwf: str, case_id: str
) -> list[TokenHistory]:
    result = await session.execute(
        select(TokenHistory).where(
            and_(TokenHistory.idwf == idwf, TokenHistory.case_id == case_id)
        )
    )
    return list(result.scalars().all())


async def _print_token_summary(
    tokens: list[Token], history: list[TokenHistory]
) -> None:
    if not tokens:
        print("\n[inspect] No active tokens found\n")
        return

    shape_counts: dict[str, dict[str, int]] = {}
    for t in tokens:
        label = stencil_label(t.type)
        shape_counts.setdefault(label, {}).setdefault(t.status, 0)
        shape_counts[label][t.status] += 1

    print("\n[summary] Shape class              Count    Status breakdown")
    print("-" * 65)
    for label in sorted(shape_counts):
        counts = shape_counts[label]
        total = sum(counts.values())
        status_str = ", ".join(f"{s}={c}" for s, c in sorted(counts.items()))
        note = ""
        if "finished" not in counts and any(
            k in counts for k in ["pending", "waiting", "user"]
        ):
            note = "  ← NOT REACHED"
        print(f"{label:<25} {total:>5}    {status_str}{note}")

    if history:
        hit_stencils = sorted({h.type for h in history})
        print(f"\n[history] Shapes hit during this run: {', '.join(hit_stencils)}")
    else:
        print("\n[history] No history records found.")


async def run_engine_test(
    idwf: str, token: str, headers: dict[str, str], post_all: bool = False
) -> int:
    """Drive the full case lifecycle. Returns 0 on success, 1 on failure."""
    api_base = get_api_base()

    # --- Create case -------------------------------------------------------- #
    print(f"\n[create] POST {api_base}/bpm/engine/newcase")
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{api_base}/bpm/engine/newcase",
            json={"idwf": idwf},
            headers=headers,
        )
    if resp.status_code != 201:
        print(f"ERROR: newcase returned {resp.status_code}: {resp.text}")
        return 1
    idcase = str(resp.json()["idcase"])
    print(f"[info] Created case idcase={idcase}")
    print("[create] OK\n")

    # --- Start case --------------------------------------------------------- #
    print(f"[start] POST {api_base}/bpm/engine/start")
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{api_base}/bpm/engine/start",
            json={"idwf": idwf, "idcase": idcase},
            headers=headers,
        )
    if resp.status_code != 200:
        print(f"ERROR: start returned {resp.status_code}: {resp.text}")
        return 1
    tokens_created = resp.json().get("tokens_created", 0)
    print(f"[start] OK — tokens_created={tokens_created}\n")

    if tokens_created == 0:
        async with async_session_factory() as session:
            tokens = await _fetch_tokens(session, idwf, idcase)
            history = await _fetch_history(session, idwf, idcase)
        print("[warn] No start shapes found in model. Some models are partial.")
        await _print_token_summary(tokens, history)
        return 0

    # --- Engine loop (optional auto-POST) ---------------------------------- #
    iteration = 0
    while True:
        iteration += 1
        print(
            f"[run] Iteration {iteration}: POST {api_base}/bpm/engine/run/{idwf}/{idcase}"
        )
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{api_base}/bpm/engine/run/{idwf}/{idcase}",
                headers=headers,
            )
        if resp.status_code != 200:
            print(f"ERROR: run returned {resp.status_code}: {resp.text}")
            return 1

        # Check for user-task tokens via DB and complete them.
        if post_all and iteration <= MAX_POST_ITERATIONS:
            async with async_session_factory() as session:
                result = await session.execute(
                    select(Token).where(
                        and_(
                            Token.idwf == idwf,
                            Token.case_id == idcase,
                            Token.status == "user",
                        )
                    )
                )
                user_tokens = list(result.scalars().all())
            if user_tokens:
                print(
                    f"[task] Found {len(user_tokens)} user-task token(s), completing..."
                )
                async with httpx.AsyncClient() as client:
                    for ut in user_tokens:
                        task_resp = await client.post(
                            f"{api_base}/bpm/engine/task/{idwf}/{idcase}/{ut.resource_id}",
                            json={"data": {}, "action": "complete"},
                            headers=headers,
                        )
                        if task_resp.status_code == 200:
                            print(f"[task] {ut.resource_id}: completed")
                        else:
                            print(
                                f"[task] {ut.resource_id}: failed ({task_resp.status_code}) — {task_resp.text}"
                            )
                continue
        break

    # --- Final inspection (via DB) ------------------------------------------ #
    async with async_session_factory() as session:
        tokens = await _fetch_tokens(session, idwf, idcase)
        history = await _fetch_history(session, idwf, idcase)
    return 0


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #

_token_cache: str = ""
_headers: dict[str, str] = {}


async def _async_main(idwf: str, do_import: bool, post_all: bool) -> int:
    if do_import:
        await ensure_model_in_db(idwf)
    else:
        print("[skip] Skipping import\n")
    return await run_engine_test(idwf, _token_cache, _headers, post_all=post_all)


def main():
    parser = argparse.ArgumentParser(
        description="Exercise a BPMN model through the live engine."
    )
    parser.add_argument(
        "idwf", help="Workflow id (matches files/images/model/<idwf>.json)"
    )
    parser.add_argument(
        "--import-models",
        action="store_true",
        help="Load model JSON from files/images/model/<idwf>.json into the DB before running.",
    )
    parser.add_argument(
        "--post-all-tasks",
        action="store_true",
        help="Auto-complete user-task tokens until idle or 10 iterations.",
    )
    args = parser.parse_args()

    if not Config.SECRET_KEY or "fallback" in Config.SECRET_KEY.lower():
        print("[error] SECRET_KEY is not configured. Set the SECRET_KEY env var.")
        sys.exit(1)

    global _token_cache, _headers
    _token_cache = create_admin_token()
    _headers = {"Authorization": f"Bearer {_token_cache}"}
    print(
        f"[auth] Admin JWT generated (idu=1, expires in {Config.JWT_EXPIRATION_HOURS}h)\n"
    )

    exit_code = asyncio.run(
        _async_main(args.idwf, args.import_models, args.post_all_tasks)
    )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
