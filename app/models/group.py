from sqlalchemy import Integer, String, Text, func, select
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.user_group import UserGroup


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

    # Relationships
    users = relationship("UserGroup", back_populates="group")

    @classmethod
    async def get_by_name(cls, db, name: str) -> "Group | None":
        """Look up a group by name."""
        result = await db.execute(select(cls).where(cls.name == name))
        return result.scalar_one_or_none()

    @classmethod
    async def get_by_id(cls, db, idgroup: int) -> "Group | None":
        """Look up a group by ID."""
        result = await db.execute(select(cls).where(cls.idgroup == idgroup))
        return result.scalar_one_or_none()

    @classmethod
    async def count_users(cls, db, idgroup: int) -> int:
        """Count the number of users in a group."""
        result = await db.execute(
            select(func.count()).where(UserGroup.idgroup == idgroup)
        )
        return result.scalar_one() or 0

    @classmethod
    async def get_all(cls, db, order: str = "name") -> list["Group"]:
        """Return all groups ordered by the given column."""
        order_col = getattr(cls, order, cls.name)
        result = await db.execute(select(cls).order_by(order_col))
        return list(result.scalars().all())
