"""Tests for Task shape handler.

Covers User/Manual (stop), Script (eval + advance), and default movenext paths.
Mirrors the test pattern in ``tests/test_flow_handlers.py`` — mocked service,
constructed token/shape dicts, await handle(), assert on call args.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def mock_service():
    """Create a mock EngineService with async methods."""
    service = MagicMock()
    service.movenext = AsyncMock()
    service.get_previous = AsyncMock(return_value=[])
    service.get_token = AsyncMock(return_value=None)
    service.get_shape = AsyncMock(return_value=None)
    service.db = MagicMock()

    # Mock the SQLAlchemy update.execute chain so handlers can call it without
    # a real DB session. We capture calls for assertions but don't actually run SQL.
    mock_result = AsyncMock()
    mock_result.scalar_one_or_none.return_value = None
    service.db.execute = AsyncMock(return_value=mock_result)
    service.db.flush = AsyncMock()

    return service


@pytest.fixture
def task_token():
    """Create a minimal token object for Task handler tests."""
    token = MagicMock()
    token.idwf = "test-model"
    token.case_id = "case-123"
    token.resource_id = "task-shape-1"
    token.status = "pending"
    return token


def _make_shape(tasktype: str, looptype: str = "Standard", **overrides):
    """Build a Task shape dict with the given tasktype and optional overrides."""
    base = {
        "resourceId": "task-shape-1",
        "stencil": {"id": "Task"},
        "properties": {
            "tasktype": tasktype,
            "looptype": looptype,
        },
    }
    base["properties"].update(overrides)
    return base


class TestTaskHandlerUserStopsExecution:
    """A User task must mark the token 'user' and NOT call movenext."""

    @pytest.mark.asyncio
    async def test_user_task_stops_execution(self, mock_service, task_token):
        shape = _make_shape("User")
        from app.handlers.task import TaskHandler

        handler = TaskHandler()
        # The handler should run without raising.
        await handler.handle(task_token, shape, mock_service)

        # movenext must NOT be called — User task waits for manual input.
        assert mock_service.movenext.call_count == 0

        # Token status='user' update goes through service.db.execute.
        assert mock_service.db.execute.call_count >= 1

    async def test_script_task_evaluates_and_advances(self, mock_service, task_token):
        shape = _make_shape(
            "Script",
            looptype="Standard",
            script="return 42",
            operationref="myvar",
        )

        from app.handlers.task import TaskHandler

        handler = TaskHandler()
        await handler.handle(task_token, shape, mock_service)

        # Script task must call movenext (auto-advance after eval).
        assert mock_service.movenext.call_count == 1
        movenext_args = mock_service.movenext.call_args
        assert movenext_args[0][0] == "task-shape-1"  # resource_id

        # The Script branch also issues a case-data update. Verify execute was
        # called for the BpmCase UPDATE (distinct from Token status update).
        exec_calls = mock_service.db.execute.call_args_list
        assert len(exec_calls) >= 2  # one for external_data, one for case data


class TestTaskHandlerSendMovenexts:
    """A Send task must movenext; message dispatch is deferred."""

    @pytest.mark.asyncio
    async def test_send_task_advances_via_movenext(self, mock_service, task_token):
        shape = _make_shape("Send")
        from app.handlers.task import TaskHandler

        handler = TaskHandler()
        await handler.handle(task_token, shape, mock_service)

        # Send v1 stub just calls movenext (no inbox dispatch yet).
        assert mock_service.movenext.call_count == 1


class TestTaskHandlerLoopGuard:
    """A non-Standard looptype task that has already run must be skipped."""

    @pytest.mark.asyncio
    async def test_loop_guard_skips_repeated_task(self, mock_service, task_token):
        shape = _make_shape("User", looptype="Sequential")
        # Pre-populate the service.task_run set so the guard thinks this task ran.
        mock_service.task_run = {"task-shape-1"}

        from app.handlers.task import TaskHandler

        handler = TaskHandler()
        await handler.handle(task_token, shape, mock_service)

        # Loop guard short-circuits — no movenext, no token update.
        assert mock_service.movenext.call_count == 0
        assert mock_service.db.execute.call_count == 0


# -- Callacitivity & outgoing-timer tests ---------------------------------- #


class TestCallacitivitySubstitution:
    """A call-activity task must swap in the concrete implementation shape."""

    @pytest.mark.asyncio
    async def test_call_activity_replaces_shape(self, mock_service, task_token):
        from app.handlers.task import TaskHandler

        handler = TaskHandler()

        # Shape is a call activity pointing to "MyTask" (name + tasktype=Script).
        shape = _make_shape("Script", looptype="Standard")
        shape["properties"]["callacitivity"] = True
        shape["properties"]["callableelement"] = ""  # fall back to name
        shape["properties"]["name"] = "MyTask"
        shape["outgoing"] = [{"resourceId": "original-out"}]  # will be swapped

        # Mock get_shapes_by_property to return a non-callactivity candidate.
        concrete_shape = {
            "resourceId": "concrete-shape-rid",
            "stencil": {"id": "Task"},
            "properties": {
                "name": "MyTask",
                "tasktype": "Script",
                "callacitivity": False,
            },
            "outgoing": [{"resourceId": "concrete-out"}],
            "resources": {"Performer": [1]},  # mirrors legacy $shape->resources copy
        }

        async def fake_get_shapes_by_property(*a, **kw):  # type: ignore[no-untyped-def]
            return [concrete_shape] if kw.get("name") == "MyTask" else []

        mock_service.get_shapes_by_property = fake_get_shapes_by_property

        await handler.handle(task_token, shape, mock_service)

        # Outgoing edges should have been swapped to the concrete shape's outgoing.
        assert shape["outgoing"] == [{"resourceId": "concrete-out"}], (
            f"Expected outgoing swap; got {shape['outgoing']}"
        )
        # Stencil and resources preserved from candidate.
        assert shape["stencil"] == {"id": "Task"}
        assert "resources" in shape  # copied from candidate


class TestOutgoingTimerPreCreation:
    """A Task with an IntermediateTimerEvent outgoing edge must pre-create a pending token."""

    @pytest.mark.asyncio
    async def test_timer_target_gets_pending_token(self, mock_service, task_token):
        from app.handlers.task import TaskHandler

        handler = TaskHandler()

        shape = _make_shape("Script", looptype="Standard")
        shape["outgoing"] = [
            {"resourceId": "next-task"},
            {"resourceId": "timer-event"},
        ]

        # Mock get_shape to return the timer event for the second outgoing edge.
        async def fake_get_shape(rid, idwf):  # type: ignore[no-untyped-def]
            if rid == "timer-event":
                return {
                    "resourceId": "timer-event",
                    "stencil": {"id": "IntermediateTimerEvent"},
                    "properties": {},
                }
            return None

        mock_service.get_shape.side_effect = fake_get_shape
        mock_service.get_previous.return_value = []
        # create_token should be called for the timer target.
        created: list[dict] = []

        async def capture_create(**kwargs):  # type: ignore[no-untyped-def]
            created.append(kwargs)

        mock_service.create_token = capture_create
        mock_service.db.execute = AsyncMock()  # type: ignore[assignment]
        mock_service.get_token.return_value = None  # no existing token on timer target

        await handler.handle(task_token, shape, mock_service)

        # Timer event should have a pending token created.
        assert len(created) == 1
        assert created[0]["resource_id"] == "timer-event"
        assert created[0]["type_"] == "IntermediateTimerEvent"
        assert created[0]["status"] == "pending"


# -- Auto-assignment fallback tests ---------------------------------------- #


class TestTaskHandlerAutoAssignNoRules:
    """When no explicit resource rules exist on a User/Manual task, the engine must auto-assign
    to the case initiator — mirroring legacy Bpm::assign() fallback behavior."""

    @pytest.mark.asyncio
    async def test_user_task_no_resources_auto_assigns_to_initiator(
        self, mock_service, task_token
    ):
        """No resources on shape triggers initiator lookup; at least one execute call includes assign+title."""
        from app.handlers.task import TaskHandler

        handler = TaskHandler()
        # Shape has no 'resources' key at all.
        shape = _make_shape("User", name="Review Document")

        mock_init_result = AsyncMock()
        mock_init_result.scalar_one_or_none.return_value = 42

        captured: list[tuple] = []

        async def fake_execute(stmt):  # type: ignore[no-untyped-def]
            captured.append((str(stmt)[:150],))
            return mock_init_result if "initiator" in str(stmt).lower() else AsyncMock()

        mock_service.db.execute.side_effect = fake_execute

        await handler.handle(task_token, shape, mock_service)

        # Verify an initiator lookup was issued.
        init_lookups = [c for c in captured if "initiator_id" in c[0]]
        assert len(init_lookups) == 1, (
            f"Expected exactly one initiator lookup; got {len(init_lookups)}"
        )

        # Verify at least one execute call included 'assign' and 'title' (the token update).
        assign_calls = [c for c in captured if "assign" in c[0] or "title" in c[0]]
        assert len(assign_calls) >= 2, (
            f"Expected updates for assign+title; got {len(assign_calls)} calls with assign/title"
        )

    @pytest.mark.asyncio
    async def test_user_task_with_explicit_rules_skips_auto_assign(
        self, mock_service, task_token
    ):
        """Shape has resource rules -> auto-assign must NOT fire (rules take precedence)."""
        from app.handlers.task import TaskHandler

        handler = TaskHandler()
        shape = _make_shape("User", name="Admin Task")
        shape["resources"] = {
            "items": [
                {
                    "resource": "user",
                    "resource_type": "assign",
                    "resourceassignmentexpr": "admin",
                },
            ]
        }

        # No initiator lookup should happen — db.execute receives no SELECT.
        exec_calls: list[str] = []

        async def track_execute(stmt):  # type: ignore[no-untyped-def]
            exec_calls.append(str(stmt))
            return AsyncMock()

        mock_service.db.execute.side_effect = track_execute

        await handler.handle(task_token, shape, mock_service)

        # No SELECT for initiator_id should have been issued.
        select_calls = [c for c in exec_calls if "initiator" in c.lower()]
        assert len(select_calls) == 0, (
            f"Expected no initiator lookup when rules exist; got: {select_calls}"
        )

    @pytest.mark.asyncio
    async def test_manual_task_no_resources_auto_assigns(
        self, mock_service, task_token
    ):
        """Manual tasks share the same auto-assign fallback as User tasks."""
        from app.handlers.task import TaskHandler

        handler = TaskHandler()
        shape = _make_shape("Manual", name="Sign Form")

        captured: list[tuple] = []
        mock_init_result = AsyncMock()
        mock_init_result.scalar_one_or_none.return_value = 7

        async def fake_execute(stmt):  # type: ignore[no-untyped-def]
            captured.append((str(stmt)[:150],))
            return mock_init_result if "initiator" in str(stmt).lower() else AsyncMock()

        mock_service.db.execute.side_effect = fake_execute

        await handler.handle(task_token, shape, mock_service)

        init_lookups = [c for c in captured if "initiator_id" in c[0]]
        assert len(init_lookups) == 1, (
            f"Expected exactly one initiator lookup; got {len(init_lookups)}"
        )

        assign_calls = [c for c in captured if "assign" in c[0] or "title" in c[0]]
        assert len(assign_calls) >= 2, (
            f"Expected updates for assign+title; got {len(assign_calls)} calls with assign/title"
        )


class TestTaskHandlerIduStored:
    """The token's 'idu' field should record who the task was auto-assigned to."""

    @pytest.mark.asyncio
    async def test_idu_stored_on_token_during_auto_assign(
        self, mock_service, task_token
    ):
        """When no rules apply, idu=initiator is persisted on the token row (visible in SQL text)."""
        from app.handlers.task import TaskHandler

        handler = TaskHandler()
        shape = _make_shape("User", name="Approve")

        mock_init_result = AsyncMock()
        mock_init_result.scalar_one_or_none.return_value = 99

        captured: list[str] = []

        async def fake_execute(stmt):  # type: ignore[no-untyped-def]
            captured.append(str(stmt))
            return mock_init_result if "initiator" in str(stmt).lower() else AsyncMock()

        mock_service.db.execute.side_effect = fake_execute

        await handler.handle(task_token, shape, mock_service)

        # At least one execute call should reference 'idu' (the column we set alongside assign).
        idu_calls = [c for c in captured if "idu" in c.lower()]
        assert len(idu_calls) >= 1, (
            f"Expected at least one update referencing 'idu'; got {len(captured)} total calls"
        )
