import { describe, expect, test } from "vitest";

import { INDICATOR_DEFAULT_WEIGHT } from "@/lib/labels";
import { createVenue, densityGrid, neckPressure, stabilityIndex, step } from "./venueSim";

const PRESSURES = {
  DENSITY_PRESSURE: 80,
  MOTION_SUPPRESSION: 40,
  EGRESS_CONGESTION: 20,
  FLOW_CONFLICT: 60,
  RATE_OF_CHANGE: 10,
};

describe("stabilityIndex", () => {
  test("matches the hand-computed CSI when every indicator is available", () => {
    // 0.35*80 + 0.20*40 + 0.20*20 + 0.15*60 + 0.10*10 = 50 -> CSI 50
    expect(stabilityIndex(PRESSURES, INDICATOR_DEFAULT_WEIGHT)).toBeCloseTo(50, 5);
  });

  test("renormalises the remaining weights when one indicator is unavailable", () => {
    // Remaining weight 0.90; renormalised sum = 0.35/.9*80 + 0.20/.9*40 + 0.20/.9*20 + 0.15/.9*60 = 54.444...
    const result = stabilityIndex(PRESSURES, INDICATOR_DEFAULT_WEIGHT, { RATE_OF_CHANGE: false });
    expect(result).toBeCloseTo(45.5556, 3);
  });

  test("clamps to 0-100", () => {
    expect(stabilityIndex({ ...PRESSURES, DENSITY_PRESSURE: 1000 }, INDICATOR_DEFAULT_WEIGHT)).toBe(0);
    const zero = { DENSITY_PRESSURE: 0, MOTION_SUPPRESSION: 0, EGRESS_CONGESTION: 0, FLOW_CONFLICT: 0, RATE_OF_CHANGE: 0 };
    expect(stabilityIndex(zero, INDICATOR_DEFAULT_WEIGHT)).toBe(100);
  });

  test("no available indicators reads as fully stable rather than dividing by zero", () => {
    expect(
      stabilityIndex(PRESSURES, INDICATOR_DEFAULT_WEIGHT, {
        DENSITY_PRESSURE: false,
        MOTION_SUPPRESSION: false,
        EGRESS_CONGESTION: false,
        FLOW_CONFLICT: false,
        RATE_OF_CHANGE: false,
      }),
    ).toBe(100);
  });
});

describe("createVenue", () => {
  test("is deterministic for a given seed", () => {
    expect(createVenue(7)).toEqual(createVenue(7));
  });

  test("different seeds produce different layouts", () => {
    expect(createVenue(1)).not.toEqual(createVenue(2));
  });
});

describe("step", () => {
  test("keeps agents within the venue bounds", () => {
    let state = createVenue(3);
    for (let i = 0; i < 60; i += 1) state = step(state, 1 / 30, () => 0);
    for (const agent of state.agents) {
      expect(agent.y).toBeGreaterThanOrEqual(20);
      expect(agent.y).toBeLessThanOrEqual(state.height - 20);
    }
  });
});

describe("densityGrid", () => {
  test("conserves the agent count across cells", () => {
    const state = createVenue(11);
    const grid = densityGrid(state);
    const total = grid.flat().reduce((sum, count) => sum + count, 0);
    expect(total).toBe(state.agents.length);
  });
});

describe("neckPressure", () => {
  test("stays within 0-100", () => {
    let state = createVenue(5);
    for (let i = 0; i < 30; i += 1) {
      state = step(state, 1 / 30, () => 0.05);
      const pressure = neckPressure(state);
      expect(pressure).toBeGreaterThanOrEqual(0);
      expect(pressure).toBeLessThanOrEqual(100);
    }
  });
});
