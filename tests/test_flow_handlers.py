"""Tests for SequenceFlow and MessageFlow shape handlers."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def mock_service():
    """Create a mock EngineService with async methods."""
    service = MagicMock()
    service.movenext = AsyncMock()
    service.get_previous = AsyncMock()
    service.get_token = AsyncMock()
    service.get_shape = AsyncMock()
    return service


@pytest.fixture
def mock_token():
    """Create a minimal token object."""
    token = MagicMock()
    token.idwf = "test-model"
    token.case_id = "case-123"
    token.resource_id = "shape-resource-1"
    token.status = "pending"
    return token


@pytest.fixture
def sequence_flow_shape():
    """Create a SequenceFlow shape dict with condition expression."""
    return {
        "resourceId": "shape-resource-1",
        "stencil": {"id": "SequenceFlow"},
        "properties": {
            "conditiontype": "Expression",
            "conditionexpression": "True",  # Always true for this test
        },
    }


@pytest.fixture
def message_flow_shape():
    """Create a MessageFlow shape dict with outgoing edges."""
    return {
        "resourceId": "shape-resource-1",
        "stencil": {"id": "MessageFlow"},
        "outgoing": [
            {"resourceId": "catching-shape-1"},
        ],
    }


class TestSequenceFlowHandler:
    """Test SequenceFlow handler logic."""

    @pytest.mark.asyncio
    async def test_sequence_flow_true_condition_moves_next(
        self, mock_token, sequence_flow_shape, mock_service
    ):
        """When condition evaluates true, movenext should be called and return False (handled internally)."""
        # Mock inbound shape with dataoutputset
        inbound_shape = {
            "resourceId": "prev-shape",
            "properties": {
                "dataoutputset": {
                    "items": [{"name": "var1"}],
                }
            },
        }
        mock_service.get_previous.return_value = [inbound_shape]

        # Mock inbound token with data
        inbound_token = MagicMock()
        inbound_token.external_data = {"var1": "value1"}
        mock_service.get_token.return_value = inbound_token

        handler = SequenceFlowHandler()
        result = await handler.handle(mock_token, sequence_flow_shape, mock_service)

        # Should return False because movenext was called internally
        assert result is False
        mock_service.movenext.assert_called_once_with(
            "shape-resource-1", "test-model", "case-123"
        )

    @pytest.mark.asyncio
    async def test_sequence_flow_false_condition_stops_token(
        self, mock_token, sequence_flow_shape, mock_service
    ):
        """When condition evaluates false, token status should be set to 'stoped'."""
        # Update shape to have false condition
        sequence_flow_shape["properties"]["conditionexpression"] = "False"

        handler = SequenceFlowHandler()
        result = await handler.handle(mock_token, sequence_flow_shape, mock_service)

        # Should return True (movenext not called internally)
        assert result is True
        mock_service.movenext.assert_not_called()
        # Token status should be set to stopped
        assert mock_token.status == "stoped"


class TestMessageFlowHandler:
    """Test MessageFlow handler logic."""

    @pytest.mark.asyncio
    async def test_message_flow_advances_catching_events(
        self, mock_token, message_flow_shape, mock_service
    ):
        """Should advance IntermediateMessageEventCatching outgoing shapes and then movenext on itself."""
        # Mock outgoing shape as IntermediateMessageEventCatching
        catching_shape = {
            "resourceId": "catching-shape-1",
            "stencil": {"id": "IntermediateMessageEventCatching"},
        }
        mock_service.get_shape.return_value = catching_shape

        handler = MessageFlowHandler()
        result = await handler.handle(mock_token, message_flow_shape, mock_service)

        # Should return False (movenext called internally)
        assert result is False
        # Should have called movenext on the catching shape AND on itself
        assert mock_service.movenext.call_count == 2
        calls = mock_service.movenext.call_args_list
        assert calls[0].args == ("catching-shape-1", "test-model", "case-123")
        assert calls[1].args == ("shape-resource-1", "test-model", "case-123")

    @pytest.mark.asyncio
    async def test_message_flow_skips_non_catching_outgoing(
        self, mock_token, message_flow_shape, mock_service
    ):
        """Non-catching outgoing shapes should be skipped."""
        # Mock outgoing shape as something other than catching event
        other_shape = {
            "resourceId": "catching-shape-1",
            "stencil": {"id": "Task"},  # Not a catching event
        }
        mock_service.get_shape.return_value = other_shape

        handler = MessageFlowHandler()
        result = await handler.handle(mock_token, message_flow_shape, mock_service)

        # Should only call movenext on itself, not the Task
        assert mock_service.movenext.call_count == 1
        calls = mock_service.movenext.call_args_list
        assert calls[0].args == ("shape-resource-1", "test-model", "case-123")


# Import handlers at module level for test classes
from app.handlers.flow import MessageFlowHandler, SequenceFlowHandler  # noqa: E402, I001
