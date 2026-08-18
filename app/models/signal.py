"""Signal persistence — global signal events stored for cross-case / cross-model matching.

Signals are thrown by end events (EndSignalEvent) or intermediate throwing
events (IntermediateSignalEventThrowing). They persist as data rows so any
matching catcher can discover them later, enabling cross-case / cross-model
signal communication between BPMN cases.
"""

from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class Signal(Base):
    """Represents a persistent global signal event."""

    __tablename__ = "signals"

    idsignal: Mapped[int] = mapped_column(
        sa.Integer, primary_key=True, autoincrement=True
    )
    name: Mapped[str] = mapped_column(sa.String(255), nullable=False, index=True)
    case_id: Mapped[str | None] = mapped_column(
        sa.String(10),
        sa.ForeignKey("cases.idcase"),
        nullable=True,  # global signals have no case context
    )
    idwf: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    data_json: Mapped[dict | None] = mapped_column(sa.JSON(), nullable=True)

    # Relationships
    case = relationship("BpmCase", backref="signals_thrown")


# Ensure BpmCase has the one-to-many relationship. Added here to avoid circular imports at module level.
from app.models.case import BpmCase  # noqa: E402 — intentionally late import

BpmCase.signals_thrown = relationship(  # type: ignore[attr-defined]
    "Signal",
    backref="thrower_case",
    cascade="all, delete-orphan",
)
