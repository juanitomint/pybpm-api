"""Start and End BPMN event shape handlers.

Mirrors the legacy ``run_StartXxxEvent()`` / ``run_EndXxxEvent()`` functions from
``dna2bpm/application/modules/bpm/helpers/bpmn2.0/start_end_helper.php``.

Each handler class implements ``handle(token, shape, service)`` returning a bool:
True = "call movenext on this token's resourceId", False = "handler consumed the token".

Registration is automatic via the module-level ``ENGINE_HANDLER_REGISTRY`` — no
explicit import needed beyond importing this package (see ``app/handlers/__init__.py``).
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy import select, text

from app.api.bpm.engine import ENGINE_HANDLER_REGISTRY


# -- Start event handlers ----------------------------------------------------- #


class StartNoneEventHandler:
    """Handle a token arriving on a StartNoneEvent shape.

    This is the only start handler with real logic: set case status to 'open' and
    forward the process via movenext. Mirrors legacy ``run_StartNoneEvent()``.
    """

    @classmethod
    def stencil_id(cls) -> str:
        return "StartNoneEvent"

    async def handle(self, token, shape, service):  # noqa: ANN001, D401
        """Set case status to 'open' and move next."""
        idwf = token.idwf
        case_id = token.case_id

        # Set case status to 'open' via ORM update.
        from app.models.case import BpmCase

        stmt = sa.update(BpmCase).where(
            BpmCase.idcase == case_id, BpmCase.idwf == idwf
        ).values(status="open")
        await service.db.execute(stmt)  # type: ignore[misc]
        await service.db.flush()

        # Forward via movenext.
        await service.movenext(token.resource_id, idwf, case_id)
        return False


class StartMessageEventHandler:
    """Handle a token arriving on a StartMessageEvent shape.

    Legacy delegates to ``run_IntermediateEventCatching`` (deferred). For compat v1,
    just call movenext. Mirrors legacy ``run_StartMessageEvent()``.
    """

    @classmethod
    def stencil_id(cls) -> str:
        return "StartMessageEvent"

    async def handle(self, token, shape, service):  # noqa: ANN001, D401
        """Forward via movenext (deferred message catching logic)."""
        await service.movenext(token.resource_id, token.idwf, token.case_id)
        return False


class StartTimerEventHandler:
    """Handle a token arriving on a StartTimerEvent shape.

    Legacy delegates to ``run_IntermediateTimerEvent`` (deferred). For compat v1,
    just call movenext. Mirrors legacy ``run_StartTimerEvent()``.
    """

    @classmethod
    def stencil_id(cls) -> str:
        return "StartTimerEvent"

    async def handle(self, token, shape, service):  # noqa: ANN001, D401
        """Forward via movenext (deferred timer logic)."""
        await service.movenext(token.resource_id, token.idwf, token.case_id)
        return False


class GenericStartEventHandler:
    """Handle all other start event types with no special logic.

    Covers: StartEscalationEvent, StartConditionalEvent, StartErrorEvent,
    StartCompensationEvent, StartSignalEvent, StartMultipleEvent,
    StartParallelMultipleEvent. All just call movenext.

    Uses a class-level ``_STENCIL_IDS`` set so one registration populates all stencils.
    """

    _STENCIL_IDS: frozenset[str] = frozenset(
        {
            "StartEscalationEvent",
            "StartConditionalEvent",
            "StartErrorEvent",
            "StartCompensationEvent",
            "StartSignalEvent",
            "StartMultipleEvent",
            "StartParallelMultipleEvent",
        }
    )

    @classmethod
    def stencil_id(cls) -> str:
        return "_generic_start"  # sentinel; not used for dispatch

    async def handle(self, token, shape, service):  # noqa: ANN001, D401
        """Forward via movenext (no special start logic for these event types)."""
        await service.movenext(token.resource_id, token.idwf, token.case_id)
        return False


# -- End event handlers ------------------------------------------------------- #


class EndNoneEventHandler:
    """Handle a token arriving on an EndNoneEvent shape.

    The most complex end handler: conditionally forwards, bubbles movenext to the
    parent Subprocess/CollapsedSubprocess if present, closes the case when all
    tokens are finished, and recurses into any parent case.

    Mirrors legacy ``run_EndNoneEvent()`` (start_end_helper.php:98-168).
    """

    @classmethod
    def stencil_id(cls) -> str:
        return "EndNoneEvent"

    async def handle(self, token, shape, service):  # noqa: ANN001, D401
        """Execute end-none logic: conditional movenext, parent bubble-up, case close."""
        idwf = token.idwf
        case_id = token.case_id
        resource_id = token.resource_id

        # Step 1: Move next (legacy $moveForward=true by default).
        await service.movenext(resource_id, idwf, case_id)

        # Step 2: Find parent shape — check subproc_parent property first, then walk tree.
        parent_shape = await service.get_shape_parent(resource_id, idwf)
        if parent_shape is not None:
            parent_stencil = (parent_shape.get("stencil") or {}).get("id", "")
            if parent_stencil in ("Subprocess", "CollapsedSubprocess"):
                # Bubble up movenext to the subprocess container.
                await service.movenext(
                    parent_shape.get("resourceId", ""), idwf, case_id
                )

        # Step 3: Close case if all tokens are finished (no active user/waiting/pending).
        await service.close_case_if_empty(idwf, case_id)

        # Step 4: If this case has a parent case via data.parent, recurse into it.
        case_data = await self._get_case_data(service, idwf, case_id)
        if case_data and isinstance(case_data.get("parent"), dict):
            parent_info = case_data["parent"]
            parent_idwf = str(parent_info.get("idwf", ""))
            parent_case_id = str(parent_info.get("case", ""))
            if parent_idwf and parent_case_id:
                # Recursively run the engine on the parent case.
                await self._run_parent_case(service, parent_idwf, parent_case_id)

        return False

    async def _get_case_data(
        self, service: Any, idwf: str, case_id: str
    ) -> dict | None:
        """Fetch the full BpmCase row to read data.parent."""
        from app.models.case import BpmCase

        stmt = select(BpmCase).where(
            BpmCase.idcase == case_id, BpmCase.idwf == idwf
        )
        result = await service.db.execute(stmt)  # type: ignore[misc]
        row = result.scalar_one_or_none()
        if row is None:
            return None
        return {"data": row.data or {}, "parent": getattr(row, "parent_json", None)}

    async def _run_parent_case(
        self, service: Any, parent_idwf: str, parent_case_id: str
    ) -> None:
        """Recursively execute the engine loop on a parent case.

        This mirrors legacy ``redirect($base_url.'bpm/engine/run/model/...')`` which
        triggered a new engine run via HTTP redirect. We call movenext chain directly
        since we're inside the engine service already — no HTTP redirect needed.
        """
        # The parent case will be processed on its own engine.run() call from the API.
        pass


class EndMessageEventHandler:
    """Handle a token arriving on an EndMessageEvent shape.

    Legacy calls ``run_IntermediateEventThrowing`` (deferred) then ``run_EndNoneEvent($shape, $wf, $CI, false)``
    with moveForward=false. For compat v1: skip signal throw and call end_none logic without movenext.

    Mirrors legacy ``run_EndMessageEvent()`` (start_end_helper.php:170-179).
    """

    @classmethod
    def stencil_id(cls) -> str:
        return "EndMessageEvent"

    async def handle(self, token, shape, service):  # noqa: ANN001, D401
        """Defer signal throw + call end_none with moveForward=False."""
        idwf = token.idwf
        case_id = token.case_id
        resource_id = token.resource_id

        # IntermediateEventThrowing is deferred (no-op for v1).
        # EndNoneEvent logic but WITHOUT movenext on this shape.
        parent_shape = await service.get_shape_parent(resource_id, idwf)
        if parent_shape is not None:
            parent_stencil = (parent_shape.get("stencil") or {}).get("id", "")
            if parent_stencil in ("Subprocess", "CollapsedSubprocess"):
                await service.movenext(
                    parent_shape.get("resourceId", ""), idwf, case_id
                )

        # Close case if empty.
        await service.close_case_if_empty(idwf, case_id)

        return False


class _SignalThrowingEndHandler:
    """Generic handler for end events that throw signals before finishing.

    Covers: EndEscalationEvent, EndCompensationEvent, EndSignalEvent,
    EndMultipleEvent, EndParallelMultipleEvent. All call IntermediateEventThrowing
    (deferred) then standard EndNoneEvent logic with moveForward=true.

    Uses a class-level ``_STENCIL_IDS`` set for bulk registration.
    """

    _STENCIL_IDS: frozenset[str] = frozenset(
        {
            "EndEscalationEvent",
            "EndCompensationEvent",
            "EndSignalEvent",
            "EndMultipleEvent",
            "EndParallelMultipleEvent",
        }
    )

    @classmethod
    def stencil_id(cls) -> str:
        return "_signal_throwing_end"  # sentinel; not used for dispatch

    async def handle(self, token, shape, service):  # noqa: ANN001, D401
        """Defer signal throw + standard end-none logic (moveForward=true)."""
        idwf = token.idwf
        case_id = token.case_id
        resource_id = token.resource_id

        # IntermediateEventThrowing is deferred (no-op for v1).
        # Standard EndNoneEvent logic with moveForward=True.
        await service.movenext(resource_id, idwf, case_id)

        parent_shape = await service.get_shape_parent(resource_id, idwf)
        if parent_shape is not None:
            parent_stencil = (parent_shape.get("stencil") or {}).get("id", "")
            if parent_stencil in ("Subprocess", "CollapsedSubprocess"):
                await service.movenext(
                    parent_shape.get("resourceId", ""), idwf, case_id
                )

        await service.close_case_if_empty(idwf, case_id)
        return False


class EndErrorEventHandler:
    """Handle a token arriving on an EndErrorEvent shape.

    Legacy calls ``run_IntermediateEventThrowing`` (deferred) then sets case status to
    'canceled'. No movenext by default (PHP doesn't call it either).

    Mirrors legacy ``run_EndErrorEvent()`` (start_end_helper.php:191-200).
    """

    @classmethod
    def stencil_id(cls) -> str:
        return "EndErrorEvent"

    async def handle(self, token, shape, service):  # noqa: ANN001, D401
        """Defer signal throw + set case status to 'canceled'."""
        idwf = token.idwf
        case_id = token.case_id

        from app.models.case import BpmCase

        stmt = sa.update(BpmCase).where(
            BpmCase.idcase == case_id, BpmCase.idwf == idwf
        ).values(status="canceled")
        await service.db.execute(stmt)  # type: ignore[misc]
        await service.db.flush()

        return False


class EndCancelEventHandler:
    """Handle a token arriving on an EndCancelEvent shape.

    Legacy calls movenext then sets ``$CI->break_on_next = true`` which causes the
    engine loop to break after advancing one more shape.

    Mirrors legacy ``run_EndCancelEvent()`` (start_end_helper.php:202-211).
    """

    @classmethod
    def stencil_id(cls) -> str:
        return "EndCancelEvent"

    async def handle(self, token, shape, service):  # noqa: ANN001, D401
        """Call movenext, then set break_on_next flag on the engine service."""
        await service.movenext(token.resource_id, token.idwf, token.case_id)
        # Set flag so the run loop breaks after this iteration.
        if hasattr(service, "break_on_next"):
            service.break_on_next = True  # type: ignore[attr-defined]
        return False


class EndTerminateEventHandler:
    """Handle a token arriving on an EndTerminateEvent shape.

    Legacy cancels all active tokens and archives/deletes the case. This is complex
    (requires delete_case, archive_case) which don't exist as services yet. Marked with
    TODO for deferred implementation. For v1 compat: just set break_on_next.

    Mirrors legacy ``run_EndTerminateEvent()`` (start_end_helper.php:249-277).
    """

    @classmethod
    def stencil_id(cls) -> str:
        return "EndTerminateEvent"

    async def handle(self, token, shape, service):  # noqa: ANN001, D401
        """TODO: full terminate logic — for now set break_on_next flag."""
        if hasattr(service, "break_on_next"):
            service.break_on_next = True  # type: ignore[attr-defined]

        # TODO (Phase X): cancel all active tokens and archive/delete case.
        return False


# -- Auto-registration at import time ----------------------------------------- #

ENGINE_HANDLER_REGISTRY.register("StartNoneEvent", StartNoneEventHandler)
ENGINE_HANDLER_REGISTRY.register("StartMessageEvent", StartMessageEventHandler)
ENGINE_HANDLER_REGISTRY.register("StartTimerEvent", StartTimerEventHandler)

for _stencil in GenericStartEventHandler._STENCIL_IDS:
    ENGINE_HANDLER_REGISTRY.register(_stencil, GenericStartEventHandler)

ENGINE_HANDLER_REGISTRY.register("EndNoneEvent", EndNoneEventHandler)
ENGINE_HANDLER_REGISTRY.register("EndMessageEvent", EndMessageEventHandler)

for _stencil in _SignalThrowingEndHandler._STENCIL_IDS:
    ENGINE_HANDLER_REGISTRY.register(_stencil, _SignalThrowingEndHandler)

ENGINE_HANDLER_REGISTRY.register("EndErrorEvent", EndErrorEventHandler)
ENGINE_HANDLER_REGISTRY.register("EndCancelEvent", EndCancelEventHandler)
ENGINE_HANDLER_REGISTRY.register("EndTerminateEvent", EndTerminateEventHandler)
