"""FastAPI router for Case Manager CRUD operations.

Ported from legacy CodeIgniter `dna2bpm/application/modules/dna2/controllers/CaseManager.php`.
Handles case instance management with idcase as the primary parameter.

Endpoints:
- GET    /data/read/{idwf}              - Get cases in Ext.js format (returns totalCount + rows)
- GET    /tokens/status/{idwf}/{idcase} - Get tokens for a case
- GET    /{idcase}                      - Get a single case by ID
- PATCH  /{idcase}                      - Update case attributes
- DELETE /{idcase}                     - Delete a case
- POST   /{idcase}/freez                - Freeze/unfreeze a case
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete as sa_delete
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.case import BpmCase
from app.models.token import Token
from app.schemas.case import (
    CaseRead,
    CasesListResponse,
    DeleteCaseResponse,
    FreezCaseRequest,
    FreezCaseResponse,
    UpdateCaseRequest,
    UpdateCaseResponse,
)

logger = logging.getLogger(__name__)

"""Helper functions for Case Manager endpoints."""

ICON_MAP = {
    'SequenceFlow': 'connector/sequenceflow.png',
    'EndNoneEvent': 'endevent/none.png',
    'EndMessageEvent': 'endevent/message.png',
    'StartMessageEvent ': 'startevent/message.png',
    'Task': 'activity/task.png',
    'CollapsedSubprocess': 'activity/event.subprocess.collapsed.png',
    1: 'activity/event.subprocess.png',
    2: 'activity/expanded.subprocess.png',
    'SubProcess': 'activity/subprocess.png',
    4: 'activity/task.png',
    5: 'artifact/group.png',
    'TextAnnotation': 'artifact/text.annotation.png',
    'IntermediateCancelEvent': 'catching/cancel.png',
    'IntermediateCompensationEventCatching': 'catching/compensation.png',
    'IntermediateConditionalEvent': 'catching/conditional.png',
    'IntermediateErrorEvent': 'catching/error.png',
    'IntermediateEscalationEvent': 'catching/escalation.png',
    'IntermediateLinkEventCatching': 'catching/link.png',
    'IntermediateMessageEventCatching': 'catching/message.png',
    'IntermediateParallelMultipleEventCatching': 'catching/multiple.parallel.png',
    'IntermediateMultipleEventCatching': 'catching/multiple.png',
    'IntermediateSignalEventCatching': 'catching/signal.png',
    'IntermediateTimerEvent': 'catching/timer.png',
    'Association_Bidirectional': 'connector/association.bidirectional.png',
    'Association_Undirected': 'connector/association.undirected.png',
    'Association_Unidirectional': 'connector/association.unidirectional.png',
    'MessageFlow': 'connector/messageflow.png',
    'DataObject': 'dataobject/data.object.png',
    'DataStore': 'dataobject/data.store.png',
    'ITSystem': 'dataobject/it.system.png',
    'Message': 'dataobject/message.png',
    'EndCancelEvent': 'endevent/cancel.png',
    'EndCompensationEvent': 'endevent/compensation.png',
    'EndErrorEvent': 'endevent/error.png',
    'EndEscalationEvent': 'endevent/escalation.png',
    'EndMultipleEvent': 'endevent/multiple.png',
    'EndSignalEvent': 'endevent/signal.png',
    'EndTerminateEvent': 'endevent/terminate.png',
    'ComplexGateway': 'gateway/complex.png',
    'EventbasedGateway': 'gateway/eventbased.png',
    'Exclusive_Databased_Gateway': 'gateway/exclusive.databased.png',
    'InclusiveGateway': 'gateway/inclusive.png',
    'ParallelGateway': 'gateway/parallel.png',
    'StartCompensationEvent': 'startevent/compensation.png',
    'StartConditionalEvent': 'startevent/conditional.png',
    'StartErrorEvent': 'startevent/error.png',
    'StartEscalationEvent': 'startevent/escalation.png',
    'StartMessageEvent': 'startevent/message.png',
    'StartParallelMultipleEvent': 'startevent/multiple.parallel.png',
    'StartMultipleEvent': 'startevent/multiple.png',
    'StartNoneEvent': 'startevent/none.png',
    'StartSignalEvent': 'startevent/signal.png',
    'StartTimerEvent': 'startevent/timer.png',
    'Lane': 'swimlane/lane.png',
    'Pool': 'swimlane/pool.png',
    'processparticipant': 'swimlane/process.participant.png',
    'IntermediateCompensationEventThrowing': 'throwing/compensation.png',
    'IntermediateEscalationEventThrowing': 'throwing/escalation.png',
    'IntermediateLinkEventThrowing': 'throwing/link.png',
    'IntermediateMessageEventThrowing': 'throwing/message.png',
    'IntermediateMultipleEventThrowing': 'throwing/multiple.png',
    'IntermediateEvent': 'throwing/none.png',
    'IntermediateSignalEventThrowing': 'throwing/signal.png',
}


def get_icon(token_type: str) -> str:
    """Get the icon path for a token type, matching legacy Bpm.php get_icon().

    Args:
        token_type: The BPMN element type (e.g., 'Task', 'EndNoneEvent')

    Returns:
        Full icon path string if found, empty string otherwise
    """
    return ICON_MAP.get(token_type, "")


router = APIRouter(prefix="/bpm/case_manager", tags=["case-manager"])


async def get_db():
    """FastAPI dependency for async database session."""
    from extensions import async_session_factory

    async with async_session_factory() as db:
        yield db


@router.get("/data/read/{idwf}", status_code=status.HTTP_200_OK)
async def read_cases(
    idwf: str,
    db: AsyncSession = Depends(get_db),
):
    """Get cases for a workflow in Ext.js compatible format.

    Ported from legacy CaseManager::read() method.
    Returns data in Ext.data.Store format with totalCount and rows array containing
    MongoDB-style _id structure ($id field) and formatted date fields.

    Args:
        idwf: Workflow/model identifier to fetch cases for

    Raises:
        HTTPException: 500 on database errors

    Returns:
        Dict with 'totalCount' (int) and 'rows' (list of case dicts) in Ext.js format — empty if no cases found for the workflow
    """
    # Fetch all cases for this workflow (legacy reads by idwf)
    stmt = (
        select(BpmCase).where(BpmCase.idwf == idwf).order_by(BpmCase.created_at.desc())
    )

    result = await db.execute(stmt)
    cases = result.scalars().all()

    # Convert to Ext.js format with MongoDB-style _id and formatted dates
    rows = []
    for case in cases:
        # Format date as MM/DD/YYYY (legacy uses this format)
        check_date_str = ""
        if case.created_at:
            check_date_str = case.created_at.strftime("%m/%d/%Y")

        # Get initiator user info if available
        user_name = "admin"  # default
        iduser = None
        if case.initiator_id:
            from app.models.user import User

            user_stmt = select(User).where(User.idu == case.initiator_id)
            user_result = await db.execute(user_stmt)
            user = user_result.scalar_one_or_none()
            if user and hasattr(user, "name"):
                user_name = user.name or "admin"
            iduser = case.initiator_id

        rows.append(
            {
                "_id": {"$id": str(case.idcase)},  # MongoDB-style _id with $id field
                "id": case.idcase,
                "idwf": case.idwf,
                "iduser": iduser or 0,
                "status": case.status,
                "checkdate": case.created_at.strftime("%Y-%m-%d %H:%M:%S")
                if case.created_at
                else "",
                "user": user_name,
                "date": check_date_str,
            }
        )

    return {
        "totalCount": len(rows),
        "rows": rows,
    }


@router.get("/tokens/status/{idwf}/{idcase}", status_code=status.HTTP_200_OK)
async def get_token_status(
    idwf: str,
    idcase: str,
    db: AsyncSession = Depends(get_db),
):
    """Get tokens for a case in Ext.js compatible format.

    Ported from legacy Engine::tokens() method.
    Returns token information including user assignments and task status.

    Args:
        idwf: Workflow/model identifier
        idcase: Case instance identifier

    Returns:
        Dict with 'totalCount' (int) and 'rows' (list of token dicts) in Ext.js format

    Raises:
        HTTPException: 404 if case not found
    """
    # Validate case exists
    stmt = select(BpmCase).where(BpmCase.idcase == idcase, BpmCase.idwf == idwf)
    result = await db.execute(stmt)
    case: BpmCase | None = result.scalar_one_or_none()

    if case is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Case '{idcase}' does not exist in workflow '{idwf}'",
        )

    # Fetch all tokens for this case
    stmt = select(Token).where(Token.case_id == idcase).order_by(Token.idtoken)

    result = await db.execute(stmt)
    tokens = result.scalars().all()

    from app.models.user import User


    # Convert to Ext.js format matching legacy Case_manager.php
    rows = []
    for token in tokens:
        assigned_ids = getattr(token, 'assign', []) or []
        primary_uid = assigned_ids[0] if assigned_ids else None

        # Get user nick (legacy uses $user->nick, not name)
        user_nick = "admin"  # default
        id_user = primary_uid or 0
        if primary_uid:
            user_stmt = select(User).where(User.idu == primary_uid)
            user_result = await db.execute(user_stmt)
            user = user_result.scalar_one_or_none()
            if user and hasattr(user, "nick"):
                user_nick = user.nick or "admin"
            elif user and hasattr(user, "name"):
                user_nick = user.name or "admin"

        # Get lockedBy user nick (legacy field)
        locked_by_uid = getattr(token, 'locked_by', None)
        locked_by_nick = None
        if locked_by_uid:
            lock_user_stmt = select(User).where(User.idu == locked_by_uid)
            lock_user_result = await db.execute(lock_user_stmt)
            lock_user = lock_user_result.scalar_one_or_none()
            if lock_user and hasattr(lock_user, "nick"):
                locked_by_nick = lock_user.nick

        # Format date as MM/DD/YYYY (legacy dateFmt uses this format)
        check_date_str = ""
        token_check_date = getattr(token, 'checkdate', None) or getattr(token, 'updated_at', None)
        if token_check_date:
            check_date_str = token_check_date.strftime("%m/%d/%Y")

        # Get icon based on token type (matches legacy $this->bpm->get_icon())
        token_type = getattr(token, 'type', '') or ''
        icon_path = get_icon(token_type) or f"{token_type}.png"
        icon_html = f"<img src='/static/editor/stencilsets/bpmn2.0/icons/{icon_path}' />" if icon_path else ""

        # Get title from name field (legacy: $token['title']=$token['name'])
        token_title = getattr(token, 'name', '') or ''

        # Calculate microtime from check_date (Unix timestamp with microseconds)
        microtime_val = 0.0
        interval_obj = {}
        if token_check_date and isinstance(token_check_date, datetime):
            epoch = datetime(1970, 1, 1, tzinfo=token_check_date.tzinfo or UTC)
            delta = token_check_date - epoch
            microtime_val = delta.total_seconds()

            # Build interval breakdown (legacy format)
            total_days = int(delta.days)
            hours, remainder = divmod(int(delta.seconds), 3600)
            minutes, seconds = divmod(remainder, 60)
            microseconds = delta.microseconds / 1_000_000

            interval_obj = {
                "y": 0,
                "m": 0,
                "d": total_days % 30,
                "h": hours,
                "i": minutes,
                "s": seconds,
                "f": round(microseconds, 6),
                "weekday": 0,
                "weekday_behavior": 0,
                "first_last_day_of": 0,
                "invert": 0,
                "days": total_days,
                "special_type": 0,
                "special_amount": 0,
                "have_weekday_relative": 0,
                "have_special_relative": 0,
            }

        # Get full checkdate string (YYYY-MM-DD HH:MM:SS) for API compatibility
        check_date_full = ""
        if token_check_date:
            check_date_full = token_check_date.strftime("%Y-%m-%d %H:%M:%S")

        rows.append(
            {
                "iduser": id_user,
                "status": token.status,
                "idwf": token.idwf,
                "case": token.case_id,
                "resourceId": token.resource_id,
                "type": token.type,
                "run": getattr(token, 'run_count', 0) or 0,
                "checkdate": check_date_full,
                "microtime": microtime_val,
                "interval": interval_obj,
                "lockedBy": locked_by_nick,
                "user": user_nick,
                "date": check_date_str,
                "icon": icon_html,
                "title": token_title,
            }
        )

    return {
        "totalCount": len(rows),
        "rows": rows,
    }


@router.get("/{idcase}", response_model=CaseRead, status_code=status.HTTP_200_OK)
async def get_case(
    idcase: str,
    db: AsyncSession = Depends(get_db),
):
    """Get a single case by its ID.

    Ported from legacy CaseManager::get_case() method.
    Returns case details including status, data, and metadata in JSON format.

    Args:
        idcase: The unique identifier of the case to retrieve

    Returns:
        CaseRead model with all case attributes in JSON format

    Raises:
        HTTPException: 404 if case not found
    """
    stmt = select(BpmCase).where(BpmCase.idcase == idcase)
    result = await db.execute(stmt)
    case: BpmCase | None = result.scalar_one_or_none()

    if case is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Case '{idcase}' not found",
        )

    return case


@router.patch("/{idcase}", response_model=UpdateCaseResponse)
async def update_case(
    idcase: str,
    request: UpdateCaseRequest,
    db: AsyncSession = Depends(get_db),
):
    """Update case attributes.

    Ported from legacy CaseManager::update() method.
    Updates status, data variables, or parent information for a running case.

    Args:
        idcase: The unique identifier of the case to update
        request: UpdateCaseRequest with fields to modify

    Returns:
        UpdateCaseResponse indicating success/failure

    Raises:
        HTTPException: 404 if case not found
    """
    stmt = select(BpmCase).where(BpmCase.idcase == idcase)
    result = await db.execute(stmt)
    case: BpmCase | None = result.scalar_one_or_none()

    if case is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Case '{idcase}' not found",
        )

    # Update provided fields
    if request.status is not None:
        case.status = request.status

    if request.data is not None:
        case.data = request.data

    if request.parent_json is not None:
        case.parent_json = request.parent_json

    await db.commit()
    await db.refresh(case)

    logger.info(f"Case {idcase} updated successfully")

    return UpdateCaseResponse(
        ok=True,
        msg="Case updated successfully",
        idcase=idcase,
    )


@router.post("/{idcase}/freez", response_model=FreezCaseResponse)
async def freez_case(
    idcase: str,
    request: FreezCaseRequest,
    db: AsyncSession = Depends(get_db),
):
    """Freeze or unfreeze a case.

    Ported from legacy CaseManager::freez() method.
    Toggles the locked_by status to pause/resume case processing.

    Args:
        idcase: The unique identifier of the case to freeze/unfreeze
        request: FreezCaseRequest with user ID performing the action

    Returns:
        FreezCaseResponse with updated lock information

    Raises:
        HTTPException: 404 if case not found
    """
    stmt = select(BpmCase).where(BpmCase.idcase == idcase)
    result = await db.execute(stmt)
    case: BpmCase | None = result.scalar_one_or_none()

    if case is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Case '{idcase}' not found",
        )

    # Toggle freeze state based on locked_by presence
    msg = "Case status unchanged"  # default message
    if request.iduser is not None:
        if case.locked_by == request.iduser:
            # Unfreeze - clear lock
            case.locked_by = None
            case.locked_date = None
            msg = "Case unfrozen successfully"
        else:
            # Freeze - set lock
            from datetime import datetime

            case.locked_by = request.iduser
            case.locked_date = datetime.now(UTC)
            msg = f"Case frozen by user {request.iduser}"

    await db.commit()
    await db.refresh(case)

    logger.info(f"Case {idcase} freeze status updated: locked_by={case.locked_by}")

    return FreezCaseResponse(
        ok=True,
        msg=msg,
        idcase=idcase,
        locked_by=case.locked_by,
    )


@router.delete("/{idcase}", response_model=DeleteCaseResponse)
async def delete_case(
    idcase: str,
    db: AsyncSession = Depends(get_db),
):
    """Delete a case and all its associated tokens.

    Ported from legacy CaseManager::delete() method.
    Removes the case record and cascades to delete all related tokens.

    Args:
        idcase: The unique identifier of the case to delete

    Returns:
        DeleteCaseResponse indicating success/failure

    Raises:
        HTTPException: 404 if case not found
    """
    stmt = select(BpmCase).where(BpmCase.idcase == idcase)
    result = await db.execute(stmt)
    case = result.scalar_one_or_none()

    if case is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Case '{idcase}' not found",
        )

    # Delete all tokens first (cascade should handle this in DB)
    token_delete = sa_delete(Token).where(Token.case_id == idcase)
    await db.execute(token_delete)

    # Delete the case itself
    delete_stmt = sa_delete(BpmCase).where(BpmCase.idcase == idcase)
    await db.execute(delete_stmt)

    await db.commit()

    logger.info(f"Case {idcase} deleted successfully with all tokens")

    return DeleteCaseResponse(
        ok=True,
        msg="Case and associated tokens deleted successfully",
        idcase=idcase,
    )


@router.get("", response_model=list[CasesListResponse], status_code=status.HTTP_200_OK)
async def list_cases(
    db: AsyncSession = Depends(get_db),
):
    """List all cases.

    Retrieves a paginated list of case instances for display in the UI.

    Returns:
        List[CasesListResponse] containing basic case information

    Note:
        For large datasets, implement pagination parameters (skip, limit)
    """
    stmt = select(BpmCase).order_by(BpmCase.updated_at.desc())
    result = await db.execute(stmt)
    cases = result.scalars().all()

    # Convert to response models
    case_responses = []
    for case in cases:
        case_responses.append(
            CasesListResponse(
                idcase=case.idcase,
                idwf=case.idwf,
                status=case.status,
                initiator_id=case.initiator_id,
                created_at=case.created_at,
            )
        )

    return case_responses


@router.get(
    "/search/{status}",
    response_model=list[CasesListResponse],
    status_code=status.HTTP_200_OK,
)
async def search_cases(
    status_filter: str,
    db: AsyncSession = Depends(get_db),
):
    """Search cases by status.

    Ported from legacy CaseManager::search() method.
    Filters cases based on their current status (open, running, paused, closed).

    Args:
        status_filter: The status to filter by

    Returns:
        List[CasesListResponse] matching the status filter
    """
    stmt = (
        select(BpmCase)
        .where(BpmCase.status == status_filter)
        .order_by(BpmCase.updated_at.desc())
    )

    result = await db.execute(stmt)
    cases = result.scalars().all()

    case_responses = []
    for case in cases:
        case_responses.append(
            CasesListResponse(
                idcase=case.idcase,
                idwf=case.idwf,
                status=case.status,
                initiator_id=case.initiator_id,
                created_at=case.created_at,
            )
        )

    return case_responses
