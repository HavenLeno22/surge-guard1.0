export interface HistoryRange {
  label: string;
  hours: number;
  /** Seconds per plotted point; the backend rounds it to whole buckets and caps the point count. */
  resolution: number;
}

export const DEFAULT_RANGE: HistoryRange = { label: "24h", hours: 24, resolution: 900 };

export const RANGE_PRESETS: readonly HistoryRange[] = [
  { label: "1h", hours: 1, resolution: 60 },
  { label: "6h", hours: 6, resolution: 300 },
  DEFAULT_RANGE,
  { label: "7d", hours: 24 * 7, resolution: 3600 },
  { label: "30d", hours: 24 * 30, resolution: 21_600 },
];

/** Stored history is re-read this often while the page is open, so a rolling range keeps up with now. */
export const HISTORY_REFRESH_MS = 60_000;

/**
 * The window ending now, as the API expects it.
 *
 * Called when a request is made, never while rendering: queries are keyed by
 * the range's label, so the key stays stable and every refetch (interval or
 * retry) reads a window that ends at the moment it runs.
 */
export function historyWindow(range: HistoryRange, now = Date.now()): { from: string; to: string } {
  return {
    from: new Date(now - range.hours * 3_600_000).toISOString(),
    to: new Date(now).toISOString(),
  };
}
