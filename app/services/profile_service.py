"""Profile and avatar management service."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.schemas.user import ProfileUpdate

logger = logging.getLogger(__name__)

AVATAR_DIR = Path("static/images/avatar")


class ProfileService:
    """Business logic for user profile and avatar management."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def update_profile(self, idu: int, data: ProfileUpdate) -> User | None:
        """Update profile fields for a user."""
        user = await User.get_by_id(self.db, idu)
        if user is None:
            return None
        update_data = data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(user, field, value)
        await self.db.flush()
        return user

    async def get_avatar_url(self, user: User) -> str:
        """Return avatar URL — check file storage, fallback to gravatar or default."""
        avatar_path = AVATAR_DIR / f"{user.idu}.png"
        if avatar_path.exists():
            return f"/static/images/avatar/{user.idu}.png"
        # Fallback to gravatar based on email
        if user.email:
            email_hash = hashlib.md5(user.email.strip().lower().encode()).hexdigest()
            return f"https://www.gravatar.com/avatar/{email_hash}?d=identicon"
        return "/static/images/avatar/default.png"

    async def save_avatar(self, idu: int, image_data: bytes) -> str:
        """Save avatar image to static/images/avatar/, return path."""
        AVATAR_DIR.mkdir(parents=True, exist_ok=True)
        avatar_path = AVATAR_DIR / f"{idu}.png"
        avatar_path.write_bytes(image_data)
        return f"/static/images/avatar/{idu}.png"
