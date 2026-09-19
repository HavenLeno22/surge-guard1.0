/** Mirrors of backend/app/schemas/history.py. */

import type { SourceMode } from "./contracts";

export interface HistoryPoint {
  t: string;
  samples: number;
  degraded_share: number;
  csi_mean: number | null;
  csi_min: number | null;
  csi_max: number | null;
  status_worst: string | null;
  status_samples: Record<string, number>;
  confidence_mean: number | null;
  people_mean: number | null;
  people_max: number | null;
  estimated_share: number;
  density_max: number | null;
  density_is_metric: boolean | null;
  queue_length_mean: number | null;
  queue_length_max: number | null;
  wait_minutes_mean: number | null;
  wait_minutes_max: number | null;
  arrival_rate_mean: number | null;
  service_rate_mean: number | null;
  cameras_contributing_min: number | null;
}

export interface HistorySeries {
  camera_id: string;
  start: string;
  end: string;
  resolution_seconds: number;
  bucket_seconds: number;
  source_mode: SourceMode;
  points: HistoryPoint[];
}

export interface HistorySummaryItem {
  camera_id: string;
  buckets: number;
  observed_seconds: number;
  first_at: string | null;
  last_at: string | null;
  baseline_available: boolean;
  csi_mean: number | null;
  csi_min: number | null;
  people_mean: number | null;
  people_max: number | null;
  queue_length_max: number | null;
  wait_minutes_max: number | null;
  status_share: Record<string, number>;
  estimated_share: number;
}

export interface HistorySummary {
  start: string;
  end: string;
  source_mode: SourceMode;
  bucket_seconds: number;
  baseline_min_samples: number;
  retention_days: number;
  recording: boolean;
  cameras: HistorySummaryItem[];
  site: HistorySummaryItem | null;
}
