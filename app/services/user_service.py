"""User management service."""

from __future__ import annotations

import logging

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.schemas.user import UserCreate, UserUpdate

logger = logging.getLogger(__name__)


class UserService:
    """Business logic for user management."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_user(self, idu: int) -> User | None:
        """Look up a user by ID."""
        result = await self.db.execute(select(User).where(User.idu == idu))
        return result.scalar_one_or_none()

    async def get_user_by_nick(self, nick: str) -> User | None:
        """Look up a user by nickname."""
        result = await self.db.execute(select(User).where(User.nick == nick))
        return result.scalar_one_or_none()

    async def get_user_by_email(self, email: str) -> User | None:
        """Look up a user by email."""
        result = await self.db.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    async def get_users(
        self,
        skip: int = 0,
        limit: int = 50,
        query: str | None = None,
        idgroup: int | None = None,
    ) -> tuple[list[User], int]:
        """Paginated user list with optional search and group filter."""
        # Count query
        count_query = select(User)
        if query:
            like = f"%{query}%"
            count_query = count_query.where(
                or_(
                    User.nick.ilike(like),
                    User.name.ilike(like),
                    User.lastname.ilike(like),
                    User.email.ilike(like),
                )
            )
        if idgroup is not None:
            count_query = count_query.where(User.idgroup == idgroup)
        count_result = await self.db.execute(count_query)
        total = len(count_result.all())

        # Data query
        data_query = select(User)
        if query:
            like = f"%{query}%"
            data_query = data_query.where(
                or_(
                    User.nick.ilike(like),
                    User.name.ilike(like),
                    User.lastname.ilike(like),
                    User.email.ilike(like),
                )
            )
        if idgroup is not None:
            data_query = data_query.where(User.idgroup == idgroup)
        data_query = data_query.offset(skip).limit(limit)
        result = await self.db.execute(data_query)
        return list(result.scalars().all()), total

    async def get_user_count(
        self, query: str | None = None, idgroup: int | None = None
    ) -> int:
        """Return total user count with optional filters."""
        _, total = await self.get_users(skip=0, limit=1, query=query, idgroup=idgroup)
        return total

    async def create_user(self, data: UserCreate) -> User:
        """Create a new user."""
        user = User(
            nick=data.nick,
            name=data.name,
            lastname=data.lastname,
            email=data.email,
            idgroup=data.idgroup,
            notification_by_email=data.notification_by_email,
        )
        self.db.add(user)
        await self.db.flush()
        return user

    async def delete_user(self, idu: int) -> bool:
        """Hard-delete a user (matching legacy behavior)."""
        user = await self.get_user(idu)
        if user is None:
            return False
        await self.db.delete(user)
        await self.db.flush()
        return True

    async def update_user(self, idu: int, data: UserUpdate) -> User | None:
        """Update user fields (only non-None fields)."""
        user = await self.get_user(idu)
        if user is None:
            return None
        update_data = data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(user, field, value)
        await self.db.flush()
        return user

    async def is_admin(self, user: User) -> bool:
        """Delegate to user.is_admin()."""
        return await user.is_admin(self.db)
