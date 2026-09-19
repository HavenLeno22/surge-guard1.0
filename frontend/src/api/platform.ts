import type {
  Camera,
  CameraAnalysis,
  CameraChanges,
  CameraDecision,
  CamerasRead,
  CameraSpec,
  ConnectionTestRead,
  CounterSettingsWrite,
  CountersRead,
  CrowdIntelligenceRead,
  DecisionHistoryRead,
  DecisionRead,
  EvidenceHistoryRead,
  OperatorAction,
  OperatorActionRead,
  PerceptionIngestStatus,
  PerceptionRead,
  PipelineStatus,
  SimulationRead,
  SimulationWrite,
  SiteReport,
  StreamLayer,
  StreamStatus,
  SystemHealth,
  SystemInfo,
  TimelineRead,
  TopologyLinkWrite,
  TopologyRead,
  Zone,
  ZonesRead,
} from "@/types/contracts";
import type { HardwareStatus, HardwareTestWrite } from "@/types/hardware";
import type { HistorySeries, HistorySummary } from "@/types/history";

import { API_BASE, apiRequest, apiRequestEnvelope } from "./client";

const cameraPath = (cameraId: string) => `/cameras/${encodeURIComponent(cameraId)}`;

/** The Arduino alert hardware: status, and a bounded test that overrides live monitoring. */
export const hardwareApi = {
  status: (signal?: AbortSignal) => apiRequest<HardwareStatus>("/hardware", { signal }),
  startTest: (body: HardwareTestWrite) =>
    apiRequest<HardwareStatus>("/hardware/test", { method: "POST", body }),
  stopTest: () => apiRequest<HardwareStatus>("/hardware/test", { method: "DELETE" }),
};

export const systemApi = {
  health: (signal?: AbortSignal) => apiRequest<SystemHealth>("/system-health", { signal }),
  info: (signal?: AbortSignal) => apiRequest<SystemInfo>("/system-info", { signal }),
  pipeline: (signal?: AbortSignal) => apiRequest<PipelineStatus>("/pipeline/status", { signal }),
  perception: (signal?: AbortSignal) => apiRequest<PerceptionRead>("/perception/latest", { signal }),
  perceptionStatus: (signal?: AbortSignal) =>
    apiRequest<PerceptionIngestStatus>("/perception/status", { signal }),
  streamStatus: (signal?: AbortSignal) =>
    apiRequest<StreamStatus>("/camera/stream/status", { signal }),
  ready: (signal?: AbortSignal) =>
    apiRequest<{ status: string; database: boolean }>("/health/ready", { signal }),
};

export const camerasApi = {
  list: (signal?: AbortSignal) => apiRequest<CamerasRead>("/cameras", { signal }),
  get: (cameraId: string, signal?: AbortSignal) =>
    apiRequest<Camera>(cameraPath(cameraId), { signal }),
  add: (spec: CameraSpec) => apiRequestEnvelope<Camera>("/cameras", { method: "POST", body: spec }),
  update: (cameraId: string, changes: CameraChanges) =>
    apiRequestEnvelope<Camera>(cameraPath(cameraId), { method: "PATCH", body: changes }),
  remove: (cameraId: string) =>
    apiRequestEnvelope<null>(cameraPath(cameraId), { method: "DELETE" }),
  retry: (cameraId: string) =>
    apiRequestEnvelope<Camera>(`${cameraPath(cameraId)}/retry`, { method: "POST" }),
  testAddress: (url: string, cameraId?: string | null) =>
    apiRequest<ConnectionTestRead>("/cameras/test-connection", {
      method: "POST",
      body: { url, camera_id: cameraId ?? null },
      timeoutMs: 30_000,
    }),
  testCamera: (cameraId: string) =>
    apiRequest<ConnectionTestRead>(`${cameraPath(cameraId)}/test-connection`, {
      method: "POST",
      timeoutMs: 30_000,
    }),
  analysis: (cameraId: string, signal?: AbortSignal) =>
    apiRequest<CameraAnalysis>(`${cameraPath(cameraId)}/analytics`, { signal }),
  decisions: (cameraId: string, signal?: AbortSignal) =>
    apiRequest<CameraDecision>(`${cameraPath(cameraId)}/decisions`, { signal }),
  operate: (cameraId: string, action: OperatorAction, note?: string, ruleId?: string) =>
    apiRequestEnvelope<OperatorActionRead>(`${cameraPath(cameraId)}/operations`, {
      method: "POST",
      body: { action, note: note || null, rule_id: ruleId ?? null },
    }),
  zones: (cameraId: string, signal?: AbortSignal) =>
    apiRequest<ZonesRead>(`${cameraPath(cameraId)}/zones`, { signal }),
  saveZones: (cameraId: string, zones: Zone[]) =>
    apiRequestEnvelope<ZonesRead>(`${cameraPath(cameraId)}/zones`, {
      method: "PUT",
      body: { zones },
    }),
  counters: (cameraId: string, signal?: AbortSignal) =>
    apiRequest<CountersRead>(`${cameraPath(cameraId)}/counters`, { signal }),
  setCounters: (cameraId: string, zoneId: string, body: CounterSettingsWrite) =>
    apiRequestEnvelope<CountersRead>(
      `${cameraPath(cameraId)}/counters/${encodeURIComponent(zoneId)}`,
      { method: "POST", body },
    ),
};

/** MJPEG stream for an <img>. `nonce` forces a fresh connection after a failure. */
export function cameraStreamUrl(cameraId: string, layers: StreamLayer[], nonce = 0): string {
  const params = new URLSearchParams({ layers: layers.join(",") });
  if (nonce) params.set("v", String(nonce));
  return `${API_BASE}${cameraPath(cameraId)}/stream?${params.toString()}`;
}

/** A single fresh JPEG. `nonce` defeats any cache between refreshes. */
export function cameraSnapshotUrl(cameraId: string, layers: StreamLayer[], nonce: number): string {
  const params = new URLSearchParams({ layers: layers.join(","), v: String(nonce) });
  return `${API_BASE}${cameraPath(cameraId)}/snapshot?${params.toString()}`;
}

export const siteApi = {
  analytics: (signal?: AbortSignal) => apiRequest<SiteReport>("/global/analytics", { signal }),
  topology: (signal?: AbortSignal) => apiRequest<TopologyRead>("/global/topology", { signal }),
  saveTopology: (links: TopologyLinkWrite[]) =>
    apiRequestEnvelope<TopologyRead>("/global/topology", { method: "PUT", body: { links } }),
};

export const decisionsApi = {
  current: (signal?: AbortSignal) => apiRequest<DecisionRead>("/decisions/current", { signal }),
  history: (limit = 50, signal?: AbortSignal) =>
    apiRequest<DecisionHistoryRead>("/decisions/history", { query: { limit }, signal }),
  timeline: (limit = 200, signal?: AbortSignal) =>
    apiRequest<TimelineRead>("/decisions/timeline", { query: { limit }, signal }),
  intelligence: (signal?: AbortSignal) =>
    apiRequest<CrowdIntelligenceRead>("/intelligence/current", { signal }),
  evidenceHistory: (signal?: AbortSignal) =>
    apiRequest<EvidenceHistoryRead>("/intelligence/evidence/history", { signal }),
};

export const simulationApi = {
  run: (body: SimulationWrite) =>
    apiRequestEnvelope<SimulationRead>("/simulation/run", {
      method: "POST",
      body,
      timeoutMs: 30_000,
    }),
  state: (signal?: AbortSignal) => apiRequest<SimulationRead>("/simulation/state", { signal }),
  reset: () => apiRequest<null>("/simulation/reset", { method: "POST" }),
};

export interface HistoryParams {
  from?: string;
  to?: string;
  resolution?: number;
  sourceMode?: "LIVE" | "DEMO";
}

export const historyApi = {
  camera: (cameraId: string, params: HistoryParams, signal?: AbortSignal) =>
    apiRequest<HistorySeries>(`/history/cameras/${encodeURIComponent(cameraId)}`, {
      query: {
        from: params.from,
        to: params.to,
        resolution: params.resolution,
        source_mode: params.sourceMode,
      },
      signal,
    }),
  site: (params: HistoryParams, signal?: AbortSignal) =>
    apiRequest<HistorySeries>("/history/site", {
      query: {
        from: params.from,
        to: params.to,
        resolution: params.resolution,
        source_mode: params.sourceMode,
      },
      signal,
    }),
  summary: (params: HistoryParams, signal?: AbortSignal) =>
    apiRequest<HistorySummary>("/history/summary", {
      query: { from: params.from, to: params.to, source_mode: params.sourceMode },
      signal,
    }),
};
