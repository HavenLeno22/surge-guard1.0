"""Site intelligence - combining every camera without inventing anything.

The analyses fed in start from a real analysis pipeline run and have their
figures replaced, so every report here is built from genuine contract objects
while each test controls exactly the numbers it is about.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import pytest

from surgeguard_ai.analysis import CrowdAnalysisConfig, GridCrowdAnalyzer
from surgeguard_ai.contracts import (
    AnalysisResult,
    CameraConnectionStatus,
    CameraRole,
    CountAggregation,
    FlowLinkBasis,
    ForecastMethod,
    GrowthPattern,
    ImagePoint,
    ImagePolygon,
    QueueFormation,
    RateSource,
    Severity,
    SiteAlertKind,
    StabilityIndicator,
    ZoneType,
    status_for_csi,
)
from surgeguard_ai.contracts.camera import CameraZone
from surgeguard_ai.contracts.forecast import (
    ForecastPoint,
    ForecastReport,
    GrowthAssessment,
    QueueForecast,
)
from surgeguard_ai.contracts.queue import (
    FlowRates,
    QueueGeometry,
    QueueMetrics,
    QueueReport,
    ServiceCapacity,
    WaitEstimate,
)
from surgeguard_ai.contracts.site import FlowLinkConfig, SiteCamera, SiteTopology
from surgeguard_ai.contracts.zones import ZoneFlowReport, ZoneFlowSnapshot, ZoneTransition
from surgeguard_ai.evidence import EvidenceConfig, RuleEvidenceEngine
from surgeguard_ai.pipeline.analysis_pipeline import AnalysisPipeline
from surgeguard_ai.site import CameraObservation, SiteIntelligence, SiteIntelligenceConfig
from surgeguard_ai.site.pressure import time_to_pressure
from surgeguard_ai.stability import CsiConfig, WeightedStabilityAssessor

from .conftest import ANALYSIS_SIZE, make_perception, make_tracks

NOW = datetime(2026, 9, 16, 12, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def base() -> AnalysisResult:
    """One genuine analysis result, whose figures each test replaces."""
    from surgeguard_ai.contracts import CameraConfig

    width, height = ANALYSIS_SIZE
    pipeline = AnalysisPipeline(
        CameraConfig(camera_id="cam-01", name="Camera 01", location="Hall"),
        GridCrowdAnalyzer(CrowdAnalysisConfig(frame_width=width, frame_height=height)),
        WeightedStabilityAssessor(CsiConfig()),
        RuleEvidenceEngine(EvidenceConfig()),
    )
    return pipeline.process(
        make_perception(seq=1, tracks=make_tracks(count=4, speed=5.0), seconds=0.0)
    )


def analysis(
    base: AnalysisResult,
    camera_id: str,
    people: int,
    *,
    queues: Sequence[QueueMetrics] = (),
    forecasts: Sequence[QueueForecast] = (),
    zone_flow: ZoneFlowReport | None = None,
    csi: float = 95.0,
    density_pressure: float | None = None,
) -> AnalysisResult:
    stability = base.stability.model_copy(
        update={"csi_smoothed": csi, "status": status_for_csi(csi)}
    )
    if density_pressure is not None:
        readings = tuple(
            reading.model_copy(update={"available": True, "pressure": density_pressure})
            if reading.indicator is StabilityIndicator.DENSITY_PRESSURE
            else reading
            for reading in stability.breakdown.readings
        )
        stability = stability.model_copy(
            update={"breakdown": stability.breakdown.model_copy(update={"readings": readings})}
        )
    return base.model_copy(
        update={
            "camera_id": camera_id,
            "crowd": base.crowd.model_copy(update={"person_count": people}),
            "stability": stability,
            "queue": QueueReport(frame_seq=1, frame_ts=NOW, queues=tuple(queues))
            if queues
            else None,
            "forecast": (
                ForecastReport(frame_seq=1, frame_ts=NOW, forecasts=tuple(forecasts))
                if forecasts
                else None
            ),
            "zone_flow": zone_flow,
        }
    )


def queue(
    zone_id: str = "queue-a",
    *,
    people: int = 10,
    arrival: float = 3.0,
    served: float = 3.0,
    active: int = 2,
    total: int = 4,
    per_counter: float = 2.0,
    observed: float = 300.0,
    rate_source: RateSource = RateSource.MEASURED,
    formation: QueueFormation = QueueFormation.QUEUE,
) -> QueueMetrics:
    capacity = active * per_counter
    return QueueMetrics(
        zone_id=zone_id,
        zone_name=zone_id.replace("-", " ").title(),
        frame_seq=1,
        frame_ts=NOW,
        person_count=people,
        formation=formation,
        formation_confidence=0.8,
        geometry=QueueGeometry(sample_size=people),
        flow=FlowRates(
            window_seconds=180.0,
            arrivals=int(arrival * 3),
            departures_served=int(served * 3),
            departures_abandoned=0,
            arrival_rate_per_min=arrival,
            service_rate_per_min=served,
            rate_source=rate_source,
            observation_seconds=observed,
        ),
        capacity=ServiceCapacity(
            total_counters=total,
            active_counters=active,
            service_rate_per_counter_per_min=per_counter,
            rate_source=rate_source,
        ),
        wait=WaitEstimate(
            minutes=people / capacity if capacity else None,
            queue_length=people,
            effective_service_rate_per_min=capacity,
            rate_source=rate_source,
            confidence=0.7,
        ),
    )


def forecast(
    zone_id: str = "queue-a",
    *,
    current: int = 10,
    expected: tuple[float, float, float] = (11.0, 12.0, 13.0),
    pattern: GrowthPattern = GrowthPattern.STABLE,
    z: float | None = None,
    rate: float = 0.2,
) -> QueueForecast:
    points = tuple(
        ForecastPoint(
            horizon_minutes=horizon,
            at=NOW + timedelta(minutes=horizon),
            expected=value,
            lower=max(0.0, value - 3.0),
            upper=value + 3.0,
        )
        for horizon, value in zip((5, 10, 15), expected, strict=True)
    )
    return QueueForecast(
        zone_id=zone_id,
        zone_name=zone_id.replace("-", " ").title(),
        generated_at=NOW,
        frame_ts=NOW,
        current_length=current,
        points=points,
        growth=GrowthAssessment(
            pattern=pattern,
            growth_rate_per_min=rate,
            baseline_rate_per_min=0.1 if z is not None else None,
            baseline_std=0.4 if z is not None else None,
            z_score=z,
            change_pct=45.0 if pattern is GrowthPattern.ABNORMAL_GROWTH else None,
            window_minutes=5.0,
            samples=30,
            explanation=f"Queue is growing at {rate:.1f} people/min.",
        ),
        confidence=0.7,
        observation_minutes=5.0,
    )


def camera(
    camera_id: str,
    *,
    area: str | None = None,
    role: CameraRole = CameraRole.GENERAL,
    enabled: bool = True,
) -> SiteCamera:
    return SiteCamera(
        camera_id=camera_id,
        name=f"Camera {camera_id[-2:]}",
        role=role,
        coverage_area=area or camera_id,
        enabled=enabled,
    )


def rectangle(x1: float, x2: float) -> ImagePolygon:
    return ImagePolygon(
        points=(
            ImagePoint(x=x1, y=0.0),
            ImagePoint(x=x2, y=0.0),
            ImagePoint(x=x2, y=540.0),
            ImagePoint(x=x1, y=540.0),
        )
    )


QUEUE_ZONE = CameraZone(
    zone_id="queue-a", name="Queue A", zone_type=ZoneType.QUEUE, polygon=rectangle(300, 700)
)
ENTRANCE_ZONE = CameraZone(
    zone_id="entrance", name="Entrance", zone_type=ZoneType.ENTRY, polygon=rectangle(0, 300)
)


def online(
    camera_id: str,
    result: AnalysisResult,
    *,
    zones: tuple[CameraZone, ...] = (),
    age: float = 0.5,
    status: CameraConnectionStatus = CameraConnectionStatus.ONLINE,
) -> CameraObservation:
    return CameraObservation(
        camera_id=camera_id,
        status=status,
        analysis=result,
        analysis_age_seconds=age,
        zones=zones,
    )


def offline(
    camera_id: str,
    *,
    zones: tuple[CameraZone, ...] = (),
    status: CameraConnectionStatus = CameraConnectionStatus.OFFLINE,
    detail: str = "No frame for 22s - the stream appears to have stopped.",
) -> CameraObservation:
    return CameraObservation(camera_id=camera_id, status=status, status_detail=detail, zones=zones)


def site(*cameras: SiteCamera, links: Sequence[FlowLinkConfig] = ()) -> SiteTopology:
    return SiteTopology(cameras=cameras, links=tuple(links))


def zone_flow(
    camera_id: str,
    *snapshots: ZoneFlowSnapshot,
    transitions: Sequence[ZoneTransition] = (),
    observed: float = 300.0,
) -> ZoneFlowReport:
    return ZoneFlowReport(
        camera_id=camera_id,
        frame_seq=1,
        frame_ts=NOW,
        window_seconds=180.0,
        observation_seconds=observed,
        zones=snapshots,
        transitions=tuple(transitions),
    )


def snapshot(
    zone: CameraZone, *, occupancy: int = 3, entry: float = 2.0, exit: float = 2.0
) -> ZoneFlowSnapshot:
    return ZoneFlowSnapshot(
        zone_id=zone.zone_id,
        zone_name=zone.name,
        zone_type=zone.zone_type,
        occupancy=occupancy,
        entries=int(entry * 3),
        exits=int(exit * 3),
        entry_rate_per_min=entry,
        exit_rate_per_min=exit,
    )


# ---------------------------------------------------------------------------
# Headcount
# ---------------------------------------------------------------------------


class TestHeadcount:
    def test_cameras_watching_separate_areas_are_added(self, base: AnalysisResult) -> None:
        report = SiteIntelligence().update(
            site(camera("cam-01"), camera("cam-02")),
            [
                online("cam-01", analysis(base, "cam-01", 5)),
                online("cam-02", analysis(base, "cam-02", 7)),
            ],
            NOW,
        )

        count = report.headcount
        assert (count.value, count.upper_bound) == (12, 12)
        assert count.aggregation is CountAggregation.INDEPENDENT_SUM
        assert count.label == "Combined observed count"
        assert count.complete
        assert report.cameras_contributing == 2
        assert not report.degraded

    def test_cameras_sharing_an_area_are_not_added(self, base: AnalysisResult) -> None:
        report = SiteIntelligence().update(
            site(camera("cam-01", area="Ticket Hall"), camera("cam-02", area="Ticket Hall")),
            [
                online("cam-01", analysis(base, "cam-01", 5)),
                online("cam-02", analysis(base, "cam-02", 7)),
            ],
            NOW,
        )

        count = report.headcount
        assert (count.value, count.upper_bound) == (7, 12)
        assert count.aggregation is CountAggregation.OVERLAP_ADJUSTED
        assert count.areas[0].overlapping
        assert "at least 7 and at most 12" in count.explanation

    def test_an_offline_camera_is_missing_never_zero(self, base: AnalysisResult) -> None:
        report = SiteIntelligence().update(
            site(camera("cam-01"), camera("cam-02")),
            [offline("cam-01"), online("cam-02", analysis(base, "cam-02", 7))],
            NOW,
        )

        assert report.headcount.value == 7
        assert report.headcount.missing_camera_ids == ("cam-01",)
        assert not report.headcount.complete
        assert "CAM-01 is offline" in report.headcount.explanation

        cam1 = report.cameras[0]
        assert cam1.contributing is False
        assert cam1.people_count is None
        assert cam1.csi is None
        assert cam1.excluded_reason == "No frame for 22s - the stream appears to have stopped."

        assert report.degraded
        assert "Global analysis degraded - CAM-01 offline" in report.degraded_reasons
        assert report.cameras_contributing == 1

    def test_with_no_contributing_camera_there_is_no_count(self) -> None:
        report = SiteIntelligence().update(
            site(camera("cam-01"), camera("cam-02")), [offline("cam-01"), offline("cam-02")], NOW
        )

        assert report.headcount.value is None
        assert report.headcount.upper_bound is None
        assert report.headcount.aggregation is CountAggregation.NO_DATA

    def test_a_disabled_camera_is_neither_counted_nor_missing(self, base: AnalysisResult) -> None:
        report = SiteIntelligence().update(
            site(camera("cam-01", enabled=False), camera("cam-02")),
            [offline("cam-01"), online("cam-02", analysis(base, "cam-02", 7))],
            NOW,
        )

        assert report.headcount.value == 7
        assert report.headcount.missing_camera_ids == ()
        assert report.cameras[0].status is CameraConnectionStatus.DISABLED
        assert not report.degraded

    def test_stale_analysis_is_not_used(self, base: AnalysisResult) -> None:
        report = SiteIntelligence().update(
            site(camera("cam-01"), camera("cam-02")),
            [
                online("cam-01", analysis(base, "cam-01", 5), age=30.0),
                online("cam-02", analysis(base, "cam-02", 7)),
            ],
            NOW,
        )

        assert report.headcount.value == 7
        assert report.cameras[0].excluded_reason == "The latest analysis is 30s old."
        assert report.cameras[0].people_count is None

    def test_an_offline_camera_in_a_shared_area_leaves_the_area_counted(
        self, base: AnalysisResult
    ) -> None:
        report = SiteIntelligence().update(
            site(camera("cam-01", area="Ticket Hall"), camera("cam-02", area="Ticket Hall")),
            [offline("cam-01"), online("cam-02", analysis(base, "cam-02", 7))],
            NOW,
        )

        assert report.headcount.value == 7
        assert "Ticket Hall is still counted by CAM-02" in report.headcount.explanation

    def test_a_configured_camera_that_reports_nothing_is_offline(
        self, base: AnalysisResult
    ) -> None:
        report = SiteIntelligence().update(
            site(camera("cam-01"), camera("cam-03")),
            [online("cam-01", analysis(base, "cam-01", 5))],
            NOW,
        )

        assert report.headcount.missing_camera_ids == ("cam-03",)
        assert report.cameras[1].status is CameraConnectionStatus.OFFLINE


# ---------------------------------------------------------------------------
# Queues, forecasts and staffing
# ---------------------------------------------------------------------------


class TestQueues:
    def test_queues_in_separate_areas_are_pooled(self, base: AnalysisResult) -> None:
        report = SiteIntelligence().update(
            site(camera("cam-01"), camera("cam-02")),
            [
                online(
                    "cam-01",
                    analysis(
                        base,
                        "cam-01",
                        12,
                        queues=[queue(people=10, arrival=4.0, active=2, total=4, per_counter=2.0)],
                    ),
                ),
                online(
                    "cam-02",
                    analysis(
                        base,
                        "cam-02",
                        8,
                        queues=[
                            queue(
                                "queue-b", people=6, arrival=3.0, active=1, total=2, per_counter=3.0
                            )
                        ],
                    ),
                ),
            ],
            NOW,
        )

        pooled = report.queue
        assert pooled is not None
        assert pooled.queue_length == 16
        assert pooled.arrival_rate_per_min == pytest.approx(7.0)
        assert pooled.effective_capacity_per_min == pytest.approx(7.0)
        assert (pooled.total_counters, pooled.active_counters) == (6, 3)
        assert pooled.wait_minutes == pytest.approx(16 / 7)
        assert pooled.capacity_pressure == pytest.approx(1.0)
        assert [ref.zone_id for ref in pooled.zones] == ["queue-a", "queue-b"]

    def test_one_queue_seen_by_two_cameras_is_counted_once(self, base: AnalysisResult) -> None:
        report = SiteIntelligence().update(
            site(camera("cam-01", area="Ticket Hall"), camera("cam-02", area="Ticket Hall")),
            [
                online(
                    "cam-01", analysis(base, "cam-01", 12, queues=[queue(people=10, arrival=4.0)])
                ),
                online(
                    "cam-02", analysis(base, "cam-02", 9, queues=[queue(people=8, arrival=3.5)])
                ),
            ],
            NOW,
        )

        pooled = report.queue
        assert pooled is not None
        assert (pooled.queue_length, pooled.upper_bound) == (10, 18)
        assert pooled.aggregation is CountAggregation.OVERLAP_ADJUSTED
        # Rates and counters come from the one camera representing the queue.
        assert pooled.arrival_rate_per_min == pytest.approx(4.0)
        assert pooled.total_counters == 4

    def test_a_pool_is_only_as_measured_as_its_least_measured_queue(
        self, base: AnalysisResult
    ) -> None:
        report = SiteIntelligence().update(
            site(camera("cam-01"), camera("cam-02")),
            [
                online("cam-01", analysis(base, "cam-01", 12, queues=[queue()])),
                online(
                    "cam-02",
                    analysis(
                        base,
                        "cam-02",
                        8,
                        queues=[queue("queue-b", rate_source=RateSource.CONFIGURED)],
                    ),
                ),
            ],
            NOW,
        )
        assert report.queue is not None
        assert report.queue.rate_source is RateSource.CONFIGURED

    def test_with_no_queue_anywhere_nothing_is_pooled_forecast_or_planned(
        self, base: AnalysisResult
    ) -> None:
        report = SiteIntelligence().update(
            site(camera("cam-01")), [online("cam-01", analysis(base, "cam-01", 5))], NOW
        )

        assert report.queue is None
        assert not report.queue_forecast.available
        assert (
            report.queue_forecast.withheld_reason == "No contributing camera is measuring a queue."
        )
        assert report.resource_plan is None
        assert report.resource_plan_withheld_reason is not None

    def test_a_missing_queue_camera_withholds_the_queue_forecast_and_plan(
        self, base: AnalysisResult
    ) -> None:
        report = SiteIntelligence().update(
            site(camera("cam-01"), camera("cam-02", role=CameraRole.QUEUE)),
            [
                online("cam-01", analysis(base, "cam-01", 12, queues=[queue()])),
                offline("cam-02", zones=(QUEUE_ZONE,)),
            ],
            NOW,
        )

        assert report.queue is not None
        assert report.queue.missing_camera_ids == ("cam-02",)
        assert not report.queue_forecast.available
        assert "CAM-02" in (report.queue_forecast.withheld_reason or "")
        assert report.resource_plan is None
        assert "understate demand" in (report.resource_plan_withheld_reason or "")

    def test_the_site_staffing_plan_comes_from_the_allocator(self, base: AnalysisResult) -> None:
        report = SiteIntelligence().update(
            site(camera("cam-01"), camera("cam-02")),
            [
                online(
                    "cam-01",
                    analysis(
                        base,
                        "cam-01",
                        30,
                        queues=[queue(people=25, arrival=6.0, active=1, total=3)],
                    ),
                ),
                online(
                    "cam-02",
                    analysis(
                        base,
                        "cam-02",
                        8,
                        queues=[queue("queue-b", people=5, arrival=2.0, active=1, total=2)],
                    ),
                ),
            ],
            NOW,
        )

        plan = report.resource_plan
        assert plan is not None
        assert plan.zone_id == "site-queues"
        assert plan.total_counters == 5
        assert len(plan.options) == 6  # zero to five counters
        assert any("one pool" in assumption for assumption in plan.assumptions)


class TestSiteForecasts:
    def test_the_demand_forecast_is_withheld_while_a_camera_is_missing(
        self, base: AnalysisResult
    ) -> None:
        report = SiteIntelligence().update(
            site(camera("cam-01"), camera("cam-02")),
            [offline("cam-01"), online("cam-02", analysis(base, "cam-02", 7))],
            NOW,
        )

        demand = report.demand_forecast
        assert not demand.available
        assert demand.forecast is None
        assert "CAM-01" in (demand.withheld_reason or "")
        assert "fall in demand" in (demand.withheld_reason or "")

    def test_the_demand_forecast_is_the_trend_of_the_combined_count(
        self, base: AnalysisResult
    ) -> None:
        intelligence = SiteIntelligence()
        topology = site(camera("cam-01"), camera("cam-02"))
        report = None
        for step in range(40):  # 200 seconds, growing steadily
            at = NOW + timedelta(seconds=5 * step)
            report = intelligence.update(
                topology,
                [
                    online("cam-01", analysis(base, "cam-01", 5 + step // 4)),
                    online("cam-02", analysis(base, "cam-02", 5 + step // 4)),
                ],
                at,
            )
        assert report is not None

        demand = report.demand_forecast
        assert demand.available
        assert demand.forecast is not None
        assert demand.forecast.points, "the trend method has enough history"
        assert demand.forecast.points[-1].expected > demand.forecast.current_length
        flow = demand.forecast.method(ForecastMethod.FLOW_BALANCE)
        assert flow is not None and not flow.available
        assert "headcount has no measured arrival" in (flow.unavailable_reason or "")
        assert not demand.forecast.growth.explanation.startswith("Queue")
        assert "CAM-01 and CAM-02" in demand.basis

    def test_a_change_in_contributing_cameras_restarts_forecast_history(
        self, base: AnalysisResult
    ) -> None:
        intelligence = SiteIntelligence()
        one = site(camera("cam-01"), camera("cam-02", enabled=False))
        for step in range(30):
            intelligence.update(
                one,
                [online("cam-01", analysis(base, "cam-01", 5 + step // 3)), offline("cam-02")],
                NOW + timedelta(seconds=5 * step),
            )

        both = site(camera("cam-01"), camera("cam-02"))
        report = intelligence.update(
            both,
            [
                online("cam-01", analysis(base, "cam-01", 15)),
                online("cam-02", analysis(base, "cam-02", 9)),
            ],
            NOW + timedelta(seconds=150),
        )

        forecast = report.demand_forecast.forecast
        assert forecast is not None
        assert forecast.points == ()  # history restarted with the new aggregate

    def test_a_camera_returning_resumes_the_same_history(self, base: AnalysisResult) -> None:
        intelligence = SiteIntelligence()
        topology = site(camera("cam-01"), camera("cam-02"))
        step = 0
        for step in range(30):
            intelligence.update(
                topology,
                [
                    online("cam-01", analysis(base, "cam-01", 5 + step // 3)),
                    online("cam-02", analysis(base, "cam-02", 4)),
                ],
                NOW + timedelta(seconds=5 * step),
            )
        outage = intelligence.update(
            topology,
            [offline("cam-01"), online("cam-02", analysis(base, "cam-02", 4))],
            NOW + timedelta(seconds=5 * step + 5),
        )
        assert not outage.demand_forecast.available

        back = intelligence.update(
            topology,
            [
                online("cam-01", analysis(base, "cam-01", 15)),
                online("cam-02", analysis(base, "cam-02", 4)),
            ],
            NOW + timedelta(seconds=5 * step + 20),
        )
        assert back.demand_forecast.forecast is not None
        assert back.demand_forecast.forecast.points != ()


# ---------------------------------------------------------------------------
# Time to pressure
# ---------------------------------------------------------------------------


class TestTimeToPressure:
    def test_the_crossing_is_interpolated_between_horizons(self) -> None:
        result = time_to_pressure(
            label="Queue A (CAM-02)",
            forecast=forecast(current=10, expected=(14.0, 22.0, 30.0)),
            capacity_per_min=2.0,
            target_wait_minutes=10.0,
        )

        assert result is not None
        assert result.threshold_queue_length == pytest.approx(20.0)
        # 14 at +5 and 22 at +10: 20 is three quarters of the way.
        assert result.minutes == pytest.approx(8.75)
        assert result.within_horizon and not result.already_exceeded
        assert result.explanation.startswith("Forecast:")

    def test_a_queue_already_past_target_says_so(self) -> None:
        result = time_to_pressure(
            label="Queue A",
            forecast=forecast(current=25),
            capacity_per_min=2.0,
            target_wait_minutes=10.0,
        )
        assert result is not None
        assert result.already_exceeded
        assert result.minutes == 0.0

    def test_a_forecast_that_stays_under_target_is_not_within_the_horizon(self) -> None:
        result = time_to_pressure(
            label="Queue A",
            forecast=forecast(current=5, expected=(6.0, 7.0, 8.0)),
            capacity_per_min=2.0,
            target_wait_minutes=10.0,
        )
        assert result is not None
        assert result.minutes is None
        assert not result.within_horizon
        assert "stays under 20 people" in result.explanation

    def test_with_no_counter_open_there_is_no_threshold(self) -> None:
        result = time_to_pressure(
            label="Queue A",
            forecast=forecast(current=3),
            capacity_per_min=0.0,
            target_wait_minutes=10.0,
        )
        assert result is not None
        assert result.threshold_queue_length is None
        assert result.already_exceeded

    def test_with_no_forecast_there_is_nothing_to_read(self) -> None:
        empty = forecast().model_copy(update={"points": ()})
        assert (
            time_to_pressure(
                label="Queue A", forecast=empty, capacity_per_min=2.0, target_wait_minutes=10.0
            )
            is None
        )

    def test_the_site_report_orders_the_most_urgent_first(self, base: AnalysisResult) -> None:
        report = SiteIntelligence().update(
            site(camera("cam-01"), camera("cam-02")),
            [
                online(
                    "cam-01",
                    analysis(
                        base,
                        "cam-01",
                        8,
                        queues=[queue(people=5, active=1, per_counter=2.0)],
                        forecasts=[forecast(current=5, expected=(6.0, 7.0, 8.0))],
                    ),
                ),
                online(
                    "cam-02",
                    analysis(
                        base,
                        "cam-02",
                        30,
                        queues=[queue("queue-b", people=15, active=1, per_counter=2.0)],
                        forecasts=[forecast("queue-b", current=15, expected=(21.0, 28.0, 34.0))],
                    ),
                ),
            ],
            NOW,
        )

        labels = [item.label for item in report.time_to_pressure]
        assert labels[0] == "Queue B (CAM-02)"
        assert report.time_to_pressure[0].within_horizon


# ---------------------------------------------------------------------------
# Hotspot
# ---------------------------------------------------------------------------


class TestHotspot:
    def test_the_hotspot_is_where_congestion_measures_worst_not_where_most_people_are(
        self, base: AnalysisResult
    ) -> None:
        report = SiteIntelligence().update(
            site(camera("cam-01"), camera("cam-02")),
            [
                online("cam-01", analysis(base, "cam-01", 60, csi=92.0, density_pressure=20.0)),
                online(
                    "cam-02",
                    analysis(
                        base,
                        "cam-02",
                        9,
                        csi=45.0,
                        density_pressure=70.0,
                        queues=[queue(people=9, arrival=6.0, active=2, per_counter=2.0)],
                        forecasts=[
                            forecast(pattern=GrowthPattern.ABNORMAL_GROWTH, z=4.5, rate=2.4)
                        ],
                    ),
                ),
            ],
            NOW,
        )

        hotspot = report.hotspot
        assert hotspot is not None
        assert hotspot.camera_id == "cam-02"
        assert hotspot.zone_id == "queue-a"
        assert {factor.key for factor in hotspot.factors} == {
            "density",
            "instability",
            "growth",
            "capacity",
        }
        assert sum(factor.weight for factor in hotspot.factors) == pytest.approx(1.0)
        assert sum(factor.contribution for factor in hotspot.factors) == pytest.approx(1.0)
        assert hotspot.reasons

    def test_a_calm_site_has_no_hotspot(self, base: AnalysisResult) -> None:
        report = SiteIntelligence().update(
            site(camera("cam-01")),
            [online("cam-01", analysis(base, "cam-01", 80, csi=96.0, density_pressure=10.0))],
            NOW,
        )
        assert report.hotspot is None

    def test_unmeasurable_factors_are_left_out(self, base: AnalysisResult) -> None:
        report = SiteIntelligence(
            SiteIntelligenceConfig(hotspot_min_score=0.0, hotspot_alert_score=1.0)
        ).update(
            site(camera("cam-01")),
            [online("cam-01", analysis(base, "cam-01", 20, csi=50.0, density_pressure=60.0))],
            NOW,
        )
        hotspot = report.hotspot
        assert hotspot is not None
        assert {factor.key for factor in hotspot.factors} == {"density", "instability"}
        assert sum(factor.weight for factor in hotspot.factors) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Flow
# ---------------------------------------------------------------------------


class TestFlow:
    def test_a_link_within_one_camera_is_tracked(self, base: AnalysisResult) -> None:
        flow = zone_flow(
            "cam-01",
            snapshot(ENTRANCE_ZONE, exit=5.0),
            snapshot(QUEUE_ZONE, entry=4.0),
            transitions=[
                ZoneTransition(
                    from_zone_id="entrance",
                    to_zone_id="queue-a",
                    count=12,
                    rate_per_min=4.0,
                    median_transit_seconds=18.0,
                )
            ],
        )
        report = SiteIntelligence().update(
            site(
                camera("cam-01"),
                links=[
                    FlowLinkConfig(
                        from_camera_id="cam-01",
                        from_zone_id="entrance",
                        to_camera_id="cam-01",
                        to_zone_id="queue-a",
                    )
                ],
            ),
            [
                online(
                    "cam-01",
                    analysis(base, "cam-01", 8, zone_flow=flow),
                    zones=(ENTRANCE_ZONE, QUEUE_ZONE),
                )
            ],
            NOW,
        )

        (link,) = report.flow_links
        assert link.basis is FlowLinkBasis.TRACKED
        assert link.tracked_rate_per_min == pytest.approx(4.0)
        assert link.median_transit_seconds == pytest.approx(18.0)
        assert "counted moving from Entrance to Queue A on CAM-01" in link.explanation

    def test_a_link_across_cameras_is_correlated_never_tracked(self, base: AnalysisResult) -> None:
        report = SiteIntelligence().update(
            site(
                camera("cam-01"),
                camera("cam-02"),
                links=[
                    FlowLinkConfig(
                        from_camera_id="cam-01",
                        from_zone_id="entrance",
                        to_camera_id="cam-02",
                        to_zone_id="queue-a",
                    )
                ],
            ),
            [
                online(
                    "cam-01",
                    analysis(
                        base,
                        "cam-01",
                        8,
                        zone_flow=zone_flow("cam-01", snapshot(ENTRANCE_ZONE, exit=6.0)),
                    ),
                    zones=(ENTRANCE_ZONE,),
                ),
                online(
                    "cam-02",
                    analysis(
                        base,
                        "cam-02",
                        8,
                        zone_flow=zone_flow("cam-02", snapshot(QUEUE_ZONE, entry=4.5)),
                    ),
                    zones=(QUEUE_ZONE,),
                ),
            ],
            NOW,
        )

        (link,) = report.flow_links
        assert link.basis is FlowLinkBasis.CORRELATED
        assert link.tracked_rate_per_min is None
        assert link.conversion_ratio == pytest.approx(0.75)
        assert "not followed between cameras" in link.explanation

    def test_rates_too_small_to_compare_are_not_divided(self, base: AnalysisResult) -> None:
        report = SiteIntelligence().update(
            site(
                camera("cam-01"),
                camera("cam-02"),
                links=[
                    FlowLinkConfig(
                        from_camera_id="cam-01",
                        from_zone_id="entrance",
                        to_camera_id="cam-02",
                        to_zone_id="queue-a",
                    )
                ],
            ),
            [
                online(
                    "cam-01",
                    analysis(
                        base,
                        "cam-01",
                        8,
                        zone_flow=zone_flow("cam-01", snapshot(ENTRANCE_ZONE, exit=0.2)),
                    ),
                    zones=(ENTRANCE_ZONE,),
                ),
                online(
                    "cam-02",
                    analysis(
                        base,
                        "cam-02",
                        8,
                        zone_flow=zone_flow("cam-02", snapshot(QUEUE_ZONE, entry=3.0)),
                    ),
                    zones=(QUEUE_ZONE,),
                ),
            ],
            NOW,
        )
        assert report.flow_links[0].conversion_ratio is None

    def test_a_link_to_an_offline_camera_is_unavailable_and_says_why(
        self, base: AnalysisResult
    ) -> None:
        report = SiteIntelligence().update(
            site(
                camera("cam-01"),
                camera("cam-02"),
                links=[
                    FlowLinkConfig(
                        from_camera_id="cam-01",
                        from_zone_id="entrance",
                        to_camera_id="cam-02",
                        to_zone_id="queue-a",
                    )
                ],
            ),
            [
                online(
                    "cam-01",
                    analysis(
                        base, "cam-01", 8, zone_flow=zone_flow("cam-01", snapshot(ENTRANCE_ZONE))
                    ),
                    zones=(ENTRANCE_ZONE,),
                ),
                offline("cam-02", zones=(QUEUE_ZONE,)),
            ],
            NOW,
        )

        (link,) = report.flow_links
        assert link.basis is FlowLinkBasis.UNAVAILABLE
        assert link.explanation == "CAM-02 is offline, so this link has no figures."

        node = next(node for node in report.flow_nodes if node.camera_id == "cam-02")
        assert node.zone_name == "Queue A"
        assert node.available is False
        assert node.occupancy is None

    def test_a_link_to_a_zone_that_does_not_exist_says_so(self, base: AnalysisResult) -> None:
        report = SiteIntelligence().update(
            site(
                camera("cam-01"),
                links=[
                    FlowLinkConfig(
                        from_camera_id="cam-01",
                        from_zone_id="entrance",
                        to_camera_id="cam-01",
                        to_zone_id="gone",
                    )
                ],
            ),
            [
                online(
                    "cam-01",
                    analysis(
                        base, "cam-01", 8, zone_flow=zone_flow("cam-01", snapshot(ENTRANCE_ZONE))
                    ),
                    zones=(ENTRANCE_ZONE,),
                )
            ],
            NOW,
        )
        assert report.flow_links[0].basis is FlowLinkBasis.UNAVAILABLE
        assert "no zone called 'gone'" in report.flow_links[0].explanation


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------


def _kinds(report) -> list[SiteAlertKind]:
    return [alert.kind for alert in report.alerts]


class TestAlerts:
    def test_abnormal_growth_is_critical_and_carries_its_evidence(
        self, base: AnalysisResult
    ) -> None:
        report = SiteIntelligence().update(
            site(camera("cam-02")),
            [
                online(
                    "cam-02",
                    analysis(
                        base,
                        "cam-02",
                        14,
                        queues=[queue(people=12)],
                        forecasts=[
                            forecast(
                                current=12, pattern=GrowthPattern.ABNORMAL_GROWTH, z=4.2, rate=2.5
                            )
                        ],
                    ),
                )
            ],
            NOW,
        )

        alert = next(
            alert for alert in report.alerts if alert.kind is SiteAlertKind.ABNORMAL_GROWTH
        )
        assert alert.severity is Severity.CRITICAL
        assert alert.alert_id == "abnormal-growth:cam-02:queue-a"
        assert alert.camera_id == "cam-02" and alert.zone_id == "queue-a"
        assert any("4.2 standard deviations" in line for line in alert.evidence)
        assert any(line.startswith("Now 12; forecast +15 min") for line in alert.evidence)

    def test_a_queue_forming_raises_nothing(self, base: AnalysisResult) -> None:
        report = SiteIntelligence().update(
            site(camera("cam-02")),
            [
                online(
                    "cam-02",
                    analysis(
                        base,
                        "cam-02",
                        14,
                        queues=[queue(people=12, arrival=2.0, active=2, per_counter=2.0)],
                        forecasts=[forecast(current=12, pattern=GrowthPattern.GROWING, rate=0.6)],
                    ),
                )
            ],
            NOW,
        )
        assert report.alerts == ()

    def test_arrivals_outpacing_capacity_warn_once_rates_are_established(
        self, base: AnalysisResult
    ) -> None:
        busy = queue(people=12, arrival=6.0, active=2, per_counter=2.0, observed=300.0)
        report = SiteIntelligence().update(
            site(camera("cam-02")),
            [online("cam-02", analysis(base, "cam-02", 14, queues=[busy]))],
            NOW,
        )
        alert = next(
            alert for alert in report.alerts if alert.kind is SiteAlertKind.CAPACITY_PRESSURE
        )
        assert alert.severity is Severity.WARNING
        assert any("Capacity 4.0/min with 2 of 4 counters open" in line for line in alert.evidence)

        early = queue(people=12, arrival=6.0, active=2, per_counter=2.0, observed=20.0)
        report = SiteIntelligence().update(
            site(camera("cam-02")),
            [online("cam-02", analysis(base, "cam-02", 14, queues=[early]))],
            NOW,
        )
        assert SiteAlertKind.CAPACITY_PRESSURE not in _kinds(report)

    def test_a_lost_camera_raises_offline_and_degraded_coverage(self, base: AnalysisResult) -> None:
        report = SiteIntelligence().update(
            site(camera("cam-01"), camera("cam-02")),
            [offline("cam-01"), online("cam-02", analysis(base, "cam-02", 7))],
            NOW,
        )

        coverage = next(
            alert for alert in report.alerts if alert.kind is SiteAlertKind.DEGRADED_COVERAGE
        )
        assert coverage.title == "Global analysis degraded - CAM-01 offline"
        assert "demand forecast is withheld" in coverage.explanation
        offline_alert = next(
            alert for alert in report.alerts if alert.kind is SiteAlertKind.CAMERA_OFFLINE
        )
        assert offline_alert.alert_id == "camera-offline:cam-01"
        assert offline_alert.title == "CAM-01 offline"

    def test_a_camera_still_connecting_is_not_an_alert(self, base: AnalysisResult) -> None:
        report = SiteIntelligence().update(
            site(camera("cam-01"), camera("cam-02")),
            [
                offline(
                    "cam-01",
                    status=CameraConnectionStatus.CONNECTING,
                    detail="Connected; waiting for the first frame.",
                ),
                online("cam-02", analysis(base, "cam-02", 7)),
            ],
            NOW,
        )
        assert report.alerts == ()
        assert report.degraded  # the figures are still incomplete, and say so

    def test_alerts_are_ordered_most_severe_first(self, base: AnalysisResult) -> None:
        report = SiteIntelligence().update(
            site(camera("cam-01"), camera("cam-02")),
            [
                offline("cam-01"),
                online(
                    "cam-02",
                    analysis(
                        base,
                        "cam-02",
                        14,
                        queues=[queue(people=12)],
                        forecasts=[
                            forecast(
                                current=12, pattern=GrowthPattern.ABNORMAL_GROWTH, z=4.2, rate=2.5
                            )
                        ],
                    ),
                ),
            ],
            NOW,
        )
        severities = [alert.severity for alert in report.alerts]
        assert severities[0] is Severity.CRITICAL
        assert severities == sorted(
            severities, key=[Severity.CRITICAL, Severity.WARNING, Severity.INFO].index
        )


class TestCameraSummaries:
    def test_figures_appear_only_for_contributing_cameras(self, base: AnalysisResult) -> None:
        report = SiteIntelligence().update(
            site(camera("cam-01"), camera("cam-02", role=CameraRole.QUEUE)),
            [
                offline("cam-01"),
                online(
                    "cam-02",
                    analysis(
                        base,
                        "cam-02",
                        14,
                        queues=[queue(people=12)],
                        forecasts=[forecast(current=12, expected=(13.0, 15.0, 17.0))],
                    ),
                    zones=(QUEUE_ZONE,),
                ),
            ],
            NOW,
        )

        cam1, cam2 = report.cameras
        assert (cam1.people_count, cam1.queue_length, cam1.predicted_queue) == (None, None, None)
        assert cam2.people_count == 14
        assert cam2.queue_length == 12
        assert cam2.queue_zone_count == 1
        assert cam2.predicted_queue == pytest.approx(15.0)
        assert cam2.predicted_horizon_minutes == 10
        assert cam2.role is CameraRole.QUEUE
