from datetime import datetime

import sqlalchemy as sa
from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class User(Base):
    __tablename__ = "users"

    idu: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    nick: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    pass_hash: Mapped[str] = mapped_column(
        String(255), nullable=False
    )  # MongoDB 'passw' — bcrypt hash
    name: Mapped[str | None] = mapped_column(String(128))
    lastname: Mapped[str | None] = mapped_column(String(128))
    perm: Mapped[list | None] = mapped_column(
        sa.JSON()
    )  # MongoDB 'perm' — list of permission strings (e.g. ['ADM'])
    idgroup: Mapped[int | None] = mapped_column(
        Integer, index=True
    )  # MongoDB 'idgroup'
    lastacc: Mapped[datetime | None] = mapped_column(
        "last_acc", DateTime(timezone=True)
    )  # MongoDB 'lastacc' — last login timestamp
    email: Mapped[str | None] = mapped_column(String(255))
    avatar: Mapped[bytes | None] = mapped_column(sa.LargeBinary())
    token: Mapped[str | None] = mapped_column(String(255), unique=True)
    notification_by_email: Mapped[str | None] = mapped_column(
        String(10),
        nullable=True,
    )  # 'yes' or 'no' — used by inbox email notifications (legacy compat)
    signature: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)

    @property
    def last_acc(self) -> datetime | None:
        """Expose last_acc for pydantic serialization (aliases lastacc)."""
        return self.lastacc

    # Relationships
    groups = relationship("UserGroup", back_populates="user")

    @property
    def groups_list(self) -> list[str]:
        """Return the list of group names this user belongs to."""
        from app.models.group import Group

        return [
            ug.group.name
            for ug in self.groups
            if hasattr(ug, "group") and isinstance(ug.group, Group)
        ]

    async def is_admin(self, db) -> bool:
        """Check if the user belongs to the admin group."""
        from app.models.user_group import UserGroup
        from config import Config

        result = await db.execute(
            sa.select(UserGroup.idgroup).where(UserGroup.iduser == self.idu)
        )
        group_ids = [row[0] for row in result.all()]
        return Config.ADMIN_GROUP_ID in group_ids

    async def has_path(self, db, path: str) -> bool:
        """Check if any of the user's groups has access to the given path."""
        from app.models.permission_group import PermissionGroup
        from app.models.user_group import UserGroup

        result = await db.execute(
            sa.select(UserGroup.idgroup).where(UserGroup.iduser == self.idu)
        )
        group_ids = [row[0] for row in result.all()]
        if not group_ids:
            return False

        result = await db.execute(
            sa.select(PermissionGroup.id).where(
                PermissionGroup.idgroup.in_(group_ids),
                PermissionGroup.path == path,
            )
        )
        return result.scalar_one_or_none() is not None

    async def update_last_access(self, db) -> None:
        """Update the user's last access timestamp."""
        self.lastacc = datetime.now()
        db.add(self)

    @classmethod
    async def get_by_nick(cls, db, nick: str) -> "User | None":
        """Look up a user by nickname."""
        result = await db.execute(sa.select(cls).where(cls.nick == nick))
        return result.scalar_one_or_none()

    @classmethod
    async def get_by_id(cls, db, idu: int) -> "User | None":
        """Look up a user by ID."""
        result = await db.execute(sa.select(cls).where(cls.idu == idu))
        return result.scalar_one_or_none()
