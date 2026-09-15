"""Seed the users table with an initial admin account.

Also creates a UserGroup entry linking the admin user to the admin group.
Run: uv run python -m tools.seed_users
"""

from __future__ import annotations

import asyncio
import logging

import bcrypt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.models.user_group import UserGroup

logger = logging.getLogger(__name__)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


async def seed(db: AsyncSession) -> None:
    from config import Config

    admin_nick = "admin"
    admin_pass = "admin"
    admin_name = "Admin"
    admin_lastname = "User"
    admin_email = "admin@bpm.local"

    result = await db.execute(select(User).where(User.nick == admin_nick))
    existing = result.scalar_one_or_none()

    if existing is not None:
        print(
            f"[seed] User '{admin_nick}' already exists (id={existing.idu}), skipping"
        )
        return

    user = User(
        nick=admin_nick,
        pass_hash=hash_password(admin_pass),
        name=admin_name,
        lastname=admin_lastname,
        email=admin_email,
    )
    db.add(user)
    await db.flush()

    # Link admin user to admin group
    admin_group_id = Config.ADMIN_GROUP_ID
    existing_ug = await db.execute(
        select(UserGroup).where(
            UserGroup.iduser == user.idu,
            UserGroup.idgroup == admin_group_id,
        )
    )
    if existing_ug.scalar_one_or_none() is None:
        ug = UserGroup(iduser=user.idu, idgroup=admin_group_id)
        db.add(ug)

    print(f"[seed] Created admin user id={user.idu}, nick='{admin_nick}'")
    print(f"[seed] Linked to admin group idgroup={admin_group_id}")


async def main() -> None:
    from extensions import async_session_factory

    async with async_session_factory() as db:
        await seed(db)
        await db.commit()

    print("[seed] Users seeded successfully")


if __name__ == "__main__":
    asyncio.run(main())
