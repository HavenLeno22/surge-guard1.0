"""The perception and pipeline API surface.

Driven through the real application, with the pipeline disabled. Perception
state is populated through the ingest sink - the same path a running pipeline
uses - so what is verified is the whole chain from sink to response.
"""

from __future__ import annotations

from fastapi import FastAPI
from httpx import AsyncClient

from app.ingest.perception_sink import InProcessPerceptionSink
from app.workers.perception_worker import PerceptionWorkerState

from ..conftest import make_perception_result


async def ingest(app: FastAPI, **kwargs) -> None:
    """Push a result through the real ingest boundary."""
    sink: InProcessPerceptionSink = app.state.perception_sink
    await sink.emit(make_perception_result(**kwargs))


class TestLatestPerception:
    async def test_reports_unavailable_before_the_first_result(
        self, client: AsyncClient
    ) -> None:
        """"Not available" and "found nobody" are different facts.

        A caller that cannot tell them apart will eventually display one as the
        other, so the absence of analysis is an error rather than a success
        carrying null.
        """
        response = await client.get("/api/v1/perception/latest")

        assert response.status_code == 503
        payload = response.json()
        assert payload["status"] == "error"
        assert payload["error_code"] == "SERVICE_UNAVAILABLE"
        assert payload["data"] is None

    async def test_returns_the_most_recent_result(
        self, app: FastAPI, client: AsyncClient
    ) -> None:
        await ingest(app, frame_seq=41, person_count=3)

        response = await client.get("/api/v1/perception/latest")

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["result"]["frame_seq"] == 41
        assert data["result"]["person_count"] == 3
        assert data["is_stale"] is False
        assert data["age_seconds"] >= 0

    async def test_carries_everything_the_backend_receives(
        self, app: FastAPI, client: AsyncClient
    ) -> None:
        """Frame number, timestamp, count, identities, boxes, confidence, timings."""
        await ingest(app, frame_seq=7, person_count=2)

        data = (await client.get("/api/v1/perception/latest")).json()["data"]
        result = data["result"]

        assert result["frame_seq"] == 7
        assert result["frame_ts"]
        assert result["person_count"] == 2
        assert result["camera_id"] == "cam-01"
        assert result["source_mode"] == "LIVE"
        assert result["inference_ms"] > 0
        assert result["achieved_fps"] > 0

        tracks = result["tracking"]["tracks"]
        assert [track["track_id"] for track in tracks] == [1, 2]
        assert all(0.0 <= track["confidence"] <= 1.0 for track in tracks)

        boxes = [detection["bbox"] for detection in result["detections"]["detections"]]
        assert len(boxes) == 2
        assert all({"x1", "y1", "x2", "y2"} <= box.keys() for box in boxes)

    async def test_a_later_result_supersedes_an_earlier_one(
        self, app: FastAPI, client: AsyncClient
    ) -> None:
        await ingest(app, frame_seq=1)
        await ingest(app, frame_seq=2)

        data = (await client.get("/api/v1/perception/latest")).json()["data"]

        assert data["result"]["frame_seq"] == 2

    async def test_a_degraded_result_is_reported_as_degraded(
        self, app: FastAPI, client: AsyncClient
    ) -> None:
        """A frame a stage could not process is surfaced, not hidden."""
        await ingest(app, frame_seq=3, degraded=True)

        result = (await client.get("/api/v1/perception/latest")).json()["data"]["result"]

        assert result["degraded"] is True
        assert result["degraded_reason"]

    async def test_the_device_is_unknown_before_the_model_loads(
        self, app: FastAPI, client: AsyncClient
    ) -> None:
        """With the pipeline disabled nothing has resolved a device, and it says so."""
        await ingest(app, frame_seq=0)

        data = (await client.get("/api/v1/perception/latest")).json()["data"]

        assert data["device"] is None


class TestPerceptionStatus:
    async def test_answers_before_any_result_has_arrived(
        self, client: AsyncClient
    ) -> None:
        """The call that tells you whether to ask for data must not need data."""
        response = await client.get("/api/v1/perception/status")

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["has_result"] is False
        assert data["is_stale"] is True
        assert data["received"] == 0
        assert data["age_seconds"] is None

    async def test_counts_what_has_been_received(
        self, app: FastAPI, client: AsyncClient
    ) -> None:
        await ingest(app, frame_seq=0)
        await ingest(app, frame_seq=1, degraded=True)
        await ingest(app, frame_seq=2)

        data = (await client.get("/api/v1/perception/status")).json()["data"]

        assert data["has_result"] is True
        assert data["received"] == 3
        assert data["degraded_received"] == 1
        assert data["is_stale"] is False
        assert data["first_received_at"]
        assert data["last_received_at"]


class TestPipelineStatus:
    async def test_reports_a_disabled_pipeline_without_failing(
        self, client: AsyncClient
    ) -> None:
        """The one call that explains an outage must not fail during one."""
        response = await client.get("/api/v1/pipeline/status")

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["state"] == PerceptionWorkerState.DISABLED.value
        assert data["running"] is False
        assert data["throughput"] is None
        assert data["device"] is None
        assert data["detail"]

    async def test_reports_the_configured_source_and_camera(
        self, client: AsyncClient
    ) -> None:
        data = (await client.get("/api/v1/pipeline/status")).json()["data"]

        assert data["source_mode"] == "LIVE"
        assert data["camera_id"] == "cam-01"
        assert data["restart_attempts"] == 0
        assert data["total_restarts"] == 0


class TestSystemHealth:
    async def test_the_camera_and_pipeline_answer_for_themselves(
        self, client: AsyncClient
    ) -> None:
        """Registering probes is what turns two hardcoded OFFLINE rows into a report."""
        response = await client.get("/api/v1/system-health")

        assert response.status_code == 200
        components = {
            entry["component"]: entry
            for entry in response.json()["data"]["components"]
        }

        assert components["AI_PIPELINE"]["status"] == "OFFLINE"
        assert components["AI_PIPELINE"]["detail"]  # says why
        assert components["CAMERA"]["status"] == "OFFLINE"
        assert components["BACKEND"]["status"] == "HEALTHY"

    async def test_health_does_not_claim_a_pipeline_that_produced_nothing(
        self, client: AsyncClient
    ) -> None:
        data = (await client.get("/api/v1/system-health")).json()["data"]
        pipeline = next(
            entry for entry in data["components"] if entry["component"] == "AI_PIPELINE"
        )

        assert pipeline["status"] != "HEALTHY"
        assert pipeline["last_seen"] is None


class TestApiSurface:
    async def test_the_new_routes_are_described_in_openapi(
        self, client: AsyncClient
    ) -> None:
        """The frontend's types are generated from this schema."""
        paths = (await client.get("/openapi.json")).json()["paths"]

        assert "/api/v1/perception/latest" in paths
        assert "/api/v1/perception/status" in paths
        assert "/api/v1/pipeline/status" in paths

    async def test_no_crowd_stability_endpoints_exist_yet(
        self, client: AsyncClient
    ) -> None:
        """Nothing computes a Crowd Stability Index, so nothing may publish one."""
        paths = (await client.get("/openapi.json")).json()["paths"]

        assert not [path for path in paths if "csi" in path.lower()]
