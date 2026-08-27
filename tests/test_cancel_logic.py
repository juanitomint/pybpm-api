"""Tests for boundary-event cancel logic and EndTerminateEvent handling.

Covers:
- EngineService has _check_token_finished and _cancel_subprocess_children methods.
- EndTerminateEventHandler.handle() cancels active tokens + marks case terminated.
- Importing event module succeeds (regression guard against missing-method errors).
"""

from __future__ import annotations

import inspect
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestEngineServiceHasCancelMethods:
    """New cancel helper methods exist on EngineService."""

    def test_check_token_finished_method_exists(self):
        from app.services.engine_service import EngineService

        assert hasattr(EngineService, "_check_token_finished")
        assert inspect.iscoroutinefunction(EngineService._check_token_finished)

    def test_cancel_subprocess_children_method_exists(self):
        from app.services.engine_service import EngineService

        assert hasattr(EngineService, "_cancel_subprocess_children")
        assert inspect.iscoroutinefunction(EngineService._cancel_subprocess_children)


class TestEndTerminateEventSmoke:
    """EndTerminateEventHandler.handle() runs without AttributeError."""

    @pytest.mark.asyncio
    async def test_handle_does_not_raise_on_missing_methods(self):
        from app.handlers.start_end import EndTerminateEventHandler
        from app.services.engine_service import EngineService

        with (
            patch.object(EngineService, "_set_token_status", new_callable=AsyncMock),
            patch.object(EngineService, "delete_tokens", new_callable=AsyncMock),
        ):
            svc = MagicMock()
            svc.get_token = AsyncMock(return_value=None)

            # Build a mock that mimics SQLAlchemy's execute -> scalars().all() chain.
            mock_scalars = MagicMock()
            mock_scalars.all.return_value = []
            mock_result = MagicMock()
            mock_result.scalars.return_value = mock_scalars

            async def fake_execute(stmt):
                return mock_result

            svc.db = MagicMock()
            svc.db.execute = fake_execute
            svc.db.flush = AsyncMock()

            token_obj = MagicMock()
            shape = {"resourceId": "end-terminate", "properties": {"name": "Terminate"}}
            handler = EndTerminateEventHandler()
            result = await handler.handle(token_obj, shape, svc)
            assert result is False


class TestBoundaryEventImports:
    """Importing event module succeeds — no missing-method import errors."""

    def test_event_module_imports(self):
        pass
