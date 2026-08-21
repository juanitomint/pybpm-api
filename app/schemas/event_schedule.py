"""Pydantic v2 schemas for Event Schedule CRUD."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# -- Request Schemas ----------------------------------------------------------- #


class EventScheduleCreate(BaseModel):
    """POST /api/v1/events/schedules/ — create a new event schedule entry."""

    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(..., description="Running case ID this schedule belongs to.")
    idwf: str = Field(..., description="Workflow (model) identifier.")
    resource_id: str = Field(
        ..., description="Shape resourceId the timer/signal/conditional is attached to."
    )
    trigger_time: datetime = Field(
        ..., description="When the scheduler should fire this event (ISO 8601 with tz)."
    )
    schedule_type: str = Field(
        default="timer",
        pattern=r"^(timer|signal|conditional)$",
        description="Type of event trigger.",
    )
    idu: int | None = Field(
        default=None,
        description="User ID who created this schedule entry (null for engine-created).",
    )
    status: str = Field(
        default="pending",
        pattern=r"^(pending|fired|canceled)$",
        description="Schedule status.",
    )
    data_json: dict[str, Any] | None = Field(
        default=None,
        description="Optional JSON payload (e.g., parsed trigger expression).",
    )


class EventScheduleUpdate(BaseModel):
    """PATCH /api/v1/events/schedules/{idschedule} — update schedule fields."""

    model_config = ConfigDict(extra="forbid")

    status: str | None = Field(
        default=None,
        pattern=r"^(pending|fired|canceled)$",
        description="New status. Use 'fired' after scheduler processes it, 'canceled' to abort.",
    )
    trigger_time: datetime | None = Field(
        default=None, description="Reschedule to a new trigger time (ISO 8601 with tz)."
    )
    data_json: dict[str, Any] | None = Field(
        default=None, description="Update the JSON payload."
    )


# -- Response Schemas ---------------------------------------------------------- #


class EventScheduleResponse(BaseModel):
    """Single event schedule response."""

    model_config = ConfigDict(from_attributes=True)

    idschedule: int
    case_id: str
    idwf: str
    resource_id: str
    trigger_time: datetime
    schedule_type: str
    status: str
    idu: int | None = None
    data_json: dict[str, Any] | None = None
    updated_at: datetime


class EventScheduleListResponse(BaseModel):
    """Paginated list wrapper."""

    model_config = ConfigDict(from_attributes=True)

    total: int = 0
    page: int = 1
    per_page: int = 25
    items: list[EventScheduleResponse] = Field(default_factory=list)


class EventScheduleOperationResponse(BaseModel):
    """Generic success response for create/patch/delete operations."""

    model_config = ConfigDict(from_attributes=True)

    ok: bool = True
    idschedule: int | None = None
    detail: str = ""
