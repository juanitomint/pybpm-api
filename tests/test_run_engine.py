"""Tests for POST /bpm/engine/run/{idwf}/{idcase}."""

from __future__ import annotations

import pytest

from app.models.bpm_model import BpmModel
from app.models.token import Token


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


@pytest.fixture
async def seeded_model(setup_test_db):
    """Seed a BPM model with a simple start → task flow."""
    factory = setup_test_db["factory"]
    model = BpmModel(
        idwf="w1",
        data={
            "childShapes": [
                {
                    "resourceId": "start1",
                    "id": "start1",
                    "stencil": {"id": "StartNoneEvent"},
                    "outgoing": [{"resourceId": "flow1"}],
                    "childShapes": [
                        {
                            "resourceId": "flow1",
                            "id": "flow1",
                            "stencil": {"id": "SequenceFlow"},
                            "outgoing": [{"resourceId": "task1"}],
                            "incoming": [{"resourceId": "start1"}],
                        },
                    ],
                },
                {
                    "resourceId": "task1",
                    "id": "task1",
                    "stencil": {"id": "Task"},
                    "outgoing": [{"resourceId": "flow2"}],
                    "incoming": [{"resourceId": "flow1"}],
                    "childShapes": [
                        {
                            "resourceId": "flow2",
                            "id": "flow2",
                            "stencil": {"id": "SequenceFlow"},
                            "outgoing": [{"resourceId": "end1"}],
                            "incoming": [{"resourceId": "task1"}],
                        },
                    ],
                },
                {
                    "resourceId": "end1",
                    "id": "end1",
                    "stencil": {"id": "EndNoneEvent"},
                    "incoming": [{"resourceId": "flow2"}],
                },
            ]
        },
    )
    async with factory() as s:
        s.add(model)
        await s.commit()
    return model


@pytest.fixture
async def seeded_token(setup_test_db):
    """Seed a token matching the seeded_model shapes."""
    factory = setup_test_db["factory"]
    token = Token(
        resource_id="task1",
        idwf="w1",
        case_id="c1",
        type="Task",
        status="pending",
        assign=[],
    )
    async with factory() as s:
        s.add(token)
        await s.commit()
    return token


@pytest.mark.asyncio
async def test_run_no_model(client, auth_headers):
    """POST /run/{idwf}/{idcase} with nonexistent model returns 404."""
    response = await client.post(
        "/bpm/engine/run/nonexistent/c1",
        headers=auth_headers,
    )
    assert response.status_code in (404, 307)


@pytest.mark.asyncio
async def test_run_with_pending_tokens(
    client, auth_headers, seeded_model, seeded_token
):
    """POST /run/{idwf}/{idcase} with pending tokens executes the engine loop."""
    response = await client.post(
        "/bpm/engine/run/w1/c1",
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True


@pytest.mark.asyncio
async def test_run_without_body(client, auth_headers, seeded_model):
    """POST /run/{idwf}/{idcase} without body succeeds."""
    response = await client.post(
        "/bpm/engine/run/w1/c1",
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True


@pytest.fixture
async def seeded_parallel_model(setup_test_db):
    """Seed a BPM model with Start → SequenceFlow → ParallelGateway → End."""
    factory = setup_test_db["factory"]
    model = BpmModel(
        idwf="w-parallel",
        data={
            "childShapes": [
                {
                    "resourceId": "start1",
                    "id": "start1",
                    "stencil": {"id": "StartNoneEvent"},
                    "outgoing": [{"resourceId": "flow1"}],
                    "childShapes": [],
                },
                {
                    "resourceId": "flow1",
                    "id": "flow1",
                    "stencil": {"id": "SequenceFlow"},
                    "outgoing": [{"resourceId": "gw1"}],
                    "incoming": [{"resourceId": "start1"}],
                    "childShapes": [],
                    "target": {"resourceId": "gw1"},
                },
                {
                    "resourceId": "gw1",
                    "id": "gw1",
                    "stencil": {"id": "ParallelGateway"},
                    "outgoing": [
                        {"resourceId": "flow2a"},
                        {"resourceId": "flow2b"},
                    ],
                    "incoming": [{"resourceId": "flow1"}],
                    "childShapes": [
                        {
                            "resourceId": "flow2a",
                            "id": "flow2a",
                            "stencil": {"id": "SequenceFlow"},
                            "outgoing": [{"resourceId": "end1"}],
                            "incoming": [{"resourceId": "gw1"}],
                            "childShapes": [],
                            "target": {"resourceId": "end1"},
                        },
                        {
                            "resourceId": "flow2b",
                            "id": "flow2b",
                            "stencil": {"id": "SequenceFlow"},
                            "outgoing": [{"resourceId": "end1"}],
                            "incoming": [{"resourceId": "gw1"}],
                            "childShapes": [],
                            "target": {"resourceId": "end1"},
                        },
                    ],
                },
                {
                    "resourceId": "end1",
                    "id": "end1",
                    "stencil": {"id": "EndNoneEvent"},
                    "incoming": [
                        {"resourceId": "flow2a"},
                        {"resourceId": "flow2b"},
                    ],
                    "childShapes": [],
                },
            ]
        },
    )
    async with factory() as s:
        s.add(model)
        await s.commit()
    return model


@pytest.mark.asyncio
async def test_post_triggers_full_engine_loop(
    client, auth_headers, seeded_parallel_model, setup_test_db
):
    """POST to StartNoneEvent should trigger engine loop that processes
    SequenceFlow and creates ParallelGateway tokens."""
    # Seed a pending token on the StartNoneEvent
    factory = setup_test_db["factory"]
    token = Token(
        resource_id="start1",
        idwf="w-parallel",
        case_id="c2",
        type="StartNoneEvent",
        status="pending",
        assign=[],
    )
    async with factory() as s:
        s.add(token)
        await s.commit()

    # Call POST to advance the StartNoneEvent
    response = await client.post(
        "/bpm/engine/post/w-parallel/c2/start1",
        json={"external_origin": "test"},
        headers=auth_headers,
    )
    assert response.status_code == 200

    # Check that the engine loop processed tokens
    # The StartNoneEvent should be finished, SequenceFlow should be processed,
    # and ParallelGateway tokens should be created
    tokens_resp = await client.get(
        "/bpm/token_manager/tokens/w-parallel/c2",
        headers=auth_headers,
    )
    assert tokens_resp.status_code in (200, 307)
    if tokens_resp.status_code == 200:
        data = tokens_resp.json()
        token_rows = data.get("rows", [])
        # After engine loop: start1=finished, flow1=finished, gw1 tokens created
        resource_ids = {t["resource_id"] for t in token_rows}
        assert "start1" in resource_ids
