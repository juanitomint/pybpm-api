import sqlalchemy as sa
from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class PermissionRepository(Base):
    """Mirrors the legacy MongoDB `perm.repository` collection.

    Tracks repository-level permissions with audit metadata (source of
    the permission entry and when it was last checked). Unlike
    ``PermissionGroup`` which is group-scoped, this table represents
    permissions at the repository level without a specific group binding.
    """

    __tablename__ = "permission_repository"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    path: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True
    )  # resource path
    source: Mapped[str | None] = mapped_column(
        String(64)
    )  # MongoDB 'properties.source' (e.g. 'Setup')
    check_date: Mapped[sa.DateTime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )  # MongoDB 'properties.checkdate'
