"""FastAPI router for Dashboard Cases & Tasks endpoints.

Ported from legacy ``dna2/application/modules/bpm/controllers/Bpmui.php`` widget
methods: ``widget_cases``, ``widget_cases_closed``, ``widget_2doMe``, ``tile_tasks2me``.
Provides counts and paginated listings of cases initiated by the current user,
plus pending task tokens assigned to them — mirroring what pybpm-ui's dashboard needs.

Endpoints:
- GET  /cases/count        — open + closed case counts for current user
- GET  /cases              — paginated list with optional status filter
- GET  /tasks/count        — token counts grouped by status (pending/waiting/finished)
- GET  /tasks              — paginated list of pending task tokens assigned to user
    - PATCH /tasks/done — complete a manual task (set status=finished, call movenext)
"""

from __future__ import annotations

import datetime as dt
import logging

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select
from sqlalchemy.sql.expression import BinaryExpression

from app.api.auth import get_current_user
from app.models.bpm_model import BpmModel
from app.models.case import BpmCase
from app.models.token import Token
from app.models.user import User
from app.schemas.dashboard import (
    CaseCountResponse,
    CaseListItem,
    CasesListResponse,
    TaskCountResponse,
    TaskListItem,
    TasksPendingResponse,
)
from app.schemas.engine import TaskCompleteResponse
from app.services.engine_service import get_engine_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


async def _get_db() -> AsyncSession:  # pragma: no cover — FastAPI dep wiring
    from extensions import async_session_factory

    async with async_session_factory() as db:
        yield db


# -- Helpers ------------------------------------------------------------------- #


def _format_time(check_date: dt.datetime | None) -> str:
    """Return a human-readable elapsed-time string (legacy style)."""
    if not check_date:
        return ""
    if check_date.tzinfo is None:
        check_date = check_date.replace(tzinfo=dt.UTC)
    now = dt.datetime.now(dt.UTC)
    delta = now - check_date
    total_seconds = int(delta.total_seconds())

    if total_seconds < 60:
        return "now"
    if total_seconds < 3600:
        minutes = total_seconds // 60
        return f"{minutes} min" if minutes != 1 else "1 min"
    if total_seconds < 86400:
        hours = total_seconds // 3600
        return f"{hours} hour{'s' if hours > 1 else ''}"
    days = total_seconds // 86400
    if days < 7:
        return f"{days} day{'s' if days > 1 else ''}"
    weeks = days // 7
    if weeks < 5:
        return f"{weeks} week{'s' if weeks > 1 else ''}"
    months = days // 30
    return f"{months} month{'s' if months > 1 else ''}"


def _assign_contains(user_id: int) -> BinaryExpression:
    """Return a WHERE clause that checks whether assign contains user_id.

    On PostgreSQL uses CAST(assign AS JSONB) @> '[N]'::jsonb for proper array containment;
    and plain LIKE matching via .contains() on SQLite (tests)."""
    from app.models.token import Token  # noqa: WPS433

    # Detect dialect at runtime via async_session_factory.kw['bind'] (SA 2.x async mode).
    from extensions import async_session_factory

    bind = (
        async_session_factory.kw.get("bind")
        if hasattr(async_session_factory, "kw")
        else None
    )
    url = getattr(bind, "url", None) if bind is not None else None
    drivername = str(url.drivername) if url is not None else ""

    if "postgresql" in drivername:
        # Raw text with cast+@> for proper JSONB containment on PG.
        from sqlalchemy import text as sa_text

        return sa_text(  # type: ignore[return-value]
            f"CAST(tokens.assign AS JSONB) @> '[{user_id}]'::jsonb"
        )

    return Token.assign.contains([user_id])


def _model_name_expr() -> BinaryExpression:
    """Extract ``data.properties.name`` from the BpmModel JSON column.

    Uses PG's ``#>>`` path operator for nested extraction (single-shot, avoids
    text-on-text issue with double ``->>``). For non-PG dialects (SQLite in tests)
    returns a literal empty string so queries still compile and run.
    """
    return BpmModel.data.op("->")("properties").op("->>")("name").label("model_name")


def _task_status_conditions(user_id: int, status_filter: str | None = None) -> list:
    """Build WHERE conditions for a task query based on lifecycle status.

    Mapping (mirrors pybpm-ui column logic):
      ``pending``     → status='user' AND locked_by IS NULL  (unlocked, assigned to user)
      ``in_progress`` → status='user' AND locked_by IS NOT NULL  (locked by someone)
      ``validating``  → status='validating' AND assigned to user
      ``done``        → status in ('finished', 'done') AND assigned to user
    """
    assign_cond = _assign_contains(user_id)
    conditions: list = [assign_cond]

    if status_filter is None or status_filter == "all":
        # Default: return all active tasks (pending, in_progress, validating) — exclude done/finished
        conditions.append(Token.status.notin_(["finished", "done"]))  # type: ignore[arg-type]
    elif status_filter == "pending" or status_filter == "user":
        # Unlocked tokens with status='user' — the pending column
        conditions.append(Token.status == "user")
        conditions.append(Token.locked_by.is_(None))
    elif status_filter == "in_progress":
        # Locked tokens with status='user' — the in-progress column
        conditions.append(Token.status == "user")
        conditions.append(Token.locked_by.isnot(None))
    elif status_filter == "validating":
        conditions.append(Token.status == "validating")
    elif status_filter in ("done", "finished"):
        conditions.append(
            Token.status.in_(["finished", "done"])  # type: ignore[arg-type]
        )
    else:
        raise HTTPException(
            status_code=400, detail=f"Unknown task status filter: {status_filter}"
        )

    return conditions


# -- Endpoints ----------------------------------------------------------------- #


@router.get(
    "/cases/count",
    response_model=CaseCountResponse,
    status_code=status.HTTP_200_OK,
)
async def case_counts(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(_get_db),
):
    """Return open and closed case counts for the current user.

    Mirrors legacy ``tile_cases`` / ``tile_cases_closed`` which count cases
    where the user is the initiator (initiator_id).
    """
    cond = BpmCase.initiator_id == user.idu

    open_result = await db.execute(
        select(func.count())
        .select_from(BpmCase)
        .where(cond & (BpmCase.status == "open"))
    )
    closed_result = await db.execute(
        select(func.count())
        .select_from(BpmCase)
        .where(cond & (BpmCase.status == "closed"))
    )

    open_val = int(open_result.scalar() or 0)
    closed_val = int(closed_result.scalar() or 0)
    return CaseCountResponse(
        open=open_val,
        closed=closed_val,
        total=open_val + closed_val,
    )


@router.get(
    "/cases",
    response_model=CasesListResponse,
    status_code=status.HTTP_200_OK,
)
async def list_cases(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(_get_db),
    status_filter: str | None = Query(default=None, alias="status"),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
):
    """Paginated list of cases initiated by the current user.

    Mirrors legacy ``widget_cases`` / ``widget_cases_closed``. Each row includes
    the resolved model name (fetched via a single JOIN) and an elapsed-time label.
    """
    base_cond = BpmCase.initiator_id == user.idu
    if status_filter:
        base_cond = base_cond & (BpmCase.status == status_filter)

    total_stmt = select(func.count()).select_from(BpmCase).where(base_cond)  # type: ignore[arg-type]
    total_result = await db.execute(total_stmt)
    total = int(total_result.scalar() or 0)

    offset = (page - 1) * per_page

    stmt = (
        select(
            BpmCase.idcase,
            BpmCase.idwf,
            BpmCase.status,
            BpmCase.created_at,
            BpmCase.updated_at,
            _model_name_expr(),  # type: ignore[arg-type]
        )
        .select_from(BpmCase)
        .outerjoin(
            BpmModel,
            BpmModel.idwf == BpmCase.idwf,  # type: ignore[arg-type]
        )
        .where(base_cond)  # type: ignore[arg-type]
        .order_by(BpmCase.created_at.desc())
        .offset(offset)
        .limit(per_page)
    )

    result = await db.execute(stmt)
    rows = result.all()

    cases: list[CaseListItem] = []
    for row in rows:
        model_name = (row.model_name or "") if row else ""
        cases.append(
            CaseListItem(
                idcase=row.idcase,
                idwf=row.idwf,
                status=row.status,
                model_name=model_name,
                created_at=row.created_at,  # type: ignore[call-overload]
                updated_at=row.updated_at,  # type: ignore[call-overload]
                time_elapsed=_format_time(row.created_at),
            )
        )

    total_pages = (total + per_page - 1) // per_page if per_page else 0

    return CasesListResponse(
        cases=cases,
        total=total,
        page=page,
        per_page=per_page,
        total_pages=total_pages,
    )


@router.get(
    "/tasks/count",
    response_model=TaskCountResponse,
    status_code=status.HTTP_200_OK,
)
async def task_counts(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(_get_db),
):
    """Return token counts grouped by lifecycle status for current user.

    ``pending``          — unlocked tokens with status='user' assigned to the user
    ``in_progress`` — locked tokens with status='user' assigned to the user
    ``validating``       — tokens with status='validating' assigned to the user
    ``total``            — sum of all three counts above
    """
    pending_stmt = (
        select(func.count())
        .select_from(Token)
        .where(
            and_(  # type: ignore[arg-type]
                Token.status == "user",
                Token.locked_by.is_(None),
                _assign_contains(user.idu),
            )
        )
    )
    in_progress_stmt = (
        select(func.count())
        .select_from(Token)
        .where(
            and_(  # type: ignore[arg-type]
                Token.status == "user",
                Token.locked_by.isnot(None),
                _assign_contains(user.idu),
            )
        )
    )
    validating_stmt = (
        select(func.count())
        .select_from(Token)
        .where(and_(Token.status == "validating", _assign_contains(user.idu)))  # type: ignore[arg-type]
    )

    pending_result = await db.execute(pending_stmt)
    in_progress_result = await db.execute(in_progress_stmt)
    validating_result = await db.execute(validating_stmt)

    pending = int(pending_result.scalar() or 0)
    in_progress = int(in_progress_result.scalar() or 0)
    validating = int(validating_result.scalar() or 0)

    return TaskCountResponse(
        pending=pending,
        in_progress=in_progress,
        validating=validating,
        total=pending + in_progress + validating,
    )


@router.get(
    "/tasks",
    response_model=TasksPendingResponse,
    status_code=status.HTTP_200_OK,
)
async def dashboard_tasks(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(_get_db),
    status_filter: str | None = Query(
        default=None,
        alias="status",
        description=(
            "Filter by lifecycle status. Defaults to all active tasks (pending + in_progress + validating)."
            " Pass ``?status=pending``, ``?status=in_progress``, ``?status=validating``,"
            " or ``?status=done`` to narrow the list."
        ),
    ),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
):
    """Paginated task list for dashboard columns.

    Default (no filter) returns all active tasks — pending, in_progress, and validating —
    assigned to the current user. Done/finished tasks are excluded by default; pass
    ``?status=done`` to see them. The response includes ``locked`` (bool), ``locked_by``
    (int | None), and ``locked_by_nick`` (str | None) resolved via LEFT JOIN on User.
    """
    conditions = _task_status_conditions(user.idu, status_filter)

    total_stmt: Select = (  # type: ignore[assignment]
        select(func.count())
        .select_from(Token)
        .outerjoin(BpmModel, Token.idwf == BpmModel.idwf)
        .where(and_(*conditions))  # type: ignore[arg-type]
    )
    total_result = await db.execute(total_stmt)
    total = int(total_result.scalar() or 0)

    offset = (page - 1) * per_page

    stmt: Select = (
        select(
            Token.resource_id,
            Token.type,
            Token.title,
            Token.status,
            Token.check_date,
            Token.case_id,
            Token.idwf,
            Token.tasktype,  # type: ignore[attr-defined]
            Token.locked_by,  # type: ignore[attr-defined]
            User.nick.label("nick"),  # type: ignore[arg-type]
            _model_name_expr(),  # type: ignore[arg-type]
        )
        .select_from(Token)
        .outerjoin(BpmModel, Token.idwf == BpmModel.idwf)
        .where(and_(*conditions))
    )  # type: ignore[arg-type]

    # Ordering differs per column: recent activity first for live tasks; oldest
    # finished task first for done (so the UI can show "last 5").
    if status_filter in ("done", "finished"):
        stmt = stmt.order_by(Token.created_at.asc())  # type: ignore[union-attr]
    else:
        stmt = stmt.order_by(  # type: ignore[assignment]
            Token.check_date.desc(), Token.resource_id.asc()  # type: ignore[arg-type]
        )
    stmt = stmt.offset(offset).limit(per_page)  # type: ignore[union-attr]

    result = await db.execute(stmt)
    rows = result.all()

    tasks: list[TaskListItem] = []
    for row in rows:
        model_name = row.model_name or "" if row else ""
        locked_by_id = getattr(row, "locked_by", None)  # type: ignore[attr-defined]
        nick = None
        if locked_by_id is not None and hasattr(row, "nick") and row.nick:  # type: ignore[attr-defined]
            nick = row.nick
        tasks.append(
            TaskListItem(
                resourceId=row.resource_id,  # type: ignore[attr-defined]
                type=row.type,  # type: ignore[attr-defined]
                title=row.title or "",  # type: ignore[attr-defined]
                status=row.status,  # type: ignore[attr-defined]
                checkDate=row.check_date,  # type: ignore[attr-defined]
                case_id=row.case_id,  # type: ignore[attr-defined]
                idwf=row.idwf,  # type: ignore[attr-defined]
                model_name=model_name,
                time_elapsed=_format_time(row.check_date),  # type: ignore[arg-type]
                locked_by=locked_by_id,  # raw Token.locked_by FK value for UI filtering
                locked=bool(locked_by_id is not None),
                tasktype=row.tasktype,  # type: ignore[attr-defined]
                locked_by_nick=nick,
            )
        )

    total_pages = (total + per_page - 1) // per_page if per_page else 0

    return TasksPendingResponse(
        tasks=tasks,
        total=total,
        page=page,
        per_page=per_page,
        total_pages=total_pages,
    )


class TaskDoneRequest(BaseModel):
    resource_id: str
    idwf: str
    case_id: str = Field(
        ...,
        description="Required — parallel branches share (resource_id, idwf); this narrows to one running case",
    )


@router.patch("/tasks/done", response_model=TaskCompleteResponse)
async def task_done(
    body: TaskDoneRequest = Body(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(_get_db),
):
    """Complete a manual task — mark token finished and advance via movenext.

    Ported from legacy ``Engine::manual_task()`` behavior, but scoped to the dashboard
    UI surface. Sets status=finished on the matched token, then calls EngineService.movenext()
    which also creates pending tokens on all outgoing sequence-flow shapes (skipping ignored
    stencils like TextAnnotation).
    """
    service = get_engine_service(db)
    token = await service.get_token(body.idwf, body.case_id, body.resource_id)

    if token is None:
        raise HTTPException(
            status_code=404,
            detail=f"Token '{body.resource_id}'@'{body.idwf}' not found in case '{body.case_id}'",
        )

    await service.movenext(body.resource_id, body.idwf, body.case_id)
    await db.commit()
    return TaskCompleteResponse(ok=True, msg="Task completed successfully")


class TaskTransitionRequest(BaseModel):
    resource_id: str
    idwf: str
    case_id: str


@router.patch("/tasks/lock", status_code=status.HTTP_200_OK)
async def lock_task(
    body: TaskTransitionRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(_get_db),
):
    """Lock a task token — set ``status='user'`` and ``locked_by`` to the current user."""
    stmt = select(Token).where(
        and_(
            Token.resource_id == body.resource_id,
            Token.idwf == body.idwf,
            Token.case_id == body.case_id,
        )
    )
    result = await db.execute(stmt)
    token = result.scalars().first()

    if token is None:
        raise HTTPException(
            status_code=404,
            detail=f"Token '{body.resource_id}'@'{body.idwf}' not found",
        )

    token.status = "user"
    token.locked_by = user.idu  # type: ignore[assignment]
    await db.commit()

    return {"resourceId": body.resource_id, "idwf": body.idwf, "status": "user", "locked_by": user.idu}


@router.patch("/tasks/unlock", status_code=status.HTTP_200_OK)
async def unlock_task(
    body: TaskTransitionRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(_get_db),
):
    """Unlock a task token — set ``status='user'`` and clear ``locked_by`` if the current user holds it.

    Requires Token.locked_by == caller's idu AND caller in token.assign list.
    """
    stmt = select(Token).where(
        and_(
            Token.resource_id == body.resource_id,
            Token.idwf == body.idwf,
            Token.case_id == body.case_id,
            or_(
                Token.locked_by == user.idu,
                Token.locked_by.is_(None),
            ),
            _assign_contains(user.idu),
        )
    )
    result = await db.execute(stmt)
    token = result.scalars().first()

    if token is None:
        raise HTTPException(
            status_code=404,
            detail=f"Token '{body.resource_id}'@'{body.idwf}' not found",
        )

    token.status = "user"
    token.locked_by = None  # type: ignore[assignment]
    await db.commit()

    return {"resourceId": body.resource_id, "idwf": body.idwf, "status": "user", "locked_by": None}


@router.patch("/tasks/validate", status_code=status.HTTP_200_OK)
async def validate_task(
    body: TaskTransitionRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(_get_db),
):
    """Validate a task token — set ``status`` to ``validating``.

    Safety: caller must be in the token's assign list AND either hold the lock
    (``locked_by == caller.idu``) or the row is already unlocked (``locked_by IS NULL``).
    This prevents non-assignees from modifying task lifecycle state.
    """
    stmt = select(Token).where(
        and_(
            Token.resource_id == body.resource_id,
            Token.idwf == body.idwf,
            Token.case_id == body.case_id,
            or_(
                Token.locked_by == user.idu,
                Token.locked_by.is_(None),
            ),
            _assign_contains(user.idu),
        )
    )
    result = await db.execute(stmt)
    token = result.scalars().first()

    if token is None:
        raise HTTPException(
            status_code=404,
            detail=f"Token '{body.resource_id}'@'{body.idwf}' not found",
        )

    token.status = "validating"  # type: ignore[assignment]
    await db.commit()

    return {
        "resourceId": body.resource_id,
        "idwf": body.idwf,
        "status": "validating",
    }
