from sqlalchemy import ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class UserGroup(Base):
    """Association table linking users to groups.

    Mirrors the PostgreSQL ``users_groups`` junction table that provides
    a many-to-many relationship between :class:`User` and :class:`Group`.
    Unlike MongoDB (which stored group IDs as an array on each user),
    this normalized design allows users to belong to multiple groups
    without JSON serialization.
    """

    __tablename__ = "users_groups"

    iduser: Mapped[int] = mapped_column(
        Integer(), ForeignKey("users.idu"), primary_key=True
    )
    idgroup: Mapped[int] = mapped_column(
        Integer(), ForeignKey("groups.idgroup"), primary_key=True
    )
