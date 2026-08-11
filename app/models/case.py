from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class BpmCase(Base):
    """Represents a running case instance of a BPMN workflow.

    Mirrors the legacy MongoDB `case` collection. Each case tracks the
    state of an active workflow execution — which tokens are pending,
    who initiated it, any attached data, and locking state for
    optimistic concurrency control.
    """

    __tablename__ = "bpm_cases"

    idcase: Mapped[str] = mapped_column(String(32), primary_key=True)
    idwf: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("bpm_models.idwf", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="open",
        server_default=sa.text("'open'"),
    )
    initiator_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.idu", ondelete="SET NULL"),
        index=True,
    )
    data: Mapped[dict | None] = mapped_column(sa.JSON())  # arbitrary case variables
    locked_by: Mapped[int | None] = mapped_column(Integer)
    locked_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    run_manual: Mapped[bool | None] = mapped_column(default=False, server_default="false")
    parent_json: Mapped[dict | None] = mapped_column(
        "parent", sa.JSON()  # legacy used a JSON blob; keep column name for clarity
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    # Relationships (lazy by default)
    initiator = relationship(
        "User", backref="cases_initiated", foreign_keys=[initiator_id]
    )
    model = relationship("BpmModel", back_populates="cases")
    tokens = relationship(
        "Token", back_populates="case", cascade="all, delete-orphan"
    )
