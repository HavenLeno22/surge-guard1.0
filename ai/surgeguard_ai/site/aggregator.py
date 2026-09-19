"""Site intelligence - one report for every camera at once.

Driven once per update with the site layout and each camera's latest state.
Stateless except for the two site forecasters, whose history is what a forecast
is made from.

**When a site forecast is withheld.** A forecast of a total is only valid while
the total means the same thing from one sample to the next. If a camera drops
out, its people vanish from the total and a trend fitted across that seam
forecasts a fall in demand that is not happening. So a site forecast is withheld
while any camera that belongs in it is missing, and its history is discarded
when the set of cameras it is built from changes. A camera returning to the same
set resumes the same history, with the gap preserved rather than filled.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from ..contracts.enums import (
    CameraConnectionStatus,
    CountAggregation,
    ForecastMethod,
    GrowthPattern,
    QueueFormation,
    RateSource,
    SiteForecastScope,
    ZoneType,
)
from ..contracts.forecast import GrowthAssessment, QueueForecast
from ..contracts.queue import (
    FlowRates,
    QueueGeometry,
    QueueMetrics,
    QueueReport,
    ServiceCapacity,
    WaitEstimate,
)
from ..contracts.resources import ResourcePlan
from ..contracts.site import (
    SiteCameraSummary,
    SiteForecast,
    SiteHeadcount,
    SiteReport,
    SiteTopology,
    TimeToPressure,
)
from ..forecast.config import ForecastConfig
from ..forecast.engine import QueueForecaster
from ..resources.allocator import ResourceAllocator
from ..resources.config import AllocationConfig
from .alerts import raise_alerts
from .config import SiteIntelligenceConfig
from .flow import build_flow
from .headcount import combine_headcount
from .hotspot import find_hotspot
from .observation import CameraContext, CameraObservation, resolve_cameras
from .pressure import time_to_pressure
from .queues import PooledQueue, pool_queues
from .text import join_names

__all__ = ["SiteIntelligence"]

DEMAND_SERIES_ID = "site-demand"


class SiteIntelligence:
    """Combines per-camera analysis into a :class:`SiteReport`."""

    def __init__(
        self,
        config: SiteIntelligenceConfig | None = None,
        *,
        forecast_config: ForecastConfig | None = None,
        allocation_config: AllocationConfig | None = None,
    ) -> None:
        self._config = config or SiteIntelligenceConfig()
        self._forecast_config = forecast_config or ForecastConfig()
        self._allocation = allocation_config or AllocationConfig()
        self._allocator = ResourceAllocator(self._allocation)

        self._demand = QueueForecaster(self._forecast_config)
        self._queues = QueueForecaster(self._forecast_config)
        self._demand_basis: frozenset[str] | None = None
        self._queue_basis: frozenset[str] | None = None

    @property
    def config(self) -> SiteIntelligenceConfig:
        return self._config

    def reset(self) -> None:
        """Discard both site forecast histories."""
        self._demand.reset()
        self._queues.reset()
        self._demand_basis = None
        self._queue_basis = None

    # -- The update -----------------------------------------------------------

    def update(
        self,
        topology: SiteTopology,
        observations: Sequence[CameraObservation],
        now: datetime,
    ) -> SiteReport:
        """Build the site report for this moment."""
        cameras = resolve_cameras(topology, observations, self._config)

        headcount = combine_headcount(cameras)
        pooled = pool_queues(cameras, now)

        demand_forecast = self._forecast_demand(cameras, headcount, now)
        queue_forecast = self._forecast_queues(cameras, pooled)
        plan, plan_withheld = self._plan(cameras, pooled, queue_forecast)

        pressures = self._pressures(cameras, pooled, queue_forecast)
        hotspot = find_hotspot(cameras, self._config)
        nodes, links = build_flow(cameras, topology.links, self._config)
        alerts = raise_alerts(
            cameras=cameras,
            headcount=headcount,
            pooled=pooled,
            demand_forecast=demand_forecast,
            queue_forecast=queue_forecast,
            hotspot=hotspot,
            pressures=pressures,
            config=self._config,
        )

        missing = [camera for camera in cameras if camera.missing]
        degraded_reasons = tuple(
            f"Global analysis degraded - {camera.display_id} {camera.status_phrase}"
            for camera in missing
        )

        return SiteReport(
            generated_at=now,
            cameras_total=len(cameras),
            cameras_enabled=sum(1 for camera in cameras if camera.enabled),
            cameras_contributing=sum(1 for camera in cameras if camera.contributing),
            cameras=tuple(self._summary(camera) for camera in cameras),
            headcount=headcount,
            queue=pooled.summary if pooled is not None else None,
            demand_forecast=demand_forecast,
            queue_forecast=queue_forecast,
            resource_plan=plan,
            resource_plan_withheld_reason=plan_withheld,
            hotspot=hotspot,
            time_to_pressure=pressures,
            flow_nodes=nodes,
            flow_links=links,
            alerts=alerts,
            degraded=bool(missing),
            degraded_reasons=degraded_reasons,
        )

    # -- Forecasts --------------------------------------------------------------

    def _forecast_demand(
        self, cameras: Sequence[CameraContext], headcount: SiteHeadcount, now: datetime
    ) -> SiteForecast:
        scope = SiteForecastScope.DEMAND
        contributors = headcount.contributing_camera_ids

        if headcount.value is None:
            return _withheld(
                scope, "No camera is delivering analysis, so there is nothing to forecast."
            )
        missing = [camera for camera in cameras if camera.missing]
        if missing:
            return _withheld(
                scope,
                f"{_missing_names(missing)} {_is_are(missing)} not contributing. Forecasting the "
                "combined count without "
                f"{'it' if len(missing) == 1 else 'them'} would project a fall in demand that is "
                "not happening.",
                contributors,
            )

        basis = frozenset(contributors)
        if basis != self._demand_basis:
            self._demand.reset()
            self._demand_basis = basis

        forecast = _as_demand_forecast(
            _forecast_one(self._demand, _demand_series(headcount.value, now)),
            self._forecast_config,
        )
        return SiteForecast(
            scope=scope,
            available=True,
            forecast=forecast,
            contributing_camera_ids=contributors,
            basis=(
                f"{headcount.label} from {_ids(contributors)}."
                if len(contributors) == 1
                else f"{headcount.label} from {_ids(contributors)}, "
                f"{_AGGREGATION_PHRASES[headcount.aggregation]}."
            ),
        )

    def _forecast_queues(
        self, cameras: Sequence[CameraContext], pooled: PooledQueue | None
    ) -> SiteForecast:
        scope = SiteForecastScope.QUEUE
        if pooled is None:
            return _withheld(scope, "No contributing camera is measuring a queue.")

        missing_ids = pooled.summary.missing_camera_ids
        if missing_ids:
            missing = [camera for camera in cameras if camera.camera_id in missing_ids]
            return _withheld(
                scope,
                f"{_missing_names(missing)} {_is_are(missing)} not contributing, and "
                f"{'its' if len(missing) == 1 else 'their'} queues would drop out of the total.",
                pooled.contributing_camera_ids,
            )

        basis = frozenset(pooled.contributing_camera_ids)
        if basis != self._queue_basis:
            self._queues.reset()
            self._queue_basis = basis

        forecast = _forecast_one(self._queues, pooled.metrics)
        if pooled.zone_count == 1:
            (zone,) = pooled.summary.zones
            basis = (
                f"{zone.zone_name} on {zone.camera_id.upper()} - the only queue being measured, "
                "so this matches its own forecast."
            )
        else:
            basis = (
                f"{pooled.zone_count} queue zones on {_ids(pooled.contributing_camera_ids)}, "
                f"{_AGGREGATION_PHRASES[pooled.summary.aggregation]}."
            )
        return SiteForecast(
            scope=scope,
            available=True,
            forecast=forecast,
            contributing_camera_ids=pooled.contributing_camera_ids,
            basis=basis,
        )

    # -- Staffing ----------------------------------------------------------------

    def _plan(
        self,
        cameras: Sequence[CameraContext],
        pooled: PooledQueue | None,
        queue_forecast: SiteForecast,
    ) -> tuple[ResourcePlan | None, str | None]:
        if pooled is None:
            return None, "No contributing camera is measuring a queue."
        if pooled.summary.missing_camera_ids:
            missing = [c for c in cameras if c.camera_id in pooled.summary.missing_camera_ids]
            return None, (
                f"{_missing_names(missing)} {_is_are(missing)} not contributing; a staffing plan "
                "for part of the site would understate demand."
            )
        if pooled.summary.total_counters <= 0:
            return None, "No counters are configured for the queues on this site."

        plan = self._allocator.plan(pooled.metrics, queue_forecast.forecast)
        if pooled.zone_count > 1:
            plan = plan.model_copy(
                update={
                    "assumptions": (
                        *plan.assumptions,
                        "counters across the pooled queues are treated as one pool - a counter "
                        "opened for one queue serves only that queue in practice",
                    )
                }
            )
        return plan, None

    # -- Time to pressure ------------------------------------------------------------

    def _pressures(
        self,
        cameras: Sequence[CameraContext],
        pooled: PooledQueue | None,
        queue_forecast: SiteForecast,
    ) -> tuple[TimeToPressure, ...]:
        target = self._allocation.target_wait_minutes
        pressures: list[TimeToPressure] = []
        for camera in cameras:
            analysis = camera.analysis
            if analysis is None or analysis.queue is None or analysis.forecast is None:
                continue
            for queue in analysis.queue.queues:
                forecast = analysis.forecast.by_zone(queue.zone_id)
                if forecast is None:
                    continue
                pressure = time_to_pressure(
                    label=f"{queue.zone_name} ({camera.display_id})",
                    forecast=forecast,
                    capacity_per_min=queue.capacity.effective_service_rate_per_min,
                    target_wait_minutes=target,
                    camera_id=camera.camera_id,
                    zone_id=queue.zone_id,
                )
                if pressure is not None:
                    pressures.append(pressure)

        if pooled is not None and pooled.zone_count > 1 and queue_forecast.forecast is not None:
            site = time_to_pressure(
                label="All queues",
                forecast=queue_forecast.forecast,
                capacity_per_min=pooled.summary.effective_capacity_per_min,
                target_wait_minutes=target,
            )
            if site is not None:
                pressures.append(site)

        return tuple(
            sorted(
                pressures,
                key=lambda item: (
                    not item.already_exceeded,
                    item.minutes if item.minutes is not None else float("inf"),
                ),
            )
        )

    # -- Summaries ----------------------------------------------------------------

    def _summary(self, camera: CameraContext) -> SiteCameraSummary:
        observation = camera.observation
        analysis = camera.analysis
        status = observation.status if camera.enabled else CameraConnectionStatus.DISABLED
        base = {
            "camera_id": camera.camera_id,
            "name": camera.camera.name,
            "role": camera.camera.role,
            "coverage_area": camera.camera.coverage_area,
            "status": status,
            "status_detail": observation.status_detail,
            "contributing": camera.contributing,
            "excluded_reason": camera.excluded_reason,
            "analysis_age_seconds": observation.analysis_age_seconds,
            "queue_zone_count": sum(
                1 for zone in observation.zones if zone.zone_type is ZoneType.QUEUE
            ),
        }
        if analysis is None:
            return SiteCameraSummary(**base)

        queues = analysis.queue.queues if analysis.queue is not None else ()
        forecasts = analysis.forecast.forecasts if analysis.forecast is not None else ()
        horizon = self._allocation.decision_horizon_minutes
        worst = max(
            forecasts, key=lambda forecast: _GROWTH_RANK[forecast.growth.pattern], default=None
        )
        predicted = [
            point.expected
            for forecast in forecasts
            if (point := forecast.at_horizon(horizon)) is not None
        ]
        waits = [queue.wait.minutes for queue in queues if queue.wait.minutes is not None]

        return SiteCameraSummary(
            **{**base, "queue_zone_count": max(base["queue_zone_count"], len(queues))},
            source_mode=analysis.source_mode,
            observed_at=analysis.frame_ts,
            people_count=analysis.crowd.person_count,
            count_method=analysis.crowd.count_method,
            operational_status=analysis.stability.status,
            csi=analysis.stability.csi_smoothed,
            density_max=analysis.crowd.density_max,
            density_is_metric=analysis.crowd.density_map.is_metric,
            queue_length=sum(queue.person_count for queue in queues) if queues else None,
            arrival_rate_per_min=(
                sum(queue.flow.arrival_rate_per_min for queue in queues) if queues else None
            ),
            service_rate_per_min=(
                sum(queue.flow.service_rate_per_min for queue in queues) if queues else None
            ),
            wait_minutes=max(waits) if waits else None,
            growth_pattern=worst.growth.pattern if worst is not None else None,
            growth_rate_per_min=worst.growth.growth_rate_per_min if worst is not None else None,
            predicted_queue=sum(predicted) if predicted else None,
            predicted_horizon_minutes=horizon if predicted else None,
        )


_AGGREGATION_PHRASES = {
    CountAggregation.INDEPENDENT_SUM: "summed across separate areas",
    CountAggregation.OVERLAP_ADJUSTED: "adjusted for cameras that share an area",
    CountAggregation.NO_DATA: "with no data",
}

_GROWTH_RANK = {
    GrowthPattern.INSUFFICIENT_HISTORY: 0,
    GrowthPattern.SHRINKING: 1,
    GrowthPattern.STABLE: 2,
    GrowthPattern.GROWING: 3,
    GrowthPattern.ABNORMAL_GROWTH: 4,
}


def _withheld(
    scope: SiteForecastScope, reason: str, contributors: Sequence[str] = ()
) -> SiteForecast:
    return SiteForecast(
        scope=scope,
        available=False,
        withheld_reason=reason,
        contributing_camera_ids=tuple(contributors),
    )


def _ids(camera_ids: Sequence[str]) -> str:
    return join_names([camera_id.upper() for camera_id in camera_ids])


def _missing_names(cameras: Sequence[CameraContext]) -> str:
    return join_names([camera.display_id for camera in cameras])


def _is_are(cameras: Sequence[CameraContext]) -> str:
    return "is" if len(cameras) == 1 else "are"


def _forecast_one(forecaster: QueueForecaster, series: QueueMetrics) -> QueueForecast:
    """Run one site series through a forecaster built for camera queue reports."""
    report = forecaster.observe(
        QueueReport(frame_seq=series.frame_seq, frame_ts=series.frame_ts, queues=(series,))
    )
    return report.forecasts[0]


def _demand_series(people: int, now: datetime) -> QueueMetrics:
    """The combined count, shaped as a series the forecaster can take.

    A headcount has no arrival or departure rates, so the flow-balance method has
    nothing to integrate and only the trend method runs. Nothing about queue
    formation applies either, so the formation confidence the forecaster
    discounts by is neutral rather than invented.
    """
    return QueueMetrics(
        zone_id=DEMAND_SERIES_ID,
        zone_name="Combined observed count",
        frame_seq=0,
        frame_ts=now,
        person_count=people,
        formation=QueueFormation.UNDETERMINED,
        formation_confidence=1.0,
        geometry=QueueGeometry(sample_size=0),
        flow=FlowRates(
            window_seconds=1.0,
            arrivals=0,
            departures_served=0,
            departures_abandoned=0,
            arrival_rate_per_min=0.0,
            service_rate_per_min=0.0,
            rate_source=RateSource.MEASURED,
            observation_seconds=0.0,
        ),
        capacity=ServiceCapacity(
            total_counters=0,
            active_counters=0,
            service_rate_per_counter_per_min=1.0,
            rate_source=RateSource.MEASURED,
        ),
        wait=WaitEstimate(
            queue_length=people,
            effective_service_rate_per_min=0.0,
            rate_source=RateSource.MEASURED,
        ),
    )


def _as_demand_forecast(forecast: QueueForecast, config: ForecastConfig) -> QueueForecast:
    """Re-word a forecast of the combined count, which is not a queue.

    The numbers are the forecaster's own and are not touched. Only the sentences
    change: "queue is growing" and a flow method "needing flow observation" are
    true of queues, and would be misleading about a headcount.
    """
    methods = tuple(
        method.model_copy(
            update={
                "unavailable_reason": (
                    "A headcount has no measured arrival and departure rates, so it is "
                    "forecast from its trend alone."
                )
            }
        )
        if method.method is ForecastMethod.FLOW_BALANCE
        else method
        for method in forecast.methods
    )
    trend = forecast.method(ForecastMethod.TREND)
    assumptions = (
        ("the combined count keeps changing at its recent rate",)
        if trend is not None and trend.available
        else ("not enough history yet to forecast the combined count",)
    )
    growth = forecast.growth
    growth = growth.model_copy(update={"explanation": _demand_growth_explanation(growth, config)})
    return forecast.model_copy(
        update={"methods": methods, "assumptions": assumptions, "growth": growth}
    )


def _demand_growth_explanation(growth: GrowthAssessment, config: ForecastConfig) -> str:
    rate = growth.growth_rate_per_min
    if growth.pattern is GrowthPattern.INSUFFICIENT_HISTORY:
        return (
            f"Still learning how the combined count normally changes ({growth.samples} of "
            f"{config.growth_min_samples} samples). No growth judgement yet."
        )
    if growth.pattern is GrowthPattern.ABNORMAL_GROWTH:
        parts = [f"The combined count is growing at {rate:.1f} people/min"]
        if growth.change_pct is not None and growth.window_minutes > 0:
            parts.append(f"{growth.change_pct:+.0f}% over {growth.window_minutes:.0f} min")
        if growth.z_score is not None and growth.baseline_rate_per_min is not None:
            parts.append(
                f"{growth.z_score:.1f} standard deviations above its baseline of "
                f"{growth.baseline_rate_per_min:.1f}/min"
            )
        return " - ".join(parts) + "."
    if growth.pattern is GrowthPattern.GROWING:
        return f"The combined count is growing at {rate:.1f} people/min, within its normal range."
    if growth.pattern is GrowthPattern.SHRINKING:
        return f"The combined count is falling at {abs(rate):.1f} people/min."
    return "The combined count is steady."
