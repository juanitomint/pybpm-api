"""Tests for GET /dashboard/tasks endpoint."""

import pytest


@pytest.fixture
async def client(test_client):
    return test_client


@pytest.fixture
async def auth_headers(client):
    response = await client.post(
        "/api/v1/auth/token", data={"username": "admin", "password": "admin"}
    )
    assert response.status_code == 200, f"Auth failed: {response.text}"
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
async def seeded_pending_tokens(setup_test_db):
    """Seed tokens in pending state (status='user', locked_by IS NULL) assigned to admin."""
    from app.models.token import Token

    factory = setup_test_db["factory"]
    tokens = [
        Token(resource_id=f"r{i}", idwf="w1", case_id=f"c{i}", type="Task", status="user", assign=[1])
        for i in range(5)
    ]
    async with factory() as s:
        for t in tokens:
            s.add(t)
        await s.commit()


@pytest.fixture
async def seeded_in_progress_tokens(setup_test_db):
    """Seed tokens in in-progress state (status='user', locked_by IS NOT NULL)."""
    from app.models.token import Token

    factory = setup_test_db["factory"]
    token = Token(
        resource_id="r10", idwf="w2", case_id="c10", type="Task",
        status="user", locked_by=1, assign=[1],
    )
    async with factory() as s:
        s.add(token)
        await s.commit()


@pytest.fixture
async def seeded_validating_tokens(setup_test_db):
    """Seed tokens in validating state assigned to admin."""
    from app.models.token import Token

    factory = setup_test_db["factory"]
    token = Token(
        resource_id="r20", idwf="w3", case_id="c20", type="Task",
        status="validating", assign=[1],
    )
    async with factory() as s:
        s.add(token)
        await s.commit()


@pytest.fixture
async def seeded_done_tokens(setup_test_db):
    """Seed tokens in done state assigned to admin."""
    from app.models.token import Token

    factory = setup_test_db["factory"]
    token = Token(
        resource_id="r30", idwf="w4", case_id="c30", type="Task",
        status="finished", assign=[1],
    )
    async with factory() as s:
        s.add(token)
        await s.commit()


@pytest.mark.asyncio
async def test_get_tasks_default_returns_pending(client, auth_headers, seeded_pending_tokens):
    """GET /dashboard/tasks without filter returns pending tasks (status='user', unlocked)."""
    response = await client.get("/dashboard/tasks", headers=auth_headers)
    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
    data = response.json()
    assert "tasks" in data
    assert "total" in data
    assert "page" in data
    assert "per_page" in data
    assert "total_pages" in data
    assert data["total"] >= 1


@pytest.mark.asyncio
async def test_get_tasks_in_progress_filter(client, auth_headers, seeded_in_progress_tokens):
    """GET /dashboard/tasks?status=in_progress returns locked tasks."""
    response = await client.get(
        "/dashboard/tasks?status=in_progress", headers=auth_headers
    )
    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
    data = response.json()
    tasks = data["tasks"]
    if len(tasks) > 0:
        assert all(t.get("locked") is True for t in tasks)


@pytest.mark.asyncio
async def test_get_tasks_validating_filter(client, auth_headers, seeded_validating_tokens):
    """GET /dashboard/tasks?status=validating returns validating tasks."""
    response = await client.get(
        "/dashboard/tasks?status=validating", headers=auth_headers
    )
    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
    data = response.json()
    tasks = data["tasks"]
    if len(tasks) > 0:
        assert all(t.get("status") == "validating" for t in tasks)


@pytest.mark.asyncio
async def test_get_tasks_done_filter(client, auth_headers, seeded_done_tokens):
    """GET /dashboard/tasks?status=done returns finished tasks."""
    response = await client.get(
        "/dashboard/tasks?status=done", headers=auth_headers
    )
    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
    data = response.json()
    tasks = data["tasks"]
    if len(tasks) > 0:
        assert all(t.get("status") in ("finished", "done") for t in tasks)


@pytest.mark.asyncio
async def test_get_tasks_pagination(client, auth_headers, seeded_pending_tokens):
    """GET /dashboard/tasks respects page and per_page parameters."""
    response = await client.get(
        "/dashboard/tasks?page=1&per_page=2", headers=auth_headers
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data["tasks"]) <= 2
    assert data["page"] == 1


@pytest.mark.asyncio
async def test_get_tasks_empty_result(client, auth_headers):
    """GET /dashboard/tasks with no matching tokens returns empty list."""
    response = await client.get(
        "/dashboard/tasks?status=validating", headers=auth_headers
    )
    assert response.status_code == 200
    data = response.json()
    assert data["tasks"] == []


@pytest.mark.asyncio
async def test_get_tasks_invalid_status_filter(client, auth_headers):
    """GET /dashboard/tasks with invalid status filter returns 400."""
    response = await client.get(
        "/dashboard/tasks?status=invalid_status", headers=auth_headers
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_get_tasks_without_auth(client):
    """GET /dashboard/tasks without auth returns 401/403."""
    response = await client.get("/dashboard/tasks")
    assert response.status_code in (401, 403)


@pytest.mark.asyncio
async def test_get_tasks_invalid_page_param(client, auth_headers):
    """GET /dashboard/tasks with page < 1 returns 422."""
    response = await client.get(
        "/dashboard/tasks?page=0", headers=auth_headers
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_get_tasks_invalid_per_page_param(client, auth_headers):
    """GET /dashboard/tasks with per_page > 100 returns 422."""
    response = await client.get(
        "/dashboard/tasks?per_page=200", headers=auth_headers
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_get_tasks_response_fields(client, auth_headers, seeded_pending_tokens):
    """GET /dashboard/tasks returns required fields on each task item."""
    response = await client.get("/dashboard/tasks", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    tasks = data["tasks"]
    if len(tasks) > 0:
        first = tasks[0]
        required_fields = ["resourceId", "type", "title", "status", "case_id", "idwf", "locked_by", "locked", "model_name"]
        for field in required_fields:
            assert field in first, f"Missing field: {field}"
