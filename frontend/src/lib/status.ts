/**
 * Status semantics: CSI bands, severity ranks, and the colour tone for each state.
 *
 * Colour is reserved for meaning. Only the five Operational Status tones are
 * saturated; everything else is an ink tone. Class names are written out in
 * full so Tailwind can find them.
 */

import type {
  AlertPriority,
  CameraConnectionStatus,
  HealthStatus,
  OperationalStatus,
  Severity,
} from "@/types/contracts";

export type Tone =
  | "stable"
  | "observe"
  | "attention"
  | "high"
  | "critical"
  | "neutral"
  | "muted"
  | "faint";

/** Inclusive lower bound of each band, most stable first (contracts/enums.py CSI_BANDS). */
export const CSI_BANDS: { min: number; status: OperationalStatus }[] = [
  { min: 80, status: "STABLE" },
  { min: 60, status: "OBSERVE" },
  { min: 40, status: "ATTENTION_REQUIRED" },
  { min: 20, status: "HIGH_ALERT" },
  { min: 0, status: "CRITICAL" },
];

/** The band a CSI value falls in. High CSI is stable; values are clamped to 0–100. */
export function statusFromCsi(csi: number): OperationalStatus {
  const clamped = Math.min(Math.max(csi, 0), 100);
  for (const band of CSI_BANDS) {
    if (clamped >= band.min) return band.status;
  }
  return "CRITICAL";
}

export const STATUS_RANK: Record<OperationalStatus, number> = {
  STABLE: 0,
  OBSERVE: 1,
  ATTENTION_REQUIRED: 2,
  HIGH_ALERT: 3,
  CRITICAL: 4,
};

export const STATUS_TONE: Record<OperationalStatus, Tone> = {
  STABLE: "stable",
  OBSERVE: "observe",
  ATTENTION_REQUIRED: "attention",
  HIGH_ALERT: "high",
  CRITICAL: "critical",
};

export function worstStatus(
  statuses: Iterable<OperationalStatus | null | undefined>,
): OperationalStatus | null {
  let worst: OperationalStatus | null = null;
  for (const status of statuses) {
    if (status && (worst === null || STATUS_RANK[status] > STATUS_RANK[worst])) worst = status;
  }
  return worst;
}

export const SEVERITY_TONE: Record<Severity, Tone> = {
  INFO: "neutral",
  WARNING: "attention",
  CRITICAL: "critical",
};

export const SEVERITY_RANK: Record<Severity, number> = { INFO: 0, WARNING: 1, CRITICAL: 2 };

export const PRIORITY_TONE: Record<AlertPriority, Tone> = {
  LOW: "neutral",
  MEDIUM: "attention",
  HIGH: "high",
  CRITICAL: "critical",
};

export const HEALTH_TONE: Record<HealthStatus, Tone> = {
  HEALTHY: "stable",
  WARNING: "attention",
  OFFLINE: "critical",
};

export const CAMERA_STATUS_TONE: Record<CameraConnectionStatus, Tone> = {
  ONLINE: "stable",
  DEGRADED: "attention",
  RECOVERING: "high",
  OFFLINE: "critical",
  CONNECTING: "muted",
  DISABLED: "faint",
};

/** Statuses whose indicator pulses: something is happening and not yet resolved. */
export const CAMERA_STATUS_PULSES: Record<CameraConnectionStatus, boolean> = {
  ONLINE: false,
  DEGRADED: false,
  RECOVERING: true,
  OFFLINE: false,
  CONNECTING: true,
  DISABLED: false,
};

export const TONE_TEXT: Record<Tone, string> = {
  stable: "text-stable",
  observe: "text-observe",
  attention: "text-attention",
  high: "text-high",
  critical: "text-critical-text",
  neutral: "text-ink-secondary",
  muted: "text-ink-muted",
  faint: "text-ink-faint",
};

export const TONE_BG: Record<Tone, string> = {
  stable: "bg-stable",
  observe: "bg-observe",
  attention: "bg-attention",
  high: "bg-high",
  critical: "bg-critical",
  neutral: "bg-ink-secondary",
  muted: "bg-ink-muted",
  faint: "bg-ink-faint",
};

export const TONE_BORDER: Record<Tone, string> = {
  stable: "border-stable/45",
  observe: "border-observe/45",
  attention: "border-attention/45",
  high: "border-high/45",
  critical: "border-critical/55",
  neutral: "border-line-strong",
  muted: "border-line-strong",
  faint: "border-line",
};

export const TONE_SOFT_BG: Record<Tone, string> = {
  stable: "bg-stable/10",
  observe: "bg-observe/10",
  attention: "bg-attention/10",
  high: "bg-high/10",
  critical: "bg-critical/12",
  neutral: "bg-surface-2",
  muted: "bg-surface-2",
  faint: "bg-surface-1",
};

/** Raw hex per tone, for canvas and SVG where a class cannot reach. */
export const TONE_HEX: Record<Tone, string> = {
  stable: "#3CCB85",
  observe: "#5AB8FA",
  attention: "#EFDD55",
  high: "#F99442",
  critical: "#E8435F",
  neutral: "#B3BCC4",
  muted: "#8A96A1",
  faint: "#5D6A76",
};
