"""Task shape handler.

Mirrors legacy ``run_Task()`` from
``dna2bpm/application/modules/bpm/helpers/bpmn2.0/task_helper.php``.

Handles User, Manual, Script, Send, Receive task types with branching on the
shape's ``properties.tasktype`` value. Also implements loop-type guard so a task
runs exactly once per engine invocation (mirrors PHP's ``$wf->task_run`` stack).

Registration is automatic via the module-level ``ENGINE_HANDLER_REGISTRY`` —
no explicit import needed beyond importing this package.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa

from app.api.bpm.engine import ENGINE_HANDLER_REGISTRY
from app.handlers.eval_context import DataStorage, build_script_namespace
from app.handlers.flow import _eval_script


class TaskHandler:
    """Handle a token arriving on a Task shape.

    Branches on ``shape.properties.tasktype`` and applies the matching behavior:
    User/Manual → mark status 'user' and stop (wait for manual POST).
    Script → eval script string, store result in case data, movenext.
    Send → movenext (message dispatch deferred — no inbox service yet).
    Default → movenext.

    Also implements a loop-type guard: if the shape's ``looptype`` is not
    Standard/None and this task has already run in the current engine invocation,
    skip it entirely (mirrors legacy ``$wf->task_run`` check at PHP L16-30).

    Mirrors legacy ``run_Task()``.
    """

    _STENCIL_ID = "Task"

    @classmethod
    def stencil_id(cls) -> str:
        return cls._STENCIL_ID

    async def handle(self, token: Any, shape: dict[str, Any], service: Any) -> bool:
        """Execute Task logic based on tasktype."""
        idwf = token.idwf
        case_id = token.case_id
        resource_id = token.resource_id

        # --- Loop-type guard (PHP L16-30) ----------------------------------- #
        props = shape.get("properties") or {}
        looptype = getattr(props.get("looptype"), "value", None) or (
            props.get("looptype") if isinstance(props.get("looptype"), str) else ""
        )
        if looptype not in ("Standard", "None"):
            # Ensure task_run tracking exists on the service for this case.
            if not hasattr(service, "task_run"):
                service.task_run = set()  # type: ignore[attr-defined]
            if resource_id in service.task_run:  # type: ignore[attr-defined]
                return False  # already executed once this invocation
            service.task_run.add(resource_id)  # type: ignore[attr-defined]

        # --- Callacitivity substitution (PHP L54-80) ------------------------ #
        # If this shape is a call activity, swap it for its concrete implementation
        # shape matching the same name + tasktype. Preserves original resourceId so
        # the token's resource_id still resolves correctly against the model tree.
        if props.get("callacitivity"):
            callable_name = (props.get("callableelement") or "") or str(
                props.get("name", "")
            )
            task_type_str = str(props.get("tasktype", "") or "")
            candidates = await service.get_shapes_by_property(
                idwf, name=callable_name, tasktype=task_type_str
            )
            for candidate in candidates:
                cand_props = candidate.get("properties") or {}
                if not cand_props.get("callacitivity"):
                    # Swap outgoing / stencil / resources from the concrete shape; keep our resourceId.
                    shape["outgoing"] = candidate.get("outgoing", []) or []
                    shape["stencil"] = candidate.get("stencil", {}) or {}
                    if "resources" in candidate:
                        shape["resources"] = candidate["resources"]
                    break

        # --- Transport data from inbound shapes (PHP L83-95) ---------------- #
        inbound_shapes = await service.get_previous(resource_id, idwf)
        transport_data: dict[str, Any] = {}
        if inbound_shapes:
            for in_shape in inbound_shapes:
                in_rid = in_shape.get("resourceId") or in_shape.get("id", "")
                if not in_rid:
                    continue
                in_token = await service.get_token(idwf, case_id, in_rid)
                if in_token and getattr(in_token, "external_data", None):
                    ext = in_token.external_data
                    if isinstance(ext, dict):
                        transport_data.update(ext)
        # --- DataInputSet load (PHP L97-120) -------------------------------- #
        data: dict[str, Any] = {}
        data_input_set = props.get("datainputset") or {}
        items = (
            data_input_set.get("items", []) if isinstance(data_input_set, dict) else []
        )
        for item in items:
            name = getattr(item, "name", None) or (
                item.get("name") if isinstance(item, dict) else None
            )
            if not name:
                continue
            if "." in str(name):
                ds_source, ds_item = str(name).split(".", 1)
                # Look up data store from case data. For v1 compat we store
                # collected data on the token's external_data field; downstream
                # handlers can read it back via get_token(...).external_data.
                if ds_source not in data:
                    data[ds_source] = {}
                data[ds_source][ds_item] = transport_data.get(ds_item)

        # Persist collected data on the token (PHP L120: set_token with $data).
        merged_external = {
            **transport_data,
            **{k: v for d in [data] if isinstance(d, dict) for k, v in d.items()},
        }
        update_stmt = (
            sa.update(
                # Lazy import — Token model may not be imported at module load.
                __import__("app.models.token", fromlist=["Token"]).Token
            )
            .where(
                __import__("app.models.token", fromlist=["Token"]).Token.idwf == idwf,
                __import__("app.models.token", fromlist=["Token"]).Token.case_id
                == case_id,
                __import__("app.models.token", fromlist=["Token"]).Token.resource_id
                == resource_id,
            )
            .values(external_data=merged_external if merged_external else None)
        )
        await service.db.execute(update_stmt)  # type: ignore[misc]

        # --- Outgoing timer pre-creation (PHP L129-135) --------------------- #
        # Pre-create pending tokens on any outgoing IntermediateTimerEvent so the
        # engine can pick them up on the next /run invocation. Mirrors legacy
        # ``$CI->bpm->set_token(..., 'pending')`` on timer targets.
        for out_ref in shape.get("outgoing") or []:
            if not isinstance(out_ref, dict):
                continue
            out_rid = out_ref.get("resourceId") or out_ref.get("id", "")
            if not out_rid:
                continue
            # Skip if a token already exists (e.g., from movenext on an inbound shape).
            existing = await service.get_token(idwf, case_id, out_rid)
            if existing:
                continue
            out_shape = await service.get_shape(out_rid, idwf)
            if not out_shape:
                continue
            out_stencil = (out_shape.get("stencil") or {}).get("id", "")
            if out_stencil == "IntermediateTimerEvent":
                await service.create_token(
                    idwf=idwf,
                    case_id=case_id,
                    resource_id=out_rid,
                    type_=out_stencil,
                    status="pending",
                )

        tasktype = props.get("tasktype") or "Default"
        # Persist tasktype on the token for downstream queries (inbox, dashboard).
        from app.models.token import Token as TokenModel

        await service.db.execute(  # type: ignore[misc]
            sa.update(TokenModel)
            .where(
                TokenModel.idwf == idwf,
                TokenModel.case_id == case_id,
                TokenModel.resource_id == resource_id,
            )
            .values(tasktype=tasktype)
        )

        # --- Branch on tasktype (PHP L140-341) ------------------------------ #
        if tasktype in ("User", "Manual"):
            from app.models.case import BpmCase as CaseModel

            # --- Auto-assign when no explicit resources defined (legacy Bpm::assign() fallback) -- #
            # Legacy checks $shape->properties->resources->items; if absent, auto-assign to case initiator.
            shape_resources = shape.get("resources") or {}
            resource_items = (
                shape_resources.get("items", [])
                if isinstance(shape_resources, dict)
                else []
            )
            has_explicit_rules = any(
                item.get("resourceassignmentexpr")
                for item in resource_items  # type: ignore[union-attr]
                if isinstance(item, dict)
            )

            if not has_explicit_rules:
                # Look up case initiator — mirrors legacy $this->user->Initiator = (int)$case['iduser']
                fetch_initiator = sa.select(CaseModel.initiator_id).where(
                    CaseModel.idcase == case_id,
                    CaseModel.idwf == idwf,
                )
                init_result = await service.db.execute(fetch_initiator)  # type: ignore[misc]
                initiator_id = init_result.scalar_one_or_none()

                if initiator_id is not None:
                    # Auto-assign to initiator (legacy fallback when no rules apply)
                    current_assign = token.assign or []
                    if initiator_id not in current_assign:
                        current_assign.append(initiator_id)
                    assign_update = (
                        sa.update(TokenModel)
                        .where(
                            TokenModel.idwf == idwf,
                            TokenModel.case_id == case_id,
                            TokenModel.resource_id == resource_id,
                        )
                        .values(assign=current_assign, idu=initiator_id)
                    )
                    await service.db.execute(assign_update)  # type: ignore[misc]

            # Store shape title on token (mirrors legacy token.name field in MongoDB document)
            shape_title = props.get("name") or props.get("title") or ""
            if shape_title:
                assign_update2 = (
                    sa.update(TokenModel)
                    .where(
                        TokenModel.idwf == idwf,
                        TokenModel.case_id == case_id,
                        TokenModel.resource_id == resource_id,
                    )
                    .values(title=shape_title)
                )
                await service.db.execute(assign_update2)  # type: ignore[misc]

            # Mark token as 'user' status — stops engine loop, waits for manual POST.

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

        if tasktype == "Script":
            script_str = props.get("script", "")
            operationref = props.get("operationref") or props.get("name", "result")
            if script_str:
                # Fetch current case data so scripts can read it via `ds`.
                from app.models.case import BpmCase

                fetch_stmt = sa.select(BpmCase.data).where(
                    BpmCase.idcase == case_id,
                    BpmCase.idwf == idwf,
                )
                current_data = await service.db.execute(fetch_stmt)  # type: ignore[misc]
                current_data = current_data.scalar_one_or_none() or {}
                if not isinstance(current_data, dict):
                    current_data = {}

                # Build execution namespace with ds + identifiers.
                ns = build_script_namespace(token, current_data, transport_data)

                # Evaluate script; _eval_script returns raw value (not coerced to bool).
                result = _eval_script(script_str, ns)

                # Sync any mutations the script made via `ds` back into case data.
                ds_payload: dict[str, Any] = {}
                ds_obj = ns.get("ds")
                if isinstance(ds_obj, DataStorage):
                    ds_payload = ds_obj._data
                new_data = {**current_data, operationref: result, **ds_payload}
                update_stmt = (
                    sa.update(BpmCase)
                    .where(
                        BpmCase.idcase == case_id,
                        BpmCase.idwf == idwf,
                    )
                    .values(data=new_data)
                )
                await service.db.execute(update_stmt)  # type: ignore[misc]
            await service.movenext(resource_id, idwf, case_id)
            return False

        if tasktype == "Send":
            # TODO (Phase X): implement inbox message dispatch. For v1 compat
            # just advance via movenext.
            await service.movenext(resource_id, idwf, case_id)
            return False

        # Default / Receive / any other → just move next.
        await service.movenext(resource_id, idwf, case_id)
        return False


# Auto-register at import time via the registry pattern.
ENGINE_HANDLER_REGISTRY.register(TaskHandler._STENCIL_ID, TaskHandler)
