"""Abnormal crowd growth detection.

Problem Statement 9 is specific about what this must and must not do:

    "The alert should not trigger simply because the crowd is large. A large but
    stable crowd may be normal. A smaller crowd growing extremely quickly can be
    a more important warning."

So the test is on the **rate of change measured against this queue's own
baseline**, never on the queue's size. A ticket hall that always holds sixty
people at 09:00 is not an emergency at 09:00; the same hall going from ten to
fifty in four minutes is.

The baseline is learned online with exponentially weighted moving statistics,
which matters for a deployment that cannot be pre-trained: the platform arrives
knowing nothing about a venue and works out what normal looks like there, rather
than importing a threshold from somewhere else.

Until enough samples exist the pattern is reported as
:attr:`~surgeguard_ai.contracts.enums.GrowthPattern.INSUFFICIENT_HISTORY` rather
than defaulting to "normal". Declaring a queue normal on no evidence is exactly
the failure this component exists to prevent.
"""

from __future__ import annotations

import math

from ..contracts.enums import GrowthPattern

__all__ = ["GrowthDetector"]


class GrowthDetector:
    """Learns a queue's normal rate of change and flags departures from it.

    Driven once per sealed observation sample, so its notion of a "step" is the
    resampling interval rather than a frame.
    """

    def __init__(
        self,
        *,
        alpha: float = 0.05,
        min_samples: int = 12,
        z_threshold: float = 2.5,
        min_absolute_rate_per_min: float = 1.0,
        stable_band_per_min: float = 0.5,
    ) -> None:
        """
        Args:
            alpha: Weight of each new observation in the baseline. Deliberately
                small - the baseline should describe what this queue usually
                does, not what it did in the last thirty seconds. Too large and
                a genuine surge trains the baseline to accept itself.
            min_samples: Samples before any judgement is offered.
            z_threshold: Standard deviations above baseline that count as
                abnormal.
            min_absolute_rate_per_min: Floor on the growth rate for an abnormal
                verdict, whatever the z-score. Without it, a queue whose baseline
                is perfectly flat produces an enormous z-score from one person
                joining, and the platform cries wolf on a rounding error.
            stable_band_per_min: Rates within this band of zero are reported as
                stable rather than as growth or shrinkage.
        """
        if not 0.0 < alpha <= 1.0:
            raise ValueError("alpha must lie in (0, 1]")

        self._alpha = alpha
        self._min_samples = min_samples
        self._z_threshold = z_threshold
        self._min_absolute_rate = min_absolute_rate_per_min
        self._stable_band = stable_band_per_min

        self._mean: float | None = None
        self._variance: float = 0.0
        self._samples: int = 0

    # -- Driving ------------------------------------------------------------

    def update(self, rate_per_min: float) -> None:
        """Fold one observed rate of change into the baseline.

        **Samples already classified as abnormal are excluded by the caller**,
        and that exclusion is load-bearing rather than fastidious. Observed
        behaviour without it: during a sustained surge the baseline climbed from
        -0.8/min to +9.0/min over five minutes while the z-score *fell* from 2.6
        to 1.2, so the detector talked itself out of the alarm it had just
        raised. A baseline that adapts faster than the phenomenon it exists to
        detect will always do that.

        Everything short of abnormal - stable, growing, shrinking - still trains
        it, so a venue genuinely getting busier is still learned. Only the
        periods the platform has already decided are exceptional are withheld,
        which is the ordinary meaning of "baseline".
        """
        if self._mean is None:
            self._mean = rate_per_min
            self._variance = 0.0
            self._samples = 1
            return

        delta = rate_per_min - self._mean
        self._mean += self._alpha * delta
        # EWMA of squared deviation, measured before the mean moved.
        self._variance = (1.0 - self._alpha) * (
            self._variance + self._alpha * delta * delta
        )
        self._samples += 1

    def reset(self) -> None:
        self._mean = None
        self._variance = 0.0
        self._samples = 0

    # -- Reading ------------------------------------------------------------

    @property
    def samples(self) -> int:
        return self._samples

    @property
    def baseline_mean(self) -> float | None:
        return self._mean if self._samples >= self._min_samples else None

    @property
    def baseline_std(self) -> float | None:
        if self._samples < self._min_samples:
            return None
        return math.sqrt(max(0.0, self._variance))

    @property
    def has_baseline(self) -> bool:
        return self._samples >= self._min_samples

    def z_score(self, rate_per_min: float) -> float | None:
        """How unusual a rate is, in baseline standard deviations.

        ``None`` without a baseline. When the baseline has essentially no spread,
        a nominal floor stands in for the standard deviation: dividing by a
        near-zero number would turn any change at all into an infinite z-score.
        """
        mean = self.baseline_mean
        if mean is None:
            return None
        std = self.baseline_std or 0.0
        return (rate_per_min - mean) / max(std, 0.25)

    def classify(self, rate_per_min: float) -> tuple[GrowthPattern, float | None]:
        """Classify a rate of change, returning the pattern and its z-score."""
        if not self.has_baseline:
            return GrowthPattern.INSUFFICIENT_HISTORY, None

        z = self.z_score(rate_per_min)

        if (
            z is not None
            and z >= self._z_threshold
            and rate_per_min >= self._min_absolute_rate
        ):
            return GrowthPattern.ABNORMAL_GROWTH, z

        if rate_per_min > self._stable_band:
            return GrowthPattern.GROWING, z
        if rate_per_min < -self._stable_band:
            return GrowthPattern.SHRINKING, z
        return GrowthPattern.STABLE, z

    # -- Explanation --------------------------------------------------------

    def explain(
        self,
        pattern: GrowthPattern,
        rate_per_min: float,
        *,
        z: float | None,
        change_pct: float | None,
        window_minutes: float,
        arrival_rate: float | None = None,
        service_rate: float | None = None,
    ) -> str:
        """An operator-readable reason, built from the measurements themselves.

        Every clause names a number the platform actually measured. Nothing here
        asserts a conclusion the data does not carry - which is the difference
        between "queue population increased 47% in the last 5 minutes" and "AI
        says dangerous".
        """
        if pattern is GrowthPattern.INSUFFICIENT_HISTORY:
            return (
                f"Still establishing this queue's normal behaviour "
                f"({self._samples} of {self._min_samples} samples). No growth "
                "judgement offered yet."
            )

        if pattern is GrowthPattern.ABNORMAL_GROWTH:
            parts = [
                f"Queue is growing at {rate_per_min:.1f} people/min",
            ]
            if change_pct is not None and window_minutes > 0:
                parts.append(
                    f"a {change_pct:+.0f}% change over {window_minutes:.0f} min"
                )
            baseline = self.baseline_mean
            if baseline is not None and z is not None:
                parts.append(
                    f"{z:.1f} standard deviations above this queue's baseline of "
                    f"{baseline:.1f}/min"
                )
            if (
                arrival_rate is not None
                and service_rate is not None
                and arrival_rate > service_rate
            ):
                parts.append(
                    f"arrivals ({arrival_rate:.1f}/min) exceed service capacity "
                    f"({service_rate:.1f}/min)"
                )
            return " - ".join(parts) + "."

        if pattern is GrowthPattern.GROWING:
            text = f"Queue is growing at {rate_per_min:.1f} people/min"
            if change_pct is not None and window_minutes > 0:
                text += f" ({change_pct:+.0f}% over {window_minutes:.0f} min)"
            return text + ", within its normal range."

        if pattern is GrowthPattern.SHRINKING:
            return (
                f"Queue is shrinking at {abs(rate_per_min):.1f} people/min - "
                "service is outpacing arrivals."
            )

        return "Queue length is stable - arrivals and service are balanced."
