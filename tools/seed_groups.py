"""Seed initial groups (DNA² Admin and DNA² Users).

Mirrors legacy Setup.php Index() behavior for group creation.
Run: uv run python -m tools.seed_groups
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.group import Group

logger = logging.getLogger(__name__)


async def seed(db: AsyncSession) -> None:
    from config import Config

    # DNA² Admin group (idgroup=1)
    admin_group = await Group.get_by_id(db, Config.ADMIN_GROUP_ID)
    if admin_group is None:
        admin_group = Group(
            idgroup=Config.ADMIN_GROUP_ID,
            name="DNA² Admin",
            desc="System Administrators Group",
        )
        db.add(admin_group)
        logger.info("[seed] Created admin group idgroup=%d", Config.ADMIN_GROUP_ID)

    # DNA² Users group (idgroup=1000)
    default_group = await Group.get_by_id(db, 1000)
    if default_group is None:
        default_group = Group(
            idgroup=1000,
            name="DNA² Users",
            desc="Group for Regular users",
        )
        db.add(default_group)
        logger.info("[seed] Created default group idgroup=1000")

    await db.flush()


async def main() -> None:
    from extensions import async_session_factory

    async with async_session_factory() as db:
        await seed(db)
        await db.commit()
    print("[seed] Groups seeded successfully")


if __name__ == "__main__":
    asyncio.run(main())
