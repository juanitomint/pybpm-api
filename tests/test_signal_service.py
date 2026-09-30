"""Tests for SignalService — broadcast, find, and case queries."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.signal_service import SignalService


@pytest.fixture
def mock_db():
    """Create a mock async database session."""
    db = AsyncMock()
    db.flush = AsyncMock(return_value=None)
    db.execute.return_value = AsyncMock()
    return db


class TestSignalServiceBroadcast:
    """Test SignalService.broadcast() — the new global signal method."""

    @pytest.mark.asyncio
    async def test_broadcast_creates_signal_row(self, mock_db):
        """broadcast creates a Signal row with all fields."""
        svc = SignalService(mock_db)
        result = await svc.broadcast(
            name="mySignal",
            idwf="wf-123",
            case_id="case-456",
            resource_id="shape-789",
        )
        assert result.name == "mySignal"
        assert result.idwf == "wf-123"
        assert result.case_id == "case-456"
        assert result.resource_id == "shape-789"
        mock_db.add.assert_called_once()
        mock_db.flush.assert_called_once()

    @pytest.mark.asyncio
    async def test_broadcast_without_case_id(self, mock_db):
        """broadcast works with case_id=None for global signals."""
        svc = SignalService(mock_db)
        result = await svc.broadcast(
            name="globalSignal",
            idwf="wf-123",
            case_id=None,
            resource_id=None,
        )
        assert result.name == "globalSignal"
        assert result.case_id is None
        assert result.resource_id is None

    @pytest.mark.asyncio
    async def test_broadcast_sets_data_json(self, mock_db):
        """broadcast initializes data_json to empty dict."""
        svc = SignalService(mock_db)
        await svc.broadcast(
            name="sig",
            idwf="wf-1",
            case_id="c1",
            resource_id="r1",
        )
        # The Signal constructor receives data_json={}
        added = mock_db.add.call_args
        signal_obj = added[0][0]
        assert signal_obj.data_json == {}

    @pytest.mark.asyncio
    async def test_broadcast_all_params(self, mock_db):
        """broadcast with all parameters populated."""
        svc = SignalService(mock_db)
        result = await svc.broadcast(
            name="orderPlaced",
            idwf="model-v2",
            case_id="case-001",
            resource_id="signal-throw-1",
        )
        assert result.name == "orderPlaced"
        assert result.idwf == "model-v2"
        assert result.case_id == "case-001"
        assert result.resource_id == "signal-throw-1"


class TestSignalServiceFindByname:
    """Test SignalService.find_by_name()."""

    @pytest.mark.asyncio
    async def test_find_by_name_returns_matching_signals(self, mock_db):
        """find_by_name returns all signals with matching name."""
        signal1 = MagicMock(idsignal=1, _name="orderPlaced", idwf="wf-1", case_id="c1", resource_id="r1")
        signal2 = MagicMock(idsignal=2, _name="orderPlaced", idwf="wf-2", case_id="c2", resource_id="r2")

        mock_result = MagicMock()
        mock_result.scalars().all.return_value = [signal1, signal2]

        async def mock_execute(stmt):
            return mock_result

        mock_db.execute.side_effect = mock_execute

        svc = SignalService(mock_db)
        result = await svc.find_by_name("orderPlaced")

        assert len(result) == 2
        # Check idsignal to verify correct signals returned (MagicMock shadows 'name')
        assert {s.idsignal for s in result} == {1, 2}

    @pytest.mark.asyncio
    async def test_find_by_name_no_match(self, mock_db):
        """find_by_name returns empty list when no signals match."""
        mock_result = MagicMock()
        mock_result.scalars().all.return_value = []

        async def mock_execute(stmt):
            return mock_result

        mock_db.execute.side_effect = mock_execute

        svc = SignalService(mock_db)
        result = await svc.find_by_name("nonexistent")

        assert result == []


class TestSignalServiceGetSignalsByCase:
    """Test SignalService.get_signals_by_case()."""

    @pytest.mark.asyncio
    async def test_get_signals_by_case_filters_correctly(self, mock_db):
        """get_signals_by_case returns only signals for the given case/idwf."""
        signal1 = MagicMock(idsignal=1, name="sig1", idwf="wf-1", case_id="c1", resource_id="r1")
        signal2 = MagicMock(idsignal=2, name="sig2", idwf="wf-1", case_id="c1", resource_id="r2")
        signal3 = MagicMock(idsignal=3, name="sig3", idwf="wf-2", case_id="c1", resource_id="r3")

        mock_result = MagicMock()
        mock_result.scalars().all.return_value = [signal1, signal2]

        async def mock_execute(stmt):
            return mock_result

        mock_db.execute.side_effect = mock_execute

        svc = SignalService(mock_db)
        result = await svc.get_signals_by_case(case_id="c1", idwf="wf-1")

        assert len(result) == 2
        assert all(s.idwf == "wf-1" for s in result)
        assert all(s.case_id == "c1" for s in result)


class TestSignalThrowingHandlerIntegration:
    """Test that IntermediateSignalEventThrowingHandler calls both broadcast and movenext."""

    @pytest.mark.asyncio
    async def test_handler_calls_broadcast_with_all_params(self):
        """Handler passes name, idwf, case_id, resource_id to broadcast."""
        from app.handlers.event import IntermediateSignalEventThrowingHandler
        from app.services.signal_service import SignalService

        mock_db = AsyncMock()
        mock_db.flush = AsyncMock()

        mock_service = MagicMock()
        mock_service.db = mock_db
        mock_service.movenext = AsyncMock()
        mock_service.get_shapes_by_property = AsyncMock(return_value=[])

        # Track what broadcast was called with
        broadcast_calls = []

        async def track_broadcast(name, idwf, case_id=None, resource_id=None):
            broadcast_calls.append({
                "name": name,
                "idwf": idwf,
                "case_id": case_id,
                "resource_id": resource_id,
            })
            sig = MagicMock()
            sig.name = name
            sig.idwf = idwf
            sig.case_id = case_id
            sig.resource_id = resource_id
            sig.data_json = {}
            return sig

        token = MagicMock()
        token.idwf = "wf-test"
        token.case_id = "case-abc"

        shape = {
            "resourceId": "signal-throw-shape",
            "stencil": {"id": "IntermediateSignalEventThrowing"},
            "properties": {"name": "orderPlaced"},
        }

        with patch.object(SignalService, "broadcast", new_callable=AsyncMock, side_effect=track_broadcast):
            handler = IntermediateSignalEventThrowingHandler()
            result = await handler.handle(token, shape, mock_service)

        assert result is False
        assert len(broadcast_calls) == 1
        assert broadcast_calls[0]["name"] == "orderPlaced"
        assert broadcast_calls[0]["idwf"] == "wf-test"
        assert broadcast_calls[0]["case_id"] == "case-abc"
        assert broadcast_calls[0]["resource_id"] == "signal-throw-shape"
        mock_service.movenext.assert_called_once()

    @pytest.mark.asyncio
    async def test_handler_returns_false(self):
        """Handler returns False so the engine dispatcher calls movenext."""
        from app.handlers.event import IntermediateSignalEventThrowingHandler
        from app.services.signal_service import SignalService

        mock_db = AsyncMock()
        mock_db.flush = AsyncMock()

        mock_service = MagicMock()
        mock_service.db = mock_db
        mock_service.movenext = AsyncMock()
        mock_service.get_shapes_by_property = AsyncMock(return_value=[])

        token = MagicMock()
        token.idwf = "wf-1"
        token.case_id = "c1"

        shape = {
            "resourceId": "s1",
            "stencil": {"id": "IntermediateSignalEventThrowing"},
            "properties": {"name": "sig"},
        }

        with patch.object(SignalService, "broadcast", new_callable=AsyncMock):
            handler = IntermediateSignalEventThrowingHandler()
            result = await handler.handle(token, shape, mock_service)

        assert result is False

    @pytest.mark.asyncio
    async def test_handler_skips_broadcast_when_no_name(self):
        """Handler skips broadcast when shape has no signal name."""
        from app.handlers.event import IntermediateSignalEventThrowingHandler
        from app.services.signal_service import SignalService

        mock_db = AsyncMock()
        mock_db.flush = AsyncMock()

        mock_service = MagicMock()
        mock_service.db = mock_db
        mock_service.movenext = AsyncMock()
        mock_service.get_shapes_by_property = AsyncMock(return_value=[])
        broadcast_called = False

        async def track_broadcast(*a, **kw):
            nonlocal broadcast_called
            broadcast_called = True

        token = MagicMock()
        token.idwf = "wf-1"
        token.case_id = "c1"

        shape = {
            "resourceId": "s1",
            "stencil": {"id": "IntermediateSignalEventThrowing"},
            "properties": {},
        }

        with patch.object(SignalService, "broadcast", new_callable=AsyncMock, side_effect=track_broadcast):
            handler = IntermediateSignalEventThrowingHandler()
            result = await handler.handle(token, shape, mock_service)

        assert result is False
        assert broadcast_called is False
        mock_service.movenext.assert_called_once()
