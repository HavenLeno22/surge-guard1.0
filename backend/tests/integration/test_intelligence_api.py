"""The crowd intelligence endpoints.

Driven by handing perception results to the application's own ingest sink,
which is exactly what the AI Pipeline does. That is deliberate: it exercises
the real path - sink records state, dispatches the event, the intelligence
service picks it up as a subscriber - so a test cannot pass while the wiring is
wrong, which is the one defect a test calling the service directly would miss
entirely.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from surgeguard_ai.pipeline import AnalysisPipeline

from app.core.config import Environment, Settings

from ..conftest import make_perception_result


@pytest.fixture
def settings(tmp_path) -> Settings:
    """Test configuration with crowd analysis on and the camera off.

    The assessment layer needs no camera, no GPU and no model weights - it is
    arithmetic over tracks - so it can be exercised in full on any machine.
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
    )


async def feed(app: FastAPI, *, frames: int = 40, person_count: int = 6) -> None:
    """Deliver a run of perception results through the real ingest sink."""
    sink = app.state.perception_sink
    base = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)

    for step in range(frames):
        await sink.emit(
            make_perception_result(
                frame_seq=step,
                person_count=person_count,
                frame_ts=base + timedelta(seconds=step),
            )
        )
    await app.state.event_bus.drain()


# ---------------------------------------------------------------------------
# Availability
# ---------------------------------------------------------------------------


async def test_no_assessment_yet_is_reported_as_unavailable(client: AsyncClient) -> None:
    """503 rather than a success carrying null.

    "No assessment is available" and "the crowd is perfectly stable" are
    opposite facts, and a caller that cannot distinguish them will eventually
    display one as the other.
    """
    response = await client.get("/api/v1/intelligence/current")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "error"
    assert body["data"] is None
    assert "not produced" in body["message"]


async def test_evidence_history_is_answerable_before_any_analysis(
    client: AsyncClient,
) -> None:
    """An empty history is a fact, not a failure.

    A caller should not have to catch an error to learn that nothing has
    happened yet.
    """
    response = await client.get("/api/v1/intelligence/evidence/history")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["items"] == []
    assert data["total"] == 0
    assert data["analysed"] == 0


class TestDisabled:
    """Crowd analysis switched off entirely."""

    @pytest.fixture
    def settings(self, tmp_path) -> Settings:
        return Settings(
            auth_enabled=False,  # these tests cover behaviour, not sign-in
            _env_file=None,
            environment=Environment.DEVELOPMENT,
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}",
            log_level="WARNING",
            ws_heartbeat_seconds=3600.0,
            pipeline_enabled=False,
            csi_enabled=False,
        )

    async def test_a_disabled_analyser_says_so_rather_than_looking_like_a_slow_one(
        self, client: AsyncClient, app: FastAPI
    ) -> None:
        """A disabled analyser and a starting one call for different responses."""
        await feed(app)
        response = await client.get("/api/v1/intelligence/current")

        assert response.status_code == 503
        assert "disabled" in response.json()["message"]

    async def test_perception_still_flows_when_analysis_is_off(
        self, client: AsyncClient, app: FastAPI
    ) -> None:
        """The assessment layer is a subscriber, never a gate on ingest."""
        await feed(app)
        response = await client.get("/api/v1/perception/latest")

        assert response.status_code == 200


# ---------------------------------------------------------------------------
# A live assessment
# ---------------------------------------------------------------------------


async def test_the_current_assessment_reports_a_real_index(
    client: AsyncClient, app: FastAPI
) -> None:
    """Every figure traces to a measurement, and the breakdown proves it."""
    await feed(app)
    response = await client.get("/api/v1/intelligence/current")

    assert response.status_code == 200
    data = response.json()["data"]

    stability = data["stability"]
    assert 0.0 <= stability["csi_raw"] <= 100.0
    assert 0.0 <= stability["csi_smoothed"] <= 100.0
    assert stability["status"] in {
        "STABLE",
        "OBSERVE",
        "ATTENTION_REQUIRED",
        "HIGH_ALERT",
        "CRITICAL",
    }
    assert len(stability["breakdown"]["readings"]) == 5
    assert 0.0 <= stability["confidence"]["value"] <= 1.0
    assert len(stability["confidence"]["factors"]) == 3


async def test_the_assessment_carries_the_crowd_measurements_behind_it(
    client: AsyncClient, app: FastAPI
) -> None:
    await feed(app, person_count=6)
    data = (await client.get("/api/v1/intelligence/current")).json()["data"]

    assert data["crowd"]["person_count"] == 6
    assert data["crowd"]["count_method"] == "TRACKED"
    assert data["crowd"]["density_max"] >= 0.0
    assert data["camera_id"] == "cam-01"


async def test_an_uncalibrated_camera_is_reported_as_relative(
    client: AsyncClient, app: FastAPI
) -> None:
    """`is_metric` is what stops a relative figure being shown as persons/m2.

    The prototype's camera has no homography, so this must be false - and the
    interface has to be able to see that it is (Architecture Review C21).
    """
    await feed(app)
    data = (await client.get("/api/v1/intelligence/current")).json()["data"]

    assert data["crowd"]["is_metric"] is False


async def test_every_unavailable_indicator_states_why(
    client: AsyncClient, app: FastAPI
) -> None:
    """An operator is entitled to know the index rests on fewer than five inputs."""
    await feed(app)
    readings = (await client.get("/api/v1/intelligence/current")).json()["data"][
        "stability"
    ]["breakdown"]["readings"]

    for reading in readings:
        if not reading["available"]:
            assert reading["unavailable_reason"]
            assert reading["weight"] == 0.0
        else:
            assert reading["pressure"] is not None


async def test_the_assessment_reports_how_old_it_is(
    client: AsyncClient, app: FastAPI
) -> None:
    """A Crowd Stability Index frozen at a reassuring value without saying so is
    the single most dangerous thing this display can show."""
    await feed(app)
    data = (await client.get("/api/v1/intelligence/current")).json()["data"]

    assert data["age_seconds"] >= 0.0
    assert "is_stale" in data
    assert data["received_at"]


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------


async def test_evidence_accompanies_the_assessment_and_explains_it(
    client: AsyncClient, app: FastAPI
) -> None:
    """No observation appears without the measurement that produced it."""
    await feed(app)
    evidence = (await client.get("/api/v1/intelligence/current")).json()["data"]["evidence"]

    assert evidence is not None
    assert evidence["items"], "a calm scene still produces an observation"

    for item in evidence["items"]:
        assert item["headline"].strip()
        assert item["detail"].strip()
        assert 0.0 <= item["confidence"] <= 1.0
        assert item["severity"] in {"INFO", "WARNING", "CRITICAL"}
        assert item["observed_at"]


async def test_evidence_history_records_observations_as_they_appear(
    client: AsyncClient, app: FastAPI
) -> None:
    """One entry per onset, not one per analysis window."""
    await feed(app, frames=40)
    data = (await client.get("/api/v1/intelligence/evidence/history")).json()["data"]

    assert data["analysed"] == 40
    assert 0 < data["total"] < 40
    assert len(data["items"]) == data["total"]


async def test_evidence_history_is_newest_first(
    client: AsyncClient, app: FastAPI
) -> None:
    await feed(app, frames=40)
    items = (await client.get("/api/v1/intelligence/evidence/history")).json()["data"][
        "items"
    ]

    timestamps = [item["observed_at"] for item in items]
    assert timestamps == sorted(timestamps, reverse=True)


# ---------------------------------------------------------------------------
# Isolation
# ---------------------------------------------------------------------------


async def test_an_analysis_failure_never_stops_perception_ingest(
    client: AsyncClient, app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The assessment layer is downstream of the primary data path.

    A backend problem is a logged backend problem, never a reason to stop
    analysing frames (``04:838-849``). Fault-injected at the pipeline rather
    than mocked at the service, so the service's own isolation is what is under
    test.
    """

    def explode(self, result):  # noqa: ARG001 - signature must match
        raise RuntimeError("synthetic analysis failure")

    monkeypatch.setattr(AnalysisPipeline, "process", explode)

    await feed(app, frames=5)
    intelligence = app.state.crowd_intelligence

    assert intelligence.failures == 5
    assert intelligence.last_error

    # Perception is unaffected: the frames were recorded before the assessment
    # was even attempted.
    assert (await client.get("/api/v1/perception/latest")).status_code == 200
    assert (await client.get("/api/v1/intelligence/current")).status_code == 503


async def test_the_assessment_survives_a_frame_sequence_restart(
    client: AsyncClient, app: FastAPI
) -> None:
    """A looping clip resets analysis state rather than blending two crowds."""
    await feed(app, frames=30)
    before = (await client.get("/api/v1/intelligence/current")).json()["data"]

    await app.state.perception_sink.emit(
        make_perception_result(
            frame_seq=0,
            person_count=6,
            frame_ts=datetime(2026, 1, 1, 12, 1, 0, tzinfo=UTC),
        )
    )
    await app.state.event_bus.drain()

    after = (await client.get("/api/v1/intelligence/current")).json()["data"]

    assert after["frame_seq"] == 0
    # The smoothing window restarted, so the platform honestly knows less than
    # it did a frame ago.
    assert after["stability"]["confidence"]["value"] < before["stability"]["confidence"]["value"]
