"""FastAPI router for BPM model endpoints.

Mirrors legacy CodeIgniter structure: `modules/bpm/controllers/Repository.php`
lives inside a folder named after its module (`bpm`). The corresponding FastAPI
    return JSONResponse(content=data, status_code=200, headers=headers)
file is `app/api/bpm/repository.py`.
"""

import copy as _copy_module
import json
import re
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from urllib.parse import unquote_plus

from fastapi import APIRouter, Depends, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import CursorResult, select
from sqlalchemy import delete as sa_delete

from app.api.auth import get_current_user
from app.models.bpm_model import SVG_DIR, BpmModel
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
    OutputFormat,
    SaveModelRequest,
    SaveResponse,
    ScriptRequest,
    ShapesResponse,
    TokensResponse,
)
from app.services.model_service import ModelService, get_model_service

router = APIRouter(prefix="/bpm/repository", tags=["repository"])


# -- Helpers ---------------------------------------------------------------- #


def _conflict_or_not_found(msg: str):  # type: ignore[misc]
    """Map service-level messages to the appropriate HTTP exception."""
    if "not found" in msg.lower():
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=msg)
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=msg)


def _strip_tags(html: str) -> str:
    """Remove HTML tags from a string (legacy ``strip_tags_content`` compat)."""
    clean = re.sub(r"<[^>]+>", "", html)
    return unquote_plus(clean.strip())


# -- Step 1: save ------------------------------------------------------------- #


@router.post("/save", response_model=ModelRead)
async def save(
    data: dict | str = Form(...),
    svg: str | None = Form(default=None),
    title: str | None = Form(default=None),
    user: User = Depends(get_current_user),
    service: ModelService = Depends(get_model_service),
):
    """Save or update a model. Matches legacy PHP ``Repository::save()`` / ``save_as()`` —
    form fields ``data`` (JSON string of the full Oryx model), optional ``svg``, and optional
    ``title`` (acts as idwf override, mirroring save_as).

    Sets ``properties.modificationdate`` to today midnight UTC. Extracts idwf from:
    1. ``title`` form field if provided (save_as behavior — also sets resourceId on model data)
    2. Decoded ``$data->resourceId`` otherwise
    """
    try:
        model_data = json.loads(data) if isinstance(data, str) else data
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid JSON in 'data' field")

    # idwf comes strictly from data.resourceId — title is editor metadata, ignored for storage.
    idwf = model_data.get("resourceId") if isinstance(model_data, dict) else None

    # Fresh modification date — legacy uses today's date at midnight UTC.
    model_data.setdefault("properties", {})["modificationdate"] = datetime.now(
        UTC
    ).strftime("%Y-%m-%dT%H:%M:%S")

    model, was_created = await service.save(idwf, model_data, svg=svg)
    http_status = 201 if was_created else 200
    return JSONResponse(
        content=ModelRead.model_validate(model).model_dump(mode="json"),
        status_code=http_status,
    )


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


# -- Step 3: save_as ---------------------------------------------------------- #


@router.post("/save_as", response_model=SaveResponse)
async def save_as(
    data: str = Form(...),
    svg: str | None = Form(default=None),
    title: str = Form(...),
    user: User = Depends(get_current_user),
    service: ModelService = Depends(get_model_service),
):
    """Save a new model using the editor's 'save_as' contract.

    Matches legacy PHP ``Repository::save_as()`` — form fields ``data`` (JSON string of the
    full Oryx model), optional ``svg``, and ``title`` acts as the new idwf. Sets
    ``$data->resourceId = $idwf`` before persisting; returns 404 if a model with that idwf
    already exists (legacy uses ``show_error('Name Already Exists', 404)``).
    """
    try:
        model_data = json.loads(data) if isinstance(data, str) else data
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid JSON in 'data' field")

    idwf = (
        title or model_data.get("resourceId") if isinstance(model_data, dict) else None
    )
    if not idwf:
        raise HTTPException(status_code=500, detail="No name defined<br>")

    # save_as: override resourceId to match the new idwf (mirrors $data->resourceId = $idwf).
    model_data["resourceId"] = idwf

    if await service.model_exists(idwf):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Name Already Exists",
        )

    now = datetime.now(UTC)
    model_data.setdefault("properties", {})["modificationdate"] = now.strftime(
        "%Y-%m-%dT%H:%M:%S"
    )

    if svg:
        SVG_DIR.mkdir(parents=True, exist_ok=True)
        (SVG_DIR / f"{idwf}.svg").write_text(svg, encoding="utf-8")

    model = BpmModel(
        idwf=idwf,
        folder="General",
        version=0,
        data=model_data,
        created_at=now,
        updated_at=now,
    )
    service.db.add(model)
    await service.db.commit()
    return SaveResponse(ok=True, msg=f"saved as id: {idwf}")


# -- Step 4: add (create scaffold) -------------------------------------------- #


@router.post(
    "/add/{idwf}",
    response_model=SaveResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add(
    idwf: str,
    body: ModelCreate | None = Form(default=None),  # optional form fields (folder/name)
    user: User = Depends(get_current_user),
):
    """Create a brand-new empty model scaffold.

    Legacy PHP builds defaults for folder, name, stencilset, resourceId, and
    properties — this replicates that contract so the editor can begin editing.
    """
    if await _model_exists(idwf):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"model '{idwf}' already exists",
        )

    folder = body.folder if body else "General"
    name = body.name if body else None

    now = datetime.now(UTC)
    scaffold_data: dict = {
        "resourceId": idwf,
        "stencilset": {
            "url": ".static/jscript/editor/stencilsets/bpmn2.0/bpmn2.0_2.json",
            "namespace": "http://b3mn.org/stencilset/bpmn2.0#",
        },
        "stencil": {"id": "BPMNDiagram"},
    }

    if name:
        scaffold_data.setdefault("properties", {})["name"] = name
    else:
        scaffold_data.setdefault("properties", {})["name"] = "New Model"

    scaffold_data["properties"]["creationdate"] = now.strftime("%Y-%m-%dT%H:%M:%S")
    scaffold_data["properties"]["modificationdate"] = ""

    model = BpmModel(
        idwf=idwf,
        folder=folder or "General",
        version=0,
        data=scaffold_data,
        created_at=now,
        updated_at=now,
    )
    service_obj = await _get_svc()  # type: ignore[misc]
    service_obj.db.add(model)
    await service_obj.db.commit()

    return SaveResponse(ok=True, msg=f"created id: {idwf}")


async def _model_exists(idwf: str) -> bool:
    """Check if a model with the given idwf exists."""
    svc = await _get_svc()  # type: ignore[misc]
    result = await svc.db.execute(select(BpmModel.idwf).where(BpmModel.idwf == idwf))
    return result.scalar_one_or_none() is not None


async def _get_svc():  # type: ignore[misc]
    """Quick helper to get a ModelService bound to the current session."""

    # We need an async session — use the same pattern as get_model_service
    from extensions import async_session_factory

    session = async_session_factory()
    return ModelService(session)


# -- Step 5: check_model ------------------------------------------------------ #


@router.get("/check_model/{name}", response_model=CheckResponse)
async def check_model(name: str, service: ModelService = Depends(get_model_service)):
    exists = await service.model_exists(name)
    return CheckResponse(ok=not exists)


# -- Step 6: delete ----------------------------------------------------------- #


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


# -- Step 7: load ------------------------------------------------------------- #


@router.get("/load/model/{idwf}", response_class=JSONResponse)
async def load(
    idwf: str,
    mode: str | None = Query(None, description="Load mode (e.g., 'debug')"),
    debug: bool = Query(False, description="Verbose debug output"),
    user: User = Depends(get_current_user),
    service: ModelService = Depends(get_model_service),
):
    """Load full model data. Falls back to template if `data` is empty."""
    idwf = unquote_plus(idwf)

    result = await service.db.execute(select(BpmModel).where(BpmModel.idwf == idwf))
    model: BpmModel | None = result.scalar_one_or_none()
    if model is None:
        raise HTTPException(status_code=404, detail=f"model '{idwf}' not found")
    data = model.data or {
        "resourceId": idwf,
        "stencilset": {
            "url": "static/jscript/editor/stencilsets/bpmn2.0/bpmn2.0_2.json",
            "namespace": "http://b3mn.org/stencilset/bpmn2.0#",
        },
        "stencil": {"id": "BPMNDiagram"},
    }
    if "stencilset" not in data:
        data["stencilset"] = {
            "url": "",
            "namespace": "http://b3mn.org/stencilset/bpmn2.0#",
        }
    data["stencilset"]["url"] = "static/editor/stencilsets/bpmn2.0/bpmn2.0_2.json"
    headers = {
        "Cache-Control": "no-store, no-cache, must-revalidate",
        "Pragma": "no-cache",
    }
    return JSONResponse(content=data, status_code=200, headers=headers)


# -- Step 8: dump ------------------------------------------------------------- #


@router.get("/dump/model/{idwf}", response_model=DumpResponse)
async def dump(
    idwf: str,
    expand: bool = Query(False, description="Recursively resolve sub-processes"),
    user: User = Depends(get_current_user),
):
    """Dump full model data with optional metadata.

    When ``expand=true``, walk childShapes recursively to include all nested
    process definitions (sub-processes, call activities).
    """
    idwf = unquote_plus(idwf)

    result = await _get_svc()  # type: ignore[misc]
    stmt = select(BpmModel).where(BpmModel.idwf == idwf)
    model: BpmModel | None = (await result.db.execute(stmt)).scalar_one_or_none()
    if model is None:
        raise HTTPException(status_code=404, detail=f"model '{idwf}' not found")

    data = model.data or {}

    htmltitle = ""
    if "properties" in data and isinstance(data["properties"], dict):
        htmltitle = str(data["properties"].get("name", "") or "")

    return DumpResponse(
        htmltitle=htmltitle,
        theme="default",
        base_url="/bpm/repository/",
        idwf=idwf,
        data=data if not expand else _expand_data(data),
    )


def _expand_data(data: dict) -> dict:
    """Recursively resolve sub-processes by walking childShapes.

    This is a simplified expansion — full implementation would recursively load
    referenced models and merge their shapes into the parent's shape tree.
    """
    result = _copy_module.deepcopy(data)
    if "childShapes" in result:
        expanded_children = []
        for child in result["childShapes"]:
            if isinstance(child, dict):
                ref_idwf = child.get("resourceId") or child.get("id")
                if ref_idwf and _model_exists_sync(ref_idwf):
                    sub_data = _load_model_data_sync(ref_idwf)
                    if sub_data:
                        expanded_children.append({**child, "_expanded": True})
                        continue
            expanded_children.append(child)
        result["childShapes"] = expanded_children
    return result


def _model_exists_sync(idwf: str) -> bool:
    """Sync check for model existence (used during expansion)."""
    from sqlalchemy import select as sa_select
    from sqlalchemy.exc import SQLAlchemyError

    from extensions import sync_session_factory

    try:
        with sync_session_factory() as session:
            stmt = sa_select(BpmModel.idwf).where(BpmModel.idwf == idwf)
            result = session.execute(stmt).scalar_one_or_none()
            return result is not None
    except SQLAlchemyError as err:
        print(f"[expand] model existence check failed for {idwf}: {err}")
        return False


def _load_model_data_sync(idwf: str) -> dict | None:
    """Sync load model data for expansion."""
    from sqlalchemy import select as sa_select
    from sqlalchemy.exc import SQLAlchemyError

    from extensions import sync_session_factory

    try:
        with sync_session_factory() as session:
            stmt = sa_select(BpmModel.data).where(BpmModel.idwf == idwf)
            result = session.execute(stmt).scalar_one_or_none()
            return result if isinstance(result, dict) else None
    except SQLAlchemyError:
        return None


# -- Step 9: save_script (stub) ---------------------------------------------- #


@router.post("/save_script/{idwf}/{resource_id}", response_model=SaveResponse)
async def save_script(
    idwf: str,
    resource_id: str,
    body: ScriptRequest,
    user: User = Depends(get_current_user),
):
    return SaveResponse(ok=True, msg="script saved (no-op)")


# -- Step 10: save_model ------------------------------------------------------ #


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


# -- Step 11: thumbnail (stub) ------------------------------------------------


@router.get("/thumbnail/{idwf}/{width}/{height}")
async def thumbnail(
    idwf: str,
    width: int,
    height: int,
):
    """Stub — returns raw SVG path. Full implementation deferred to later step."""
    return {
        "msg": "thumbnail generation deferred",
        "svg_path": f"static/svg/{idwf}.svg",
    }


# -- Step 12: svg (serve file from disk) ------------------------------------- #


@router.get("/svg/{idwf}")
async def svg(
    idwf: str,
    user: User = Depends(get_current_user),
):
    """Return XHTML document (plain text/html response).

    Matches legacy CodeIgniter Repository::svg(): decodes idwf, loads the model's
    SVG payload from disk, applies ``str_replace('>', ">\n")``, and echoes raw XHTML.
    """
    idwf = unquote_plus(idwf)

    svg_path = SVG_DIR / f"{idwf}.svg"
    if not svg_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"SVG file for '{idwf}' not found",
        )

    svg_content = svg_path.read_text(encoding="utf-8")
    formatted_svg = svg_content.replace(">", ">\n")

    html = f"""<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
<head>
    <title>SVG:{idwf}</title>
</head>
<body>
    <div id="svg-box">
{formatted_svg}
    </div>
</body>
</html>"""

    return HTMLResponse(
        content=html,
        headers={"Cache-Control": "no-store, no-cache"},
    )


# -- Step 13: get_shapes ------------------------------------------------------ #


@router.get("/get_shapes/model/{idwf}", response_model=ShapesResponse)
async def get_shapes(
    idwf: str,
    debug: bool = Query(False, description="Verbose debug output"),
    user: User = Depends(get_current_user),
):
    """Walk childShapes recursively to build shapes dict indexed by resourceId."""
    result = await _get_svc()  # type: ignore[misc]
    stmt = select(BpmModel).where(BpmModel.idwf == idwf)
    model: BpmModel | None = (await result.db.execute(stmt)).scalar_one_or_none()
    if model is None:
        raise HTTPException(status_code=404, detail=f"model '{idwf}' not found")

    data = model.data or {}
    shapes = _collect_shapes(data)
    return ShapesResponse(idwf=idwf, shapes=shapes)


def _collect_shapes(data: dict, shapes: dict | None = None) -> dict:
    """Recursively collect all shapes from a BPMN data tree."""
    if shapes is None:
        shapes = {}

    for key in ("childShapes", "childGraphics"):
        children = data.get(key, [])
        if isinstance(children, list):
            for child in children:
                if isinstance(child, dict):
                    rid = child.get("resourceId") or child.get("id")
                    if rid:
                        shapes[str(rid)] = _clean_shape(child)

    # Recurse into nested data (sub-processes)
    for key in ("data", "childShapes"):
        value = data.get(key)
        if isinstance(value, dict):
            _collect_shapes(value, shapes)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    _collect_shapes(item, shapes)

    return shapes


def _clean_shape(shape: dict) -> dict:
    """Strip internal metadata from a shape dict (keep only display-relevant fields)."""
    keep = {"id", "resourceId", "stencil", "bounds", "childShapes"}
    return {k: v for k, v in shape.items() if k in keep}


# -- Step 14: get_comments ---------------------------------------------------- #


@router.get("/get_comments/model/{idwf}/{resource_id}", response_model=CommentsResponse)
async def get_comments(idwf: str, resource_id: str):
    """Look up documentation/comment for a shape by resourceId."""
    result = await _get_svc()  # type: ignore[misc]
    stmt = select(BpmModel).where(BpmModel.idwf == idwf)
    model: BpmModel | None = (await result.db.execute(stmt)).scalar_one_or_none()
    if model is None:
        raise HTTPException(status_code=404, detail=f"model '{idwf}' not found")

    data = model.data or {}
    shape = _find_shape(data, resource_id)
    if shape is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"shape '{resource_id}' not found in model '{idwf}'",
        )

    stencil_id = ""
    documentation = ""
    stencil = shape.get("stencil") or {}
    if isinstance(stencil, dict):
        stencil_id = str(stencil.get("id", ""))

    props = shape.get("properties") or {}
    if isinstance(props, dict):
        documentation = str(props.get("documentation", "") or "")

    return CommentsResponse(stencil_id=stencil_id, documentation=documentation)


def _find_shape(data: dict, resource_id: str) -> dict | None:
    """Walk the shape tree to find a shape by its resourceId."""
    for key in ("childShapes", "shapes"):
        children = data.get(key, [])
        if isinstance(children, list):
            for child in children:
                if isinstance(child, dict) and (
                    child.get("resourceId") == resource_id
                    or child.get("id") == resource_id
                ):
                    return child

    # Recurse into nested data
    for key in ("data", "childShapes"):
        value = data.get(key)
        if isinstance(value, dict):
            found = _find_shape(value, resource_id)
            if found:
                return found
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    found = _find_shape(item, resource_id)
                    if found:
                        return found

    return None


# -- Step 15: import (zip upload + extract) ----------------------------------- #


@router.post("/import", include_in_schema=False)
async def import_zip(
    file: UploadFile,
    user: User = Depends(get_current_user),
):
    """Upload a .zip archive containing model JSON + SVG.

    Extracts to a temp dir, reads ``{idwf}.json`` and ``{idwf}.svg``, then saves
    via the existing save/save_raw paths. Legacy PHP does this with CodeIgniter's
    upload library; FastAPI handles it via UploadFile.
    """
    if not file.filename or not file.filename.endswith(".zip"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only .zip files are accepted",
        )

    import tempfile

    idwf = Path(file.filename).stem  # strip .zip extension → model name

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)

        # Save uploaded zip to temp file
        zip_bytes = await file.read()
        zip_file = tmp_path / "upload.zip"
        zip_file.write_bytes(zip_bytes)

        # Extract to temp directory
        with zipfile.ZipFile(zip_file, "r") as zf:
            zf.extractall(tmp_path)

        # Look for model JSON and SVG in extracted contents
        json_files = list((tmp_path).rglob(f"{idwf}.json"))
        svg_files = list((tmp_path).rglob(f"{idwf}.svg"))

        if not json_files:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"No '{idwf}.json' found in archive",
            )

        json_data = json.loads(json_files[0].read_text(encoding="utf-8"))

        # Write SVG to static/svg/ if present in archive
        svg_content: str | None = None
        if svg_files:
            svg_path = SVG_DIR / f"{idwf}.svg"
            svg_path.parent.mkdir(parents=True, exist_ok=True)
            svg_content = svg_files[0].read_text(encoding="utf-8")

        # Use service to save (upsert — creates or updates depending on existence)
        svc = await _get_svc()  # type: ignore[misc]
        if await _model_exists(idwf):
            _, _was_created = await svc.save(idwf, json_data, svg=svg_content)
            msg = f"updated id: {idwf}"
        else:
            from datetime import UTC as _UTC

            now = datetime.now(_UTC)
            new_model = BpmModel(
                idwf=idwf,
                folder="General",
                version=0,
                data=json_data,
                created_at=now,
                updated_at=now,
            )
            svc.db.add(new_model)
            await svc.db.commit()
            msg = f"created id: {idwf}"

    return SaveResponse(ok=True, msg=msg)


# -- Step 16: update_folder --------------------------------------------------- #


@router.post("/update_folder", response_model=SaveResponse)
async def update_folder(
    body: FolderUpdate,
    user: User = Depends(get_current_user),
):
    """Move a model into a different folder. Strips HTML tags from folder name."""
    clean_folder = _strip_tags(body.folder)

    result = await _get_svc()  # type: ignore[misc]
    stmt = select(BpmModel).where(BpmModel.idwf == body.idwf)
    existing = (await result.db.execute(stmt)).scalar_one_or_none()
    if existing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"model '{body.idwf}' not found",
        )

    existing.folder = clean_folder
    await result.db.commit()

    return SaveResponse(ok=True, msg=f"moved to folder '{clean_folder}'")


# -- Helpers: tree building (ported from legacy Admin.php) ------------------ #


def _explode_tree(array: dict[str, str], delimiter: str = "/") -> dict | bool:
    """Convert a flat ``{path: name}`` dict into a nested tree structure.

    Ported from legacy ``Admin::explodeTree($array, $delimiter='/')``.
    Example input:  {"General/flow1": "My Flow", "HR/onboarding": "Onboarding"}
    Returns nested dict with asort applied at each level.
    """
    if not isinstance(array, dict):
        return False

    return_arr: dict = {}

    for key in sorted(array.keys()):
        val = array[key]
        parts = [p for p in str(key).split(delimiter) if p]
        leaf_part = parts.pop()

        parent_ref = return_arr
        for part in parts:
            if part not in parent_ref or not isinstance(parent_ref[part], dict):
                parent_ref[part] = {}
            parent_ref = parent_ref[part]

        if leaf_part not in parent_ref:
            parent_ref[leaf_part] = val

    def _sort(d):  # type: ignore[misc]
        if isinstance(d, dict):
            return {k: _sort(v) for k, v in sorted(d.items())}
        return d

    return _sort(return_arr)


def _convert_to_ext(array: dict | list):
    """Convert nested tree dict to ExtJS TreePanel format with leaf/cls fields.

    Ported from legacy ``Admin::convert_to_ext($array)``.
    Produces nodes with: id, text, leaf bool, cls (folder/user), iconCls, children[].
    """
    rtn_arr = []

    for key, value in array.items():
        if isinstance(value, dict):
            sorted_value = {k: value[k] for k in sorted(value.keys())}
            children_flat = _convert_to_ext(sorted_value)
            # Flatten nested lists from recursive calls
            children = []
            for c in children_flat:
                if isinstance(c, list):
                    children.extend(c)
                else:
                    children.append(c)
            rtn_arr.append(
                {
                    "text": key,
                    "leaf": False,
                    "cls": "folder",
                    "expanded": True,
                    "children": children,
                }
            )
        else:
            rtn_arr.append(
                {
                    "id": str(key),
                    "text": value,
                    "leaf": True,
                    "iconCls": None,
                }
            )

    return rtn_arr


def _flatten_leafs_to_ext(array: dict) -> list[dict]:
    """Extract all leaf nodes from a nested tree dict into a flat ExtJS array.

    Returns only items with ``leaf=True``, each containing id, text, and leaf fields.
    Used by get_tree2 to produce the legacy-style flat model list for the browser panel.

    Sort order: leaf ASC (all True), then text ASC — matches Ext JS sort:
        [{\"property\":\"leaf\",\"direction\":\"ASC\"},{\"property\":\"text\",\"direction\":\"ASC\"}]
    """
    leaves: list[dict] = []

    def _walk(node_dict: dict):
        for key, value in node_dict.items():
            if isinstance(value, dict):
                _walk(value)
            else:
                leaves.append(
                    {
                        "id": str(key),
                        "text": value,
                        "leaf": True,
                    }
                )

    _walk(array)
    leaves.sort(key=lambda n: (n["leaf"], n["text"]))
    return leaves


# -- Step 17 (legacy): tokens (stub) ----------------------------------------- #


@router.get("/tokens/{idwf}/{idcase}/{filter_status}", response_model=TokensResponse)
async def tokens(
    idwf: str,
    idcase: str,
    filter_status: str = "",
):
    """GET /api/v1/models/tokens/{idwf}/{idcase}/{filter_status} —
    case token inspection (stub).

    Legacy PHP loads model + case history and walks tokens to build icon/status info.
    Stub returns an empty token list until the engine is wired up.
    """
    return TokensResponse(idwf=idwf, idcase=idcase, count=0, tokens=[])


# -- Step 18: get_tree2 (legacy Admin.php) ------------------------------------ #


@router.post("/get_tree2/{output_format}")
async def get_tree2(
    output_format: OutputFormat,
    user: User = Depends(get_current_user),
):
    """Build a tree JSON representation of all BPMN models.

    Mirrors legacy ``Admin::get_tree2()`` — queries BpmModel for idwf/folder/data,
    builds a flat ``{folder/idwf => name [idwf]}`` map, explodes into nested dict,
    then converts to ExtJS leaf/children format (like ``convert_to_ext``).

    Returns JSON array of tree nodes suitable for an ExtJS TreePanel proxy.
    """
    # Query all models for idwf, folder, data columns (same projection as legacy)
    svc = await _get_svc()  # type: ignore[misc]
    stmt = select(BpmModel.idwf, BpmModel.folder, BpmModel.data).order_by(
        BpmModel.folder, BpmModel.idwf
    )
    result = cast(CursorResult, await svc.db.execute(stmt))

    m_arr: dict[str, str] = {}
    for idwf_val, folder, data in result.fetchall():
        if not idwf_val or not isinstance(data, dict):
            continue
        name = (data.get("properties") or {}).get("name", "no name")
        folder_str = f"{folder}/" if folder else ""
        m_arr[f"{folder_str}{idwf_val}"] = f"{name} [{idwf_val}]"

    tree_data = _explode_tree(m_arr, delimiter="/")
    full_tree = _flatten_leafs_to_ext(tree_data)

    return JSONResponse(content=full_tree, status_code=200)
