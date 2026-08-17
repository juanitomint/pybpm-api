import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.auth import router as auth_router
from app.api.bpm.cases import router as cases_router
from app.api.bpm.engine import router as engine_router
from app.handlers import *  # noqa: F401,F403  # triggers handler registration at import time
from app.api.bpm.repository import router as bpm_router
from app.api.bpm.tokens import router as token_manager_router
from app.api.inbox import router as inbox_router
from app.core.logging import build_uvicorn_log_config

SVG_DIR = "static/svg"


def ensure_svg_dir():
    """Create the SVG storage directory on startup if it does not exist."""
    os.makedirs(SVG_DIR, exist_ok=True)


app = FastAPI(
    title="PyBPM API",
    version="0.1.0",
    openapi_url="/openapi.json",
)


def _patch_openapi():
    """Add OAuth2 security to all routes. Silently skip if schema generation fails."""
    try:
        schema = app.openapi()
    except Exception:  # pragma: no cover — pydantic v2 forward-ref edge case
        return
    schema.setdefault("components", {})
    schema["components"].setdefault("securitySchemes", {})
    schema["components"]["securitySchemes"]["OAuth2PasswordBearer"] = {
        "type": "oauth2",
        "flows": {"password": {"scopes": {}, "tokenUrl": "/api/v1/auth/token"}},
    }
    for path, ops in schema.get("paths", {}).items():
        if path == "/api/v1/auth/token":
            continue
        for method in ("get", "post", "put", "patch", "delete"):
            op = ops.get(method)
            if not op:
                continue
            security = op.get("security") or []
            has_oauth = any(s.get("OAuth2PasswordBearer") is not None for s in security)
            if not has_oauth:
                op["security"] = [{"OAuth2PasswordBearer": []}]
    app.openapi = lambda: schema


ensure_svg_dir()

# CORS — allow local dev origins so the editor frontend can reach this API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(bpm_router)
app.include_router(engine_router)
app.include_router(cases_router)
app.include_router(token_manager_router)
app.include_router(inbox_router)  # TEMP DISABLED

_patch_openapi()


@app.get("/")
async def root():
    return {"message": "Hello from PyBPM!"}


def main():
    import uvicorn

    log_config = build_uvicorn_log_config()
    logging.config.dictConfig(log_config)

    uvicorn.run(app, host="0.0.0.0", port=5000, log_config=log_config)


if __name__ == "__main__":
    main()
