"""FastAPI router for generic admin endpoints."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/health")
async def health_check():
    """Health check endpoint for admin."""
    return {"status": "ok"}
