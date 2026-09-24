"""FastAPI router for RBAC endpoints."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, status
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.models.user import User
from app.services.rbac_service import RbacService
from extensions import get_async_db


class SaveGroupPathsBody(BaseModel):
    idgroup: int
    paths: list[str]
    source: str = "api"


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
    json_str = json.dumps(tree, separators=(",", ":"))
    return Response(content=json_str, media_type="application/json")


@router.post("/repository")
@router.post("/repository/root")
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


@router.put("/repository/")
@router.put("/repository/root")
async def save_repository(
    idgroup: int = Query(...),
    paths: list[str] = Query(...),
    source: str = Query("api"),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
):
    svc = RbacService(db)
    await svc.set_group_paths(idgroup, paths, source=source)


@router.delete("/repository")
async def delete_path(
    request: Request,
    db: AsyncSession = Depends(get_async_db),
):
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        body_dict = await request.json()
    else:
        form_data = await request.form()
        body_dict = dict(form_data)
    path = body_dict.get("path")
    if not path:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Missing 'path' in request body",
        )
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


@router.put("/paths")
async def save_group_paths(
    request: Request,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
):
    # Accept both JSON body and form-encoded data (Ext.Ajax.request sends params as form data)
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        body_dict = await request.json()
    else:
        form_data = await request.form()
        # Build body from FormData, handling repeated keys (e.g. multiple "paths" params)
        body_dict = {}
        for key in form_data:
            values = form_data.getlist(key)
            body_dict[key] = values if len(values) > 1 else values[0]
        # Normalize single-string paths to list
        if "paths" in body_dict and isinstance(body_dict["paths"], str):
            body_dict["paths"] = [p for p in [body_dict["paths"]] if p]

    try:
        body = SaveGroupPathsBody.model_validate(body_dict)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid request body: {exc}",
        ) from exc

    svc = RbacService(db)
    final = await svc.set_group_paths(
        body.idgroup, body.paths, source=body.source, updated_by=current_user.idu
    )
    return {"paths": final}


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

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Access denied"
        )
