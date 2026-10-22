"""Gate shape handlers: ParallelGateway, Exclusive_Databased_Gateway, and EventbasedGateway.

Mirrors legacy ``run_ParallelGateway()``, ``run_Exclusive_Databased_Gateway()``,
and ``run_EventbasedGateway()`` from
``dna2bpm/application/modules/bpm/helpers/bpmn2.0/gate_helper.php``.

Also provides a generic fallback handler for stencils that do not yet have a
dedicated implementation (InclusiveGateway).
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa

from app.handlers.flow import _safe_eval
from app.api.bpm.engine import ENGINE_HANDLER_REGISTRY
import re

# -- ParallelGateway -------------------------------------------------------- #


class ParallelGatewayHandler:
    """Handle a token arriving on a ParallelGateway shape.

    Synchronizes incoming flows: only advances when *all* inbound tokens are
    finished; otherwise sets this gateway's status to ``'waiting'`` so the next
    engine iteration can retry once more inbounds complete.

    Mirrors legacy ``run_ParallelGateway()`` (gate_helper.php:3-23).
    """

    _STENCIL_ID = "ParallelGateway"

    @classmethod
    def stencil_id(cls) -> str:
        return cls._STENCIL_ID

    async def handle(self, token: Any, shape: dict[str, Any], service: Any) -> bool:
        """Check inbound tokens; movenext if all finished, else wait."""
        idwf = token.idwf
        case_id = token.case_id
        resource_id = token.resource_id

        inbound = await service.get_previous(resource_id, idwf)

        has_all_finished = True
        for in_shape in inbound:
            in_rid = in_shape.get("resourceId") or in_shape.get("id", "")
            if not in_rid:
                continue

            # Check if token exists for this inbound shape
            in_token = await service.get_token(idwf, case_id, in_rid)

            # If no token exists yet (not created), gateway must wait
            if not in_token:
                has_all_finished = False
                break

            # Check token status
            status = getattr(in_token, "status", None)
            if status != "finished":
                has_all_finished = False
                break

        if has_all_finished:
            await service.movenext(resource_id, idwf, case_id)
            return False
        else:
            from app.models.token import Token as TokenModel

            update_stmt = (
                sa.update(TokenModel)
                .where(
                    TokenModel.idwf == idwf,
                    TokenModel.case_id == case_id,
                    TokenModel.resource_id == resource_id,
                )
                .values(status="waiting")
            )
            await service.db.execute(update_stmt)  # type: ignore[misc]
            return False


# -- Exclusive_Databased_Gateway -------------------------------------------- #

#: Operator list in priority order (multi-char first so '>=' beats '>').
_OP_PRIORITY = [">=", "<=", "<>", "!=", "==", ">", "<"]


def _parse_condition(cond_str: str) -> tuple[str, str]:
    """Parse a legacy PHP-style condition expression into (op, rhs).

    Legacy ``conditionexpression`` is a bare value like ``"approved"`` or
    ``">=5"`` — the operator may be embedded as a prefix. We scan for the
    first matching operator and split on it; default op is ``'=='``.

    Returns (op, rhs) where rhs has surrounding quotes stripped.
    """
    s = cond_str.strip()
    if not s:
        return "==", ""
    for op in _OP_PRIORITY:
        if s.startswith(op):
            rhs = s[len(op) :].strip().strip("'\"")
            return op, rhs
    return "==", s.strip("'\"")


#: Keywords/operators that indicate gates_assignments is a full expression, not a key name.
_EXPRESSION_OPS = frozenset(
    ("==", "!=", "<>", ">=", "<=", ">", "<", " in ", " not in ", " and ", " or ", " not ")
)


def _is_expression(s: str) -> bool:
    """Detect whether ``s`` is a full expression or a simple key name.

    If it contains operators/keywords that only make sense in an expression,
    treat it as a full expression; otherwise treat it as a key name to look
    up in case_data.
    """
    if any(op in s for op in _EXPRESSION_OPS):
        return True
    return bool(re.search(r'\bnot\b', s))


def _make_eval_str(assignment_expr: str, op: str, rhs: str, case_data: dict) -> str:
    """Build the comparison string for ``_safe_eval``.

    Handles four cases:
    1. ``assignment_expr`` is a full expression → evaluate and compare result.
    2. ``case_data[key]`` is a list → use ``in`` operator (string-converted).
    3. ``case_data[key]`` is a bool → compare with ``is``.
    4. Default → ``({key}) {op} '{rhs}'``.
    """
    if _is_expression(assignment_expr):
        # Full expression — evaluate it and compare the result against rhs.
        rhs_bool = rhs.lower() in ("true", "1", "yes")
        if op == "==":
            return f"bool({assignment_expr}) == {rhs_bool}"
        return f"bool({assignment_expr}) != {rhs_bool}"

    # Strip $ prefix (legacy PHP variable reference) when treating as key name.
    lookup_expr = assignment_expr.lstrip('$') if not _is_expression(assignment_expr) else assignment_expr
    lhs_value = case_data.get(lookup_expr)

    # Case: lhs is a list → use ``in`` operator.
    # Convert list elements to strings (mirrors PHP loose comparison).
    if isinstance(lhs_value, list):
        str_list = [str(x) for x in lhs_value]
        return f"'{rhs}' in {repr(str_list)}"

    # Case: lhs is a bool → use ``is`` comparison.
    if isinstance(lhs_value, bool):
        rhs_bool = rhs.lower() in ("true", "1", "yes")
        if op == "==":
            return f"({lookup_expr}) is {rhs_bool}"
        return f"({lookup_expr}) is not {rhs_bool}"

    # Case: rhs is a comma-separated string → check if lhs is in the list (PHP in_array semantics).
    if isinstance(rhs, str) and "," in rhs:
        return f"{repr(str(lhs_value))} in {repr(rhs.split(','))}"

    # Case: lhs is a comma-separated string → split and ``in``.
    if isinstance(lhs_value, str) and "," in lhs_value:
        return f"'{rhs}' in '{lhs_value}'.split(',')"

    # Default: simple key comparison.
    return f"({lookup_expr}) {op} '{rhs}'"


class ExclusiveDatabasedGatewayHandler:
    """Handle a token arriving on an Exclusive_Databased_Gateway shape.

    Evaluates ``gates_assignments`` against each outgoing SequenceFlow's
    ``conditionexpression`` using the same PHP-style comparison semantics, picks
    exactly one winning flow, marks the gateway finished, records history, and
    advances via movenext on that flow.

    Mirrors legacy ``run_Exclusive_Databased_Gateway()`` (gate_helper.php:25-181).
    """

    _STENCIL_ID = "Exclusive_Databased_Gateway"

    @classmethod
    def stencil_id(cls) -> str:
        return cls._STENCIL_ID

    async def handle(self, token: Any, shape: dict[str, Any], service: Any) -> bool:
        """Evaluate assignment expressions; choose exactly one outbound flow."""
        idwf = token.idwf
        case_id = token.case_id
        resource_id = token.resource_id

        props = shape.get("properties") or {}
        assignment_expr = getattr(props.get("gates_assignments"), "value", None) or (
            props.get("gates_assignments")
            if isinstance(props.get("gates_assignments"), str)
            else ""
        )

        # No assignments defined — fall through to default movenext behavior.
        if not assignment_expr:
            await service.movenext(resource_id, idwf, case_id)
            return False

        # Fetch case data so assignment variables resolve in eval context.
        from app.models.case import BpmCase as _BpmCase

        fetch_stmt = sa.select(_BpmCase.data).where(
            _BpmCase.idcase == case_id,
            _BpmCase.idwf == idwf,
        )
        fetched = await service.db.execute(fetch_stmt)  # type: ignore[misc]
        case_data = fetched.scalar_one_or_none() or {}




        outgoing = shape.get("outgoing") or []
        results: dict[
            str, tuple[dict, bool]
        ] = {}  # rid -> (shape_info_dict, eval_bool)
        match_count = 0

        for out_ref in outgoing:
            if not isinstance(out_ref, dict):
                continue
            out_rid = out_ref.get("resourceId") or out_ref.get("id", "")
            if not out_rid:
                continue

            out_shape = await service.get_shape(out_rid, idwf)
            if not out_shape:
                continue
            out_stencil = (out_shape.get("stencil") or {}).get("id", "")
            if out_stencil != "SequenceFlow":
                continue

            out_props = out_shape.get("properties") or {}
            cond_str = getattr(out_props.get("conditionexpression"), "value", None) or (
                out_props.get("conditionexpression")
                if isinstance(out_props.get("conditionexpression"), str)
                else ""
            )
            if not cond_str:
                continue

            op, rhs = _parse_condition(cond_str)

            # Build the comparison expression using type-aware logic.
            eval_str = _make_eval_str(assignment_expr, op, rhs, case_data)

            try:
                eval_result = _safe_eval(eval_str, case_data)
            except Exception:
                eval_result = False
            if eval_result:
                match_count += 1
            results[out_rid] = (out_shape, bool(eval_result))


        # If nothing matched, look for a Default-condition outgoing flow.
        if match_count == 0:
            for out_ref in outgoing:
                if not isinstance(out_ref, dict):
                    continue
                out_rid = out_ref.get("resourceId") or out_ref.get("id", "")
                if not out_rid:
                    continue
                out_shape = await service.get_shape(out_rid, idwf)
                if not out_shape:
                    continue
                out_props = out_shape.get("properties") or {}
                cond_type = getattr(out_props.get("conditiontype"), "value", None) or (
                    out_props.get("conditiontype")
                    if isinstance(out_props.get("conditiontype"), str)
                    else ""
                )
                if cond_type == "Default":
                    match_count += 1
                    results[out_rid] = (out_shape, True)

        # Decision: exactly one winner -> advance it; record history row.
        if match_count != 1:
            raise ValueError(
                f"Exclusive gateway '{props.get('name', resource_id)}' produced "
                f"{match_count} matches — expected exactly one."
            )

        # Select the winning shape by True eval result (not insertion order).
        winning_rid = None
        winning_shape = None
        for rid, (shape_ref, is_match) in results.items():
            if is_match:
                winning_rid = rid
                winning_shape = shape_ref
                break

        from app.models.token import TokenHistory

        # Mark gateway as finished (increment run_count, record history).
        gateway_token = await service.get_token(idwf, case_id, resource_id)
        if gateway_token:
            await service.mark_token_finished(gateway_token)

        chosen_flow_props = (winning_shape or {}).get("properties") or {}
        history = TokenHistory(
            idwf=idwf,
            case_id=case_id,
            resource_id=resource_id,
            type="Exclusive_Databased_Gateway",
            status="finished",
            name=(
                str(chosen_flow_props.get("conditionexpression", ""))
                if isinstance(chosen_flow_props, dict)
                else ""
            ),
        )
        service.db.add(history)  # type: ignore[attr-defined]

        # Create a pending token on the winning flow, then advance it.
        await service.upsert_token(
            idwf=idwf,
            case_id=case_id,
            resource_id=winning_rid,
            type_=(winning_shape or {}).get("stencil", {}).get("id", "SequenceFlow"),
            status="pending",
        )
        await service.db.flush()
        await service.movenext(winning_rid, idwf, case_id)


# -- InclusiveGatewayHandler ------------------------------------------------ #


class InclusiveGatewayHandler:
    """Handle a token arriving on an InclusiveGateway shape.

    Mirrors legacy ``run_InclusiveGateway()`` (gate_helper.php:194-295).

    Behaviors:
    - With ``gates_assignments``: evaluate against each outgoing flow;
      all matching flows are activated (≥1 match required).
    - Without ``gates_assignments``: synchronize inbound flows (like
      ParallelGateway). If any outgoing flow has a condition, treat as
      manual gate (set status 'user').
    """

    _STENCIL_ID = "InclusiveGateway"

    @classmethod
    def stencil_id(cls) -> str:
        return cls._STENCIL_ID

    async def handle(self, token: Any, shape: dict[str, Any], service: Any) -> bool:
        idwf = token.idwf
        case_id = token.case_id
        resource_id = token.resource_id

        props = shape.get("properties") or {}
        assignment_expr = getattr(props.get("gates_assignments"), "value", None) or (
            props.get("gates_assignments")
            if isinstance(props.get("gates_assignments"), str)
            else ""
        )

        # -- Case A: gates_assignments defined — evaluate each outgoing flow -- #
        if assignment_expr:
            from app.models.case import BpmCase as _BpmCase

            fetch_stmt = sa.select(_BpmCase.data).where(
                _BpmCase.idcase == case_id,
                _BpmCase.idwf == idwf,
            )
            fetched = await service.db.execute(fetch_stmt)  # type: ignore[misc]
            case_data = fetched.scalar_one_or_none() or {}
            if not isinstance(case_data, dict):
                case_data = {}

            outgoing = shape.get("outgoing") or []
            matches: list[tuple[str, dict]] = []  # (rid, shape) for each match

            for out_ref in outgoing:
                if not isinstance(out_ref, dict):
                    continue
                out_rid = out_ref.get("resourceId") or out_ref.get("id", "")
                if not out_rid:
                    continue

                out_shape = await service.get_shape(out_rid, idwf)
                if not out_shape:
                    continue
                out_stencil = (out_shape.get("stencil") or {}).get("id", "")
                if out_stencil != "SequenceFlow":
                    continue

                out_props = out_shape.get("properties") or {}
                cond_str = getattr(out_props.get("conditionexpression"), "value", None) or (
                    out_props.get("conditionexpression")
                    if isinstance(out_props.get("conditionexpression"), str)
                    else ""
                )
                if not cond_str:
                    continue

                # InclusiveGateway uses in_array semantics: check if condition
                # value is contained in the assignment.
                lhs_value = case_data.get(assignment_expr)
                if isinstance(lhs_value, list):
                    eval_str = f"'{cond_str}' in {assignment_expr}"
                elif isinstance(lhs_value, str) and "," in lhs_value:
                    eval_str = f"'{cond_str}' in '{lhs_value}'.split(',')"
                else:
                    # Simple key lookup — compare with ==
                    eval_str = f"({assignment_expr}) == '{cond_str}'"

                try:
                    matched = bool(_safe_eval(eval_str, case_data))
                except Exception:
                    matched = False

                if matched:
                    matches.append((out_rid, out_shape))

            if not matches:
                raise ValueError(
                    f"InclusiveGateway '{props.get('name', resource_id)}' produced "
                    f"0 matches — at least one path must match."
                )

            # Mark gateway finished, then movenext on each matched flow.
            from app.models.token import Token as TokenModel

            update_stmt = (
                sa.update(TokenModel)
                .where(
                    TokenModel.idwf == idwf,
                    TokenModel.case_id == case_id,
                    TokenModel.resource_id == resource_id,
                )
                .values(status="finished")
            )
            await service.db.execute(update_stmt)  # type: ignore[misc]

            for out_rid, _out_shape in matches:
                await service.movenext(out_rid, idwf, case_id)

            return False

        # -- Case B: No gates_assignments — check inbound synchronization ----- #
        outgoing = shape.get("outgoing") or []

        # Check if any outgoing flow has a non-empty condition → manual gate.
        has_conditions = False
        for out_ref in outgoing:
            if not isinstance(out_ref, dict):
                continue
            out_rid = out_ref.get("resourceId") or out_ref.get("id", "")
            if not out_rid:
                continue
            out_shape = await service.get_shape(out_rid, idwf)
            if not out_shape:
                continue
            out_props = out_shape.get("properties") or {}
            cond_str = getattr(out_props.get("conditionexpression"), "value", None) or (
                out_props.get("conditionexpression")
                if isinstance(out_props.get("conditionexpression"), str)
                else ""
            )
            if cond_str:
                has_conditions = True
                break

        if has_conditions:
            # Manual gate — set status to 'user' (like Exclusive when manual).
            from app.models.token import Token as TokenModel

            update_stmt = (
                sa.update(TokenModel)
                .where(
                    TokenModel.idwf == idwf,
                    TokenModel.case_id == case_id,
                    TokenModel.resource_id == resource_id,
                )
                .values(status="user")
            )
            await service.db.execute(update_stmt)  # type: ignore[misc]
            return False

        # Synchronize inbound flows (like ParallelGateway).
        inbound = await service.get_previous(resource_id, idwf)
        all_finished = True
        for in_shape in inbound:
            in_rid = in_shape.get("resourceId", "")
            if not in_rid:
                continue
            token_info = await service.get_token(idwf, case_id, in_rid)
            if token_info and token_info.get("status") != "finished":
                all_finished = False
                break

        if all_finished:
            await service.movenext(resource_id, idwf, case_id)
        else:
            from app.models.token import Token as TokenModel

            update_stmt = (
                sa.update(TokenModel)
                .where(
                    TokenModel.idwf == idwf,
                    TokenModel.case_id == case_id,
                    TokenModel.resource_id == resource_id,
                )
                .values(status="waiting")
            )
            await service.db.execute(update_stmt)  # type: ignore[misc]

        return False


# -- GenericGatewayHandler (fallback for unhandled gate stencils) ---------- #


class GenericGatewayHandler:
    """Generic fallback for gate stencils without a dedicated handler yet.

    Covers: any future gate types not explicitly handled. Advances via
    movenext on all outgoing shapes with a TODO marker documenting the
    deferred logic.
    """

    _STENCIL_IDS: frozenset = frozenset()

    @classmethod
    def stencil_id(cls) -> str:
        return "_generic_gateway"  # sentinel; not dispatched by this key

    async def handle(self, token: Any, shape: dict[str, Any], service: Any) -> bool:
        """Forward all tokens to all outgoing flows."""
        idwf = token.idwf
        case_id = token.case_id
        outgoing = shape.get("outgoing") or []
        for out_ref in outgoing:
            rid = out_ref.get("resourceId") if isinstance(out_ref, dict) else None
            if rid:
                await service.movenext(rid, idwf, case_id)
        return False


class EventbasedGatewayHandler:
    """Handle a token arriving on an EventbasedGateway shape.

    Implements BPMN 2.0 exclusive event-based gateway semantics:
    the gateway waits for exactly one of its connected catching events to
    fire, then cancels all remaining pending catchers and advances through
    the winning flow.

    Mirrors legacy ``run_EventbasedGateway()`` (gate_helper.php:297-362).
    """

    _STENCIL_ID = "EventbasedGateway"

    @classmethod
    def stencil_id(cls) -> str:
        return cls._STENCIL_ID

    async def handle(self, token: Any, shape: dict[str, Any], service: Any) -> bool:
        """Check catcher status; cancel losers if one fired, else stay waiting."""
        idwf = token.idwf
        case_id = token.case_id
        resource_id = token.resource_id

        outgoing = shape.get("outgoing") or []
        if not outgoing:
            await service.movenext(resource_id, idwf, case_id)
            return False

        # Iterate outgoing flows and check each catcher's token status.
        # Create pending tokens for catchers that don't have one yet.
        pending_catchers: list[dict] = []
        fired_flow = None  # The flow whose catcher has finished

        for out_ref in outgoing:
            if not isinstance(out_ref, dict):
                continue
            out_rid = out_ref.get("resourceId") or out_ref.get("id", "")
            if not out_rid:
                continue

            out_shape = await service.get_shape(out_rid, idwf)
            if not out_shape:
                continue

            # The gateway's outgoing flows are SequenceFlow shapes; the catcher
            # is the first outgoing shape of the flow (mirrors legacy gate_helper.php L308-310).
            flow_outgoing = out_shape.get("outgoing") or []
            if not flow_outgoing:
                continue

            catcher_ref = flow_outgoing[0]
            catcher_rid = catcher_ref.get("resourceId") if isinstance(catcher_ref, dict) else None
            if not catcher_rid:
                continue

            # Get or create token for the catcher
            catcher_token = await service.get_token(idwf, case_id, catcher_rid)
            if not catcher_token:
                # Look up the full catcher shape to get its stencil type.
                catcher_shape = await service.get_shape(catcher_rid, idwf)
                stencil_id = (
                    (catcher_shape.get("stencil") or {}) if catcher_shape else {}
                ).get("id", "")
                await service.create_token(
                    idwf=idwf,
                    case_id=case_id,
                    resource_id=catcher_rid,
                    type_=stencil_id,
                    status="pending",
                )
                catcher_token = await service.get_token(idwf, case_id, catcher_rid)

            catcher_status = getattr(catcher_token, "status", None)

            if catcher_status == "finished":
                # This catcher's event has fired — exclusive selection.
                fired_flow = out_ref
                # Mark the flow token as finished (mirrors legacy line 330).
                await service._set_token_status(
                    idwf, case_id, out_rid, "finished"
                )
            else:
                # Still pending/waiting — collect catcher rid for cancellation.
                pending_catchers.append(catcher_rid)

        # Set gateway to 'waiting' — it suspends until a catcher fires.
        await service._set_token_status(
            idwf, case_id, resource_id, "waiting"
        )

        if fired_flow is not None:
            # One catcher has finished — cancel all pending catchers.
            cancel_data = {
                "canceledBy": resource_id,
                "canceledName": (shape.get("properties") or {}).get("name", ""),
            }
            for pending_rid in pending_catchers:
                await service._set_token_status(
                    idwf, case_id, pending_rid, "canceled", data=cancel_data
                )

            # Mark gateway as finished.
            await service._set_token_status(
                idwf, case_id, resource_id, "finished"
            )

            # Record history for the winning flow.
            from app.models.token import TokenHistory

            chosen_flow_props = (fired_flow.get("outgoing") or [{}])[0].get("properties") if fired_flow.get("outgoing") else {}
            history = TokenHistory(
                idwf=idwf,
                case_id=case_id,
                resource_id=resource_id,
                type="EventbasedGateway",
                status="finished",
                name=(
                    str(chosen_flow_props.get("name", ""))
                    if isinstance(chosen_flow_props, dict)
                    else ""
                ),
            )
            service.db.add(history)

            # Advance through the winning flow.
            winning_rid = (fired_flow.get("outgoing") or [{}])[0].get("resourceId") if fired_flow.get("outgoing") else None
            if winning_rid:
                await service.movenext(winning_rid, idwf, case_id)
        # else: no catcher fired yet — gateway stays 'waiting' for next engine iteration

        return False



# -- Auto-registration at import time --------------------------------------- #

ENGINE_HANDLER_REGISTRY.register(
    ParallelGatewayHandler._STENCIL_ID, ParallelGatewayHandler
)
ENGINE_HANDLER_REGISTRY.register(
    ExclusiveDatabasedGatewayHandler._STENCIL_ID, ExclusiveDatabasedGatewayHandler
)
ENGINE_HANDLER_REGISTRY.register(
    EventbasedGatewayHandler._STENCIL_ID, EventbasedGatewayHandler
)
ENGINE_HANDLER_REGISTRY.register(
    InclusiveGatewayHandler._STENCIL_ID, InclusiveGatewayHandler
)
