"""Seed the users table with an initial admin account."""

from __future__ import annotations

import asyncio

import bcrypt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


async def seed(db: AsyncSession):
    from app.models.user import User

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

    print(f"[seed] Created admin user id={user.idu}, nick='{admin_nick}'")


async def main():
    from extensions import async_session_factory

    async with async_session_factory() as db:
        await seed(db)
        await db.commit()


if __name__ == "__main__":
    asyncio.run(main())
