"""Bucketed history: folding windows in, writing, merging and pruning."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select
from surgeguard_ai.contracts import OperationalStatus

from app.core.config import Environment, Settings
from app.core.event_bus import EventBus
from app.db.migrate import run_migrations
from app.db.session import DatabaseManager
from app.models.history import ObservationBucket
from app.services.history_recorder import BucketAccumulator, HistoryRecorder, bucket_start_for

T0 = datetime(2026, 9, 17, 10, 0, 5, tzinfo=UTC)


class FakeAnalysis:
    """Only the fields the recorder reads - enough to exercise the arithmetic."""

    def __init__(
        self,
        *,
        csi: float,
        status: OperationalStatus,
        people: int,
        produced_at: datetime = T0,
        camera_id: str = "cam-01",
        estimated: bool = False,
    ) -> None:
        from types import SimpleNamespace

        from surgeguard_ai.contracts import CountMethod, SourceMode

        self.camera_id = camera_id
        self.source_mode = SourceMode.LIVE
        self.produced_at = produced_at
        self.degraded = False
        self.stability = SimpleNamespace(
            csi_smoothed=csi, status=status, confidence=SimpleNamespace(value=0.8)
        )
        self.crowd = SimpleNamespace(
            person_count=people,
            count_method=CountMethod.ESTIMATED if estimated else CountMethod.TRACKED,
            density_max=1.5,
            is_metric=False,
        )
        self.queue = None


def test_bucket_start_is_the_utc_floor() -> None:
    assert bucket_start_for(T0, 30) == datetime(2026, 9, 17, 10, 0, 0, tzinfo=UTC)
    assert bucket_start_for(T0 + timedelta(seconds=25), 30) == datetime(
        2026, 9, 17, 10, 0, 30, tzinfo=UTC
    )


def test_an_accumulator_summarises_its_windows() -> None:
    accumulator = BucketAccumulator("cam-01", bucket_start_for(T0, 30), 30, "LIVE")
    for csi, status, people, estimated in (
        (90.0, OperationalStatus.STABLE, 10, False),
        (70.0, OperationalStatus.OBSERVE, 20, False),
        (50.0, OperationalStatus.ATTENTION_REQUIRED, 30, True),
    ):
        accumulator.add_analysis(
            FakeAnalysis(csi=csi, status=status, people=people, estimated=estimated)  # type: ignore[arg-type]
        )

    row = accumulator.to_row()
    assert row["samples"] == 3
    assert row["csi_mean"] == pytest.approx(70.0)
    assert (row["csi_min"], row["csi_max"]) == (50.0, 90.0)
    assert row["status_worst"] == "ATTENTION_REQUIRED"
    assert row["status_last"] == "ATTENTION_REQUIRED"
    assert row["status_samples"] == {"STABLE": 1, "OBSERVE": 1, "ATTENTION_REQUIRED": 1}
    assert row["people_mean"] == pytest.approx(20.0)
    assert row["people_max"] == 30
    assert row["estimated_samples"] == 1
    assert row["queue_length_mean"] is None  # no queue configured: a gap, not a zero


@pytest.fixture
async def database(tmp_path: Path) -> DatabaseManager:
    settings = Settings(
        _env_file=None,
        environment=Environment.DEVELOPMENT,
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'history.db'}",
        pipeline_enabled=False,
    )
    await run_migrations(settings.database_url)
    manager = DatabaseManager(settings)
    manager.connect()
    yield manager
    await manager.disconnect()


def _recorder(database: DatabaseManager, now: datetime) -> HistoryRecorder:
    settings = Settings(
        _env_file=None, pipeline_enabled=False, history_bucket_seconds=30, history_retention_days=30
    )
    return HistoryRecorder(settings, database, EventBus(), clock=lambda: now)


async def _rows(database: DatabaseManager) -> list[ObservationBucket]:
    async with database.session() as session:
        return list((await session.scalars(select(ObservationBucket))).all())


async def test_a_window_in_the_next_bucket_writes_the_previous_one(
    database: DatabaseManager,
) -> None:
    recorder = _recorder(database, T0)
    recorder.handle_analysis(FakeAnalysis(csi=80, status=OperationalStatus.STABLE, people=5))  # type: ignore[arg-type]
    recorder.handle_analysis(
        FakeAnalysis(
            csi=60,
            status=OperationalStatus.OBSERVE,
            people=9,
            produced_at=T0 + timedelta(seconds=40),
        )  # type: ignore[arg-type]
    )
    await recorder.stop()  # flushes the open bucket and waits for pending writes

    rows = sorted(await _rows(database), key=lambda row: row.bucket_start)
    assert [row.samples for row in rows] == [1, 1]
    assert rows[0].csi_mean == 80
    assert rows[1].status_worst == "OBSERVE"


async def test_a_late_window_for_a_closed_bucket_is_dropped(database: DatabaseManager) -> None:
    recorder = _recorder(database, T0)
    recorder.handle_analysis(
        FakeAnalysis(
            csi=80,
            status=OperationalStatus.STABLE,
            people=5,
            produced_at=T0 + timedelta(seconds=40),
        )  # type: ignore[arg-type]
    )
    recorder.handle_analysis(FakeAnalysis(csi=10, status=OperationalStatus.CRITICAL, people=99))  # type: ignore[arg-type]
    await recorder.stop()

    rows = await _rows(database)
    assert len(rows) == 1
    assert rows[0].status_worst == "STABLE"


async def test_writing_a_bucket_twice_merges_rather_than_duplicating(
    database: DatabaseManager,
) -> None:
    """A restart inside one bucket must still leave one row per bucket."""
    for csi, people in ((80.0, 10), (40.0, 30)):
        recorder = _recorder(database, T0)
        recorder.handle_analysis(
            FakeAnalysis(csi=csi, status=OperationalStatus.STABLE, people=people)  # type: ignore[arg-type]
        )
        await recorder.stop()

    rows = await _rows(database)
    assert len(rows) == 1
    assert rows[0].samples == 2
    assert rows[0].csi_mean == pytest.approx(60.0)
    assert (rows[0].csi_min, rows[0].csi_max) == (40.0, 80.0)
    assert rows[0].people_max == 30


async def test_a_silent_camera_still_has_its_last_bucket_written(
    database: DatabaseManager,
) -> None:
    recorder = _recorder(database, T0)
    recorder.handle_analysis(FakeAnalysis(csi=80, status=OperationalStatus.STABLE, people=5))  # type: ignore[arg-type]

    assert await recorder.flush_due(T0 + timedelta(seconds=10)) == 0
    assert await recorder.flush_due(T0 + timedelta(seconds=60)) == 1
    assert len(await _rows(database)) == 1


async def test_rows_past_retention_are_pruned(database: DatabaseManager) -> None:
    recorder = _recorder(database, T0)
    old = T0 - timedelta(days=40)
    recorder.handle_analysis(
        FakeAnalysis(csi=80, status=OperationalStatus.STABLE, people=5, produced_at=old)  # type: ignore[arg-type]
    )
    recorder.handle_analysis(FakeAnalysis(csi=80, status=OperationalStatus.STABLE, people=5))  # type: ignore[arg-type]
    await recorder.stop()

    assert await recorder.prune(T0) == 1
    async with database.session() as session:
        remaining = await session.scalar(select(func.count()).select_from(ObservationBucket))
    assert remaining == 1


async def test_a_failed_write_is_counted_and_never_raised(database: DatabaseManager) -> None:
    recorder = _recorder(database, T0)
    await database.disconnect()  # every write now fails
    recorder.handle_analysis(FakeAnalysis(csi=80, status=OperationalStatus.STABLE, people=5))  # type: ignore[arg-type]

    await recorder.stop()

    assert recorder.failures == 1
