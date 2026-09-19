/**
 * The Command Center socket contract (backend/app/realtime/envelope.py,
 * publisher.py and snapshot.py).
 */

import type {
  Camera,
  CameraAnalysis,
  CameraDecision,
  OperationalIntelligenceReport,
  OperationalState,
  PerceptionRead,
  PipelineStatus,
  SiteReport,
  SystemHealth,
  TimelineEntry,
} from "./contracts";

export type WsEventType =
  | "snapshot"
  | "heartbeat"
  | "csi.updated"
  | "detections.updated"
  | "oir.updated"
  | "state.updated"
  | "timeline.appended"
  | "camera.status"
  | "cameras.changed"
  | "camera.analysis"
  | "site.updated"
  | "health.updated"
  | "event.created"
  | "event.updated"
  | "alert.created"
  | "demo.state";

export interface Envelope<T = unknown> {
  type: WsEventType;
  seq: number;
  ts: string;
  camera_id: string | null;
  data: T;
}

export interface SnapshotData {
  health: SystemHealth | null;
  pipeline: PipelineStatus | null;
  perception: PerceptionRead | null;
  assessment: CameraAnalysis | null;
  report: OperationalIntelligenceReport | null;
  operational_state: OperationalState;
  timeline: TimelineEntry[];
  timeline_sequence: number;
  stale_after_seconds: number;
  cameras: Camera[];
  camera_analyses: Record<string, CameraAnalysis>;
  camera_decisions?: Record<string, CameraDecision>;
  site: SiteReport | null;
}

export interface StateUpdatedData {
  camera_id: string;
  operational_state: OperationalState;
  actor: string | null;
}

export interface CamerasChangedData {
  change: { camera_id?: string; change?: string };
  cameras: Camera[];
}

export type ClientAction = "resync" | "pong";
