#!/usr/bin/env python3
"""Post the raw Oryx save payload (from files/raw/testo.raw) to /bpm/repository/save/{idwf}.

Usage:
    uv run python tools/test_save_raw.py [--url http://localhost:5000] [--idwf my-model-id]

The script:
  1. Reads ``files/raw/testo.raw`` and URL-decodes its form fields.
  2. Logs in via POST /api/v1/auth/token with env vars ADMIN_USER / ADMIN_PASS
     (defaults to admin/admin).
  3. PUTs the decoded payload as urlencoded form data to /bpm/repository/save/{idwf}
     with a Bearer token from step 2.
"""

from __future__ import annotations

import sys
import urllib.parse
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]  # project root (above pybpm/)
RAW_FILE = ROOT / "pybpm" / "files" / "raw" / "testo.raw"


def decode_raw_payload(path: Path) -> dict[str, str]:
    """Read the raw file and url-decode each ``key=value`` pair."""
    text = path.read_text(encoding="utf-8")
    # The raw file may contain multiple form fields separated by '&'. Some
    # values themselves contain unescaped '&' so we split on '&', then decode
    # each chunk independently. This matches how PHP's $_POST parses it.
    pairs: list[tuple[str, str]] = []
    buf = ""
    for ch in text:
        if ch == "&":
            if buf.strip():
                pairs.append(tuple(buf.split("=", 1)))
            buf = ""
        else:
            buf += ch
    if buf.strip():
        key, _, value = buf.partition("=")
        pairs.append((key, value))

    decoded = {}
    for k, v in pairs:
        decoded[urllib.parse.unquote_plus(k)] = urllib.parse.unquote_plus(v)
    return decoded


async def login(url: str, username: str, password: str) -> str | None:
    """Authenticate and return a bearer token."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{url}/api/v1/auth/token",
            data={"username": username, "password": password},
        )
        if resp.status_code != 200:
            print(f"[login] {resp.status_code} — {resp.text[:200]}")
            return None
        return resp.json()["access_token"]


async def post_save(url: str, token: str, payload: dict[str, str]) -> httpx.Response:
    """PUT the decoded raw payload to /bpm/repository/save/{idwf}."""
    import json as _json

    data_field = payload.get("data", "{}")
    try:
        data_obj = (
            _json.loads(data_field) if isinstance(data_field, str) else data_field
        )
        idwf = data_obj.get("resourceId", "unknown")
    except (ValueError, TypeError):
        idwf = "unknown"

    url_path = f"{url}/bpm/repository/save/{urllib.parse.quote_plus(idwf)}"
    async with httpx.AsyncClient() as client:
        return await client.put(
            url_path,
            data=payload,
            headers={"Authorization": f"Bearer {token}"},
        )


async def main(url: str) -> int:
    if not RAW_FILE.exists():
        print(f"[error] raw payload not found at {RAW_FILE}")
        return 2

    fields = decode_raw_payload(RAW_FILE)
    print(f"[raw] decoded {len(fields)} field(s): {list(fields.keys())}")

    username = sys.environ.get("ADMIN_USER", "admin")
    password = sys.environ.get("ADMIN_PASS", "admin")
    token = await login(url, username, password)
    if not token:
        print("[error] authentication failed — set ADMIN_USER / ADMIN_PASS")
        return 1

    resp = await post_save(url, token, fields)
    print(f"[save] {resp.status_code} {resp.text[:500]}")
    return 0 if resp.is_success else 1


if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:5000"
    import asyncio

    raise SystemExit(asyncio.run(main(url)))
