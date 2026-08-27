"""Test fixtures and setup for pybpm-api tests.

Uses in-memory SQLite with per-test table creation. Each test function creates its
own tables; isolation is achieved by using a fresh session per request via the
test client's dependency override.
"""

import sys
import uuid
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Import models so they register with _ModelBase.metadata before create_all runs.
from app.models import (
    Token,
    User,
)
from app.models.base import Base as _ModelBase
from extensions import get_async_db

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


@pytest.fixture(scope="function", autouse=True)
async def setup_test_db():
    """Create tables in an in-memory SQLite for each test function.

    Seeds a default admin user (admin/admin) so auth-dependent tests can log in.
    Uses bcrypt directly (matching production app/api/auth.py).
    """
    import bcrypt as _bcrypt

    # Unique per-test SQLite file to avoid collisions when loops share addresses.
    db_path = f"sqlite+aiosqlite:///test_{uuid.uuid4().hex}.db"
    db_file = Path(db_path.split("///")[1])
    engine = create_async_engine(db_path, echo=False)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession)

    async with engine.begin() as conn:
        await conn.run_sync(_ModelBase.metadata.create_all)

    # Seed default admin user (admin/admin).
    pw_hash = _bcrypt.hashpw(b"admin", _bcrypt.gensalt()).decode("utf-8")
    async with factory() as seed_session:
        admin = User(
            nick="admin",
            pass_hash=pw_hash,
            name="Admin",
            lastname="User",
            perm=["ADM"],
            idgroup=1,
            email="admin@localhost",
        )
        seed_session.add(admin)
        await seed_session.commit()

    yield {"engine": engine, "factory": factory}

    # Clean up test database file
    if db_file.exists():
        db_file.unlink()


@pytest.fixture
async def test_client(setup_test_db):
    """Create a TestClient using per-request session isolation.

    Patches get_async_db both as a FastAPI dependency override AND at the module
    level so inbox.py's direct calls (which import it once at load time) also use
    the test engine instead of production Postgres. Also patches dashboard's
    _get_db which uses its own local import from extensions.
    """
    from main import app

    db_info = setup_test_db

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
        gen = _TestDbGenerator(db_info["factory"])
        async for session in gen:
            yield session

    async def override_dashboard_get_db():  # type: ignore[misc]
        gen = _TestDbGenerator(db_info["factory"])
        async for session in gen:
            yield session

    # Patch FastAPI dependency injection (for Depends-based endpoints).
    app.dependency_overrides[get_async_db] = override_get_async_db

    # Also patch dashboard's _get_db which uses its own import.
    from app.api.dashboard import _get_db as _dashboard_get_db

    app.dependency_overrides[_dashboard_get_db] = override_dashboard_get_db

    # Patch at module level so inbox.py's direct calls use test engine.
    import extensions as _ext

    _ext.get_async_db = override_get_async_db
    # Also patch async_session_factory.kw['bind'] so _assign_contains (dashboard)
    # detects the SQLite test engine instead of production PostgreSQL.
    _ext.async_session_factory.kw["bind"] = db_info["engine"]
    import app.api.inbox as _inbox_mod

    _inbox_mod.get_async_db = override_get_async_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        try:
            yield client
        finally:
            app.dependency_overrides.clear()


@pytest.fixture
async def seed_token(setup_test_db):
    """Seed a Token row in the test DB so lock/unlock endpoints have something to find.

    Creates its own session within the same event loop as setup_test_db (which is
    also function-scoped, so it shares the running loop).
    """

    factory = setup_test_db["factory"]
    token = Token(resource_id="r1", idwf="w1", case_id="c1", type="Task", assign=[1])
    async with factory() as s:
        s.add(token)
        await s.commit()
    return token
