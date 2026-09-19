import { describe, expect, test } from "vitest";

import type { Camera, CameraConnectionStatus } from "@/types/contracts";

import { cameraFigures } from "./cameraFigures";
import type { TimedAnalysis } from "./reducers";

const NOW = 1_000_000;

function camera(status: CameraConnectionStatus): Camera {
  // Only the fields the rule reads; the rest of the contract is irrelevant here.
  return { camera_id: "cam-02", display_id: "CAM-02", name: "Queue Side View", status } as Camera;
}

function analysisReceived(secondsAgo: number): TimedAnalysis {
  return { camera_id: "cam-02", receivedAt: NOW - secondsAgo * 1000 } as TimedAnalysis;
}

describe("cameraFigures", () => {
  test("an offline camera shows no figures, even with a last analysis in the store", () => {
    const figures = cameraFigures(camera("OFFLINE"), analysisReceived(2), NOW, 30);
    expect(figures.analysis).toBeNull();
    expect(figures.withheldReason).toBe("Queue Side View is offline. Its figures are withheld until it reconnects.");
    expect(figures.staleSeconds).toBeNull();
  });

  test("a disabled camera says so", () => {
    const figures = cameraFigures(camera("DISABLED"), analysisReceived(2), NOW, 30);
    expect(figures.analysis).toBeNull();
    expect(figures.withheldReason).toContain("is disabled");
  });

  test("a recent analysis is shown as current", () => {
    const latest = analysisReceived(3);
    expect(cameraFigures(camera("ONLINE"), latest, NOW, 30)).toEqual({
      analysis: latest,
      withheldReason: null,
      staleSeconds: null,
    });
  });

  test("an analysis past the stale threshold is still shown, marked with its age", () => {
    const figures = cameraFigures(camera("RECOVERING"), analysisReceived(45), NOW, 30);
    expect(figures.analysis).not.toBeNull();
    expect(figures.staleSeconds).toBe(45);
  });

  test("no analysis yet is neither withheld nor stale", () => {
    expect(cameraFigures(camera("CONNECTING"), undefined, NOW, 30)).toEqual({
      analysis: null,
      withheldReason: null,
      staleSeconds: null,
    });
  });
});
