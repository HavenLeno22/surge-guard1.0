"""SurgeGuard data contracts.

The structured data that crosses module and process boundaries (``04:511``,
``07:444``). This subpackage is the **single source of truth** for the shape of
every value in the platform: the backend imports these models directly, and the
frontend's TypeScript types mirror them.

Two properties are maintained deliberately:

1. **Dependency-free leaf.** ``contracts`` imports nothing else from
   ``surgeguard_ai``. This is what makes it safe for the backend to depend on
   the AI package without inheriting OpenCV or model runtimes.
2. **Serializable only.** Anything carrying a raw image buffer is *not* a
   contract. :class:`~surgeguard_ai.perception.frame_source.Frame` lives in
   ``perception`` because it never crosses a process boundary.
"""

from __future__ import annotations

from .analysis import AnalysisResult
from .base import Contract
from .camera import CameraCalibration, CameraConfig, CameraZone
from .crowd import CrowdMetrics, DensityCell, DensityMap, FlowMetrics, ZoneOccupancy
from .enums import (
    CSI_BANDS,
    CSI_MAX,
    CSI_MIN,
    AlertPriority,
    AlertStatus,
    CameraConnectionStatus,
    CameraRole,
    ComponentType,
    ConfidenceFactor,
    CountAggregation,
    CountMethod,
    EventStatus,
    EvidenceType,
    FlowLinkBasis,
    ForecastMethod,
    GrowthPattern,
    HealthStatus,
    OperationalState,
    OperationalStatus,
    QueueFormation,
    RateSource,
    RecommendationType,
    Severity,
    SiteAlertKind,
    SiteForecastScope,
    SourceMode,
    StabilityIndicator,
    TimelineEntryType,
    ZoneType,
    status_for_csi,
)
from .evidence import EvidenceItem, EvidenceReport, SupportingMetric
from .forecast import (
    ForecastPoint,
    ForecastReport,
    GrowthAssessment,
    MethodForecast,
    QueueForecast,
)
from .geometry import BoundingBox, GroundPoint, ImagePoint, ImagePolygon, Vector2D
from .intelligence import (
    OperationalIntelligenceReport,
    PrimaryCause,
    RecommendedAction,
)
from .perception import (
    Detection,
    DetectionResult,
    PerceptionResult,
    Track,
    TrackingResult,
)
from .queue import (  # noqa: I001 - queue depends on nothing here; order is cosmetic
    FlowRates,
    QueueGeometry,
    QueueMetrics,
    QueueReport,
    ServiceCapacity,
    WaitEstimate,
)
from .resources import (
    CapacityOption,
    ResourcePlan,
    ResourcePlanReport,
)
from .site import (  # noqa: I001 - site depends on forecast and resources above
    CoverageAreaCount,
    FlowLinkConfig,
    Hotspot,
    HotspotFactor,
    QueueZoneRef,
    SiteAlert,
    SiteCamera,
    SiteCameraSummary,
    SiteFlowNode,
    SiteForecast,
    SiteHeadcount,
    SiteQueueSummary,
    SiteReport,
    SiteTopology,
    TimeToPressure,
    ZoneFlowLink,
)
from .stability import (
    ConfidenceReading,
    DecisionConfidence,
    IndicatorBreakdown,
    IndicatorReading,
    PerceptionQuality,
    StabilityAssessment,
)
from .zones import ZoneFlowReport, ZoneFlowSnapshot, ZoneTransition

__all__ = [
    # Base
    "Contract",
    # Enumerations
    "AlertPriority",
    "AlertStatus",
    "ComponentType",
    "ConfidenceFactor",
    "CountMethod",
    "ForecastMethod",
    "GrowthPattern",
    "QueueFormation",
    "RateSource",
    "EventStatus",
    "EvidenceType",
    "HealthStatus",
    "OperationalState",
    "OperationalStatus",
    "RecommendationType",
    "Severity",
    "SourceMode",
    "StabilityIndicator",
    "TimelineEntryType",
    "ZoneType",
    # Multi-camera
    "CameraConnectionStatus",
    "CameraRole",
    "CountAggregation",
    "FlowLinkBasis",
    "SiteAlertKind",
    "SiteForecastScope",
    # CSI band specification
    "CSI_BANDS",
    "CSI_MAX",
    "CSI_MIN",
    "status_for_csi",
    # Geometry
    "BoundingBox",
    "GroundPoint",
    "ImagePoint",
    "ImagePolygon",
    "Vector2D",
    # Camera configuration
    "CameraCalibration",
    "CameraConfig",
    "CameraZone",
    # Perception
    "Detection",
    "DetectionResult",
    "PerceptionResult",
    "Track",
    "TrackingResult",
    # Queue Intelligence - measured queue state
    "FlowRates",
    "QueueGeometry",
    "QueueMetrics",
    "QueueReport",
    "ServiceCapacity",
    "WaitEstimate",
    # Forecasting - what is expected to happen next
    "ForecastPoint",
    "ForecastReport",
    "GrowthAssessment",
    "MethodForecast",
    "QueueForecast",
    # Resource allocation - what could be done about capacity
    "CapacityOption",
    "ResourcePlan",
    "ResourcePlanReport",
    # Crowd analysis
    "CrowdMetrics",
    "DensityCell",
    "DensityMap",
    "FlowMetrics",
    "ZoneOccupancy",
    # Stability
    "ConfidenceReading",
    "DecisionConfidence",
    "IndicatorBreakdown",
    "IndicatorReading",
    "PerceptionQuality",
    "StabilityAssessment",
    # Evidence
    "EvidenceItem",
    "EvidenceReport",
    "SupportingMetric",
    # Decision intelligence
    "OperationalIntelligenceReport",
    "PrimaryCause",
    "RecommendedAction",
    # Zone flow - movement within one camera
    "ZoneFlowReport",
    "ZoneFlowSnapshot",
    "ZoneTransition",
    # Site intelligence - every camera at once
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
    # Result
    "AnalysisResult",
]
