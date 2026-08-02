import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.auth import router as auth_router
from app.api.bpm.repository import router as bpm_router

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
    schema = app.openapi()
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

if os.path.isdir("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")


app.include_router(auth_router)
app.include_router(bpm_router)

_patch_openapi()


@app.get("/")
async def root():
    return {"message": "Hello from PyBPM!"}


def main():
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=5000)


if __name__ == "__main__":
    main()
