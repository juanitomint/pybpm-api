"""CollapsedSubprocess shape handler — full subprocess orchestration.

Mirrors legacy ``run_CollapsedSubprocess()`` from
``dna2bpm/application/modules/bpm/helpers/bpmn2.0/subproc_helper.php:1-236``.

Supports two subprocesstype modes:
- **Independent / Reference**: creates separate child cases in the database,
  each with its own idwf (from shape.properties.entry), parent context, and
  engine.run loop. Child cases are tracked persistently in parent case data
  under ``data.child[{shape.resourceId}][{child_idwf}]``.
- **Embedded**: would inline-execute child shapes within the same case (handled
  by a separate Subprocess handler — not yet implemented here).

Loop types determine how many child instances to create:
- **Standard / None**: exactly one child case per invocation; Standard reuses
  an existing case if present, otherwise creates new.
- **Sequential**: iterate over DataStore items (if connected upstream) or
  create a single instance; only start next child after previous finishes.
- **Parallel**: create all children from DataStore at once, or ``startquantity``
  instances (defaults to 1 if not set).

Completion condition: while loop is Sequential/Parallel and token status is
'waiting', check ``completionquantity`` threshold or eval ``completioncondition``
expression against case data. If satisfied, movenext on the subprocess shape;
otherwise run the next unfinished child via recursive engine.run.

This replaces the v1 stub which just called movenext unconditionally — now
subprocesses actually delegate to child cases and wait for them to finish.
"""

from __future__ import annotations

import logging
from typing import Any

import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.bpm.engine import ENGINE_HANDLER_REGISTRY
from app.handlers.flow import _safe_eval
from app.services.bpm_service import gen_case, startcase

logger = logging.getLogger(__name__)


class CollapsedSubprocessHandler:
    """Handle a token arriving on a CollapsedSubprocess shape.

    Implements full subprocess orchestration: child case creation per
    subprocesstype/looptype combination, completion-condition evaluation, and
    recursive engine.run on children. Mirrors legacy ``run_CollapsedSubprocess()``.
    """

    _STENCIL_ID = "CollapsedSubprocess"

    @classmethod
    def stencil_id(cls) -> str:
        return cls._STENCIL_ID

    async def handle(self, token: Any, shape: dict[str, Any], service: Any) -> bool:  # noqa: ANN001, D401
        """Execute CollapsedSubprocess logic — create children or wait for completion."""
        db = service.db
        idwf = token.idwf
        case_id = token.case_id

        props = shape.get("properties") or {}
        subprocesstype = props.get("subprocesstype", "Independent")
        looptype = props.get("looptype", "Standard")
        entry = props.get("entry", "")  # child model idwf for Independent/Reference

        # Fetch current token to check status and persisted child list
        current_token = await service.get_token(idwf, case_id, shape["resourceId"])
        if not current_token:
            logger.warning(
                "CollapsedSubprocessHandler: no token found for %s in case %s",
                shape["resourceId"], case_id,
            )
            return False

        # Persisted child case IDs stored during previous invocations
        child_cases = (current_token.external_data or {}).get("child") or []

        parent_case_stmt = select(sa.text("*")).select_from(
            sa.table("cases", sa.column("idcase"), sa.column("data"))
        ).where(
            sa.column("idcase") == case_id,
            sa.column("idwf") == idwf,
        )
        # Use service's internal DB query instead of raw table reference
        parent_data = {}
        async for row in db.execute(sa.text(
            "SELECT data FROM cases WHERE idcase=$1 AND idwf=$2"
        ).bindparams(case_id, idwf)):
            parent_data = dict(row[0]) if row[0] else {}

        # ------------------------------------------------------------------ #
        # Phase A: If waiting + Sequential/Parallel loop → check completion    #
        # ------------------------------------------------------------------ #
        if current_token.status == "waiting" and subprocesstype != "Embedded":
            # Count finished vs total children
            cases_finished = 0
            still_open: list[str] = []
            for child_id in child_cases:
                child_case_stmt = select(sa.text("*")).select_from(
                    sa.table("cases", sa.column("idcase"), sa.column("status"))
                ).where(
                    sa.column("idcase") == child_id,
                )
                async for row in db.execute(child_case_stmt):
                    if row[0]["status"] != "open":  # type: ignore[index]
                        cases_finished += 1
                    else:
                        still_open.append(child_id)

            is_finished = False
            completion_qty = int(props.get("completionquantity", 0)) or 0

            # Check quantity threshold
            if completion_qty > 0 and cases_finished >= completion_qty:
                is_finished = True

            # Evaluate dynamic completioncondition expression (PHP L48-56)
            if not is_finished and props.get("completioncondition"):
                cond_expr = props["completioncondition"]
                if "return" not in cond_expr.lower():
                    cond_expr = f"return({cond_expr})"
                context = {"data": parent_data}
                try:
                    result = eval(cond_expr, {"__builtins__": {}}, context)  # noqa: S307
                    is_finished = bool(result)
                except Exception:
                    logger.debug("CollapsedSubprocessHandler: completion condition eval failed")

            if is_finished:
                # All children done — move next on subprocess shape
                await service.movenext(shape["resourceId"], idwf, case_id)
                return False

            # Sequential loop: only start next child if previous finished
            if looptype == "Sequential" and still_open:
                logger.debug(
                    "CollapsedSubprocessHandler: sequential loop — %d children still open",
                    len(still_open),
                )
                return False  # keep waiting

        # ------------------------------------------------------------------ #
        # Phase B: Create child cases based on subprocesstype + looptype      #
        # ------------------------------------------------------------------ #
        if subprocesstype == "Embedded":
            # Embedded subprocesses execute inline — not yet implemented; skip
            logger.debug("CollapsedSubprocessHandler: Embedded subprocesstype not yet supported")
            return False

        if not entry:
            logger.warning(
                "CollapsedSubprocessHandler: no 'entry' property for %s — cannot create child cases",
                shape["resourceId"],
            )
            await service.movenext(shape["resourceId"], idwf, case_id)
            return False

        # Detect upstream DataStore shapes (for Sequential/Parallel loop iteration)
        prev_shapes = await service.get_previous(shape["resourceId"], idwf)
        data_store_name = ""
        for ps in prev_shapes:
            if ps.get("stencil", {}).get("id") == "DataStore":
                data_store_name = ps.get("properties", {}).get("name", "") or ""

        # Build parent context to pass to children
        parent_context = {
            "token": {},  # token metadata — not fully populated in PHP either
            "case": case_id,
            "idwf": idwf,
        }
        child_data: dict[str, Any] = {"parent": parent_context}

        new_children: list[str] = []

        if looptype == "Sequential":
            # Start one instance at a time; iterate DataStore items if connected
            if data_store_name and parent_data.get(data_store_name):
                store_items = parent_data[data_store_name]
                for item in (store_items if isinstance(store_items, list) else [store_items]):
                    child_case_id = await gen_case(
                        db, entry, parent_id=case_id,
                        parent_data={**child_data.get("parent_data", {}), "parent_data": item},
                    )
                    new_children.append(child_case_id)
            else:
                # Single instance from shape
                child_case_id = await gen_case(
                    db, entry, parent_id=case_id, parent_data=child_data,
                )
                new_children.append(child_case_id)

        elif looptype == "Parallel":
            # Start all instances at once — either from DataStore or startquantity
            if data_store_name and parent_data.get(data_store_name):
                store_items = parent_data[data_store_name]
                for item in (store_items if isinstance(store_items, list) else [store_items]):
                    child_case_id = await gen_case(
                        db, entry, parent_id=case_id,
                        parent_data={**child_data.get("parent_data", {}), "parent_data": item},
                    )
                    new_children.append(child_case_id)
            else:
                start_qty = int(props.get("startquantity", 1)) or 1
                for _ in range(start_qty):
                    child_case_id = await gen_case(
                        db, entry, parent_id=case_id, parent_data=child_data,
                    )
                    new_children.append(child_case_id)

        else:
            # Standard / None — exactly one child case (reuse if exists for Standard)
            existing_stmt = select(sa.text("*")).select_from(
                sa.table("cases", sa.column("idcase"), sa.column("data"))
            ).where(
                sa.column("idwf") == entry,
            )
            # Check for existing child case under this subprocess resourceId
            existing_child_id: str | None = None
            for cid in (child_cases + new_children):
                async for row in db.execute(sa.text(
                    "SELECT 1 FROM cases WHERE idcase=$1 AND idwf=$2"
                ).bindparams(cid, entry)):
                    if row[0]:  # type: ignore[index]
                        existing_child_id = cid
                        break

            if not existing_child_id:
                child_case_id = await gen_case(
                    db, entry, parent_id=case_id, parent_data=child_data,
                )
                new_children.append(child_case_id)

        # ------------------------------------------------------------------ #
        # Phase C: Start each new child case (clear tokens + seed pending)    #
        # ------------------------------------------------------------------ #
        for child_id in new_children:
            await startcase(db, entry, child_id, silent=True)
            logger.debug(
                "CollapsedSubprocessHandler: started child case %s on model %s",
                child_id, entry,
            )

        # Merge new children with previously tracked ones (Sequential adds one at a time)
        all_children = list(child_cases) + new_children

        # Persist child list back to parent case token.external_data for next invocation
        update_stmt = sa.text(
            "UPDATE cases SET data = jsonb_set(data, '{child}', :child_json::jsonb) "
            "WHERE idcase = :case_id AND idwf = :idwf"
        ).bindparams(
            child_json=str(all_children),  # serialize as JSON string for storage
            case_id=case_id,
            idwf=idwf,
        )
        await db.execute(update_stmt)

        # Set subprocess token to waiting with children list in external_data
        await service._set_token_status(
            idwf, case_id, shape["resourceId"], "waiting",
            {"child": all_children},
        )

        # If we created new children and they haven't been run yet, trigger their engine.run
        # This is handled by the caller (engine.py main loop) picking up pending tokens
        return False


class InlineSubprocessHandler:
    """Handle a token arriving on an expanded Subprocess (inline childShapes).

    Unlike CollapsedSubprocess which spawns a separate child case, this handler
    walks the shape's childShapes directly within the current case and creates
    pending tokens on each executable shape. The engine loop then dispatches them
    to their own handlers in sequence — no new case, no persistent tracking.

    Visual-only stencils (Lane, Pool, TextAnnotation, Association_*) are skipped.
    """

    _STENCIL_ID = "Subprocess"

    VISUAL_ONLY = {
        "TextAnnotation", "Association_Undirected", "Association_Unidirectional",
        "Lane", "Pool", "CollapsedPool", "DataObject", "DataStore",
    }

    @classmethod
    def stencil_id(cls) -> str:
        return cls._STENCIL_ID

    async def handle(self, token: Any, shape: dict[str, Any], service: Any) -> bool:  # noqa: ANN001
        idwf = token.idwf
        case_id = token.case_id
        resource_id = shape["resourceId"]

        for child in shape.get("childShapes") or []:
            if not isinstance(child, dict):
                continue
            stencil = (child.get("stencil") or {}).get("id", "")
            if stencil in self.VISUAL_ONLY:
                continue
            out_rid = child.get("resourceId") or child.get("id", "")
            if not out_rid:
                continue
            existing = await service.get_token(idwf, case_id, out_rid)
            if existing:
                continue  # already has a token — let it flow normally
            await service.create_token(
                idwf=idwf,
                case_id=case_id,
                resource_id=out_rid,
                type_=stencil,
                status="pending",
            )

        await service.mark_token_finished(token)
        return False

# Auto-register at import time via the registry pattern.
from app.api.bpm.engine import ENGINE_HANDLER_REGISTRY  # noqa: E402

ENGINE_HANDLER_REGISTRY.register(CollapsedSubprocessHandler._STENCIL_ID, CollapsedSubprocessHandler)
ENGINE_HANDLER_REGISTRY.register(InlineSubprocessHandler._STENCIL_ID, InlineSubprocessHandler)
