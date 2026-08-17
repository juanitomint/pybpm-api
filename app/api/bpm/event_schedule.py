"""FastAPI router for Event Schedule CRUD.

Mirrors CodeIgniter module/controller layout: `modules/bpm/controllers/EventSchedule.php`
-> `app/api/bpm/event_schedule.py`. Exposes REST endpoints to manage event_schedules
table entries (timer triggers, signal waits, conditional waits) that the scheduler
uses to fire waiting tokens at their trigger time.

Endpoints:
- ``index``    -- list schedules with filters (case_id, idwf, resource_id, status, type)
- ``create``   -- create a new schedule entry
- ``read``     -- fetch a single schedule by idschedule
- ``update``   -- partial update (status transitions, reschedule, data)
- ``cancel``   -- cancel (soft-delete) a pending schedule
"""

from __future__ import annotations

import logging

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.event_schedule import EventSchedule
from app.schemas.event_schedule import (
    EventScheduleCreate,
    EventScheduleListResponse,
    EventScheduleOperationResponse,
    EventScheduleResponse,
    EventScheduleUpdate,
)
from app.services.event_schedule_service import (
    EventScheduleService,
    get_event_schedule_service,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/events/schedules", tags=["event-schedules"])


# -- index -------------------------------------------------------------------- #


@router.get(
    "",
    response_model=EventScheduleListResponse,
    status_code=status.HTTP_200_OK,
)
async def index(
    case_id: str | None = Query(None, description="Filter by case ID"),
    idwf: str | None = Query(None, description="Filter by workflow identifier"),
    resource_id: str | None = Query(None, description="Filter by shape resourceId"),
    status_filter: str | None = Query(
        None, alias="status", description="Filter by schedule status"
    ),
    schedule_type: str | None = Query(
        None, description="Filter by schedule type (timer/signal/conditional)"
    ),
    page: int = Query(default=1, ge=1, description="Page number"),
    per_page: int = Query(default=25, ge=1, le=200, description="Items per page"),
    service: EventScheduleService = Depends(get_event_schedule_service),
) -> EventScheduleListResponse:
    """List event schedules with optional filters and pagination."""
    conditions: list[sa.ColumnElement] = []
    if case_id:
        conditions.append(EventSchedule.case_id == case_id)
    if idwf:
        conditions.append(EventSchedule.idwf == idwf)
    if resource_id:
        conditions.append(EventSchedule.resource_id == resource_id)
    if status_filter:
        conditions.append(EventSchedule.status == status_filter)
    if schedule_type:
        conditions.append(EventSchedule.schedule_type == schedule_type)

    # Count total matching
    count_q = select(sa.func.count()).select_from(EventSchedule)
    if conditions:
        count_q = count_q.where(*conditions)
    total = (await service.db.execute(count_q)).scalar() or 0  # type: ignore[arg-type]

    # Paginated fetch (newest first)
    offset = (page - 1) * per_page
    query_q = select(EventSchedule).order_by(EventSchedule.created_at.desc())
    if conditions:
        query_q = query_q.where(*conditions)
    query_q = query_q.offset(offset).limit(per_page)
    result = await service.db.execute(query_q)  # type: ignore[misc]
    items = list(result.scalars().all())

    return EventScheduleListResponse(
        total=total, page=page, per_page=per_page, items=items
    )


# -- create ------------------------------------------------------------------- #


@router.post(
    "",
    response_model=EventScheduleOperationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create(
    body: EventScheduleCreate,
    service: EventScheduleService = Depends(get_event_schedule_service),
) -> EventScheduleOperationResponse:
    """Create a new event schedule entry."""
    entry = await service.create(
        case_id=body.case_id,
        idwf=body.idwf,
        resource_id=body.resource_id,
        trigger_time=body.trigger_time,
        schedule_type=body.schedule_type,
        data_json=body.data_json,
        status_=body.status,
        idu=body.idu,
    )
    return EventScheduleOperationResponse(
        ok=True, idschedule=entry.idschedule, detail="Event schedule created"
    )


# -- read --------------------------------------------------------------------- #


@router.get(
    "/{idschedule}",
    response_model=EventScheduleResponse,
    status_code=status.HTTP_200_OK,
)
async def read(
    idschedule: int,
    service: EventScheduleService = Depends(get_event_schedule_service),
) -> EventScheduleResponse | None:
    """Fetch a single event schedule by its ID."""
    stmt = select(EventSchedule).where(EventSchedule.idschedule == idschedule)
    result = await service.db.execute(stmt)  # type: ignore[misc]
    entry = result.scalar_one_or_none()
    if not entry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Event schedule {idschedule} not found",
        )
    return entry


# -- update ------------------------------------------------------------------- #


@router.patch(
    "/{idschedule}",
    response_model=EventScheduleOperationResponse,
    status_code=status.HTTP_200_OK,
)
async def update(
    idschedule: int,
    body: EventScheduleUpdate,
    service: EventScheduleService = Depends(get_event_schedule_service),
) -> EventScheduleOperationResponse:
    """Partially update an event schedule.

    Can transition status (e.g., pending -> fired by scheduler, or pending ->
    canceled by admin), reschedule to a new trigger_time, or update data_json.
    """
    entry_stmt = select(EventSchedule).where(
        EventSchedule.idschedule == idschedule
    )
    result = await service.db.execute(entry_stmt)  # type: ignore[misc]
    entry = result.scalar_one_or_none()
    if not entry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Event schedule {idschedule} not found",
        )

    update_data: dict[str, object] = {}
    if body.status is not None:
        update_data["status"] = body.status
    if body.trigger_time is not None:
        update_data["trigger_time"] = body.trigger_time
    if body.data_json is not None:
        update_data["data_json"] = body.data_json

    if not update_data:
        return EventScheduleOperationResponse(
            ok=True, idschedule=idschedule, detail="No changes applied"
        )

    stmt = (
        sa.update(EventSchedule)
        .where(EventSchedule.idschedule == idschedule)
        .values(**update_data)  # type: ignore[arg-type]
    )
    await service.db.execute(stmt)  # type: ignore[misc]
    await service.db.flush()

    logger.info("Updated event_schedule %s: %s", idschedule, ", ".join(update_data.keys()))
    return EventScheduleOperationResponse(
        ok=True, idschedule=idschedule, detail="Event schedule updated"
    )


# -- cancel ------------------------------------------------------------------- #


@router.delete(
    "/{idschedule}",
    response_model=EventScheduleOperationResponse,
    status_code=status.HTTP_200_OK,
)
async def cancel(
    idschedule: int,
    service: EventScheduleService = Depends(get_event_schedule_service),
) -> EventScheduleOperationResponse:
    """Cancel (soft-delete) a pending event schedule.

    Sets status to 'canceled'. Fired or already-canceled entries return 409 Conflict.
    """
    entry_stmt = select(EventSchedule).where(
        EventSchedule.idschedule == idschedule
    )
    result = await service.db.execute(entry_stmt)  # type: ignore[misc]
    entry = result.scalar_one_or_none()
    if not entry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Event schedule {idschedule} not found",
        )

    if entry.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Cannot cancel event_schedule {idschedule}: "
                f"current status is '{entry.status}'"
            ),
        )

    stmt = (
        sa.update(EventSchedule)
        .where(EventSchedule.idschedule == idschedule)
        .values(status="canceled")
    )
    await service.db.execute(stmt)  # type: ignore[misc]
    await service.db.flush()

    logger.info("Canceled event_schedule %s", idschedule)
    return EventScheduleOperationResponse(
        ok=True, idschedule=idschedule, detail="Event schedule canceled"
    )
