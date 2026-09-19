"""Canonical enumerations for the SurgeGuard platform.

Every value here is official SurgeGuard terminology (Rule 3, ``15:49-67``).
Do not introduce alternative names for these concepts anywhere in the codebase.

Two distinct five-value taxonomies exist and must never be conflated
(``00_Architecture_Review.md`` C8):

- :class:`OperationalStatus` - the **crowd condition**, derived by the AI from
  the Crowd Stability Index. Owns the semantic status palette.
- :class:`OperationalState` - the **operator workflow phase**, advanced by
  operator interaction. Rendered in a neutral progress palette.
"""

from __future__ import annotations

from enum import StrEnum

__all__ = [
    "OperationalStatus",
    "OperationalState",
    "SourceMode",
    "CountMethod",
    "QueueFormation",
    "RateSource",
    "ForecastMethod",
    "GrowthPattern",
    "StabilityIndicator",
    "ConfidenceFactor",
    "EvidenceType",
    "RecommendationType",
    "ZoneType",
    "CameraConnectionStatus",
    "CameraRole",
    "CountAggregation",
    "FlowLinkBasis",
    "SiteAlertKind",
    "SiteForecastScope",
    "ComponentType",
    "HealthStatus",
    "EventStatus",
    "AlertPriority",
    "AlertStatus",
    "TimelineEntryType",
    "Severity",
]


class OperationalStatus(StrEnum):
    """Crowd condition, derived from the Crowd Stability Index (``05:622-663``).

    Owns the semantic status palette used throughout the Command Center.
    """

    STABLE = "STABLE"
    OBSERVE = "OBSERVE"
    ATTENTION_REQUIRED = "ATTENTION_REQUIRED"
    HIGH_ALERT = "HIGH_ALERT"
    CRITICAL = "CRITICAL"

    @property
    def severity_rank(self) -> int:
        """Ordinal severity, 0 (Stable) through 4 (Critical).

        Provided so callers can compare statuses without hard-coding an order.
        """
        return _STATUS_RANK[self]


class OperationalState(StrEnum):
    """Operator workflow phase (``10:240-335``).

    Advanced by operator interaction, not by the AI. Rendered in a neutral
    progress palette - never the :class:`OperationalStatus` palette. The source
    document assigns red to ``RECOVERING``, which inverts its own guidance at
    ``10:722``; the neutral palette resolves that (Architecture Review C9).
    """

    MONITORING = "MONITORING"
    OBSERVING = "OBSERVING"
    INVESTIGATING = "INVESTIGATING"
    RESPONDING = "RESPONDING"
    RECOVERING = "RECOVERING"


class SourceMode(StrEnum):
    """Origin of the frames being processed.

    Carried through the pipeline as a **tag only**. The AI Pipeline must never
    branch on this value; it exists so that operational records generated from
    demonstration footage remain separable from live records (Rule 7,
    ``15:121-125``) and so the Command Center can display an unambiguous
    Live/Demo indicator (``11:633-646``).
    """

    LIVE = "LIVE"
    DEMO = "DEMO"


class CountMethod(StrEnum):
    """How a crowd count was obtained.

    The prototype uses detection-plus-tracking below a density threshold and an
    explicitly-labelled estimate above it, because per-person tracking does not
    survive extreme density (Architecture Review C11). The method is reported so
    the Command Center never presents an estimate as a tracked count.
    """

    TRACKED = "TRACKED"
    ESTIMATED = "ESTIMATED"


class QueueFormation(StrEnum):
    """How the people in a queue zone are arranged.

    The distinction Problem Statement 9 asks for - "is this a queue or just a
    crowd?" - is made from measurable spatial structure (linearity, spacing
    regularity, heading coherence, dwell), never from semantic understanding the
    detector cannot provide. Each classification therefore travels with a
    confidence, and :attr:`UNDETERMINED` exists so the platform can decline to
    answer rather than guess (Rule 8).
    """

    QUEUE = "QUEUE"
    """People are linearly arranged and oriented toward a service point."""

    GENERAL_CROWD = "GENERAL_CROWD"
    """People are present but not queued - scattered, milling, or passing through."""

    SPARSE = "SPARSE"
    """Too few people present for any arrangement to be meaningful."""

    UNDETERMINED = "UNDETERMINED"
    """Structure measurable but inconclusive, or tracking too unstable to trust.

    Reported rather than resolved. A queue length the platform is not confident
    in is worse than an admission that it cannot tell.
    """


class RateSource(StrEnum):
    """Where a service-rate figure came from.

    Displayed alongside every waiting-time estimate, because a wait computed
    from a measured rate and one computed from an operator's typed-in assumption
    deserve different amounts of trust and must not look identical on screen.
    """

    MEASURED = "MEASURED"
    """Counted from observed departures through the service end of the queue."""

    CONFIGURED = "CONFIGURED"
    """Supplied by the operator. Used until enough departures are observed."""

    BLENDED = "BLENDED"
    """Measured rate blended toward the configured rate on a short sample."""


class ForecastMethod(StrEnum):
    """Which model produced a forecast.

    Both methods run on every window and both are reported. They rest on
    different assumptions - one extrapolates the observed trend, the other
    projects the arrival/service balance forward - so when they disagree, that
    disagreement is a genuine signal about how well-understood the situation is,
    and the interface shows it rather than averaging it away.
    """

    TREND = "TREND"
    """Holt's linear trend over observed queue length."""

    FLOW_BALANCE = "FLOW_BALANCE"
    """Integration of (arrival rate - effective service rate)."""

    CONSENSUS = "CONSENSUS"
    """Confidence-weighted combination of the two, reported as the headline."""


class GrowthPattern(StrEnum):
    """The shape of recent change in a queue, against its own baseline.

    Keyed to *rate* rather than size, per Problem Statement 9: a large stable
    queue is normal and must stay quiet, while a small queue growing far faster
    than it historically does is the warning worth raising.
    """

    STABLE = "STABLE"
    SHRINKING = "SHRINKING"
    GROWING = "GROWING"
    ABNORMAL_GROWTH = "ABNORMAL_GROWTH"
    """Growth rate exceeds the established baseline by a statistically
    significant margin. This is the Problem Statement 9 abnormal-growth alarm."""

    INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"
    """Not enough observations yet to know what normal looks like."""


class StabilityIndicator(StrEnum):
    """The measurable indicators contributing to the Crowd Stability Index.

    Specified and frozen in ``02_Hackathon_Execution_Plan.md`` section 4.
    Each contributes an instability *pressure* in the range 0-100.
    """

    DENSITY_PRESSURE = "DENSITY_PRESSURE"
    MOTION_SUPPRESSION = "MOTION_SUPPRESSION"
    EGRESS_CONGESTION = "EGRESS_CONGESTION"
    FLOW_CONFLICT = "FLOW_CONFLICT"
    RATE_OF_CHANGE = "RATE_OF_CHANGE"


class ConfidenceFactor(StrEnum):
    """Data-quality factors composing Decision Confidence.

    Decision Confidence is the product of these factors. Defining it in terms of
    measurable data quality is what keeps it from being a fabricated number
    (Architecture Review C5, and ``05:250-254`` on communicating uncertainty).
    """

    DETECTION_QUALITY = "DETECTION_QUALITY"
    TRACK_STABILITY = "TRACK_STABILITY"
    TEMPORAL_SUFFICIENCY = "TEMPORAL_SUFFICIENCY"


class EvidenceType(StrEnum):
    """What the platform is currently observing (``17_Evidence_Engine_Specification.md``).

    Evidence is the *explanation* layer: it says what is happening and why the
    Crowd Stability Index reads as it does, without recommending anything. That
    boundary is the Evidence Engine's whole purpose - recommendations belong to
    the Operational Decision Engine, one stage later.

    Every member here is backed by a measurement the platform actually takes.
    The source document's remaining examples - queue detection, running
    detection, bidirectional conflict - are listed there under *Future
    Expansion* and are deliberately absent: an observation the platform cannot
    measure would be a fabricated explanation, which Rule 8 (``15:129-133``)
    forbids more strongly than it forbids a missing one.
    """

    # -- Occupancy and density ---------------------------------------------
    CONGESTION_FORMING = "CONGESTION_FORMING"
    OCCUPANCY_INCREASING = "OCCUPANCY_INCREASING"
    CROWD_DISPERSING = "CROWD_DISPERSING"

    # -- Movement -----------------------------------------------------------
    MOVEMENT_SLOWING = "MOVEMENT_SLOWING"
    STATIONARY_CLUSTER = "STATIONARY_CLUSTER"

    # -- Flow ---------------------------------------------------------------
    FLOW_CONFLICT = "FLOW_CONFLICT"

    # -- Egress -------------------------------------------------------------
    EGRESS_CONGESTION = "EGRESS_CONGESTION"

    # -- Baseline -----------------------------------------------------------
    CONDITIONS_NOMINAL = "CONDITIONS_NOMINAL"
    """No abnormal behaviour observed.

    Present so that a calm scene produces a positive statement rather than an
    empty panel. "Nothing is wrong" and "the platform has nothing to say" look
    identical on an empty display, and only one of them is reassuring.
    """


class RecommendationType(StrEnum):
    """Kinds of operational guidance the platform may offer (``18:125-143``).

    A **closed** vocabulary, and deliberately so. The Operational Decision
    Engine selects from this list; it never composes an action of its own. An
    engine free to invent an action is an engine that can recommend something
    the venue cannot do, cannot staff, or must not attempt - and no operator can
    audit a recommendation drawn from an open set.

    Ordered from least to most interventionist, which is also the order in which
    a decision rule escalates. :attr:`escalation_rank` exposes that ordering so
    callers compare intent rather than hard-coding a list.
    """

    OBSERVE = "OBSERVE"
    """Continue normal monitoring. The correct answer for a calm crowd."""

    INCREASE_MONITORING = "INCREASE_MONITORING"

    CLOSE_COUNTER = "CLOSE_COUNTER"
    """Release a service counter whose capacity is not being used.

    Ranked below every escalating action because it is the one recommendation
    that *reduces* committed resource. Surfaced for the same reason the others
    are: an operator holding four counters open for a queue two can serve is
    spending staff they will want back when demand returns.
    """

    OPEN_COUNTER = "OPEN_COUNTER"
    """Bring an idle service counter into service.

    The primary lever on waiting time: it raises effective service rate, which
    is the denominator of every wait estimate the platform produces.
    """

    DEPLOY_PERSONNEL = "DEPLOY_PERSONNEL"
    OPEN_ENTRY = "OPEN_ENTRY"
    OPEN_EXIT = "OPEN_EXIT"
    REDIRECT_CROWD = "REDIRECT_CROWD"
    BROADCAST_GUIDANCE = "BROADCAST_GUIDANCE"
    ESCALATE_TO_CONTROL_ROOM = "ESCALATE_TO_CONTROL_ROOM"
    EMERGENCY_RESPONSE = "EMERGENCY_RESPONSE"

    @property
    def escalation_rank(self) -> int:
        """How interventionist this recommendation is, 0 through 10."""
        return _RECOMMENDATION_RANK[self]


class ZoneType(StrEnum):
    """Semantic role of a camera zone.

    Zones make egress congestion measurable at all, and let recommendations name
    a real location rather than an invented one (Architecture Review C26).
    """

    ENTRY = "ENTRY"
    EXIT = "EXIT"
    PLATFORM = "PLATFORM"
    CONCOURSE = "CONCOURSE"
    STAIRWELL = "STAIRWELL"

    QUEUE = "QUEUE"
    """A region where people wait their turn for service.

    Queue Intelligence measures arrival and departure rates from crossings of
    this boundary, so a configured QUEUE zone is what makes queue length,
    waiting time and service rate measurable rather than inferred.
    """

    COUNTER = "COUNTER"
    """A service point a queue is served by - a ticket window, billing desk,
    registration counter.

    Its position gives the queue an orientation: the end of the line nearest a
    COUNTER zone is the *service end*, which is how a departure through service
    is distinguished from someone abandoning the queue and walking away.
    """


# ---------------------------------------------------------------------------
# Multi-camera
# ---------------------------------------------------------------------------


class CameraConnectionStatus(StrEnum):
    """Whether a camera is currently delivering frames the platform can analyse.

    Distinct from :class:`HealthStatus`, which summarises a whole component for
    the System Health panel. A site with several cameras needs to say *which*
    camera is in which condition, and the conditions call for different
    operator responses: a camera still connecting is not a camera that failed,
    and neither is one an operator switched off.

    **A camera that is not contributing is never reported as zero people.** Its
    figures are withheld and the site-level view says it is degraded - a
    missing measurement and an empty room are opposite facts.
    """

    CONNECTING = "CONNECTING"
    """Loading the model or opening the stream for the first time."""

    ONLINE = "ONLINE"
    """Frames arriving and being analysed within budget."""

    DEGRADED = "DEGRADED"
    """Frames arriving, but late, slow or failing some stage."""

    RECOVERING = "RECOVERING"
    """The stream was lost and reconnection is being attempted."""

    OFFLINE = "OFFLINE"
    """No frames, and no recovery in progress - failed or never configured."""

    DISABLED = "DISABLED"
    """Switched off by an operator. Deliberate, not a fault."""

    @property
    def is_contributing(self) -> bool:
        """Whether this camera's latest measurements may enter site figures."""
        return self in (CameraConnectionStatus.ONLINE, CameraConnectionStatus.DEGRADED)


class CameraRole(StrEnum):
    """What a camera is primarily pointed at, in operational terms.

    A description of the camera's placement, not a measurement: it orders the
    crowd flow map and labels camera tiles. What a camera actually measures is
    still decided by its zones.
    """

    GENERAL = "GENERAL"
    ENTRANCE = "ENTRANCE"
    WAITING_AREA = "WAITING_AREA"
    QUEUE = "QUEUE"
    SERVICE = "SERVICE"
    EXIT = "EXIT"


class CountAggregation(StrEnum):
    """How per-camera headcounts were combined into a site figure.

    Cameras whose views may overlap cannot simply be added: one person seen by
    two cameras is still one person. The method is reported beside every
    combined figure so a sum is never presented as a count of unique people
    when it might not be one.
    """

    INDEPENDENT_SUM = "INDEPENDENT_SUM"
    """Every contributing camera covers a distinct area, so counts add."""

    OVERLAP_ADJUSTED = "OVERLAP_ADJUSTED"
    """At least two cameras share a coverage area. Within a shared area the
    largest single-camera count is used - the most any one view proves - and
    the plain sum is reported as the upper bound."""

    NO_DATA = "NO_DATA"
    """No camera is contributing, so there is no figure at all."""


class FlowLinkBasis(StrEnum):
    """What a movement figure between two zones actually rests on.

    The platform does not re-identify people across cameras. Movement between
    zones on the *same* camera is counted from track identities; movement
    between zones on *different* cameras can only be shown as two independently
    measured rates side by side. The two are labelled differently everywhere
    so a correlation is never read as a tracked count.
    """

    TRACKED = "TRACKED"
    """Same camera: tracks observed leaving one zone and entering the other."""

    CORRELATED = "CORRELATED"
    """Different cameras: exit and entry rates compared, identities unknown."""

    UNAVAILABLE = "UNAVAILABLE"
    """Not measurable right now - a camera is offline or a zone is missing."""


class SiteAlertKind(StrEnum):
    """Site-level conditions the platform raises for an operator.

    Every alert of every kind carries its evidence - the measurements that
    raised it - so "why is the system alerting?" always has an answer.
    """

    ABNORMAL_GROWTH = "ABNORMAL_GROWTH"
    CAPACITY_PRESSURE = "CAPACITY_PRESSURE"
    HOTSPOT = "HOTSPOT"
    CAMERA_OFFLINE = "CAMERA_OFFLINE"
    DEGRADED_COVERAGE = "DEGRADED_COVERAGE"


class SiteForecastScope(StrEnum):
    """Which site-level quantity a forecast projects."""

    DEMAND = "DEMAND"
    """People observed across the whole site."""

    QUEUE = "QUEUE"
    """People waiting across every queue zone on every camera."""


class ComponentType(StrEnum):
    """Platform components reported by the System Health panel (``06:872-896``)."""

    CAMERA = "CAMERA"
    AI_PIPELINE = "AI_PIPELINE"
    BACKEND = "BACKEND"
    DATABASE = "DATABASE"
    NETWORK = "NETWORK"


class HealthStatus(StrEnum):
    """Health of a single platform component (``06:890-896``)."""

    HEALTHY = "HEALTHY"
    WARNING = "WARNING"
    OFFLINE = "OFFLINE"


class EventStatus(StrEnum):
    """Lifecycle state of a Crowd Event episode.

    A Crowd Event is an *episode* with a lifecycle, not a per-frame record
    (Architecture Review C3). It opens on sustained instability and closes on
    operator action (``10:329``).
    """

    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


class AlertPriority(StrEnum):
    """Operational priority, derived from Operational Status.

    Used for both Operational Alerts and the Operational Decision Engine's own
    guidance. One priority vocabulary rather than two: an alert and the
    recommendation that accompanies it describe the urgency of the same
    situation, and giving them separate scales would invite them to disagree
    on screen (Rule 3).
    """

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"

    @property
    def rank(self) -> int:
        """Ordinal urgency, 0 (Low) through 3 (Critical)."""
        return _PRIORITY_RANK[self]

    @classmethod
    def from_rank(cls, rank: int) -> AlertPriority:
        """The priority at an ordinal, clamped into range."""
        ordered = (cls.LOW, cls.MEDIUM, cls.HIGH, cls.CRITICAL)
        return ordered[min(max(rank, 0), len(ordered) - 1)]


class AlertStatus(StrEnum):
    """Lifecycle state of an Operational Alert."""

    NEW = "NEW"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESOLVED = "RESOLVED"


class TimelineEntryType(StrEnum):
    """Category of a Crowd Event Timeline entry (``06:846-868``)."""

    AI_OBSERVATION = "AI_OBSERVATION"
    STATUS_CHANGE = "STATUS_CHANGE"
    ALERT = "ALERT"
    OPERATOR_ACTION = "OPERATOR_ACTION"
    SYSTEM = "SYSTEM"


class Severity(StrEnum):
    """Display severity for timeline entries and system messages."""

    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


# ---------------------------------------------------------------------------
# Crowd Stability Index bands
# ---------------------------------------------------------------------------
#
# These are *specification data*, not a calculation. They are declared once,
# here, so that the AI Pipeline, the backend and the frontend cannot drift
# apart on where a band boundary lies (Rule 4 and Rule 9 - no duplicated logic).
#
# Five even 20-point bands using the OperationalStatus vocabulary verbatim,
# resolving the naming mismatch between 05:106-128 and 05:622-663
# (Architecture Review C10). Frozen in 02_Hackathon_Execution_Plan.md section 4.

CSI_MIN: float = 0.0
CSI_MAX: float = 100.0

#: Inclusive lower bound of each band, ordered from most to least severe.
CSI_BANDS: tuple[tuple[float, OperationalStatus], ...] = (
    (80.0, OperationalStatus.STABLE),
    (60.0, OperationalStatus.OBSERVE),
    (40.0, OperationalStatus.ATTENTION_REQUIRED),
    (20.0, OperationalStatus.HIGH_ALERT),
    (0.0, OperationalStatus.CRITICAL),
)

_PRIORITY_RANK: dict[AlertPriority, int] = {
    AlertPriority.LOW: 0,
    AlertPriority.MEDIUM: 1,
    AlertPriority.HIGH: 2,
    AlertPriority.CRITICAL: 3,
}

_RECOMMENDATION_RANK: dict[RecommendationType, int] = {
    RecommendationType.OBSERVE: 0,
    RecommendationType.INCREASE_MONITORING: 1,
    RecommendationType.CLOSE_COUNTER: 2,
    RecommendationType.OPEN_COUNTER: 3,
    RecommendationType.DEPLOY_PERSONNEL: 4,
    RecommendationType.OPEN_ENTRY: 5,
    RecommendationType.OPEN_EXIT: 6,
    RecommendationType.REDIRECT_CROWD: 7,
    RecommendationType.BROADCAST_GUIDANCE: 8,
    RecommendationType.ESCALATE_TO_CONTROL_ROOM: 9,
    RecommendationType.EMERGENCY_RESPONSE: 10,
}

_STATUS_RANK: dict[OperationalStatus, int] = {
    OperationalStatus.STABLE: 0,
    OperationalStatus.OBSERVE: 1,
    OperationalStatus.ATTENTION_REQUIRED: 2,
    OperationalStatus.HIGH_ALERT: 3,
    OperationalStatus.CRITICAL: 4,
}


def status_for_csi(csi: float) -> OperationalStatus:
    """Return the Operational Status for a Crowd Stability Index value.

    This is a lookup against the frozen band table above - it performs no part
    of the CSI computation itself. It exists so that exactly one definition of
    the band boundaries exists in the codebase.

    Args:
        csi: Crowd Stability Index, expected in ``[0, 100]``. Values outside
            that range are clamped rather than rejected, so that a display can
            never be left without a status.

    Returns:
        The Operational Status for ``csi``.
    """
    clamped = min(max(csi, CSI_MIN), CSI_MAX)
    for lower_bound, status in CSI_BANDS:
        if clamped >= lower_bound:
            return status
    return OperationalStatus.CRITICAL  # pragma: no cover - unreachable
