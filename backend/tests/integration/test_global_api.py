"""Site intelligence through the API and the Command Center socket.

Two cameras, no model: results arrive through each camera's own ingest sink, and
a camera is made to look connected the way a running worker would, so what is
tested is how the site figures are combined, withheld and explained.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import AsyncClient

from app.workers.perception_worker import PerceptionWorkerState

from ..conftest import make_perception_result
from .test_cameras_api import QUEUE_ZONE, feed, settings  # noqa: F401 - shared fixture

ENTRANCE_ZONE = {
    "zone_id": "entrance",
    "name": "Entrance",
    "zone_type": "ENTRY",
    "polygon": [
        {"x": 0.0, "y": 0.0},
        {"x": 480.0, "y": 0.0},
        {"x": 480.0, "y": 540.0},
        {"x": 0.0, "y": 540.0},
    ],
}


def link(from_camera: str, from_zone: str, to_camera: str, to_zone: str) -> dict[str, str]:
    return {
        "from_camera_id": from_camera,
        "from_zone_id": from_zone,
        "to_camera_id": to_camera,
        "to_zone_id": to_zone,
    }


def connected(app: FastAPI, *camera_ids: str) -> None:
    """Mark cameras as running, as their workers would once frames flow."""
    for camera_id in camera_ids:
        app.state.camera_manager.require(camera_id).worker._worker_state = (  # noqa: SLF001
            PerceptionWorkerState.RUNNING
        )


class TestSiteAnalytics:
    async def test_nothing_is_reported_before_the_first_update(self, client: AsyncClient) -> None:
        assert (await client.get("/api/v1/global/analytics")).status_code == 503
        assert (await client.get("/api/v1/global/forecast")).status_code == 503

    async def test_every_contributing_camera_is_combined(
        self, app: FastAPI, client: AsyncClient
    ) -> None:
        await feed(app, "cam-01", person_count=5)
        await feed(app, "cam-02", person_count=7)
        connected(app, "cam-01", "cam-02")
        app.state.site_intelligence.update_once()

        report = (await client.get("/api/v1/global/analytics")).json()["data"]

        assert report["cameras_contributing"] == 2
        assert report["headcount"]["value"] == 12
        assert report["headcount"]["aggregation"] == "INDEPENDENT_SUM"
        assert report["headcount"]["label"] == "Combined observed count"
        assert report["degraded"] is False
        assert [camera["people_count"] for camera in report["cameras"]] == [5, 7]

    async def test_an_offline_camera_is_missing_never_zero(
        self, app: FastAPI, client: AsyncClient
    ) -> None:
        await feed(app, "cam-02", person_count=7)
        connected(app, "cam-02")
        app.state.site_intelligence.update_once()

        report = (await client.get("/api/v1/global/analytics")).json()["data"]

        assert report["headcount"]["value"] == 7
        assert report["headcount"]["missing_camera_ids"] == ["cam-01"]
        primary = report["cameras"][0]
        assert primary["contributing"] is False
        assert primary["people_count"] is None
        assert primary["excluded_reason"]
        assert report["degraded"] is True
        assert "Global analysis degraded - CAM-01 offline" in report["degraded_reasons"]

    async def test_the_forecast_route_says_why_a_forecast_is_withheld(
        self, app: FastAPI, client: AsyncClient
    ) -> None:
        await feed(app, "cam-02", person_count=7)
        connected(app, "cam-02")
        app.state.site_intelligence.update_once()

        forecast = (await client.get("/api/v1/global/forecast")).json()["data"]

        assert forecast["demand"]["available"] is False
        assert "CAM-01" in forecast["demand"]["withheld_reason"]
        assert forecast["queue"]["available"] is False
        assert forecast["resource_plan"] is None
        assert forecast["resource_plan_withheld_reason"]
        assert forecast["degraded"] is True


class TestTopology:
    async def test_the_topology_lists_cameras_zones_and_links(
        self, client: AsyncClient
    ) -> None:
        await client.put("/api/v1/cameras/cam-01/zones", json={"zones": [ENTRANCE_ZONE]})
        await client.put("/api/v1/cameras/cam-02/zones", json={"zones": [QUEUE_ZONE]})

        topology = (await client.get("/api/v1/global/topology")).json()["data"]

        assert [camera["display_id"] for camera in topology["cameras"]] == ["CAM-01", "CAM-02"]
        assert topology["cameras"][1]["role"] == "QUEUE"
        assert {(zone["camera_id"], zone["zone_id"]) for zone in topology["zones"]} == {
            ("cam-01", "entrance"),
            ("cam-02", "queue-b"),
        }
        assert topology["links"] == []

    async def test_a_link_across_cameras_is_saved_and_marked_as_such(
        self, client: AsyncClient
    ) -> None:
        await client.put("/api/v1/cameras/cam-01/zones", json={"zones": [ENTRANCE_ZONE]})
        await client.put("/api/v1/cameras/cam-02/zones", json={"zones": [QUEUE_ZONE]})

        response = await client.put(
            "/api/v1/global/topology",
            json={
                "links": [
                    {
                        "from_camera_id": "CAM-01",
                        "from_zone_id": "entrance",
                        "to_camera_id": "cam-02",
                        "to_zone_id": "queue-b",
                    }
                ]
            },
        )

        assert response.status_code == 200
        (saved,) = response.json()["data"]["links"]
        assert saved["link_id"] == "cam-01:entrance->cam-02:queue-b"
        assert saved["crosses_cameras"] is True
        again = (await client.get("/api/v1/global/topology")).json()["data"]
        assert again["links"] == [saved]

    async def test_a_link_must_name_zones_that_exist(self, client: AsyncClient) -> None:
        await client.put("/api/v1/cameras/cam-01/zones", json={"zones": [ENTRANCE_ZONE]})

        unknown_zone = await client.put(
            "/api/v1/global/topology",
            json={"links": [link("cam-01", "entrance", "cam-02", "nowhere")]},
        )
        unknown_camera = await client.put(
            "/api/v1/global/topology",
            json={"links": [link("cam-09", "entrance", "cam-01", "entrance")]},
        )

        assert unknown_zone.status_code == 400
        assert "CAM-02 has no zone 'nowhere'" in unknown_zone.json()["message"]
        assert unknown_camera.status_code == 400

    async def test_a_zone_cannot_feed_itself(self, client: AsyncClient) -> None:
        await client.put("/api/v1/cameras/cam-01/zones", json={"zones": [ENTRANCE_ZONE]})

        response = await client.put(
            "/api/v1/global/topology",
            json={"links": [link("cam-01", "entrance", "cam-01", "entrance")]},
        )
        assert response.status_code == 400

    async def test_a_saved_link_is_measured_as_a_correlation(
        self, app: FastAPI, client: AsyncClient
    ) -> None:
        await client.put("/api/v1/cameras/cam-01/zones", json={"zones": [ENTRANCE_ZONE]})
        await client.put("/api/v1/cameras/cam-02/zones", json={"zones": [QUEUE_ZONE]})
        await client.put(
            "/api/v1/global/topology",
            json={"links": [link("cam-01", "entrance", "cam-02", "queue-b")]},
        )
        await feed(app, "cam-01", person_count=3)
        await feed(app, "cam-02", person_count=4)
        connected(app, "cam-01", "cam-02")
        app.state.site_intelligence.update_once()

        report = (await client.get("/api/v1/global/analytics")).json()["data"]

        (measured,) = report["flow_links"]
        assert measured["basis"] == "CORRELATED"
        assert measured["tracked_rate_per_min"] is None
        assert {node["node_id"] for node in report["flow_nodes"]} == {
            "cam-01:entrance",
            "cam-02:queue-b",
        }


def test_site_updates_reach_the_command_center(app: FastAPI) -> None:
    base = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)

    with TestClient(app) as client, client.websocket_connect("/ws/command-center") as socket:
        snapshot = socket.receive_json()
        assert snapshot["data"]["site"] is None

        portal = client.portal  # type: ignore[attr-defined]
        sink = app.state.camera_manager.require("cam-02").sink

        async def update() -> None:
            for step in range(3):
                await sink.emit(
                    make_perception_result(
                        camera_id="cam-02",
                        frame_seq=step,
                        person_count=4,
                        frame_ts=base + timedelta(seconds=step),
                    )
                )
            await app.state.event_bus.drain()
            connected(app, "cam-02")
            app.state.site_intelligence.update_once()
            await app.state.event_bus.drain()

        portal.call(update)

        site = None
        for _ in range(12):
            envelope = json.loads(socket.receive_text())
            if envelope["type"] == "site.updated":
                site = envelope["data"]
                break

    assert site is not None, "the site report was not pushed"
    assert site["headcount"]["value"] == 4
    assert site["headcount"]["missing_camera_ids"] == ["cam-01"]
