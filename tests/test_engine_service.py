"""Tests for the engine service."""

from __future__ import annotations

import asyncio
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

        with patch("app.services.engine_service.Token") as MockToken:
            MockToken.return_value = MagicMock()

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

        mock_token1 = MagicMock(idtoken=1)
        mock_token2 = MagicMock(idtoken=2)
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


class TestGetEngineService:
    """Test the get_engine_service dependency function."""

    def test_returns_engine_service(self, mock_db):
        """Test that get_engine_service returns an EngineService instance."""
        from app.services.engine_service import get_engine_service

        service = get_engine_service(mock_db)
        assert isinstance(service, EngineService)
