"""Finding the most congested place on the site - and never by headcount.

A large, calm crowd is a venue working normally. A congestion hotspot is where
the *measurements of congestion* are worst, so each contributing camera is
scored from four of them, each normalised to ``[0, 1]``:

- **density** - the density-pressure indicator behind the Crowd Stability Index;
- **instability** - the Crowd Stability Index itself, inverted;
- **growth** - how far above its own baseline a queue on that camera is growing;
- **capacity** - arrivals against service capacity for its queues.

Factors that cannot be measured - growth before a baseline exists, capacity on
a camera with no queue - are left out and the remaining weights renormalised,
exactly as the stability index treats an unavailable indicator. Every factor
carries the measurement it came from, so the score can always be explained.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ..contracts.enums import StabilityIndicator
from ..contracts.site import Hotspot, HotspotFactor
from .config import SiteIntelligenceConfig
from .observation import CameraContext

__all__ = ["find_hotspot", "score_camera"]

_STATUS_LABELS = {
    "STABLE": "stable",
    "OBSERVE": "observe",
    "ATTENTION_REQUIRED": "attention required",
    "HIGH_ALERT": "high alert",
    "CRITICAL": "critical",
}


@dataclass(frozen=True, slots=True)
class _Factor:
    key: str
    label: str
    value: float
    weight: float
    detail: str
    zone_id: str | None = None
    zone_name: str | None = None


def score_camera(camera: CameraContext, config: SiteIntelligenceConfig) -> Hotspot | None:
    """This camera's congestion score, or ``None`` when it is not contributing."""
    analysis = camera.analysis
    if analysis is None:
        return None

    factors: list[_Factor] = []

    density = next(
        (
            reading
            for reading in analysis.stability.breakdown.readings
            if reading.indicator is StabilityIndicator.DENSITY_PRESSURE
            and reading.available
            and reading.pressure is not None
        ),
        None,
    )
    if density is not None and density.pressure is not None:
        unit = "people/m²" if analysis.crowd.density_map.is_metric else "relative"
        factors.append(
            _Factor(
                "density",
                "Density",
                _clamp(density.pressure / 100.0),
                config.density_weight,
                f"Density pressure {density.pressure:.0f}/100 "
                f"(peak {analysis.crowd.density_max:.1f} {unit})",
            )
        )

    csi = analysis.stability.csi_smoothed
    status = analysis.stability.status.value
    factors.append(
        _Factor(
            "instability",
            "Stability",
            _clamp((100.0 - csi) / 100.0),
            config.instability_weight,
            f"Crowd Stability Index {csi:.0f} ({_STATUS_LABELS.get(status, status)})",
        )
    )

    growth = _growth_factor(camera, config)
    if growth is not None:
        factors.append(growth)

    capacity = _capacity_factor(camera, config)
    if capacity is not None:
        factors.append(capacity)

    total_weight = sum(factor.weight for factor in factors)
    weighted = [factor.weight * factor.value for factor in factors]
    score = sum(weighted) / total_weight if total_weight > 0 else 0.0
    total_weighted = sum(weighted)

    contract_factors = tuple(
        HotspotFactor(
            key=factor.key,
            label=factor.label,
            value=factor.value,
            weight=factor.weight / total_weight if total_weight > 0 else 0.0,
            contribution=part / total_weighted if total_weighted > 0 else 0.0,
            detail=factor.detail,
        )
        for factor, part in zip(factors, weighted, strict=True)
    )

    ranked = sorted(zip(factors, weighted, strict=True), key=lambda pair: pair[1], reverse=True)
    lead = ranked[0][0] if ranked and ranked[0][1] > 0 else None

    # Density and stability describe the whole view; growth and capacity belong
    # to a queue. When a queue factor is strong, name that queue - "Queue A on
    # CAM-02" is somewhere to send someone, "CAM-02" is not.
    zone_factor = next(
        (factor for factor, _ in ranked if factor.zone_id is not None and factor.value >= 0.5),
        None,
    )
    zone_id = zone_factor.zone_id if zone_factor is not None else None
    zone_name = zone_factor.zone_name if zone_factor is not None else None

    strong = [factor.detail for factor, _ in ranked if factor.value >= 0.5]
    reasons = tuple(strong) if strong else ((lead.detail,) if lead is not None else ())

    return Hotspot(
        camera_id=camera.camera_id,
        zone_id=zone_id,
        label=(
            f"{zone_name} ({camera.display_id})"
            if zone_name
            else f"{camera.camera.name} ({camera.display_id})"
        ),
        score=_clamp(score),
        reasons=reasons,
        factors=contract_factors,
    )


def find_hotspot(
    cameras: Sequence[CameraContext], config: SiteIntelligenceConfig
) -> Hotspot | None:
    """The highest-scoring camera, when it is congested enough to name."""
    scored = [
        hotspot for camera in cameras if (hotspot := score_camera(camera, config)) is not None
    ]
    best = max(scored, key=lambda hotspot: hotspot.score, default=None)
    if best is None or best.score < config.hotspot_min_score:
        return None
    return best


def _growth_factor(camera: CameraContext, config: SiteIntelligenceConfig) -> _Factor | None:
    analysis = camera.analysis
    if analysis is None or analysis.forecast is None:
        return None
    judged = [
        forecast for forecast in analysis.forecast.forecasts if forecast.growth.z_score is not None
    ]
    if not judged:
        return None
    worst = max(judged, key=lambda forecast: forecast.growth.z_score or 0.0)
    z = worst.growth.z_score or 0.0
    return _Factor(
        "growth",
        "Growth",
        _clamp(z / config.growth_z_saturation),
        config.growth_weight,
        f"{worst.zone_name} growing {worst.growth.growth_rate_per_min:+.1f}/min, "
        f"z = {z:.1f} against its baseline",
        zone_id=worst.zone_id,
        zone_name=worst.zone_name,
    )


def _capacity_factor(camera: CameraContext, config: SiteIntelligenceConfig) -> _Factor | None:
    analysis = camera.analysis
    if analysis is None or analysis.queue is None:
        return None
    measured = [
        queue
        for queue in analysis.queue.queues
        if queue.flow.observation_seconds >= config.min_rate_observation_seconds
        and queue.capacity.effective_service_rate_per_min > 0
    ]
    if not measured:
        return None
    worst = max(
        measured,
        key=lambda queue: (
            queue.flow.arrival_rate_per_min / queue.capacity.effective_service_rate_per_min
        ),
    )
    capacity = worst.capacity.effective_service_rate_per_min
    pressure = worst.flow.arrival_rate_per_min / capacity
    # Half of capacity is comfortable; arrivals at capacity read 0.5; half as
    # many again as the counters can serve reads 1.0.
    return _Factor(
        "capacity",
        "Capacity",
        _clamp(pressure - 0.5),
        config.capacity_weight,
        f"{worst.zone_name}: arrivals {worst.flow.arrival_rate_per_min:.1f}/min against "
        f"capacity {capacity:.1f}/min",
        zone_id=worst.zone_id,
        zone_name=worst.zone_name,
    )


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))
