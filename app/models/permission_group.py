from datetime import datetime

import sqlalchemy as sa
from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class PermissionGroup(Base):
    """Mirrors the legacy MongoDB `perm.groups` collection.

    Grants a group access to a specific path within the BPM repository
    (e.g., ``root/modules/bpm``). One row per ``(group, path)`` pair.
    """

    __tablename__ = "permission_groups"

    __table_args__ = (sa.PrimaryKeyConstraint("idgroup", "path"),)

    idgroup: Mapped[int] = mapped_column(
        Integer, ForeignKey("groups.idgroup"), primary_key=True
    )
    path: Mapped[str] = mapped_column(
        String(255), primary_key=True, nullable=False, index=True
    )
    source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime, nullable=False, server_default=sa.func.now()
    )
    updated_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
