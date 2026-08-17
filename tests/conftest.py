"""Test fixtures and setup for pybpm-api tests.

Uses in-memory SQLite with per-test table creation. Each test function creates its
own tables; isolation is achieved by using a fresh session per request via the
test client's dependency override.
"""

import asyncio
import sys
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy import text

# Import models so they register with _ModelBase.metadata before create_all runs.
from app.models import (  # noqa: F401 — side-effect only; register tables
    BpmCase, BpmModel, Group, Message, PermissionGroup,
    PermissionRepository, Token, TokenHistory, User, UserGroup,
)
from app.models.base import Base as _ModelBase
from extensions import get_async_db


# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


class _State:
    """Holds the test DB engine and session factory across fixtures."""
    _engine = None
    _factory = None


_state = _State()


@pytest.fixture(scope="function", autouse=True)
async def setup_test_db():
    """Create tables in an in-memory SQLite for each test function.

    Seeds a default admin user (admin/admin) so auth-dependent tests can log in.
    Uses bcrypt directly (matching production app/api/auth.py).
    """
    import bcrypt as _bcrypt

    _url = "sqlite+aiosqlite:///:memory:"
    engine = create_async_engine(_url, echo=False)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession)

    async with engine.begin() as conn:
        await conn.run_sync(_ModelBase.metadata.create_all)

    # Seed default admin user (admin/admin).
    pw_hash = _bcrypt.hashpw(b"admin", _bcrypt.gensalt()).decode("utf-8")
    async with factory() as seed_session:
        admin = User(
            nick="admin", pass_hash=pw_hash, name="Admin", lastname="User",
            perm=["ADM"], idgroup=1, email="admin@localhost",
        )
        seed_session.add(admin)
        await seed_session.commit()

    _state._engine = engine
    _state._factory = factory

    yield

    await engine.dispose()
    _state._engine = None
    _state._factory = None


@pytest.fixture
async def test_client(setup_test_db):
    """Create a TestClient using per-request session isolation.

    Patches get_async_db both as a FastAPI dependency override AND at the module
    level so inbox.py's direct calls (which import it once at load time) also use
    the test engine instead of production Postgres.
    """
    from main import app


    class _TestDbGenerator:
        def __init__(self, factory):
            self._factory = factory

        async def __aiter__(self):  # type: ignore[misc]
            async with self._factory() as session:
                try:
                    yield session
                finally:
                    if session.in_transaction():
                        await session.rollback()


    async def override_get_async_db():  # type: ignore[misc]
        gen = _TestDbGenerator(_state._factory)
        async for session in gen:
            yield session

    # Patch FastAPI dependency injection (for Depends-based endpoints).
    app.dependency_overrides[get_async_db] = override_get_async_db

    # Also patch at module level so inbox.py's direct calls use test engine.
    import extensions as _ext
    _ext.get_async_db = override_get_async_db
    import app.api.inbox as _inbox_mod
    _inbox_mod.get_async_db = override_get_async_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        try:
            yield client
        finally:
            app.dependency_overrides.clear()

