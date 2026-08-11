"""FastAPI router for Case Manager CRUD operations.

Ported from legacy CodeIgniter `dna2bpm/application/modules/dna2/controllers/CaseManager.php`.
Handles case instance management with idcase as the primary parameter.

Endpoints:
- GET    /{idcase}              - Get a single case by ID
- PATCH  /{idcase}              - Update case attributes
- DELETE /{idcase}              - Delete a case
- GET    /                      - List all cases (optional)
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, delete as sa_delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
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

router = APIRouter(prefix="/cases", tags=["case-manager"])


async def get_db():
    """FastAPI dependency for async database session."""
    from extensions import async_session_factory
    
    async with async_session_factory() as db:
        yield db


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
    case = result.scalar_one_or_none()

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
    case = result.scalar_one_or_none()

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
    case = result.scalar_one_or_none()

    if case is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Case '{idcase}' not found",
        )

    # Toggle freeze state based on locked_by presence
    if request.iduser is not None:
        if case.locked_by == request.iduser:
            # Unfreeze - clear lock
            case.locked_by = None
            case.locked_date = None
            msg = "Case unfrozen successfully"
        else:
            # Freeze - set lock
            from datetime import datetime, timezone
            case.locked_by = request.iduser
            case.locked_date = datetime.now(timezone.utc)
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
        case_responses.append(CasesListResponse(
            idcase=case.idcase,
            idwf=case.idwf,
            status=case.status,
            initiator_id=case.initiator_id,
            created_at=case.created_at,
        ))

    return case_responses


@router.get("/search/{status}", response_model=list[CasesListResponse], status_code=status.HTTP_200_OK)
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
    stmt = select(BpmCase).where(
        BpmCase.status == status_filter
    ).order_by(BpmCase.updated_at.desc())
    
    result = await db.execute(stmt)
    cases = result.scalars().all()

    case_responses = []
    for case in cases:
        case_responses.append(CasesListResponse(
            idcase=case.idcase,
            idwf=case.idwf,
            status=case.status,
            initiator_id=case.initiator_id,
            created_at=case.created_at,
        ))

    return case_responses

