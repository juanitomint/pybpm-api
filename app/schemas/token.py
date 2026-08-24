"""Pydantic v2 schemas for Token Management API."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# -- Request Schemas ----------------------------------------------------------- #


class TokenCreate(BaseModel):
    """Request body for creating a new token (legacy Engine::token_checkin)."""

    model_config = ConfigDict(extra="forbid")

    resource_id: str = Field(
        ..., description="Resource ID of the shape where this token is placed"
    )
    type_: str = Field(
        alias="type",
        description="Stencil ID (e.g., 'Task', 'StartNoneEvent')",
    )
    status: str = Field(
        default="pending",
        pattern=r"^(pending|waiting|finished)$",
        description="Initial token status",
    )


class TokenUpdate(BaseModel):
    """Request body for updating an existing token (legacy Engine::update_token)."""

    model_config = ConfigDict(extra="forbid")

    status: str | None = Field(
        default=None,
        pattern=r"^(pending|waiting|finished)$",
        description="New status (pending/waiting/finished)",
    )
    assign: list[int] | None = Field(
        default=None, description="List of user IDs assigned to this token"
    )
    external_data: dict[str, Any] | None = Field(
        default=None, description="External webhook data keyed by origin"
    )


class TokenAssignRequest(BaseModel):
    """Request body for assigning users to a token (legacy Engine::assign_task)."""

    model_config = ConfigDict(extra="forbid")

    user_ids: list[int] = Field(
        ..., alias="idu", description="List of user IDs to assign the task to"
    )


# -- Response Schemas ---------------------------------------------------------- #


class TokenResponse(BaseModel):
    """Response schema for a single token."""

    model_config = ConfigDict(from_attributes=True)

    idwf: str
    case_id: str
    resource_id: str
    type: str  # stencil ID (e.g., "Task", "StartNoneEvent")
    status: str
    assign: list[int] | None = Field(
        default=None, description="List of assigned user IDs"
    )
    external_data: dict[str, Any] | None = Field(
        default=None, description="External webhook data keyed by origin"
    )
    check_date: datetime | None = Field(default=None)
    run_count: int = 0
    locked_by: int | None = Field(default=None)
    tasktype: str | None = Field(default=None)
    updated_at: datetime = Field(alias="updatedAt")


class TokenListResponse(BaseModel):
    """Response schema for a list of tokens."""

    model_config = ConfigDict(from_attributes=True)

    idwf: str
    case_id: str
    resource_id: str
    type: str  # stencil ID (e.g., "Task", "StartNoneEvent")
    status: str
    assign: list[int] | None = Field(
        default=None, description="List of assigned user IDs"
    )
    check_date: datetime | None = Field(default=None)
    created_at: datetime = Field(alias="createdAt")


class TokenCreateResponse(BaseModel):
    """Response after creating a token."""

    ok: bool = True
    msg: str = "Token created successfully"
    resource_id: str | None = None
    idwf: str | None = None


class TokenUpdateResponse(BaseModel):
    """Response after updating a token."""

    ok: bool = True
    msg: str = "Token updated successfully"
    resource_id: str | None = None
    idwf: str | None = None


class TokenDeleteResponse(BaseModel):
    """Response after deleting a token."""

    ok: bool = True
    msg: str = "Token deleted successfully"
    resource_id: str | None = None
    idwf: str | None = None


class TokenAssignResponse(BaseModel):
    """Response after assigning users to a token."""

    ok: bool = True
    msg: str = "Token assigned successfully"
    resource_id: str | None = None
    idwf: str | None = None
    assign: list[int] = Field(default=[], description="List of assigned user IDs")


class TokenStatusSummary(BaseModel):
    """Response schema for token status summary (legacy Engine::get_case_tokens)."""

    model_config = ConfigDict(from_attributes=True)

    idwf: str
    case_id: str
    pending_count: int = 0
    waiting_count: int = 0
    finished_count: int = 0
    total_count: int = 0
