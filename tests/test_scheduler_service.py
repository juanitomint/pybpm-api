"""Tests for SchedulerService — dispatch logic, signal firing, and single schedule dispatch."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select as sa_select

# -- helpers ------------------------------------------------------------------ #


def _past_dt() -> datetime:
    """Return a datetime in the past (so trigger_time <= NOW())."""
    return datetime.now(UTC) - timedelta(hours=1)


def _future_dt() -> datetime:
    """Return a datetime in the future."""
    return datetime.now(UTC) + timedelta(hours=1)


# -- fixtures ----------------------------------------------------------------- #


@pytest.fixture
def _insert_schedule(setup_test_db):
    """Helper to insert an EventSchedule row and return it."""
    factory = setup_test_db["factory"]

    async def _factory(
        case_id="TEST-CASE",
        idwf="test-wf",
        resource_id="timer-shape",
        trigger_time=None,
        schedule_type="timer",
        status="pending",
        data_json=None,
    ):
        from app.models.event_schedule import EventSchedule as ScheduleModel

        entry = ScheduleModel(
            case_id=case_id,
            idwf=idwf,
            resource_id=resource_id,
            trigger_time=trigger_time or _past_dt(),
            schedule_type=schedule_type,
            status=status,
            data_json=data_json or {},
        )
        async with factory() as s:
            s.add(entry)
            await s.commit()

        # Reload to get auto-generated id
        async with factory() as s:
            stmt = sa_select(ScheduleModel).where(
                ScheduleModel.case_id == case_id,
                ScheduleModel.idwf == idwf,
                ScheduleModel.resource_id == resource_id,
            )
            result = await s.execute(stmt)
            return result.scalar_one()

    return _factory


@pytest.fixture
def _insert_token(setup_test_db):
    """Helper to insert a Token row and return it."""
    factory = setup_test_db["factory"]

    async def _factory(
        idtoken=1,
        idwf="test-wf",
        case_id="TEST-CASE",
        resource_id="timer-shape",
        type="IntermediateTimerEvent",
        status="waiting",
        run_count=0,
    ):
        from app.models.token import Token

        token = Token(
            idtoken=idtoken,
            idwf=idwf,
            case_id=case_id,
            resource_id=resource_id,
            type=type,
            status=status,
            run_count=run_count,
        )
        async with factory() as s:
            s.add(token)
            await s.commit()

        # Reload
        async with factory() as s:
            stmt = sa_select(Token).where(Token.idtoken == idtoken)
            result = await s.execute(stmt)
            return result.scalar_one()

    return _factory


# -- test: dispatch_due_schedules — no due schedules -------------------------- #


@pytest.mark.asyncio
async def test_dispatch_no_due_schedules(setup_test_db):
    """dispatch_due_schedules returns 0 when no pending schedules are due."""
    factory = setup_test_db["factory"]
    from app.models.event_schedule import EventSchedule as ScheduleModel
    from app.services.scheduler_service import SchedulerService

    # Insert a schedule with a future trigger_time (not due).
    entry = ScheduleModel(
        case_id="FUTURE-CASE",
        idwf="future-wf",
        resource_id="future-shape",
        trigger_time=_future_dt(),
        schedule_type="timer",
        status="pending",
        data_json={},
    )
    async with factory() as s:
        s.add(entry)
        await s.commit()

    async with factory() as s:
        service = SchedulerService(s)
        fired = await service.dispatch_due_schedules()
    assert fired == 0


# -- test: dispatch_due_schedules — timer schedule with waiting token --------- #


@pytest.mark.asyncio
async def test_dispatch_timer_with_waiting_token(setup_test_db, _insert_schedule, _insert_token):
    """dispatch_due_schedules fires a timer schedule when its token is waiting."""
    factory = setup_test_db["factory"]
    from app.models.event_schedule import EventSchedule as ScheduleModel
    from app.services.scheduler_service import SchedulerService

    schedule = await _insert_schedule(
        case_id="TIMER-CASE",
        idwf="timer-wf",
        resource_id="timer-shape",
        trigger_time=_past_dt(),
        status="pending",
    )
    await _insert_token(
        idtoken=10,
        idwf="timer-wf",
        case_id="TIMER-CASE",
        resource_id="timer-shape",
        status="waiting",
    )

    async with factory() as s:
        service = SchedulerService(s)
        fired = await service.dispatch_due_schedules()

    assert fired >= 1

    # Verify schedule status changed to 'fired'.
    async with factory() as s:
        stmt = sa_select(ScheduleModel).where(ScheduleModel.idschedule == schedule.idschedule)
        result = await s.execute(stmt)
        updated = result.scalar_one()
    assert updated.status == "fired"


# -- test: dispatch_due_schedules — skips token that is not waiting ----------- #


@pytest.mark.asyncio
async def test_dispatch_skips_non_waiting_token(setup_test_db, _insert_schedule, _insert_token):
    """dispatch_due_schedules skips a schedule when its token is not 'waiting'."""
    factory = setup_test_db["factory"]
    from app.models.event_schedule import EventSchedule as ScheduleModel
    from app.services.scheduler_service import SchedulerService

    schedule = await _insert_schedule(
        case_id="SKIP-CASE",
        idwf="skip-wf",
        resource_id="skip-shape",
        trigger_time=_past_dt(),
        status="pending",
    )
    # Token exists but status is 'pending', not 'waiting'.
    await _insert_token(
        idtoken=20,
        idwf="skip-wf",
        case_id="SKIP-CASE",
        resource_id="skip-shape",
        status="pending",
    )

    async with factory() as s:
        service = SchedulerService(s)
        fired = await service.dispatch_due_schedules()

    assert fired == 0

    # Schedule should remain 'pending'.
    async with factory() as s:
        stmt = sa_select(ScheduleModel).where(ScheduleModel.idschedule == schedule.idschedule)
        result = await s.execute(stmt)
        updated = result.scalar_one()
    assert updated.status == "pending"


# -- test: dispatch_due_schedules — skips missing token ----------------------- #


@pytest.mark.asyncio
async def test_dispatch_skips_missing_token(setup_test_db, _insert_schedule):
    """dispatch_due_schedules skips a schedule when no token exists for it."""
    factory = setup_test_db["factory"]
    from app.models.event_schedule import EventSchedule as ScheduleModel
    from app.services.scheduler_service import SchedulerService

    schedule = await _insert_schedule(
        case_id="NO-TOKEN-CASE",
        idwf="no-token-wf",
        resource_id="no-token-shape",
        trigger_time=_past_dt(),
        status="pending",
    )
    # No token inserted at all.

    async with factory() as s:
        service = SchedulerService(s)
        fired = await service.dispatch_due_schedules()

    assert fired == 0

    # Schedule should remain 'pending'.
    async with factory() as s:
        stmt = sa_select(ScheduleModel).where(ScheduleModel.idschedule == schedule.idschedule)
        result = await s.execute(stmt)
        updated = result.scalar_one()
    assert updated.status == "pending"


# -- test: dispatch_due_schedules — skips already-fired schedule --------------- #


@pytest.mark.asyncio
async def test_dispatch_skips_fired_schedule(setup_test_db, _insert_schedule, _insert_token):
    """dispatch_due_schedules skips schedules that are already 'fired'."""
    factory = setup_test_db["factory"]
    from app.services.scheduler_service import SchedulerService

    await _insert_schedule(
        case_id="FIREDCASE",
        idwf="fired-wf",
        resource_id="fired-shape",
        trigger_time=_past_dt(),
        status="fired",  # Already fired.
    )
    await _insert_token(
        idtoken=30,
        idwf="fired-wf",
        case_id="FIREDCASE",
        resource_id="fired-shape",
        status="waiting",
    )

    async with factory() as s:
        service = SchedulerService(s)
        fired = await service.dispatch_due_schedules()

    assert fired == 0


# -- test: dispatch_due_schedules — signal schedules -------------------------- #


@pytest.mark.asyncio
async def test_dispatch_signal_schedules(setup_test_db, _insert_schedule, _insert_token):
    """dispatch_due_schedules fires signal schedules when matching signal exists."""
    factory = setup_test_db["factory"]
    from app.models.event_schedule import EventSchedule as ScheduleModel
    from app.models.signal import Signal
    from app.services.scheduler_service import SchedulerService

    schedule = await _insert_schedule(
        case_id="SIGNAL-CASE",
        idwf="signal-wf",
        resource_id="signal-shape",
        trigger_time=_past_dt(),
        schedule_type="signal",
        status="pending",
        data_json={"name": "test-signal"},
    )
    await _insert_token(
        idtoken=40,
        idwf="signal-wf",
        case_id="SIGNAL-CASE",
        resource_id="signal-shape",
        status="waiting",
    )

    # Insert a matching signal.
    signal = Signal(
        idsignal=1,
        name="test-signal",
        case_id="SIGNAL-CASE",
        idwf="signal-wf",
    )
    async with factory() as s:
        s.add(signal)
        await s.commit()

    async with factory() as s:
        service = SchedulerService(s)
        fired = await service.dispatch_due_schedules()

    assert fired >= 1

    # Verify schedule status changed to 'fired'.
    async with factory() as s:
        stmt = sa_select(ScheduleModel).where(ScheduleModel.idschedule == schedule.idschedule)
        result = await s.execute(stmt)
        updated = result.scalar_one()
    assert updated.status == "fired"


# -- test: dispatch_due_schedules — signal with no matching signal ------------ #


@pytest.mark.asyncio
async def test_dispatch_signal_no_match(setup_test_db, _insert_schedule, _insert_token):
    """dispatch_due_schedules skips signal schedules when no matching signal exists.

    Uses a future trigger_time so the schedule is NOT picked up by get_due_schedules()
    (which would fire it via the timer loop). Instead we test _fire_signal_schedules
    directly.
    """
    factory = setup_test_db["factory"]
    from app.models.event_schedule import EventSchedule as ScheduleModel
    from app.services.scheduler_service import SchedulerService

    schedule = await _insert_schedule(
        case_id="NOSIGNAL-CASE",
        idwf="nosignal-wf",
        resource_id="nosignal-shape",
        trigger_time=_future_dt(),  # Future so get_due_schedules won't pick it up.
        schedule_type="signal",
        status="pending",
        data_json={"name": "nonexistent-signal"},
    )
    await _insert_token(
        idtoken=50,
        idwf="nosignal-wf",
        case_id="NOSIGNAL-CASE",
        resource_id="nosignal-shape",
        status="waiting",
    )

    async with factory() as s:
        service = SchedulerService(s)
        # get_due_schedules returns empty (future trigger_time), so dispatch returns 0.
        fired = await service.dispatch_due_schedules()

    assert fired == 0

    # Schedule should remain 'pending'.
    async with factory() as s:
        stmt = sa_select(ScheduleModel).where(ScheduleModel.idschedule == schedule.idschedule)
        result = await s.execute(stmt)
        updated = result.scalar_one()
    assert updated.status == "pending"


# -- test: dispatch_due_schedules — signal schedule missing name -------------- #


@pytest.mark.asyncio
async def test_dispatch_signal_missing_name(setup_test_db, _insert_schedule, _insert_token):
    """dispatch_due_schedules skips signal schedules with no name in data_json.

    Uses a future trigger_time so the schedule is NOT picked up by get_due_schedules()
    (which would fire it via the timer loop). Instead we test _fire_signal_schedules
    directly.
    """
    factory = setup_test_db["factory"]
    from app.models.event_schedule import EventSchedule as ScheduleModel
    from app.services.scheduler_service import SchedulerService

    schedule = await _insert_schedule(
        case_id="NONAME-CASE",
        idwf="noname-wf",
        resource_id="noname-shape",
        trigger_time=_future_dt(),  # Future so get_due_schedules won't pick it up.
        schedule_type="signal",
        status="pending",
        data_json={},  # No 'name' key.
    )
    await _insert_token(
        idtoken=60,
        idwf="noname-wf",
        case_id="NONAME-CASE",
        resource_id="noname-shape",
        status="waiting",
    )

    async with factory() as s:
        service = SchedulerService(s)
        # get_due_schedules returns empty (future trigger_time), so dispatch returns 0.
        fired = await service.dispatch_due_schedules()

    assert fired == 0

    # Schedule should remain 'pending'.
    async with factory() as s:
        stmt = sa_select(ScheduleModel).where(ScheduleModel.idschedule == schedule.idschedule)
        result = await s.execute(stmt)
        updated = result.scalar_one()
    assert updated.status == "pending"


# -- test: fire_single_schedule — success ------------------------------------- #


@pytest.mark.asyncio
async def test_fire_single_schedule_success(setup_test_db, _insert_schedule, _insert_token):
    """fire_single_schedule returns True and marks schedule as fired."""
    factory = setup_test_db["factory"]
    from app.models.event_schedule import EventSchedule as ScheduleModel
    from app.services.scheduler_service import SchedulerService

    schedule = await _insert_schedule(
        case_id="SINGLE-CASE",
        idwf="single-wf",
        resource_id="single-shape",
        trigger_time=_past_dt(),
        status="pending",
    )
    await _insert_token(
        idtoken=70,
        idwf="single-wf",
        case_id="SINGLE-CASE",
        resource_id="single-shape",
        status="waiting",
    )

    async with factory() as s:
        service = SchedulerService(s)
        result = await service.fire_single_schedule(schedule.idschedule)

    assert result is True

    # Verify schedule status changed to 'fired'.
    async with factory() as s:
        stmt = sa_select(ScheduleModel).where(ScheduleModel.idschedule == schedule.idschedule)
        result2 = await s.execute(stmt)
        updated = result2.scalar_one()
    assert updated.status == "fired"


# -- test: fire_single_schedule — non-existent schedule ----------------------- #


@pytest.mark.asyncio
async def test_fire_single_schedule_not_found(setup_test_db):
    """fire_single_schedule returns False for a non-existent schedule ID."""
    factory = setup_test_db["factory"]
    from app.services.scheduler_service import SchedulerService

    async with factory() as s:
        service = SchedulerService(s)
        result = await service.fire_single_schedule(99999)

    assert result is False


# -- test: fire_single_schedule — already fired ------------------------------- #


@pytest.mark.asyncio
async def test_fire_single_schedule_already_fired(setup_test_db, _insert_schedule):
    """fire_single_schedule returns False for an already-fired schedule."""
    factory = setup_test_db["factory"]
    from app.services.scheduler_service import SchedulerService

    schedule = await _insert_schedule(
        case_id="FIREDCASE2",
        idwf="fired-wf2",
        resource_id="fired-shape2",
        trigger_time=_past_dt(),
        status="fired",
    )

    async with factory() as s:
        service = SchedulerService(s)
        result = await service.fire_single_schedule(schedule.idschedule)

    assert result is False


# -- test: fire_single_schedule — token not waiting --------------------------- #


@pytest.mark.asyncio
async def test_fire_single_schedule_token_not_waiting(setup_test_db, _insert_schedule, _insert_token):
    """fire_single_schedule returns False when token is not 'waiting'."""
    factory = setup_test_db["factory"]
    from app.services.scheduler_service import SchedulerService

    schedule = await _insert_schedule(
        case_id="NOTWAITING-CASE",
        idwf="notwaiting-wf",
        resource_id="notwaiting-shape",
        trigger_time=_past_dt(),
        status="pending",
    )
    await _insert_token(
        idtoken=80,
        idwf="notwaiting-wf",
        case_id="NOTWAITING-CASE",
        resource_id="notwaiting-shape",
        status="pending",  # Not 'waiting'.
    )

    async with factory() as s:
        service = SchedulerService(s)
        result = await service.fire_single_schedule(schedule.idschedule)

    assert result is False


# -- test: fire_single_schedule — missing token ------------------------------- #


@pytest.mark.asyncio
async def test_fire_single_schedule_missing_token(setup_test_db, _insert_schedule):
    """fire_single_schedule returns False when no token exists for the schedule."""
    factory = setup_test_db["factory"]
    from app.services.scheduler_service import SchedulerService

    schedule = await _insert_schedule(
        case_id="NOTOKEN-CASE2",
        idwf="notoken-wf2",
        resource_id="notoken-shape2",
        trigger_time=_past_dt(),
        status="pending",
    )
    # No token inserted.

    async with factory() as s:
        service = SchedulerService(s)
        result = await service.fire_single_schedule(schedule.idschedule)

    assert result is False


# -- test: dispatch_due_schedules — limit parameter --------------------------- #


@pytest.mark.asyncio
async def test_dispatch_respects_limit(setup_test_db, _insert_schedule, _insert_token):
    """dispatch_due_schedules respects the limit parameter."""
    factory = setup_test_db["factory"]
    from app.models.event_schedule import EventSchedule as ScheduleModel
    from app.services.scheduler_service import SchedulerService

    # Insert 5 due schedules.
    for i in range(5):
        await _insert_schedule(
            case_id=f"LIMIT-CASE-{i}",
            idwf=f"limit-wf-{i}",
            resource_id=f"limit-shape-{i}",
            trigger_time=_past_dt(),
            status="pending",
        )
        await _insert_token(
            idtoken=100 + i,
            idwf=f"limit-wf-{i}",
            case_id=f"LIMIT-CASE-{i}",
            resource_id=f"limit-shape-{i}",
            status="waiting",
        )

    async with factory() as s:
        service = SchedulerService(s)
        # Limit to 2.
        fired = await service.dispatch_due_schedules(limit=2)

    assert fired == 2

    # Verify only 2 schedules were fired.
    async with factory() as s:
        stmt = sa_select(ScheduleModel).where(ScheduleModel.status == "fired")
        result = await s.execute(stmt)
        fired_count = len(list(result.scalars().all()))
    assert fired_count == 2


# -- test: dispatch_due_schedules — multiple due schedules -------------------- #


@pytest.mark.asyncio
async def test_dispatch_multiple_due_schedules(setup_test_db, _insert_schedule, _insert_token):
    """dispatch_due_schedules fires all due schedules in one pass."""
    factory = setup_test_db["factory"]
    from app.models.event_schedule import EventSchedule as ScheduleModel
    from app.services.scheduler_service import SchedulerService

    for i in range(3):
        await _insert_schedule(
            case_id=f"MULTI-CASE-{i}",
            idwf=f"multi-wf-{i}",
            resource_id=f"multi-shape-{i}",
            trigger_time=_past_dt(),
            status="pending",
        )
        await _insert_token(
            idtoken=200 + i,
            idwf=f"multi-wf-{i}",
            case_id=f"MULTI-CASE-{i}",
            resource_id=f"multi-shape-{i}",
            status="waiting",
        )

    async with factory() as s:
        service = SchedulerService(s)
        fired = await service.dispatch_due_schedules()

    assert fired == 3

    # Verify all 3 schedules were fired.
    async with factory() as s:
        stmt = sa_select(ScheduleModel).where(ScheduleModel.status == "fired")
        result = await s.execute(stmt)
        fired_count = len(list(result.scalars().all()))
    assert fired_count == 3


# -- test: get_due_schedules -------------------------------------------------- #


@pytest.mark.asyncio
async def test_get_due_schedules(setup_test_db, _insert_schedule):
    """get_due_schedules returns only pending schedules with trigger_time <= NOW()."""
    factory = setup_test_db["factory"]
    from app.models.event_schedule import EventSchedule as ScheduleModel
    from app.services.scheduler_service import SchedulerService

    # Insert a due schedule.
    await _insert_schedule(
        case_id="DUE-CASE",
        idwf="due-wf",
        resource_id="due-shape",
        trigger_time=_past_dt(),
        status="pending",
    )
    # Insert a not-yet-due schedule.
    await _insert_schedule(
        case_id="FUTURE-CASE2",
        idwf="future-wf2",
        resource_id="future-shape2",
        trigger_time=_future_dt(),
        status="pending",
    )
    # Insert a fired schedule.
    await _insert_schedule(
        case_id="FIREDCASE3",
        idwf="fired-wf3",
        resource_id="fired-shape3",
        trigger_time=_past_dt(),
        status="fired",
    )

    async with factory() as s:
        service = SchedulerService(s)
        due = await service.get_due_schedules()

    assert len(due) == 1
    assert due[0].case_id == "DUE-CASE"
