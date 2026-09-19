"""Turning irregular analysis windows into an evenly spaced time series.

Forecasting needs a regular series. The AI Pipeline does not produce one: frames
arrive at whatever rate the camera and the GPU manage between them, and that
rate varies with load. Running a trend model directly on those readings would
make the trend depend on frame rate - a queue would appear to grow faster simply
because the machine got busier.

This module resamples. Readings are collected into fixed-length buckets and each
sealed bucket contributes one sample at the mean of its readings. The result is a
series whose step is a known number of seconds, which is what makes "the trend
per minute" a meaningful phrase.

Gaps are preserved rather than interpolated. When the pipeline stops for two
minutes, the buffer records that a gap happened instead of inventing the samples
that would have filled it - a fabricated observation is worse than a missing one.
"""

from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta

__all__ = ["Sample", "ObservationBuffer"]


class Sample:
    """One resampled observation: a value at an instant."""

    __slots__ = ("at", "value", "readings")

    def __init__(self, at: datetime, value: float, readings: int) -> None:
        self.at = at
        self.value = value
        self.readings = readings
        """How many raw readings this sample averages. A sample built from one
        reading is noisier than one built from thirty, and the forecaster is
        entitled to know."""

    def __repr__(self) -> str:  # pragma: no cover - diagnostic only
        return f"Sample(at={self.at.isoformat()}, value={self.value:.2f})"


class ObservationBuffer:
    """A fixed-cadence, bounded history of one measured quantity.

    Driven by :meth:`observe` once per analysis window. Emits a sample whenever a
    bucket completes, and retains a bounded number of them.
    """

    def __init__(
        self,
        *,
        sample_interval_seconds: float = 10.0,
        max_samples: int = 360,
    ) -> None:
        if sample_interval_seconds <= 0:
            raise ValueError("sample_interval_seconds must be positive")
        if max_samples < 2:
            raise ValueError("max_samples must be at least 2 for a trend to exist")

        self._interval = timedelta(seconds=sample_interval_seconds)
        self._interval_seconds = sample_interval_seconds
        self._samples: deque[Sample] = deque(maxlen=max_samples)

        self._bucket_start: datetime | None = None
        self._bucket_total: float = 0.0
        self._bucket_count: int = 0
        self._gap_before_next: bool = False

    # -- Driving ------------------------------------------------------------

    def observe(self, at: datetime, value: float) -> bool:
        """Record one reading. Returns True when this sealed a sample.

        A reading whose timestamp precedes the current bucket - which happens
        when a demonstration clip loops - resets the buffer. Extrapolating a
        trend across a rewind would forecast from a discontinuity.
        """
        if self._bucket_start is None:
            self._start_bucket(at)
            self._accumulate(value)
            return False

        if at < self._bucket_start:
            self.reset()
            self._start_bucket(at)
            self._accumulate(value)
            return False

        elapsed = at - self._bucket_start
        if elapsed < self._interval:
            self._accumulate(value)
            return False

        sealed = self._seal(at)

        # A reading far beyond the bucket that just closed means the pipeline
        # was not running in between. Mark the gap so the trend model can
        # decline to treat the two sides as one continuous series.
        if elapsed > self._interval * 3:
            self._gap_before_next = True

        self._start_bucket(at)
        self._accumulate(value)
        return sealed

    def _start_bucket(self, at: datetime) -> None:
        self._bucket_start = at
        self._bucket_total = 0.0
        self._bucket_count = 0

    def _accumulate(self, value: float) -> None:
        self._bucket_total += value
        self._bucket_count += 1

    def _seal(self, at: datetime) -> bool:
        if self._bucket_count == 0 or self._bucket_start is None:
            return False
        self._samples.append(
            Sample(
                at=self._bucket_start + self._interval,
                value=self._bucket_total / self._bucket_count,
                readings=self._bucket_count,
            )
        )
        return True

    def reset(self) -> None:
        """Discard all history. Used on a source restart."""
        self._samples.clear()
        self._bucket_start = None
        self._bucket_total = 0.0
        self._bucket_count = 0
        self._gap_before_next = False

    # -- Reading ------------------------------------------------------------

    @property
    def samples(self) -> tuple[Sample, ...]:
        return tuple(self._samples)

    @property
    def series(self) -> tuple[float, ...]:
        """Sample values only - the input a trend model consumes."""
        return tuple(sample.value for sample in self._samples)

    @property
    def count(self) -> int:
        return len(self._samples)

    @property
    def interval_seconds(self) -> float:
        """Seconds per sample - what converts a per-step trend into a per-minute one."""
        return self._interval_seconds

    @property
    def steps_per_minute(self) -> float:
        return 60.0 / self._interval_seconds

    @property
    def had_gap(self) -> bool:
        """Whether a gap in observation preceded the most recent samples."""
        return self._gap_before_next

    @property
    def span_seconds(self) -> float:
        """Time covered by the retained samples."""
        if len(self._samples) < 2:
            return 0.0
        return (self._samples[-1].at - self._samples[0].at).total_seconds()

    @property
    def latest(self) -> Sample | None:
        return self._samples[-1] if self._samples else None

    def change_over(self, minutes: float) -> tuple[float, float] | None:
        """Absolute and percentage change over the last ``minutes``.

        Returns ``None`` when the buffer does not reach back that far - a change
        computed over a shorter span than claimed would misstate the rate.
        """
        if len(self._samples) < 2:
            return None

        latest = self._samples[-1]
        cutoff = latest.at - timedelta(minutes=minutes)

        earlier: Sample | None = None
        for sample in self._samples:
            if sample.at >= cutoff:
                earlier = sample
                break

        if earlier is None or earlier is latest:
            return None
        if (latest.at - earlier.at).total_seconds() < minutes * 60.0 * 0.5:
            # Less than half the requested window is present. Reporting it as a
            # change over the full window would overstate the rate.
            return None

        absolute = latest.value - earlier.value
        if earlier.value <= 1e-9:
            return absolute, 0.0 if absolute <= 0 else 100.0
        return absolute, (absolute / earlier.value) * 100.0
