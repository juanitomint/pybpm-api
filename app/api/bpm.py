"""FastAPI router for BPM model endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from sqlalchemy import delete as sa_delete
from sqlalchemy import select

from app.core.auth import get_current_user
from app.models.bpm_model import BpmModel
from app.models.user import User
from app.schemas.repository import (
    CheckResponse,
    CommentsResponse,
    DumpResponse,
    FolderUpdate,
    ModelCreate,
    ModelDuplicateRequest,
    ModelRead,
    ModelUpdate,
    SaveAsRequest,
    SaveModelRequest,
    SaveResponse,
    ScriptRequest,
    ShapesResponse,
)
from app.services.model_service import ModelService, get_model_service

router = APIRouter(prefix="/api/v1/models", tags=["models"])


# -- Step 2: duplicate -------------------------------------------------------- #


@router.post(
    "/{idwf}/duplicate",
    response_model=SaveResponse,
    status_code=status.HTTP_201_CREATED,
)
async def duplicate(
    idwf: str,
    body: ModelDuplicateRequest,
    user: User = Depends(get_current_user),
    service: ModelService = Depends(get_model_service),
):
    """Clone a model to a new ``idwf`` (raw insert — no version bump).

    Returns 201 on success, 409 if the target idwf is already taken.
    Source-not-found returns 404 via FastAPI's default exception handler.
    """
    result = await service.duplicate(idwf, body.new_idwf)

    if not result["ok"]:
        raise _conflict_or_not_found(result["msg"])

    return SaveResponse(ok=result["ok"], msg=result["msg"])


def _conflict_or_not_found(msg: str):  # type: ignore[misc]
    """Map service-level messages to the appropriate HTTP exception."""
    if "not found" in msg.lower():
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=msg)
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=msg)


# -- Stubs for future steps (1–16) ------------------------------------------- #
# Each endpoint below is a placeholder that will be replaced with full logic
# when its corresponding step is implemented. They require auth and return
# 501 Not Implemented so the router shape is stable across all steps.


@router.post(
    "/",
    status_code=status.HTTP_201_CREATED,
)
async def add(
    body: ModelCreate,
    user: User = Depends(get_current_user),
):
    raise NotImplementedError("Step 4 — create scaffold not yet implemented")


@router.put("/{idwf}", response_model=ModelRead)
async def save(
    idwf: str,
    body: ModelUpdate,
    user: User = Depends(get_current_user),
    service: ModelService = Depends(get_model_service),
):
    """Save or update a model. Bumps version on update; writes SVG to disk."""
    # Strip legacy _id just in case the editor sends it along with data
    body.data.pop("_id", None)

    model, was_created = await service.save(idwf, body.data, svg=body.svg)
    status = 201 if was_created else 200
    return JSONResponse(
        content=ModelRead.model_validate(model).model_dump(mode="json"),
        status_code=status,
    )


@router.post("/save-as")
async def save_as(
    body: SaveAsRequest,
    user: User = Depends(get_current_user),
):
    raise NotImplementedError("Step 3 — save-as not yet implemented")


@router.get("/check/{idwf}", response_model=CheckResponse)
async def check_model(idwf: str, service: ModelService = Depends(get_model_service)):
    exists = await service.model_exists(idwf)
    return SaveResponse(ok=not exists, msg="" if not exists else "idwf already taken")


@router.delete("/{idwf}", response_model=SaveResponse)
async def delete(
    idwf: str,
    user: User = Depends(get_current_user),
    service: ModelService = Depends(get_model_service),
):
    stmt = sa_delete(BpmModel).where(BpmModel.idwf == idwf)
    result = await service.db.execute(stmt)
    if result.rowcount == 0:
        return SaveResponse(ok=False, msg=f"model '{idwf}' not found")
    await service.db.commit()
    return SaveResponse(ok=True, msg=f"deleted id: {idwf}")


@router.get("/{idwf}", response_class=JSONResponse)
async def load(
    idwf: str,
    user: User = Depends(get_current_user),
    service: ModelService = Depends(get_model_service),
):
    """Load full model data. Falls back to template if `data` is empty."""
    result = await service.db.execute(select(BpmModel).where(BpmModel.idwf == idwf))
    model = result.scalar_one_or_none()
    if model is None:
        raise HTTPException(status_code=404, detail=f"model '{idwf}' not found")

    data = model.data or {
        "resourceId": idwf,
        "stencilset": {
            "url": "../../jscript/bpm-dna2/stencilsets/bpmn2.0/bpmn2.0_2.json",
            "namespace": "http://b3mn.org/stencilset/bpmn2.0#",
        },
        "stencil": {"id": "BPMNDiagram"},
    }

    headers = {
        "Cache-Control": "no-store, no-cache, must-revalidate",
        "Pragma": "no-cache",
    }
    return JSONResponse(content=data, status_code=200, headers=headers)


@router.get("/{idwf}/dump", response_model=DumpResponse)
async def dump(
    idwf: str,
    user: User = Depends(get_current_user),
):
    raise NotImplementedError("Step 8 — dump not yet implemented")


@router.post("/{idwf}/script", response_model=SaveResponse)
async def save_script(
    idwf: str,
    body: ScriptRequest,
    user: User = Depends(get_current_user),
):
    return SaveResponse(ok=True, msg="script saved (no-op)")


@router.post("/{idwf}/save", response_model=SaveResponse)
async def save_model(
    idwf: str,
    body: SaveModelRequest,
    user: User = Depends(get_current_user),
):
    raise NotImplementedError("Step 10 — save data payload not yet implemented")


@router.get("/{idwf}/thumbnail")
async def thumbnail(idwf: str):
    return {
        "msg": "thumbnail generation deferred",
        "svg_path": f"static/svg/{idwf}.svg",
    }


@router.get("/{idwf}/svg")
async def svg(idwf: str, service: ModelService = Depends(get_model_service)):
    raise NotImplementedError("Step 12 — SVG file serving not yet implemented")


@router.get("/{idwf}/shapes", response_model=ShapesResponse)
async def get_shapes(idwf: str, user: User = Depends(get_current_user)):
    return ShapesResponse(idwf=idwf, shapes={})


@router.get("/{idwf}/comments/{resource_id}", response_model=CommentsResponse)
async def get_comments(idwf: str, resource_id: str):
    return CommentsResponse(stencil_id="", documentation="")


@router.post("/import")
async def import_zip(user: User = Depends(get_current_user)):
    raise NotImplementedError("Step 15 — zip import not yet implemented")


@router.patch("/{idwf}/folder", response_model=SaveResponse)
async def update_folder(
    idwf: str, body: FolderUpdate, user: User = Depends(get_current_user)
):
    return SaveResponse(ok=True, msg=f"moved to folder '{body.folder}'")
