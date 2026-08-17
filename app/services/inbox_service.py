"""Inbox service layer.

Business logic for message CRUD, folder management (inbox/star/trash/outbox),
read/star tagging, and user search for the send-message workflow. Ported from
legacy ``dna2/application/modules/inbox/controllers/Msg.php`` (the
``Mensagem`` class).
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.message import Message
from app.models.user import User


# -- Helpers ------------------------------------------------------------------- #

def _format_time(checkdate: dt.datetime | None) -> str:
    """Format a timestamp in the legacy style used by the UI.

    Within 24 hours → ``HH:MM`` or ``N min``; otherwise ``YYYY-MM-DD HH:MM``.
    Handles both naive (SQLite storage) and aware (PostgreSQL) datetimes.
    """
    if not checkdate:
        return ""
    # Coerce naive datetimes to UTC so subtraction works against an aware ``now``.
    if checkdate.tzinfo is None:
        checkdate = checkdate.replace(tzinfo=dt.timezone.utc)
    now = dt.datetime.now(dt.timezone.utc)
    delta = now - checkdate
    if delta.total_seconds() < 86_400:
        minutes = int(delta.seconds // 60)
        if minutes == 0:
            return "now"
        if minutes < 60:
            return f"{minutes} min"
        return checkdate.strftime("%H:%M")
    return checkdate.strftime("%Y-%m-%d %H:%M")


# -- Service ------------------------------------------------------------------- #


class InboxService:
    """Stateless business logic over the messages table."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # -- Query helpers ------------------------------------------------------- #

    async def _user_exists(self, user_idu: int) -> bool:
        result = await self.db.execute(select(func.count()).where(User.idu == user_idu))
        return (result.scalar() or 0) > 0

    @staticmethod
    def _message_to_dict(message: Message) -> dict[str, Any]:
        starred = bool(message.is_starred)
        icon_star = "fa fa-star" if starred else "fa fa-star-o"
        return {
            "msgid": str(message.idmessage),
            "subject": message.subject or "No Subject",
            "body": message.body or "",
            "from_user": message.from_idu,
            "to_user": message.to_idu,
            "folder": message.folder,
            "read": bool(message.is_read),
            "star": starred,
            "tag": message.tag,
            "checkdate": message.checkdate.isoformat() if message.checkdate else None,
            "icon_star": icon_star,
            "msg_time": _format_time(message.checkdate),
        }

    # -- Folder listing ------------------------------------------------------ #

    async def get_folder_messages(
        self,
        user_idu: int,
        folder: str | None = None,
        page: int = 1,
        per_page: int = 15,
        filter_query: str | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        """Return paginated messages for ``user_idu`` in the given folder.

        ``folder`` values: ``inbox``, ``star``, ``trash``, ``outbox``. When
        omitted (or ``None``) returns all folders. Returns ``(rows, total_count)``.
        """
        base = select(Message).where(Message.to_idu == user_idu)

        if folder == "star":
            base = base.where(Message.is_starred.is_(True))
        elif folder:
            base = base.where(Message.folder == folder)

        # Filter — text search on subject/body (case-insensitive LIKE).
        if filter_query:
            pattern = f"%{filter_query}%"
            base = base.where(
                or_(Message.subject.ilike(pattern), Message.body.ilike(pattern))
            )

        count_stmt = select(func.count()).select_from(base.subquery())
        total_count = (await self.db.execute(count_stmt)).scalar() or 0

        query = base.order_by(Message.checkdate.desc()).offset(
            (page - 1) * per_page
        ).limit(per_page)
        result = await self.db.execute(query)
        rows = [self._message_to_dict(m) for m in result.scalars().all()]
        return rows, total_count

    async def get_message_by_id(self, message_id: int, user_idu: int) -> Message | None:
        """Fetch a single message; must belong to ``user_idu``."""
        query = select(Message).where(
            and_(Message.idmessage == message_id, Message.to_idu == user_idu)
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    # -- Mutations ----------------------------------------------------------- #

    async def send_message(
        self, sender_idu: int, recipient_idu: int, subject: str, body: str
    ) -> Message:
        """Create a new message. Returns the persisted ``Message`` row."""
        if not await self._user_exists(recipient_idu):
            raise ValueError("Recipient user not found")

        msg = Message(
            to_idu=recipient_idu,
            from_idu=sender_idu,
            subject=subject or "No Subject",
            body=body,
            folder="inbox",
            is_read=False,
            is_starred=False,
            checkdate=dt.datetime.now(dt.timezone.utc),
        )
        self.db.add(msg)
        await self.db.commit()
        await self.db.refresh(msg)

        # TODO(v1): trigger email notification when recipient has
        # ``notification_by_email == 'yes'``. Requires an async SMTP client.
        return msg

    async def mark_read(self, message_id: int, user_idu: int, is_read: bool = True) -> Message:
        """Mark a message as read/unread; raises if not found."""
        msg = await self.get_message_by_id(message_id, user_idu)
        if not msg:
            raise ValueError("Message not found or does not belong to the current user")
        msg.is_read = is_read
        await self.db.commit()
        return msg

    async def toggle_star(self, message_id: int, user_idu: int) -> Message:
        """Toggle ``is_starred`` on a message."""
        msg = await self.get_message_by_id(message_id, user_idu)
        if not msg:
            raise ValueError("Message not found or does not belong to the current user")
        msg.is_starred = not bool(msg.is_starred)
        await self.db.commit()
        return msg

    async def set_tag(self, message_id: int, user_idu: int, tag: str) -> Message:
        """Set (or clear) a user-defined tag on a message."""
        msg = await self.get_message_by_id(message_id, user_idu)
        if not msg:
            raise ValueError("Message not found or does not belong to the current user")
        msg.tag = tag
        await self.db.commit()
        return msg

    async def move_to_folder(
        self, message_ids: list[int], folder: str, user_idu: int
    ) -> int:
        """Move messages into ``folder``. Returns the number actually moved."""
        if folder not in ("inbox", "star", "trash", "outbox"):
            raise ValueError("Invalid folder")

        query = select(Message).where(
            and_(Message.idmessage.in_(message_ids), Message.to_idu == user_idu)
        )
        result = await self.db.execute(query)
        moved = 0
        for msg in result.scalars().all():
            if folder == "star":
                # Star is a virtual folder — toggle ``is_starred`` instead.
                msg.is_starred = True
            else:
                msg.folder = folder
            moved += 1

        await self.db.commit()
        return moved

    async def delete_messages(self, message_ids: list[int], user_idu: int) -> int:
        """Permanently remove messages (only those in ``trash``). Returns count."""
        query = select(Message).where(
            and_(
                Message.idmessage.in_(message_ids),
                Message.to_idu == user_idu,
                Message.folder == "trash",
            )
        )
        result = await self.db.execute(query)
        deleted = 0
        for msg in result.scalars().all():
            await self.db.delete(msg)
            deleted += 1

        await self.db.commit()
        return deleted

    # -- Counts / toolbar ---------------------------------------------------- #

    async def count_messages(self, user_idu: int) -> dict[str, int]:
        """Return counts keyed by folder plus an ``unread_count`` for inbox."""
        counts: dict[str, int] = {}
        for fld in ("inbox", "star", "trash"):
            q = select(func.count()).where(
                and_(Message.to_idu == user_idu, Message.folder == fld)
            )
            counts[f"{fld}_count"] = (await self.db.execute(q)).scalar() or 0

        sent_q = select(func.count()).where(Message.from_idu == user_idu)
        counts["sent_count"] = (await self.db.execute(sent_q)).scalar() or 0

        unread_q = select(func.count()).where(
            and_(Message.to_idu == user_idu, Message.folder == "inbox", Message.is_read.is_(False))
        )
        counts["unread_count"] = (await self.db.execute(unread_q)).scalar() or 0

        return counts

    async def get_toolbar_messages(self, user_idu: int) -> list[dict[str, Any]]:
        """Four most recent messages in the user's inbox — used by toolbar widget."""
        query = (
            select(Message)
            .where(and_(Message.to_idu == user_idu, Message.folder == "inbox"))
            .order_by(Message.checkdate.desc())
            .limit(4)
        )
        result = await self.db.execute(query)
        return [self._message_to_dict(m) for m in result.scalars().all()]

    # -- User search --------------------------------------------------------- #

    async def search_users(self, term: str, limit: int = 20) -> list[dict[str, Any]]:
        """Search users whose display name or nick contains ``term``.

        Returns rows shaped like legacy ``get_users()`` JSON for the send form.
        """
        pattern = f"%{term}%"
        query = (
            select(User)
            .where(
                or_(
                    User.nick.ilike(pattern),
                    User.name.ilike(pattern),
                    User.lastname.ilike(pattern),
                )
            )
            .limit(limit)
        )
        result = await self.db.execute(query)
        users = result.scalars().all()
        return [
            {
                "text": f"{u.name or ''} {u.lastname or ''}".strip() or u.nick,
                "id_user": u.idu,
            }
            for u in users
        ]
