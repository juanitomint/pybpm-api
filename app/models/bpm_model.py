from datetime import datetime
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy import DateTime, ForeignKey, SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.models.base import Base

SVG_DIR = Path(__file__).parent.parent.parent / "static" / "svg"


class BpmModel(Base):
    __tablename__ = "bpm_models"

    idwf: Mapped[str] = mapped_column(String(255), primary_key=True)
    folder: Mapped[str] = mapped_column(String(255), nullable=False, default="General")
    version: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    data: Mapped[dict | None] = mapped_column(sa.JSON())  # BPMN stencil data (JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.idu"))

    author = relationship("User", backref="models", foreign_keys=[created_by])
    cases = relationship("BpmCase", back_populates="model")

    @property
    def svg_path(self) -> Path:
        """Reconstruct SVG file path from idwf. No DB column needed."""
        return SVG_DIR / f"{self.idwf}.svg"
