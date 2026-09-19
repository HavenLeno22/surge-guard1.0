/**
 * Formatting for measured values.
 *
 * One rule runs through every function here: a value the backend did not
 * measure is shown as missing, never as zero. `null` in, `MISSING` out.
 */

export const MISSING = "—";

const numberFormatters = new Map<string, Intl.NumberFormat>();

function numberFormat(minimum: number, maximum: number): Intl.NumberFormat {
  const key = `${minimum}:${maximum}`;
  let formatter = numberFormatters.get(key);
  if (!formatter) {
    formatter = new Intl.NumberFormat("en-GB", {
      minimumFractionDigits: minimum,
      maximumFractionDigits: maximum,
    });
    numberFormatters.set(key, formatter);
  }
  return formatter;
}

export function isMeasured(value: number | null | undefined): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

export function formatNumber(
  value: number | null | undefined,
  digits = 0,
  { minimumDigits = digits }: { minimumDigits?: number } = {},
): string {
  if (!isMeasured(value)) return MISSING;
  return numberFormat(minimumDigits, digits).format(value);
}

export function formatInteger(value: number | null | undefined): string {
  return formatNumber(value, 0);
}

/** The Crowd Stability Index as an operator reads it: a whole number. */
export function formatCsi(value: number | null | undefined): string {
  return isMeasured(value) ? String(Math.round(value)) : MISSING;
}

/** A 0–1 share as a percentage. */
export function formatPercent(value: number | null | undefined, digits = 0): string {
  if (!isMeasured(value)) return MISSING;
  return `${numberFormat(digits, digits).format(value * 100)}%`;
}

export function formatRate(perMinute: number | null | undefined, digits = 1): string {
  if (!isMeasured(perMinute)) return MISSING;
  return `${numberFormat(0, digits).format(perMinute)}/min`;
}

export function formatMs(value: number | null | undefined): string {
  if (!isMeasured(value)) return MISSING;
  return value >= 100 ? `${Math.round(value)} ms` : `${numberFormat(0, 1).format(value)} ms`;
}

export function formatFps(value: number | null | undefined): string {
  if (!isMeasured(value)) return MISSING;
  return `${numberFormat(1, 1).format(value)} fps`;
}

/** A duration in minutes, readable at a glance: "<1 min", "12 min", "1 h 5 min". */
export function formatMinutes(minutes: number | null | undefined): string {
  if (!isMeasured(minutes)) return MISSING;
  if (minutes < 1) return "<1 min";
  const rounded = Math.round(minutes);
  if (rounded < 60) return `${rounded} min`;
  const hours = Math.floor(rounded / 60);
  const rest = rounded % 60;
  return rest ? `${hours} h ${rest} min` : `${hours} h`;
}

/**
 * An estimated wait. `null` with people waiting means nobody is being served -
 * an unbounded wait, which is never shown as a very large number.
 */
export function formatWait(minutes: number | null | undefined, queueLength: number): string {
  if (isMeasured(minutes)) return formatMinutes(minutes);
  return queueLength > 0 ? "Not draining" : "No queue";
}

export interface DensityDisplay {
  value: string;
  unit: "p/m²" | "relative";
}

/**
 * Density with the only honest unit. Uncalibrated density is relative and is
 * never presented as persons per square metre (Architecture Review C21).
 */
export function formatDensity(value: number | null | undefined, isMetric: boolean): DensityDisplay {
  return { value: formatNumber(value, 2), unit: isMetric ? "p/m²" : "relative" };
}

/** A span of seconds: "45 s", "3 min", "2 h 10 min". */
export function formatDuration(seconds: number | null | undefined): string {
  if (!isMeasured(seconds)) return MISSING;
  if (seconds < 60) return `${Math.max(0, Math.round(seconds))} s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)} min`;
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.round((seconds % 3600) / 60);
  if (hours >= 48) return `${Math.round(hours / 24)} days`;
  return minutes ? `${hours} h ${minutes} min` : `${hours} h`;
}

/** How long ago something happened, in seconds: "just now", "12 s ago", "3 min ago". */
export function formatAge(seconds: number | null | undefined): string {
  if (!isMeasured(seconds)) return MISSING;
  if (seconds < 2) return "just now";
  return `${formatDuration(seconds)} ago`;
}

const clockFormat = new Intl.DateTimeFormat("en-GB", {
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hour12: false,
});

const shortClockFormat = new Intl.DateTimeFormat("en-GB", {
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

const dateTimeFormat = new Intl.DateTimeFormat("en-GB", {
  day: "numeric",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

const dateFormat = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short" });

function toDate(value: string | number | Date | null | undefined): Date | null {
  if (value === null || value === undefined) return null;
  const date = value instanceof Date ? value : new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

export function formatClock(value: string | number | Date | null | undefined): string {
  const date = toDate(value);
  return date ? clockFormat.format(date) : MISSING;
}

export function formatShortClock(value: string | number | Date | null | undefined): string {
  const date = toDate(value);
  return date ? shortClockFormat.format(date) : MISSING;
}

export function formatDateTime(value: string | number | Date | null | undefined): string {
  const date = toDate(value);
  return date ? dateTimeFormat.format(date) : MISSING;
}

export function formatDate(value: string | number | Date | null | undefined): string {
  const date = toDate(value);
  return date ? dateFormat.format(date) : MISSING;
}

/** Seconds between an ISO timestamp and now. `null` for a missing or invalid timestamp. */
export function secondsSince(
  value: string | number | Date | null | undefined,
  now: number = Date.now(),
): number | null {
  const date = toDate(value);
  return date ? Math.max(0, (now - date.getTime()) / 1000) : null;
}

export function plural(count: number, singular: string, pluralForm = `${singular}s`): string {
  return `${formatInteger(count)} ${count === 1 ? singular : pluralForm}`;
}
