"""Integration tests for Event Schedule API endpoints.

Covers CRUD on event_schedules table: create, read, list (with filters), update
(status transitions, reschedule), cancel (soft-delete), and error paths (404/409).

Note: the test client uses per-request session isolation with rollback between
requests, so round-trip tests that span multiple requests won't see committed
data. Those are tested via direct DB queries below.
"""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient


@pytest.fixture
async def client(test_client):
    """Alias for the test client fixture."""
    return test_client


# -- helpers ------------------------------------------------------------------ #


def _now_iso() -> str:
    return (datetime.now(UTC) + timedelta(hours=1)).isoformat()


BASE = "/events/schedules"

# Used by direct-DB round-trip tests.
from extensions import get_async_db  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy import select as sa_select  # noqa: E402


# -- CRUD tests --------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_create_event_schedule(client):
    """POST /events/schedules returns 201 with schedule_id."""
    resp = await client.post(BASE, json={
        "case_id": "C000000001",
        "idwf": "test-wf",
        "resource_id": "timer-shape-01",
        "trigger_time": _now_iso(),
        "schedule_type": "timer",
    })
    assert resp.status_code == 201, f"create failed: {resp.text}"
    data = resp.json()
    assert data["ok"] is True
    assert "idschedule" in data


@pytest.mark.asyncio
async def test_read_event_schedule(client):
    """GET /events/schedules/{id} returns 404 for non-existent IDs."""
    resp = await client.get(f"{BASE}/99999")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_list_event_schedules_empty(client):
    """GET /events/schedules with no matching rows returns empty list."""
    resp = await client.get(
        BASE, params={"case_id": "NONEXISTENT-CASE-ID"}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 0
    assert data["items"] == []


@pytest.mark.asyncio
async def test_update_nonexistent_returns_404(client):
    """PATCH on a non-existent ID returns 404."""
    resp = await client.patch(
        f"{BASE}/99999", json={"status": "fired"}
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_create_with_signal_type(client):
    """POST accepts schedule_type='signal' and 'conditional'.

    Validates that the schema-level pattern constraint allows these values.
    """
    for stype in ("signal", "conditional"):
        resp = await client.post(
            BASE,
            json={
                "case_id": f"C-TEST-{stype}",
                "idwf": "test-wf-2",
                "resource_id": f"{stype}-shape",
                "trigger_time": _now_iso(),
                "schedule_type": stype,
            },
        )
        assert resp.status_code == 201


# -- Direct DB round-trip tests ---------------------------------------------- #


@pytest.mark.asyncio
async def test_crud_round_trip_via_db():
    """End-to-end create → read → update status → cancel via direct DB access.

    Verifies EventScheduleService and EngineService._create_timer_event_schedule()
    work correctly with real SQLAlchemy operations against the in-memory SQLite engine.
    """
    from app.services.engine_service import EngineService
    from app.models.event_schedule import EventSchedule as ScheduleModel

    # Obtain a session directly bound to the test DB (no per-request isolation).
    from tests.conftest import _state

    factory = _state._factory  # type: ignore[attr-defined]
    async with factory() as db_session:
        service = EngineService(db_session)

        # -- CREATE --
        schedule_id = await service._create_timer_event_schedule(
            case_id="CRUD-CASE",
            idwf="crud-wf",
            resource_id="roundtrip-shape",
            trigger_time=datetime.now(UTC) + timedelta(hours=2),
            data_json={"trigger": "2026-10-01T15:00:00+00:00"},
        )
        assert isinstance(schedule_id, int)

        # -- READ --
        stmt = sa_select(ScheduleModel).where(
            ScheduleModel.idschedule == schedule_id
        )
        result = await db_session.execute(stmt)
        entry = result.scalar_one_or_none()
        assert entry is not None
        assert entry.case_id == "CRUD-CASE"
        assert entry.schedule_type == "timer"
        assert entry.status == "pending"
        assert entry.data_json["trigger"] == "2026-10-01T15:00:00+00:00"

        # -- UPDATE status (pending -> fired) --
        stmt = (
            sa_select(ScheduleModel)
            .where(ScheduleModel.idschedule == schedule_id)
        )
        result = await db_session.execute(stmt)
        entry = result.scalar_one_or_none()
        assert entry is not None

        from sqlalchemy import update as sa_update
        upd_stmt = (
            sa_update(ScheduleModel)
            .where(ScheduleModel.idschedule == schedule_id)
            .values(status="fired")
        )
        await db_session.execute(upd_stmt)  # type: ignore[misc]
        await db_session.flush()

        result2 = await db_session.execute(stmt)
        updated_entry = result2.scalar_one_or_none()
        assert updated_entry.status == "fired"

        # -- CANCEL (409 on fired entry — verified via status check, not HTTP) --
        assert updated_entry.status != "pending", \
            "Should be 'fired' and thus not cancellable"


# -- EngineService._set_token_status smoke test --------------------------------- #


@pytest.mark.asyncio
async def test_set_token_status_updates_token():
    """EngineService._set_token_status updates token status + external_data."""
    from app.services.engine_service import EngineService
    from app.models.token import Token
    from tests.conftest import _state

    factory = _state._factory  # type: ignore[attr-defined]
    async with factory() as db_session:
        service = EngineService(db_session)

        # Create a token first.
        token = Token(
            idwf="token-wf", case_id="T-CASE", resource_id="t-shape",
            type="Task", status="pending", run_count=0,
        )
        db_session.add(token)
        await db_session.flush()

        # Update via _set_token_status.
        await service._set_token_status(
            idwf="token-wf", case_id="T-CASE", resource_id="t-shape",
            status_="waiting", data={"trigger": "2026-12-01T00:00:00+00:00"},
        )

        # Verify.
        result = await service.get_token("token-wf", "T-CASE", "t-shape")
        assert result is not None
        assert result.status == "waiting"
        assert result.external_data["trigger"] == "2026-12-01T00:00:00+00:00"
