"""Group management service."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.group import Group
from app.schemas.user import GroupCreate, GroupUpdate


class GroupService:
    """Business logic for group management."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_group(self, idgroup: int) -> Group | None:
        """Look up a group by ID."""
        return await Group.get_by_id(self.db, idgroup)

    async def get_group_by_name(self, name: str) -> Group | None:
        """Look up a group by name."""
        return await Group.get_by_name(self.db, name)

    async def get_groups(
        self,
        query: str | None = None,
        page: int = 1,
        start: int = 0,
        limit: int = 25,
        sort: str | None = None,
    ) -> tuple[list[Group], int]:
        """Return groups with optional name search, pagination, and sorting.

        Args:
            query: name search (ILIKE).
            page: 1-based page number.
            start: 0-based offset.
            limit: page size.
            sort: column name to order by (default: "name").
        """
        order = sort or "name"
        base_query = select(Group)
        if query:
            like = f"%{query}%"
            base_query = base_query.where(Group.name.ilike(like))
        base_query = base_query.order_by(getattr(Group, order, Group.name))

        # Count total
        count_query = select(func.count()).select_from(base_query.subquery())
        count_result = await self.db.execute(count_query)
        total = count_result.scalar()

        # Paginate
        query = base_query.offset(start).limit(limit)
        result = await self.db.execute(query)
        groups = list(result.scalars().all())
        return groups, total

    async def create_group(self, data: GroupCreate) -> Group:
        """Create a new group."""
        group = Group(
            name=data.name,
            desc=data.desc,
            idsup=data.idsup,
        )
        self.db.add(group)
        await self.db.flush()
        return group

    async def update_group(self, idgroup: int, data: GroupUpdate) -> Group | None:
        """Update group fields (only non-None fields)."""
        group = await self.get_group(idgroup)
        if group is None:
            return None
        update_data = data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(group, field, value)
        await self.db.flush()
        return group

    async def delete_group(self, idgroup: int) -> bool:
        """Delete a group."""
        group = await self.get_group(idgroup)
        if group is None:
            return False
        await self.db.delete(group)
        await self.db.flush()
        return True

    async def count_users_in_group(self, idgroup: int) -> int:
        """Count users in a group."""
        return await Group.count_users(self.db, idgroup)
