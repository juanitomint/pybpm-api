"""Tests for /dashboard/tasks/lock and /dashboard/tasks/unlock endpoints."""

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
async def seeded_token_with_assign(setup_test_db):
    """Seed a token whose assign list does NOT include admin (idu=1)."""
    from app.models.token import Token

    factory = setup_test_db["factory"]
    # assign=[999] — admin user has idu=1, so they're not assigned.
    token = Token(resource_id="r2", idwf="w2", case_id="c1", type="Task", assign=[999])
    async with factory() as s:
        s.add(token)
        await s.commit()


# Lock/unlock URL template — params are path segments, not body fields.
LOCK_URL = "/dashboard/tasks/lock/{resource_id}/{case_id}/{idwf}"
UNLOCK_URL = "/dashboard/tasks/unlock/{resource_id}/{case_id}/{idwf}"

_OK_PAYLOAD = {"resource_id": "r1", "idwf": "w1", "case_id": "c1"}


@pytest.mark.asyncio
async def test_lock_task_success(client, auth_headers, seed_token):
    """PATCH /dashboard/tasks/lock/{rid}/{cid}/{idwf} sets locked_by on an existing token."""
    url = LOCK_URL.format(**_OK_PAYLOAD)
    response = await client.patch(url, headers=auth_headers)
    assert (
        response.status_code == 200
    ), f"Expected 200, got {response.status_code}: {response.text}"
    data = response.json()
    assert data["resourceId"] == "r1"
    assert data["idwf"] == "w1"
    assert data["locked_by"] is not None


@pytest.mark.asyncio
async def test_unlock_task_success(client, auth_headers, seed_token):
    """PATCH /dashboard/tasks/unlock clears locked_by when caller holds the lock and is assigned.

    Requires Token.locked_by == current user's idu AND caller in token.assign list.
    """
    url = LOCK_URL.format(**_OK_PAYLOAD)
    lock_resp = await client.patch(url, headers=auth_headers)
    assert lock_resp.status_code == 200

    url = UNLOCK_URL.format(**_OK_PAYLOAD)
    response = await client.patch(url, headers=auth_headers)
    assert (
        response.status_code == 200
    ), f"Expected 200, got {response.status_code}: {response.text}"
    data = response.json()
    assert data["resourceId"] == "r1"
    assert data["idwf"] == "w1"
    assert data["locked_by"] is None


@pytest.mark.asyncio
async def test_lock_nonexistent_token(client, auth_headers):
    """PATCH /dashboard/tasks/lock on missing token returns 404."""
    url = LOCK_URL.format(resource_id="nonexistent", idwf="w999", case_id="c999")
    response = await client.patch(url, headers=auth_headers)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_unlock_nonexistent_token(client, auth_headers):
    """PATCH /dashboard/tasks/unlock on missing token returns 404."""
    url = UNLOCK_URL.format(resource_id="nonexistent", idwf="w999", case_id="c999")
    response = await client.patch(url, headers=auth_headers)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_lock_without_auth(client):
    """PATCH /dashboard/tasks/lock without token returns 401."""
    url = LOCK_URL.format(**_OK_PAYLOAD)
    response = await client.patch(url)
    assert response.status_code in (401, 403)


@pytest.mark.asyncio
async def test_unlock_without_auth(client):
    """PATCH /dashboard/tasks/unlock without token returns 401."""
    url = UNLOCK_URL.format(**_OK_PAYLOAD)
    response = await client.patch(url)
    assert response.status_code in (401, 403)


@pytest.mark.asyncio
async def test_lock_invalid_path_format(client, auth_headers):
    """PATCH /dashboard/tasks/lock with malformed path returns 404 (not 422)."""
    response = await client.patch(
        "/dashboard/tasks/lock/not-a-valid-path", headers=auth_headers
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_unlock_invalid_path_format(client, auth_headers):
    """PATCH /dashboard/tasks/unlock with malformed path returns 404 (not 422)."""
    response = await client.patch(
        "/dashboard/tasks/unlock/not-a-valid-path", headers=auth_headers
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_lock_unlock_sequence(client, auth_headers, seed_token):
    """Lock then unlock a token — locked_by goes from set to None."""
    url = LOCK_URL.format(**_OK_PAYLOAD)
    lock_resp = await client.patch(url, headers=auth_headers)
    assert lock_resp.status_code == 200
    assert lock_resp.json()["locked_by"] is not None

    url = UNLOCK_URL.format(**_OK_PAYLOAD)
    unlock_resp = await client.patch(url, headers=auth_headers)
    assert unlock_resp.status_code == 200
    assert unlock_resp.json()["locked_by"] is None


@pytest.mark.asyncio
async def test_unlock_not_assigned_fails(
    client, auth_headers, seeded_token_with_assign
):
    """PATCH /dashboard/tasks/unlock on a token not assigned to the caller returns 404.

    The token has assign=[999] but admin user has idu=1, so _assign_contains(1) fails —
    even if locked_by somehow matched, unlock must be denied for unassigned users.
    """
    url = UNLOCK_URL.format(resource_id="r2", idwf="w2", case_id="c1")
    response = await client.patch(url, headers=auth_headers)
    assert response.status_code == 404
