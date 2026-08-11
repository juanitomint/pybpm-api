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

    Ported from legacy ``Engine::Run($model, $idwf, $case, $run_resourceId, $silent)``.
    ``idwf``, ``idcase``, and ``run_resource_id`` are path segments; this schema
    carries the optional body fields only (``silent``).
    """

    model_config = ConfigDict(extra="forbid")

    silent: bool | None = Field(
        default=None,
        description="When true, suppress debug output and inbox notifications.",
    )


class RunResponse(BaseModel):
    """Response from the engine run loop."""

    ok: bool = True
    msg: str = "Engine executed successfully"


# -- Post Request/Response ------------------------------------------------------- #


class PostRequest(BaseModel):
    """POST /api/v1/bpm/engine/post/{token_id} — external webhook callback.

    Ported from legacy ``Engine::post($token_id, $external_origin, $external_id)``.
    The token ID comes from the URL path; this schema carries the remaining
    fields that the caller supplies in the body.
    """

    model_config = ConfigDict(extra="forbid")

    external_origin: str = Field(
        ..., description="Origin of the external event (e.g., 'email', 'webhook')."
    )
    external_id: str | None = Field(
        default=None,
        description="Optional ID associated with this external origin.",
    )
    data: dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary payload to persist on the token's external_data.",
    )


class PostResponse(BaseModel):
    """Response after saving POST data and advancing the engine."""

    ok: bool = True
    msg: str = "POST processed successfully"


# -- Assign Request/Response ------------------------------------------------------ #


class AssignRequest(BaseModel):
    """POST /api/v1/bpm/engine/assign — assign a task to one or more users.

    Ported from legacy ``Engine::assign($model, $idwf, $idcase, $src_resourceId, $resourceId, $idu)``.
    """

    model_config = ConfigDict(extra="forbid")

    idwf: str = Field(..., description="Workflow (model) identifier.")
    idcase: str = Field(..., description="Case identifier to assign the task on.")
    src_resource_id: str = Field(
        ..., alias="srcResourceId", description="Source shape resource ID."
    )
    resource_id: str = Field(
        ...,
        alias="resourceId",
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
