"""Aggregated observation history.

One row per camera per time bucket - thirty seconds by default - and one per
bucket for the site as a whole (``camera_id = "site"``). Each row summarises the
analysis windows that fell inside it: how stable the crowd was and for how much
of the bucket, how many people, how long the queues.

**Measurements only.** No frames, no images, no track identities and no
positions are ever written here. A bucket of averages cannot be turned back into
a picture of a person, which is what makes keeping thirty days of it defensible.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, Float, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base
from ..db.mixins import UUIDPrimaryKeyMixin
from ..db.types import UTCDateTime

__all__ = ["SITE_HISTORY_ID", "ObservationBucket"]

#: The ``camera_id`` site-wide buckets are stored under - the same identifier the
#: timeline uses for site entries.
SITE_HISTORY_ID = "site"


class ObservationBucket(UUIDPrimaryKeyMixin, Base):
    """What one camera - or the site - measured during one bucket."""

    __table_args__ = (
        UniqueConstraint("camera_id", "bucket_start", "bucket_seconds", "source_mode"),
        Index(None, "camera_id", "bucket_start"),
    )

    camera_id: Mapped[str] = mapped_column(String(32), nullable=False)
    bucket_start: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    bucket_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    source_mode: Mapped[str] = mapped_column(String(8), nullable=False)
    """LIVE or DEMO - demonstration footage is kept separable from live records (Rule 7)."""

    samples: Mapped[int] = mapped_column(Integer, nullable=False)
    degraded_samples: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # -- Crowd Stability Index (camera buckets) ------------------------------
    csi_mean: Mapped[float | None] = mapped_column(Float, nullable=True)
    csi_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    csi_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    status_worst: Mapped[str | None] = mapped_column(String(24), nullable=True)
    status_last: Mapped[str | None] = mapped_column(String(24), nullable=True)
    status_samples: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    """Analysis windows per Operational Status - the time spent in each band."""
    confidence_mean: Mapped[float | None] = mapped_column(Float, nullable=True)

    # -- People ------------------------------------------------------------------
    people_mean: Mapped[float | None] = mapped_column(Float, nullable=True)
    people_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    estimated_samples: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    """Windows whose count was an estimate rather than tracked - reported, never hidden."""
    density_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    density_is_metric: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    # -- Queues ------------------------------------------------------------------
    queue_length_mean: Mapped[float | None] = mapped_column(Float, nullable=True)
    queue_length_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    wait_minutes_mean: Mapped[float | None] = mapped_column(Float, nullable=True)
    wait_minutes_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    arrival_rate_mean: Mapped[float | None] = mapped_column(Float, nullable=True)
    service_rate_mean: Mapped[float | None] = mapped_column(Float, nullable=True)

    # -- Site buckets --------------------------------------------------------------
    cameras_contributing_min: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
