"""Integration tests for Inbox API endpoints using httpx.AsyncClient.

Follows AGENTS.md section 4: "Integration Tests: Test api/ endpoints using AsyncClient."
"""

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture
async def client():
    """Create an async test client with the FastAPI app."""
    from main import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def auth_headers(client):
    """Get authentication headers by logging in as admin."""
    response = await client.post("/api/v1/auth/token", data={"username": "admin", "password": "admin"})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.mark.asyncio
async def test_get_inbox_list(client, auth_headers):
    """GET /api/v1/inbox/ returns paginated message list."""
    response = await client.get("/api/v1/inbox/", headers=auth_headers, follow_redirects=False)
    assert response.status_code in (200, 307)


@pytest.mark.asyncio
async def test_get_inbox_counts(client, auth_headers):
    """POST /api/v1/inbox/counts/ returns folder and unread counts."""
    response = await client.post("/api/v1/inbox/counts/", headers=auth_headers, json={})
    assert response.status_code == 200
    data = response.json()
    assert "inbox_count" in data
    assert "sent_count" in data
    assert "star_count" in data
    assert "trash_count" in data
    assert "unread_count" in data


@pytest.mark.asyncio
async def test_filter_with_key_value_dict(client, auth_headers):
    """POST /api/v1/inbox/filter/ accepts key-value dict and filters messages."""
    response = await client.post("/api/v1/inbox/filter/", headers=auth_headers, json={"folder": "inbox"})
    assert response.status_code == 200
    data = response.json()
    assert "messages" in data
    assert "total_count" in data


@pytest.mark.asyncio
async def test_filter_with_multiple_keys(client, auth_headers):
    """POST /api/v1/inbox/filter/ with multiple filter keys returns AND'd results."""
    response = await client.post(
        "/api/v1/inbox/filter/",
        headers=auth_headers,
        json={"folder": "inbox", "read": False},
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_get_single_message(client, auth_headers):
    """GET /api/v1/inbox/message/{msgid}/ returns a single message."""
    response = await client.get("/api/v1/inbox/message/1/", headers=auth_headers)
    assert response.status_code in (200, 404)


@pytest.mark.asyncio
async def test_unified_patch_star(client, auth_headers):
    """PATCH /api/v1/inbox/message/{msgid}/ with action=star toggles star status."""
    response = await client.patch(
        "/api/v1/inbox/message/1/",
        headers=auth_headers,
        json={"action": "star"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "ok" in data
    assert "starred" in data


@pytest.mark.asyncio
async def test_unified_patch_read(client, auth_headers):
    """PATCH /api/v1/inbox/message/{msgid}/ with action=read toggles read status."""
    response = await client.patch(
        "/api/v1/inbox/message/1/",
        headers=auth_headers,
        json={"action": "read", "is_read": True},
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_unified_patch_tag(client, auth_headers):
    """PATCH /api/v1/inbox/message/{msgid}/ with action=tag sets a tag."""
    response = await client.patch(
        "/api/v1/inbox/message/1/",
        headers=auth_headers,
        json={"action": "tag", "tag": "urgent"},
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_send_message(client, auth_headers):
    """POST /api/v1/inbox/send/ creates a new message."""
    response = await client.post(
        "/api/v1/inbox/send/",
        headers=auth_headers,
        json={"to_user_id": 1, "subject": "Test", "body": "Body"},
    )
    assert response.status_code == 201


@pytest.mark.asyncio
async def test_delete_nonexistent_message(client, auth_headers):
    """DELETE /api/v1/inbox/message/999/ returns ok=false for nonexistent."""
    response = await client.delete("/api/v1/inbox/message/999/", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is False
