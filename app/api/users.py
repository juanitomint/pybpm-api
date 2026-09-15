"""FastAPI router for admin user management endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.user import UserCreate, UserRead, UserUpdate
from app.services.user_service import UserService
from extensions import get_async_db

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=list[UserRead])
async def list_users(
    skip: int = 0,
    limit: int = 50,
    query: str | None = None,
    idgroup: int | None = None,
    db: AsyncSession = Depends(get_async_db),
):
    svc = UserService(db)
    users, _ = await svc.get_users(skip, limit, query, idgroup)
    return users


@router.get("/count")
async def count_users(
    query: str | None = None,
    idgroup: int | None = None,
    db: AsyncSession = Depends(get_async_db),
):
    svc = UserService(db)
    return {"count": await svc.get_user_count(query, idgroup)}


@router.get("/{idu}", response_model=UserRead)
async def get_user(
    idu: int,
    db: AsyncSession = Depends(get_async_db),
):
    svc = UserService(db)
    user = await svc.get_user(idu)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


@router.post("", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def create_user(
    data: UserCreate,
    db: AsyncSession = Depends(get_async_db),
):
    svc = UserService(db)
    return await svc.create_user(data)


@router.put("/{idu}", response_model=UserRead)
async def update_user(
    idu: int,
    data: UserUpdate,
    db: AsyncSession = Depends(get_async_db),
):
    svc = UserService(db)
    user = await svc.update_user(idu, data)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


@router.delete("/{idu}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    idu: int,
    db: AsyncSession = Depends(get_async_db),
):
    svc = UserService(db)
    if not await svc.delete_user(idu):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return None
