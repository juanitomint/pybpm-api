"""FastAPI router for Token Manager CRUD operations.

Ported from legacy CodeIgniter `dna2bpm/application/modules/bpm/controllers/Engine.php`
specifically the token_checkin, assign_task, and token_status methods.

Endpoints:
- GET    /tokens/{idwf}/{idcase}              - List all tokens for a case
- POST   /tokens/create/{idwf}/{idcase}        - Create new token (legacy Engine::token_checkin)
- PATCH  /tokens/update/{idwf}/{idcase}/{idtoken} - Update token status/assign
- DELETE /tokens/delete/{idwf}/{idcase}/{idtoken} - Delete individual token
- POST   /tokens/assign/{idwf}/{idcase}/{idtoken} - Assign users to token (legacy Engine::assign_task)

All endpoints use {idwf}, {idcase}, and optionally {idtoken} as parameters.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete as sa_delete
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bpm_model import BpmModel
from app.models.case import BpmCase
from app.models.token import Token
from app.schemas.token import (
    TokenAssignRequest,
    TokenAssignResponse,
    TokenCreate,
    TokenCreateResponse,
    TokenDeleteResponse,
    TokenListResponse,
    TokenUpdate,
    TokenUpdateResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tokens", tags=["token-manager"])


async def get_db():
    """FastAPI dependency for async database session."""
    from extensions import async_session_factory

    async with async_session_factory() as db:
        yield db


@router.get(
    "/{idwf}/{idcase}",
    response_model=list[TokenListResponse],
    status_code=status.HTTP_200_OK,
)
async def list_tokens(
    idwf: str,
    idcase: str,
    db: AsyncSession = Depends(get_db),
):
    """List all tokens for a specific case.

    Ported from legacy Engine::get_all_tokens($model, $idwf, $case) method.
    Returns complete list of tokens with their current status and assignments.

    Args:
        idwf: Workflow/model identifier
        idcase: Case identifier

    Returns:
        List[TokenListResponse] containing all token information

    Raises:
        HTTPException: 404 if model or case not found
    """
    # Validate model exists
    stmt = select(BpmModel).where(BpmModel.idwf == idwf)
    result = await db.execute(stmt)
    if result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Model '{idwf}' does not exist",
        )

    # Validate case exists
    stmt = select(BpmCase).where(BpmCase.idcase == idcase)
    result = await db.execute(stmt)
    if result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Case '{idcase}' not found",
        )

    # Fetch all tokens for this case
    stmt = (
        select(Token)
        .where(
            Token.idwf == idwf,
            Token.case_id == idcase,
        )
        .order_by(Token.created_at.asc())
    )

    result = await db.execute(stmt)
    tokens = result.scalars().all()

    token_responses = []
    for token in tokens:
        token_responses.append(
            TokenListResponse(
                idtoken=token.idtoken,
                idwf=token.idwf,
                case_id=token.case_id,
                resource_id=token.resource_id,
                type=token.type,
                status=token.status,
                assign=token.assign,
                check_date=token.check_date,
                createdAt=token.created_at,
            )
        )

    return token_responses


@router.post(
    "/create/{idwf}/{idcase}",
    response_model=TokenCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_token(
    idwf: str,
    idcase: str,
    request: TokenCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a new token for a shape in a case.

    Ported from legacy Engine::token_checkin($model, $idwf, $case, $resourceId, $type) method.
    Used to initialize tokens when starting cases or advancing workflow.

    Args:
        idwf: Workflow/model identifier
        idcase: Case identifier
        request: TokenCreate with resource_id, type_, and optional status

    Returns:
        TokenCreateResponse with new token ID

    Raises:
        HTTPException: 404 if model or case not found
        HTTPException: 409 if token already exists for this shape
    """
    # Validate model exists
    stmt = select(BpmModel).where(BpmModel.idwf == idwf)
    result = await db.execute(stmt)
    if result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Model '{idwf}' does not exist",
        )

    # Validate case exists
    stmt = select(BpmCase).where(BpmCase.idcase == idcase)
    result = await db.execute(stmt)
    if result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Case '{idcase}' not found",
        )

    # Check for duplicate token (legacy uses checkin logic to avoid duplicates)
    stmt = select(Token).where(
        Token.idwf == idwf,
        Token.case_id == idcase,
        Token.resource_id == request.resource_id,
    )
    result = await db.execute(stmt)
    if result.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Token already exists for shape '{request.resource_id}'",
        )

    # Create new token
    now = datetime.now(UTC)
    token = Token(
        idwf=idwf,
        case_id=idcase,
        resource_id=request.resource_id,
        type=request.type_,  # alias in schema
        status=request.status or "pending",
        assign=[],
        external_data={},
        created_at=now,
        updated_at=now,
    )

    db.add(token)
    await db.flush()  # Get auto-generated IDtoken
    await db.commit()

    logger.info(
        f"Created token {token.idtoken} for shape '{request.resource_id}' in case '{idcase}'"
    )

    return TokenCreateResponse(
        ok=True,
        msg="Token created successfully",
        idtoken=token.idtoken,
    )


@router.patch("/{idwf}/{idcase}/{idtoken}", response_model=TokenUpdateResponse)
async def update_token(
    idwf: str,
    idcase: str,
    idtoken: int,
    request: TokenUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update an existing token's status or assignment.

    Ported from legacy Engine::update_token($model, $idwf, $idcase, $idtoken) method.
    Updates status (pending/waiting/finished), user assignments, or external data.

    Args:
        idwf: Workflow/model identifier
        idcase: Case identifier
        idtoken: Token ID to update
        request: TokenUpdate with fields to modify

    Returns:
        TokenUpdateResponse confirming the update

    Raises:
        HTTPException: 404 if token not found or doesn't belong to this case
    """
    # Find token by ID and validate ownership
    stmt = select(Token).where(
        Token.idtoken == idtoken,
        Token.idwf == idwf,
        Token.case_id == idcase,
    )
    result = await db.execute(stmt)
    token = result.scalar_one_or_none()

    if token is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Token '{idtoken}' not found for case '{idcase}'",
        )

    # Update provided fields
    if request.status is not None:
        old_status = token.status
        token.status = request.status
        logger.info(f"Token {idtoken} status changed: {old_status} -> {request.status}")

    if request.assign is not None:
        old_assign = token.assign or []
        token.assign = request.assign
        logger.info(f"Token {idtoken} assign updated: {old_assign} -> {request.assign}")

    if request.external_data is not None:
        # Merge external data (legacy merges nested dictionaries)
        if token.external_data is None:
            token.external_data = {}
        for origin, data in request.external_data.items():
            if isinstance(data, dict):
                token.external_data.setdefault(origin, {}).update(data)
            else:
                token.external_data[origin] = data

    # Update timestamp
    token.updated_at = datetime.now(UTC)

    await db.commit()
    await db.refresh(token)

    logger.info(f"Token {idtoken} updated successfully")

    return TokenUpdateResponse(
        ok=True,
        msg="Token updated successfully",
        idtoken=idtoken,
    )


@router.delete("/{idwf}/{idcase}/{idtoken}", response_model=TokenDeleteResponse)
async def delete_token(
    idwf: str,
    idcase: str,
    idtoken: int,
    db: AsyncSession = Depends(get_db),
):
    """Delete an individual token.

    Ported from legacy Engine::delete_token($model, $idwf, $idcase, $idtoken) method.
    Removes a specific token (typically after completion or cancellation).

    Args:
        idwf: Workflow/model identifier
        idcase: Case identifier
        idtoken: Token ID to delete

    Returns:
        TokenDeleteResponse confirming the deletion

    Raises:
        HTTPException: 404 if token not found or doesn't belong to this case
    """
    # Find token by ID and validate ownership
    stmt = select(Token).where(
        Token.idtoken == idtoken,
        Token.idwf == idwf,
        Token.case_id == idcase,
    )
    result = await db.execute(stmt)
    token = result.scalar_one_or_none()

    if token is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Token '{idtoken}' not found for case '{idcase}'",
        )

    # Record history before deletion (legacy records all state changes)
    from app.models.token import TokenHistory

    history = TokenHistory(
        idwf=token.idwf,
        case_id=token.case_id,
        resource_id=token.resource_id,
        type=token.type,
        status="deleted",
        check_date=datetime.now(UTC),
        run_count=token.run_count,
    )

    db.add(history)

    # Delete the token itself
    delete_stmt = sa_delete(Token).where(Token.idtoken == idtoken)
    await db.execute(delete_stmt)

    await db.commit()

    logger.info(f"Token {idtoken} deleted successfully")

    return TokenDeleteResponse(
        ok=True,
        msg="Token deleted successfully",
        idtoken=idtoken,
    )


@router.post("/{idwf}/{idcase}/{idtoken}/assign", response_model=TokenAssignResponse)
async def assign_token(
    idwf: str,
    idcase: str,
    idtoken: int,
    request: TokenAssignRequest,
    db: AsyncSession = Depends(get_db),
):
    """Assign users to a token (task assignment).

    Ported from legacy Engine::assign_task($model, $idwf, $idcase, $src_resourceId, $resourceId, $idu) method.
    Sets the assign array on a token for task delegation and inbox processing.

    Args:
        idwf: Workflow/model identifier
        idcase: Case identifier
        idtoken: Token ID to assign
        request: TokenAssignRequest with user_ids list

    Returns:
        TokenAssignResponse with updated assignment

    Raises:
        HTTPException: 404 if token not found or doesn't belong to this case
        HTTPException: 400 if no user IDs provided
    """
    # Validate at least one user ID is provided (legacy checks `if($idu)`)
    if not request.user_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one user ID must be provided",
        )

    # Find token by ID and validate ownership
    stmt = select(Token).where(
        Token.idtoken == idtoken,
        Token.idwf == idwf,
        Token.case_id == idcase,
    )
    result = await db.execute(stmt)
    token = result.scalar_one_or_none()

    if token is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Token '{idtoken}' not found for case '{idcase}'",
        )

    # Update assign array (legacy uses $idu directly)
    token.assign = request.user_ids

    logger.info(f"Token {idtoken} assigned to users: {request.user_ids}")

    await db.commit()
    await db.refresh(token)

    return TokenAssignResponse(
        ok=True,
        msg="Token assigned successfully",
        idtoken=idtoken,
        assign=token.assign or [],
    )


@router.get("/status/{idwf}/{idcase}", status_code=status.HTTP_200_OK)
async def get_token_status(
    idwf: str,
    idcase: str,
    db: AsyncSession = Depends(get_db),
):
    """Get token status summary for a case.

    Ported from legacy Engine::get_case_tokens($model, $idwf, $case) method.
    Returns aggregated status counts and pending/finished breakdowns.

    Args:
        idwf: Workflow/model identifier
        idcase: Case identifier

    Returns:
        List of dicts containing status summaries (legacy returns array with 'pending', 'waiting', etc.)

    Raises:
        HTTPException: 404 if model or case not found
    """
    # Validate model exists
    stmt = select(BpmModel).where(BpmModel.idwf == idwf)
    result = await db.execute(stmt)
    if result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Model '{idwf}' does not exist",
        )

    # Validate case exists
    stmt = select(BpmCase).where(BpmCase.idcase == idcase)
    result = await db.execute(stmt)
    if result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Case '{idcase}' not found",
        )

    # Count tokens by status (legacy uses COUNT GROUP BY)
    from sqlalchemy import func

    stmt = (
        select(Token.status, func.count(Token.idtoken).label("count"))
        .where(
            Token.idwf == idwf,
            Token.case_id == idcase,
        )
        .group_by(Token.status)
    )

    result = await db.execute(stmt)
    rows = result.fetchall()

    # Format as legacy expects: array with status keys
    status_summary = []
    for row in rows:
        status_summary.append(
            {
                "status": row[0],
                "count": int(row[1]),  # Cast to int for consistency
            }
        )

    return status_summary
