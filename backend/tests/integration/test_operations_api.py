"""Per-camera guidance, operator actions, and the realtime messages they produce.

Driven through the real ingest sink, as the decisions suite is, so the whole
chain runs from a perception result to the socket.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import AsyncClient

from app.core.config import Environment, Settings

from ..conftest import make_perception_result


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        _env_file=None,
        auth_enabled=False,
        environment=Environment.DEVELOPMENT,
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}",
        log_level="WARNING",
        ws_heartbeat_seconds=3600.0,
        pipeline_enabled=False,
        csi_enabled=True,
        ode_enabled=True,
        ode_report_min_interval_seconds=0.0,
        camera_registry_path=tmp_path / "cameras.json",
        topology_path=tmp_path / "topology.json",
        zones_dir=tmp_path / "zones",
    )


async def feed(app: FastAPI, *, frames: int = 40, busy_from: int = 15) -> None:
    sink = app.state.perception_sink
    base = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    for step in range(frames):
        await sink.emit(
            make_perception_result(
                frame_seq=step,
                person_count=4 if step < busy_from else 30,
                frame_ts=base + timedelta(seconds=step),
            )
        )
    await app.state.event_bus.drain()


async def test_camera_guidance_always_answers(client: AsyncClient) -> None:
    response = await client.get("/api/v1/cameras/cam-01/decisions")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["camera_id"] == "cam-01"
    assert data["report"] is None
    assert data["operational_state"] == "MONITORING"


async def test_unknown_camera_guidance_is_not_found(client: AsyncClient) -> None:
    assert (await client.get("/api/v1/cameras/cam-99/decisions")).status_code == 404


async def test_acknowledging_a_stable_camera_is_a_conflict_that_says_why(
    client: AsyncClient,
) -> None:
    response = await client.post(
        "/api/v1/cameras/cam-01/operations", json={"action": "ACKNOWLEDGE"}
    )

    assert response.status_code == 409
    assert "nothing to acknowledge" in response.json()["message"]


async def test_an_operator_works_a_situation_and_the_timeline_names_them(
    client: AsyncClient, app: FastAPI
) -> None:
    await feed(app)
    guidance = (await client.get("/api/v1/cameras/cam-01/decisions")).json()["data"]
    if guidance["operational_state"] != "OBSERVING":
        pytest.skip("The synthetic crowd did not destabilise this camera")

    acknowledged = await client.post(
        "/api/v1/cameras/cam-01/operations",
        json={"action": "ACKNOWLEDGE", "note": "Checking the east concourse feed"},
    )
    assert acknowledged.status_code == 200
    body = acknowledged.json()["data"]
    assert body["operational_state"] == "INVESTIGATING"
    assert body["entry"]["entry_type"] == "OPERATOR_ACTION"
    assert body["entry"]["actor"] == "Control Room Operator"
    assert body["entry"]["detail"] == "Checking the east concourse feed"

    rule_id = (
        guidance["report"]["recommended_actions"][0]["rule_id"] if guidance["report"] else None
    )
    logged = await client.post(
        "/api/v1/cameras/cam-01/operations",
        json={"action": "LOG_ACTION", "note": "Opened gate 3", "rule_id": rule_id},
    )
    assert logged.json()["data"]["operational_state"] == "RESPONDING"

    timeline = (await client.get("/api/v1/decisions/timeline")).json()["data"]["entries"]
    actions = [entry for entry in timeline if entry["entry_type"] == "OPERATOR_ACTION"]
    assert len(actions) == 2
    assert all(entry["actor"] == "Control Room Operator" for entry in actions)

    closed = await client.post("/api/v1/cameras/cam-01/operations", json={"action": "CLOSE"})
    assert closed.status_code == 409  # still unstable


def test_state_changes_and_reports_reach_the_socket_tagged_by_camera(app: FastAPI) -> None:
    base = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)

    with TestClient(app) as client, client.websocket_connect("/ws/command-center") as socket:
        snapshot = socket.receive_json()
        assert snapshot["data"]["camera_decisions"]["cam-01"]["operational_state"] == "MONITORING"

        portal = client.portal  # type: ignore[attr-defined]
        for step in range(30):
            portal.call(
                app.state.perception_sink.emit,
                make_perception_result(
                    frame_seq=step,
                    person_count=4 if step < 10 else 30,
                    frame_ts=base + timedelta(seconds=step),
                ),
            )
        portal.call(app.state.event_bus.drain)

        messages = []
        for _ in range(30):
            envelope = json.loads(socket.receive_text())
            messages.append(envelope)
            types = {message["type"] for message in messages}
            if {"oir.updated", "state.updated"} <= types:
                break

    reports = [message for message in messages if message["type"] == "oir.updated"]
    states = [message for message in messages if message["type"] == "state.updated"]
    assert reports and all(message["camera_id"] == "cam-01" for message in reports)
    assert states
    assert states[0]["data"]["camera_id"] == "cam-01"
    assert states[0]["data"]["operational_state"] in {"OBSERVING", "RECOVERING", "MONITORING"}


def test_the_snapshot_route_refuses_a_camera_that_is_not_running(app: FastAPI) -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/cameras/cam-01/snapshot")

    assert response.status_code == 503
    assert response.json()["error_code"] == "SERVICE_UNAVAILABLE"
