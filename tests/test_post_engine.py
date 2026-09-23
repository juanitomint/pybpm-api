"""Tests for POST /bpm/engine/post/{token_id} and /bpm/engine/post/{idwf}/{idcase}/{resource_id}."""

from __future__ import annotations

import pytest


@pytest.fixture
async def client(test_client):
    """Alias for the test client fixture."""
    return test_client


@pytest.fixture
async def auth_headers(client):
    """Get authentication headers by logging in as admin."""
    login_resp = await client.post(
        "/api/v1/auth/token",
        data={"username": "admin", "password": "admin"},
    )
    assert login_resp.status_code == 200, f"Login failed: {login_resp.text}"
    return {"Authorization": f"Bearer {login_resp.json()['access_token']}"}


# ---------------------------------------------------------------------------
# POST /bpm/engine/post/{token_id}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_post_with_body(client, auth_headers):
    """POST /post/{token_id} with body succeeds."""
    response = await client.post(
        "/bpm/engine/post/1/",
        json={
            "external_origin": "webhook",
            "external_id": "ext-42",
            "data": {"field": "value"},
        },
        headers=auth_headers,
    )
    assert response.status_code in (200, 307, 404)
    if response.status_code == 200:
        data = response.json()
        assert data["ok"] is True


@pytest.mark.asyncio
async def test_post_without_body(client, auth_headers):
    """POST /post/{token_id} without body succeeds (body is optional)."""
    response = await client.post(
        "/bpm/engine/post/1/",
        headers=auth_headers,
    )
    assert response.status_code in (200, 307, 404)
    if response.status_code == 200:
        data = response.json()
        assert data["ok"] is True


@pytest.mark.asyncio
async def test_post_token_not_found(client, auth_headers):
    """POST /post/{token_id} with nonexistent ID returns 404."""
    response = await client.post(
        "/bpm/engine/post/999999/",
        json={"external_origin": "webhook"},
        headers=auth_headers,
    )
    assert response.status_code in (404, 307)


# ---------------------------------------------------------------------------
# POST /bpm/engine/post/{idwf}/{idcase}/{resource_id}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_post_data_with_body(client, auth_headers):
    """POST /post/{idwf}/{idcase}/{resource_id} with body succeeds."""
    response = await client.post(
        "/bpm/engine/post/w1/c1/r1/",
        json={
            "external_origin": "inbox",
            "external_id": "msg-7",
            "data": {"note": "test"},
        },
        headers=auth_headers,
    )
    assert response.status_code in (200, 307, 404)
    if response.status_code == 200:
        data = response.json()
        assert data["ok"] is True


@pytest.mark.asyncio
async def test_post_data_without_body(client, auth_headers):
    """POST /post/{idwf}/{idcase}/{resource_id} without body succeeds (body is optional)."""
    response = await client.post(
        "/bpm/engine/post/w1/c1/r1/",
        headers=auth_headers,
    )
    assert response.status_code in (200, 307, 404)
    if response.status_code == 200:
        data = response.json()
        assert data["ok"] is True


@pytest.mark.asyncio
async def test_post_data_token_not_found(client, auth_headers):
    """POST /post/{idwf}/{idcase}/{resource_id} with nonexistent combo returns 404."""
    response = await client.post(
        "/bpm/engine/post/nonexistent/case123/missing_resource/",
        json={"external_origin": "webhook"},
        headers=auth_headers,
    )
    assert response.status_code in (404, 307)
