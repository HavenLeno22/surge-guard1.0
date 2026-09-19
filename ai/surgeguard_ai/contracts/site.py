"""Site contracts - intelligence across every camera at once.

A site is several cameras watching parts of one venue. These contracts describe
what the platform can honestly say about the whole of it, and are shaped by
three rules that run through every field:

1. **A camera that is not contributing is absent, never zero.** Its figures are
   ``None``, it is named in ``missing_camera_ids``, and the report is marked
   degraded. An offline camera and an empty room are opposite facts.
2. **Overlapping views are not added.** Cameras that share a coverage area can
   see the same person twice. Within a shared area the largest single-camera
   count is used and the plain sum is carried as the upper bound, so a combined
   figure is never presented as a count of unique people when it might not be.
3. **Movement across cameras is correlated, not tracked.** Nobody is
   re-identified between cameras. A link between zones on different cameras
   shows two measured rates side by side and is labelled as such.

Nothing here is a new forecasting or allocation method. Site forecasts and the
site staffing plan are produced by the same
:class:`~surgeguard_ai.forecast.QueueForecaster` and
:class:`~surgeguard_ai.resources.ResourceAllocator` every camera uses, fed with
site-level aggregates, and they reuse those engines' contracts.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from .base import Contract
from .enums import (
    CameraConnectionStatus,
    CameraRole,
    CountAggregation,
    CountMethod,
    FlowLinkBasis,
    GrowthPattern,
    OperationalStatus,
    RateSource,
    Severity,
    SiteAlertKind,
    SiteForecastScope,
    SourceMode,
    ZoneType,
)
from .forecast import QueueForecast
from .resources import ResourcePlan

__all__ = [
    "CoverageAreaCount",
    "FlowLinkConfig",
    "Hotspot",
    "HotspotFactor",
    "QueueZoneRef",
    "SiteAlert",
    "SiteCamera",
    "SiteCameraSummary",
    "SiteFlowNode",
    "SiteForecast",
    "SiteHeadcount",
    "SiteQueueSummary",
    "SiteReport",
    "SiteTopology",
    "TimeToPressure",
    "ZoneFlowLink",
]


# ---------------------------------------------------------------------------
# Configuration - how the venue is laid out
# ---------------------------------------------------------------------------


class SiteCamera(Contract):
    """One camera as the site sees it: identity, role and coverage."""

    camera_id: str
    name: str
    role: CameraRole = CameraRole.GENERAL
    coverage_area: str = Field(
        description=(
            "Physical area this camera watches. Cameras sharing a value are "
            "treated as overlapping; a camera with an area of its own is "
            "independent and its count adds to the others."
        )
    )
    enabled: bool = True


class FlowLinkConfig(Contract):
    """A directed connection between two camera zones: people in one feed the other.

    Zones belong to cameras because every camera has its own image coordinate
    space; a link therefore names both ends by camera *and* zone.
    """

    from_camera_id: str
    from_zone_id: str
    to_camera_id: str
    to_zone_id: str

    @property
    def link_id(self) -> str:
        return f"{self.from_camera_id}:{self.from_zone_id}->{self.to_camera_id}:{self.to_zone_id}"

    @property
    def crosses_cameras(self) -> bool:
        return self.from_camera_id != self.to_camera_id


class SiteTopology(Contract):
    """The site layout: which cameras exist and how their zones connect."""

    cameras: tuple[SiteCamera, ...] = Field(default=())
    links: tuple[FlowLinkConfig, ...] = Field(default=())


# ---------------------------------------------------------------------------
# Per-camera summaries
# ---------------------------------------------------------------------------


class SiteCameraSummary(Contract):
    """One camera's headline figures, or the reason it has none."""

    camera_id: str
    name: str
    role: CameraRole
    coverage_area: str
    status: CameraConnectionStatus
    status_detail: str | None = None

    contributing: bool = Field(
        description="Whether this camera's measurements entered the site figures."
    )
    excluded_reason: str | None = Field(
        default=None,
        description="Why a camera's measurements were left out, in operator terms.",
    )

    source_mode: SourceMode | None = None
    observed_at: datetime | None = None
    analysis_age_seconds: float | None = Field(default=None, ge=0.0)

    people_count: int | None = Field(
        default=None,
        ge=0,
        description="None whenever the camera is not contributing - never zero for missing.",
    )
    count_method: CountMethod | None = None
    operational_status: OperationalStatus | None = None
    csi: float | None = Field(default=None, ge=0.0, le=100.0)
    density_max: float | None = Field(default=None, ge=0.0)
    density_is_metric: bool = False

    queue_zone_count: int = Field(default=0, ge=0)
    queue_length: int | None = Field(default=None, ge=0)
    arrival_rate_per_min: float | None = Field(default=None, ge=0.0)
    service_rate_per_min: float | None = Field(default=None, ge=0.0)
    wait_minutes: float | None = Field(default=None, ge=0.0)
    growth_pattern: GrowthPattern | None = None
    growth_rate_per_min: float | None = None
    predicted_queue: float | None = Field(
        default=None,
        ge=0.0,
        description="Consensus forecast for this camera's queues at the decision horizon.",
    )
    predicted_horizon_minutes: int | None = Field(default=None, gt=0)


# ---------------------------------------------------------------------------
# Headcount
# ---------------------------------------------------------------------------


class CoverageAreaCount(Contract):
    """The count for one physical area, from every camera that covers it."""

    coverage_area: str
    camera_ids: tuple[str, ...]
    value: int = Field(ge=0, description="Largest single-camera count in the area.")
    upper_bound: int = Field(ge=0, description="Sum of every camera's count in the area.")
    overlapping: bool = Field(description="Whether more than one camera covers the area.")


class SiteHeadcount(Contract):
    """People observed across the site, with the method and its limits."""

    value: int | None = Field(
        default=None,
        ge=0,
        description=(
            "Best supportable figure. For independent coverage this is the sum; "
            "with overlap it is a lower bound. None when no camera contributes."
        ),
    )
    upper_bound: int | None = Field(default=None, ge=0)
    aggregation: CountAggregation
    label: str = Field(
        description="Operator-facing name for the figure, e.g. 'Combined observed count'."
    )
    explanation: str
    areas: tuple[CoverageAreaCount, ...] = Field(default=())
    contributing_camera_ids: tuple[str, ...] = Field(default=())
    missing_camera_ids: tuple[str, ...] = Field(
        default=(),
        description="Enabled cameras whose measurements are absent from this figure.",
    )

    @property
    def complete(self) -> bool:
        """Whether every enabled camera contributed."""
        return not self.missing_camera_ids and self.value is not None


# ---------------------------------------------------------------------------
# Queues
# ---------------------------------------------------------------------------


class QueueZoneRef(Contract):
    """One queue zone's contribution to the site queue."""

    camera_id: str
    zone_id: str
    zone_name: str
    coverage_area: str
    queue_length: int = Field(ge=0)
    wait_minutes: float | None = Field(default=None, ge=0.0)
    growth_pattern: GrowthPattern | None = None


class SiteQueueSummary(Contract):
    """Every queue on every contributing camera, pooled."""

    queue_length: int = Field(ge=0, description="Coverage-adjusted people waiting.")
    upper_bound: int = Field(ge=0)
    aggregation: CountAggregation

    arrival_rate_per_min: float = Field(ge=0.0)
    service_rate_per_min: float = Field(
        ge=0.0, description="Measured throughput, summed across queues."
    )
    effective_capacity_per_min: float = Field(
        ge=0.0, description="Active counters times their per-counter rate, summed."
    )
    total_counters: int = Field(ge=0)
    active_counters: int = Field(ge=0)
    rate_source: RateSource = Field(
        description="The least-measured rate source among the pooled queues."
    )
    wait_minutes: float | None = Field(
        default=None,
        ge=0.0,
        description="Pooled queue over pooled capacity. None when nothing is being served.",
    )
    capacity_pressure: float | None = Field(
        default=None,
        ge=0.0,
        description=(
            "Arrival rate over effective capacity. Above 1.0 the queues are "
            "being joined faster than they can be served."
        ),
    )
    zones: tuple[QueueZoneRef, ...] = Field(default=())
    missing_camera_ids: tuple[str, ...] = Field(default=())

    @property
    def complete(self) -> bool:
        return not self.missing_camera_ids


# ---------------------------------------------------------------------------
# Forecasts
# ---------------------------------------------------------------------------


class SiteForecast(Contract):
    """A site-level forecast, or the reason there is none.

    Withheld - not approximated - whenever the aggregate it would forecast is
    incomplete. Projecting a sum that silently lost a camera would forecast a
    drop in demand that never happened.
    """

    scope: SiteForecastScope
    available: bool
    withheld_reason: str | None = None
    forecast: QueueForecast | None = None
    contributing_camera_ids: tuple[str, ...] = Field(default=())
    basis: str = Field(
        default="",
        description="What was aggregated to produce the series, in operator terms.",
    )


# ---------------------------------------------------------------------------
# Hotspot and time to pressure
# ---------------------------------------------------------------------------


class HotspotFactor(Contract):
    """One measured contribution to a congestion score."""

    key: str = Field(description="Stable identifier: density, instability, growth, capacity.")
    label: str
    value: float = Field(ge=0.0, le=1.0, description="Normalised severity of this factor.")
    weight: float = Field(ge=0.0, le=1.0)
    contribution: float = Field(ge=0.0, le=1.0, description="Share of the final score.")
    detail: str = Field(description="The measurement behind the value, e.g. 'z = 4.1'.")


class Hotspot(Contract):
    """The most congested place on the site, and why.

    Scored from density, instability, growth against baseline and capacity
    pressure - never from raw headcount, because a large calm crowd is a venue
    working normally.
    """

    camera_id: str
    zone_id: str | None = None
    label: str
    score: float = Field(ge=0.0, le=1.0)
    reasons: tuple[str, ...] = Field(default=())
    factors: tuple[HotspotFactor, ...] = Field(default=())


class TimeToPressure(Contract):
    """When a queue is projected to exceed its waiting-time target.

    A forecast, labelled as one. Derived from the consensus forecast points and
    the queue's effective capacity: the queue length at which the wait reaches
    target is ``target x capacity``, and the first crossing of the projected
    curve is interpolated between forecast horizons.
    """

    label: str
    camera_id: str | None = Field(default=None, description="None for the site as a whole.")
    zone_id: str | None = None
    minutes: float | None = Field(
        default=None,
        ge=0.0,
        description="Minutes until the target is exceeded; None when not within the horizon.",
    )
    already_exceeded: bool = False
    within_horizon: bool
    horizon_minutes: int = Field(gt=0)
    threshold_queue_length: float | None = Field(default=None, ge=0.0)
    target_wait_minutes: float = Field(gt=0.0)
    explanation: str


# ---------------------------------------------------------------------------
# Flow
# ---------------------------------------------------------------------------


class SiteFlowNode(Contract):
    """A camera zone placed on the site flow map."""

    node_id: str
    camera_id: str
    camera_name: str
    zone_id: str
    zone_name: str
    zone_type: ZoneType
    camera_role: CameraRole
    available: bool = Field(description="Whether the owning camera is contributing.")
    occupancy: int | None = Field(default=None, ge=0)
    entry_rate_per_min: float | None = Field(default=None, ge=0.0)
    exit_rate_per_min: float | None = Field(default=None, ge=0.0)
    dominant_heading_deg: float | None = Field(default=None, ge=0.0, lt=360.0)


class ZoneFlowLink(Contract):
    """Movement between two nodes, and exactly what the figure rests on."""

    link_id: str
    from_node_id: str
    to_node_id: str
    basis: FlowLinkBasis
    from_exit_rate_per_min: float | None = Field(default=None, ge=0.0)
    to_entry_rate_per_min: float | None = Field(default=None, ge=0.0)
    tracked_rate_per_min: float | None = Field(
        default=None,
        ge=0.0,
        description="Counted per track identity. Only ever set for a same-camera link.",
    )
    median_transit_seconds: float | None = Field(default=None, ge=0.0)
    conversion_ratio: float | None = Field(
        default=None,
        ge=0.0,
        description=(
            "Downstream entries over upstream exits. A comparison of two rates, "
            "not a count of the same people; withheld when either rate is too "
            "small to divide meaningfully."
        ),
    )
    explanation: str


# ---------------------------------------------------------------------------
# Alerts and the report
# ---------------------------------------------------------------------------


class SiteAlert(Contract):
    """A condition worth an operator's attention, with the evidence for it."""

    alert_id: str = Field(
        description="Stable key for the condition, so a persisting alert is not re-raised."
    )
    kind: SiteAlertKind
    severity: Severity
    title: str
    explanation: str
    evidence: tuple[str, ...] = Field(
        default=(),
        description="Each measurement the alert rests on, one statement per entry.",
    )
    camera_id: str | None = None
    zone_id: str | None = None


class SiteReport(Contract):
    """The whole site, for one update."""

    generated_at: datetime

    cameras_total: int = Field(ge=0)
    cameras_enabled: int = Field(ge=0)
    cameras_contributing: int = Field(ge=0)
    cameras: tuple[SiteCameraSummary, ...] = Field(default=())

    headcount: SiteHeadcount
    queue: SiteQueueSummary | None = Field(
        default=None, description="None when no contributing camera has a queue zone."
    )

    demand_forecast: SiteForecast
    queue_forecast: SiteForecast
    resource_plan: ResourcePlan | None = None
    resource_plan_withheld_reason: str | None = None

    hotspot: Hotspot | None = None
    time_to_pressure: tuple[TimeToPressure, ...] = Field(default=())

    flow_nodes: tuple[SiteFlowNode, ...] = Field(default=())
    flow_links: tuple[ZoneFlowLink, ...] = Field(default=())

    alerts: tuple[SiteAlert, ...] = Field(default=())

    degraded: bool = False
    degraded_reasons: tuple[str, ...] = Field(default=())
