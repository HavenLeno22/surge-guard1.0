/**
 * Operator-facing names for every value the backend sends.
 *
 * Wording follows the backend's own vocabulary (Rule 3): the cause labels match
 * `intelligence/decision_engine.py`, status names match `decision_service.py`,
 * and SurgeGuard terms are never paraphrased.
 */

import type {
  AlertPriority,
  CameraConnectionStatus,
  CameraRole,
  ComponentType,
  ConfidenceFactor,
  CountAggregation,
  CountMethod,
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
  StabilityIndicator,
  StreamLayer,
  StreamOutcome,
  TimelineEntryType,
  WorkerState,
  ZoneType,
} from "@/types/contracts";

export const STATUS_LABEL: Record<OperationalStatus, string> = {
  STABLE: "Stable",
  OBSERVE: "Observe",
  ATTENTION_REQUIRED: "Attention Required",
  HIGH_ALERT: "High Alert",
  CRITICAL: "Critical",
};

export const STATE_LABEL: Record<OperationalState, string> = {
  MONITORING: "Monitoring",
  OBSERVING: "Observing",
  INVESTIGATING: "Investigating",
  RESPONDING: "Responding",
  RECOVERING: "Recovering",
};

export const STATE_DESCRIPTION: Record<OperationalState, string> = {
  MONITORING: "Conditions are stable. The platform is watching.",
  OBSERVING: "Conditions have left Stable. Nobody has acknowledged it yet.",
  INVESTIGATING: "An operator has acknowledged the situation and is looking into it.",
  RESPONDING: "An operator has logged action on the situation.",
  RECOVERING: "Conditions returned to Stable. The platform is confirming the recovery holds.",
};

/** The order the Operational State strip draws its steps in. */
export const STATE_ORDER: OperationalState[] = [
  "MONITORING",
  "OBSERVING",
  "INVESTIGATING",
  "RESPONDING",
  "RECOVERING",
];

export const INDICATOR_LABEL: Record<StabilityIndicator, string> = {
  DENSITY_PRESSURE: "Crowd density",
  MOTION_SUPPRESSION: "Movement suppression",
  EGRESS_CONGESTION: "Exit congestion",
  FLOW_CONFLICT: "Opposing flow",
  RATE_OF_CHANGE: "Rate of change",
};

export const INDICATOR_DESCRIPTION: Record<StabilityIndicator, string> = {
  DENSITY_PRESSURE: "How compressed the most crowded part of the view is.",
  MOTION_SUPPRESSION: "How far movement has fallen below this camera's own normal.",
  EGRESS_CONGESTION: "How full the exits are against their clear width.",
  FLOW_CONFLICT: "How much of the crowd is moving against the majority.",
  RATE_OF_CHANGE: "How fast conditions are worsening.",
};

/** Default weights from `core/config.py` (SURGEGUARD_CSI_WEIGHT_*). */
export const INDICATOR_DEFAULT_WEIGHT: Record<StabilityIndicator, number> = {
  DENSITY_PRESSURE: 0.35,
  MOTION_SUPPRESSION: 0.2,
  EGRESS_CONGESTION: 0.2,
  FLOW_CONFLICT: 0.15,
  RATE_OF_CHANGE: 0.1,
};

export const INDICATOR_ORDER: StabilityIndicator[] = [
  "DENSITY_PRESSURE",
  "MOTION_SUPPRESSION",
  "EGRESS_CONGESTION",
  "FLOW_CONFLICT",
  "RATE_OF_CHANGE",
];

export const CONFIDENCE_FACTOR_LABEL: Record<ConfidenceFactor, string> = {
  DETECTION_QUALITY: "Detection quality",
  TRACK_STABILITY: "Track stability",
  TEMPORAL_SUFFICIENCY: "Observation time",
};

export const EVIDENCE_TYPE_LABEL: Record<EvidenceType, string> = {
  CONGESTION_FORMING: "Congestion forming",
  OCCUPANCY_INCREASING: "Occupancy increasing",
  CROWD_DISPERSING: "Crowd dispersing",
  MOVEMENT_SLOWING: "Movement slowing",
  STATIONARY_CLUSTER: "Stationary cluster",
  FLOW_CONFLICT: "Opposing flow",
  EGRESS_CONGESTION: "Exit congestion",
  CONDITIONS_NOMINAL: "Conditions nominal",
};

export const RECOMMENDATION_LABEL: Record<RecommendationType, string> = {
  OBSERVE: "Observe",
  INCREASE_MONITORING: "Increase monitoring",
  CLOSE_COUNTER: "Close a counter",
  OPEN_COUNTER: "Open a counter",
  DEPLOY_PERSONNEL: "Deploy personnel",
  OPEN_ENTRY: "Open entry",
  OPEN_EXIT: "Open exit",
  REDIRECT_CROWD: "Redirect crowd",
  BROADCAST_GUIDANCE: "Broadcast guidance",
  ESCALATE_TO_CONTROL_ROOM: "Escalate",
  EMERGENCY_RESPONSE: "Emergency response",
};

export const PRIORITY_LABEL: Record<AlertPriority, string> = {
  LOW: "Low",
  MEDIUM: "Medium",
  HIGH: "High",
  CRITICAL: "Critical",
};

export const SEVERITY_LABEL: Record<Severity, string> = {
  INFO: "Info",
  WARNING: "Warning",
  CRITICAL: "Critical",
};

export const CAMERA_STATUS_LABEL: Record<CameraConnectionStatus, string> = {
  CONNECTING: "Connecting",
  ONLINE: "Online",
  DEGRADED: "Degraded",
  RECOVERING: "Reconnecting",
  OFFLINE: "Offline",
  DISABLED: "Disabled",
};

export const CAMERA_ROLE_LABEL: Record<CameraRole, string> = {
  GENERAL: "General",
  ENTRANCE: "Entrance",
  WAITING_AREA: "Waiting area",
  QUEUE: "Queue",
  SERVICE: "Service",
  EXIT: "Exit",
};

export const HEALTH_LABEL: Record<HealthStatus, string> = {
  HEALTHY: "Healthy",
  WARNING: "Warning",
  OFFLINE: "Offline",
};

export const COMPONENT_LABEL: Record<ComponentType, string> = {
  CAMERA: "Cameras",
  AI_PIPELINE: "AI pipeline",
  BACKEND: "Backend",
  DATABASE: "Database",
  NETWORK: "Network",
};

export const ZONE_TYPE_LABEL: Record<ZoneType, string> = {
  ENTRY: "Entry",
  EXIT: "Exit",
  PLATFORM: "Platform",
  CONCOURSE: "Concourse",
  STAIRWELL: "Stairwell",
  QUEUE: "Queue",
  COUNTER: "Counter",
};

export const FORMATION_LABEL: Record<QueueFormation, string> = {
  QUEUE: "Queue",
  GENERAL_CROWD: "General crowd",
  SPARSE: "Sparse",
  UNDETERMINED: "Undetermined",
};

export const RATE_SOURCE_LABEL: Record<RateSource, string> = {
  MEASURED: "Measured",
  CONFIGURED: "Assumed",
  BLENDED: "Blended",
};

export const RATE_SOURCE_DESCRIPTION: Record<RateSource, string> = {
  MEASURED: "Counted from observed departures.",
  CONFIGURED: "An operator-supplied assumption, used until enough departures are observed.",
  BLENDED: "A short measured sample blended toward the operator's assumption.",
};

export const FORECAST_METHOD_LABEL: Record<ForecastMethod, string> = {
  TREND: "Trend",
  FLOW_BALANCE: "Flow balance",
  CONSENSUS: "Consensus",
};

export const GROWTH_LABEL: Record<GrowthPattern, string> = {
  STABLE: "Steady",
  SHRINKING: "Shrinking",
  GROWING: "Growing",
  ABNORMAL_GROWTH: "Abnormal growth",
  INSUFFICIENT_HISTORY: "Learning baseline",
};

export const ALERT_KIND_LABEL: Record<SiteAlertKind, string> = {
  ABNORMAL_GROWTH: "Abnormal growth",
  CAPACITY_PRESSURE: "Capacity pressure",
  HOTSPOT: "Hotspot",
  CAMERA_OFFLINE: "Camera offline",
  DEGRADED_COVERAGE: "Degraded coverage",
};

export const AGGREGATION_LABEL: Record<CountAggregation, string> = {
  INDEPENDENT_SUM: "Sum of independent views",
  OVERLAP_ADJUSTED: "Overlap-adjusted",
  NO_DATA: "No data",
};

export const FLOW_BASIS_LABEL: Record<FlowLinkBasis, string> = {
  TRACKED: "Tracked",
  CORRELATED: "Correlated",
  UNAVAILABLE: "Unavailable",
};

export const TIMELINE_TYPE_LABEL: Record<TimelineEntryType, string> = {
  AI_OBSERVATION: "Observation",
  STATUS_CHANGE: "Status change",
  ALERT: "Alert",
  OPERATOR_ACTION: "Operator action",
  SYSTEM: "System",
};

export const WORKER_STATE_LABEL: Record<WorkerState, string> = {
  disabled: "Disabled",
  stopped: "Stopped",
  starting: "Starting",
  running: "Running",
  recovering: "Recovering",
  completed: "Completed",
  failed: "Failed",
};

export const STREAM_OUTCOME_LABEL: Record<StreamOutcome, string> = {
  OK: "Frames received",
  STREAMING: "Streaming",
  BUSY: "Busy with another viewer",
  UNREACHABLE: "Unreachable",
  NOT_A_STREAM: "Not a video stream",
  HTTP_ERROR: "Refused",
  OPEN_FAILED: "Could not be opened",
  NO_FRAMES: "No frames",
  NOT_DIAGNOSABLE: "Not diagnosable",
};

export const LAYER_LABEL: Record<StreamLayer, string> = {
  hud: "Readout",
  tracks: "Tracks",
  trails: "Trails",
  zones: "Zones",
  flow: "Flow",
  heatmap: "Density",
};

export const LAYER_ORDER: StreamLayer[] = ["hud", "tracks", "trails", "zones", "flow", "heatmap"];

export const SITE_TIMELINE_ID = "site";

export function countMethodLabel(method: CountMethod): string {
  return method === "TRACKED" ? "Tracked" : "Estimated";
}

export function sourceModeLabel(mode: string | null | undefined): string {
  if (mode === "DEMO") return "Demonstration";
  if (mode === "LIVE") return "Live";
  return "Unknown source";
}
