"""Gate shape handlers: ParallelGateway and Exclusive_Databased_Gateway.

Mirrors legacy ``run_ParallelGateway()`` and
``run_Exclusive_Databased_Gateway()`` from
``dna2bpm/application/modules/bpm/helpers/bpmn2.0/gate_helper.php``.

Also provides a generic fallback handler for stencils that do not yet have a
dedicated implementation (InclusiveGateway, EventbasedGateway).
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa

from app.api.bpm.engine import ENGINE_HANDLER_REGISTRY
from app.handlers.flow import _safe_eval


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

    async def handle(self, token: Any, shape: dict[str, Any], service: Any) -> bool:  # noqa: ANN001, D401
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
            
            update_stmt = sa.update(TokenModel).where(
                TokenModel.idwf == idwf,
                TokenModel.case_id == case_id,
                TokenModel.resource_id == resource_id,
            ).values(status="waiting")
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
            rhs = s[len(op):].strip().strip("'\"")
            return op, rhs
    return "==", s.strip("'\"")


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

    async def handle(self, token: Any, shape: dict[str, Any], service: Any) -> bool:  # noqa: ANN001, D401
        """Evaluate assignment expressions; choose exactly one outbound flow."""
        idwf = token.idwf
        case_id = token.case_id
        resource_id = token.resource_id

        props = shape.get("properties") or {}
        assignment_expr = getattr(props.get("gates_assignments"), "value", None) or (
            props.get("gates_assignments") if isinstance(props.get("gates_assignments"), str) else ""
        )

        # No assignments defined — fall through to default movenext behavior.
        if not assignment_expr:
            await service.movenext(resource_id, idwf, case_id)
            return False

        # Fetch case data so assignment variables resolve in eval context.
        from app.models.case import BpmCase as _BpmCase

        fetch_stmt = sa.select(_BpmCase.data).where(
            _BpmCase.idcase == case_id, _BpmCase.idwf == idwf,
        )
        fetched = await service.db.execute(fetch_stmt)  # type: ignore[misc]
        case_data = fetched.scalar_one_or_none() or {}
        if not isinstance(case_data, dict):
            case_data = {}

        outgoing = shape.get("outgoing") or []
        results: dict[str, tuple[dict, bool]] = {}  # rid -> (shape_info_dict, eval_bool)
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
                out_props.get("conditionexpression") if isinstance(out_props.get("conditionexpression"), str) else ""
            )
            if not cond_str:
                continue

            op, rhs = _parse_condition(cond_str)

            # Build comparison expression for _safe_eval. The assignment name is
            # resolved from case_data context; wrap in parens so it's a valid
            # mode='eval' expression: ``(approved) == 'yes'``.
            eval_str = f"({assignment_expr}) {op} '{rhs}'"  # noqa: S307

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
                    out_props.get("conditiontype") if isinstance(out_props.get("conditiontype"), str) else ""
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

        from app.models.token import Token as TokenModel, TokenHistory

        update_stmt = sa.update(TokenModel).where(
            TokenModel.idwf == idwf,
            TokenModel.case_id == case_id,
            TokenModel.resource_id == resource_id,
        ).values(status="finished")
        await service.db.execute(update_stmt)  # type: ignore[misc]

        chosen_flow_props = (winning_shape or {}).get("properties") or {}
        history = TokenHistory(
            idwf=idwf,
            case_id=case_id,
            resource_id=resource_id,
            type="Exclusive_Databased_Gateway",
            status="finished",
            name=str(chosen_flow_props.get("conditionexpression", "")) if isinstance(chosen_flow_props, dict) else "",
        )
        service.db.add(history)  # type: ignore[attr-defined]

        await service.movenext(winning_rid, idwf, case_id)
        return False


# -- GenericGatewayHandler (Inclusive/Eventbased stubs) --------------------- #


class GenericGatewayHandler:
    """Generic fallback for gate stencils without a dedicated handler yet.

    Covers: InclusiveGateway, EventbasedGateway. For v1 compat, advances via
    movenext on all outgoing shapes with a TODO marker documenting the deferred
    logic (PHP L194-362).
    """

    _STENCIL_IDS = frozenset({"InclusiveGateway", "EventbasedGateway"})

    @classmethod
    def stencil_id(cls) -> str:
        return "_generic_gateway"  # sentinel; not dispatched by this key

    async def handle(self, token: Any, shape: dict[str, Any], service: Any) -> bool:  # noqa: ANN001, D401
        """TODO (Phase 4b): full inclusive/event-based routing."""
        idwf = token.idwf
        case_id = token.case_id
        outgoing = shape.get("outgoing") or []
        for out_ref in outgoing:
            rid = out_ref.get("resourceId") if isinstance(out_ref, dict) else None
            if rid:
                await service.movenext(rid, idwf, case_id)
        return False


# -- Auto-registration at import time --------------------------------------- #

ENGINE_HANDLER_REGISTRY.register(ParallelGatewayHandler._STENCIL_ID, ParallelGatewayHandler)
ENGINE_HANDLER_REGISTRY.register(ExclusiveDatabasedGatewayHandler._STENCIL_ID, ExclusiveDatabasedGatewayHandler)

for _stencil in GenericGatewayHandler._STENCIL_IDS:
    ENGINE_HANDLER_REGISTRY.register(_stencil, GenericGatewayHandler)
