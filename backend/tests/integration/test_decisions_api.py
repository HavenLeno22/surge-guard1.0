"""The decision endpoints and the realtime path.

Driven through the application's own ingest sink, so the whole chain runs:
sink → perception event → assessment → analysis event → decision service →
timeline → realtime publisher. A test that called a service directly would pass
while the wiring was wrong, which is the one defect these are for.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import AsyncClient

from app.core.config import Environment, Settings
from app.realtime.connection_manager import ConnectionManager

from ..conftest import make_perception_result


@pytest.fixture
def settings(tmp_path) -> Settings:
    """Analysis and decisions on, camera off, reporting ungated by time.

    ``ode_report_min_interval_seconds=0`` removes only the *timer*; the
    material-change gate still applies, so a test cannot accidentally assert on
    reports the engine would not otherwise issue.
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
        ode_enabled=True,
        ode_report_min_interval_seconds=0.0,
    )


async def feed(
    app: FastAPI,
    *,
    frames: int = 40,
    calm_frames: int = 15,
    calm_count: int = 4,
    busy_count: int = 30,
) -> None:
    """Deliver a calm run then a crowding run, through the real ingest sink."""
    sink = app.state.perception_sink
    base = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)

    for step in range(frames):
        count = calm_count if step < calm_frames else busy_count
        await sink.emit(
            make_perception_result(
                frame_seq=step,
                person_count=count,
                frame_ts=base + timedelta(seconds=step),
            )
        )
    await app.state.event_bus.drain()


# ---------------------------------------------------------------------------
# Availability
# ---------------------------------------------------------------------------


async def test_no_guidance_yet_is_reported_as_unavailable(client: AsyncClient) -> None:
    """503 rather than a success carrying null.

    "No guidance available" and "no action required" are different answers, and
    a caller that cannot tell them apart will display one as the other.
    """
    response = await client.get("/api/v1/decisions/current")

    assert response.status_code == 503
    assert response.json()["data"] is None


async def test_the_timeline_is_answerable_before_anything_happens(
    client: AsyncClient,
) -> None:
    """An empty timeline is a fact, not a failure."""
    response = await client.get("/api/v1/decisions/timeline")

    assert response.status_code == 200
    data = response.json()["data"]
    # Startup itself is recorded, so the session always has a beginning.
    assert data["total"] >= 1
    assert data["latest_sequence"] >= 1


class TestDisabled:
    """The Operational Decision Engine switched off."""

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
            csi_enabled=True,
            ode_enabled=False,
        )

    async def test_no_guidance_is_produced(self, client: AsyncClient, app: FastAPI) -> None:
        await feed(app)
        assert (await client.get("/api/v1/decisions/current")).status_code == 503

    async def test_the_assessment_still_runs(
        self, client: AsyncClient, app: FastAPI
    ) -> None:
        """Measurement is useful without guidance, and must not depend on it."""
        await feed(app)
        assert (await client.get("/api/v1/intelligence/current")).status_code == 200


# ---------------------------------------------------------------------------
# Guidance
# ---------------------------------------------------------------------------


async def test_the_current_report_carries_a_complete_decision(
    client: AsyncClient, app: FastAPI
) -> None:
    """Every field the Operational Intelligence Report is specified to carry."""
    await feed(app)
    response = await client.get("/api/v1/decisions/current")

    assert response.status_code == 200
    data = response.json()["data"]
    report = data["report"]

    assert report["sequence"] >= 1
    assert report["revision"] >= 1
    assert report["status"] in {
        "STABLE",
        "OBSERVE",
        "ATTENTION_REQUIRED",
        "HIGH_ALERT",
        "CRITICAL",
    }
    assert report["priority"] in {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
    assert 0.0 <= report["csi"] <= 100.0
    assert 0.0 <= report["confidence"] <= 1.0
    assert report["situation_summary"].strip()
    assert data["operational_state"] in {
        "MONITORING",
        "OBSERVING",
        "INVESTIGATING",
        "RESPONDING",
        "RECOVERING",
    }


async def test_every_recommendation_is_traceable(
    client: AsyncClient, app: FastAPI
) -> None:
    """Rule identifier, cited indicators and a rationale on every action.

    This is what makes guidance auditable after an incident rather than merely
    persuasive during one (``18:99-109``).
    """
    await feed(app)
    report = (await client.get("/api/v1/decisions/current")).json()["data"]["report"]

    assert report["recommended_actions"]
    for action in report["recommended_actions"]:
        assert action["rule_id"]
        assert action["supporting_indicators"]
        assert action["rationale"].strip()
        assert action["action"].strip()
        assert 0.0 <= action["confidence"] <= 1.0
        assert action["urgency"] in {"LOW", "MEDIUM", "HIGH", "CRITICAL"}


async def test_primary_causes_and_evidence_accompany_the_report(
    client: AsyncClient, app: FastAPI
) -> None:
    """A stored report stays self-explanatory after the live evidence moves on."""
    await feed(app)
    report = (await client.get("/api/v1/decisions/current")).json()["data"]["report"]

    assert report["primary_causes"]
    assert report["supporting_evidence"]
    assert report["dominant_contributor_statement"]


async def test_the_history_is_a_revision_series(
    client: AsyncClient, app: FastAPI
) -> None:
    await feed(app)
    data = (await client.get("/api/v1/decisions/history")).json()["data"]

    assert data["total"] >= 1
    sequences = [report["sequence"] for report in data["reports"]]
    assert sequences == sorted(sequences, reverse=True)


async def test_the_retained_report_history_is_bounded(
    client: AsyncClient, app: FastAPI
) -> None:
    """A control-room process runs for a shift.

    An unbounded list of reports is a slow leak, and this one was unbounded -
    the engine's own history was capped while the backend's copy was not.
    """
    decisions = app.state.decisions
    limit = decisions._history.maxlen  # noqa: SLF001 - asserting the bound itself

    await feed(app, frames=200, calm_frames=20, busy_count=40)

    assert limit is not None
    assert len(decisions._history) <= limit  # noqa: SLF001


async def test_guidance_is_reported_stale_once_analysis_stops(
    client: AsyncClient, app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A report frozen at a reassuring value must say that it is frozen.

    Guidance is legitimately older than an assessment - it is reissued only on
    a material change - so staleness is measured from the *analysis* stream.
    That was previously ANDed against a condition which stopped holding after
    the first frame, leaving `is_stale` permanently false: the platform could
    never report frozen guidance, which is the exact silent-staleness failure
    it exists to prevent.
    """
    await feed(app)

    fresh = (await client.get("/api/v1/decisions/current")).json()["data"]
    assert fresh["is_stale"] is False

    # Wind the clock past the staleness threshold without delivering anything.
    decisions = app.state.decisions
    stale_at = decisions._last_analysis_at - timedelta(seconds=30)  # noqa: SLF001
    monkeypatch.setattr(decisions, "_last_analysis_at", stale_at, raising=False)

    stale = (await client.get("/api/v1/decisions/current")).json()["data"]
    assert stale["is_stale"] is True


# ---------------------------------------------------------------------------
# Timeline
# ---------------------------------------------------------------------------


async def test_operational_events_reach_the_timeline(
    client: AsyncClient, app: FastAPI
) -> None:
    """Status changes and issued recommendations are both recorded."""
    await feed(app)
    entries = (await client.get("/api/v1/decisions/timeline")).json()["data"]["entries"]

    kinds = {entry["entry_type"] for entry in entries}
    assert "STATUS_CHANGE" in kinds
    assert "SYSTEM" in kinds

    titles = " | ".join(entry["title"] for entry in entries)
    assert "Operational Status" in titles


async def test_the_timeline_is_ordered_newest_first_by_sequence(
    client: AsyncClient, app: FastAPI
) -> None:
    await feed(app)
    entries = (await client.get("/api/v1/decisions/timeline")).json()["data"]["entries"]

    sequences = [entry["sequence"] for entry in entries]
    assert sequences == sorted(sequences, reverse=True)


async def test_unchanged_guidance_is_not_relogged(
    client: AsyncClient, app: FastAPI
) -> None:
    """A report reissued on the timer carries the same actions.

    Logging it again would fill the timeline with repetition and bury the
    moment guidance actually changed.
    """
    await feed(app, frames=60, calm_frames=15)
    entries = (await client.get("/api/v1/decisions/timeline")).json()["data"]["entries"]

    recommendations = [
        entry["title"] for entry in entries if entry["title"].startswith("Recommendation issued")
    ]
    assert len(recommendations) == len(set(recommendations))


# ---------------------------------------------------------------------------
# Realtime
# ---------------------------------------------------------------------------


def test_the_snapshot_carries_every_section_a_client_needs(app: FastAPI) -> None:
    """A client that connects late is immediately correct, not waiting for an update."""
    with TestClient(app) as client, client.websocket_connect("/ws/command-center") as socket:
        envelope = socket.receive_json()

    assert envelope["type"] == "snapshot"
    assert envelope["seq"] == 0

    data = envelope["data"]
    for section in (
        "health",
        "pipeline",
        "perception",
        "assessment",
        "report",
        "operational_state",
        "timeline",
        "timeline_sequence",
        "stale_after_seconds",
    ):
        assert section in data

    # Derived from the server's own heartbeat, so the two cannot be configured
    # into disagreement and raise the stale banner on a healthy connection.
    assert data["stale_after_seconds"] > 0


def test_the_snapshot_carries_perception_for_the_camera_panel(app: FastAPI) -> None:
    """Every panel's data must survive the handover from polling to push.

    The Live Camera panel reads the perception slice, which only REST supplied.
    Once polling began suspending itself on connect, the largest panel on the
    screen went blank the moment the socket came up - the regression this
    asserts against.
    """
    base = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)

    with TestClient(app) as client:
        portal = client.portal  # type: ignore[attr-defined]
        for step in range(5):
            portal.call(
                app.state.perception_sink.emit,
                make_perception_result(
                    frame_seq=step,
                    person_count=4,
                    frame_ts=base + timedelta(seconds=step),
                ),
            )
        portal.call(app.state.event_bus.drain)

        with client.websocket_connect("/ws/command-center") as socket:
            snapshot = socket.receive_json()

    perception = snapshot["data"]["perception"]
    assert perception is not None
    assert perception["result"]["person_count"] == 4
    assert "is_stale" in perception


def test_perception_is_pushed_to_a_connected_client(app: FastAPI) -> None:
    """The Live Camera panel stays live on the socket, not only via the snapshot."""
    base = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)

    with TestClient(app) as client, client.websocket_connect("/ws/command-center") as socket:
        socket.receive_json()  # snapshot

        portal = client.portal  # type: ignore[attr-defined]
        for step in range(10):
            portal.call(
                app.state.perception_sink.emit,
                make_perception_result(
                    frame_seq=step,
                    person_count=6,
                    frame_ts=base + timedelta(seconds=step),
                ),
            )
        portal.call(app.state.event_bus.drain)

        seen: set[str] = set()
        for _ in range(8):
            seen.add(json.loads(socket.receive_text())["type"])
            if "detections.updated" in seen:
                break

    assert "detections.updated" in seen


def test_assessments_and_guidance_are_pushed_to_a_connected_client(
    app: FastAPI,
) -> None:
    """The socket is the primary path, and carries the whole operational picture."""
    base = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)

    with TestClient(app) as client, client.websocket_connect("/ws/command-center") as socket:
        socket.receive_json()  # snapshot

        sink = app.state.perception_sink
        portal = client.portal  # type: ignore[attr-defined]
        for step in range(30):
            count = 4 if step < 10 else 30
            portal.call(
                sink.emit,
                make_perception_result(
                    frame_seq=step,
                    person_count=count,
                    frame_ts=base + timedelta(seconds=step),
                ),
            )
        portal.call(app.state.event_bus.drain)

        seen: set[str] = set()
        sequences: list[int] = []
        for _ in range(12):
            raw = socket.receive_text()
            envelope = json.loads(raw)
            seen.add(envelope["type"])
            sequences.append(envelope["seq"])
            if {"csi.updated", "oir.updated", "timeline.appended"} <= seen:
                break

    assert "csi.updated" in seen
    assert "oir.updated" in seen
    assert "timeline.appended" in seen

    # Monotonic per connection: a gap is what tells a client it missed a
    # message and should resynchronise.
    assert sequences == sorted(sequences)
    assert len(sequences) == len(set(sequences))


def test_a_resync_request_returns_a_fresh_snapshot(app: FastAPI) -> None:
    """A client that detected a gap asks for this rather than reconnecting."""
    with TestClient(app) as client, client.websocket_connect("/ws/command-center") as socket:
        first = socket.receive_json()
        socket.send_json({"action": "resync", "data": {}})
        second = socket.receive_json()

    assert first["type"] == "snapshot"
    assert second["type"] == "snapshot"
    # A resync does not restart numbering: the client learns it is current
    # again from the snapshot itself, and the sequence stays continuous.
    assert second["seq"] > first["seq"]


async def test_a_broadcast_failure_never_stops_analysis(
    client: AsyncClient, app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A socket problem is a socket problem, never a reason to stop analysing.

    The publisher runs on the event bus, whose ultimate upstream is the AI
    Pipeline (``04:838-849``).

    A client is simulated as connected before the failure is injected. Without
    that the publisher short-circuits on an empty client list, never reaches the
    broadcast, and the test would pass without exercising the isolation it
    claims to cover.
    """
    monkeypatch.setattr(ConnectionManager, "client_count", 1)

    async def explode(*_args, **_kwargs):
        raise RuntimeError("synthetic broadcast failure")

    monkeypatch.setattr(app.state.broadcaster, "publish", explode)

    await feed(app)

    assert (await client.get("/api/v1/intelligence/current")).status_code == 200
    assert (await client.get("/api/v1/decisions/current")).status_code == 200


async def test_nothing_is_serialised_when_no_client_is_listening(
    client: AsyncClient, app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Payloads are not built for an empty room.

    Serialising an assessment costs the same whether or not anyone is
    connected, and with nobody there it is work done entirely for the garbage
    collector. The ``client`` fixture runs the lifespan without opening a
    WebSocket, which is exactly the condition under test.
    """
    published: list[str] = []

    async def record(event_type, *_args, **_kwargs):
        published.append(event_type.value)

    monkeypatch.setattr(app.state.broadcaster, "publish", record)

    await feed(app, frames=20)

    assert published == []
