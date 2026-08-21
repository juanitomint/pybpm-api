from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Group(Base):
    """Represents a user group.

    Mirrors the legacy MongoDB `groups` collection. Groups are used for
    RBAC — each user belongs to one or more groups, and permissions
    are granted per-group per-path.
    """

    __tablename__ = "groups"

    idgroup: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    desc: Mapped[str | None] = mapped_column(
        Text()
    )  # MongoDB 'desc' — group description
    idsup: Mapped[str | None] = mapped_column(
        String(255)
    )  # MongoDB 'idsup' — supervisor group reference
