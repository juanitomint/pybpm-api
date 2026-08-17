"""Pydantic v2 schemas for the Inbox API.

Used by ``app.api.inbox`` router under prefix ``/api/v1/inbox``.
"""

import datetime as dt
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


# -- Request Schemas ----------------------------------------------------------- #


class FolderMessagesRequest(BaseModel):
    """POST /inbox/folder/{folder}/ — paginated folder listing."""

    page: int = Field(default=1, ge=1)
    per_page: int = Field(default=15, ge=1, le=200)
    filter_query: str | None = None


class SendMessageRequest(BaseModel):
    """POST /inbox/send/ — compose and send a new message."""

    to_user_id: int
    subject: str = Field(..., max_length=512)
    body: str = ""


class MessageActionRequest(BaseModel):
    """Unified PATCH /inbox/message/{msgid}/ request.

    ``action`` selects between star (toggle), read (mark/unread), and tag (set/clear).
    ``is_read`` is used only for ``action="read"``; ``tag`` only for ``action="tag"``.
    """

    action: Literal["star", "read", "tag"]
    is_read: bool | None = None
    tag: str | None = Field(default=None, max_length=128)


# -- Response Schemas ---------------------------------------------------------- #


class MessageActionResponse(BaseModel):
    """Generic response for the unified message-action PATCH endpoint."""

    ok: bool = True
    msg: str = ""
    starred: bool | None = None
    read: bool | None = None


class MessageRead(BaseModel):
    """Single inbox message as returned to the client."""

    msgid: str
    subject: str
    body: str
    from_user: int | None = None
    to_user: int
    folder: str
    read: bool
    star: bool
    tag: str | None = None
    checkdate: dt.datetime | None = None
    icon_star: str = "fa fa-star-o"
    msg_time: str


class FolderMessagesResponse(BaseModel):
    """POST /inbox/folder/{folder}/ response — paginated message set."""

    messages: list[MessageRead] = []
    total_count: int = 0
    page: int = 1
    per_page: int = 15
    total_pages: int


class MessageCounts(BaseModel):
    """GET /inbox/counts/ — folder and unread counts for the current user."""

    inbox_count: int = 0
    sent_count: int = 0
    star_count: int = 0
    trash_count: int = 0
    unread_count: int = 0


class UserSearchResult(BaseModel):
    """POST /inbox/users/search/ — single user match for send-target selection."""

    text: str  # Display name (name lastname (nick))
    id_user: int


class UserSearchResponse(BaseModel):
    """Wrapper for the user search endpoint."""

    results: list[UserSearchResult] = []


class MessageOperationResponse(BaseModel):
    """Generic success/failure wrapper for send, move, delete operations.

    Used by ``POST /send``, ``DELETE`` endpoints.
    """

    ok: bool = True
    msg: str
    data: dict[str, Any] | None = None


class NewMessageFormResponse(BaseModel):
    """GET /inbox/new/ — compose form metadata (current user info + defaults)."""

    current_user_id: int
    default_subject: str = "No Subject"
