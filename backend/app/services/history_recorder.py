"""Aggregated observation history - the `history_*` settings, implemented.

Every analysis window a camera produces, and every site update, is folded into a
bucket (thirty seconds by default). When a bucket closes it is written as one
row: how stable the crowd was and for how long in each band, how many people,
how long the queues. Nothing else is stored - no frames, no images, no tracks.

**Never on the analysis path's clock.** Accumulating is arithmetic on the event
loop; writing happens in a task of its own, a failed write is logged and
dropped, and nothing here can slow or stop frame analysis (``04:838-849``).

**Late and restarted buckets.** A window that arrives for a bucket already
closed is dropped rather than reopening it. A bucket written twice - the backend
restarted inside one - is merged into the row already stored, sample-weighted,
so the record stays one row per bucket.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select
from surgeguard_ai.contracts import (
    AnalysisResult,
    CountMethod,
    OperationalStatus,
    SiteReport,
)

from ..core.config import Settings
from ..core.event_bus import DomainEvent, EventBus
from ..core.logging import get_logger
from ..db.session import DatabaseManager
from ..models.history import SITE_HISTORY_ID, ObservationBucket

__all__ = ["BucketAccumulator", "HistoryRecorder", "bucket_start_for"]

logger = get_logger(__name__)

#: How often open buckets are checked for having closed without a successor -
#: a camera that went silent still has its last bucket written.
SWEEP_INTERVAL_SECONDS = 10.0
#: Extra time a bucket is held open past its end for a late window.
CLOSE_GRACE_SECONDS = 5.0
#: How often rows past retention are deleted.
PRUNE_INTERVAL = timedelta(hours=6)

_STATUS_RANK = {status: status.severity_rank for status in OperationalStatus}


def bucket_start_for(moment: datetime, bucket_seconds: int) -> datetime:
    """The UTC start of the bucket containing ``moment``."""
    utc = moment.astimezone(UTC)
    epoch = int(utc.timestamp())
    return datetime.fromtimestamp(epoch - epoch % bucket_seconds, tz=UTC)


class _Mean:
    """A running mean that knows how many values it has seen."""

    __slots__ = ("count", "total")

    def __init__(self) -> None:
        self.total = 0.0
        self.count = 0

    def add(self, value: float | None) -> None:
        if value is None:
            return
        self.total += value
        self.count += 1

    @property
    def value(self) -> float | None:
        return self.total / self.count if self.count else None


def _max(current: float | None, value: float | None) -> float | None:
    if value is None:
        return current
    return value if current is None else max(current, value)


def _min(current: float | None, value: float | None) -> float | None:
    if value is None:
        return current
    return value if current is None else min(current, value)


class BucketAccumulator:
    """One camera's - or the site's - running totals for one bucket."""

    def __init__(
        self, camera_id: str, bucket_start: datetime, bucket_seconds: int, source_mode: str
    ) -> None:
        self.camera_id = camera_id
        self.bucket_start = bucket_start
        self.bucket_seconds = bucket_seconds
        self.source_mode = source_mode

        self.samples = 0
        self.degraded_samples = 0
        self.csi = _Mean()
        self.csi_min: float | None = None
        self.csi_max: float | None = None
        self.status_samples: dict[str, int] = {}
        self.status_worst: OperationalStatus | None = None
        self.status_last: OperationalStatus | None = None
        self.confidence = _Mean()
        self.people = _Mean()
        self.people_max: float | None = None
        self.estimated_samples = 0
        self.density_max: float | None = None
        self.density_is_metric: bool | None = None
        self.queue_length = _Mean()
        self.queue_length_max: float | None = None
        self.wait = _Mean()
        self.wait_max: float | None = None
        self.arrival = _Mean()
        self.service = _Mean()
        self.cameras_contributing_min: int | None = None

    @property
    def bucket_end(self) -> datetime:
        return self.bucket_start + timedelta(seconds=self.bucket_seconds)

    # -- Folding in ---------------------------------------------------------

    def add_analysis(self, analysis: AnalysisResult) -> None:
        self.samples += 1
        if analysis.degraded:
            self.degraded_samples += 1

        stability = analysis.stability
        self.csi.add(stability.csi_smoothed)
        self.csi_min = _min(self.csi_min, stability.csi_smoothed)
        self.csi_max = _max(self.csi_max, stability.csi_smoothed)
        status = stability.status
        self.status_samples[status.value] = self.status_samples.get(status.value, 0) + 1
        if self.status_worst is None or _STATUS_RANK[status] > _STATUS_RANK[self.status_worst]:
            self.status_worst = status
        self.status_last = status
        self.confidence.add(stability.confidence.value)

        crowd = analysis.crowd
        self.people.add(float(crowd.person_count))
        self.people_max = _max(self.people_max, float(crowd.person_count))
        if crowd.count_method is CountMethod.ESTIMATED:
            self.estimated_samples += 1
        self.density_max = _max(self.density_max, crowd.density_max)
        self.density_is_metric = crowd.is_metric

        queue = analysis.queue
        if queue is not None and not queue.unconfigured and queue.queues:
            waiting = float(queue.total_waiting)
            self.queue_length.add(waiting)
            self.queue_length_max = _max(self.queue_length_max, waiting)
            waits = [item.wait.minutes for item in queue.queues if item.wait.minutes is not None]
            if waits:
                worst = max(waits)
                self.wait.add(worst)
                self.wait_max = _max(self.wait_max, worst)
            self.arrival.add(sum(item.flow.arrival_rate_per_min for item in queue.queues))
            self.service.add(sum(item.flow.service_rate_per_min for item in queue.queues))

    def add_site(self, report: SiteReport) -> None:
        self.samples += 1
        if report.degraded:
            self.degraded_samples += 1
        self.cameras_contributing_min = (
            report.cameras_contributing
            if self.cameras_contributing_min is None
            else min(self.cameras_contributing_min, report.cameras_contributing)
        )

        # A site with no contributing camera has no figure, and none is invented.
        if report.headcount.value is not None:
            self.people.add(float(report.headcount.value))
            self.people_max = _max(self.people_max, float(report.headcount.value))

        queue = report.queue
        if queue is not None:
            self.queue_length.add(float(queue.queue_length))
            self.queue_length_max = _max(self.queue_length_max, float(queue.queue_length))
            if queue.wait_minutes is not None:
                self.wait.add(queue.wait_minutes)
                self.wait_max = _max(self.wait_max, queue.wait_minutes)
            self.arrival.add(queue.arrival_rate_per_min)
            self.service.add(queue.service_rate_per_min)

    # -- Writing ------------------------------------------------------------

    def to_row(self) -> dict[str, Any]:
        people_max = self.people_max
        queue_max = self.queue_length_max
        return {
            "camera_id": self.camera_id,
            "bucket_start": self.bucket_start,
            "bucket_seconds": self.bucket_seconds,
            "source_mode": self.source_mode,
            "samples": self.samples,
            "degraded_samples": self.degraded_samples,
            "csi_mean": self.csi.value,
            "csi_min": self.csi_min,
            "csi_max": self.csi_max,
            "status_worst": self.status_worst.value if self.status_worst else None,
            "status_last": self.status_last.value if self.status_last else None,
            "status_samples": dict(self.status_samples) or None,
            "confidence_mean": self.confidence.value,
            "people_mean": self.people.value,
            "people_max": int(people_max) if people_max is not None else None,
            "estimated_samples": self.estimated_samples,
            "density_max": self.density_max,
            "density_is_metric": self.density_is_metric,
            "queue_length_mean": self.queue_length.value,
            "queue_length_max": int(queue_max) if queue_max is not None else None,
            "wait_minutes_mean": self.wait.value,
            "wait_minutes_max": self.wait_max,
            "arrival_rate_mean": self.arrival.value,
            "service_rate_mean": self.service.value,
            "cameras_contributing_min": self.cameras_contributing_min,
        }


def _weighted(a: float | None, a_weight: int, b: float | None, b_weight: int) -> float | None:
    if a is None:
        return b
    if b is None:
        return a
    total = a_weight + b_weight
    return (a * a_weight + b * b_weight) / total if total else a


def merge_into(row: ObservationBucket, values: dict[str, Any]) -> None:
    """Fold a second write for the same bucket into the stored row."""
    old, new = row.samples, int(values["samples"])
    for mean_field in (
        "csi_mean",
        "confidence_mean",
        "people_mean",
        "queue_length_mean",
        "wait_minutes_mean",
        "arrival_rate_mean",
        "service_rate_mean",
    ):
        setattr(row, mean_field, _weighted(getattr(row, mean_field), old, values[mean_field], new))
    for low in ("csi_min",):
        setattr(row, low, _min(getattr(row, low), values[low]))
    for high in ("csi_max", "people_max", "density_max", "queue_length_max", "wait_minutes_max"):
        merged = _max(getattr(row, high), values[high])
        setattr(row, high, merged)
    if values["cameras_contributing_min"] is not None:
        row.cameras_contributing_min = (
            values["cameras_contributing_min"]
            if row.cameras_contributing_min is None
            else min(row.cameras_contributing_min, values["cameras_contributing_min"])
        )
    counts = dict(row.status_samples or {})
    for status, count in (values["status_samples"] or {}).items():
        counts[status] = counts.get(status, 0) + count
    row.status_samples = counts or None
    worst_candidates = [status for status in (row.status_worst, values["status_worst"]) if status]
    if worst_candidates:
        row.status_worst = max(
            worst_candidates, key=lambda status: _STATUS_RANK[OperationalStatus(status)]
        )
    row.status_last = values["status_last"] or row.status_last
    row.samples = old + new
    row.degraded_samples += int(values["degraded_samples"])
    row.estimated_samples += int(values["estimated_samples"])
    if values["density_is_metric"] is not None:
        row.density_is_metric = values["density_is_metric"]


class HistoryRecorder:
    """Writes bucketed history for every camera and the site."""

    def __init__(
        self,
        settings: Settings,
        database: DatabaseManager,
        event_bus: EventBus,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._settings = settings
        self._database = database
        self._event_bus = event_bus
        self._clock = clock or (lambda: datetime.now(UTC))
        self._bucket_seconds = settings.history_bucket_seconds
        self._open: dict[tuple[str, str], BucketAccumulator] = {}
        self._writes: set[asyncio.Task[None]] = set()
        self._sweeper: asyncio.Task[None] | None = None
        self._subscribed = False
        self._failures = 0

    @property
    def enabled(self) -> bool:
        return self._settings.history_enabled

    @property
    def failures(self) -> int:
        """Bucket writes that failed and were dropped."""
        return self._failures

    # -- Lifecycle ----------------------------------------------------------

    def start(self) -> None:
        if not self.enabled or self._subscribed:
            return
        self._event_bus.subscribe(DomainEvent.ANALYSIS_RECEIVED, self.handle_analysis)
        self._event_bus.subscribe(DomainEvent.SITE_UPDATED, self.handle_site)
        self._subscribed = True
        self._sweeper = asyncio.create_task(self._sweep(), name="history-sweeper")
        logger.info(
            "History recording started",
            extra={
                "bucket_seconds": self._bucket_seconds,
                "retention_days": self._settings.history_retention_days,
            },
        )

    async def stop(self) -> None:
        """Stop recording and write whatever is still open."""
        if self._subscribed:
            self._event_bus.unsubscribe(DomainEvent.ANALYSIS_RECEIVED, self.handle_analysis)
            self._event_bus.unsubscribe(DomainEvent.SITE_UPDATED, self.handle_site)
            self._subscribed = False
        if self._sweeper is not None:
            self._sweeper.cancel()
            await asyncio.gather(self._sweeper, return_exceptions=True)
            self._sweeper = None
        pending, self._open = list(self._open.values()), {}
        for accumulator in pending:
            await self._write(accumulator)
        if self._writes:
            await asyncio.gather(*self._writes, return_exceptions=True)

    # -- Folding in (event handlers; synchronous so windows stay in order) --------

    def handle_analysis(self, analysis: AnalysisResult) -> None:
        try:
            self._fold(
                analysis.camera_id,
                analysis.source_mode.value,
                analysis.produced_at,
                lambda accumulator: accumulator.add_analysis(analysis),
            )
        except Exception as error:  # noqa: BLE001 - history must never affect analysis
            logger.warning("History could not record an analysis window", exc_info=error)

    def handle_site(self, report: SiteReport) -> None:
        try:
            modes = {camera.source_mode for camera in report.cameras if camera.source_mode}
            mode = (
                next(iter(modes)).value
                if len(modes) == 1
                else self._settings.pipeline_source_mode.value
            )
            self._fold(
                SITE_HISTORY_ID,
                mode,
                report.generated_at,
                lambda accumulator: accumulator.add_site(report),
            )
        except Exception as error:  # noqa: BLE001
            logger.warning("History could not record a site update", exc_info=error)

    def _fold(
        self,
        camera_id: str,
        source_mode: str,
        moment: datetime,
        add: Callable[[BucketAccumulator], None],
    ) -> None:
        start = bucket_start_for(moment, self._bucket_seconds)
        key = (camera_id, source_mode)
        accumulator = self._open.get(key)
        if accumulator is not None and accumulator.bucket_start != start:
            if start < accumulator.bucket_start:
                return  # a late window for a bucket already moved past
            self._schedule_write(self._open.pop(key))
            accumulator = None
        if accumulator is None:
            accumulator = BucketAccumulator(camera_id, start, self._bucket_seconds, source_mode)
            self._open[key] = accumulator
        add(accumulator)

    # -- Writing --------------------------------------------------------------

    def _schedule_write(self, accumulator: BucketAccumulator) -> None:
        task = asyncio.create_task(self._write(accumulator))
        self._writes.add(task)
        task.add_done_callback(self._writes.discard)

    async def _write(self, accumulator: BucketAccumulator) -> None:
        if accumulator.samples == 0:
            return
        values = accumulator.to_row()
        try:
            async with self._database.session() as session:
                existing = await session.scalar(
                    select(ObservationBucket).where(
                        ObservationBucket.camera_id == values["camera_id"],
                        ObservationBucket.bucket_start == values["bucket_start"],
                        ObservationBucket.bucket_seconds == values["bucket_seconds"],
                        ObservationBucket.source_mode == values["source_mode"],
                    )
                )
                if existing is None:
                    session.add(ObservationBucket(**values, created_at=self._clock()))
                else:
                    merge_into(existing, values)
        except Exception as error:  # noqa: BLE001 - a lost bucket is a gap, not an outage
            self._failures += 1
            logger.warning(
                "A history bucket could not be written",
                exc_info=error,
                extra={"camera_id": accumulator.camera_id},
            )

    async def flush_due(self, now: datetime | None = None) -> int:
        """Write every open bucket that has ended. Returns how many were written."""
        reference = now or self._clock()
        grace = timedelta(seconds=CLOSE_GRACE_SECONDS)
        due = [key for key, item in self._open.items() if item.bucket_end + grace <= reference]
        for key in due:
            await self._write(self._open.pop(key))
        return len(due)

    async def prune(self, now: datetime | None = None) -> int:
        """Delete rows older than the retention window. Returns how many were deleted."""
        reference = now or self._clock()
        cutoff = reference - timedelta(days=self._settings.history_retention_days)
        try:
            async with self._database.session() as session:
                result = await session.execute(
                    delete(ObservationBucket).where(ObservationBucket.bucket_start < cutoff)
                )
                deleted = int(result.rowcount or 0)
        except Exception as error:  # noqa: BLE001
            logger.warning("History pruning failed", exc_info=error)
            return 0
        if deleted:
            logger.info("Pruned history past retention", extra={"deleted": deleted})
        return deleted

    async def _sweep(self) -> None:
        last_prune: datetime | None = None
        while True:
            await asyncio.sleep(SWEEP_INTERVAL_SECONDS)
            now = self._clock()
            try:
                await self.flush_due(now)
                if last_prune is None or now - last_prune >= PRUNE_INTERVAL:
                    await self.prune(now)
                    last_prune = now
            except Exception as error:  # noqa: BLE001 - the sweeper must outlive one bad pass
                logger.warning("History sweep failed", exc_info=error)
