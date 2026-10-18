import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncSession

from app import handlers  # triggers handler registration at import time  # noqa: F401
from app.api.admin import router as admin_router
from app.api.auth import router as auth_router
from app.api.bpm.cases import router as cases_router
from app.api.bpm.cases_rest import router as cases_rest_router
from app.api.bpm.engine import router as engine_router
from app.api.bpm.event_schedule import router as event_schedule_router
from app.api.bpm.repository import router as bpm_router
from app.api.bpm.tokens import router as token_manager_router
from app.api.dashboard import router as dashboard_router
from app.api.groups import router as groups_router
from app.api.inbox import router as inbox_router
from app.api.profile import router as profile_router
from app.api.rbac import router as rbac_router
from app.api.users import router as users_router
from app.core.logging import build_uvicorn_log_config
from app.services.rbac_service import RbacService
from extensions import _async_engine as engine

SVG_DIR = "static/svg"


def ensure_svg_dir():
    """Create the SVG storage directory on startup if it does not exist."""
    os.makedirs(SVG_DIR, exist_ok=True)


def _collect_route_paths():
    """Collect all route paths from known routers."""
    routers = [
        (auth_router, "/api/v1"),
        (bpm_router, ""),
        (engine_router, ""),
        (cases_router, ""),
        (cases_rest_router, ""),
        (token_manager_router, ""),
        (dashboard_router, ""),
        (inbox_router, ""),
        (event_schedule_router, ""),
        (admin_router, ""),
        (users_router, ""),
        (groups_router, ""),
        (rbac_router, ""),
        (profile_router, ""),
    ]
    paths = []
    for router, prefix in routers:
        for route in router.routes:
            path = getattr(route, "path", None)
            methods = getattr(route, "methods", set())
            if path:
                full = prefix + path if not path.startswith("/") else path
                paths.append((full, methods))
    return paths


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: register all endpoints in permission_repository (idempotent)
    async with AsyncSession(engine) as db:
        svc = RbacService(db)
        existing_repo = await svc.get_repository()
        existing_paths = {entry.path for entry in existing_repo}
        paths = _collect_route_paths()
        registered = 0
        for path, methods in paths:
            # Skip auth routes
            if path.startswith("/auth/"):
                continue

            # Strip /api/v1 prefix
            stripped = path
            if stripped.startswith("/api/v1"):
                stripped = stripped[7:]
            if not stripped:
                continue

            for method in methods:
                entry = f"{stripped}:{method.lower()}"
                if entry not in existing_paths:
                    await svc.put_path(entry, {"source": "autoregister"})
                    existing_paths.add(entry)
                    registered += 1
        await db.commit()
        if registered:
            logging.info(
                "[startup] Registered %d routes in permission_repository", registered
            )
    yield
    # Shutdown: no-op


app = FastAPI(
    title="PyBPM API",
    version="0.1.0",
    openapi_url="/openapi.json",
    lifespan=lifespan,
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

app.include_router(auth_router, prefix="/api/v1")
app.include_router(bpm_router)
app.include_router(engine_router)
app.include_router(cases_router)
app.include_router(cases_rest_router)
app.include_router(token_manager_router)
app.include_router(dashboard_router)
app.include_router(inbox_router)  # TEMP DISABLED
app.include_router(event_schedule_router)
app.include_router(admin_router)
app.include_router(users_router)
app.include_router(groups_router)
app.include_router(rbac_router)
app.include_router(profile_router)

_patch_openapi()


@app.get("/")
async def root():
    return {"message": "Hello from PyBPM!"}


def main():
    import uvicorn

    log_config = build_uvicorn_log_config()
    log_level = os.environ.get("LOG_LEVEL", "INFO")
    port = int(os.environ.get("APP_PORT", 5000))

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        log_config=log_config,
        log_level=log_level.lower(),
    )


if __name__ == "__main__":
    main()
