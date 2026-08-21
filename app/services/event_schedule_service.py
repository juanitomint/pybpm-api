"""Event Schedule Service — manages event_schedules table entries.

Handles creation, lookup, and lifecycle management of scheduled events (timer
triggers, signal waits, conditional waits) that the scheduler polls to fire
waiting tokens at their trigger time.

Mirrors legacy PHP timer/event trigger semantics where tokens transition from
``status='pending'`` -> ``status='waiting'`` with a separate schedule entry in
the event_schedules table so the scheduler can efficiently query "what's due now?".
"""

import logging
from datetime import UTC, datetime

import sqlalchemy as sa
from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.event_schedule import EventSchedule
from extensions import get_async_db

logger = logging.getLogger(__name__)


class EventScheduleService:
    """CRUD operations on the event_schedules table.

    Each row represents one active (non-fired) schedule entry for a token on an
    intermediate event shape — e.g., a waiting timer or signal catcher awaiting
    its thrower.

    The scheduler polls this service to find events that should fire: rows with
    ``status='pending'`` and ``trigger_time <= now`` are candidates for firing.
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(
        self,
        case_id: str,
        idwf: str,
        resource_id: str,
        trigger_time: datetime,
        schedule_type: str = "timer",
        data_json: dict | None = None,
        status_: str = "pending",
        idu: int | None = None,
    ) -> EventSchedule:
        """Insert a new event schedule entry.

        Args:
            case_id: The running case ID this schedule belongs to.
            idwf: Workflow ID (for cross-case lookups in subprocess scenarios).
            resource_id: Shape resourceId this schedule entry belongs to.
            trigger_time: When the scheduler should fire this event.
            schedule_type: Type of event — 'timer', 'signal', or 'conditional'.
            data_json: Optional JSON payload (e.g., parsed trigger expression).
            status_: Schedule status — defaults to 'pending'.

        Returns:
            The created EventSchedule row.
        """
        entry = EventSchedule(
            case_id=case_id,
            idwf=idwf,
            resource_id=resource_id,
            trigger_time=trigger_time,
            status=status_,
            data_json=data_json or {},
            idu=idu,
        )
        self.db.add(entry)
        await self.db.flush()
        logger.debug(
            "Created event_schedule: idschedule=%s type=%s resource=%s trigger=%s",
            entry.idschedule,
            schedule_type,
            resource_id,
            trigger_time.isoformat(),
        )
        return entry

    async def get_by_resource(
        self, case_id: str, idwf: str, resource_id: str
    ) -> EventSchedule | None:
        """Fetch a single event schedule by (case_id, idwf, resource_id)."""
        stmt = select(EventSchedule).where(
            EventSchedule.case_id == case_id,
            EventSchedule.idwf == idwf,
            EventSchedule.resource_id == resource_id,
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_due_schedules(self, limit: int = 100) -> list[EventSchedule]:
        """Fetch pending schedules that are due now (trigger_time <= now).

        Used by the scheduler to find events that should fire. Results are ordered
        by trigger_time ascending so earliest-due events fire first.
        """
        stmt = (
            select(EventSchedule)
            .where(
                EventSchedule.status == "pending",
                EventSchedule.trigger_time <= datetime.now(UTC),
            )
            .order_by(EventSchedule.trigger_time.asc())
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def mark_fired(self, entry: EventSchedule) -> None:
        """Mark a schedule entry as fired."""
        entry.status = "fired"
        entry.updated_at = datetime.now(UTC)
        await self.db.flush()

    async def cancel_by_case(self, case_id: str, idwf: str) -> int:
        """Cancel all pending schedules for a case. Returns count of canceled rows."""
        stmt = (
            sa.update(EventSchedule)
            .where(
                EventSchedule.case_id == case_id,
                EventSchedule.idwf == idwf,
                EventSchedule.status == "pending",
            )
            .values(status="canceled")
        )
        result = await self.db.execute(stmt)  # type: ignore[misc]
        return result.rowcount  # type: ignore[return-value]

    async def cancel_by_resource(
        self, case_id: str, idwf: str, resource_id: str
    ) -> int:
        """Cancel all pending schedules for a specific shape in a case."""
        stmt = (
            sa.update(EventSchedule)
            .where(
                EventSchedule.case_id == case_id,
                EventSchedule.idwf == idwf,
                EventSchedule.resource_id == resource_id,
                EventSchedule.status == "pending",
            )
            .values(status="canceled")
        )
        result = await self.db.execute(stmt)  # type: ignore[misc]
        return result.rowcount  # type: ignore[return-value]


def get_event_schedule_service(db: AsyncSession = Depends(get_async_db)):
    """FastAPI dependency that yields a bound ``EventScheduleService``.

    Note: This uses the raw AsyncSession from dependency injection rather than
    the custom ``get_async_db`` helper, to keep this service decoupled from the
    engine-specific DB session pattern. The FastAPI app's dependency override
    in tests will still provide a working session.
    """
    return EventScheduleService(db)  # type: ignore[arg-type]
