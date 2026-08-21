"""Pydantic v2 schemas for the Engine API (case lifecycle)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# -- Request Schemas ----------------------------------------------------------- #


class NewcaseRequest(BaseModel):
    """POST /api/v1/bpm/engine/newcase — create a new case instance."""

    model_config = ConfigDict(extra="forbid")

    idwf: str = Field(..., description="Workflow (model) identifier to instantiate.")
    manual: bool = Field(
        default=False,
        description=(
            "When true, sets run_manual flag on the case record for debugging."
        ),
    )
    parent: str | None = Field(
        default=None,
        description="Parent case id (sub-process call).",
    )
    silent: bool = Field(
        default=False,
        description=("When true, skip inbox message creation and HTTP redirect."),
    )
    data: dict[str, Any] = Field(
        default_factory=dict,
        description="Initial case variables / input data.",
    )


class StartRequest(BaseModel):
    """POST /api/v1/bpm/engine/start — resume an existing case at start shapes."""

    model_config = ConfigDict(extra="forbid")

    idwf: str = Field(..., description="Workflow (model) identifier.")
    idcase: str = Field(..., description="Existing case identifier to start/resume.")
    silent: bool = Field(
        default=False,
        description="When true, skip inbox message creation and HTTP redirect.",
    )


# -- Response Schemas ---------------------------------------------------------- #


class CaseCreated(BaseModel):
    """Response from newcase — the freshly created case identifier."""

    model_config = ConfigDict(from_attributes=True)

    idwf: str
    idcase: str


class StartResponse(BaseModel):
    """Response from start — confirms pending tokens were placed on start shapes."""

    idwf: str
    idcase: str
    tokens_created: int = 0


# -- Run Request/Response ------------------------------------------------------- #


class RunRequest(BaseModel):
    """POST /api/v1/bpm/engine/run — execute the engine loop for a case.

    The legacy ``Engine::Run()`` method was called automatically by CodeIgniter's
    redirect after Startcase(). In pybpm-api we make it explicit: clients POST to
    this endpoint to drive the engine forward one tick.
    """

    model_config = ConfigDict(extra="forbid")

    idwf: str = Field(..., description="Workflow (model) identifier.")
    idcase: str = Field(..., description="Case instance identifier.")


class RunResponse(BaseModel):
    """Response from the engine run loop."""

    ok: bool = True
    msg: str = "Engine executed successfully"


# -- Post Request/Response ------------------------------------------------------- #


class PostRequest(BaseModel):
    """POST /api/v1/bpm/engine/post/{token_id} — external webhook callback.

    Used when an external system sends data back to the engine (e.g., after a
    Send Task dispatched a message and the receiver replied). The payload is
    stored on the case record under ``data['external'][origin][resourceId]`` so
    downstream handlers can read it.
    """

    model_config = ConfigDict(extra="forbid")

    external_origin: str = Field(
        ...,
        description="Origin label for the external data bucket (e.g., 'inbox', 'webhook').",
    )
    external_id: str | None = Field(
        default=None,
        description="Identifier of the external resource (message ID, webhook reference).",
    )
    data: dict[str, Any] | None = Field(
        default=None,
        description="Optional payload merged into case.data under data[external_origin][resourceId].",
    )


class PostResponse(BaseModel):
    """Response after saving POST data and advancing the engine."""

    ok: bool = True
    msg: str = "POST processed successfully"


# -- Assign Request/Response ------------------------------------------------------ #


class AssignRequest(BaseModel):
    """POST /api/v1/bpm/engine/assign — assign a task to one or more users.

    Mirrors legacy ``Engine::assign()`` which updates the token's assignment list
    and records history. Used by pybpm-ui to route work items to specific users.
    """

    model_config = ConfigDict(extra="forbid")

    idwf: str = Field(..., description="Workflow (model) identifier.")
    idcase: str = Field(..., description="Case instance identifier.")
    resource_id: str = Field(
        ...,
        description="Target shape resource ID (the task).",
    )
    user_ids: list[int] = Field(
        ...,
        alias="idu",
        description="List of user IDs to assign the task to.",
    )


class AssignResponse(BaseModel):
    """Response after assigning a task and advancing the engine."""

    ok: bool = True
    msg: str = "Task assigned successfully"


# -- Gate Decision Request/Response -------------------------------------------- #
# (Priority 3: manual gateway completion endpoint)


class GateDecisionRequest(BaseModel):
    """POST /api/v1/bpm/engine/gate/{idwf}/{idcase}/{resource_id} — choose an outgoing flow from a manual gate.

    Mirrors legacy ``Engine::run_gate()`` which is called when the user clicks one
    of the gate's output buttons in pybpm-ui. The body carries the resourceId of
    the chosen SequenceFlow so the engine can mark the gate finished and advance
    along that specific outgoing edge (instead of moving all of them).
    """

    model_config = ConfigDict(extra="forbid")

    flow_resource_id: str = Field(
        ..., description="Resource ID of the outgoing SequenceFlow the user selected."
    )


class GateResponse(BaseModel):
    """Response after processing a manual gate decision."""

    ok: bool = True
    msg: str = "Gate decision recorded"


# -- Task Complete Request/Response -------------------------------------------- #
# (Priority 3: manual task completion endpoint)


class TaskCompleteRequest(BaseModel):
    """POST /api/v1/bpm/engine/task/{idwf}/{idcase}/{resource_id} — submit data and complete a manual task.

    Mirrors legacy ``Engine::manual_task()`` behavior: the user fills out form
    fields on pybpm-ui's manual-task modal, then POSTs here to mark the token as
    finished so movenext can advance along the outgoing flow(s). Any submitted
    data is merged into case.data for downstream shapes to read.
    """

    model_config = ConfigDict(extra="forbid")

    data: dict[str, Any] | None = Field(
        default=None,
        description="Optional user-submitted form data merged into case.data.",
    )

    action: str = Field(
        default="complete",
        description=(
            "Action to perform. 'complete' marks the task finished and advances; "
            "'skip' skips without marking complete (rarely used)."
        ),
    )


class TaskCompleteResponse(BaseModel):
    """Response after completing a manual task."""

    ok: bool = True
    msg: str = "Task completed successfully"
