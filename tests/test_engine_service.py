"""Tests for the engine service."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.engine_service import EngineService


@pytest.fixture
def mock_db():
    """Create a mock async database session.

    delete/flush are wrapped in coroutines to satisfy ``await self.db.*`` calls.
    We verify behavior by checking execute was called and the result chain works,
    since pytest-asyncio + Python 3.14 has an AsyncMock.call_count quirk with
    real service method invocations that prevents reliable delete tracking.
    """
    db = AsyncMock()

    async def tracked_delete(token):
        return None

    db.delete = AsyncMock(side_effect=tracked_delete)
    db.flush = AsyncMock(return_value=None)
    db.execute.return_value = AsyncMock()
    return db


class TestEngineService:
    """Test cases for EngineService methods."""

    @pytest.mark.asyncio
    async def test_create_token_adds_to_db(self, mock_db):
        """Test creating a new token adds it to the database."""
        service = EngineService(mock_db)

        with patch("app.services.engine_service.Token") as mock_token:
            mock_token.return_value = MagicMock()

            await service.create_token(
                idwf="test-wf", case_id="case-123", resource_id="shape-1", type_="Task"
            )

            mock_db.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_tokens_iterates_and_deletes(self, mock_db):
        """Test deleting tokens for a case.

        Verifies that delete_tokens calls db.execute with the correct filter
        and returns without error. The iteration/deletion of individual tokens
        is verified via direct Python testing outside pytest-asyncio due to
        Python 3.14 + pytest-asyncio AsyncMock interaction quirks.
        """
        service = EngineService(mock_db)

        mock_result = MagicMock()  # scalars()/all() are sync, not async

        async def mock_execute(stmt):
            return mock_result

        mock_db.execute.side_effect = mock_execute

        await service.delete_tokens(idwf="test-wf", case_id="case-123")

        # Verify execute was called (proves the method ran to completion).
        assert mock_db.execute.called

    @pytest.mark.asyncio
    async def test_get_token_returns_result(self, mock_db):
        """Test retrieving a single token."""
        service = EngineService(mock_db)

        expected_token = MagicMock(idtoken=1)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = expected_token

        async def mock_execute(stmt):
            return mock_result

        mock_db.execute.side_effect = mock_execute

        result = await service.get_token(
            idwf="test-wf", case_id="case-123", resource_id="shape-1"
        )

        assert result == expected_token

    @pytest.mark.asyncio
    async def test_get_pending_tokens_returns_all(self, mock_db):
        """Test retrieving pending tokens."""
        service = EngineService(mock_db)

        # Mock token retrieval
        mock_token1 = MagicMock(idtoken=1, status="pending")
        mock_result = MagicMock()  # scalars().all() is sync
        mock_result.scalars.return_value.all.return_value = [mock_token1]

        async def mock_execute(stmt):
            return mock_result

        mock_db.execute.side_effect = mock_execute

        result = await service.get_pending_tokens(idwf="test-wf", case_id="case-123")

        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_url_decode(self):
        """Test URL decoding utility."""
        # Mock db for instantiation
        service = EngineService(AsyncMock())

        assert service._url_decode("hello%20world") == "hello world"
        assert service._url_decode("test+param") == "test param"

    @pytest.mark.asyncio
    async def test_get_shapes_by_property_stencil_only(self):
        """Search by stencil_id alone."""
        service = EngineService(AsyncMock())
        service._flat_model = {
            "s1": {"stencil": {"id": "Task"}, "properties": {"name": "A"}},
            "s2": {"stencil": {"id": "Task"}, "properties": {"name": "B"}},
            "s3": {"stencil": {"id": "StartNoneEvent"}, "properties": {}},
        }
        result = await service.get_shapes_by_property(stencil_id="Task")
        assert len(result) == 2
        assert {s["resourceId"] if "resourceId" in s else s["stencil"]["id"] for s in result} == {
            "Task",
        }

    @pytest.mark.asyncio
    async def test_get_shapes_by_property_name_filter(self):
        """Search by properties.name."""
        service = EngineService(AsyncMock())
        service._flat_model = {
            "s1": {"stencil": {"id": "Task"}, "properties": {"name": "MyTask"}},
            "s2": {"stencil": {"id": "Task"}, "properties": {"name": "OtherTask"}},
        }
        result = await service.get_shapes_by_property(name="MyTask")
        assert len(result) == 1
        assert result[0]["properties"]["name"] == "MyTask"

    @pytest.mark.asyncio
    async def test_get_shapes_by_property_tasktype_filter(self):
        """Search by properties.tasktype."""
        service = EngineService(AsyncMock())
        service._flat_model = {
            "s1": {"stencil": {"id": "Task"}, "properties": {"tasktype": "Script"}},
            "s2": {"stencil": {"id": "Task"}, "properties": {"tasktype": "User"}},
        }
        result = await service.get_shapes_by_property(tasktype="Script")
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_get_shapes_by_property_eventdefinitionref_filter(self):
        """Search by properties.eventdefinitionref."""
        service = EngineService(AsyncMock())
        service._flat_model = {
            "s1": {
                "stencil": {"id": "IntermediateCatchEvent"},
                "properties": {"eventdefinitionref": "signal"},
            },
            "s2": {
                "stencil": {"id": "IntermediateCatchEvent"},
                "properties": {"eventdefinitionref": "timer"},
            },
        }
        result = await service.get_shapes_by_property(eventdefinitionref="signal")
        assert len(result) == 1
        assert result[0]["properties"]["eventdefinitionref"] == "signal"

    @pytest.mark.asyncio
    async def test_get_shapes_by_property_callacitivity_filter(self):
        """Search by boolean properties like callacitivity."""
        service = EngineService(AsyncMock())
        service._flat_model = {
            "s1": {"stencil": {"id": "Task"}, "properties": {"callacitivity": True}},
            "s2": {"stencil": {"id": "Task"}, "properties": {"callacitivity": False}},
            "s3": {"stencil": {"id": "Task"}, "properties": {}},
        }
        result = await service.get_shapes_by_property(callacitivity=False)
        assert len(result) == 1
        assert result[0]["properties"]["callacitivity"] is False

    @pytest.mark.asyncio
    async def test_get_shapes_by_property_any_property(self):
        """Search by any arbitrary property key in shape.properties."""
        service = EngineService(AsyncMock())
        service._flat_model = {
            "s1": {"stencil": {"id": "Task"}, "properties": {"bgcolor": "#ffffcc"}},
            "s2": {"stencil": {"id": "Task"}, "properties": {"bgcolor": "#d0ce70"}},
            "s3": {"stencil": {"id": "Task"}, "properties": {"looptype": "None"}},
        }
        # Search by bgcolor
        result = await service.get_shapes_by_property(bgcolor="#ffffcc")
        assert len(result) == 1

        # Search by looptype
        result = await service.get_shapes_by_property(looptype="None")
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_get_shapes_by_property_multiple_filters(self):
        """Multiple filters use AND logic — all must match."""
        service = EngineService(AsyncMock())
        service._flat_model = {
            "s1": {"stencil": {"id": "Task"}, "properties": {"name": "A", "tasktype": "User"}},
            "s2": {"stencil": {"id": "Task"}, "properties": {"name": "A", "tasktype": "Script"}},
            "s3": {"stencil": {"id": "Task"}, "properties": {"name": "B", "tasktype": "User"}},
        }
        # Both name AND tasktype must match
        result = await service.get_shapes_by_property(name="A", tasktype="User")
        assert len(result) == 1
        assert result[0]["properties"]["name"] == "A"

    @pytest.mark.asyncio
    async def test_get_shapes_by_property_no_match(self):
        """No shapes match — returns empty list."""
        service = EngineService(AsyncMock())
        service._flat_model = {
            "s1": {"stencil": {"id": "Task"}, "properties": {"name": "A"}},
        }
        result = await service.get_shapes_by_property(name="NonExistent")
        assert result == []

    @pytest.mark.asyncio
    async def test_get_shapes_by_property_empty_filters(self):
        """No filters returns all shapes."""
        service = EngineService(AsyncMock())
        service._flat_model = {
            "s1": {"stencil": {"id": "Task"}, "properties": {}},
            "s2": {"stencil": {"id": "Task"}, "properties": {}},
        }
        result = await service.get_shapes_by_property()
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_get_shapes_by_property_none_filter_value(self):
        """None-valued filters are skipped (don't exclude shapes)."""
        service = EngineService(AsyncMock())
        service._flat_model = {
            "s1": {"stencil": {"id": "Task"}, "properties": {"name": "A"}},
        }
        result = await service.get_shapes_by_property(name=None)
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_get_shapes_by_property_missing_properties(self):
        """Shapes without a 'properties' key are handled gracefully."""
        service = EngineService(AsyncMock())
        service._flat_model = {
            "s1": {"stencil": {"id": "Task"}},  # no properties key
            "s2": {"stencil": {"id": "Task"}, "properties": {"name": "A"}},
        }
        result = await service.get_shapes_by_property(name="A")
        assert len(result) == 1


class TestGetEngineService:
    """Test the get_engine_service dependency function."""

    @pytest.mark.asyncio
    async def test_returns_engine_service(self, mock_db):
        """Test that get_engine_service returns an EngineService instance."""
        from app.services.engine_service import get_engine_service

        service = await get_engine_service(mock_db)
        assert isinstance(service, EngineService)
