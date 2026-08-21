"""SQLAlchemy model for inbox messages.

Mirrors legacy ``dna2/application/modules/inbox/`` MongoDB ``msg`` collection,
adapted for PostgreSQL via SQLAlchemy.
"""

from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class Message(Base):
    """User-to-user inbox message.

    One recipient per message (single ``to_idu``). The legacy system supported
    multiple recipients via a JSON array but single-recipient covers ~90 % of
    use cases and avoids a junction table for v1.
    """

    __tablename__ = "messages"

    idmessage: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    to_idu: Mapped[int] = mapped_column(
        ForeignKey("users.idu"), index=True  # recipient user ID
    )
    from_idu: Mapped[int | None] = mapped_column(
        ForeignKey("users.idu")
    )  # sender; null for system messages
    subject: Mapped[str] = mapped_column(
        String(512), nullable=False, default="No Subject"
    )
    body: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    folder: Mapped[str] = mapped_column(
        String(32), index=True, server_default="inbox"  # inbox | star | trash | outbox
    )
    is_read: Mapped[bool] = mapped_column(default=False, server_default="false")
    is_starred: Mapped[bool] = mapped_column(default=False, server_default="false")
    tag: Mapped[str | None] = mapped_column(String(128))  # optional user-defined tag
    checkdate: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=func.now(), index=True
    )

    # Relationships — use foreign_keys to disambiguate from User's backref.
    recipient = relationship("User", foreign_keys=[to_idu], backref="received_messages")  # type: ignore[name-defined]
    sender = relationship("User", foreign_keys=[from_idu])  # type: ignore[name-defined]
