from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool

from config import Config


class Base(DeclarativeBase):
    """Declarative base for all SQLAlchemy models.

    Exposes ``metadata`` for Alembic autogenerate and provides the standard
    ``query``, ``insert``, etc. classmethods from DeclarativeBase.
    """


def _build_database_url() -> str:
    """Return the database URL, translating SQLite to use aiosqlite if needed."""
    url = Config.SQLALCHEMY_DATABASE_URI
    if url.startswith("sqlite:///"):
        return url.replace("sqlite:///", "sqlite+aiosqlite://", 1)
    return url


# -- Synchronous engine/session (used by Alembic migrations) -- #

_sync_url = _build_database_url()
_sync_engine = create_engine(
    _sync_url,
    echo=Config.SQLALCHEMY_ECHO if hasattr(Config, "SQLALCHEMY_ECHO") else False,
)

sync_session_factory = sessionmaker(bind=_sync_engine, class_=Session)


# -- Async engine/session (used by FastAPI async endpoints) -- #

_async_url = _build_database_url()
_async_engine = create_async_engine(
    _async_url,
    echo=Config.SQLALCHEMY_ECHO if hasattr(Config, "SQLALCHEMY_ECHO") else False,
    poolclass=StaticPool if "sqlite" in _async_url else None,
)

async_session_factory = async_sessionmaker(
    bind=_async_engine, class_=AsyncSession, expire_on_commit=False
)


async def get_async_db() -> AsyncSession:  # type: ignore[misc]
    """FastAPI dependency that yields an async DB session."""
    async with async_session_factory() as session:
        try:
            yield session
        finally:
            await session.close()
