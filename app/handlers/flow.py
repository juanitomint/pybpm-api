"""SequenceFlow and MessageFlow shape handlers.

Mirrors legacy ``run_SequenceFlow()`` and ``run_MessageFlow()`` from
``dna2bpm/application/modules/bpm/helpers/bpmn2.0/flow_helper.php``.

Registration is automatic via the module-level ``ENGINE_HANDLER_REGISTRY`` —
no explicit import needed beyond importing this package (see ``app/handlers/__init__.py``).
"""

from __future__ import annotations

import ast
from typing import Any

from app.api.bpm.engine import ENGINE_HANDLER_REGISTRY


def _safe_eval(expression: str, context: dict[str, Any] | None = None) -> bool:
    """Evaluate a Python expression safely (mirrors legacy PHP ``eval()``).

    Returns True on truthy result, False otherwise. Raises are treated as falsy
    to match PHP's warning-and-continue behavior.
    """
    if not expression or not expression.strip():
        return False
    try:
        tree = ast.parse(expression.strip(), mode="eval")
        code = compile(tree, "<condition>", "eval")
        local_ns = dict(context) if context else {}
        result = eval(code, {"__builtins__": {}}, local_ns)  # noqa: S307
        return bool(result)
    except Exception:
        return False


class SequenceFlowHandler:
    """Handle a token arriving on a SequenceFlow shape.

    Collects transport data from the inbound shape's token (if ``dataoutputset`` is set),
    evaluates any condition expression, and advances to movenext or stops on failure.
    Mirrors legacy ``run_SequenceFlow()``.
    """

    @classmethod
    def stencil_id(cls) -> str:
        return "SequenceFlow"

    async def handle(self, token, shape, service):  # noqa: ANN001, D401
        """Execute SequenceFlow logic: collect data, evaluate condition, movenext or stop."""
        idwf = token.idwf
        case_id = token.case_id
        resource_id = token.resource_id

        # Collect transport data from inbound shape's token if it has dataoutputset.
        inbound_shapes = await service.get_previous(resource_id, idwf)
        transport_data: dict[str, Any] = {}
        if inbound_shapes:
            first_inbound = inbound_shapes[0]
            props = first_inbound.get("properties", {}) or {}
            data_output_set = props.get("dataoutputset")
            if data_output_set and isinstance(data_output_set, dict):
                items = data_output_set.get("items", [])
                if items:
                    inbound_token = await service.get_token(idwf, case_id, first_inbound["resourceId"])
                    if inbound_token and hasattr(inbound_token, "external_data") and inbound_token.external_data:
                        for item in items:
                            name = getattr(item, "name", None) or (item.get("name") if isinstance(item, dict) else None)
                            if name:
                                transport_data[name] = (
                                    inbound_token.external_data.get(name)
                                    if isinstance(inbound_token.external_data, dict)
                                    else None
                                )

        # Evaluate condition expression if present.
        shape_props = shape.get("properties", {}) or {}
        condition_type = shape_props.get("conditiontype", "None")

        if condition_type == "Expression":
            condition_expr = shape_props.get("conditionexpression", "")
            if _safe_eval(condition_expr, transport_data):
                # Condition true — advance token.
                await service.movenext(resource_id, idwf, case_id)
                return False  # handled movenext internally
            else:
                # Condition false — mark this flow's token as stopped with carry-data.
                from app.models.token import TokenHistory

                history = TokenHistory(
                    idwf=idwf,
                    case_id=case_id,
                    resource_id=resource_id,
                    type="SequenceFlow",
                    status="stoped",
                    name=condition_expr,
                )
                service.db.add(history)  # type: ignore[attr-defined]
                await service.db.flush()
                token.status = "stoped"  # type: ignore[attr-defined]
                return False

        # None or Default — always movenext.
        await service.movenext(resource_id, idwf, case_id)
        return False


class MessageFlowHandler:
    """Handle a token arriving on a MessageFlow shape.

    For each outgoing shape that is an ``IntermediateMessageEventCatching``,
    advance it with collected data. Then always movenext on this flow itself.
    Mirrors legacy ``run_MessageFlow()``.
    """

    @classmethod
    def stencil_id(cls) -> str:
        return "MessageFlow"

    async def handle(self, token, shape, service):  # noqa: ANN001, D401
        """Execute MessageFlow logic: advance catching events, then movenext."""
        idwf = token.idwf
        case_id = token.case_id
        resource_id = token.resource_id

        outgoing_shapes = shape.get("outgoing", []) or []
        transport_data: dict[str, Any] = {}

        # For each outgoing shape that is IntermediateMessageEventCatching, advance it.
        for out_shape_ref in outgoing_shapes:
            out_resource_id = out_shape_ref.get("resourceId") if isinstance(out_shape_ref, dict) else None
            if not out_resource_id:
                continue

            out_shape = await service.get_shape(out_resource_id, idwf)
            if not out_shape:
                continue

            out_stencil = (out_shape.get("stencil") or {}).get("id", "")
            if out_stencil == "IntermediateMessageEventCatching":
                # Advance the catching event with any collected data.
                await service.movenext(out_resource_id, idwf, case_id)

        # Always fall through to movenext on this flow itself.
        await service.movenext(resource_id, idwf, case_id)
        return False


# Auto-register at import time via the registry pattern.
ENGINE_HANDLER_REGISTRY.register("SequenceFlow", SequenceFlowHandler)
ENGINE_HANDLER_REGISTRY.register("MessageFlow", MessageFlowHandler)
