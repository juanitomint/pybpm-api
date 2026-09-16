"""FastAPI router for RBAC endpoints."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, status
from fastapi.responses import Response
from app.api.auth import get_current_user
from app.models.user import User
from app.services.rbac_service import RbacService
from extensions import get_async_db

router = APIRouter(prefix="/rbac", tags=["rbac"])


@router.get("/repository")
@router.get("/repository/root")
async def get_repository(
    node: str | None = Query(default=None),
    sort: str | None = Query(default=None),
    db: AsyncSession = Depends(get_async_db),
):
    svc = RbacService(db)
    tree = await svc.get_tree(node=node, sort=sort)
    # Match legacy PHP json_encode() default (escaped slashes); wrap under
    # Ext JS Ajax proxy expects data at response["data"]
    json_str = json.dumps({"data": tree}, separators=(",", ":"))
    return Response(content=json_str, media_type="application/json")

@router.post("/repository")
async def read_repository(
    request: Request,
    node: str | None = Form(default=None),
    sort: str | None = Form(default=None),
    db: AsyncSession = Depends(get_async_db),
):
    svc = RbacService(db)
    tree = await svc.get_tree(node=node, sort=sort)
    json_str = json.dumps({"data": tree}, separators=(",", ":"))
    return Response(content=json_str, media_type="application/json")

@router.put("/repository")
async def save_repository(
    idgroup: int = Query(...),
    paths: list[str] = Query(...),
    source: str = Query("api"),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
):
    svc = RbacService(db)
    final = await svc.set_group_paths(idgroup, paths, source=source)


@router.delete("/repository")
async def delete_path(
    path: str = Query(...),
    db: AsyncSession = Depends(get_async_db),
):
    svc = RbacService(db)
    success = await svc.remove_path(path)
    return {"success": success}


@router.get("/paths")
async def get_group_paths(
    idgroup: int = Query(...),
    db: AsyncSession = Depends(get_async_db),
):
    svc = RbacService(db)
    paths = await svc.get_group_paths(idgroup)
    return {"paths": paths}


class RbacDependency:
    """FastAPI dependency that checks RBAC before allowing access.

    Args:
        required_path: exact API path to check (e.g. "/bpm/engine/execute").
            If None, checks admin only.
    """

    def __init__(self, required_path: str | None = None):
        self.required_path = required_path

    async def __call__(
        self,
        user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_async_db),
    ) -> User:
        # Admin bypass
        if await user.is_admin(db):
            return user

        # Path-based check
        if self.required_path and await user.has_path(db, self.required_path):
            return user

        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
