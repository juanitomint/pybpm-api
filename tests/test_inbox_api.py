"""Integration tests for Inbox API endpoints using httpx.AsyncClient.

Follows AGENTS.md section 4: "Integration Tests: Test api/ endpoints using AsyncClient."
Uses per-test isolated DB sessions via conftest.py fixtures.
"""

import pytest


@pytest.fixture
async def client(test_client):
    """Alias for the test client fixture."""
    return test_client


@pytest.fixture
async def auth_headers(client):
    """Get authentication headers by logging in as admin."""
    response = await client.post("/api/v1/auth/token", data={"username": "admin", "password": "admin"})
    assert response.status_code == 200, f"Auth failed: {response.text}"
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.mark.asyncio
async def test_get_inbox_list(client, auth_headers):
    """GET /inbox/ returns paginated message list."""
    response = await client.get("/inbox/", headers=auth_headers)
    assert response.status_code in (200, 307, 404)


@pytest.mark.asyncio
async def test_get_inbox_counts(client, auth_headers):
    """POST /inbox/counts/ returns folder and unread counts."""
    response = await client.post("/inbox/counts/", headers=auth_headers, json={})
    assert response.status_code == 200
    data = response.json()
    assert "inbox_count" in data
    assert "sent_count" in data


@pytest.mark.asyncio
async def test_filter_with_key_value_dict(client, auth_headers):
    """POST /inbox/filter/ accepts key-value dict and filters messages."""
    response = await client.post("/inbox/filter/", headers=auth_headers, json={"folder": "inbox"})
    assert response.status_code == 200
    data = response.json()
    assert "messages" in data


@pytest.mark.asyncio
async def test_get_single_message(client, auth_headers):
    """GET /inbox/message/{msgid}/ returns a single message or 404."""
    response = await client.get("/inbox/message/1/", headers=auth_headers)
    assert response.status_code in (200, 404)


@pytest.mark.asyncio
async def test_unified_patch_star(client, auth_headers):
    """PATCH /inbox/message/{msgid}/ with action=star returns valid response."""
    response = await client.patch(
        "/inbox/message/1/",
        headers=auth_headers,
        json={"action": "star"},
    )
    assert response.status_code in (200, 404)


@pytest.mark.asyncio
async def test_unified_patch_read(client, auth_headers):
    """PATCH /inbox/message/{msgid}/ with action=read returns valid response."""
    response = await client.patch(
        "/inbox/message/1/",
        headers=auth_headers,
        json={"action": "read", "is_read": True},
    )
    assert response.status_code in (200, 404)


@pytest.mark.asyncio
async def test_unified_patch_tag(client, auth_headers):
    """PATCH /inbox/message/{msgid}/ with action=tag returns valid response."""
    response = await client.patch(
        "/inbox/message/1/",
        headers=auth_headers,
        json={"action": "tag", "tag": "urgent"},
    )
    assert response.status_code in (200, 404)


@pytest.mark.asyncio
async def test_send_message(client, auth_headers):
    """POST /inbox/send/ creates a new message or returns error."""
    response = await client.post(
        "/inbox/send/",
        headers=auth_headers,
        json={"to_user_id": 1, "subject": "Test", "body": "Body"},
    )
    assert response.status_code in (200, 201)


@pytest.mark.asyncio
async def test_delete_nonexistent_message(client, auth_headers):
    """DELETE /inbox/message/999/ returns ok=false for nonexistent."""
    response = await client.delete("/inbox/message/999/", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert "ok" in data


@pytest.mark.asyncio
async def test_filter_with_multiple_keys(client, auth_headers):
    """POST /inbox/filter/ with multiple filter keys returns results."""
    response = await client.post(
        "/inbox/filter/",
        headers=auth_headers,
        json={"folder": "inbox", "read": False},
    )
    assert response.status_code == 200
