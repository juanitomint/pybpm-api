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

        async with _scheduler_session_factory() as db:
            service = SchedulerService(db)
            fired_count = await service.dispatch_due_schedules(limit=100)
            print(f"[SCHEDULER] fired_count={fired_count}")
            if fired_count > 0:
                logger.info("Scheduler: dispatched %d due schedule(s)", fired_count)

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(run_dispatch())
    finally:
        loop.close()


# Lazy-initialized scheduler engine and session factory.
_scheduler_engine = None
_scheduler_session_factory = None


def _ensure_scheduler_engine():
    """Create or return the shared async engine and session factory for the scheduler."""
    global _scheduler_engine, _scheduler_session_factory
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
    from sqlalchemy.pool import StaticPool

    from extensions import _async_database_url
    _url = _async_database_url()
    if _scheduler_engine is None:
        _scheduler_engine = create_async_engine(
            _url,
            echo=False,
            poolclass=StaticPool if "sqlite" in _url else None,
        )
        _scheduler_session_factory = async_sessionmaker(
            bind=_scheduler_engine, class_=AsyncSession, expire_on_commit=False
        )
    return _scheduler_engine, _scheduler_session_factory


def start_scheduler(app: FastAPI) -> None:  # type: ignore[name-defined]
    """Start the background scheduler that polls event_schedules every 60 seconds.

    Registers a single ``BackgroundScheduler`` job that calls ``_scheduler_job()``
    every 60 seconds. The scheduler is created once at app startup and runs in
    its own thread pool, isolated from the async FastAPI event loop.

    Args:
        app: The FastAPI application instance (unused but required for lifespan wiring).
    """
    # Ensure engine/session_factory exist before the scheduler starts (they are
    # thread-local, so we create them in the main thread).
    _ensure_scheduler_engine()

    scheduler = BackgroundScheduler()
    scheduler.add_job(
        _scheduler_job,
        trigger=IntervalTrigger(seconds=60),
        id="event_schedule_dispatch",
        name="Dispatch due event schedules",
        replace_existing=True,
    )
    scheduler.start()

    # Store scheduler on app for lifespan shutdown.
    app.state.scheduler = scheduler  # type: ignore[attr-defined]

    logger.info("Scheduler started — polling event_schedules every 60 seconds")


def stop_scheduler(app: FastAPI) -> None:  # type: ignore[name-defined]
    """Stop the background scheduler on app shutdown."""
    scheduler = getattr(app.state, "scheduler", None)
    if scheduler and scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
