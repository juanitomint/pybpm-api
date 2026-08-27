"""Event schedules — timer triggers, signal waits, conditional waits.

Stores pending event-triggered state that the scheduler must process. Each row
represents one active (non-fired) schedule entry for a token on an intermediate
event shape (e.g., a waiting timer, a signal catcher awaiting its thrower).

Mirrors legacy PHP timer/event trigger semantics where tokens transition from
``status='pending'`` → ``status='waiting'`` with a `trigger_time` stored
separately so the scheduler can efficiently query "what's due now?".

Schema:
- ``idschedule`` — primary key, auto-increment
- ``case_id`` — links to running case (no FK constraint)
- ``idwf`` — workflow ID (for cross-case lookups in subprocess scenarios)
- ``resource_id`` — shape resourceId this schedule entry belongs to
- ``trigger_time`` — when the scheduler should fire this event
- ``schedule_type`` — categorizes what kind of event: 'timer', 'signal', 'conditional'
- ``status`` — pending / fired / canceled (mirrors legacy token status)
- ``data_json`` — optional JSON payload (e.g., parsed trigger expression, signal name)

Relationships to Token and BpmCase for audit trails.
"""

from __future__ import annotations

from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.case import BpmCase


class EventSchedule(Base):
    """Represents a pending event schedule (timer trigger, signal wait, etc.).

    The scheduler polls this table to find events that should fire. Each row is
    one active schedule entry — when the trigger time arrives and status remains
    'pending', the scheduler fires the corresponding token's catching logic.
    """

    __tablename__ = "event_schedules"

    idschedule: Mapped[int] = mapped_column(
        sa.Integer, primary_key=True, autoincrement=True
    )
    case_id: Mapped[str] = mapped_column(
        sa.String(10),
        nullable=False,
    )
    idwf: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    resource_id: Mapped[str] = mapped_column(sa.String(1024), nullable=False)
    trigger_time: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, index=True
    )
    schedule_type: Mapped[str] = mapped_column(
        sa.String(50), nullable=False, default="timer"
    )  # 'timer', 'signal', 'conditional'
    status: Mapped[str] = mapped_column(
        sa.String(50), nullable=False, default="pending", index=True
    )  # pending / fired / canceled
    data_json: Mapped[dict | None] = mapped_column(sa.JSON(), nullable=True)
    idu: Mapped[int | None] = mapped_column(
        sa.Integer, nullable=True, index=True
    )  # User who created this schedule (null when engine-created)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        default=datetime.now(UTC),
        onupdate=datetime.now(UTC),
    )

    # Relationships — EventSchedule.case_id has no FK constraint.
    # No back-reference on the EventSchedule side to avoid ambiguity without an FK.


BpmCase.event_schedules = relationship(  # type: ignore[attr-defined]
    "EventSchedule",
    foreign_keys=[EventSchedule.case_id],
    primaryjoin="foreign(BpmCase.idcase) == EventSchedule.case_id",
)
