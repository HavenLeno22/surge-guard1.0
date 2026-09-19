/**
 * Coordinate transforms and hit-testing for the zone editor.
 *
 * Zones are stored in analysis-resolution image space (`metrics.analysis_width
 * /height`, default 960x540 - the snapshot JPEG is exactly that size, since
 * frames are resized before analysis). The editor's container is always given
 * that same aspect ratio via CSS, so the image-to-screen transform is a plain
 * uniform scale - no letterboxing math is needed.
 */

export interface Size {
  width: number;
  height: number;
}

export interface Point {
  x: number;
  y: number;
}

export function imageToScreen(point: Point, imageSize: Size, displaySize: Size): Point {
  return {
    x: (point.x / imageSize.width) * displaySize.width,
    y: (point.y / imageSize.height) * displaySize.height,
  };
}

export function screenToImage(point: Point, imageSize: Size, displaySize: Size): Point {
  return {
    x: (point.x / displaySize.width) * imageSize.width,
    y: (point.y / displaySize.height) * imageSize.height,
  };
}

export function clampToImage(point: Point, imageSize: Size): Point {
  return {
    x: Math.min(Math.max(point.x, 0), imageSize.width),
    y: Math.min(Math.max(point.y, 0), imageSize.height),
  };
}

export function distance(a: Point, b: Point): number {
  return Math.hypot(a.x - b.x, a.y - b.y);
}

/** Ray casting: is `point` inside the closed `polygon`? */
export function pointInPolygon(point: Point, polygon: Point[]): boolean {
  let inside = false;
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
    const pi = polygon[i] as Point;
    const pj = polygon[j] as Point;
    const intersects =
      pi.y > point.y !== pj.y > point.y &&
      point.x < ((pj.x - pi.x) * (point.y - pi.y)) / (pj.y - pi.y) + pi.x;
    if (intersects) inside = !inside;
  }
  return inside;
}

/** The nearest vertex within `radius` (image-space units), or null. */
export function hitTestVertex(point: Point, polygon: Point[], radius: number): number | null {
  let best: number | null = null;
  let bestDist = radius;
  polygon.forEach((vertex, index) => {
    const d = distance(point, vertex);
    if (d <= bestDist) {
      bestDist = d;
      best = index;
    }
  });
  return best;
}

function distanceToSegment(point: Point, a: Point, b: Point): number {
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  const lengthSquared = dx * dx + dy * dy;
  if (lengthSquared === 0) return distance(point, a);
  let t = ((point.x - a.x) * dx + (point.y - a.y) * dy) / lengthSquared;
  t = Math.min(Math.max(t, 0), 1);
  return distance(point, { x: a.x + t * dx, y: a.y + t * dy });
}

/** The closed polygon edge nearest `point`, within `radius` - for inserting a vertex there. */
export function hitTestEdge(point: Point, polygon: Point[], radius: number): number | null {
  let best: number | null = null;
  let bestDist = radius;
  for (let i = 0; i < polygon.length; i += 1) {
    const a = polygon[i] as Point;
    const b = polygon[(i + 1) % polygon.length] as Point;
    const d = distanceToSegment(point, a, b);
    if (d <= bestDist) {
      bestDist = d;
      best = i;
    }
  }
  return best;
}

export function isValidPolygon(polygon: Point[]): boolean {
  return polygon.length >= 3;
}

const ZONE_ID_PATTERN = /^[a-z0-9][a-z0-9-]{1,63}$/;

export function isValidZoneId(id: string): boolean {
  return ZONE_ID_PATTERN.test(id);
}
