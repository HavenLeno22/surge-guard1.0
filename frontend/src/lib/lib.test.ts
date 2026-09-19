import { describe, expect, test } from "vitest";

import {
  MISSING,
  formatAge,
  formatCsi,
  formatDensity,
  formatDuration,
  formatMinutes,
  formatPercent,
  formatRate,
  formatWait,
  secondsSince,
} from "./format";
import { countMethodLabel, INDICATOR_DEFAULT_WEIGHT, STATUS_LABEL } from "./labels";
import { RingBuffer } from "./ringBuffer";
import { STATUS_TONE, statusFromCsi, worstStatus } from "./status";

describe("Crowd Stability Index bands", () => {
  test("follow the frozen specification, with high values stable", () => {
    expect(statusFromCsi(100)).toBe("STABLE");
    expect(statusFromCsi(80)).toBe("STABLE");
    expect(statusFromCsi(79.9)).toBe("OBSERVE");
    expect(statusFromCsi(60)).toBe("OBSERVE");
    expect(statusFromCsi(40)).toBe("ATTENTION_REQUIRED");
    expect(statusFromCsi(20)).toBe("HIGH_ALERT");
    expect(statusFromCsi(19.99)).toBe("CRITICAL");
    expect(statusFromCsi(0)).toBe("CRITICAL");
  });

  test("clamp out-of-range values rather than leaving a display without a status", () => {
    expect(statusFromCsi(140)).toBe("STABLE");
    expect(statusFromCsi(-5)).toBe("CRITICAL");
  });

  test("every status has a label and a tone of its own", () => {
    expect(STATUS_LABEL.ATTENTION_REQUIRED).toBe("Attention Required");
    expect(new Set(Object.values(STATUS_TONE)).size).toBe(5);
  });

  test("the worst status wins, and nothing measured means no status", () => {
    expect(worstStatus(["STABLE", "HIGH_ALERT", null, "OBSERVE"])).toBe("HIGH_ALERT");
    expect(worstStatus([null, undefined])).toBeNull();
  });

  test("default weights sum to one, as the backend requires", () => {
    const total = Object.values(INDICATOR_DEFAULT_WEIGHT).reduce((sum, weight) => sum + weight, 0);
    expect(total).toBeCloseTo(1, 10);
  });
});

describe("measured values", () => {
  test("a missing measurement is shown as missing, never as zero", () => {
    expect(formatCsi(null)).toBe(MISSING);
    expect(formatRate(undefined)).toBe(MISSING);
    expect(formatPercent(Number.NaN)).toBe(MISSING);
    expect(formatCsi(0)).toBe("0");
  });

  test("relative density is never labelled per square metre", () => {
    expect(formatDensity(1.842, false)).toEqual({ value: "1.84", unit: "relative" });
    expect(formatDensity(1.842, true).unit).toBe("p/m²");
  });

  test("an unbounded wait reads as not draining, never as a number", () => {
    expect(formatWait(null, 12)).toBe("Not draining");
    expect(formatWait(null, 0)).toBe("No queue");
    expect(formatWait(0.4, 3)).toBe("<1 min");
    expect(formatWait(16.4, 30)).toBe("16 min");
  });

  test("estimated counts are named as estimates", () => {
    expect(countMethodLabel("ESTIMATED")).toBe("Estimated");
    expect(countMethodLabel("TRACKED")).toBe("Tracked");
  });

  test("durations and ages read naturally", () => {
    expect(formatMinutes(65)).toBe("1 h 5 min");
    expect(formatMinutes(120)).toBe("2 h");
    expect(formatDuration(45)).toBe("45 s");
    expect(formatDuration(7800)).toBe("2 h 10 min");
    expect(formatAge(1)).toBe("just now");
    expect(formatAge(12)).toBe("12 s ago");
  });

  test("seconds since a timestamp is never negative and tolerates bad input", () => {
    const now = Date.parse("2026-09-17T10:00:10Z");
    expect(secondsSince("2026-09-17T10:00:00Z", now)).toBe(10);
    expect(secondsSince("2026-09-17T10:00:20Z", now)).toBe(0);
    expect(secondsSince("not a date", now)).toBeNull();
  });
});

describe("RingBuffer", () => {
  test("keeps only the newest items, oldest first", () => {
    const buffer = new RingBuffer<number>(3);
    [1, 2, 3, 4, 5].forEach((value) => buffer.push(value));
    expect(buffer.toArray()).toEqual([3, 4, 5]);
    expect(buffer.last()).toBe(5);
    expect(buffer.size).toBe(3);
  });

  test("clears completely", () => {
    const buffer = new RingBuffer<string>(2);
    buffer.push("a");
    buffer.clear();
    expect(buffer.toArray()).toEqual([]);
    expect(buffer.last()).toBeUndefined();
  });
});
