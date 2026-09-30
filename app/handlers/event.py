"""Intermediate event handlers — throwing and catching semantics from legacy PHP.

Mirrors `dna2bpm/application/modules/bpm/helpers/bpmn2.0/event_helper.php`.

Core architecture:
- ``run_IntermediateEventThrowing()`` — finds all matching catchers (by name,
  messageref, eventdefinitionref) and launches them via ``movenext()`` on the
  catcher shape.
- ``run_IntermediateEventCatching()`` — generic catching logic that handles:
  - Normal flow: waits for all inbound sequence flows to finish before advancing
  - Boundary events: cancels parent activity when boundary triggers, or self-cancels if parent finished first
  - Synchronization: Parallel Multiple Event catches must wait for ALL throwers
- ``run_IntermediateTimerEvent()`` — parses trigger timestamp, sets status='waiting' with trigger data, then on next iteration checks if time has elapsed.

Individual event stencils (Message, Signal, Error, Link, etc.) all route through these two generic functions. The timer event is special because it needs time-based waiting logic.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime, timedelta
from typing import Any

from app.api.bpm.engine import ENGINE_HANDLER_REGISTRY

logger = logging.getLogger(__name__)

# -- Generic Throwing Logic --------------------------------------------------- #


async def run_intermediate_event_throwing(
    shape: dict[str, Any],
    idwf: str,
    case_id: str,
    service: Any,
) -> None:
    """Find all matching catchers and launch them.

    Search strategy (mirrors legacy PHP):
    1. Build trigger name from stencil ID (e.g., 'IntermediateMessageEventThrowing' → 'IntermediateMessageEventCatching')
    2. Find shapes by same stencil type + matching name/trigger
    3. Find shapes by messageref property match
    4. Merge all found catchers, exclude self

    Then for each catcher: if no token exists (or status not canceled/finished), launch it via movenext on the catcher shape.

    Mirrors legacy ``run_IntermediateEventThrowing()``.
    """
    stencil_id = shape.get("stencil", {}).get("id", "")
    props = shape.get("properties") or {}
    name = props.get("name", "")
    event_definition_ref = props.get("eventdefinitionref", "")

    # Determine trigger/catcher stencil names.
    if "Throwing" in stencil_id:
        catcher_stencil = stencil_id.replace("Throwing", "Catching")
    elif stencil_id.startswith("End"):
        catcher_stencil = stencil_id.replace("End", "Start")
    else:
        catcher_stencil = None

    # Determine trigger value.
    trigger = event_definition_ref or (name or "")

    # Build search query: shapes with matching stencil ID and trigger/name match.
    catchers_by_trigger: list[dict] = []
    catchers_by_ref: list[dict] = []

    if catcher_stencil:
        # Search for shapes by name/trigger.
        result = await service.get_shapes_by_property(
            stencil_id=catcher_stencil, name=trigger
        )
        catchers_by_trigger = [
            s for s in result if s.get("resourceId") != shape.get("resourceId")
        ]

    # Search by messageref (only when we have a valid catcher stencil).
    if catcher_stencil:
        result = await service.get_shapes_by_property(
            stencil_id=catcher_stencil, eventdefinitionref=name
        )
        catchers_by_ref = [
            s for s in result if s.get("resourceId") != shape.get("resourceId")
        ]

    # Merge all catchers, deduplicating by resourceId.
    seen_rids: set[str] = set()
    all_catchers: list[dict] = []
    for catcher in catchers_by_trigger + catchers_by_ref:
        rid = catcher.get("resourceId")
        if rid and rid not in seen_rids:
            seen_rids.add(rid)
            all_catchers.append(catcher)

    # Advance this throwing shape.
    await service.movenext(shape["resourceId"], idwf, case_id)

    # Launch each catcher (create pending token and dispatch).
    for catcher in all_catchers:
        catcher_rid = catcher.get("resourceId") or ""
        if not catcher_rid:
            continue

        # Check if token already exists (gateway handler may have created it).
        existing_token = await service.get_token(idwf, case_id, catcher_rid)
        if existing_token:
            if getattr(existing_token, "status", None) in ("canceled", "finished"):
                continue  # Skip canceled or finished catchers.
            # Token exists with status 'pending'/'waiting' — gateway already
            # created it. Still dispatch to process it.
        else:
            # Create pending token on catcher and dispatch.
            stencil = (catcher.get("stencil") or {}).get("id", "")
            await service.create_token(
                idwf=idwf,
                case_id=case_id,
                resource_id=catcher_rid,
                type_=stencil,
                status="pending",
            )

        # Dispatch to catcher handler (will call movenext on next iteration).
        await _dispatch_catcher(catcher, idwf, case_id, service)


async def _dispatch_catcher(
    shape: dict[str, Any],
    idwf: str,
    case_id: str,
    service: Any,
) -> None:
    """Dispatch a catcher token to the appropriate handler.

    For most events this just calls movenext (which creates tokens on outgoing flows).
    For Timer events, it triggers time-based waiting logic.
    """
    stencil_id = shape.get("stencil", {}).get("id", "")
    if "Timer" in stencil_id:
        await run_intermediate_timer_event(shape, idwf, case_id, service)
    else:
        await run_intermediate_event_catching(shape, idwf, case_id, service)


# -- Generic Catching Logic --------------------------------------------------- #
async def run_intermediate_event_catching(
    shape: dict[str, Any],
    idwf: str,
    case_id: str,
    service: Any,
) -> None:
    """Generic catching logic with boundary/normal flow handling.

    Search for matching throwers (by name or messageref), then check if all inbound flows AND all throwers are finished before advancing.

    Boundary events have special semantics:
    - If parent activity is NOT finished and boundary is interrupting → cancel parent, advance to next
    - If parent activity IS finished → cancel this catching token (parent already done)

    Normal flow just waits for synchronization like ParallelGateway.

    Mirrors legacy ``run_IntermediateEventCatching()``.
    """
    props = shape.get("properties") or {}
    name = props.get("name", "")
    stencil_id = shape.get("stencil", {}).get("id", "")
    is_interrupting = bool(props.get("isinterrupting"))

    # Determine thrower stencil names (reverse of throwing).
    if "Catching" in stencil_id:
        thrower_stencil = stencil_id.replace("Catching", "Throwing")
    elif stencil_id.startswith("Start"):
        thrower_stencil = stencil_id.replace("Start", "End")
    else:
        thrower_stencil = None

    # Find inbound flows.
    inbound_shapes = await service.get_previous(shape["resourceId"], idwf)

    # Determine if this is a boundary event or normal flow.
    is_boundary_event = False
    is_normal_flow = True
    if len(inbound_shapes) == 1:
        in_shape = inbound_shapes[0]
        in_stencil = (in_shape.get("stencil") or {}).get("id", "")
        if in_stencil in ("Task", "Subprocess"):
            is_boundary_event = True
            is_normal_flow = False
    elif len(inbound_shapes) == 0:
        # No inbound — assume normal flow.
        pass

    has_finished_thrower = False
    throwers = []
    if thrower_stencil and name:
        result = await service.get_shapes_by_property(
            stencil_id=thrower_stencil, name=name
        )
        throwers = [s for s in result if s.get("resourceId") != shape.get("resourceId")]

    # Check all throwers are finished.
    if throwers:
        has_finished_thrower = all(
            [
                await service._check_token_finished(idwf, case_id, t["resourceId"])
                for t in throwers
            ]
        )

    # Handle boundary events specially.
    if is_boundary_event and inbound_shapes:
        in_shape = inbound_shapes[0]
        in_rid = in_shape.get("resourceId") or ""
        in_token = await service.get_token(idwf, case_id, in_rid)

        if not in_token or getattr(in_token, "status", None) != "finished":
            # Parent activity NOT finished.
            if is_interrupting:
                # Cancel parent and advance to next.
                data = {
                    "canceledBy": shape["resourceId"],
                    "canceledName": name,
                }
                await service._set_token_status(
                    idwf, case_id, in_rid, "canceled", data=data
                )
                # Cancel any child tokens if parent is a subprocess.
                if (in_shape.get("stencil") or {}).get("id") == "Subprocess":
                    await service._cancel_subprocess_children(in_rid, idwf, case_id)
                await service.movenext(shape["resourceId"], idwf, case_id)
                return
        else:
            # Parent activity IS finished — cancel this catching token.
            data = {
                "canceledBy": in_rid,
                "canceledName": (in_shape.get("properties") or {}).get("name", ""),
            }
            await service._set_token_status(
                idwf, case_id, shape["resourceId"], "canceled", data=data
            )
            return

    # For normal flow: check all inbound flows are finished.
    if is_normal_flow and inbound_shapes:
        has_finished_flow = all(
            [
                await service._check_token_finished(idwf, case_id, s["resourceId"])
                for s in inbound_shapes
                if (s.get("stencil") or {}).get("id") in ("SequenceFlow", "MessageFlow")
            ]
        )
    else:
        has_finished_flow = True

    # If throwers were found and all are finished, consider flows as finished too.
    # This handles the case where the catcher is directly dispatched by a thrower
    # (e.g., IntermediateMessageEventThrowing) but the inbound sequence flow
    # token is still "pending" because it was just created by movenext().
    if throwers and has_finished_thrower:
        has_finished_flow = True

    # Merge conditions.
    has_finished = has_finished_flow and has_finished_thrower
    if not is_interrupting:
        has_finished = has_finished or True  # Non-interrupting always advances.

    if has_finished:
        await service.movenext(shape["resourceId"], idwf, case_id)
        # Check if previous shape is an EventbasedGateway — if so, wake it up.
        # Mirrors legacy event_helper.php L346-354.
        # The previous shape may be a SequenceFlow; traverse through it to find
        # the EventbasedGateway that triggered this flow.
        previous_shapes = await service.get_previous(shape["resourceId"], idwf)
        if previous_shapes:
            previous = previous_shapes[0]
            prev_stencil = (previous.get("stencil") or {}).get("id", "")
            if prev_stencil == "EventbasedGateway":
                await service._set_token_status(
                    idwf, case_id, previous["resourceId"], "pending"
                )
            elif prev_stencil == "SequenceFlow":
                # Traverse through the flow to find the EventbasedGateway.
                flow_prev_shapes = await service.get_previous(previous["resourceId"], idwf)
                if flow_prev_shapes:
                    flow_prev = flow_prev_shapes[0]
                    flow_prev_stencil = (flow_prev.get("stencil") or {}).get("id", "")
                    if flow_prev_stencil == "EventbasedGateway":
                        await service._set_token_status(
                            idwf, case_id, flow_prev["resourceId"], "pending"
                        )
    else:
        # Not finished yet — keep waiting.
        data = {"name": name}
        await service._set_token_status(
            idwf, case_id, shape["resourceId"], "waiting", data=data
        )


# -- Timer Event Special Handler --------------------------------------------- #


async def run_intermediate_timer_event(
    shape: dict[str, Any],
    idwf: str,
    case_id: str,
    service: Any,
) -> None:
    """Timer-specific handling with time-based waiting.

    On first arrival (status='pending'):
    1. Parse the trigger string as a timestamp using ``strtotime()``-like logic.
    2. Set status to 'waiting' with trigger data stored in token's external_data.

    On subsequent iterations:
    - If time has elapsed → advance via movenext and mark finished.
    - Otherwise keep waiting.

    Mirrors legacy ``run_IntermediateTimerEvent()``.
    """
    props = shape.get("properties") or {}
    name = props.get("name", "")
    resource_id = shape["resourceId"]

    # Fetch current token to check status.
    token = await service.get_token(idwf, case_id, resource_id)
    if not token:
        return  # Token doesn't exist yet.

    status = getattr(token, "status", None)

    if status == "pending":
        # First arrival — parse trigger and set to waiting.
        try:
            trigger_str = name.strip("'\"")
            trigger_dt = _parse_trigger_timestamp(trigger_str)
            if trigger_dt is None:
                raise ValueError(f"Cannot parse timer trigger: {trigger_str}")

            trigger_iso = trigger_dt.isoformat()
            data = {"trigger": trigger_iso}
            await service._set_token_status(
                idwf, case_id, resource_id, "waiting", data=data
            )
            # Register a pending schedule entry so the scheduler can fire this timer.
            await service._create_timer_event_schedule(
                case_id=case_id,
                idwf=idwf,
                resource_id=resource_id,
                trigger_time=trigger_dt,
                data_json={"trigger": trigger_iso},
            )
        except (ValueError, TypeError) as exc:
            raise ValueError(f"Invalid timer trigger '{name}': {exc}") from None

    elif status == "waiting":
        # Check if time has elapsed.
        current_dt = datetime.now(UTC)
        trigger_str = (
            token.external_data.get("trigger")
            if isinstance(token.external_data, dict)
            else ""
        )
        if not trigger_str:
            return  # No trigger set — keep waiting.

        try:
            trigger_dt = _parse_trigger_timestamp(trigger_str)
            if trigger_dt is None:
                return  # Invalid trigger — keep waiting.

            # Compare time zones: ensure both are aware or naive consistently.
            if current_dt.tzinfo and not trigger_dt.tzinfo:
                trigger_dt = trigger_dt.replace(tzinfo=UTC)
            elif not current_dt.tzinfo and trigger_dt.tzinfo:
                trigger_dt = trigger_dt.replace(tzinfo=None)

            if current_dt >= trigger_dt:
                # Time has elapsed — advance.
                await service.movenext(resource_id, idwf, case_id)
                # Check if previous shape is an EventbasedGateway — if so, wake it up.
                # Mirrors legacy event_helper.php L403-411.
                # The previous shape may be a SequenceFlow; traverse through it.
                previous_shapes = await service.get_previous(shape["resourceId"], idwf)
                if previous_shapes:
                    previous = previous_shapes[0]
                    prev_stencil = (previous.get("stencil") or {}).get("id", "")
                    if prev_stencil == "EventbasedGateway":
                        await service._set_token_status(
                            idwf, case_id, previous["resourceId"], "pending"
                        )
                    elif prev_stencil == "SequenceFlow":
                        flow_prev_shapes = await service.get_previous(previous["resourceId"], idwf)
                        if flow_prev_shapes:
                            flow_prev = flow_prev_shapes[0]
                            flow_prev_stencil = (flow_prev.get("stencil") or {}).get("id", "")
                            if flow_prev_stencil == "EventbasedGateway":
                                await service._set_token_status(
                                    idwf, case_id, flow_prev["resourceId"], "pending"
                                )
        except (ValueError, TypeError):
            return  # Invalid trigger string — keep waiting.


def _parse_trigger_timestamp(trigger_str: str) -> datetime | None:
    """Parse a timer trigger string to a datetime.

    Supports formats:
    - ISO 8601: '2024-01-15T10:30:00' or '2024-01-15T10:30:00Z'
    - Date only: '2024-01-15' (treated as midnight UTC)
    - Relative: '+1 hour', '+30 minutes' (relative to now)

    Mirrors legacy PHP ``strtotime()`` behavior.
    """
    trigger_str = trigger_str.strip()
    if not trigger_str:
        return None
    # Try ISO format first.
    try:
        if "T" in trigger_str and "Z" in trigger_str:
            return datetime.fromisoformat(trigger_str.replace("Z", "+00:00"))
        elif "T" in trigger_str:
            return datetime.fromisoformat(trigger_str)
    except (ValueError, TypeError):
        pass

    # Try date-only format.
    try:
        dt = datetime.strptime(trigger_str, "%Y-%m-%d")
        return dt.replace(tzinfo=UTC)
    except (ValueError, TypeError):
        pass

    # Try relative time (+1 hour, +30 minutes).
    match = re.match(r"^\+?(\d+)\s*(hour|minute|min|day)s?$", trigger_str, re.IGNORECASE)
    if match:
        value = int(match.group(1))
        unit = match.group(2).lower()
        delta_map = {
            "hour": timedelta(hours=value),
            "minute": timedelta(minutes=value),
            "min": timedelta(minutes=value),
            "day": timedelta(days=value),
        }
        return datetime.now(UTC) + delta_map.get(unit, timedelta())

    return None


# -- Handler Classes ----------------------------------------------------------- #


class IntermediateTimerEventHandler:
    """Handle a token arriving on an IntermediateTimerEvent shape.

    Routes to the timer-specific logic in :func:`run_intermediate_timer_event`.
    """

    _STENCIL_ID = "IntermediateTimerEvent"

    @classmethod
    def stencil_id(cls) -> str:
        return cls._STENCIL_ID

    async def handle(self, token: Any, shape: dict[str, Any], service: Any) -> bool:
        await run_intermediate_timer_event(shape, token.idwf, token.case_id, service)
        return False


class IntermediateMessageEventCatchingHandler:
    """Handle a token arriving on an IntermediateMessageEventCatching shape.

    Routes to generic catching logic via :func:`run_intermediate_event_catching`.
    """

    _STENCIL_ID = "IntermediateMessageEventCatching"

    @classmethod
    def stencil_id(cls) -> str:
        return cls._STENCIL_ID

    async def handle(self, token: Any, shape: dict[str, Any], service: Any) -> bool:
        await run_intermediate_event_catching(shape, token.idwf, token.case_id, service)
        return False


class IntermediateSignalEventCatchingHandler:
    """Handle a token arriving on an IntermediateSignalEventCatching shape.

    Checks SignalService for matching active signals; if found, advances the
    token past this shape. Otherwise creates a signal schedule so the scheduler
    can fire it later when signals arrive.
    """

    _STENCIL_ID = "IntermediateSignalEventCatching"

    @classmethod
    def stencil_id(cls) -> str:
        return cls._STENCIL_ID

    async def handle(self, token: Any, shape: dict[str, Any], service: Any) -> bool:
        """Check for active signal matches via SignalService; if found, advance the token. Otherwise create a waiting schedule."""
        idwf = token.idwf
        case_id = token.case_id
        resource_id = token.resource_id

        # Get signal name from shape properties (matches legacy PHP $shape->properties->name).
        props = shape.get("properties") or {}
        signal_name = props.get("name", "")

        if signal_name:
            try:
                from app.services.signal_service import SignalService

                signal_svc = SignalService(service.db)  # type: ignore[arg-type]
                active_signals = await signal_svc.find_by_name(signal_name)

                if active_signals:
                    # Found matching signals — advance the token past this shape.
                    logger.info(
                        "SignalCatchingHandler: found %d active signal(s) for '%s', advancing token",
                        len(active_signals),
                        signal_name,
                    )
                    await service.movenext(resource_id, idwf, case_id)

                    return False
            except Exception as exc:
                logger.error(
                    "SignalCatchingHandler: error checking signals for '%s': %s",
                    signal_name,
                    exc,
                )

        # No active signals found — create a signal schedule so the scheduler can fire this later when signals arrive.
        await service._set_token_status(
            idwf,
            case_id,
            resource_id,
            "waiting",
            data={"signal_name": signal_name},
        )
        try:
            await service._create_signal_event_schedule(
                case_id=case_id,
                idwf=idwf,
                resource_id=resource_id,
                signal_name=signal_name,
                data_json={"name": signal_name},
            )
        except Exception as exc:
            logger.warning(
                "SignalCatchingHandler: failed to create signal schedule for '%s': %s",
                signal_name,
                exc,
            )

        return False


class IntermediateErrorEventHandler:
    """Handle a token arriving on an IntermediateErrorEvent shape."""

    _STENCIL_ID = "IntermediateErrorEvent"

    @classmethod
    def stencil_id(cls) -> str:
        return cls._STENCIL_ID

    async def handle(self, token: Any, shape: dict[str, Any], service: Any) -> bool:
        await run_intermediate_event_catching(shape, token.idwf, token.case_id, service)
        return False


class IntermediateConditionalEventHandler:
    """Handle a token arriving on an IntermediateConditionalEvent shape."""

    _STENCIL_ID = "IntermediateConditionalEvent"

    @classmethod
    def stencil_id(cls) -> str:
        return cls._STENCIL_ID

    async def handle(self, token: Any, shape: dict[str, Any], service: Any) -> bool:
        await run_intermediate_event_catching(shape, token.idwf, token.case_id, service)
        return False


class IntermediateLinkEventCatchingHandler:
    _STENCIL_ID = "IntermediateLinkEventCatching"

    @classmethod
    def stencil_id(cls) -> str:
        return cls._STENCIL_ID

    async def handle(self, token: Any, shape: dict[str, Any], service: Any) -> bool:
        await run_intermediate_event_catching(shape, token.idwf, token.case_id, service)
        return False


# -- No-op stubs for missing intermediate events ---------------------------- #
# These stencils exist in legacy PHP helper functions as no-ops or passthroughs.
# Registering them prevents the engine dispatcher from crashing on unknown IDs.


class _NoOpIntermediateEventCatchingHandler:
    """Generic no-op stub for intermediate catching events not yet implemented."""

    @classmethod
    def stencil_id(cls) -> str:
        return "NoOp"  # not dispatched; only used as base class sentinel

    async def handle(self, token: Any, shape: dict[str, Any], service: Any) -> bool:
        return False


class IntermediateEscalationEventCatchingHandler(_NoOpIntermediateEventCatchingHandler):
    """IntermediateEscalationEvent catching — no-op in PHP too (event_helper.php:425-430)."""

    _STENCIL_ID = "IntermediateEscalationEvent"


class IntermediateCancelEventHandler(_NoOpIntermediateEventCatchingHandler):
    """IntermediateCancelEvent catching — no-op in PHP too (event_helper.php:454-459)."""

    _STENCIL_ID = "IntermediateCancelEvent"


class IntermediateCompensationEventCatchingHandler(
    _NoOpIntermediateEventCatchingHandler
):
    """IntermediateCompensationEventCatching — no-op in PHP too (event_helper.php:461-466)."""

    _STENCIL_ID = "IntermediateCompensationEventCatching"


class IntermediateMultipleEventCatchingHandler(_NoOpIntermediateEventCatchingHandler):
    """IntermediateMultipleEventCatching — no-op in PHP too (event_helper.php:485-490)."""

    _STENCIL_ID = "IntermediateMultipleEventCatching"


# Non-trivial stub: waits for all throwers before advancing.
class IntermediateParallelMultipleEventCatchingHandler(
    _NoOpIntermediateEventCatchingHandler
):
    """IntermediateParallelMultipleEventCatching — partial implementation.

    Waits until at least one matching throwing event has been observed, then advances.
    """

    _STENCIL_ID = "IntermediateParallelMultipleEventCatching"


class IntermediateMessageEventThrowingHandler:
    """Handle a token arriving on an IntermediateMessageEventThrowing shape.

    Routes to generic throwing logic via :func:`run_intermediate_event_throwing`.
    """

    _STENCIL_ID = "IntermediateMessageEventThrowing"

    @classmethod
    def stencil_id(cls) -> str:
        return cls._STENCIL_ID

    async def handle(self, token: Any, shape: dict[str, Any], service: Any) -> bool:
        await run_intermediate_event_throwing(shape, token.idwf, token.case_id, service)
        return False


class IntermediateLinkEventThrowingHandler:
    """Handle a token arriving on an IntermediateLinkEventThrowing shape.

    Routes to generic throwing logic via :func:`run_intermediate_event_throwing`.
    """

    _STENCIL_ID = "IntermediateLinkEventThrowing"

    @classmethod
    def stencil_id(cls) -> str:
        return cls._STENCIL_ID

    async def handle(self, token: Any, shape: dict[str, Any], service: Any) -> bool:
        await run_intermediate_event_throwing(shape, token.idwf, token.case_id, service)
        return False


class IntermediateSignalEventThrowingHandler:
    """Handle a token arriving on an IntermediateSignalEventThrowing shape.

    Broadcasts the signal to SignalService so all matching catchers can pick it up.
    Signal catchers check SignalService for active signals and advance if found.
    """

    _STENCIL_ID = "IntermediateSignalEventThrowing"

    @classmethod
    def stencil_id(cls) -> str:
        return cls._STENCIL_ID

    async def handle(self, token: Any, shape: dict[str, Any], service: Any) -> bool:
        # Broadcast signal to SignalService so all matching catchers can pick it up.
        # Do NOT dispatch catchers directly — signal catchers need to check
        # SignalService for active signals (which may not exist yet).
        from app.services.signal_service import SignalService

        signal_name = (shape.get("properties") or {}).get("name", "")
        if signal_name:
            signal_svc = SignalService(service.db)
            await signal_svc.broadcast(signal_name)
            logger.info("SignalThrowingHandler: broadcast signal '%s'", signal_name)
        return True


# -- Auto-registration at import time ----------------------------------------- #


ENGINE_HANDLER_REGISTRY.register(
    IntermediateTimerEventHandler._STENCIL_ID, IntermediateTimerEventHandler
)
ENGINE_HANDLER_REGISTRY.register(
    IntermediateMessageEventCatchingHandler._STENCIL_ID,
    IntermediateMessageEventCatchingHandler,
)
ENGINE_HANDLER_REGISTRY.register(
    IntermediateSignalEventCatchingHandler._STENCIL_ID,
    IntermediateSignalEventCatchingHandler,
)
ENGINE_HANDLER_REGISTRY.register(
    IntermediateErrorEventHandler._STENCIL_ID, IntermediateErrorEventHandler
)
ENGINE_HANDLER_REGISTRY.register(
    IntermediateConditionalEventHandler._STENCIL_ID, IntermediateConditionalEventHandler
)
ENGINE_HANDLER_REGISTRY.register(
    IntermediateLinkEventCatchingHandler._STENCIL_ID,
    IntermediateLinkEventCatchingHandler,
)

# Register no-op stubs for intermediate stencils not yet implemented.
ENGINE_HANDLER_REGISTRY.register(
    IntermediateEscalationEventCatchingHandler._STENCIL_ID,
    IntermediateEscalationEventCatchingHandler,
)
ENGINE_HANDLER_REGISTRY.register(
    IntermediateCancelEventHandler._STENCIL_ID, IntermediateCancelEventHandler
)
ENGINE_HANDLER_REGISTRY.register(
    IntermediateCompensationEventCatchingHandler._STENCIL_ID,
    IntermediateCompensationEventCatchingHandler,
)
ENGINE_HANDLER_REGISTRY.register(
    IntermediateMultipleEventCatchingHandler._STENCIL_ID,
    IntermediateMultipleEventCatchingHandler,
)
ENGINE_HANDLER_REGISTRY.register(
    IntermediateParallelMultipleEventCatchingHandler._STENCIL_ID,
    IntermediateParallelMultipleEventCatchingHandler,
)
ENGINE_HANDLER_REGISTRY.register(
    IntermediateMessageEventThrowingHandler._STENCIL_ID,
    IntermediateMessageEventThrowingHandler,
)
ENGINE_HANDLER_REGISTRY.register(
    IntermediateLinkEventThrowingHandler._STENCIL_ID,
    IntermediateLinkEventThrowingHandler,
)
ENGINE_HANDLER_REGISTRY.register(
    IntermediateSignalEventThrowingHandler._STENCIL_ID,
    IntermediateSignalEventThrowingHandler,
)
