import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.bpm import router as bpm_router

SVG_DIR = "static/svg"


def ensure_svg_dir():
    """Create the SVG storage directory on startup if it does not exist."""
    os.makedirs(SVG_DIR, exist_ok=True)


app = FastAPI(title="PyBPM API", version="0.1.0")

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


app.include_router(bpm_router)


@app.get("/")
async def root():
    return {"message": "Hello from PyBPM!"}


def main():
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=5000)


if __name__ == "__main__":
    main()
