"""Tests for gate shape handlers (ParallelGateway, Exclusive_Databased_Gateway).

Mirrors the test pattern in ``tests/test_flow_handlers.py`` — mocked service,
constructed token/shape dicts, await handle(), assert on call args.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.handlers.gate import _parse_condition


@pytest.fixture
def mock_service():
    """Create a mock EngineService with async methods."""
    service = MagicMock()
    service.movenext = AsyncMock()
    service.get_previous = AsyncMock(return_value=[])
    service.get_token = AsyncMock(return_value=None)
    service.get_shape = AsyncMock(return_value=None)

    # Build db mock chain explicitly so attribute assignment persists.
    real_db = MagicMock()
    result_obj = AsyncMock()
    result_obj.scalar_one_or_none.return_value = None
    real_db.execute = AsyncMock(return_value=result_obj)
    real_db.flush = AsyncMock()
    service.db = real_db

    return service


def _patch_case_data(mock_service, case_data: dict):
    """Patch db.execute to return a specific case_data from scalar_one_or_none."""
    result_obj = MagicMock()
    result_obj.scalar_one_or_none.return_value = case_data

    async def fake_execute(stmt=None):
        return result_obj

    mock_service.db.execute = fake_execute


@pytest.fixture
def gateway_token():
    token = MagicMock()
    token.idwf = "test-model"
    token.case_id = "case-123"
    token.resource_id = "gw-shape-1"
    token.status = "pending"
    return token


def _make_parallel_shape(outgoing_rids=None):
    shape = {
        "resourceId": "gw-shape-1",
        "stencil": {"id": "ParallelGateway"},
        "properties": {},
    }
    if outgoing_rids:
        shape["outgoing"] = [{"resourceId": rid} for rid in outgoing_rids]
    return shape


def _make_exclusive_shape(assignment_expr, outgoing_conditions):
    shape = {
        "resourceId": "gw-shape-1",
        "stencil": {"id": "Exclusive_Databased_Gateway"},
        "properties": {"name": "Decision Gate", "gates_assignments": assignment_expr},
        "outgoing": [{"resourceId": c["resourceId"]} for c in outgoing_conditions],
    }
    return shape


# -- _parse_condition unit tests ------------------------------------------- #


class TestParseCondition:
    def test_plain_value_defaults_to_equals(self):
        op, rhs = _parse_condition("approved")
        assert op == "==" and rhs == "approved"

    def test_greater_than_operator_prefix(self):
        op, rhs = _parse_condition(">5")
        assert op == ">" and rhs == "5"

    def test_greater_equal_operator_prefix(self):
        op, rhs = _parse_condition(">=10")
        assert op == ">=" and rhs == "10"

    def test_not_equals_operator_prefix(self):
        op, rhs = _parse_condition("<>reject")
        assert op == "<>" and rhs == "reject"

    def test_empty_string_returns_default(self):
        op, rhs = _parse_condition("")
        assert op == "==" and rhs == ""


# -- ParallelGateway tests ------------------------------------------------- #


class TestParallelGatewayAdvancesWhenAllFinished:
    @pytest.mark.asyncio
    async def test_all_inbounds_finished_advances(self, mock_service, gateway_token):
        in_a = {"resourceId": "in-shape-a"}
        in_b = {"resourceId": "in-shape-b"}
        fin_a = MagicMock(status="finished")
        fin_b = MagicMock(status="finished")

        mock_service.get_previous.return_value = [in_a, in_b]
        mock_service.get_token.side_effect = lambda *a: (
            fin_a if a[2] == "in-shape-a" else fin_b
        )

        from app.handlers.gate import ParallelGatewayHandler

        await ParallelGatewayHandler().handle(
            gateway_token, _make_parallel_shape(), mock_service
        )
        assert mock_service.movenext.call_count == 1


class TestParallelGatewayWaitsForInbounds:
    @pytest.mark.asyncio
    async def test_some_inbounds_not_finished_waits(self, mock_service, gateway_token):
        in_a = {"resourceId": "in-shape-a"}
        in_b = {"resourceId": "in-shape-b"}
        fin_a = MagicMock(status="finished")
        pend_b = MagicMock(status="pending")

        mock_service.get_previous.return_value = [in_a, in_b]
        mock_service.get_token.side_effect = lambda *a: (
            fin_a if a[2] == "in-shape-a" else pend_b
        )

        from app.handlers.gate import ParallelGatewayHandler

        await ParallelGatewayHandler().handle(
            gateway_token, _make_parallel_shape(), mock_service
        )
        assert mock_service.movenext.call_count == 0


# -- Exclusive_Databased_Gateway tests ------------------------------------- #


class TestExclusiveGatewayChoosesOneOutbound:
    @pytest.mark.asyncio
    async def test_exactly_one_match_advances_it(self, mock_service, gateway_token):
        out_a = {"resourceId": "flow-a", "conditionexpression": "yes"}
        out_b = {"resourceId": "flow-b", "conditionexpression": "no"}

        shape = _make_exclusive_shape("approved", [out_a, out_b])
        _patch_case_data(mock_service, {"approved": "yes"})

        async def fake_get_shape(rid, idwf):
            if rid == "flow-a":
                return {
                    "resourceId": "flow-a",
                    "stencil": {"id": "SequenceFlow"},
                    "properties": {
                        "conditiontype": "Expression",
                        "conditionexpression": "yes",
                    },
                }
            if rid == "flow-b":
                return {
                    "resourceId": "flow-b",
                    "stencil": {"id": "SequenceFlow"},
                    "properties": {
                        "conditiontype": "Expression",
                        "conditionexpression": "no",
                    },
                }
            return None

        mock_service.get_shape.side_effect = fake_get_shape
        mock_service.get_previous.return_value = []

        from app.handlers.gate import ExclusiveDatabasedGatewayHandler

        await ExclusiveDatabasedGatewayHandler().handle(
            gateway_token, shape, mock_service
        )
        assert mock_service.movenext.call_count == 1
        assert mock_service.movenext.call_args[0][0] == "flow-a"


class TestExclusiveGatewayRejectsMultipleMatches:
    @pytest.mark.asyncio
    async def test_multiple_matches_raises(self, mock_service, gateway_token):
        shape = _make_exclusive_shape(
            "match",
            [
                {"resourceId": "flow-a", "conditionexpression": "match"},
                {"resourceId": "flow-b", "conditionexpression": "match"},
            ],
        )
        _patch_case_data(mock_service, {"match": "match"})

        async def fake_get_shape(rid, idwf):
            return {
                "resourceId": rid,
                "stencil": {"id": "SequenceFlow"},
                "properties": {
                    "conditiontype": "Expression",
                    "conditionexpression": "match",
                },
            }

        mock_service.get_shape.side_effect = fake_get_shape
        mock_service.get_previous.return_value = []

        from app.handlers.gate import ExclusiveDatabasedGatewayHandler

        with pytest.raises(ValueError, match="produced 2 matches"):
            await ExclusiveDatabasedGatewayHandler().handle(
                gateway_token, shape, mock_service
            )


class TestExclusiveGatewayFallsBackToDefault:
    @pytest.mark.asyncio
    async def test_fallback_to_default_flow(self, mock_service, gateway_token):
        shape = _make_exclusive_shape(
            "x",
            [
                {"resourceId": "flow-a", "conditionexpression": "nomatch"},
                {
                    "resourceId": "flow-b",
                    "conditionexpression": "",
                },  # empty -> skipped in first loop
            ],
        )
        _patch_case_data(mock_service, {})

        async def fake_get_shape(rid, idwf):
            if rid == "flow-a":
                return {
                    "resourceId": "flow-a",
                    "stencil": {"id": "SequenceFlow"},
                    "properties": {
                        "conditiontype": "Expression",
                        "conditionexpression": "nomatch",
                    },
                }
            if rid == "flow-b":
                return {
                    "resourceId": "flow-b",
                    "stencil": {"id": "SequenceFlow"},
                    "properties": {
                        "conditiontype": "Default",
                        "conditionexpression": "",
                    },
                }
            return None

        mock_service.get_shape.side_effect = fake_get_shape
        mock_service.get_previous.return_value = []

        from app.handlers.gate import ExclusiveDatabasedGatewayHandler

        await ExclusiveDatabasedGatewayHandler().handle(
            gateway_token, shape, mock_service
        )
        assert mock_service.movenext.call_count == 1
        assert mock_service.movenext.call_args[0][0] == "flow-b"


class TestExclusiveGatewayNoAssignmentMovesNext:
    @pytest.mark.asyncio
    async def test_empty_assignment_movenext(self, mock_service, gateway_token):
        shape = _make_exclusive_shape("", [])

        from app.handlers.gate import ExclusiveDatabasedGatewayHandler

        await ExclusiveDatabasedGatewayHandler().handle(
            gateway_token, shape, mock_service
        )
        assert mock_service.movenext.call_count == 1
        assert mock_service.movenext.call_args[0][0] == "gw-shape-1"


class TestExclusiveGatewayOperatorParsingIntegration:
    @pytest.mark.asyncio
    async def test_greater_than_condition(self, mock_service, gateway_token):
        # assignment_expr="score", condition ">5": _parse_condition(">5") -> (">", "5").
        # case_data['score'] = '9'; eval ("score") > '5' with resolved assignment
        # becomes '9' > '5' (string compare) -> True.
        out_a = {"resourceId": "flow-a", "conditionexpression": ">5"}

        shape = _make_exclusive_shape("score", [out_a])
        _patch_case_data(mock_service, {"score": "9"})

        async def fake_get_shape(rid, idwf):
            return {
                "resourceId": rid,
                "stencil": {"id": "SequenceFlow"},
                "properties": {
                    "conditiontype": "Expression",
                    "conditionexpression": ">5",
                },
            }

        mock_service.get_shape.side_effect = fake_get_shape
        mock_service.get_previous.return_value = []

        from app.handlers.gate import ExclusiveDatabasedGatewayHandler

        await ExclusiveDatabasedGatewayHandler().handle(
            gateway_token, shape, mock_service
        )
        assert mock_service.movenext.call_count == 1


# -- GenericGatewayHandler tests ------------------------------------------- #


class TestGenericGatewayAdvancesAllOutgoing:
    @pytest.mark.asyncio
    async def test_generic_gateway_movenexts_all_outgoing(
        self, mock_service, gateway_token
    ):
        from app.handlers.gate import GenericGatewayHandler

        shape = {
            "resourceId": "gw-shape-1",
            "stencil": {"id": "InclusiveGateway"},
            "outgoing": [{"resourceId": f"flow-{c}"} for c in "abc"],
        }
        await GenericGatewayHandler().handle(gateway_token, shape, mock_service)
        assert mock_service.movenext.call_count == 3
