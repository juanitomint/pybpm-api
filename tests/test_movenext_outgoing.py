"""Tests that EngineService.movenext() advances to every non-ignored outgoing shape.

These tests patch the three internal methods movenext calls (get_token, get_shape, create_token)
so we can verify *which* outgoing shapes receive pending tokens without hitting the DB.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestMovenextAdvancesAllOutgoingShapes:
    """movenext should create pending tokens on every outgoing edge (except ignored)."""

    @pytest.mark.asyncio
    async def test_fan_out_to_three_tasks(self):
        """A shape with three outgoing edges → three pending task tokens."""
        from app.services.engine_service import EngineService

        mock_db = AsyncMock()
        service = EngineService(mock_db)

        # get_token returns the source token so mark_token_finished can run.
        fake_source_token = MagicMock(idwf="m", case_id="c", resource_id="start")

        shape_with_three_outgoing = {
            "resourceId": "start",
            "stencil": {"id": "StartNoneEvent"},
            "outgoing": [
                {"resourceId": "task-a"},
                {"resourceId": "task-b"},
                {"resourceId": "task-c"},
            ],
        }

        # Per-outgoing-shape shapes (the second get_shape call per iteration).
        outgoing_shapes = {
            "task-a": {"resourceId": "task-a", "stencil": {"id": "Task"}},
            "task-b": {"resourceId": "task-b", "stencil": {"id": "Task"}},
            "task-c": {"resourceId": "task-c", "stencil": {"id": "Task"}},
        }

        created = []

        async def capture_create(**kwargs):
            created.append(kwargs)

        call_seq = 0

        async def mock_get_token(idwf, case_id, resource_id):
            nonlocal call_seq
            call_seq += 1
            if call_seq == 1:
                return fake_source_token  # first call is get_token for source shape
            return None  # subsequent calls check existing tokens on outgoing shapes → none exist

        with (
            patch.object(
                service, "get_token", new_callable=AsyncMock, side_effect=mock_get_token
            ),
            patch.object(
                service,
                "get_shape",
                new_callable=AsyncMock,
                side_effect=lambda rid, _idwf: outgoing_shapes.get(
                    rid, shape_with_three_outgoing
                ),
            ),
            patch.object(service, "create_token", new=capture_create),
            patch.object(service, "mark_token_finished", new_callable=AsyncMock),
        ):
            await service.movenext("start", "m", "c")

        assert len(created) == 3, f"Expected 3 pending tokens; got {len(created)}"
        created_rids = sorted(t["resource_id"] for t in created)
        assert created_rids == ["task-a", "task-b", "task-c"]
        for t in created:
            assert t["status"] == "pending"

    @pytest.mark.asyncio
    async def test_skips_text_annotation_and_association(self):
        """TextAnnotation / Association_Undirected edges must NOT receive tokens."""
        from app.services.engine_service import EngineService

        mock_db = AsyncMock()
        service = EngineService(mock_db)
        fake_token = MagicMock(idwf="m", case_id="c", resource_id="start")

        shape_with_ignored = {
            "resourceId": "start",
            "stencil": {"id": "StartNoneEvent"},
            "outgoing": [
                {"resourceId": "task-real"},
                {"resourceId": "text-note"},
                {"resourceId": "assoc-link"},
            ],
        }
        outgoing_shapes = {
            "start": shape_with_ignored,
            "task-real": {"resourceId": "task-real", "stencil": {"id": "Task"}},
            "text-note": {
                "resourceId": "text-note",
                "stencil": {"id": "TextAnnotation"},
            },
            "assoc-link": {
                "resourceId": "assoc-link",
                "stencil": {"id": "Association_Undirected"},
            },
        }

        created = []

        async def capture_create(**kwargs):
            created.append(kwargs)

        call_seq = 0

        async def mock_get_token(_idwf, _case_id, resource_id):
            nonlocal call_seq
            call_seq += 1
            return fake_token if call_seq == 1 else None

        with (
            patch.object(
                service, "get_token", new_callable=AsyncMock, side_effect=mock_get_token
            ),
            patch.object(
                service,
                "get_shape",
                new_callable=AsyncMock,
                side_effect=lambda rid, _i: outgoing_shapes.get(rid),
            ),
            patch.object(service, "create_token", new=capture_create),
            patch.object(service, "mark_token_finished", new_callable=AsyncMock),
        ):
            await service.movenext("start", "m", "c")

        assert len(created) == 1
        assert created[0]["resource_id"] == "task-real"

    @pytest.mark.asyncio
    async def test_skips_duplicate_existing_token(self):
        """If a token already exists on the outgoing shape, movenext must not create another."""
        from app.services.engine_service import EngineService

        mock_db = AsyncMock()
        service = EngineService(mock_db)
        fake_source = MagicMock(idwf="m", case_id="c", resource_id="start")
        existing_outgoing = MagicMock(idwf="m", case_id="c", resource_id="task-a")

        outgoing_shapes = {
            "task-a": {"resourceId": "task-a", "stencil": {"id": "Task"}},
        }

        created = []

        async def capture_create(**kwargs):
            created.append(kwargs)

        call_seq = 0

        async def mock_get_token(_idwf, _case_id, resource_id):
            nonlocal call_seq
            call_seq += 1
            return fake_source if call_seq == 1 else existing_outgoing

        with (
            patch.object(
                service, "get_token", new_callable=AsyncMock, side_effect=mock_get_token
            ),
            patch.object(
                service,
                "get_shape",
                new_callable=AsyncMock,
                side_effect=lambda rid, _i: outgoing_shapes.get(rid),
            ),
            patch.object(service, "create_token", new=capture_create),
            patch.object(service, "mark_token_finished", new_callable=AsyncMock),
        ):
            await service.movenext("start", "m", "c")

        assert len(created) == 0, (
            f"Expected no new tokens when one already exists; got {created}"
        )

    @pytest.mark.asyncio
    async def test_mixed_outgoing_types_all_get_tokens(self):
        """Outgoing to Task, EndNoneEvent, SequenceFlow — every non-ignored shape gets a pending token with matching type_."""
        from app.services.engine_service import EngineService

        mock_db = AsyncMock()
        service = EngineService(mock_db)
        fake_token = MagicMock(idwf="m", case_id="c", resource_id="gateway")

        outgoing_shapes = {
            "gateway": {
                "resourceId": "gateway",
                "stencil": {"id": "ParallelGateway"},
                "outgoing": [
                    {"resourceId": "task-1"},
                    {"resourceId": "end-a"},
                    {"resourceId": "flow-to-end"},
                ],
            },
            "task-1": {"resourceId": "task-1", "stencil": {"id": "Task"}},
            "end-a": {"resourceId": "end-a", "stencil": {"id": "EndNoneEvent"}},
            "flow-to-end": {
                "resourceId": "flow-to-end",
                "stencil": {"id": "SequenceFlow"},
            },
        }

        created = []

        async def capture_create(**kwargs):
            created.append(kwargs)

        call_seq = 0

        async def mock_get_token(_idwf, _case_id, resource_id):
            nonlocal call_seq
            call_seq += 1
            return fake_token if call_seq == 1 else None

        with (
            patch.object(
                service, "get_token", new_callable=AsyncMock, side_effect=mock_get_token
            ),
            patch.object(
                service,
                "get_shape",
                new_callable=AsyncMock,
                side_effect=lambda rid, _i: outgoing_shapes.get(rid),
            ),
            patch.object(service, "create_token", new=capture_create),
            patch.object(service, "mark_token_finished", new_callable=AsyncMock),
        ):
            await service.movenext("gateway", "m", "c")

        assert len(created) == 3
        created_stencils = {t["resource_id"]: t["type_"] for t in created}
        assert created_stencils == {
            "task-1": "Task",
            "end-a": "EndNoneEvent",
            "flow-to-end": "SequenceFlow",
        }
