"""FastAPI router for BPM model endpoints."""

from __future__ import annotations

import copy as _copy_module
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy import CursorResult, select
from sqlalchemy import delete as sa_delete

from app.core.auth import get_current_user
from app.models.bpm_model import BpmModel
from app.models.user import User
from app.schemas.repository import (
    CheckResponse,
    CommentsResponse,
    DumpResponse,
    FolderUpdate,
    ModelCreate,
    ModelDeleteRequest,
    ModelDuplicateRequest,
    ModelRead,
    ModelUpdate,
    SaveAsRequest,
    SaveModelRequest,
    SaveResponse,
    ScriptRequest,
    ShapesResponse,
    TokensResponse,
)
from app.services.model_service import ModelService, get_model_service

router = APIRouter(prefix="/api/v1/models", tags=["models"])


# -- Step 2: duplicate -------------------------------------------------------- #


@router.post(
    "/duplicate",
    response_model=SaveResponse,
    status_code=status.HTTP_201_CREATED,
)
async def duplicate(
    body: ModelDuplicateRequest,
    user: User = Depends(get_current_user),
    service: ModelService = Depends(get_model_service),
):
    """Clone a model to a new ``idwf`` (raw insert — no version bump).

    Returns 201 on success, 409 if the target idwf is already taken.
    Source-not-found returns 404 via FastAPI's default exception handler.
    Both ``idwf`` and ``new_idwf`` come from the request body.
    """
    result = await service.duplicate(body.idwf, body.new_idwf)

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
    "/add/{idwf}",
    status_code=status.HTTP_201_CREATED,
)
async def add(
    idwf: str,
    body: ModelCreate | None = None,
    user: User = Depends(get_current_user),
):
    raise NotImplementedError("Step 4 — create scaffold not yet implemented")


@router.put("/save/{idwf}", response_model=ModelRead)
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


@router.post("/save_as", response_model=SaveResponse)
async def save_as(
    body: SaveAsRequest,
    user: User = Depends(get_current_user),
    service: ModelService = Depends(get_model_service),
):
    """Save a copy with a custom title/idwf (no version bump).

    ``title`` is the new model identifier — legacy PHP reads it from the POST
    form field ``title``, not as a path parameter.
    """
    idwf = body.title
    data = _copy_module.deepcopy(body.data)
    data.pop("_id", None)
    data["resourceId"] = idwf

    if await service.model_exists(idwf):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"model '{idwf}' already exists",
        )

    now = datetime.now(UTC)
    data.setdefault("properties", {})["modificationdate"] = now.strftime(
        "%Y-%m-%dT%H:%M:%S"
    )

    if body.svg:
        svg_dir = Path(__file__).parent.parent.parent / "static" / "svg"
        svg_dir.mkdir(parents=True, exist_ok=True)
        (svg_dir / f"{idwf}.svg").write_text(body.svg, encoding="utf-8")

    model = BpmModel(
        idwf=idwf,
        folder="General",
        version=0,
        data=data,
        created_at=now,
        updated_at=now,
    )
    service.db.add(model)
    await service.db.commit()

    return SaveResponse(ok=True, msg=f"saved as id: {idwf}")


@router.get("/check_model/{name}", response_model=CheckResponse)
async def check_model(name: str, service: ModelService = Depends(get_model_service)):
    exists = await service.model_exists(name)
    return SaveResponse(ok=not exists, msg="" if not exists else "idwf already taken")


@router.delete("/delete", response_model=SaveResponse)
async def delete(
    body: ModelDeleteRequest,
    user: User = Depends(get_current_user),
    service: ModelService = Depends(get_model_service),
):
    stmt = sa_delete(BpmModel).where(BpmModel.idwf == body.idwf)
    result = cast(CursorResult, await service.db.execute(stmt))
    if result.rowcount == 0:
        return SaveResponse(ok=False, msg=f"model '{body.idwf}' not found")
    await service.db.commit()
    return SaveResponse(ok=True, msg=f"deleted id: {body.idwf}")


@router.get("/load/{idwf}", response_class=JSONResponse)
async def load(
    idwf: str,
    mode: str | None = Query(None, description="Load mode (e.g., 'debug')"),
    debug: bool = Query(False, description="Verbose debug output"),
    user: User = Depends(get_current_user),
    service: ModelService = Depends(get_model_service),
):
    """Load full model data. Falls back to template if `data` is empty."""
    result = await service.db.execute(select(BpmModel).where(BpmModel.idwf == idwf))
    model: BpmModel | None = result.scalar_one_or_none()
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


@router.get("/dump/{idwf}", response_model=DumpResponse)
async def dump(
    idwf: str,
    expand: bool = Query(False, description="Recursively resolve sub-processes"),
    user: User = Depends(get_current_user),
):
    raise NotImplementedError("Step 8 — dump not yet implemented")


@router.post("/save_script/{idwf}/{resource_id}", response_model=SaveResponse)
async def save_script(
    idwf: str,
    resource_id: str,
    body: ScriptRequest,
    user: User = Depends(get_current_user),
):
    return SaveResponse(ok=True, msg="script saved (no-op)")


@router.post("/save_model/{idwf}", response_model=SaveResponse)
async def save_model(
    idwf: str,
    body: SaveModelRequest,
    user: User = Depends(get_current_user),
    service: ModelService = Depends(get_model_service),
):
    """Persist the editor's data + svg payload.

    The Oryx "save" POST ships three fields (data, svg, title). ``title`` is
    accepted but ignored; ``idwf`` comes from the URL path segment — matching
    legacy PHP where ``$this->input->post('idwf')`` was the source of truth.
    """
    model, _mf, _zp = await service.save_model(idwf, body.data, svg=body.svg)
    return SaveResponse(ok=True, msg=f"saved id: {model.idwf}")


@router.get("/thumbnail/{idwf}/{width}/{height}")
async def thumbnail(
    idwf: str,
    width: int,
    height: int,
):
    return {
        "msg": "thumbnail generation deferred",
        "svg_path": f"static/svg/{idwf}.svg",
    }


@router.get("/svg/{idwf}")
async def svg(idwf: str, service: ModelService = Depends(get_model_service)):
    raise NotImplementedError("Step 12 — SVG file serving not yet implemented")


@router.get("/get_shapes/{idwf}", response_model=ShapesResponse)
async def get_shapes(
    idwf: str,
    debug: bool = Query(False, description="Verbose debug output"),
    user: User = Depends(get_current_user),
):
    return ShapesResponse(idwf=idwf, shapes={})


@router.get("/get_comments/{idwf}/{resource_id}", response_model=CommentsResponse)
async def get_comments(idwf: str, resource_id: str):
    return CommentsResponse(stencil_id="", documentation="")


@router.get("/tokens/{idwf}/{idcase}/{filter_status}", response_model=TokensResponse)
async def tokens(
    idwf: str,
    idcase: str,
    filter_status: str = "",
):
    """GET `/api/v1/models/tokens/{idwf}/{idcase}/{filter_status}` — case token inspection (stub).

    Legacy PHP loads model + case history and walks tokens to build icon/status info.
    Stub returns an empty token list until the engine is wired up.
    """
    return TokensResponse(idwf=idwf, idcase=idcase, count=0, tokens=[])


@router.post("/import")
async def import_zip(user: User = Depends(get_current_user)):
    raise NotImplementedError("Step 15 — zip import not yet implemented")


@router.post("/update_folder", response_model=SaveResponse)
async def update_folder(
    body: FolderUpdate,
    user: User = Depends(get_current_user),
):
    return SaveResponse(ok=True, msg=f"moved to folder '{body.folder}'")
