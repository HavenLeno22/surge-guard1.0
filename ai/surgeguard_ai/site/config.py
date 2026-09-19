"""Thresholds for site-level intelligence."""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["SiteIntelligenceConfig"]


@dataclass(frozen=True, slots=True)
class SiteIntelligenceConfig:
    """How site intelligence decides what to combine and what to flag.

    Attributes:
        max_observation_age_seconds: A camera whose latest analysis is older than
            this is not contributing. Stale figures summed with fresh ones would
            describe a moment that never existed.
        min_rate_observation_seconds: Observation below which measured rates are
            too short-lived to raise a capacity alert or anchor a hotspot. The
            queue allocator marks plans provisional under the same threshold.
        capacity_alert_pressure: Arrivals over capacity above which a queue is
            flagged. At 1.0 people join faster than they are served.
        correlation_min_rate_per_min: Rates below this are too small to compare;
            a conversion ratio between two near-zero rates is noise.
        hotspot_min_score: Below this nowhere on the site is congested enough to
            name as a hotspot.
        hotspot_alert_score: A hotspot at or above this is raised as an alert.
        growth_z_saturation: Growth z-score at which the growth factor of a
            hotspot score reaches its maximum.
        density_weight: Hotspot weight of density pressure.
        instability_weight: Hotspot weight of the Crowd Stability Index. The
            index already includes density; the two weights are set with that
            in mind rather than as independent evidence.
        growth_weight: Hotspot weight of queue growth against its baseline.
        capacity_weight: Hotspot weight of arrivals against service capacity.
    """

    max_observation_age_seconds: float = 10.0
    min_rate_observation_seconds: float = 60.0
    capacity_alert_pressure: float = 1.0
    correlation_min_rate_per_min: float = 0.5
    hotspot_min_score: float = 0.35
    hotspot_alert_score: float = 0.6
    growth_z_saturation: float = 5.0
    density_weight: float = 0.3
    instability_weight: float = 0.3
    growth_weight: float = 0.2
    capacity_weight: float = 0.2

    def __post_init__(self) -> None:
        if self.max_observation_age_seconds <= 0:
            raise ValueError("max_observation_age_seconds must be positive")
        if not 0.0 <= self.hotspot_min_score <= self.hotspot_alert_score <= 1.0:
            raise ValueError("hotspot scores must satisfy 0 <= min <= alert <= 1")
        if self.growth_z_saturation <= 0:
            raise ValueError("growth_z_saturation must be positive")
        weights = (
            self.density_weight,
            self.instability_weight,
            self.growth_weight,
            self.capacity_weight,
        )
        if any(weight < 0 for weight in weights) or sum(weights) <= 0:
            raise ValueError("hotspot weights must be non-negative and not all zero")
