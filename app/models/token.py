from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class Token(Base):
    """Represents an active token in a running case.

    Mirrors the legacy MongoDB `tokens` collection. Each token tracks
    execution state for a specific shape within a case — its status
    (pending/waiting/finished), assignment, and metadata like check_date
    and run count.
    """

    __tablename__ = "bpm_tokens"

    idtoken: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    idwf: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("bpm_models.idwf", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    case_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("bpm_cases.idcase", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    resource_id: Mapped[str] = mapped_column(String(1024), nullable=False)
    type: Mapped[str] = mapped_column(String(64), nullable=False)  # stencil ID (e.g., "Task", "StartNoneEvent")
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="pending",
        server_default=sa.text("'pending'"),
    )
    assign: Mapped[list | None] = mapped_column(sa.JSON())  # list of user IDs assigned to this token
    external_data: Mapped[dict | None] = mapped_column(sa.JSON())  # external webhook data keyed by origin
    check_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    run_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    locked_by: Mapped[int | None] = mapped_column(Integer)
    locked_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    # Relationships
    case = relationship("BpmCase", back_populates="tokens")


class TokenHistory(Base):
    """Records the history of token state changes for audit trails.

    Mirrors the legacy MongoDB `tokens.history` collection. Each row captures
    a snapshot when a token's status changed — who did it, what shape, and when.
    Used for reporting and debugging workflow execution.
    """

    __tablename__ = "bpm_token_history"

    idhistory: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    idwf: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("bpm_models.idwf", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    case_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("bpm_cases.idcase", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    resource_id: Mapped[str] = mapped_column(String(1024), nullable=False)
    type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    check_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    run_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    name: Mapped[str | None] = mapped_column(String(255))  # shape's properties.name
    iduser: Mapped[int | None] = mapped_column(ForeignKey("users.idu", ondelete="SET NULL"))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
