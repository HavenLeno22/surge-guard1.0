"""Historical observation schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field
from surgeguard_ai.contracts import SourceMode

__all__ = ["HistoryPoint", "HistorySeriesRead", "HistorySummaryItem", "HistorySummaryRead"]


class HistoryPoint(BaseModel):
    """One point of a history series - one or more stored buckets combined.

    Means are sample-weighted across the buckets combined; minimums and maximums
    are the extremes within them. Every figure is ``None`` where nothing was
    measured - a gap, never a zero.
    """

    model_config = ConfigDict(extra="forbid")

    t: datetime = Field(description="Start of the period this point covers.")
    samples: int = Field(ge=0, description="Analysis windows (or site updates) behind it.")
    degraded_share: float = Field(ge=0.0, le=1.0)

    csi_mean: float | None = None
    csi_min: float | None = None
    csi_max: float | None = None
    status_worst: str | None = None
    status_samples: dict[str, int] = Field(default_factory=dict)
    confidence_mean: float | None = None

    people_mean: float | None = None
    people_max: int | None = None
    estimated_share: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Share of windows whose count was an estimate rather than tracked.",
    )
    density_max: float | None = None
    density_is_metric: bool | None = None

    queue_length_mean: float | None = None
    queue_length_max: int | None = None
    wait_minutes_mean: float | None = None
    wait_minutes_max: float | None = None
    arrival_rate_mean: float | None = None
    service_rate_mean: float | None = None

    cameras_contributing_min: int | None = None


class HistorySeriesRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    camera_id: str = Field(description="A camera id, or 'site' for the whole site.")
    start: datetime
    end: datetime
    resolution_seconds: int
    bucket_seconds: int
    source_mode: SourceMode
    points: list[HistoryPoint]


class HistorySummaryItem(BaseModel):
    """What one camera - or the site - recorded over a range."""

    model_config = ConfigDict(extra="forbid")

    camera_id: str
    buckets: int = Field(ge=0, description="Stored buckets in the range.")
    observed_seconds: int = Field(ge=0)
    first_at: datetime | None = None
    last_at: datetime | None = None
    baseline_available: bool = Field(
        description=(
            "Whether enough buckets exist for a historical comparison to be shown "
            "(SURGEGUARD_HISTORY_BASELINE_MIN_SAMPLES). Below it, comparisons are withheld."
        )
    )
    csi_mean: float | None = None
    csi_min: float | None = None
    people_mean: float | None = None
    people_max: int | None = None
    queue_length_max: int | None = None
    wait_minutes_max: float | None = None
    status_share: dict[str, float] = Field(
        default_factory=dict, description="Share of analysed windows spent in each status."
    )
    estimated_share: float = Field(default=0.0, ge=0.0, le=1.0)


class HistorySummaryRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: datetime
    end: datetime
    source_mode: SourceMode
    bucket_seconds: int
    baseline_min_samples: int
    retention_days: int
    recording: bool = Field(description="Whether history is being recorded on this deployment.")
    cameras: list[HistorySummaryItem]
    site: HistorySummaryItem | None = None
