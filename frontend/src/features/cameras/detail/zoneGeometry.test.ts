import { describe, expect, test } from "vitest";

import {
  hitTestEdge,
  hitTestVertex,
  imageToScreen,
  isValidPolygon,
  isValidZoneId,
  pointInPolygon,
  screenToImage,
} from "./zoneGeometry";

const IMAGE_SIZE = { width: 960, height: 540 };
const DISPLAY_SIZE = { width: 480, height: 270 }; // exactly half, same aspect ratio

const SQUARE = [
  { x: 100, y: 100 },
  { x: 200, y: 100 },
  { x: 200, y: 200 },
  { x: 100, y: 200 },
];

describe("imageToScreen / screenToImage", () => {
  test("scale uniformly and invert each other", () => {
    const screen = imageToScreen({ x: 960, y: 540 }, IMAGE_SIZE, DISPLAY_SIZE);
    expect(screen).toEqual({ x: 480, y: 270 });
    expect(screenToImage(screen, IMAGE_SIZE, DISPLAY_SIZE)).toEqual({ x: 960, y: 540 });
  });
});

describe("pointInPolygon", () => {
  test("is true for a point inside a square and false outside", () => {
    expect(pointInPolygon({ x: 150, y: 150 }, SQUARE)).toBe(true);
    expect(pointInPolygon({ x: 50, y: 50 }, SQUARE)).toBe(false);
    expect(pointInPolygon({ x: 250, y: 150 }, SQUARE)).toBe(false);
  });
});

describe("hitTestVertex", () => {
  test("finds the nearest vertex within the radius", () => {
    expect(hitTestVertex({ x: 102, y: 98 }, SQUARE, 10)).toBe(0);
    expect(hitTestVertex({ x: 198, y: 202 }, SQUARE, 10)).toBe(2);
  });

  test("returns null when nothing is close enough", () => {
    expect(hitTestVertex({ x: 150, y: 150 }, SQUARE, 10)).toBeNull();
  });
});

describe("hitTestEdge", () => {
  test("finds the nearest edge within the radius", () => {
    // Midpoint of the top edge (0 -> 1)
    expect(hitTestEdge({ x: 150, y: 101 }, SQUARE, 10)).toBe(0);
    // Midpoint of the left edge (3 -> 0)
    expect(hitTestEdge({ x: 101, y: 150 }, SQUARE, 10)).toBe(3);
  });

  test("returns null far from every edge", () => {
    expect(hitTestEdge({ x: 150, y: 150 }, SQUARE, 10)).toBeNull();
  });
});

describe("isValidPolygon", () => {
  test("requires at least three points", () => {
    expect(isValidPolygon(SQUARE)).toBe(true);
    expect(isValidPolygon(SQUARE.slice(0, 2))).toBe(false);
  });
});

describe("isValidZoneId", () => {
  test("accepts lowercase slugs and rejects the rest", () => {
    expect(isValidZoneId("west-exit")).toBe(true);
    expect(isValidZoneId("zone1")).toBe(true);
    expect(isValidZoneId("a")).toBe(false); // too short (min 2 chars)
    expect(isValidZoneId("West Exit")).toBe(false);
    expect(isValidZoneId("-leading-hyphen")).toBe(false);
  });
});
