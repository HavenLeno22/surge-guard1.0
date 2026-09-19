"""The history routes, over buckets written directly."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import FastAPI
from httpx import AsyncClient

from app.models.history import ObservationBucket

NOW = datetime.now(UTC).replace(microsecond=0)
START = NOW - timedelta(hours=1)


async def _seed(app: FastAPI, rows: list[dict]) -> None:
    async with app.state.database.session() as session:
        for index, values in enumerate(rows):
            session.add(
                ObservationBucket(
                    camera_id=values.get("camera_id", "cam-01"),
                    bucket_start=values["bucket_start"],
                    bucket_seconds=30,
                    source_mode=values.get("source_mode", "LIVE"),
                    samples=values.get("samples", 10),
                    degraded_samples=0,
                    csi_mean=values.get("csi_mean"),
                    csi_min=values.get("csi_min"),
                    csi_max=values.get("csi_max"),
                    status_worst=values.get("status_worst"),
                    status_samples=values.get("status_samples"),
                    people_mean=values.get("people_mean"),
                    people_max=values.get("people_max"),
                    estimated_samples=values.get("estimated_samples", 0),
                    created_at=NOW + timedelta(seconds=index),
                )
            )


def _bucket(offset_seconds: int) -> datetime:
    """A bucket start inside the queried range, aligned to a whole minute.

    Rounded *up* from the range start, so the first bucket is never before it,
    and to a minute, so buckets 0 and 30 fall in the same 60-second point.
    """
    base = int(START.timestamp())
    base += (60 - base % 60) % 60
    return datetime.fromtimestamp(base + offset_seconds, tz=UTC)


async def test_a_series_combines_buckets_with_sample_weights(
    client: AsyncClient, app: FastAPI
) -> None:
    await _seed(
        app,
        [
            {
                "bucket_start": _bucket(0),
                "samples": 10,
                "csi_mean": 90.0,
                "csi_min": 85.0,
                "csi_max": 95.0,
                "status_worst": "STABLE",
                "status_samples": {"STABLE": 10},
                "people_mean": 10.0,
                "people_max": 12,
            },
            {
                "bucket_start": _bucket(30),
                "samples": 30,
                "csi_mean": 50.0,
                "csi_min": 40.0,
                "csi_max": 60.0,
                "status_worst": "ATTENTION_REQUIRED",
                "status_samples": {"OBSERVE": 10, "ATTENTION_REQUIRED": 20},
                "people_mean": 30.0,
                "people_max": 41,
                "estimated_samples": 15,
            },
        ],
    )

    response = await client.get(
        "/api/v1/history/cameras/cam-01",
        params={"from": START.isoformat(), "to": NOW.isoformat(), "resolution": 60},
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["resolution_seconds"] == 60
    assert len(data["points"]) == 1
    point = data["points"][0]
    assert point["samples"] == 40
    assert point["csi_mean"] == 60.0  # (90*10 + 50*30) / 40
    assert (point["csi_min"], point["csi_max"]) == (40.0, 95.0)
    assert point["status_worst"] == "ATTENTION_REQUIRED"
    assert point["status_samples"] == {"STABLE": 10, "OBSERVE": 10, "ATTENTION_REQUIRED": 20}
    assert point["people_max"] == 41
    assert point["estimated_share"] == 15 / 40


async def test_live_and_demonstration_history_are_never_mixed(
    client: AsyncClient, app: FastAPI
) -> None:
    await _seed(
        app,
        [
            {"bucket_start": _bucket(0), "csi_mean": 90.0, "source_mode": "LIVE"},
            {"bucket_start": _bucket(0), "csi_mean": 20.0, "source_mode": "DEMO"},
        ],
    )

    live = await client.get(
        "/api/v1/history/cameras/cam-01",
        params={"from": START.isoformat(), "to": NOW.isoformat(), "source_mode": "LIVE"},
    )
    demo = await client.get(
        "/api/v1/history/cameras/cam-01",
        params={"from": START.isoformat(), "to": NOW.isoformat(), "source_mode": "DEMO"},
    )

    assert [p["csi_mean"] for p in live.json()["data"]["points"]] == [90.0]
    assert [p["csi_mean"] for p in demo.json()["data"]["points"]] == [20.0]


async def test_the_summary_withholds_a_baseline_until_enough_is_recorded(
    client: AsyncClient, app: FastAPI
) -> None:
    camera_rows = [
        {"bucket_start": _bucket(offset * 30), "csi_mean": 80.0, "status_samples": {"STABLE": 10}}
        for offset in range(19)
    ]
    site_row = {"camera_id": "site", "bucket_start": _bucket(0), "people_max": 14}
    await _seed(app, [*camera_rows, site_row])
    params = {"from": START.isoformat(), "to": NOW.isoformat()}

    summary = (await client.get("/api/v1/history/summary", params=params)).json()["data"]
    camera = summary["cameras"][0]
    assert camera["buckets"] == 19
    assert camera["baseline_available"] is False
    assert camera["status_share"] == {"STABLE": 1.0}
    assert summary["site"]["people_max"] == 14

    await _seed(app, [{"bucket_start": _bucket(19 * 30), "csi_mean": 80.0}])
    summary = (await client.get("/api/v1/history/summary", params=params)).json()["data"]
    assert summary["cameras"][0]["baseline_available"] is True


async def test_an_empty_range_is_an_empty_series_not_zeroes(client: AsyncClient) -> None:
    response = await client.get("/api/v1/history/site")

    assert response.status_code == 200
    assert response.json()["data"]["points"] == []


async def test_an_unusable_range_is_rejected(client: AsyncClient) -> None:
    backwards = await client.get(
        "/api/v1/history/site", params={"from": NOW.isoformat(), "to": START.isoformat()}
    )
    assert backwards.status_code == 400

    too_long = await client.get(
        "/api/v1/history/site",
        params={"from": (NOW - timedelta(days=40)).isoformat(), "to": NOW.isoformat()},
    )
    assert too_long.status_code == 400


async def test_history_requires_sign_in(auth_client: AsyncClient) -> None:
    assert (await auth_client.get("/api/v1/history/summary")).status_code == 401
