"""Background scheduler for event schedule dispatch.

Uses APScheduler's BackgroundScheduler to poll the ``event_schedules`` table
every 60 seconds, find entries whose ``trigger_time <= NOW()`` and status is
'pending', then advance the corresponding waiting token via movenext and mark
the schedule as 'fired'.

Delegates dispatch orchestration to :class:`app.services.scheduler_service.SchedulerService`.

Usage:
    From main.py, call ``start_scheduler(app)`` inside uvicorn.run wrapper.
"""

from __future__ import annotations

import asyncio
import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import FastAPI

logger = logging.getLogger(__name__)


def _scheduler_job():
    """APScheduler job that runs every 60 seconds — dispatches due schedules via SchedulerService."""

    async def run_dispatch():
        from app.services.scheduler_service import SchedulerService
        from extensions import get_async_db

        async with get_async_db() as db:
            service = SchedulerService(db)
            fired_count = await service.dispatch_due_schedules(limit=100)
            if fired_count > 0:
                logger.info("Scheduler: dispatched %d due schedule(s)", fired_count)

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(run_dispatch())
    finally:
        loop.close()


def start_scheduler(app: FastAPI) -> None:  # type: ignore[name-defined]
    """Start the background scheduler that polls event_schedules every 60 seconds.

    Registers a single ``BackgroundScheduler`` job that calls ``_scheduler_job()``
    every 60 seconds. The scheduler is created once at app startup and runs in
    its own thread pool, isolated from the async FastAPI event loop.

    Args:
        app: The FastAPI application instance (unused but required for lifespan wiring).
    """
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        _scheduler_job,
        trigger=IntervalTrigger(seconds=60),
        id="event_schedule_dispatch",
        name="Dispatch due event schedules",
        replace_existing=True,
    )

    # Store scheduler on app for lifespan shutdown.
    app.state.scheduler = scheduler  # type: ignore[attr-defined]

    logger.info("Scheduler started — polling event_schedules every 60 seconds")


def stop_scheduler(app: FastAPI) -> None:  # type: ignore[name-defined]
    """Stop the background scheduler on app shutdown."""
    scheduler = getattr(app.state, "scheduler", None)
    if scheduler and scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
