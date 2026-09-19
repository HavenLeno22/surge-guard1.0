"""Reading stored history back.

Series are re-aggregated to the requested resolution here rather than in SQL:
the number of rows in a month of thirty-second buckets for a handful of cameras
is small, and one Python definition of "combine these buckets" - sample-weighted
means, true extremes, summed band counts - is easier to trust than the same
arithmetic restated in a query.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from surgeguard_ai.contracts import OperationalStatus, SourceMode

from ..core.config import Settings
from ..core.exceptions import ValidationError
from ..db.session import DatabaseManager
from ..models.history import SITE_HISTORY_ID, ObservationBucket
from ..schemas.history import (
    HistoryPoint,
    HistorySeriesRead,
    HistorySummaryItem,
    HistorySummaryRead,
)

__all__ = ["HistoryQuery", "MAX_RANGE", "MAX_POINTS"]

#: The longest range one request may cover. Retention defaults to 30 days.
MAX_RANGE = timedelta(days=31)
#: A chart has no use for more points than it has pixels to draw them on.
MAX_POINTS = 720

_RANK = {status.value: status.severity_rank for status in OperationalStatus}


@dataclass(slots=True)
class _Combined:
    samples: int = 0
    degraded: int = 0
    estimated: int = 0
    sums: dict[str, float] = field(default_factory=dict)
    weights: dict[str, int] = field(default_factory=dict)
    minimums: dict[str, float] = field(default_factory=dict)
    maximums: dict[str, float] = field(default_factory=dict)
    status_samples: dict[str, int] = field(default_factory=dict)
    status_worst: str | None = None
    density_is_metric: bool | None = None
    cameras_contributing_min: int | None = None
    first: datetime | None = None
    last: datetime | None = None
    rows: int = 0

    def add(self, row: ObservationBucket) -> None:
        self.rows += 1
        self.samples += row.samples
        self.degraded += row.degraded_samples
        self.estimated += row.estimated_samples
        for name in (
            "csi_mean",
            "confidence_mean",
            "people_mean",
            "queue_length_mean",
            "wait_minutes_mean",
            "arrival_rate_mean",
            "service_rate_mean",
        ):
            value = getattr(row, name)
            if value is not None:
                self.sums[name] = self.sums.get(name, 0.0) + value * row.samples
                self.weights[name] = self.weights.get(name, 0) + row.samples
        if row.csi_min is not None:
            self.minimums["csi"] = min(self.minimums.get("csi", row.csi_min), row.csi_min)
        for name, value in (
            ("csi", row.csi_max),
            ("people", row.people_max),
            ("density", row.density_max),
            ("queue", row.queue_length_max),
            ("wait", row.wait_minutes_max),
        ):
            if value is not None:
                self.maximums[name] = max(self.maximums.get(name, value), value)
        for status, count in (row.status_samples or {}).items():
            self.status_samples[status] = self.status_samples.get(status, 0) + int(count)
        if row.status_worst is not None and (
            self.status_worst is None or _RANK[row.status_worst] > _RANK[self.status_worst]
        ):
            self.status_worst = row.status_worst
        if row.density_is_metric is not None:
            self.density_is_metric = row.density_is_metric
        if row.cameras_contributing_min is not None:
            self.cameras_contributing_min = (
                row.cameras_contributing_min
                if self.cameras_contributing_min is None
                else min(self.cameras_contributing_min, row.cameras_contributing_min)
            )
        self.first = row.bucket_start if self.first is None else min(self.first, row.bucket_start)
        self.last = row.bucket_start if self.last is None else max(self.last, row.bucket_start)

    def mean(self, name: str) -> float | None:
        weight = self.weights.get(name, 0)
        return self.sums[name] / weight if weight else None

    def share(self, count: int) -> float:
        return min(1.0, count / self.samples) if self.samples else 0.0

    def maximum_int(self, name: str) -> int | None:
        value = self.maximums.get(name)
        return int(value) if value is not None else None


class HistoryQuery:
    """Series and summaries over stored buckets."""

    def __init__(self, database: DatabaseManager, settings: Settings) -> None:
        self._database = database
        self._settings = settings

    # -- Ranges ---------------------------------------------------------------

    def resolve_range(
        self, start: datetime | None, end: datetime | None
    ) -> tuple[datetime, datetime]:
        """Apply defaults and limits. Raises ``ValidationError`` for an unusable range."""
        resolved_end = _aware(end) if end is not None else datetime.now(UTC)
        resolved_start = (
            _aware(start) if start is not None else resolved_end - timedelta(hours=24)
        )
        if resolved_start >= resolved_end:
            raise ValidationError("The range must start before it ends.")
        if resolved_end - resolved_start > MAX_RANGE:
            raise ValidationError("A history range can cover at most 31 days.")
        return resolved_start, resolved_end

    def resolve_resolution(
        self, start: datetime, end: datetime, requested: int | None
    ) -> int:
        """A resolution that is a whole number of buckets and yields at most MAX_POINTS."""
        bucket = self._settings.history_bucket_seconds
        span = (end - start).total_seconds()
        minimum = max(bucket, math.ceil(span / MAX_POINTS / bucket) * bucket)
        if requested is None:
            return minimum
        rounded = max(bucket, math.ceil(requested / bucket) * bucket)
        return max(rounded, minimum)

    # -- Reads ----------------------------------------------------------------

    async def series(
        self,
        camera_id: str,
        *,
        start: datetime | None,
        end: datetime | None,
        resolution_seconds: int | None,
        source_mode: SourceMode | None,
    ) -> HistorySeriesRead:
        range_start, range_end = self.resolve_range(start, end)
        resolution = self.resolve_resolution(range_start, range_end, resolution_seconds)
        mode = source_mode or self._settings.pipeline_source_mode

        rows = await self._rows(range_start, range_end, mode, camera_id=camera_id)
        groups: dict[int, _Combined] = {}
        for row in rows:
            key = int(row.bucket_start.timestamp()) // resolution
            groups.setdefault(key, _Combined()).add(row)

        points = [
            _point(datetime.fromtimestamp(key * resolution, tz=UTC), combined)
            for key, combined in sorted(groups.items())
        ]
        return HistorySeriesRead(
            camera_id=camera_id,
            start=range_start,
            end=range_end,
            resolution_seconds=resolution,
            bucket_seconds=self._settings.history_bucket_seconds,
            source_mode=mode,
            points=points,
        )

    async def summary(
        self,
        *,
        start: datetime | None,
        end: datetime | None,
        source_mode: SourceMode | None,
    ) -> HistorySummaryRead:
        range_start, range_end = self.resolve_range(start, end)
        mode = source_mode or self._settings.pipeline_source_mode
        rows = await self._rows(range_start, range_end, mode)

        by_camera: dict[str, _Combined] = {}
        for row in rows:
            by_camera.setdefault(row.camera_id, _Combined()).add(row)

        items = {
            camera_id: self._summary_item(camera_id, combined)
            for camera_id, combined in by_camera.items()
        }
        site = items.pop(SITE_HISTORY_ID, None)
        return HistorySummaryRead(
            start=range_start,
            end=range_end,
            source_mode=mode,
            bucket_seconds=self._settings.history_bucket_seconds,
            baseline_min_samples=self._settings.history_baseline_min_samples,
            retention_days=self._settings.history_retention_days,
            recording=self._settings.history_enabled,
            cameras=[items[camera_id] for camera_id in sorted(items)],
            site=site,
        )

    async def _rows(
        self,
        start: datetime,
        end: datetime,
        mode: SourceMode,
        *,
        camera_id: str | None = None,
    ) -> Sequence[ObservationBucket]:
        statement = (
            select(ObservationBucket)
            .where(
                ObservationBucket.bucket_start >= start,
                ObservationBucket.bucket_start < end,
                ObservationBucket.source_mode == mode.value,
            )
            .order_by(ObservationBucket.bucket_start.asc())
        )
        if camera_id is not None:
            statement = statement.where(ObservationBucket.camera_id == camera_id)
        async with self._database.session() as session:
            return list((await session.scalars(statement)).all())

    def _summary_item(self, camera_id: str, combined: _Combined) -> HistorySummaryItem:
        status_total = sum(combined.status_samples.values())
        return HistorySummaryItem(
            camera_id=camera_id,
            buckets=combined.rows,
            observed_seconds=combined.rows * self._settings.history_bucket_seconds,
            first_at=combined.first,
            last_at=combined.last,
            baseline_available=combined.rows >= self._settings.history_baseline_min_samples,
            csi_mean=combined.mean("csi_mean"),
            csi_min=combined.minimums.get("csi"),
            people_mean=combined.mean("people_mean"),
            people_max=combined.maximum_int("people"),
            queue_length_max=combined.maximum_int("queue"),
            wait_minutes_max=combined.maximums.get("wait"),
            status_share=(
                {status: count / status_total for status, count in combined.status_samples.items()}
                if status_total
                else {}
            ),
            estimated_share=combined.share(combined.estimated),
        )


def _point(t: datetime, combined: _Combined) -> HistoryPoint:
    return HistoryPoint(
        t=t,
        samples=combined.samples,
        degraded_share=combined.share(combined.degraded),
        csi_mean=combined.mean("csi_mean"),
        csi_min=combined.minimums.get("csi"),
        csi_max=combined.maximums.get("csi"),
        status_worst=combined.status_worst,
        status_samples=combined.status_samples,
        confidence_mean=combined.mean("confidence_mean"),
        people_mean=combined.mean("people_mean"),
        people_max=combined.maximum_int("people"),
        estimated_share=combined.share(combined.estimated),
        density_max=combined.maximums.get("density"),
        density_is_metric=combined.density_is_metric,
        queue_length_mean=combined.mean("queue_length_mean"),
        queue_length_max=combined.maximum_int("queue"),
        wait_minutes_mean=combined.mean("wait_minutes_mean"),
        wait_minutes_max=combined.maximums.get("wait"),
        arrival_rate_mean=combined.mean("arrival_rate_mean"),
        service_rate_mean=combined.mean("service_rate_mean"),
        cameras_contributing_min=combined.cameras_contributing_min,
    )


def _aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)
