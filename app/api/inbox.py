"""FastAPI router for Inbox API.

Mirrors the legacy ``dna2/application/modules/inbox/controllers/Inbox.php``
endpoints, adapted to RESTful conventions:

.. code-block:: text

    GET    /api/v1/inbox/              — main listing page data (default inbox)
    POST   /api/v1/inbox/folder/{folder}/           — paginated folder messages
    GET    /api/v1/inbox/counts/             — message counts by folder
    POST   /api/v1/inbox/filter/             — filter/search messages by query
    GET    /api/v1/inbox/message/{msgid}/    — get single message (marks as read)
    PATCH  /api/v1/inbox/message/{msgid}/    — unified star/read/tag action
    POST   /api/v1/inbox/send/               — send message to user(s)
    DELETE /api/v1/inbox/message/{msgid}/    — delete message permanently
"""

# from __future__ import annotations  # disabled for pydantic v2 compat

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.models.user import User
from app.schemas.inbox import (
    FolderMessagesRequest,
    FolderMessagesResponse,
    MessageActionRequest,
    MessageActionResponse,
    MessageCounts,
    MessageOperationResponse,
    MessageRead,
    SendMessageRequest,
)
from app.services.inbox_service import InboxService

logger = logging.getLogger(__name__)


router = APIRouter(prefix="/api/v1/inbox", tags=["inbox"])


async def _get_db() -> AsyncSession:  # pragma: no cover — FastAPI dep wiring
    from extensions import get_async_db
    async for session in get_async_db():
        yield session


# -- Endpoints ----------------------------------------------------------------- #


@router.get("", response_model=FolderMessagesResponse, status_code=status.HTTP_200_OK)
async def index(
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=15, ge=1, le=200),
    filter_query: str | None = Query(default=None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(_get_db),
):
    """Main listing page data — default view is the user's inbox."""
    svc = InboxService(db)
    rows, total_count = await svc.get_folder_messages(
        user_idu=user.idu,
        folder="inbox",
        page=page,
        per_page=per_page,
        filter_query=filter_query,
    )
    return FolderMessagesResponse(
        messages=[MessageRead(**m) for m in rows],
        total_count=total_count,
        page=page,
        per_page=per_page,
        total_pages=(total_count + per_page - 1) // per_page if per_page else 0,
    )

@router.get("/counts/", response_model=MessageCounts, status_code=status.HTTP_200_OK)
async def count_msgs(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(_get_db),
):
    """Return message counts by folder and unread inbox messages."""
    svc = InboxService(db)
    counts = await svc.count_messages(user_idu=user.idu)
    return MessageCounts(**counts)


@router.post("/filter/", response_model=FolderMessagesResponse, status_code=status.HTTP_200_OK)
async def show_msgs_by_filter(
    body: FolderMessagesRequest = FolderMessagesRequest(),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(_get_db),
):
    """Widget endpoint: search messages by free-text filter."""
    if not body.filter_query:
        return FolderMessagesResponse(messages=[], total_count=0, page=body.page, per_page=body.per_page, total_pages=0)

    svc = InboxService(db)
    rows, total_count = await svc.get_folder_messages(
        user_idu=user.idu,
        folder=None,  # search across all folders
        page=body.page,
        per_page=body.per_page,
        filter_query=body.filter_query,
    )
    return FolderMessagesResponse(
        messages=[MessageRead(**m) for m in rows],
        total_count=total_count,
        page=body.page,
        per_page=body.per_page,
        total_pages=(total_count + body.per_page - 1) // body.per_page if body.per_page else 0,
    )


@router.get("/message/{msgid}/", response_model=MessageRead, status_code=status.HTTP_200_OK)
async def get_msg(
    msgid: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(_get_db),
):
    """Get a single message by ID. Marks it as read on retrieval."""
    svc = InboxService(db)
    message = await svc.get_message_by_id(msgid, user_idu=user.idu)
    if not message:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Message not found"
        )

    # Mark as read on open (legacy behavior).
    if not bool(message.is_read):
        message.is_read = True
        await db.commit()

    return MessageRead(**InboxService._message_to_dict(message))


@router.patch(
    "/message/{msgid}/", response_model=MessageActionResponse, status_code=status.HTTP_200_OK
)
async def action_message(
    msgid: int,
    body: MessageActionRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(_get_db),
):
    """Unified PATCH handler for star / read / tag actions on a single message."""
    svc = InboxService(db)

    if body.action == "star":
        try:
            message = await svc.toggle_star(msgid, user_idu=user.idu)
            return MessageActionResponse(
                ok=True,
                msg="Star toggled" if not bool(message.is_starred) else "Message starred",
                starred=bool(message.is_starred),
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))

    elif body.action == "read":
        try:
            message = await svc.mark_read(
                msgid, user_idu=user.idu, is_read=bool(body.is_read)
            )
            return MessageActionResponse(
                ok=True,
                msg="Marked as read" if body.is_read else "Marked as unread",
                starred=bool(message.is_starred),
                read=bool(message.is_read),
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))

    elif body.action == "tag":
        try:
            tag = body.tag if body.tag is not None else ""
            await svc.set_tag(msgid, user_idu=user.idu, tag=tag)
            return MessageActionResponse(ok=True, msg="Tag set")
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))

    else:  # pragma: no cover — Literal guards this at the schema level
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown action: {body.action}",
        )


@router.post("/send/", response_model=MessageOperationResponse, status_code=status.HTTP_201_CREATED)
async def send(
    body: SendMessageRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(_get_db),
):
    """Send a message to one or more recipients.

    Accepts ``to_user_id`` as a single int; for multi-recipient support in v2,
    extend with a junction table.
    """
    svc = InboxService(db)
    try:
        msg = await svc.send_message(
            sender_idu=user.idu,
            recipient_idu=body.to_user_id,
            subject=body.subject,
            body=body.body or "",
        )
        return MessageOperationResponse(
            ok=True,
            msg="Message sent successfully",
            data={"msgid": str(msg.idmessage)},
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))



@router.delete(
    "/message/{msgid}/", response_model=MessageOperationResponse, status_code=status.HTTP_200_OK
)
async def remove_msg(
    msgid: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(_get_db),
):
    """Permanently delete a message (only those in trash)."""
    svc = InboxService(db)
    try:
        deleted = await svc.delete_messages([msgid], user_idu=user.idu)
        if deleted == 0:
            return MessageOperationResponse(
                ok=False, msg="Message not found or not in trash"
            )
        return MessageOperationResponse(ok=True, msg="Message permanently deleted")
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
