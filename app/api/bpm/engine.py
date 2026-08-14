"""FastAPI router for BPM Engine case lifecycle endpoints.

Mirrors legacy CodeIgniter structure: `modules/bpm/controllers/Engine.php`
lives inside a folder named after its module (`bpm`). The corresponding FastAPI
file is `app/api/bpm/engine.py`.

Endpoints ported so far:
- ``newcase``  -- create a new case instance and advance it to start shapes
- ``start``    -- resume an existing case at its diagram's start points
- ``run``      -- execute the engine loop for pending tokens
- ``post/{token_id}`` -- external webhook callback
- ``assign``   -- assign task to one or more users

These correspond to the legacy ``Engine::Newcase()``, ``Engine::Start()``,
``Engine::Run()``, ``Engine::post()``, and ``Engine::assign()`` methods.
"""

from __future__ import annotations

#import uuid
import random
from fastapi import APIRouter, Body, Depends, HTTPException, status
from sqlalchemy import select

from app.core.auth import get_current_user
from app.models.bpm_model import BpmModel
from app.models.case import BpmCase
from app.models.token import Token
from app.models.user import User
from app.schemas.engine import (
    AssignRequest,
    AssignResponse,
    CaseCreated,
    NewcaseRequest,
    PostRequest,
    PostResponse,
    RunRequest,
    RunResponse,
    StartRequest,
    StartResponse,
)
from app.services.engine_service import EngineService, get_engine_service

router = APIRouter(prefix="/bpm/engine", tags=["engine"])


# -- Handler registry --------------------------------------------------------- #


class _EngineHandlerRegistry:
    """Maps BPMN stencil IDs to handler classes for shape dispatch.

    Populated in Phase 2 when engine_service.py is created. Each handler class
    must implement ``handle(token, shape, service)`` and return a bool indicating
    whether movenext should also be called (False means the handler consumed the token).

    This is a module-level singleton so downstream services can register handlers
    via::

        from app.api.bpm.engine import ENGINE_HANDLER_REGISTRY
        ENGINE_HANDLER_REGISTRY.register("Task", TaskHandler)
    """

    def __init__(self):
        self._handlers: dict[str, type] = {}

    def register(self, stencil_id: str, handler_cls: type) -> None:
        self._handlers[stencil_id] = handler_cls

    def get(self, stencil_id: str) -> type | None:
        return self._handlers.get(stencil_id)

    @property
    def handlers(self) -> dict[str, type]:
        return dict(self._handlers)


ENGINE_HANDLER_REGISTRY = _EngineHandlerRegistry()


# -- newcase ------------------------------------------------------------------ #


@router.post(
    "/newcase", response_model=CaseCreated, status_code=status.HTTP_201_CREATED
)
async def newcase(
    body: NewcaseRequest,
    user: User = Depends(get_current_user),
    service: EngineService = Depends(get_engine_service),
):
    """Create a new case instance for the given workflow.

    Ported from legacy ``Engine::Newcase()``:

    1. Generate a unique case ID via :func:`_generate_case_id`.
    2. Create BpmCase record with status 'open'.
    3. Find all start shapes in the diagram and place pending tokens on each.
    4. If ``manual=True``, mark the case as run-manual.

    Returns 201 with the new case ID and workflow reference.
    """
    # 1. Validate model exists.
    stmt = select(BpmModel).where(BpmModel.idwf == body.idwf)
    result = await service.db.execute(stmt)
    model_row = result.scalar_one_or_none()

    if model_row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Model '{body.idwf}' does not exist",
        )

    # 2. Generate case ID (with collision retry, mirroring legacy gen_case).
    idcase = _generate_case_id()
    for _ in range(10):
        check_stmt = select(BpmCase.idcase).where(BpmCase.idcase == idcase)
        exists = (await service.db.execute(check_stmt)).scalar_one_or_none()
        if not exists:
            break
        idcase = _generate_case_id()

    # 3. Create BpmCase record.
    case = BpmCase(
        idcase=idcase,
        idwf=body.idwf,
        status="open",
        initiator_id=user.idu if user else None,
        run_manual=body.manual,
    )
    service.db.add(case)

    # 4. Find start shapes and place tokens (Startcase logic from legacy L128-176).
    start_shapes = await service.get_start_shapes(body.idwf)

    if not start_shapes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The Schema doesn't have a start point",
        )

    for shape in start_shapes:
        resource_id = shape.get("resourceId", "")
        if resource_id:
            stencil_id = (shape.get("stencil") or {}).get("id", "StartNoneEvent")
            await service.create_token(
                idwf=body.idwf,
                case_id=idcase,
                resource_id=resource_id,
                type_=stencil_id,
                status="pending",
            )

    # 5. Save the case record (flush + commit — flush alone won't persist).
    await service.db.flush()
    await service.db.commit()

    return CaseCreated(idwf=body.idwf, idcase=idcase)


# -- start -------------------------------------------------------------------- #


@router.post("/start", response_model=StartResponse)
async def start(
    body: StartRequest,
    user: User = Depends(get_current_user),
    service: EngineService = Depends(get_engine_service),
):
    """Resume an existing case at its diagram's start shapes.

    Ported from legacy ``Engine::Start()`` which delegates to ``Startcase()``:

    1. Validate model exists; return 404 if not found.
    2. Clear any existing tokens for this (idwf, idcase).
    3. Find all start shapes in the diagram and place pending tokens on each.

    Returns count of tokens placed so the caller can verify progress.
    """
    # 1. Validate model exists.
    stmt = select(BpmModel).where(BpmModel.idwf == body.idwf)
    result = await service.db.execute(stmt)
    model_row = result.scalar_one_or_none()

    if model_row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Model '{body.idwf}' does not exist",
        )

    # 2. Clear existing tokens for this case (mirrors legacy clear_tokens/clear_case).
    await service.delete_tokens(body.idwf, body.idcase)

    # 3. Find start shapes and place pending tokens.
    start_shapes = await service.get_start_shapes(body.idwf)

    if not start_shapes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The Schema doesn't have a start point",
        )

    tokens_created = 0
    for shape in start_shapes:
        resource_id = shape.get("resourceId", "")
        if resource_id:
            stencil_id = (shape.get("stencil") or {}).get("id", "StartNoneEvent")
            await service.create_token(
                idwf=body.idwf,
                case_id=body.idcase,
                resource_id=resource_id,
                type_=stencil_id,
                status="pending",
            )
            tokens_created += 1

    return StartResponse(
        idwf=body.idwf,
        idcase=body.idcase,
        tokens_created=tokens_created,
    )


# -- run ---------------------------------------------------------------------- #


@router.post("/run/{idwf}/{idcase}", response_model=RunResponse)
async def run(
    idwf: str,
    idcase: str,
    body: RunRequest | None = Body(None),
    user: User = Depends(get_current_user),
    service: EngineService = Depends(get_engine_service),
):
    """Execute the engine loop for a case instance.

    Ported from legacy ``Engine::Run($model, $idwf, $case)`` (L183-301).
    The main loop fetches pending/waiting tokens, dispatches each to its
    registered shape handler (or falls back to movenext), and repeats until
    no more work remains or the iteration cap is hit.

    When ``silent`` is true in the request body, returns immediately after the
    loop without rendering pending tasks list.
    """
    # 1. Validate model exists.
    stmt = select(BpmModel).where(BpmModel.idwf == idwf)
    result = await service.db.execute(stmt)
    model_row = result.scalar_one_or_none()

    if model_row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Model '{idwf}' does not exist",
        )

    # 2. Build the token filter — fetch pending/waiting tokens for this case.
    pending_statuses = ["pending", "waiting"]

    # 3. Main loop (up to 100 iterations, mirroring legacy $i < 100).
    max_iterations = 100
    iteration = 0
    filter_statuses: list[str] = pending_statuses.copy()

    while iteration < max_iterations:
        iteration += 1

        # Fetch tokens matching current status filter.
        tokens = await service.get_pending_tokens(idwf, idcase, filter_statuses)
        if not tokens:
            break

        # Legacy line 278: after first pass, only look at 'pending' (not 'waiting').
        filter_statuses = ["pending"]

        for token in tokens:
            shape = await service.get_shape(token.resource_id, idwf)
            if not shape:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Shape '{token.resource_id}' not found in model tree",
                )

            stencil_id = (shape.get("stencil") or {}).get("id", "")
            handler_cls = ENGINE_HANDLER_REGISTRY.get(stencil_id)

            if handler_cls is not None:
                instance = handler_cls()  # type: ignore[call-arg]
                should_movenext = instance.handle(token, shape, service)  # type: ignore[misc]
            else:
                # No registered handler — fall back to movenext.
                should_movenext = True

            if should_movenext:
                await service.movenext(token.resource_id, idwf, idcase)

    return RunResponse(ok=True, msg="Engine executed successfully")


# -- post --------------------------------------------------------------------- #


@router.post("/post/{token_id}", response_model=PostResponse)
async def post(
    token_id: int,
    body: PostRequest,
    user: User = Depends(get_current_user),
    service: EngineService = Depends(get_engine_service),
):
    """External webhook callback for a specific token.

    Ported from legacy ``Engine::post($token_id, $external_origin, $external_id)``
    (L316-333). The legacy controller:

    1. Looks up the token by ID via ``$this->bpm->get_token_byid($token_id)``.
    2. Saves external data on the case record under ``data['external'][origin][resourceId]``.
    3. Calls ``run_post()`` to load inbound DataObjects/connectors and advance the engine.

    Returns 404 if no matching token is found (mirrors legacy ``show_error('Token not found',500)``).
    """
    # Search for token by ID.
    stmt = select(Token).where(Token.idtoken == token_id)
    result = await service.db.execute(stmt)
    token = result.scalar_one_or_none()

    if token is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Token not found",
        )

    # Persist external data on the token's external_data JSONB column.
    # Legacy stores it as ``case['data']['external'][origin][resourceId] = external_id``;
    # we mirror that nested structure under Token.external_data for now.
    if body.data:
        ext_data = token.external_data or {}
        origin_bucket = ext_data.setdefault(body.external_origin, {})
        origin_bucket[token.resource_id] = body.external_id

        token.external_data = ext_data
        await service.db.flush()
        await service.db.commit()

    # Mark the token as done. The full run_post chain (load DataObjects, connectors, movenext)
    # is deferred until connector logic is implemented — see ENGINE.md Phase 2.
    if token.status != "finished":
        await service.mark_token_finished(token)

    return PostResponse(ok=True, msg="POST processed successfully")


# -- assign ------------------------------------------------------------------- #


@router.post("/assign", response_model=AssignResponse)
async def assign(
    body: AssignRequest,
    user: User = Depends(get_current_user),
    service: EngineService = Depends(get_engine_service),
):
    """Assign a task to one or more users.

    Ported from legacy ``Engine::assign($model, $idwf, $idcase, $src_resourceId, $resourceId, $idu)``
    (L81-108). The legacy controller:

    1. Validates that ``$idu`` is truthy; skip entirely if no users supplied.
    2. Loads the workflow model and validates it exists.
    3. Fetches both the target shape (resourceId) and source shape (src_resourceId); returns errors if either is missing.
    4. Looks up an existing token for that resourceId: assigns users via ``assign_task()`` if found, otherwise creates a new token with checkin and sets its assign array.

    Since Case/Token tables now exist, this implementation uses the database directly.
    """
    # 1. Validate that at least one user ID was supplied (mirrors legacy ``if($idu)`` guard).
    if not body.user_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one user ID must be provided",
        )

    # 2. Load model and validate existence.
    stmt = select(BpmModel).where(BpmModel.idwf == body.idwf)
    result = await service.db.execute(stmt)
    model_row = result.scalar_one_or_none()

    if model_row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Model referenced:{body.idwf} does not exists",
        )

    # 3. Fetch shapes by resourceId and src_resourceId; validate both exist in the model tree.
    target_shape = await service.get_shape(body.resource_id, body.idwf)
    source_shape = await service.get_shape(body.src_resource_id, body.idwf)

    if target_shape is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"The shape:{body.resource_id} doesn't exists in the model: {body.idwf}",
        )
    if source_shape is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"The source shape:{body.src_resource_id} doesn't exists in the model: {body.idwf}",
        )

    # 4. Validate that target and source are different shapes.
    if body.resource_id == body.src_resource_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Source and target resource IDs must be different",
        )

    # 5. Look up or create token (mirrors legacy assign_task/token_checkin logic).
    existing_token = await service.get_token(body.idwf, body.idcase, body.resource_id)

    if existing_token:
        # Token exists — update its assignment array (legacy ``assign_task``).
        existing_token.assign = body.user_ids
        await service.db.flush()
        await service.db.commit()
    else:
        # Token doesn't exist — create one (legacy ``token_checkin``).
        stencil_id = ""
        shape_stencil = (target_shape.get("stencil") or {}).get("id", "")
        if isinstance(shape_stencil, str):
            stencil_id = shape_stencil

        new_token = Token(
            idwf=body.idwf,
            case_id=body.idcase,
            resource_id=body.resource_id,
            type_=stencil_id or "Task",
            status="pending",
            assign=body.user_ids,
        )
        service.db.add(new_token)
        await service.db.flush()
        await service.db.commit()

    return AssignResponse(ok=True, msg="Task assigned successfully")


# -- Helpers ---------------------------------------------------------------- #


def _generate_case_id(length: int = 4) -> str:
    """Generate a unique case identifier.

    Mirrors the legacy PHP implementation which used random 4-letter codes
    (chr(64+rand(1,26)) x 4) for human-readable case IDs like "KXRF".
    Collisions are prevented by database-level uniqueness on ``idcase``.
    """
    # return uuid=uuid.uuid4().hex[:8].upper()

    return "".join(chr(random.randint(65, 90)) for _ in range(4))  # mirrors chr(64+rand(1,26)) x 4 from legacy PHP


# -- Phase 4: Utility / internal methods ------------------------------------ #


def run_after(callbacks: list[dict]) -> None:
    """Execute deferred callback stack (mirrors legacy ``Engine::run_after()`` L303-310).

    The legacy code iterates through ``$this->run_after_stack``, calling each
    entry's function with its arguments via ``call_user_func_array``. This
    Python equivalent takes a list of dicts, each containing "func" (a callable)
    and "args" (positional args), and executes them in order.

    Usage::

        run_after([{"func": my_callback, "args": [arg1, arg2]}])

    Raises ``TypeError`` if any entry is malformed or the function isn't callable.
    """
    for entry in callbacks:
        func = entry.get("func")
        args = entry.get("args", [])
        if not callable(func):
            raise TypeError(
                f"run_after: callback at index {entry} has non-callable 'func'"
            )
        if not isinstance(args, (list, tuple)):
            raise TypeError(
                f"run_after: 'args' must be a list or tuple, got {type(args)}"
            )
        func(*args)


async def task_locked(
    service: EngineService,
    case_id: str,
    idwf: str,
    resource_id: str,
    current_user_id: int | None = None,
) -> dict:
    """Check if a case is locked by another user (mirrors legacy ``Engine::task_locked()`` L480-506).

    The legacy code renders an HTML modal via CodeIgniter's parser. This Python
    equivalent returns structured data instead — pybpm-ui will render its own UI.

    Returns a dict with keys: locked (bool), locked_by, locked_date, resource_id,
    idwf, case. When ``locked=True``, the caller should return HTTP 423 to indicate
    the resource is locked by another user.
    """
    from sqlalchemy import select as sa_select

    from app.models.case import BpmCase

    stmt = sa_select(BpmCase).where(
        BpmCase.idcase == case_id,
        BpmCase.idwf == idwf,
    )
    result = await service.db.execute(stmt)  # type: ignore[misc]
    case_row = result.scalar_one_or_none()

    if not case_row or not case_row.locked_by:
        return {
            "locked": False,
            "locked_by": None,
            "locked_date": None,
            "resource_id": resource_id,
            "idwf": idwf,
            "case": case_id,
        }

    # If the current user is the one who locked it, allow access (mirrors legacy behavior)
    if current_user_id and case_row.locked_by == current_user_id:
        return {
            "locked": False,
            "locked_by": None,
            "locked_date": None,
            "resource_id": resource_id,
            "idwf": idwf,
            "case": case_id,
        }

    # Case is locked by another user — refuse access
    return {
        "locked": True,
        "locked_by": case_row.locked_by,
        "locked_date": str(case_row.locked_date) if case_row.locked_date else None,
        "resource_id": resource_id,
        "idwf": idwf,
        "case": case_id,
    }


def recursive_array_search(
    haystack: dict | list, needle: object, index_key: str | None = None
) -> tuple[object, object] | bool:
    """Deep search through nested dicts/lists for a value (mirrors legacy ``Engine::recursiveArraySearch()`` L917-935).

    Walks the entire tree depth-first and returns ``(parent_key, parent_value)`` when
    the needle is found as a leaf value. When ``index_key`` is provided, only keys with
    that name are considered (e.g., searching for all nodes where key == 'name').

    Returns ``False`` if no match is found, or a tuple of ``(key, value)`` where the
    value matches the needle.

    Legacy used PHP's ``RecursiveArrayIterator`` and ``RecursiveIteratorIterator``; this
    Python implementation uses plain recursion for clarity and performance.
    """

    def _walk(node: object):
        if isinstance(node, dict):
            for k, v in node.items():
                # Check if this key matches the index filter and value matches needle
                if index_key is not None and k != index_key:
                    result = _walk(v)
                    if result is not False:
                        return result
                    continue
                if v == needle:
                    return (k, node)  # type: ignore[return-value]
                result = _walk(v)
                if result is not False:
                    return result
        elif isinstance(node, list):
            for item in node:
                result = _walk(item)
                if result is not False:
                    return result
        return False

    return _walk(haystack) or False  # type: ignore[return-value]
