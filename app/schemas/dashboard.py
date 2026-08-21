"""Pydantic v2 schemas for the Dashboard API (cases & tasks).

All endpoints live under `/api/v1/dashboard/…` in `app/api/dashboard/`.
"""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict, Field

# -- Response schemas ---------------------------------------------------------- #


class CaseCountResponse(BaseModel):
    """GET /dashboard/cases/counts/ — counts of cases by status for current user."""

    open: int = 0
    closed: int = 0


class CaseListItem(BaseModel):
    """Single case row returned in list endpoints.

    Mirrors the legacy ``prepare_cases()`` output shape so pybpm-ui can render it directly.
    """

    model_config = ConfigDict(populate_by_name=True)

    idcase: str
    idwf: str
    status: str
    model_name: str = ""  # resolved from BpmModel on read
    created_at: dt.datetime = Field(alias="createdAt")
    updated_at: dt.datetime = Field(alias="updatedAt")
    time_elapsed: str = ""  # human-readable elapsed since creation


class CasesListResponse(BaseModel):
    """Paginated case list for dashboard widgets."""

    cases: list[CaseListItem] = []
    total: int = 0
    page: int = 1
    per_page: int = 20
    total_pages: int = 0


class TaskCountResponse(BaseModel):
    """GET /dashboard/tasks/count — counts grouped by lifecycle status for current user."""

    pending: int = 0
    validating: int = 0


class TaskListItem(BaseModel):
    """Single task (token) row returned in list endpoints.

    Mirrors the legacy ``prepare_tasks()`` output shape so pybpm-ui can render it directly.
    """

    model_config = ConfigDict(populate_by_name=True)

    resource_id: str = Field(alias="resourceId")
    type_: str = Field(alias="type", description="BPMN stencil ID (e.g., 'Task')")
    title: str
    status: str  # usually 'user' for pending tasks
    check_date: dt.datetime | None = Field(default=None, alias="checkDate")
    time_elapsed: str = ""  # human-readable elapsed since check_date
    model_name: str = ""  # resolved from BpmModel on read
    idwf: str
    case_id: str = Field(alias="case_id")
    locked_by: int | None = None  # raw Token.locked_by FK value
    locked: bool = False  # True if Token.locked_by is not NULL
    locked_by_nick: str | None = None  # User.nick of the locker (NULL when unlocked)


class TasksPendingResponse(BaseModel):
    """Paginated pending task list for dashboard widgets."""

    tasks: list[TaskListItem] = []
    total: int = 0
    page: int = 1
    per_page: int = 20
    total_pages: int = 0


# -- Request schemas ----------------------------------------------------------- #


class CasesListQuery(BaseModel):
    """Query parameters for GET /dashboard/cases/."""

    status: str | None = Field(
        default=None,
        description="Filter by case status ('open' or 'closed'). Defaults to all.",
    )
    page: int = Field(default=1, ge=1)
    per_page: int = Field(default=20, ge=1, le=100)
