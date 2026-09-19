"""The Camera Network API - several cameras, managed while running.

Two cameras are configured the way a real deployment configures them: the
primary one from the long-standing settings, the second from indexed settings.
The pipeline is disabled - no camera, no GPU - and results are delivered through
each camera's own ingest sink, exactly as its AI Pipeline would deliver them.

What matters most, and is asserted from both sides:

1. **Cameras do not bleed into each other.** One camera's frames never reach
   another camera's analysis, and the single-camera routes keep describing the
   primary camera only.
2. **A connection test never steals a stream.** An address a running camera owns
   is answered from that camera's live measurements.
3. **Absence is reported, never zero.** A camera with nothing analysed answers
   503, and its people count is null, not 0.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import AsyncClient
from surgeguard_ai.contracts import CameraRole

from app.core.config import CameraSeed, Environment, Settings
from app.workers.perception_worker import PerceptionWorkerState

from ..conftest import make_perception_result
from ..unit.test_camera_probe import _FakeDroidCam

TEAM_CAMERA_URL = "http://172.18.225.59:4747/video"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        auth_enabled=False,  # these tests cover behaviour, not sign-in
        _env_file=None,
        environment=Environment.DEVELOPMENT,
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}",
        log_level="WARNING",
        ws_heartbeat_seconds=3600.0,
        pipeline_enabled=False,
        csi_enabled=True,
        queue_enabled=True,
        zones_dir=tmp_path / "zones",
        camera_registry_path=tmp_path / "cameras.json",
        topology_path=tmp_path / "topology.json",
        camera_name="Main Entrance",
        live_camera_device="http://172.30.213.172:4747/video",
        additional_cameras=(
            CameraSeed(
                index=2,
                camera_id="cam-02",
                name="Team Camera",
                url=TEAM_CAMERA_URL,
                role=CameraRole.QUEUE,
            ),
        ),
    )


@pytest.fixture
def droidcam() -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeDroidCam)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


async def feed(app: FastAPI, camera_id: str, *, frames: int = 20, person_count: int = 5) -> None:
    """Deliver results through one camera's own ingest sink."""
    runtime = app.state.camera_manager.require(camera_id)
    base = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    for step in range(frames):
        await runtime.sink.emit(
            make_perception_result(
                camera_id=camera_id,
                frame_seq=step,
                person_count=person_count,
                frame_ts=base + timedelta(seconds=step),
            )
        )
    await app.state.event_bus.drain()


# ---------------------------------------------------------------------------
# The camera set
# ---------------------------------------------------------------------------


class TestListing:
    async def test_every_configured_camera_is_listed_primary_first(
        self, client: AsyncClient
    ) -> None:
        response = await client.get("/api/v1/cameras")
        assert response.status_code == 200

        data = response.json()["data"]
        assert [camera["camera_id"] for camera in data["cameras"]] == ["cam-01", "cam-02"]
        primary, team = data["cameras"]
        assert primary["is_primary"] is True
        assert primary["name"] == "Main Entrance"
        assert team["display_id"] == "CAM-02"
        assert team["stream_url"] == TEAM_CAMERA_URL
        assert team["url_source"] == "ENVIRONMENT"
        assert team["role"] == "QUEUE"
        assert data["total"] == 2

    async def test_a_camera_that_is_not_running_reports_no_measurements(
        self, client: AsyncClient
    ) -> None:
        """An offline camera has no people count - not a count of zero."""
        team = (await client.get("/api/v1/cameras/cam-02")).json()["data"]

        assert team["status"] == "OFFLINE"
        assert team["status_detail"]
        assert team["metrics"]["people_count"] is None
        assert team["metrics"]["achieved_fps"] is None

    async def test_an_unknown_camera_is_not_found(self, client: AsyncClient) -> None:
        assert (await client.get("/api/v1/cameras/cam-99")).status_code == 404


class TestChanges:
    async def test_a_camera_can_be_added_by_ip_and_port(
        self, client: AsyncClient, settings: Settings
    ) -> None:
        response = await client.post(
            "/api/v1/cameras",
            json={"name": "Counter View", "stream_url": "192.168.1.40:4747", "role": "SERVICE"},
        )

        assert response.status_code == 201
        added = response.json()["data"]
        assert added["camera_id"] == "cam-03"
        assert added["stream_url"] == "http://192.168.1.40:4747/video"
        assert added["origin"] == "OPERATOR"
        assert settings.camera_registry_path.exists()

        listed = (await client.get("/api/v1/cameras")).json()["data"]["cameras"]
        assert [camera["camera_id"] for camera in listed] == ["cam-01", "cam-02", "cam-03"]

    async def test_a_duplicate_id_is_a_conflict(self, client: AsyncClient) -> None:
        response = await client.post("/api/v1/cameras", json={"camera_id": "cam-02", "name": "Dup"})
        assert response.status_code == 409

    async def test_an_unusable_address_is_rejected(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/v1/cameras", json={"name": "Bad", "stream_url": "ftp://10.0.0.4/video"}
        )
        assert response.status_code == 400

    async def test_changing_an_address_is_saved_and_takes_precedence(
        self, client: AsyncClient
    ) -> None:
        response = await client.patch(
            "/api/v1/cameras/cam-02", json={"stream_url": "172.18.230.10"}
        )

        assert response.status_code == 200
        updated = response.json()["data"]
        assert updated["stream_url"] == "http://172.18.230.10:4747/video"
        assert updated["url_source"] == "REGISTRY"

    async def test_a_name_cannot_be_cleared(self, client: AsyncClient) -> None:
        response = await client.patch("/api/v1/cameras/cam-02", json={"name": None})
        assert response.status_code == 400

    async def test_disabling_a_camera_reports_it_disabled(self, client: AsyncClient) -> None:
        response = await client.patch("/api/v1/cameras/cam-02", json={"enabled": False})
        assert response.json()["data"]["status"] == "DISABLED"

    async def test_the_primary_camera_cannot_be_removed(self, client: AsyncClient) -> None:
        assert (await client.delete("/api/v1/cameras/cam-01")).status_code == 409

    async def test_a_removed_camera_is_gone(self, client: AsyncClient) -> None:
        assert (await client.delete("/api/v1/cameras/cam-02")).status_code == 200
        assert (await client.get("/api/v1/cameras/cam-02")).status_code == 404


# ---------------------------------------------------------------------------
# Isolation between cameras
# ---------------------------------------------------------------------------


class TestIsolation:
    async def test_a_camera_without_analysis_answers_503(self, client: AsyncClient) -> None:
        assert (await client.get("/api/v1/cameras/cam-02/analytics")).status_code == 503

    async def test_one_cameras_frames_never_reach_another_camera(
        self, app: FastAPI, client: AsyncClient
    ) -> None:
        await feed(app, "cam-02", person_count=7)

        team = await client.get("/api/v1/cameras/cam-02/analytics")
        assert team.status_code == 200
        assert team.json()["data"]["camera_id"] == "cam-02"
        assert team.json()["data"]["crowd"]["person_count"] == 7

        # The primary camera saw nothing, and the single-camera routes - which
        # describe the primary camera - say so.
        assert (await client.get("/api/v1/cameras/cam-01/analytics")).status_code == 503
        assert (await client.get("/api/v1/intelligence/current")).status_code == 503

    async def test_the_single_camera_routes_still_describe_the_primary_camera(
        self, app: FastAPI, client: AsyncClient
    ) -> None:
        await feed(app, "cam-01", person_count=3)
        await feed(app, "cam-02", person_count=9)

        current = (await client.get("/api/v1/intelligence/current")).json()["data"]
        assert current["camera_id"] == "cam-01"
        assert current["crowd"]["person_count"] == 3


# ---------------------------------------------------------------------------
# Connection tests
# ---------------------------------------------------------------------------


class TestConnectionTests:
    async def test_a_busy_droidcam_is_reported_as_busy(
        self, client: AsyncClient, droidcam: str
    ) -> None:
        response = await client.post(
            "/api/v1/cameras/test-connection", json={"url": f"{droidcam}/busy"}
        )

        assert response.status_code == 200
        result = response.json()["data"]
        assert result["success"] is False
        assert result["outcome"] == "BUSY"
        assert result["device_name"] == "A015"

    async def test_an_address_a_running_camera_owns_is_not_opened_again(
        self, app: FastAPI, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """DroidCam serves one client: a second connection would steal the stream."""

        def must_not_open(*_args, **_kwargs):
            raise AssertionError("a second client was opened to an owned camera")

        monkeypatch.setattr("app.cameras.manager.run_connection_test", must_not_open)
        runtime = app.state.camera_manager.require("cam-02")
        # Stand in for a camera whose worker is running - no GPU in tests.
        runtime.worker._worker_state = PerceptionWorkerState.RUNNING
        await feed(app, "cam-02")

        response = await client.post(
            "/api/v1/cameras/test-connection", json={"url": TEAM_CAMERA_URL}
        )

        result = response.json()["data"]
        assert result["live_measurement"] is True
        assert "no second client" in result["detail"]

    async def test_a_missing_address_is_invalid(self, client: AsyncClient) -> None:
        response = await client.post("/api/v1/cameras/test-connection", json={"url": "   "})
        assert response.status_code == 400


# ---------------------------------------------------------------------------
# Zones and counters
# ---------------------------------------------------------------------------


QUEUE_ZONE = {
    "zone_id": "queue-b",
    "name": "Side Queue",
    "zone_type": "QUEUE",
    "polygon": [
        {"x": 0.0, "y": 250.0},
        {"x": 940.0, "y": 250.0},
        {"x": 940.0, "y": 530.0},
        {"x": 0.0, "y": 530.0},
    ],
}


class TestZones:
    async def test_zones_are_applied_without_a_restart(
        self, app: FastAPI, client: AsyncClient
    ) -> None:
        response = await client.put("/api/v1/cameras/cam-02/zones", json={"zones": [QUEUE_ZONE]})

        assert response.status_code == 200
        assert response.json()["data"]["requires_restart"] is False

        await feed(app, "cam-02", person_count=6)
        analytics = (await client.get("/api/v1/cameras/cam-02/analytics")).json()["data"]
        (queue,) = analytics["queue"]["queues"]
        assert queue["zone_id"] == "queue-b"
        assert queue["person_count"] == 6

    async def test_zones_are_per_camera(self, client: AsyncClient) -> None:
        await client.put("/api/v1/cameras/cam-02/zones", json={"zones": [QUEUE_ZONE]})

        team = (await client.get("/api/v1/cameras/cam-02/zones")).json()["data"]
        primary = (await client.get("/api/v1/cameras/cam-01/zones")).json()["data"]
        assert [zone["zone_id"] for zone in team["zones"]] == ["queue-b"]
        assert primary["zones"] == []

    async def test_counters_are_set_on_the_cameras_own_queue(
        self, app: FastAPI, client: AsyncClient
    ) -> None:
        await client.put("/api/v1/cameras/cam-02/zones", json={"zones": [QUEUE_ZONE]})

        response = await client.post(
            "/api/v1/cameras/cam-02/counters/queue-b",
            json={"total_counters": 5, "active_counters": 3},
        )
        assert response.status_code == 200
        assert response.json()["data"]["counters"][0]["active_counters"] == 3

        missing = await client.post(
            "/api/v1/cameras/cam-01/counters/queue-b",
            json={"total_counters": 5, "active_counters": 3},
        )
        assert missing.status_code == 404


# ---------------------------------------------------------------------------
# Realtime
# ---------------------------------------------------------------------------


def test_the_snapshot_carries_every_camera(app: FastAPI) -> None:
    with TestClient(app) as client, client.websocket_connect("/ws/command-center") as socket:
        snapshot = socket.receive_json()

    cameras = snapshot["data"]["cameras"]
    assert [camera["camera_id"] for camera in cameras] == ["cam-01", "cam-02"]
    assert snapshot["data"]["camera_analyses"] == {}


def test_each_camera_is_pushed_under_its_own_id(app: FastAPI) -> None:
    """A second camera's analysis arrives as camera.analysis, never as csi.updated."""
    base = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)

    with TestClient(app) as client, client.websocket_connect("/ws/command-center") as socket:
        socket.receive_json()  # snapshot

        portal = client.portal  # type: ignore[attr-defined]
        sink = app.state.camera_manager.require("cam-02").sink
        for step in range(6):
            portal.call(
                sink.emit,
                make_perception_result(
                    camera_id="cam-02",
                    frame_seq=step,
                    person_count=4,
                    frame_ts=base + timedelta(seconds=step),
                ),
            )
        portal.call(app.state.event_bus.drain)

        received: list[dict] = []
        for _ in range(6):
            envelope = json.loads(socket.receive_text())
            received.append(envelope)
            if envelope["type"] == "camera.analysis":
                break

    analyses = [envelope for envelope in received if envelope["type"] == "camera.analysis"]
    assert analyses, "the second camera's analysis was not pushed"
    assert analyses[0]["camera_id"] == "cam-02"
    assert analyses[0]["data"]["camera_id"] == "cam-02"
    assert not [envelope for envelope in received if envelope["type"] == "csi.updated"]
