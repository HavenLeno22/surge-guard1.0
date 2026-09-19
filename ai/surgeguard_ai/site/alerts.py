"""Site alerts - the conditions worth an operator's attention, with their evidence.

Every alert is raised from a measurement and carries it: an alert an operator
cannot check is an alert an operator learns to ignore. Three things are
deliberately *not* alerts:

- **A queue forming.** Queues are how service works; formation is shown, never
  alarmed. Growth *against the queue's own baseline* is the alarm condition.
- **A large crowd.** Headcount alone never raises anything.
- **A camera still connecting.** Startup is not a fault. A camera that stays
  away - offline, or reconnecting after a loss - is.

Each alert has a stable ``alert_id`` for its condition, so a consumer can tell a
persisting alert from a new one and record only the transitions.
"""

from __future__ import annotations

from collections.abc import Sequence

from ..contracts.enums import (
    CameraConnectionStatus,
    GrowthPattern,
    Severity,
    SiteAlertKind,
)
from ..contracts.forecast import QueueForecast
from ..contracts.site import (
    Hotspot,
    SiteAlert,
    SiteForecast,
    SiteHeadcount,
    TimeToPressure,
)
from .config import SiteIntelligenceConfig
from .observation import CameraContext
from .queues import PooledQueue
from .text import join_names, plural

__all__ = ["raise_alerts"]

#: Statuses that mean a camera has been lost rather than not yet found.
_LOST = frozenset({CameraConnectionStatus.OFFLINE, CameraConnectionStatus.RECOVERING})

_SEVERITY_ORDER = {Severity.CRITICAL: 0, Severity.WARNING: 1, Severity.INFO: 2}
_KIND_ORDER = {
    SiteAlertKind.ABNORMAL_GROWTH: 0,
    SiteAlertKind.CAPACITY_PRESSURE: 1,
    SiteAlertKind.HOTSPOT: 2,
    SiteAlertKind.DEGRADED_COVERAGE: 3,
    SiteAlertKind.CAMERA_OFFLINE: 4,
}


def raise_alerts(
    *,
    cameras: Sequence[CameraContext],
    headcount: SiteHeadcount,
    pooled: PooledQueue | None,
    demand_forecast: SiteForecast,
    queue_forecast: SiteForecast,
    hotspot: Hotspot | None,
    pressures: Sequence[TimeToPressure],
    config: SiteIntelligenceConfig,
) -> tuple[SiteAlert, ...]:
    alerts: list[SiteAlert] = []
    alerts.extend(_growth_alerts(cameras, demand_forecast, queue_forecast, pooled))
    alerts.extend(_capacity_alerts(cameras, pressures, config))
    if hotspot is not None and hotspot.score >= config.hotspot_alert_score:
        alerts.append(_hotspot_alert(hotspot))
    coverage = _coverage_alert(cameras, headcount, pooled, demand_forecast, queue_forecast)
    if coverage is not None:
        alerts.append(coverage)
    alerts.extend(_camera_alerts(cameras))
    return tuple(
        sorted(alerts, key=lambda alert: (_SEVERITY_ORDER[alert.severity], _KIND_ORDER[alert.kind]))
    )


# -- Growth ---------------------------------------------------------------------


def _growth_alerts(
    cameras: Sequence[CameraContext],
    demand_forecast: SiteForecast,
    queue_forecast: SiteForecast,
    pooled: PooledQueue | None,
) -> list[SiteAlert]:
    alerts = []
    for camera in cameras:
        analysis = camera.analysis
        if analysis is None or analysis.forecast is None:
            continue
        for forecast in analysis.forecast.forecasts:
            if forecast.growth.pattern is not GrowthPattern.ABNORMAL_GROWTH:
                continue
            alerts.append(
                SiteAlert(
                    alert_id=f"abnormal-growth:{camera.camera_id}:{forecast.zone_id}",
                    kind=SiteAlertKind.ABNORMAL_GROWTH,
                    severity=Severity.CRITICAL,
                    title=f"Abnormal queue growth - {forecast.zone_name} ({camera.display_id})",
                    explanation=forecast.growth.explanation,
                    evidence=_growth_evidence(forecast),
                    camera_id=camera.camera_id,
                    zone_id=forecast.zone_id,
                )
            )

    demand = demand_forecast.forecast
    if demand is not None and demand.growth.pattern is GrowthPattern.ABNORMAL_GROWTH:
        alerts.append(
            SiteAlert(
                alert_id="abnormal-growth:site-demand",
                kind=SiteAlertKind.ABNORMAL_GROWTH,
                severity=Severity.CRITICAL,
                title="Abnormal growth across the site",
                explanation=demand.growth.explanation,
                evidence=_growth_evidence(demand),
            )
        )

    # With a single queue zone the pooled queue is that zone, already alerted.
    pooled_forecast = queue_forecast.forecast
    if (
        pooled is not None
        and pooled.zone_count > 1
        and pooled_forecast is not None
        and pooled_forecast.growth.pattern is GrowthPattern.ABNORMAL_GROWTH
    ):
        alerts.append(
            SiteAlert(
                alert_id="abnormal-growth:site-queues",
                kind=SiteAlertKind.ABNORMAL_GROWTH,
                severity=Severity.CRITICAL,
                title="Abnormal growth across all queues",
                explanation=pooled_forecast.growth.explanation,
                evidence=_growth_evidence(pooled_forecast),
            )
        )
    return alerts


def _growth_evidence(forecast: QueueForecast) -> tuple[str, ...]:
    growth = forecast.growth
    evidence = [f"Growing at {growth.growth_rate_per_min:.1f} people/min"]
    if growth.change_pct is not None and growth.window_minutes > 0:
        evidence.append(f"{growth.change_pct:+.0f}% over {growth.window_minutes:.0f} min")
    if growth.z_score is not None and growth.baseline_rate_per_min is not None:
        evidence.append(
            f"{growth.z_score:.1f} standard deviations above a baseline of "
            f"{growth.baseline_rate_per_min:+.1f}/min"
        )
    peak = forecast.points[-1] if forecast.points else None
    if peak is not None:
        evidence.append(
            f"Now {forecast.current_length}; forecast +{peak.horizon_minutes} min: "
            f"{peak.expected:.0f} ({peak.lower:.0f}-{peak.upper:.0f})"
        )
    return tuple(evidence)


# -- Capacity -------------------------------------------------------------------


def _capacity_alerts(
    cameras: Sequence[CameraContext],
    pressures: Sequence[TimeToPressure],
    config: SiteIntelligenceConfig,
) -> list[SiteAlert]:
    alerts = []
    for camera in cameras:
        analysis = camera.analysis
        if analysis is None or analysis.queue is None:
            continue
        for queue in analysis.queue.queues:
            capacity = queue.capacity
            flow = queue.flow
            if queue.person_count <= 0 or capacity.total_counters <= 0:
                continue
            counters = (
                f"{capacity.active_counters} of {plural(capacity.total_counters, 'counter')} open"
            )
            alert_id = f"capacity:{camera.camera_id}:{queue.zone_id}"
            title = f"Arrivals outpacing service - {queue.zone_name} ({camera.display_id})"

            if capacity.active_counters == 0:
                alerts.append(
                    SiteAlert(
                        alert_id=alert_id,
                        kind=SiteAlertKind.CAPACITY_PRESSURE,
                        severity=Severity.WARNING,
                        title=f"No counter open - {queue.zone_name} ({camera.display_id})",
                        explanation=(
                            f"{plural(queue.person_count, 'person', 'people')} waiting and no "
                            "counter is serving them."
                        ),
                        evidence=(f"Counters: {counters}",),
                        camera_id=camera.camera_id,
                        zone_id=queue.zone_id,
                    )
                )
                continue

            if flow.observation_seconds < config.min_rate_observation_seconds:
                continue
            served = capacity.effective_service_rate_per_min
            pressure = flow.arrival_rate_per_min / served
            if pressure <= config.capacity_alert_pressure:
                continue

            evidence = [
                f"Arrivals {flow.arrival_rate_per_min:.1f}/min, counted over "
                f"{flow.observation_seconds / 60:.0f} min",
                f"Capacity {served:.1f}/min with {counters}",
                f"{plural(queue.person_count, 'person', 'people')} waiting now",
            ]
            pressure_forecast = next(
                (
                    item
                    for item in pressures
                    if item.camera_id == camera.camera_id and item.zone_id == queue.zone_id
                ),
                None,
            )
            if pressure_forecast is not None and pressure_forecast.within_horizon:
                evidence.append(pressure_forecast.explanation)

            alerts.append(
                SiteAlert(
                    alert_id=alert_id,
                    kind=SiteAlertKind.CAPACITY_PRESSURE,
                    severity=Severity.WARNING,
                    title=title,
                    explanation=(
                        f"People are joining at {flow.arrival_rate_per_min:.1f}/min and the open "
                        f"counters serve {served:.1f}/min, so the queue grows for as long as "
                        "that lasts."
                    ),
                    evidence=tuple(evidence),
                    camera_id=camera.camera_id,
                    zone_id=queue.zone_id,
                )
            )
    return alerts


# -- Hotspot --------------------------------------------------------------------


def _hotspot_alert(hotspot: Hotspot) -> SiteAlert:
    ranked = sorted(hotspot.factors, key=lambda factor: factor.contribution, reverse=True)
    return SiteAlert(
        alert_id=f"hotspot:{hotspot.camera_id}:{hotspot.zone_id or '-'}",
        kind=SiteAlertKind.HOTSPOT,
        severity=Severity.WARNING,
        title=f"Congestion building - {hotspot.label}",
        explanation=(
            f"Congestion score {hotspot.score:.2f}, from density, stability, growth and "
            "capacity - never from headcount alone."
        ),
        evidence=tuple(factor.detail for factor in ranked if factor.contribution > 0),
        camera_id=hotspot.camera_id,
        zone_id=hotspot.zone_id,
    )


# -- Coverage and cameras ---------------------------------------------------------


def _coverage_alert(
    cameras: Sequence[CameraContext],
    headcount: SiteHeadcount,
    pooled: PooledQueue | None,
    demand_forecast: SiteForecast,
    queue_forecast: SiteForecast,
) -> SiteAlert | None:
    lost = [camera for camera in cameras if _is_lost(camera)]
    if not lost:
        return None

    covered = {camera.camera.coverage_area for camera in cameras if camera.contributing}
    effects: list[str] = []
    uncovered = [camera for camera in lost if camera.camera.coverage_area not in covered]
    if uncovered:
        effects.append(
            f"The {headcount.label.lower()} leaves out what "
            f"{join_names([camera.display_id for camera in uncovered])} "
            f"{'sees' if len(uncovered) == 1 else 'see'}"
        )
    if not demand_forecast.available and demand_forecast.withheld_reason:
        effects.append("the site demand forecast is withheld until coverage returns")
    queue_cameras = [camera for camera in lost if camera.has_queue_zones]
    if queue_cameras:
        owner = "its" if len(queue_cameras) == 1 else "their"
        effects.append(
            f"queue totals, the queue forecast and the staffing plan exclude {owner} queues"
        )
    if not effects:
        return None

    names = join_names([camera.display_id for camera in lost])
    state = lost[0].status_phrase if len(lost) == 1 else "unavailable"
    explanation = "; ".join(effects)
    return SiteAlert(
        alert_id="degraded-coverage",
        kind=SiteAlertKind.DEGRADED_COVERAGE,
        severity=Severity.WARNING,
        title=f"Global analysis degraded - {names} {state}",
        explanation=explanation[0].upper() + explanation[1:] + ".",
        evidence=tuple(
            f"{camera.display_id}: {camera.excluded_reason}"
            for camera in lost
            if camera.excluded_reason
        ),
    )


def _is_lost(camera: CameraContext) -> bool:
    """Missing because it went away - not because it is still starting up."""
    return camera.missing and (camera.observation.status in _LOST or _is_stale(camera))


def _is_stale(camera: CameraContext) -> bool:
    """Connected, with analysis, but that analysis is too old to use."""
    return (
        camera.missing
        and camera.observation.status.is_contributing
        and camera.observation.analysis is not None
    )


def _camera_alerts(cameras: Sequence[CameraContext]) -> list[SiteAlert]:
    alerts = []
    for camera in cameras:
        if not _is_lost(camera):
            continue
        stale = _is_stale(camera)
        evidence = []
        age = camera.observation.analysis_age_seconds
        if age is not None:
            evidence.append(f"Last analysis {age:.0f}s ago")
        alerts.append(
            SiteAlert(
                alert_id=f"camera-offline:{camera.camera_id}",
                kind=SiteAlertKind.CAMERA_OFFLINE,
                severity=Severity.WARNING,
                title=(
                    f"{camera.display_id} not delivering analysis"
                    if stale
                    else f"{camera.display_id} {camera.status_phrase}"
                ),
                explanation=camera.excluded_reason or "No analysis is arriving from this camera.",
                evidence=tuple(evidence),
                camera_id=camera.camera_id,
            )
        )
    return alerts
