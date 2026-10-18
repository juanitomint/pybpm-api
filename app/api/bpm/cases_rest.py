"""FastAPI router for Cases REST API.

Standard REST endpoints matching Ext.data.Store type: 'rest' proxy conventions.
Separate from the legacy case_manager endpoints kept for backwards compatibility.

Endpoints:
- GET    /bpm/cases/{idwf}                  - List cases for a workflow (paginated)
- GET    /bpm/cases/{idwf}/{case_id}        - Get a single case
- PUT    /bpm/cases/{idwf}/{case_id}        - Update a case (Ext sends full record as JSON body)
- DELETE /bpm/cases/{idwf}/{case_id}        - Delete a case
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from sqlalchemy import delete as sa_delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.case import BpmCase
from app.models.token import Token
from app.schemas.case import DeleteCaseResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/bpm/cases", tags=["cases-rest"])


async def get_db():
    """FastAPI dependency for async database session."""
    from extensions import async_session_factory

    async with async_session_factory() as db:
        yield db


async def _get_user_nick(db: AsyncSession, uid: int) -> str:
    """Look up a user's nick by ID, defaulting to '???'.

    Ported from legacy: $user->nick (not name).
    """
    from app.models.user import User

    user_stmt = select(User).where(User.idu == uid)
    user_result = await db.execute(user_stmt)
    user = user_result.scalar_one_or_none()
    if user and hasattr(user, "nick"):
        return user.nick or "???"
    if user and hasattr(user, "name"):
        return user.name or "???"
    return "???"


def _case_to_legacy_row(case: BpmCase, user_nick: str) -> dict:
    """Convert a BpmCase row to the legacy Ext.js data/read format.

    Ported from legacy Case_manager::Data() — mirrors the exact field names
    and structure the Ext.js store expects.
    """
    check_date_str = ""
    if case.created_at:
        check_date_str = case.created_at.strftime("%m/%d/%Y")

    iduser = case.initiator_id or 0

    return {
        "_id": {"$id": str(case.idcase)},
        "id": case.idcase,
        "idwf": case.idwf,
        "iduser": iduser,
        "status": case.status,
        "checkdate": (
            case.created_at.strftime("%Y-%m-%d %H:%M:%S")
            if case.created_at
            else ""
        ),
        "user": user_nick,
        "date": check_date_str,
    }


@router.get("/{idwf}", status_code=status.HTTP_200_OK)
async def list_cases(
    idwf: str,
    start: int = Query(default=0),
    limit: int = Query(default=20),
    sort: str = Query(default=""),
    query: str = Query(default=""),
    db: AsyncSession = Depends(get_db),
):
    """List cases for a workflow with pagination.

    Ported from legacy Case_manager::Data('read'). Accepts sort/limit/start
    from query params (Ext.data.Store type: 'rest' sends GET).

    Returns { totalCount: N, rows: [...] } matching legacy format exactly.
    """
    # Parse sort from JSON (legacy: json_decode($this->input->post('sort')))
    sort_dict = {}
    if sort:
        try:
            sort_obj = json.loads(sort)
            if isinstance(sort_obj, list):
                for item in sort_obj:
                    prop = item.get("property")
                    direction = item.get("direction", "ASC")
                    if prop:
                        sort_dict[prop] = 1 if direction == "ASC" else -1
        except json.JSONDecodeError:
            sort_dict = {}

    # Default sort by checkdate descending
    if not sort_dict:
        sort_dict["checkdate"] = -1

    # Build SQLAlchemy order_by from sort_dict
    order_clauses = []
    for col_name, direction in sort_dict.items():
        col = getattr(BpmCase, col_name, None)
        if col is not None:
            order_clauses.append(col.desc() if direction == -1 else col.asc())

    # Query cases
    stmt = select(BpmCase).where(BpmCase.idwf == idwf)
    if order_clauses:
        stmt = stmt.order_by(*order_clauses)
    else:
        stmt = stmt.order_by(BpmCase.updated_at.desc())

    # Count total
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total_result = await db.execute(count_stmt)
    total: int = total_result.scalar()

    # Paginate
    stmt = stmt.offset(start).limit(limit)
    result = await db.execute(stmt)
    cases = result.scalars().all()

    from fastapi.responses import JSONResponse

    rows = []
    for case in cases:
        # Set user nick
        user_nick = "???"
        if case.initiator_id:
            user_nick = await _get_user_nick(db, case.initiator_id)

        # Build row
        row = _case_to_legacy_row(case, user_nick)

        # Pseudo status: if locked, override status to 'locked'
        if case.locked_by is not None:
            row["status"] = "locked"

        rows.append(row)

    resp = JSONResponse(content={"totalCount": total, "rows": rows})
    return resp


@router.get("/{idwf}/{case_id}", status_code=status.HTTP_200_OK)
async def get_case(
    idwf: str,
    case_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get a single case by its ID.

    Returns the same row format as /bpm/case_manager/data/read/{idwf}.
    """
    stmt = select(BpmCase).where(
        BpmCase.idcase == case_id, BpmCase.idwf == idwf
    )
    result = await db.execute(stmt)
    case: BpmCase | None = result.scalar_one_or_none()

    if case is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Case '{case_id}' not found in workflow '{idwf}'",
        )

    user_nick = "???"
    if case.initiator_id:
        user_nick = await _get_user_nick(db, case.initiator_id)

    row = _case_to_legacy_row(case, user_nick)
    if case.locked_by is not None:
        row["status"] = "locked"

    return row


@router.put("/{idwf}/{case_id}", status_code=status.HTTP_200_OK)
async def update_case(
    idwf: str,
    case_id: str,
    case_data: dict = Body(default={}),
    db: AsyncSession = Depends(get_db),
):
    """Update a case instance."""
    stmt = select(BpmCase).where(
        BpmCase.idcase == case_id, BpmCase.idwf == idwf
    )
    result = await db.execute(stmt)
    case: BpmCase | None = result.scalar_one_or_none()

    if case is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Case '{case_id}' not found in workflow '{idwf}'",
        )

    for field in ["status", "data", "parent_json", "locked_by"]:
        if field in case_data and case_data[field] is not None:
            setattr(case, field, case_data[field])

    await db.commit()
    await db.refresh(case)

    logger.info(f"Case {case_id} updated")

    user_nick = "???"
    if case.initiator_id:
        user_nick = await _get_user_nick(db, case.initiator_id)

    row = _case_to_legacy_row(case, user_nick)
    if case.locked_by is not None:
        row["status"] = "locked"

    return row


@router.delete("/{idwf}/{case_id}", response_model=DeleteCaseResponse, status_code=status.HTTP_200_OK)
async def delete_case(
    idwf: str,
    case_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Delete a case and all its associated tokens."""
    stmt = select(BpmCase).where(
        BpmCase.idcase == case_id, BpmCase.idwf == idwf
    )
    result = await db.execute(stmt)
    case = result.scalar_one_or_none()

    if case is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Case '{case_id}' not found in workflow '{idwf}'",
        )

    await db.execute(sa_delete(Token).where(Token.case_id == case_id))
    await db.execute(sa_delete(BpmCase).where(BpmCase.idcase == case_id))
    await db.commit()

    logger.info(f"Case {case_id} deleted")
    return DeleteCaseResponse(ok=True, msg="Case deleted", idcase=case_id)
