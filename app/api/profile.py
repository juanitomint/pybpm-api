"""FastAPI router for user profile endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.models.user import User
from app.schemas.user import ProfileUpdate
from app.services.profile_service import ProfileService
from extensions import get_async_db

router = APIRouter(prefix="/users", tags=["profile"])


@router.get("/profile", response_model=dict)
async def get_profile(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    svc = ProfileService(db)
    return {
        "idu": user.idu,
        "nick": user.nick,
        "name": user.name,
        "lastname": user.lastname,
        "email": user.email,
        "signature": user.signature,
        "notification_by_email": user.notification_by_email,
        "avatar": await svc.get_avatar_url(user),
    }


@router.put("/profile", response_model=dict)
async def update_profile(
    data: ProfileUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    svc = ProfileService(db)
    updated = await svc.update_profile(user.idu, data)
    return {"success": True, "user": updated}
