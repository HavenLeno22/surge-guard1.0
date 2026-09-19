/**
 * Pure state transitions for live data.
 *
 * The socket and the REST fallback both land here, so a pushed message and a
 * fetched response can never leave the interface in two different states -
 * the same guarantee the backend's snapshot builder makes from its side.
 */

import type {
  Camera,
  CameraAnalysis,
  CameraDecision,
  OperationalIntelligenceReport,
  PerceptionRead,
  PipelineStatus,
  SiteReport,
  SystemHealth,
  TimelineEntry,
} from "@/types/contracts";
import type {
  CamerasChangedData,
  Envelope,
  SnapshotData,
  StateUpdatedData,
} from "@/types/realtime";

export interface TrendPoint {
  /** Epoch ms. */
  t: number;
  csi: number | null;
  people: number | null;
  queue: number | null;
}

export interface SiteTrendPoint {
  t: number;
  headcount: number | null;
  queue: number | null;
}

export type TimedAnalysis = CameraAnalysis & { receivedAt: number };
export type TimedDecision = CameraDecision & { receivedAt: number };

export interface LiveData {
  snapshotAt: number | null;
  primaryCameraId: string | null;
  health: SystemHealth | null;
  pipeline: PipelineStatus | null;
  perception: PerceptionRead | null;
  cameras: Record<string, Camera>;
  cameraOrder: string[];
  analyses: Record<string, TimedAnalysis>;
  decisions: Record<string, TimedDecision>;
  site: SiteReport | null;
  siteReceivedAt: number | null;
  timeline: TimelineEntry[];
  trends: Record<string, TrendPoint[]>;
  siteTrend: SiteTrendPoint[];
}

export const TIMELINE_CAP = 300;
/** Session trends: one point every 2 s for 15 minutes. */
export const TREND_INTERVAL_MS = 2_000;
export const TREND_CAP = 450;

export const initialLiveData: LiveData = {
  snapshotAt: null,
  primaryCameraId: null,
  health: null,
  pipeline: null,
  perception: null,
  cameras: {},
  cameraOrder: [],
  analyses: {},
  decisions: {},
  site: null,
  siteReceivedAt: null,
  timeline: [],
  trends: {},
  siteTrend: [],
};

// -- Helpers ------------------------------------------------------------------

function indexCameras(cameras: Camera[]): Pick<LiveData, "cameras" | "cameraOrder"> {
  const sorted = [...cameras].sort((a, b) => a.order - b.order);
  return {
    cameras: Object.fromEntries(sorted.map((camera) => [camera.camera_id, camera])),
    cameraOrder: sorted.map((camera) => camera.camera_id),
  };
}

/** People waiting across a camera's configured queue zones, or null when none are configured. */
export function queueTotal(analysis: CameraAnalysis | null | undefined): number | null {
  const queue = analysis?.queue;
  if (!queue || queue.unconfigured || queue.queues.length === 0) return null;
  return queue.queues.reduce((total, zone) => total + zone.person_count, 0);
}

function appendSample<T extends { t: number }>(points: T[] | undefined, point: T): T[] {
  const existing = points ?? [];
  const last = existing.at(-1);
  if (last && point.t - last.t < TREND_INTERVAL_MS) return existing;
  const next = existing.length >= TREND_CAP ? existing.slice(existing.length - TREND_CAP + 1) : [...existing];
  next.push(point);
  return next;
}

function withAnalysis(state: LiveData, analysis: CameraAnalysis, receivedAt: number): LiveData {
  const cameraId = analysis.camera_id;
  const previous = state.analyses[cameraId];
  // csi.updated lacks zone flow and frame time; keep what camera.analysis supplied.
  const merged: TimedAnalysis = {
    ...previous,
    ...analysis,
    zone_flow: analysis.zone_flow !== undefined ? analysis.zone_flow : previous?.zone_flow,
    tracked_count:
      analysis.tracked_count !== undefined ? analysis.tracked_count : previous?.tracked_count,
    frame_ts: analysis.frame_ts ?? previous?.frame_ts,
    receivedAt,
  };
  return {
    ...state,
    analyses: { ...state.analyses, [cameraId]: merged },
    trends: {
      ...state.trends,
      [cameraId]: appendSample(state.trends[cameraId], {
        t: receivedAt,
        csi: analysis.stability?.csi_smoothed ?? null,
        people: analysis.crowd?.person_count ?? null,
        queue: queueTotal(analysis),
      }),
    },
  };
}

function withDecision(
  state: LiveData,
  cameraId: string,
  patch: Partial<CameraDecision>,
  receivedAt: number,
): LiveData {
  const previous = state.decisions[cameraId];
  const decision: TimedDecision = {
    camera_id: cameraId,
    report: null,
    operational_state: "MONITORING",
    received_at: null,
    age_seconds: null,
    is_stale: false,
    ...previous,
    ...patch,
    receivedAt,
  };
  return { ...state, decisions: { ...state.decisions, [cameraId]: decision } };
}

export function mergeTimeline(
  existing: TimelineEntry[],
  incoming: TimelineEntry[],
): TimelineEntry[] {
  const seen = new Set(existing.map((entry) => entry.entry_id));
  const fresh = incoming.filter((entry) => !seen.has(entry.entry_id));
  if (fresh.length === 0) return existing;
  // Ordered by append sequence, as the backend orders it: entries can share a
  // millisecond, and a recording's frame time is not wall-clock time.
  return [...fresh, ...existing].sort((a, b) => b.sequence - a.sequence).slice(0, TIMELINE_CAP);
}

function withSite(state: LiveData, site: SiteReport, receivedAt: number): LiveData {
  return {
    ...state,
    site,
    siteReceivedAt: receivedAt,
    siteTrend: appendSample(state.siteTrend, {
      t: receivedAt,
      headcount: site.headcount.value,
      queue: site.queue ? site.queue.queue_length : null,
    }),
  };
}

function withCameras(state: LiveData, cameras: Camera[]): LiveData {
  const indexed = indexCameras(cameras);
  const present = new Set(indexed.cameraOrder);
  const keep = <T>(record: Record<string, T>) =>
    Object.fromEntries(Object.entries(record).filter(([cameraId]) => present.has(cameraId)));
  const primary = cameras.find((camera) => camera.is_primary)?.camera_id ?? state.primaryCameraId;
  return {
    ...state,
    ...indexed,
    primaryCameraId: primary,
    // A removed camera takes its analysis, guidance and trend with it.
    analyses: keep(state.analyses),
    decisions: keep(state.decisions),
    trends: keep(state.trends),
  };
}

// -- Transitions ----------------------------------------------------------------

export function applySnapshot(state: LiveData, data: SnapshotData, receivedAt: number): LiveData {
  let next: LiveData = {
    ...state,
    snapshotAt: receivedAt,
    health: data.health,
    pipeline: data.pipeline,
    perception: data.perception,
    analyses: {},
    decisions: {},
    site: null,
    siteReceivedAt: null,
    timeline: [...(data.timeline ?? [])].slice(0, TIMELINE_CAP),
  };
  next = withCameras(next, data.cameras ?? []);
  if (!next.primaryCameraId) next.primaryCameraId = data.pipeline?.camera_id ?? null;

  for (const analysis of Object.values(data.camera_analyses ?? {})) {
    next = withAnalysis(next, analysis, receivedAt);
  }
  if (data.assessment && next.primaryCameraId && !next.analyses[next.primaryCameraId]) {
    next = withAnalysis(next, data.assessment, receivedAt);
  }

  if (data.camera_decisions) {
    for (const [cameraId, decision] of Object.entries(data.camera_decisions)) {
      next = withDecision(next, cameraId, decision, receivedAt);
    }
  } else if (next.primaryCameraId) {
    next = withDecision(
      next,
      next.primaryCameraId,
      { report: data.report, operational_state: data.operational_state },
      receivedAt,
    );
  }

  if (data.site) next = withSite(next, data.site, receivedAt);
  return next;
}

export function applyEnvelope(state: LiveData, envelope: Envelope, receivedAt: number): LiveData {
  switch (envelope.type) {
    case "snapshot":
      return applySnapshot(state, envelope.data as SnapshotData, receivedAt);

    case "camera.analysis":
    case "csi.updated": {
      const analysis = envelope.data as CameraAnalysis;
      if (!analysis?.camera_id) return state;
      return withAnalysis(state, analysis, receivedAt);
    }

    case "detections.updated":
      return { ...state, perception: envelope.data as PerceptionRead };

    case "oir.updated": {
      const cameraId = envelope.camera_id ?? state.primaryCameraId;
      if (!cameraId) return state;
      return withDecision(
        state,
        cameraId,
        {
          report: envelope.data as OperationalIntelligenceReport,
          received_at: envelope.ts,
          age_seconds: 0,
          is_stale: false,
        },
        receivedAt,
      );
    }

    case "state.updated": {
      const data = envelope.data as StateUpdatedData;
      if (!data?.camera_id) return state;
      return withDecision(
        state,
        data.camera_id,
        { operational_state: data.operational_state },
        receivedAt,
      );
    }

    case "timeline.appended":
      return { ...state, timeline: mergeTimeline(state.timeline, [envelope.data as TimelineEntry]) };

    case "camera.status":
      return withCameras(state, (envelope.data as { cameras: Camera[] }).cameras ?? []);

    case "cameras.changed":
      return withCameras(state, (envelope.data as CamerasChangedData).cameras ?? []);

    case "site.updated":
      return withSite(state, envelope.data as SiteReport, receivedAt);

    case "health.updated":
      return { ...state, health: envelope.data as SystemHealth };

    default:
      return state;
  }
}

// -- REST fallback --------------------------------------------------------------

export interface FallbackBatch {
  cameras?: Camera[];
  analyses?: CameraAnalysis[];
  decisions?: CameraDecision[];
  site?: SiteReport | null;
  health?: SystemHealth;
  pipeline?: PipelineStatus;
  timeline?: TimelineEntry[];
}

/** Apply what REST polling fetched while the socket is not live. */
export function applyFallback(state: LiveData, batch: FallbackBatch, receivedAt: number): LiveData {
  let next = state;
  if (batch.cameras) next = withCameras(next, batch.cameras);
  for (const analysis of batch.analyses ?? []) next = withAnalysis(next, analysis, receivedAt);
  for (const decision of batch.decisions ?? []) {
    next = withDecision(next, decision.camera_id, decision, receivedAt);
  }
  if (batch.site) next = withSite(next, batch.site, receivedAt);
  if (batch.health) next = { ...next, health: batch.health };
  if (batch.pipeline) next = { ...next, pipeline: batch.pipeline };
  if (batch.timeline) next = { ...next, timeline: mergeTimeline(next.timeline, batch.timeline) };
  return next;
}
