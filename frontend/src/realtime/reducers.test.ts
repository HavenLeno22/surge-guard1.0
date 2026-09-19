import { describe, expect, test } from "vitest";

import type { Camera, CameraAnalysis, TimelineEntry } from "@/types/contracts";
import type { Envelope, SnapshotData } from "@/types/realtime";

import {
  applyEnvelope,
  applyFallback,
  initialLiveData,
  queueTotal,
  TREND_INTERVAL_MS,
} from "./reducers";

function camera(cameraId: string, order: number, isPrimary = false): Camera {
  return {
    camera_id: cameraId,
    display_id: cameraId.toUpperCase(),
    name: `Camera ${cameraId}`,
    location: "",
    role: "GENERAL",
    coverage_area: cameraId,
    enabled: true,
    is_primary: isPrimary,
    origin: "ENVIRONMENT",
    order,
    stream_url: null,
    url_source: "UNSET",
    demo_video_path: null,
    source_mode: "DEMO",
    status: "ONLINE",
    status_detail: null,
    status_since: "2026-09-17T10:00:00Z",
    worker_state: "running",
    diagnosis: null,
    zone_count: 0,
    queue_zone_count: 0,
    metrics: {
      achieved_fps: 10,
      source_fps: 25,
      native_width: 960,
      native_height: 540,
      analysis_width: 960,
      analysis_height: 540,
      frames_processed: 100,
      frames_dropped: 0,
      last_frame_at: null,
      frame_age_seconds: 0.1,
      inference_ms: 20,
      processing_ms: 25,
      pipeline_latency_ms: 30,
      network_rtt_ms: null,
      device_name: null,
      battery_percent: null,
      device_checked_at: null,
      people_count: 4,
      tracked_count: 4,
      detection_active: true,
      tracking_active: true,
      reconnections: 0,
    },
  };
}

function analysis(cameraId: string, csi: number, extra: Partial<CameraAnalysis> = {}): CameraAnalysis {
  return {
    camera_id: cameraId,
    source_mode: "DEMO",
    frame_seq: 1,
    stability: {
      frame_seq: 1,
      frame_ts: "2026-09-17T10:00:00Z",
      csi_raw: csi,
      csi_smoothed: csi,
      status: "STABLE",
      status_changed: false,
      breakdown: { readings: [] },
      confidence: { value: 0.9, factors: [], limiting_factor: null },
    },
    evidence: null,
    crowd: {
      person_count: 4,
      count_method: "TRACKED",
      density_max: 0.5,
      density_mean: 0.3,
      is_metric: false,
      median_speed: null,
      baseline_speed: null,
    },
    queue: null,
    forecast: null,
    resources: null,
    degraded: false,
    degraded_reason: null,
    ...extra,
  };
}

function entry(sequence: number, cameraId = "cam-01"): TimelineEntry {
  return {
    entry_id: `entry-${sequence}`,
    sequence,
    occurred_at: "2026-09-17T10:00:00Z",
    entry_type: "SYSTEM",
    severity: "INFO",
    title: `Entry ${sequence}`,
    detail: null,
    camera_id: cameraId,
    actor: null,
  };
}

function envelope<T>(type: Envelope["type"], data: T, cameraId: string | null = null): Envelope<T> {
  return { type, seq: 1, ts: "2026-09-17T10:00:00Z", camera_id: cameraId, data };
}

const snapshot: SnapshotData = {
  health: null,
  pipeline: null,
  perception: null,
  assessment: null,
  report: null,
  operational_state: "MONITORING",
  timeline: [entry(2), entry(1)],
  timeline_sequence: 2,
  stale_after_seconds: 30,
  cameras: [camera("cam-02", 1000), camera("cam-01", 0, true)],
  camera_analyses: { "cam-01": analysis("cam-01", 82), "cam-02": analysis("cam-02", 55) },
  camera_decisions: {
    "cam-01": {
      camera_id: "cam-01",
      report: null,
      operational_state: "MONITORING",
      received_at: null,
      age_seconds: null,
      is_stale: false,
    },
  },
  site: null,
};

describe("applyEnvelope", () => {
  test("a snapshot replaces state, orders cameras and finds the primary", () => {
    const state = applyEnvelope(initialLiveData, envelope("snapshot", snapshot), 1_000);

    expect(state.cameraOrder).toEqual(["cam-01", "cam-02"]);
    expect(state.primaryCameraId).toBe("cam-01");
    expect(state.analyses["cam-02"]?.stability.csi_smoothed).toBe(55);
    expect(state.decisions["cam-01"]?.operational_state).toBe("MONITORING");
    expect(state.timeline.map((item) => item.sequence)).toEqual([2, 1]);
    expect(state.snapshotAt).toBe(1_000);
  });

  test("a timeline entry already seen is never added twice", () => {
    let state = applyEnvelope(initialLiveData, envelope("snapshot", snapshot), 1_000);
    state = applyEnvelope(state, envelope("timeline.appended", entry(3)), 1_100);
    state = applyEnvelope(state, envelope("timeline.appended", entry(3)), 1_200);

    expect(state.timeline.map((item) => item.sequence)).toEqual([3, 2, 1]);
  });

  test("a report is filed under the camera named on the envelope", () => {
    let state = applyEnvelope(initialLiveData, envelope("snapshot", snapshot), 1_000);
    const report = { sequence: 1, status: "OBSERVE" } as never;
    state = applyEnvelope(state, envelope("oir.updated", report, "cam-02"), 1_100);

    expect(state.decisions["cam-02"]?.report).toBe(report);
    expect(state.decisions["cam-01"]?.report).toBeNull();
  });

  test("a state change updates only that camera's workflow phase", () => {
    let state = applyEnvelope(initialLiveData, envelope("snapshot", snapshot), 1_000);
    state = applyEnvelope(
      state,
      envelope("state.updated", {
        camera_id: "cam-01",
        operational_state: "INVESTIGATING",
        actor: "Asha",
      }),
      1_100,
    );

    expect(state.decisions["cam-01"]?.operational_state).toBe("INVESTIGATING");
    expect(state.decisions["cam-02"]).toBeUndefined();
  });

  test("a pushed assessment keeps zone flow the previous camera analysis carried", () => {
    let state = applyEnvelope(initialLiveData, envelope("snapshot", snapshot), 1_000);
    const zoneFlow = { camera_id: "cam-01", zones: [], transitions: [] } as never;
    state = applyEnvelope(
      state,
      envelope("camera.analysis", analysis("cam-01", 70, { zone_flow: zoneFlow })),
      1_100,
    );
    state = applyEnvelope(state, envelope("csi.updated", analysis("cam-01", 65)), 1_200);

    expect(state.analyses["cam-01"]?.stability.csi_smoothed).toBe(65);
    expect(state.analyses["cam-01"]?.zone_flow).toBe(zoneFlow);
  });

  test("trends are sampled, not appended on every message", () => {
    let state = applyEnvelope(initialLiveData, envelope("snapshot", snapshot), 0);
    state = applyEnvelope(state, envelope("camera.analysis", analysis("cam-01", 70)), 500);
    state = applyEnvelope(
      state,
      envelope("camera.analysis", analysis("cam-01", 60)),
      TREND_INTERVAL_MS + 1,
    );

    expect(state.trends["cam-01"]?.map((point) => point.csi)).toEqual([82, 60]);
  });

  test("a removed camera takes its analysis and trend with it", () => {
    let state = applyEnvelope(initialLiveData, envelope("snapshot", snapshot), 1_000);
    state = applyEnvelope(
      state,
      envelope("cameras.changed", {
        change: { camera_id: "cam-02", change: "removed" },
        cameras: [camera("cam-01", 0, true)],
      }),
      1_100,
    );

    expect(state.cameraOrder).toEqual(["cam-01"]);
    expect(state.analyses["cam-02"]).toBeUndefined();
    expect(state.trends["cam-02"]).toBeUndefined();
  });

  test("the REST fallback lands in the same state as the socket", () => {
    const state = applyFallback(
      initialLiveData,
      {
        cameras: [camera("cam-01", 0, true)],
        analyses: [analysis("cam-01", 77)],
        timeline: [entry(5), entry(4)],
      },
      2_000,
    );

    expect(state.primaryCameraId).toBe("cam-01");
    expect(state.analyses["cam-01"]?.stability.csi_smoothed).toBe(77);
    expect(state.timeline).toHaveLength(2);
  });
});

describe("queueTotal", () => {
  test("is missing - not zero - when no queue zone is configured", () => {
    expect(queueTotal(analysis("cam-01", 80))).toBeNull();
    expect(
      queueTotal(
        analysis("cam-01", 80, {
          queue: { frame_seq: 1, frame_ts: "", queues: [], unconfigured: true },
        }),
      ),
    ).toBeNull();
  });
});
