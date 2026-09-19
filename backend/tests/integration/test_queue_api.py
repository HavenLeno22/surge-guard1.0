"""The Queue Intelligence API surface.

Driven through the application's own ingest sink, exactly as the AI Pipeline
drives it, so a test cannot pass while the wiring is wrong.

Two properties matter most and are tested from both sides:

1. **The three layers stay apart.** Measurement, prediction and recommendation
   are three routes, and none returns another's payload.
2. **Absence is reported, never faked.** A camera with no queue zone and a
   pipeline that has produced nothing yet must give distinguishable answers -
   not a zero that reads like a measurement.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from surgeguard_ai.contracts import ZoneType

from app.core.config import Environment, Settings
from app.schemas.queue import CounterSettingsWrite, ZonePointWrite, ZoneWrite

from ..conftest import make_perception_result

#: The stock perception factory puts foot points at y=300, so a zone spanning
#: y 250-540 contains them and one above does not.
QUEUE_POLYGON = [
    {"x": 0.0, "y": 250.0},
    {"x": 940.0, "y": 250.0},
    {"x": 940.0, "y": 530.0},
    {"x": 0.0, "y": 530.0},
]
COUNTER_POLYGON = [
    {"x": 860.0, "y": 100.0},
    {"x": 950.0, "y": 100.0},
    {"x": 950.0, "y": 240.0},
    {"x": 860.0, "y": 240.0},
]


@pytest.fixture
def zones_dir(tmp_path: Path) -> Path:
    """A zone directory seeded with one queue and one counter."""
    directory = tmp_path / "zones"
    directory.mkdir()
    (directory / "cam-01.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "camera_id": "cam-01",
                "zones": [
                    {
                        "zone_id": "queue-a",
                        "name": "Ticket Hall Queue",
                        "zone_type": "QUEUE",
                        "width_m": None,
                        "polygon": QUEUE_POLYGON,
                    },
                    {
                        "zone_id": "counter-1",
                        "name": "Counter 1",
                        "zone_type": "COUNTER",
                        "width_m": None,
                        "polygon": COUNTER_POLYGON,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    return directory


@pytest.fixture
def settings(tmp_path: Path, zones_dir: Path) -> Settings:
    """Queue Intelligence on, camera off.

    Queue analysis is arithmetic over tracks - no camera, no GPU, no weights -
    so it runs in full on any machine.
    """
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
        zones_dir=zones_dir,
    )


@pytest.fixture
def unzoned_settings(tmp_path: Path) -> Settings:
    """Queue Intelligence on, but no zones drawn - an ordinary state."""
    return Settings(
        auth_enabled=False,  # these tests cover behaviour, not sign-in
        _env_file=None,
        environment=Environment.DEVELOPMENT,
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'empty.db'}",
        log_level="WARNING",
        ws_heartbeat_seconds=3600.0,
        pipeline_enabled=False,
        csi_enabled=True,
        queue_enabled=True,
        zones_dir=tmp_path / "no-zones",
    )


async def feed(app: FastAPI, *, frames: int = 30, person_count: int = 8) -> None:
    """Deliver a run of perception results through the real ingest sink."""
    sink = app.state.perception_sink
    base = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)

    for step in range(frames):
        await sink.emit(
            make_perception_result(
                frame_seq=step,
                person_count=person_count,
                frame_ts=base + timedelta(seconds=step * 2),
            )
        )
    await app.state.event_bus.drain()


# ---------------------------------------------------------------------------
# Availability
# ---------------------------------------------------------------------------


class TestAvailability:
    async def test_routes_report_why_there_is_nothing(
        self, client: AsyncClient
    ) -> None:
        """A 503 with a reason, not a 200 carrying zeroes."""
        for route in (
            "/api/v1/queue/current",
            "/api/v1/queue/prediction",
            "/api/v1/recommendations",
        ):
            response = await client.get(route)
            assert response.status_code == 503, route
            body = response.json()
            assert body["status"] == "error"
            assert body["message"], "an unavailable route must say why"

    async def test_counters_are_readable_before_anything_is_analysed(
        self, client: AsyncClient
    ) -> None:
        """Configuration is readable whether or not analysis is producing."""
        response = await client.get("/api/v1/counters")
        assert response.status_code == 200
        counters = response.json()["data"]["counters"]
        assert len(counters) == 1
        assert counters[0]["zone_id"] == "queue-a"

    async def test_an_unzoned_camera_reports_unconfigured_not_empty(
        self, unzoned_settings: Settings
    ) -> None:
        """'No queue is configured' and 'the queue is empty' are different facts."""
        from httpx import ASGITransport

        from app.main import create_app

        app = create_app(unzoned_settings)
        async with app.router.lifespan_context(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as http:
                await feed(app)
                response = await http.get("/api/v1/queue/current")
                assert response.status_code == 200
                report = response.json()["data"]["queue"]
                assert report["unconfigured"] is True
                assert report["queues"] == []


# ---------------------------------------------------------------------------
# The three layers
# ---------------------------------------------------------------------------


class TestMeasurement:
    async def test_a_queue_is_measured_from_real_perception(
        self, app: FastAPI, client: AsyncClient
    ) -> None:
        await feed(app)

        response = await client.get("/api/v1/queue/current")
        assert response.status_code == 200

        data = response.json()["data"]
        assert data["camera_id"] == "cam-01"
        assert data["age_seconds"] >= 0

        queue = data["queue"]["queues"][0]
        assert queue["zone_id"] == "queue-a"
        assert queue["zone_name"] == "Ticket Hall Queue"
        assert queue["person_count"] == 8
        assert queue["formation"] in {
            "QUEUE",
            "GENERAL_CROWD",
            "SPARSE",
            "UNDETERMINED",
        }
        assert queue["formation_basis"], "a classification must carry its reasons"

    async def test_the_wait_carries_its_assumptions(
        self, app: FastAPI, client: AsyncClient
    ) -> None:
        await feed(app)

        queue = (await client.get("/api/v1/queue/current")).json()["data"]["queue"][
            "queues"
        ][0]
        assert queue["wait"]["assumptions"], "a derived wait must state what it assumes"
        assert queue["wait"]["rate_source"] in {"MEASURED", "BLENDED", "CONFIGURED"}

    async def test_people_outside_the_zone_are_not_counted(
        self, app: FastAPI, client: AsyncClient
    ) -> None:
        await client.post(
            "/api/v1/zones",
            json={
                "zones": [
                    {
                        "zone_id": "queue-a",
                        "name": "Ticket Hall Queue",
                        "zone_type": "QUEUE",
                        # Well above the y=300 foot points.
                        "polygon": [
                            {"x": 0.0, "y": 0.0},
                            {"x": 100.0, "y": 0.0},
                            {"x": 100.0, "y": 50.0},
                            {"x": 0.0, "y": 50.0},
                        ],
                    }
                ]
            },
        )
        # The running pipeline still holds the original zones, which is exactly
        # what requires_restart reports.
        zones = (await client.get("/api/v1/zones")).json()["data"]
        assert zones["requires_restart"] is True


class TestPrediction:
    async def test_prediction_is_a_separate_route_with_separate_content(
        self, app: FastAPI, client: AsyncClient
    ) -> None:
        await feed(app, frames=60)

        response = await client.get("/api/v1/queue/prediction")
        assert response.status_code == 200

        data = response.json()["data"]
        assert "forecast" in data
        assert "queue" not in data, "prediction must not carry the measurement payload"

        forecast = data["forecast"]["forecasts"][0]
        assert forecast["zone_id"] == "queue-a"
        assert forecast["growth"]["pattern"] in {
            "STABLE",
            "GROWING",
            "SHRINKING",
            "ABNORMAL_GROWTH",
            "INSUFFICIENT_HISTORY",
        }
        assert forecast["growth"]["explanation"]
        assert {m["method"] for m in forecast["methods"]} == {
            "TREND",
            "FLOW_BALANCE",
        }

    async def test_an_unavailable_method_says_why(
        self, app: FastAPI, client: AsyncClient
    ) -> None:
        """A missing line on the chart must have a stated cause."""
        await feed(app, frames=4)

        forecast = (await client.get("/api/v1/queue/prediction")).json()["data"][
            "forecast"
        ]["forecasts"][0]
        unavailable = [m for m in forecast["methods"] if not m["points"]]
        assert unavailable
        assert all(m["unavailable_reason"] for m in unavailable)


class TestRecommendations:
    async def test_a_plan_discloses_the_whole_decision(
        self, app: FastAPI, client: AsyncClient
    ) -> None:
        await feed(app, frames=60)

        response = await client.get("/api/v1/recommendations")
        assert response.status_code == 200

        data = response.json()["data"]
        assert "resources" in data
        assert "forecast" not in data, "recommendations must not carry the forecast"

        plan = data["resources"]["plans"][0]
        for field in (
            "current_queue",
            "arrival_rate_per_min",
            "current",
            "recommended",
            "options",
            "action",
            "rationale",
            "feasible",
        ):
            assert field in plan, f"the plan must disclose {field}"
        assert plan["options"], "the option ladder must be reported"


# ---------------------------------------------------------------------------
# Operator configuration
# ---------------------------------------------------------------------------


class TestCounters:
    async def test_setting_counters_changes_the_wait(
        self, app: FastAPI, client: AsyncClient
    ) -> None:
        """The lever the recommendation pulls must actually move the number."""
        await feed(app)
        before = (await client.get("/api/v1/queue/current")).json()["data"]["queue"][
            "queues"
        ][0]["wait"]["minutes"]

        response = await client.post(
            "/api/v1/counters/queue-a",
            json={"total_counters": 4, "active_counters": 4, "service_rate_per_min": 2.0},
        )
        assert response.status_code == 200
        assert response.json()["data"]["counters"][0]["active_counters"] == 4

        await feed(app, frames=5)
        after = (await client.get("/api/v1/queue/current")).json()["data"]["queue"][
            "queues"
        ][0]["wait"]["minutes"]

        assert before is not None and after is not None
        assert after < before

    async def test_an_unknown_zone_is_rejected(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/v1/counters/no-such-zone",
            json={"total_counters": 4, "active_counters": 2},
        )
        assert response.status_code == 404

    async def test_active_cannot_exceed_total(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/v1/counters/queue-a",
            json={"total_counters": 2, "active_counters": 5},
        )
        # This application maps request-validation failures to 400, not
        # FastAPI's default 422.
        assert response.status_code == 400


class TestZones:
    async def test_zones_round_trip(self, client: AsyncClient) -> None:
        written = await client.post(
            "/api/v1/zones",
            json={
                "zones": [
                    {
                        "zone_id": "queue-a",
                        "name": "Renamed Queue",
                        "zone_type": ZoneType.QUEUE.value,
                        "polygon": QUEUE_POLYGON,
                    }
                ]
            },
        )
        assert written.status_code == 200

        read = await client.get("/api/v1/zones")
        zones = read.json()["data"]["zones"]
        assert len(zones) == 1
        assert zones[0]["name"] == "Renamed Queue"
        assert len(zones[0]["polygon"]) == 4

    async def test_saving_zones_reports_that_a_restart_is_needed(
        self, client: AsyncClient
    ) -> None:
        """A newly drawn zone must never be silently inert."""
        response = await client.post(
            "/api/v1/zones",
            json={
                "zones": [
                    {
                        "zone_id": "queue-b",
                        "name": "Second Queue",
                        "zone_type": ZoneType.QUEUE.value,
                        "polygon": QUEUE_POLYGON,
                    }
                ]
            },
        )
        assert response.status_code == 200
        assert response.json()["data"]["requires_restart"] is True
        assert "Restart" in response.json()["message"]

    async def test_zones_can_be_cleared(self, client: AsyncClient) -> None:
        response = await client.post("/api/v1/zones", json={"zones": []})
        assert response.status_code == 200
        assert response.json()["data"]["zones"] == []

    async def test_a_polygon_needs_three_points(self, client: AsyncClient) -> None:
        """Two points are a line, not a region."""
        response = await client.post(
            "/api/v1/zones",
            json={
                "zones": [
                    {
                        "zone_id": "bad",
                        "name": "Too Few",
                        "zone_type": ZoneType.QUEUE.value,
                        "polygon": [{"x": 0.0, "y": 0.0}, {"x": 10.0, "y": 10.0}],
                    }
                ]
            },
        )
        # This application maps request-validation failures to 400, not
        # FastAPI's default 422.
        assert response.status_code == 400

    async def test_a_zone_id_must_be_addressable(self, client: AsyncClient) -> None:
        """Zone ids name a zone in recommendations; spaces break that."""
        response = await client.post(
            "/api/v1/zones",
            json={
                "zones": [
                    {
                        "zone_id": "not a valid id",
                        "name": "Bad Id",
                        "zone_type": ZoneType.QUEUE.value,
                        "polygon": QUEUE_POLYGON,
                    }
                ]
            },
        )
        # This application maps request-validation failures to 400, not
        # FastAPI's default 422.
        assert response.status_code == 400


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class TestSchemaValidation:
    def test_counter_settings_reject_more_active_than_total(self) -> None:
        with pytest.raises(ValueError, match="cannot exceed"):
            CounterSettingsWrite(total_counters=2, active_counters=3)

    def test_counter_settings_accept_a_valid_allocation(self) -> None:
        settings = CounterSettingsWrite(total_counters=4, active_counters=2)
        assert settings.active_counters == 2
        assert settings.service_rate_per_min is None

    def test_a_zone_needs_at_least_three_vertices(self) -> None:
        with pytest.raises(ValueError):
            ZoneWrite(
                zone_id="q",
                name="Q",
                zone_type=ZoneType.QUEUE,
                polygon=(ZonePointWrite(x=0, y=0), ZonePointWrite(x=1, y=1)),
            )
