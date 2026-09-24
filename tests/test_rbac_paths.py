"""Integration tests for RBAC paths endpoint (PUT /rbac/paths)."""

import uuid
from pathlib import Path

import bcrypt
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.base import Base as _ModelBase
from app.models.group import Group
from app.models.user import User
from extensions import get_async_db

project_root = Path(__file__).parent.parent


@pytest.fixture(scope="function", autouse=True)
async def setup_test_db():
    """Create tables in a per-test SQLite for each test function."""
    db_path = f"sqlite+aiosqlite:///test_{uuid.uuid4().hex}.db"
    db_file = Path(db_path.split("///")[1])
    engine = create_async_engine(db_path, echo=False)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession)

    async with engine.begin() as conn:
        await conn.run_sync(_ModelBase.metadata.create_all)

    # Seed default admin user (admin/admin).
    pw_hash = bcrypt.hashpw(b"admin", bcrypt.gensalt()).decode("utf-8")
    async with factory() as seed_session:
        admin = User(
            idgroup=1,
            nick="admin",
            pass_hash=pw_hash,
            email="admin@example.com",
        )
        seed_session.add(admin)

        # Seed admin group (idgroup=1)
        admin_group = Group(
            idgroup=1, name="DNA² Admin", desc="System Administrators Group"
        )
        seed_session.add(admin_group)

        # Seed default user group (idgroup=1000)
        user_group = Group(
            idgroup=1000, name="DNA² Users", desc="Group for Regular users"
        )
        seed_session.add(user_group)

        await seed_session.commit()

    yield {"engine": engine, "factory": factory}

    if db_file.exists():
        db_file.unlink()


@pytest.fixture
async def test_client(setup_test_db):
    """Create an httpx AsyncClient with dependency overrides for test DB."""
    from main import app

    db_info = setup_test_db

    class _TestDbGenerator:
        def __init__(self, factory):
            self._factory = factory

        async def __aiter__(self):
            async with self._factory() as session:
                try:
                    yield session
                finally:
                    if session.in_transaction():
                        await session.rollback()

    async def override_get_async_db():
        gen = _TestDbGenerator(db_info["factory"])
        async for session in gen:
            yield session

    app.dependency_overrides[get_async_db] = override_get_async_db

    import extensions as _ext

    _ext.get_async_db = override_get_async_db
    _ext.async_session_factory.kw["bind"] = db_info["engine"]

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        try:
            yield client
        finally:
            app.dependency_overrides.clear()


@pytest.fixture
async def auth_headers(test_client):
    """Get authentication headers by logging in as admin."""
    response = await test_client.post(
        "/api/v1/auth/token", data={"username": "admin", "password": "admin"}
    )
    assert response.status_code == 200, f"Login failed: {response.text}"
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def seeded_group(test_client, setup_test_db):
    """Seed a test group and return its idgroup."""
    factory = setup_test_db["factory"]
    async with factory() as db:
        group = Group(idgroup=9999, name="Test Group", desc="Test group for RBAC paths")
        db.add(group)
        await db.commit()
    return 9999


# -- Tests -------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_put_paths_success(test_client, auth_headers, seeded_group):
    """PUT /rbac/paths with valid JSON body saves paths and returns them."""
    paths = ["root/bpm", "root/bpm/case_manager", "root/bpm/engine"]
    resp = await test_client.put(
        "/rbac/paths",
        json={"idgroup": seeded_group, "paths": paths, "source": "api"},
        headers=auth_headers,
    )
    assert resp.status_code == 200, f"Unexpected response: {resp.text}"
    data = resp.json()
    assert set(data["paths"]) == set(paths)


@pytest.mark.asyncio
async def test_put_paths_empty_list(test_client, auth_headers, seeded_group):
    """PUT /rbac/paths with empty paths list clears all paths."""
    # First add a path
    await test_client.put(
        "/rbac/paths",
        json={"idgroup": seeded_group, "paths": ["root/bpm"], "source": "api"},
        headers=auth_headers,
    )
    # Then clear with empty list
    resp = await test_client.put(
        "/rbac/paths",
        json={"idgroup": seeded_group, "paths": [], "source": "api"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["paths"] == []


@pytest.mark.asyncio
async def test_put_paths_no_auth(test_client):
    """PUT /rbac/paths without auth returns 401."""
    resp = await test_client.put(
        "/rbac/paths",
        json={"idgroup": 1, "paths": ["root/bpm"]},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_put_paths_invalid_body_missing_idgroup(test_client, auth_headers):
    """PUT /rbac/paths with missing idgroup returns 422."""
    resp = await test_client.put(
        "/rbac/paths",
        json={"paths": ["root/bpm"]},
        headers=auth_headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_put_paths_invalid_body_missing_paths(test_client, auth_headers):
    """PUT /rbac/paths with missing paths returns 422."""
    resp = await test_client.put(
        "/rbac/paths",
        json={"idgroup": 1},
        headers=auth_headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_put_paths_idempotent(test_client, auth_headers, seeded_group):
    """PUT /rbac/paths with same paths twice is idempotent."""
    paths = ["root/bpm", "root/bpm/case_manager"]
    resp1 = await test_client.put(
        "/rbac/paths",
        json={"idgroup": seeded_group, "paths": paths, "source": "api"},
        headers=auth_headers,
    )
    assert resp1.status_code == 200

    resp2 = await test_client.put(
        "/rbac/paths",
        json={"idgroup": seeded_group, "paths": paths, "source": "api"},
        headers=auth_headers,
    )
    assert resp2.status_code == 200
    assert resp2.json()["paths"] == paths
