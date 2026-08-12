"""FastAPI router for Token CRUD operations.

Ported from legacy CodeIgniter `dna2bpm/application/modules/dna2/controllers/Engine.php`.
Handles token lifecycle management within case instances — creation, status updates, assignments, and deletion.

Endpoints:
- GET    /tokens/{idwf}/{case_id}              - List all tokens for a case (Ext.js format)
- GET    /status/{idwf}/{idcase}               - Get token status summary for a case
- GET    /{idtoken}                            - Get single token by ID
- POST   /create/{idwf}/{case_id}              - Create new token(s)
- PATCH  /update/{idwf}/{case_id}/{idtoken}    - Update token attributes/status
- DELETE /delete/{idwf}/{case_id}/{idtoken}    - Delete specific token
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import delete as sa_delete
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.token import Token, TokenHistory
from app.schemas.token import TokenResponse

logger = logging.getLogger(__name__)


# ============================================================================
# Request/Response Models (Ext.js compatible)
# ============================================================================


class TokenPayload(BaseModel):
    """Schema for a single token payload (legacy Ext.js format)."""

    resource_id: str = ""
    type_: str = Field(default="Task", alias="type")


class TokenCreateRequest(BaseModel):
    """Request body for creating new tokens."""

    tokens: TokenPayload | list[TokenPayload]  # Single token or bulk creation


class CreateTokenResponse(BaseModel):
    """Response after creating token(s)."""

    ok: bool = True
    msg: str
    tokens: list[dict[str, Any]]


class TokenUpdateRequest(BaseModel):
    """Request body for updating token attributes."""

    status: str | None = None  # pending/waiting/finished
    assign: list[int] | None = None
    external_data: dict[str, Any] | None = None
    run_count: int | None = None
    check_date: datetime | None = None


class UpdateTokenResponse(BaseModel):
    """Response after updating token."""

    ok: bool = True
    msg: str
    idtoken: int
    status: str
    assign: list[int]


class DeleteTokenResponse(BaseModel):
    """Response after deleting token."""

    ok: bool = True
    msg: str
    idtoken: int


class TokenAssignRequest(BaseModel):
    """Request body for assigning/removing users from tokens."""

    id_user: int
    action: Literal["add", "remove"]  # Add or remove user from assignment


class AssignTokenResponse(BaseModel):
    """Response after assigning/removing user."""

    ok: bool = True
    msg: str
    idtoken: int
    assign: list[int]


router = APIRouter(prefix="/bpm/token_manager", tags=["token-manager"])


async def get_db():
    """FastAPI dependency for async database session."""
    from extensions import async_session_factory

    async with async_session_factory() as db:
        yield db


@router.get("/tokens/{idwf}/{case_id}", status_code=status.HTTP_200_OK)
async def list_tokens(
    idwf: str,
    case_id: str,
    db: AsyncSession = Depends(get_db),
):
    """List all tokens for a case in Ext.js compatible format.

    Ported from legacy Engine::tokens() method.
    Returns token information including user assignments and task status.

    Args:
        idwf: Workflow/model identifier
        case_id: Case instance identifier

    Returns:
        Dict with 'totalCount' (int) and 'rows' (list of token dicts) in Ext.js format

    Raises:
        HTTPException: 404 if case not found
    """
    # Validate case exists
    stmt = (
        select(Token)
        .where(Token.case_id == case_id, Token.idwf == idwf)
        .order_by(Token.idtoken)
    )

    result = await db.execute(stmt)
    tokens = result.scalars().all()

    # Convert to Ext.js format with MongoDB-style _id and formatted dates
    rows = []
    for token in tokens:
        user_name = "admin"  # default
        if token.assign and len(token.assign) > 0:
            from app.models.user import User

            user_stmt = select(User).where(User.idu == token.assign[0])
            user_result = await db.execute(user_stmt)
            user = user_result.scalar_one_or_none()
            if user and hasattr(user, "name"):
                user_name = user.name or "admin"

        rows.append(
            {
                "_id": {"$id": str(token.idtoken)},  # MongoDB-style _id with $id field
                "id_token": token.idtoken,
                "idwf": idwf,
                "case_id": case_id,
                "resource_id": token.resource_id,
                "type": token.type,
                "status": token.status,
                "assign": token.assign or [],
                "name_user": user_name,
                "checkdate": token.check_date.strftime("%Y-%m-%d %H:%M:%S")
                if token.check_date
                else "",
                "run_count": token.run_count,
            }
        )

    return {
        "totalCount": len(rows),
        "rows": rows,
    }


@router.get("/status/{idwf}/{idcase}", status_code=status.HTTP_200_OK)
async def get_token_status(
    idwf: str,
    idcase: str,
    db: AsyncSession = Depends(get_db),
):
    """Get token status summary for a case.

    Ported from legacy Engine::tokens() method.
    Returns compact token information for status display in UI.

    Args:
        idwf: Workflow/model identifier
        idcase: Case instance identifier

    Returns:
        Dict with 'totalCount' (int) and 'rows' (list of token dicts) in Ext.js format

    Raises:
        HTTPException: 404 if case not found
    """
    # Validate case exists
    stmt = (
        select(Token)
        .where(Token.case_id == idcase, Token.idwf == idwf)
        .order_by(Token.idtoken)
    )

    result = await db.execute(stmt)
    tokens = result.scalars().all()

    rows = []
    for token in tokens:
        user_name = "admin"
        if token.assign and len(token.assign) > 0:
            from app.models.user import User

            user_stmt = select(User).where(User.idu == token.assign[0])
            user_result = await db.execute(user_stmt)
            user = user_result.scalar_one_or_none()
            if user and hasattr(user, "name"):
                user_name = user.name or "admin"

        rows.append(
            {
                "_id": {"$id": str(token.idtoken)},
                "id_token": token.idtoken,
                "idwf": idwf,
                "case_id": idcase,
                "resource_id": token.resource_id,
                "type": token.type,
                "status": token.status,
                "name_user": user_name,
                "checkdate": token.check_date.strftime("%Y-%m-%d %H:%M:%S")
                if token.check_date
                else "",
            }
        )

    return {
        "totalCount": len(rows),
        "rows": rows,
    }


@router.get("/{idtoken}", response_model=TokenResponse, status_code=status.HTTP_200_OK)
async def get_token(
    idtoken: int,
    db: AsyncSession = Depends(get_db),
):
    """Get a single token by its ID.

    Ported from legacy Engine::get_token() method.
    Returns full token details including assignments and execution state.

    Args:
        idtoken: The unique identifier of the token to retrieve

    Returns:
        TokenResponse with all token attributes in JSON format

    Raises:
        HTTPException: 404 if token not found
    """
    stmt = select(Token).where(Token.idtoken == idtoken)
    result = await db.execute(stmt)
    token = result.scalar_one_or_none()

    if token is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Token '{idtoken}' not found",
        )

    # Get assigned user info if available
    name_user = "admin"
    if token.assign and len(token.assign) > 0:
        from app.models.user import User

        user_stmt = select(User).where(User.idu == token.assign[0])
        user_result = await db.execute(user_stmt)
        user = user_result.scalar_one_or_none()
        if user and hasattr(user, "name"):
            name_user = user.name or "admin"

    return {
        "idtoken": token.idtoken,
        "idwf": token.idwf,
        "case_id": token.case_id,
        "resource_id": token.resource_id,
        "type": token.type,
        "status": token.status,
        "assign": token.assign or [],
        "external_data": token.external_data or {},
        "check_date": token.check_date.isoformat() if token.check_date else None,
        "run_count": token.run_count,
        "locked_by": token.locked_by,
        "name_user": name_user,
    }


@router.post("/create/{idwf}/{case_id}", status_code=status.HTTP_201_CREATED)
async def create_token(
    idwf: str,
    case_id: str,
    request: TokenCreateRequest,
    db: AsyncSession = Depends(get_db),
):
    """Create new token(s) for a case.

    Ported from legacy Engine::createToken() method.
    Creates token records with proper assignment and status tracking.

    Args:
        idwf: Workflow/model identifier
        case_id: Case instance identifier
        request: TokenCreateRequest with token attributes

    Returns:
        CreateTokenResponse indicating success/failure

    Raises:
        HTTPException: 404 if case not found, 422 for validation errors
    """
    # Validate case exists
    from app.models.case import BpmCase

    stmt = select(BpmCase).where(BpmCase.idcase == case_id, BpmCase.idwf == idwf)
    result = await db.execute(stmt)
    case = result.scalar_one_or_none()

    if case is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Case '{case_id}' does not exist in workflow '{idwf}'",
        )

    # Create new token(s) — support bulk creation via list
    tokens_created = []

    if isinstance(request.tokens, list):
        for token_data in request.tokens:
            new_token = Token(
                idwf=idwf,
                case_id=case_id,
                resource_id=token_data.resource_id,
                type=token_data.type_,
                status="pending",
                assign=[],
                external_data=None,
            )
            db.add(new_token)
            await db.flush()  # Get the auto-generated idtoken
            tokens_created.append(
                {
                    "idtoken": new_token.idtoken,
                    "status": "created",
                }
            )
    else:
        token_data = request.tokens  # type: ignore[assignment]
        assert isinstance(token_data, TokenPayload)
        new_token = Token(
            idwf=idwf,
            case_id=case_id,
            resource_id=token_data.resource_id,
            type=token_data.type_,
            status="pending",
            assign=[],
        )
        db.add(new_token)
        await db.flush()
        tokens_created.append(
            {
                "idtoken": new_token.idtoken,
                "status": "created",
            }
        )

    await db.commit()

    logger.info(f"Created {len(tokens_created)} token(s) for case {case_id}")

    return CreateTokenResponse(
        ok=True,
        msg=f"{len(tokens_created)} token(s) created successfully",
        tokens=tokens_created,
    )


@router.patch("/update/{idwf}/{case_id}/{idtoken}", status_code=status.HTTP_200_OK)
async def update_token(
    idwf: str,
    case_id: str,
    idtoken: int,
    request: TokenUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    """Update token attributes or status.

    Ported from legacy Engine::updateToken() method.
    Modifies token state including assignments, completion, and lock information.

    Args:
        idwf: Workflow/model identifier
        case_id: Case instance identifier
        idtoken: Token ID to update
        request: TokenUpdateRequest with fields to modify

    Returns:
        UpdateTokenResponse indicating success/failure

    Raises:
        HTTPException: 404 if token not found, 422 for validation errors
    """
    # Get existing token
    stmt = select(Token).where(
        Token.idtoken == idtoken,
        Token.case_id == case_id,
        Token.idwf == idwf,
    )
    result = await db.execute(stmt)
    token = result.scalar_one_or_none()

    if token is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Token '{idtoken}' not found in case '{case_id}'",
        )

    # Update provided fields
    if request.status is not None:
        token.status = request.status

    if request.assign is not None:
        token.assign = request.assign

    if request.external_data is not None:
        token.external_data = request.external_data

    if request.run_count is not None:
        token.run_count = request.run_count

    # Update check_date if provided or on status change
    from datetime import datetime

    now = datetime.now(UTC)

    if request.check_date is not None:
        token.check_date = request.check_date
    elif request.status in ["waiting", "finished"]:
        token.check_date = now

    await db.commit()
    await db.refresh(token)

    logger.info(
        f"Token {idtoken} updated: status={token.status}, assign={token.assign}"
    )

    return UpdateTokenResponse(
        ok=True,
        msg="Token updated successfully",
        idtoken=idtoken,
        status=token.status,
        assign=token.assign or [],
    )


@router.delete("/delete/{idwf}/{case_id}/{idtoken}", status_code=status.HTTP_200_OK)
async def delete_token(
    idwf: str,
    case_id: str,
    idtoken: int,
    db: AsyncSession = Depends(get_db),
):
    """Delete a specific token.

    Ported from legacy Engine::deleteToken() method.
    Removes the token record and optionally creates history entry.

    Args:
        idwf: Workflow/model identifier
        case_id: Case instance identifier
        idtoken: Token ID to delete

    Returns:
        DeleteTokenResponse indicating success/failure

    Raises:
        HTTPException: 404 if token not found, 422 for validation errors
    """
    # Get existing token first (for history)
    stmt = select(Token).where(
        Token.idtoken == idtoken,
        Token.case_id == case_id,
        Token.idwf == idwf,
    )
    result = await db.execute(stmt)
    token = result.scalar_one_or_none()

    if token is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Token '{idtoken}' not found in case '{case_id}'",
        )

    # Create history record before deletion (optional audit trail)
    history = TokenHistory(
        idwf=idwf,
        case_id=case_id,
        resource_id=token.resource_id,
        type=token.type,
        status=f"deleted_{token.status}",  # Mark as deleted with original status
        check_date=datetime.now(UTC),
        run_count=token.run_count,
    )
    db.add(history)

    # Delete the token
    delete_stmt = sa_delete(Token).where(Token.idtoken == idtoken)
    await db.execute(delete_stmt)

    await db.commit()

    logger.info(f"Token {idtoken} deleted from case {case_id}")

    return DeleteTokenResponse(
        ok=True,
        msg="Token deleted successfully",
        idtoken=idtoken,
    )


@router.post("/assign/{idwf}/{case_id}/{idtoken}", status_code=status.HTTP_200_OK)
async def assign_token(
    idwf: str,
    case_id: str,
    idtoken: int,
    request: TokenAssignRequest,
    db: AsyncSession = Depends(get_db),
):
    """Assign a user to a token.

    Ported from legacy Engine::assignToken() method.
    Updates the assign field with user ID for task assignment.

    Args:
        idwf: Workflow/model identifier
        case_id: Case instance identifier
        idtoken: Token ID to assign
        request: TokenAssignRequest with user ID

    Returns:
        AssignTokenResponse indicating success/failure

    Raises:
        HTTPException: 404 if token not found, 422 for validation errors
    """
    # Get existing token
    stmt = select(Token).where(
        Token.idtoken == idtoken,
        Token.case_id == case_id,
        Token.idwf == idwf,
    )
    result = await db.execute(stmt)
    token = result.scalar_one_or_none()

    if token is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Token '{idtoken}' not found in case '{case_id}'",
        )

    # Update assignment list
    current_assign = token.assign or []

    if request.action == "add":
        if request.id_user not in current_assign:
            current_assign.append(request.id_user)
    elif request.action == "remove":
        current_assign = [uid for uid in current_assign if uid != request.id_user]

    token.assign = current_assign
    await db.commit()

    logger.info(f"Token {idtoken} assigned to user(s): {current_assign}")

    return AssignTokenResponse(
        ok=True,
        msg=f"User {request.id_user} {'assigned' if request.action == 'add' else 'removed'} from token",
        idtoken=idtoken,
        assign=current_assign,
    )


# ============================================================================
# Import BaseModels for Pydantic validation
# ============================================================================
