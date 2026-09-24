"""Scheduler Service — orchestrates event schedule dispatch.

Wraps ``EventScheduleService.get_due_schedules()`` and adds the dispatch logic:
for each due schedule, looks up the waiting token on the corresponding shape,
calls ``EngineService.movenext()`` to advance it past the waiting state, then
marks the schedule entry as 'fired'.

Additionally fires pending signal schedules (schedule_type='signal') when
matching active signals exist in the persistence store — enabling timer-free
signal-based workflow coordination.

Usage:
    Called by the APScheduler background worker (see ``app/core/scheduler.py``)
    every 60 seconds, or directly from API endpoints for manual retriggering.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import select as sa_select
from sqlalchemy import update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.event_schedule import EventSchedule
from app.services.event_schedule_service import EventScheduleService

logger = logging.getLogger(__name__)


class SchedulerService:
    """Orchestrates event schedule dispatch — finds due entries and fires them.

    Delegates low-level CRUD to ``EventScheduleService``; this class handles the
    higher-level flow: query for due schedules → look up waiting tokens → advance
    engine via movenext → mark as fired. Additionally fires pending signal
    schedules (schedule_type='signal') when matching active signals exist in the
    persistence store — enabling timer-free signal-based workflow coordination.

    The background worker (APScheduler) calls :meth:`dispatch_due_schedules`
    every 60 seconds; API endpoints may call :meth:`fire_single_schedule` to
    manually trigger a specific schedule entry.
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.event_service = EventScheduleService(db)

    async def get_due_schedules(self, limit: int = 100) -> list[EventSchedule]:
        """Fetch pending schedules that are due now (trigger_time <= NOW()).

        Args:
            limit: Maximum number of entries to return per batch. Defaults to 100.

        Returns:
            List of ``EventSchedule`` rows ordered by trigger_time ascending
            (earliest-due first). Empty list if no schedules are due.
        """
        return await self.event_service.get_due_schedules(limit=limit)

    async def dispatch_due_schedules(self, limit: int = 100) -> int:
        """Find due schedules and fire them all. Returns count of fired entries.

        For each schedule entry whose ``trigger_time <= NOW()`` and status is
        'pending':
          1. Look up the waiting token on the corresponding shape (same case, idwf, resource_id).
          2. If the token exists and status is 'waiting', call ``EngineService.movenext()`` to advance it past the waiting state.
          3. Mark the schedule entry as 'fired' with updated_at timestamp.

        Additionally fires pending signal schedules (schedule_type='signal') when matching active signals exist in the persistence store — enabling timer-free signal-based workflow coordination.

        Args:
            limit: Maximum number of entries to process per batch. Defaults to 100.

        Returns:
            Number of schedules successfully fired this cycle (timer + signal).
        """
        due = await self.get_due_schedules(limit=limit)

        if not due:
            return 0

        fired_count = 0
        for schedule in due:
            try:
                from app.models.token import Token
                from app.services.engine_service import EngineService

                # Look up the waiting token for this schedule.
                token_stmt = sa_select(Token).where(
                    Token.idwf == schedule.idwf,
                    Token.case_id == schedule.case_id,
                    Token.resource_id == schedule.resource_id,
                )
                token_result = await self.db.execute(token_stmt)  # type: ignore[misc]
                token = token_result.scalar_one_or_none()

                if not token or token.status != "waiting":
                    logger.debug(
                        "SchedulerService: skipping %s (token missing or status=%s)",
                        schedule.idschedule,
                        token.status if token else "missing",
                    )
                    continue

                # Advance the engine past this shape via movenext.
                service = await EngineService.create(self.db, idwf=schedule.idwf, idcase=schedule.case_id)
                await service.movenext(
                    schedule.resource_id, schedule.idwf, schedule.case_id
                )

                # Mark schedule as fired with updated_at timestamp.
                update_stmt = (
                    sa_update(EventSchedule)
                    .where(EventSchedule.idschedule == schedule.idschedule)  # type: ignore[attr-defined]
                    .values(status="fired", updated_at=datetime.now(UTC))
                )
                await self.db.execute(update_stmt)  # type: ignore[misc]

                fired_count += 1

                logger.info(
                    "SchedulerService: fired %s (resource=%s case=%s)",
                    schedule.idschedule,
                    schedule.resource_id,
                    schedule.case_id,
                )

            except Exception as exc:
                logger.error(
                    "SchedulerService: error dispatching schedule %d: %s",
                    schedule.idschedule,
                    exc,
                )

        # Also fire any pending signal schedules whose matching signals are active.
        try:
            signal_fired = await self._fire_signal_schedules()
            if signal_fired > 0:
                logger.info(
                    "SchedulerService: fired %d signal schedule(s)", signal_fired
                )
        except Exception as exc:
            logger.error("SchedulerService: error firing signal schedules: %s", exc)

        await self.db.flush()  # type: ignore[misc]
        return fired_count + signal_fired if "signal_fired" in dir() else fired_count

    async def _fire_signal_schedules(self) -> int:
        """Fire pending signal schedules whose matching signals are active.

        Signal schedules (schedule_type='signal') wait for a specific signal name to be thrown.
        This method finds all pending signal schedules, checks if their matching signal exists in
        the persistence store, and fires them if found. Returns count of fired signal schedules.

        Returns:
            Number of signal schedules successfully fired this cycle.
        """
        from app.models.event_schedule import EventSchedule as ScheduleModel

        # Find all pending signal schedules (schedule_type='signal').
        stmt = (
            sa_select(ScheduleModel)
            .where(
                ScheduleModel.status == "pending",
                ScheduleModel.schedule_type == "signal",
            )
            .limit(100)
        )

        result = await self.db.execute(stmt)  # type: ignore[misc]
        signal_schedules = list(result.scalars().all())

        if not signal_schedules:
            return 0

        fired_count = 0
        for schedule in signal_schedules:
            try:
                from app.services.engine_service import EngineService
                from app.services.signal_service import SignalService

                # Extract signal name from schedule data_json (legacy PHP stores it under 'name' key).
                data = schedule.data_json or {}
                signal_name = data.get("name", "")

                if not signal_name:
                    logger.debug(
                        "SchedulerService: skipping signal schedule %d (no name in data)",
                        schedule.idschedule,
                    )
                    continue

                # Check if matching signal exists.
                signal_svc = SignalService(self.db)  # type: ignore[arg-type]
                active_signals = await signal_svc.find_by_name(signal_name)

                if not active_signals:
                    continue  # No matching signal — keep waiting.

                # Found matching signals — fire this schedule.
                engine_service = await EngineService.create(self.db, idwf=schedule.idwf, idcase=schedule.case_id)
                await engine_service.movenext(
                    schedule.resource_id, schedule.idwf, schedule.case_id
                )

                update_stmt = (
                    sa_update(ScheduleModel)
                    .where(ScheduleModel.idschedule == schedule.idschedule)  # type: ignore[attr-defined]
                    .values(status="fired", updated_at=datetime.now(UTC))
                )
                await self.db.execute(update_stmt)  # type: ignore[misc]

                fired_count += 1
                logger.info(
                    "SchedulerService: fired signal schedule %s (name=%s resource=%s case=%s)",
                    schedule.idschedule,
                    signal_name,
                    schedule.resource_id,
                    schedule.case_id,
                )
            except Exception as exc:
                logger.error(
                    "SchedulerService: error firing signal schedule %d: %s",
                    schedule.idschedule,
                    exc,
                )

        await self.db.flush()  # type: ignore[misc]
        return fired_count

    async def fire_single_schedule(self, idschedule: int) -> bool:
        """Manually trigger a single schedule entry. Returns True if fired.

        Useful for testing or manual retriggering after a missed dispatch cycle.

        Args:
            idschedule: Primary key of the EventSchedule row to fire.

        Returns:
            True if the schedule was found, pending, and successfully fired; False otherwise.
        """
        # Fetch the target schedule entry.
        stmt = sa_select(EventSchedule).where(EventSchedule.idschedule == idschedule)
        result = await self.db.execute(stmt)  # type: ignore[misc]
        schedule = result.scalar_one_or_none()

        if not schedule or schedule.status != "pending":
            logger.warning(
                "SchedulerService: cannot fire %s (status=%s)",
                idschedule,
                schedule.status if schedule else "missing",
            )
            return False

        # Look up the waiting token for this schedule.
        from app.models.token import Token
        from app.services.engine_service import EngineService

        token_stmt = sa_select(Token).where(
            Token.idwf == schedule.idwf,
            Token.case_id == schedule.case_id,
            Token.resource_id == schedule.resource_id,
        )
        token_result = await self.db.execute(token_stmt)  # type: ignore[misc]
        token = token_result.scalar_one_or_none()

        if not token or token.status != "waiting":
            logger.warning(
                "SchedulerService: token for %s is missing or not waiting (status=%s)",
                idschedule,
                token.status if token else "missing",
            )
            return False

        # Advance the engine past this shape via movenext.
        service = await EngineService.create(self.db, idwf=schedule.idwf, idcase=schedule.case_id)
        await service.movenext(schedule.resource_id, schedule.idwf, schedule.case_id)

        # Mark schedule as fired with updated_at timestamp.
        update_stmt = (
            sa_update(EventSchedule)
            .where(EventSchedule.idschedule == idschedule)  # type: ignore[attr-defined]
            .values(status="fired", updated_at=datetime.now(UTC))
        )
        await self.db.execute(update_stmt)  # type: ignore[misc]

        logger.info("SchedulerService: manually fired %s", idschedule)
        return True


def get_scheduler_service(db: AsyncSession):
    """FastAPI dependency that yields a bound ``SchedulerService``."""
    from extensions import get_async_db

    async def _get():
        async with get_async_db() as db_session:
            yield SchedulerService(db_session)

    return _get()  # type: ignore[return-value]


# Re-export for convenience.
__all__ = ["SchedulerService", "get_scheduler_service"]
