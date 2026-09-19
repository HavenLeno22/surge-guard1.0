/**
 * TypeScript mirrors of the SurgeGuard data contracts.
 *
 * Each type follows a Pydantic model in `ai/surgeguard_ai/contracts/` or
 * `backend/app/schemas/` field for field. Timestamps arrive as ISO 8601 strings.
 * Nullable fields are nullable because the backend withholds a figure it did
 * not measure - never replace a null with zero when displaying one.
 */

// ---------------------------------------------------------------------------
// Enumerations (contracts/enums.py)
// ---------------------------------------------------------------------------

/** Crowd condition, derived from the Crowd Stability Index. High CSI = stable. */
export type OperationalStatus =
  | "STABLE"
  | "OBSERVE"
  | "ATTENTION_REQUIRED"
  | "HIGH_ALERT"
  | "CRITICAL";

/** Operator workflow phase. Never rendered in the status palette. */
export type OperationalState =
  | "MONITORING"
  | "OBSERVING"
  | "INVESTIGATING"
  | "RESPONDING"
  | "RECOVERING";

export type SourceMode = "LIVE" | "DEMO";
export type CountMethod = "TRACKED" | "ESTIMATED";
export type QueueFormation = "QUEUE" | "GENERAL_CROWD" | "SPARSE" | "UNDETERMINED";
export type RateSource = "MEASURED" | "CONFIGURED" | "BLENDED";
export type ForecastMethod = "TREND" | "FLOW_BALANCE" | "CONSENSUS";
export type GrowthPattern =
  | "STABLE"
  | "SHRINKING"
  | "GROWING"
  | "ABNORMAL_GROWTH"
  | "INSUFFICIENT_HISTORY";
export type StabilityIndicator =
  | "DENSITY_PRESSURE"
  | "MOTION_SUPPRESSION"
  | "EGRESS_CONGESTION"
  | "FLOW_CONFLICT"
  | "RATE_OF_CHANGE";
export type ConfidenceFactor = "DETECTION_QUALITY" | "TRACK_STABILITY" | "TEMPORAL_SUFFICIENCY";
export type EvidenceType =
  | "CONGESTION_FORMING"
  | "OCCUPANCY_INCREASING"
  | "CROWD_DISPERSING"
  | "MOVEMENT_SLOWING"
  | "STATIONARY_CLUSTER"
  | "FLOW_CONFLICT"
  | "EGRESS_CONGESTION"
  | "CONDITIONS_NOMINAL";
export type RecommendationType =
  | "OBSERVE"
  | "INCREASE_MONITORING"
  | "CLOSE_COUNTER"
  | "OPEN_COUNTER"
  | "DEPLOY_PERSONNEL"
  | "OPEN_ENTRY"
  | "OPEN_EXIT"
  | "REDIRECT_CROWD"
  | "BROADCAST_GUIDANCE"
  | "ESCALATE_TO_CONTROL_ROOM"
  | "EMERGENCY_RESPONSE";
export type ZoneType =
  | "ENTRY"
  | "EXIT"
  | "PLATFORM"
  | "CONCOURSE"
  | "STAIRWELL"
  | "QUEUE"
  | "COUNTER";
export type CameraConnectionStatus =
  | "CONNECTING"
  | "ONLINE"
  | "DEGRADED"
  | "RECOVERING"
  | "OFFLINE"
  | "DISABLED";
export type CameraRole = "GENERAL" | "ENTRANCE" | "WAITING_AREA" | "QUEUE" | "SERVICE" | "EXIT";
export type CountAggregation = "INDEPENDENT_SUM" | "OVERLAP_ADJUSTED" | "NO_DATA";
export type FlowLinkBasis = "TRACKED" | "CORRELATED" | "UNAVAILABLE";
export type SiteAlertKind =
  | "ABNORMAL_GROWTH"
  | "CAPACITY_PRESSURE"
  | "HOTSPOT"
  | "CAMERA_OFFLINE"
  | "DEGRADED_COVERAGE";
export type SiteForecastScope = "DEMAND" | "QUEUE";
export type ComponentType = "CAMERA" | "AI_PIPELINE" | "BACKEND" | "DATABASE" | "NETWORK";
export type HealthStatus = "HEALTHY" | "WARNING" | "OFFLINE";
export type AlertPriority = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
export type TimelineEntryType =
  | "AI_OBSERVATION"
  | "STATUS_CHANGE"
  | "ALERT"
  | "OPERATOR_ACTION"
  | "SYSTEM";
export type Severity = "INFO" | "WARNING" | "CRITICAL";

/** Perception worker state - lowercase on the wire (workers/perception_worker.py). */
export type WorkerState =
  | "disabled"
  | "stopped"
  | "starting"
  | "running"
  | "recovering"
  | "completed"
  | "failed";

export type StreamOutcome =
  | "OK"
  | "STREAMING"
  | "BUSY"
  | "UNREACHABLE"
  | "NOT_A_STREAM"
  | "HTTP_ERROR"
  | "OPEN_FAILED"
  | "NO_FRAMES"
  | "NOT_DIAGNOSABLE";

export type CameraOrigin = "ENVIRONMENT" | "OPERATOR";
export type UrlSource = "ENVIRONMENT" | "REGISTRY" | "UNSET";
export type StreamLayer = "hud" | "tracks" | "trails" | "zones" | "flow" | "heatmap";
export type OperatorAction = "ACKNOWLEDGE" | "LOG_ACTION" | "CLOSE";

// ---------------------------------------------------------------------------
// Geometry and perception
// ---------------------------------------------------------------------------

export interface ImagePoint {
  x: number;
  y: number;
}

export interface BoundingBox {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
}

export interface Detection {
  bbox: BoundingBox;
  confidence: number;
}

export interface Track {
  track_id: number;
  bbox: BoundingBox;
  confidence: number;
  age_frames: number;
  foot_point: ImagePoint;
  ground_point: { x_m: number; y_m: number } | null;
  velocity_image: { dx: number; dy: number } | null;
  velocity_ground: { dx: number; dy: number } | null;
}

export interface PerceptionResult {
  camera_id: string;
  source_mode: SourceMode;
  frame_seq: number;
  frame_ts: string;
  produced_at: string;
  person_count: number;
  detections: {
    frame_seq: number;
    frame_ts: string;
    detections: Detection[];
    inference_ms: number | null;
  };
  tracking: { frame_seq: number; frame_ts: string; tracks: Track[]; id_switches: number };
  inference_ms: number | null;
  processing_ms: number;
  achieved_fps: number;
  degraded: boolean;
  degraded_reason: string | null;
}

export interface DetectionDevice {
  device: string;
  name: string;
  is_cuda: boolean;
  precision: string;
  total_memory_mb: number | null;
  fallback_reason: string | null;
}

export interface PerceptionRead {
  result: PerceptionResult;
  device: DetectionDevice | null;
  received_at: string;
  age_seconds: number;
  is_stale: boolean;
}

export interface PerceptionIngestStatus {
  has_result: boolean;
  is_stale: boolean;
  received: number;
  degraded_received: number;
  first_received_at: string | null;
  last_received_at: string | null;
  age_seconds: number | null;
}

// ---------------------------------------------------------------------------
// Stability and evidence
// ---------------------------------------------------------------------------

export interface IndicatorReading {
  indicator: StabilityIndicator;
  available: boolean;
  raw_value: number | null;
  pressure: number | null;
  weight: number;
  unavailable_reason: string | null;
}

export interface ConfidenceReading {
  factor: ConfidenceFactor;
  value: number;
  detail: string | null;
}

export interface DecisionConfidence {
  value: number;
  factors: ConfidenceReading[];
  limiting_factor: ConfidenceFactor | null;
}

export interface StabilityAssessment {
  frame_seq: number;
  frame_ts: string;
  csi_raw: number;
  csi_smoothed: number;
  status: OperationalStatus;
  status_changed: boolean;
  breakdown: { readings: IndicatorReading[] };
  confidence: DecisionConfidence;
}

export interface SupportingMetric {
  label: string;
  value: number;
  unit: string;
  baseline: number | null;
}

export interface EvidenceItem {
  evidence_type: EvidenceType;
  severity: Severity;
  confidence: number;
  headline: string;
  detail: string;
  metrics: SupportingMetric[];
  observed_at: string;
  frame_seq: number;
  zone_id: string | null;
  indicator: StabilityIndicator | null;
}

export interface EvidenceReport {
  frame_seq: number;
  frame_ts: string;
  generated_at: string;
  items: EvidenceItem[];
  suppressed: number;
}

export interface CrowdSummary {
  person_count: number;
  count_method: CountMethod;
  density_max: number;
  density_mean: number;
  is_metric: boolean;
  median_speed: number | null;
  baseline_speed: number | null;
}

export interface CrowdIntelligenceRead {
  camera_id: string;
  source_mode: SourceMode;
  frame_seq: number;
  stability: StabilityAssessment;
  evidence: EvidenceReport | null;
  crowd: CrowdSummary;
  received_at: string;
  age_seconds: number;
  is_stale: boolean;
  degraded: boolean;
  degraded_reason: string | null;
}

export interface EvidenceHistoryRead {
  items: EvidenceItem[];
  total: number;
  analysed: number;
}

// ---------------------------------------------------------------------------
// Operational Intelligence Report
// ---------------------------------------------------------------------------

export interface PrimaryCause {
  indicator: StabilityIndicator;
  label: string;
  contribution_pct: number;
  pressure: number;
  detail: string | null;
}

export interface RecommendedAction {
  priority: number;
  recommendation_type: RecommendationType;
  action: string;
  rationale: string;
  supporting_indicators: StabilityIndicator[];
  confidence: number;
  urgency: AlertPriority;
  zone_id: string | null;
  rule_id: string;
}

export interface OperationalIntelligenceReport {
  sequence: number;
  revision: number;
  generated_at: string;
  frame_seq: number;
  status: OperationalStatus;
  priority: AlertPriority;
  csi: number;
  confidence: number;
  situation_summary: string;
  primary_causes: PrimaryCause[];
  supporting_evidence: EvidenceItem[];
  dominant_contributor_statement: string | null;
  recommended_actions: RecommendedAction[];
  suppressed_actions: number;
}

export interface DecisionRead {
  report: OperationalIntelligenceReport;
  operational_state: OperationalState;
  received_at: string;
  age_seconds: number;
  is_stale: boolean;
}

export interface CameraDecision {
  camera_id: string;
  report: OperationalIntelligenceReport | null;
  operational_state: OperationalState;
  received_at: string | null;
  age_seconds: number | null;
  is_stale: boolean;
}

// ---------------------------------------------------------------------------
// Queue Intelligence, forecasts, resources
// ---------------------------------------------------------------------------

export interface QueueGeometry {
  sample_size: number;
  linearity: number | null;
  spacing_regularity: number | null;
  heading_coherence: number | null;
  counter_alignment: number | null;
  mean_spacing_px: number | null;
  mean_spacing_m: number | null;
  major_axis_deg: number | null;
}

export interface FlowRates {
  window_seconds: number;
  arrivals: number;
  departures_served: number;
  departures_abandoned: number;
  arrival_rate_per_min: number;
  service_rate_per_min: number;
  abandonment_rate_per_min: number;
  rate_source: RateSource;
  observation_seconds: number;
}

export interface ServiceCapacity {
  total_counters: number;
  active_counters: number;
  service_rate_per_counter_per_min: number;
  rate_source: RateSource;
}

export interface WaitEstimate {
  minutes: number | null;
  queue_length: number;
  effective_service_rate_per_min: number;
  rate_source: RateSource;
  assumptions: string[];
  confidence: number;
}

export interface QueueMetrics {
  zone_id: string;
  zone_name: string;
  frame_seq: number;
  frame_ts: string;
  person_count: number;
  formation: QueueFormation;
  formation_confidence: number;
  formation_basis: string[];
  geometry: QueueGeometry;
  flow: FlowRates;
  capacity: ServiceCapacity;
  wait: WaitEstimate;
  mean_dwell_seconds: number | null;
  max_dwell_seconds: number | null;
}

export interface QueueReport {
  frame_seq: number;
  frame_ts: string;
  queues: QueueMetrics[];
  unconfigured: boolean;
}

export interface ForecastPoint {
  horizon_minutes: number;
  at: string;
  expected: number;
  lower: number;
  upper: number;
}

export interface MethodForecast {
  method: ForecastMethod;
  points: ForecastPoint[];
  confidence: number;
  unavailable_reason: string | null;
}

export interface GrowthAssessment {
  pattern: GrowthPattern;
  growth_rate_per_min: number;
  baseline_rate_per_min: number | null;
  baseline_std: number | null;
  z_score: number | null;
  change_pct: number | null;
  window_minutes: number;
  samples: number;
  explanation: string;
}

export interface QueueForecast {
  zone_id: string;
  zone_name: string;
  generated_at: string;
  frame_ts: string;
  current_length: number;
  points: ForecastPoint[];
  methods: MethodForecast[];
  method_agreement: number | null;
  growth: GrowthAssessment;
  confidence: number;
  assumptions: string[];
  observation_minutes: number;
}

export interface ForecastReport {
  frame_seq: number;
  frame_ts: string;
  forecasts: QueueForecast[];
}

export interface CapacityOption {
  active_counters: number;
  effective_service_rate_per_min: number;
  projected_queue: number;
  projected_wait_minutes: number | null;
  clears_target: boolean;
  capacity_pressure: number | null;
}

export interface ResourcePlan {
  zone_id: string;
  zone_name: string;
  horizon_minutes: number;
  target_wait_minutes: number;
  current_queue: number;
  current_wait_minutes: number | null;
  arrival_rate_per_min: number;
  total_counters: number;
  current: CapacityOption;
  recommended: CapacityOption;
  options: CapacityOption[];
  action: RecommendationType;
  counters_to_change: number;
  rationale: string;
  expected_effect: string | null;
  feasible: boolean;
  provisional: boolean;
  limiting_factor: string | null;
  confidence: number;
  assumptions: string[];
}

export interface ResourcePlanReport {
  plans: ResourcePlan[];
}

export interface CounterState {
  zone_id: string;
  zone_name: string;
  total_counters: number;
  active_counters: number;
  service_rate_per_min: number;
  idle_counters: number;
}

export interface CountersRead {
  counters: CounterState[];
}

export interface CounterSettingsWrite {
  total_counters: number;
  active_counters: number;
  service_rate_per_min?: number | null;
}

// ---------------------------------------------------------------------------
// Zones and zone flow
// ---------------------------------------------------------------------------

export interface Zone {
  zone_id: string;
  name: string;
  zone_type: ZoneType;
  polygon: ImagePoint[];
  width_m: number | null;
}

export interface ZonesRead {
  camera_id: string;
  zones: Zone[];
  requires_restart: boolean;
}

export interface ZoneFlowSnapshot {
  zone_id: string;
  zone_name: string;
  zone_type: ZoneType;
  occupancy: number;
  entries: number;
  exits: number;
  entry_rate_per_min: number;
  exit_rate_per_min: number;
  dominant_heading_deg: number | null;
  heading_coherence: number | null;
  moving_count: number;
}

export interface ZoneTransition {
  from_zone_id: string;
  to_zone_id: string;
  count: number;
  rate_per_min: number;
  median_transit_seconds: number | null;
}

export interface ZoneFlowReport {
  camera_id: string;
  frame_seq: number;
  frame_ts: string;
  window_seconds: number;
  observation_seconds: number;
  zones: ZoneFlowSnapshot[];
  transitions: ZoneTransition[];
}

// ---------------------------------------------------------------------------
// Per-camera analysis (camera.analysis / GET /cameras/{id}/analytics)
// ---------------------------------------------------------------------------

export interface CameraAnalysis {
  camera_id: string;
  source_mode: SourceMode;
  frame_seq: number;
  frame_ts?: string;
  received_at?: string;
  age_seconds?: number;
  is_stale?: boolean;
  tracked_count?: number | null;
  stability: StabilityAssessment;
  evidence: EvidenceReport | null;
  crowd: CrowdSummary;
  queue: QueueReport | null;
  forecast: ForecastReport | null;
  resources: ResourcePlanReport | null;
  zone_flow?: ZoneFlowReport | null;
  degraded: boolean;
  degraded_reason: string | null;
}

// ---------------------------------------------------------------------------
// Cameras
// ---------------------------------------------------------------------------

export interface CameraMetrics {
  achieved_fps: number | null;
  source_fps: number | null;
  native_width: number | null;
  native_height: number | null;
  analysis_width: number | null;
  analysis_height: number | null;
  frames_processed: number;
  frames_dropped: number;
  last_frame_at: string | null;
  frame_age_seconds: number | null;
  inference_ms: number | null;
  processing_ms: number | null;
  pipeline_latency_ms: number | null;
  network_rtt_ms: number | null;
  device_name: string | null;
  battery_percent: number | null;
  device_checked_at: string | null;
  people_count: number | null;
  tracked_count: number | null;
  detection_active: boolean;
  tracking_active: boolean;
  reconnections: number;
}

export interface Camera {
  camera_id: string;
  display_id: string;
  name: string;
  location: string;
  role: CameraRole;
  coverage_area: string;
  enabled: boolean;
  is_primary: boolean;
  origin: CameraOrigin;
  order: number;
  stream_url: string | null;
  url_source: UrlSource;
  demo_video_path: string | null;
  source_mode: SourceMode;
  status: CameraConnectionStatus;
  status_detail: string | null;
  status_since: string;
  worker_state: WorkerState;
  diagnosis: StreamOutcome | null;
  zone_count: number;
  queue_zone_count: number;
  metrics: CameraMetrics;
}

export interface CamerasRead {
  cameras: Camera[];
  total: number;
  enabled: number;
  contributing: number;
  registry_error: string | null;
}

export interface CameraSpec {
  camera_id?: string | null;
  name: string;
  location?: string;
  role?: CameraRole;
  stream_url?: string | null;
  demo_video_path?: string | null;
  enabled?: boolean;
  coverage_area?: string | null;
}

export type CameraChanges = Partial<Omit<CameraSpec, "camera_id">>;

export interface ConnectionTestRead {
  url: string;
  success: boolean;
  outcome: StreamOutcome;
  detail: string;
  tested_at: string;
  duration_seconds: number;
  width: number | null;
  height: number | null;
  reported_fps: number | null;
  measured_fps: number | null;
  first_frame_ms: number | null;
  frames_read: number;
  failed_reads: number;
  network_rtt_ms: number | null;
  device_name: string | null;
  battery_percent: number | null;
  live_measurement: boolean;
}

// ---------------------------------------------------------------------------
// Site intelligence and topology
// ---------------------------------------------------------------------------

export interface SiteCameraSummary {
  camera_id: string;
  name: string;
  role: CameraRole;
  coverage_area: string;
  status: CameraConnectionStatus;
  status_detail: string | null;
  contributing: boolean;
  excluded_reason: string | null;
  source_mode: SourceMode | null;
  observed_at: string | null;
  analysis_age_seconds: number | null;
  people_count: number | null;
  count_method: CountMethod | null;
  operational_status: OperationalStatus | null;
  csi: number | null;
  density_max: number | null;
  density_is_metric: boolean;
  queue_zone_count: number;
  queue_length: number | null;
  arrival_rate_per_min: number | null;
  service_rate_per_min: number | null;
  wait_minutes: number | null;
  growth_pattern: GrowthPattern | null;
  growth_rate_per_min: number | null;
  predicted_queue: number | null;
  predicted_horizon_minutes: number | null;
}

export interface CoverageAreaCount {
  coverage_area: string;
  camera_ids: string[];
  value: number;
  upper_bound: number;
  overlapping: boolean;
}

export interface SiteHeadcount {
  value: number | null;
  upper_bound: number | null;
  aggregation: CountAggregation;
  label: string;
  explanation: string;
  areas: CoverageAreaCount[];
  contributing_camera_ids: string[];
  missing_camera_ids: string[];
}

export interface QueueZoneRef {
  camera_id: string;
  zone_id: string;
  zone_name: string;
  coverage_area: string;
  queue_length: number;
  wait_minutes: number | null;
  growth_pattern: GrowthPattern | null;
}

export interface SiteQueueSummary {
  queue_length: number;
  upper_bound: number;
  aggregation: CountAggregation;
  arrival_rate_per_min: number;
  service_rate_per_min: number;
  effective_capacity_per_min: number;
  total_counters: number;
  active_counters: number;
  rate_source: RateSource;
  wait_minutes: number | null;
  capacity_pressure: number | null;
  zones: QueueZoneRef[];
  missing_camera_ids: string[];
}

export interface SiteForecast {
  scope: SiteForecastScope;
  available: boolean;
  withheld_reason: string | null;
  forecast: QueueForecast | null;
  contributing_camera_ids: string[];
  basis: string;
}

export interface HotspotFactor {
  key: string;
  label: string;
  value: number;
  weight: number;
  contribution: number;
  detail: string;
}

export interface Hotspot {
  camera_id: string;
  zone_id: string | null;
  label: string;
  score: number;
  reasons: string[];
  factors: HotspotFactor[];
}

export interface TimeToPressure {
  label: string;
  camera_id: string | null;
  zone_id: string | null;
  minutes: number | null;
  already_exceeded: boolean;
  within_horizon: boolean;
  horizon_minutes: number;
  threshold_queue_length: number | null;
  target_wait_minutes: number;
  explanation: string;
}

export interface SiteFlowNode {
  node_id: string;
  camera_id: string;
  camera_name: string;
  zone_id: string;
  zone_name: string;
  zone_type: ZoneType;
  camera_role: CameraRole;
  available: boolean;
  occupancy: number | null;
  entry_rate_per_min: number | null;
  exit_rate_per_min: number | null;
  dominant_heading_deg: number | null;
}

export interface ZoneFlowLink {
  link_id: string;
  from_node_id: string;
  to_node_id: string;
  basis: FlowLinkBasis;
  from_exit_rate_per_min: number | null;
  to_entry_rate_per_min: number | null;
  tracked_rate_per_min: number | null;
  median_transit_seconds: number | null;
  conversion_ratio: number | null;
  explanation: string;
}

export interface SiteAlert {
  alert_id: string;
  kind: SiteAlertKind;
  severity: Severity;
  title: string;
  explanation: string;
  evidence: string[];
  camera_id: string | null;
  zone_id: string | null;
}

export interface SiteReport {
  generated_at: string;
  cameras_total: number;
  cameras_enabled: number;
  cameras_contributing: number;
  cameras: SiteCameraSummary[];
  headcount: SiteHeadcount;
  queue: SiteQueueSummary | null;
  demand_forecast: SiteForecast;
  queue_forecast: SiteForecast;
  resource_plan: ResourcePlan | null;
  resource_plan_withheld_reason: string | null;
  hotspot: Hotspot | null;
  time_to_pressure: TimeToPressure[];
  flow_nodes: SiteFlowNode[];
  flow_links: ZoneFlowLink[];
  alerts: SiteAlert[];
  degraded: boolean;
  degraded_reasons: string[];
}

export interface TopologyRead {
  cameras: {
    camera_id: string;
    display_id: string;
    name: string;
    role: CameraRole;
    coverage_area: string;
    enabled: boolean;
  }[];
  zones: { camera_id: string; zone_id: string; name: string; zone_type: ZoneType }[];
  links: {
    link_id: string;
    from_camera_id: string;
    from_zone_id: string;
    to_camera_id: string;
    to_zone_id: string;
    crosses_cameras: boolean;
  }[];
  load_error: string | null;
}

export interface TopologyLinkWrite {
  from_camera_id: string;
  from_zone_id: string;
  to_camera_id: string;
  to_zone_id: string;
}

// ---------------------------------------------------------------------------
// Platform
// ---------------------------------------------------------------------------

export interface ComponentHealth {
  component: ComponentType;
  status: HealthStatus;
  detail: string | null;
  last_seen: string | null;
}

export interface SystemHealth {
  components: ComponentHealth[];
  checked_at: string;
}

export interface SystemInfo {
  name: string;
  version: string;
  environment: string;
  api_version: string;
  analysis_fps: number;
  server_time: string;
  operator_name: string;
  camera_id: string;
  camera_name: string;
  camera_location: string;
}

export interface PipelineStatus {
  state: WorkerState;
  detail: string | null;
  state_changed_at: string;
  running: boolean;
  source_mode: string;
  source_id: string | null;
  camera_id: string;
  model_name: string | null;
  device: DetectionDevice | null;
  throughput: {
    frames_processed: number;
    frames_dropped: number;
    achieved_fps: number;
    last_frame_at: string | null;
  } | null;
  degraded: boolean;
  degraded_reason: string | null;
  restart_attempts: number;
  total_restarts: number;
}

export interface StreamStatus {
  available: boolean;
  has_frame: boolean;
  viewers: number;
  worker_state: WorkerState;
}

export interface TimelineEntry {
  entry_id: string;
  sequence: number;
  occurred_at: string;
  entry_type: TimelineEntryType;
  severity: Severity;
  title: string;
  detail: string | null;
  camera_id: string;
  actor: string | null;
}

export interface TimelineRead {
  entries: TimelineEntry[];
  total: number;
  latest_sequence: number;
}

export interface DecisionHistoryRead {
  reports: OperationalIntelligenceReport[];
  total: number;
}

export interface OperatorActionRead {
  camera_id: string;
  operational_state: OperationalState;
  entry: TimelineEntry;
}

// ---------------------------------------------------------------------------
// Simulation
// ---------------------------------------------------------------------------

export interface SimulationWrite {
  arrival_rate_per_min: number;
  service_rate_per_counter_per_min: number;
  total_counters: number;
  active_counters: number;
  initial_queue: number;
  duration_minutes: number;
  arrival_growth_per_min: number;
  surge_start_minute: number;
  seed: number;
}

export interface SimulationRead {
  mode: "SIMULATION";
  queue: QueueReport;
  forecast: ForecastReport;
  resources: ResourcePlanReport;
  series: { minute: number; queue_length: number }[];
  simulated_minutes: number;
  steps: number;
}
