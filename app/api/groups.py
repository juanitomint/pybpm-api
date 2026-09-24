"""FastAPI router for admin group management endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.user import GroupCreate, GroupRead, GroupUpdate
from app.services.group_service import GroupService
from extensions import get_async_db

router = APIRouter(prefix="/groups", tags=["groups"])


@router.get("")
async def list_groups(
    query: str | None = None,
    page: int = Query(1, ge=1),
    start: int = Query(0, ge=0),
    limit: int = Query(25, ge=1, le=100),
    sort: str | None = None,
    db: AsyncSession = Depends(get_async_db),
) -> dict[str, Any]:
    """List groups with pagination and sorting.

    Returns ExtJS-compatible format: {"rows": [...], "totalCount": N}
    """
    svc = GroupService(db)
    groups, total = await svc.get_groups(
        query=query,
        page=page,
        start=start,
        limit=limit,
        sort=sort,
    )
    return {
        "rows": [GroupRead.model_validate(g).model_dump() for g in groups],
        "totalCount": total,
    }


@router.get("/count")
async def count_groups(
    query: str | None = None,
    db: AsyncSession = Depends(get_async_db),
):
    svc = GroupService(db)
    _, count = await svc.get_groups(query)
    return {"count": count}


@router.get("/{idgroup}", response_model=GroupRead)
async def get_group(
    idgroup: int,
    db: AsyncSession = Depends(get_async_db),
):
    svc = GroupService(db)
    group = await svc.get_group(idgroup)
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Group not found"
        )
    return group


@router.post("", response_model=GroupRead, status_code=status.HTTP_201_CREATED)
async def create_group(
    data: GroupCreate,
    db: AsyncSession = Depends(get_async_db),
):
    svc = GroupService(db)
    return await svc.create_group(data)


@router.put("/{idgroup}", response_model=GroupUpdate)
async def update_group(
    idgroup: int,
    data: GroupUpdate,
    db: AsyncSession = Depends(get_async_db),
):
    svc = GroupService(db)
    group = await svc.update_group(idgroup, data)
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Group not found"
        )
    return group


@router.delete("/{idgroup}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_group(
    idgroup: int,
    db: AsyncSession = Depends(get_async_db),
):
    svc = GroupService(db)
    if not await svc.delete_group(idgroup):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Group not found"
        )
    return None
