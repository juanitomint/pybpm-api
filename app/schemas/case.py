"""Pydantic v2 schemas for the Case Manager API.

All endpoints are under prefix `/cases` in `app/api/bpm/cases.py`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


# -- Request Schemas ----------------------------------------------------------- #


class UpdateCaseRequest(BaseModel):
    """PATCH /cases/{idcase} — update case attributes.

    Ported from legacy CaseManager::update().
    Updates status, data variables, or parent information for a running case.
    """

    model_config = ConfigDict(extra="forbid")

    status: str | None = Field(
        default=None,
        pattern=r"^(open|running|paused|closed)$",
        description="New status (e.g., 'open', 'running', 'paused', 'closed')",
    )
    data: dict[str, Any] | None = Field(
        default=None,
        description="Update case variables / input data",
    )
    parent_json: dict[str, Any] | None = Field(
        default=None,
        alias="parentJson",
        description="Parent case information (sub-process call)",
    )


class FreezCaseRequest(BaseModel):
    """POST /cases/{idcase}/freez — freeze/unfreeze a case.

    Ported from legacy CaseManager::freez().
    Toggles the locked_by status to pause/resume case processing.
    """

    model_config = ConfigDict(extra="forbid")

    iduser: int | None = Field(
        default=None,
        description="User ID who is freezing/unfreezing the case",
    )


# -- Response Schemas ---------------------------------------------------------- #


class CaseRead(BaseModel):
    """GET /cases/{idcase} — single case details.

    Ported from legacy CaseManager::get_case().
    Returns case attributes in JSON format with camelCase aliases matching the legacy response shape.
    """

    model_config = ConfigDict(from_attributes=True)

    idcase: str
    idwf: str
    status: str
    initiator_id: int | None = Field(default=None, alias="initiatorId")
    data: dict[str, Any] | None = None
    locked_by: int | None = Field(default=None, alias="lockedBy")
    locked_date: datetime | None = Field(default=None, alias="lockedDate")
    run_manual: bool = Field(default=False, alias="runManual")
    parent_json: dict[str, Any] | None = Field(default=None, alias="parentJson")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")


class CasesListResponse(BaseModel):
    """GET /cases — multiple cases (list all).

    Ported from legacy CaseManager::list().
    Returns basic case information for UI list views.
    """

    model_config = ConfigDict(from_attributes=True)

    idcase: str
    idwf: str
    status: str
    initiator_id: int | None = Field(default=None, alias="initiatorId")
    created_at: datetime = Field(alias="createdAt")


class UpdateCaseResponse(BaseModel):
    """PATCH /cases/{idcase} — response after updating a case."""

    ok: bool = True
    msg: str = "Case updated successfully"
    idcase: str | None = None


class FreezCaseResponse(BaseModel):
    """POST /cases/{idcase}/freez — response after freeze/unfreeze."""

    ok: bool = True
    msg: str = "Case frozen/unfrozen successfully"
    idcase: str | None = None
    locked_by: int | None = Field(default=None, alias="lockedBy")


class DeleteCaseResponse(BaseModel):
    """DELETE /cases/{idcase} — response after deleting a case."""

    ok: bool = True
    msg: str = "Case deleted successfully"
    idcase: str | None = None
