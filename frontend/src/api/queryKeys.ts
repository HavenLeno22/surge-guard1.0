/** TanStack Query keys, in one place so invalidation cannot miss a spelling. */
export const queryKeys = {
  authStatus: ["auth", "status"] as const,
  me: ["auth", "me"] as const,
  sessions: ["auth", "sessions"] as const,
  users: ["users"] as const,
  systemInfo: ["system", "info"] as const,
  systemHealth: ["system", "health"] as const,
  pipeline: ["system", "pipeline"] as const,
  perceptionStatus: ["system", "perception-status"] as const,
  streamStatus: ["system", "stream-status"] as const,
  hardware: ["system", "hardware"] as const,
  cameras: ["cameras"] as const,
  camera: (cameraId: string) => ["cameras", cameraId] as const,
  cameraZones: (cameraId: string) => ["cameras", cameraId, "zones"] as const,
  cameraCounters: (cameraId: string) => ["cameras", cameraId, "counters"] as const,
  topology: ["site", "topology"] as const,
  decisionHistory: ["decisions", "history"] as const,
  timeline: ["decisions", "timeline"] as const,
  evidenceHistory: ["intelligence", "evidence-history"] as const,
  simulation: ["simulation", "state"] as const,
  // Keyed by the range's label, not its timestamps: the window is computed at
  // fetch time, so a key built from `new Date()` would never settle.
  // A `null` mode means "the deployment's own mode", resolved by the backend.
  historySummary: (rangeLabel: string, mode: string | null) =>
    ["history", "summary", rangeLabel, mode] as const,
  historySeries: (scope: string, rangeLabel: string, mode: string | null) =>
    ["history", "series", scope, rangeLabel, mode] as const,
};
