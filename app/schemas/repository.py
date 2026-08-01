"""Pydantic v2 schemas for the Repository API.

Organized into:
- Request schemas (used as FastAPI `Body` / `Query` typed params)
- Response schemas (returned via `response_model=` on route decorators)
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

# -- Request Schemas ----------------------------------------------------------- #


class ModelCreate(BaseModel):
    """POST `/api/v1/models` — create a brand-new empty scaffold.

    Matches the legacy `add()` method: idwf is required, folder/name default.
    """

    model_config = ConfigDict(extra="forbid")

    idwf: str = Field(..., description="Unique model identifier (primary key).")
    folder: str = Field(default="General", description="Folder to place the model in.")
    name: str | None = Field(default=None, description='Display name; defaults to "New Model".')


class ModelUpdate(BaseModel):
    """PUT `/api/v1/models/{idwf}` — save/update model with full data + svg payload."""

    model_config = ConfigDict(extra="forbid")

    data: dict = Field(..., description="BPMN stencil data (JSON object).")
    svg: str | None = Field(default=None, description="Raw SVG string to write to disk.")


class ModelDuplicateRequest(BaseModel):
    """POST `/api/v1/models/{idwf}/duplicate` — clone to a new idwf."""

    model_config = ConfigDict(extra="forbid")

    new_idwf: str = Field(..., alias="newIdwf", description="The new unique identifier for the duplicate.")


class SaveAsRequest(BaseModel):
    """POST `/api/v1/models/save-as` — save a copy with a custom title."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(..., description="New idwf / display name for the saved model.")
    data: dict = Field(..., description="BPMN stencil data to persist.")
    svg: str | None = Field(default=None, description="Raw SVG string.")


class FolderUpdate(BaseModel):
    """PATCH `/api/v1/models/{idwf}/folder` — move a model into another folder."""

    model_config = ConfigDict(extra="forbid")

    folder: str = Field(..., min_length=1, max_length=255, description="New folder name (HTML tags stripped server-side).")


class ScriptRequest(BaseModel):
    """POST `/api/v1/models/{idwf}/script` — re-save current model state.

    Legacy accepts a `script` field but ignores it; this is effectively a no-op
    save that bumps the version and updates modificationdate.
    """

    model_config = ConfigDict(extra="forbid")

    script: str | None = Field(default=None, description="Ignored — kept for legacy compat.")


class SaveModelRequest(BaseModel):
    """POST `/api/v1/models/{idwf}/save` — update data payload, keep existing SVG."""

    model_config = ConfigDict(extra="forbid")

    data: dict = Field(..., description="New BPMN stencil data to persist.")


# -- Response Schemas ---------------------------------------------------------- #


class ModelRead(BaseModel):
    """Full model read response. No `svg` field — served via separate /svg endpoints."""

    model_config = ConfigDict(from_attributes=True)

    idwf: str
    folder: str
    version: int
    data: dict | None = None
    created_at: datetime
    updated_at: datetime


class ModelCreateResponse(BaseModel):
    """Response from POST `/api/v1/models` (add scaffold)."""

    ok: bool = True
    msg: str = "Model created"
    idwf: str
    folder: str
    version: int


class SaveResponse(BaseModel):
    """Generic success response for save/duplicate/folder operations."""

    ok: bool = True
    msg: str


class CheckResponse(BaseModel):
    """GET `/api/v1/models/check/{idwf}` — availability check.

    `ok=true` means the idwf is NOT taken (safe to use); `ok=false` means it already exists.
    """

    ok: bool


class DumpResponse(BaseModel):
    """GET `/api/v1/models/{idwf}/dump` — verbose model dump with metadata."""

    htmltitle: str = ""
    theme: str = "default"
    base_url: str = ""
    idwf: str
    data: dict | None = None


class ShapesResponse(BaseModel):
    """GET `/api/v1/models/{idwf}/shapes` — shapes indexed by resourceId."""

    idwf: str
    shapes: dict[str, dict] = Field(default_factory=dict)


class CommentsResponse(BaseModel):
    """GET `/api/v1/models/{idwf}/comments/{resource_id}` — shape documentation."""

    stencil_id: str = ""
    documentation: str = ""
