import { useCallback, useRef, useState } from "react";
import type { MouseEvent, TouchEvent } from "react";

export interface ChartHover {
  index: number | null;
  x: number;
  y: number;
}

/** Nearest-point crosshair tracking for a chart's SVG, shared across chart types. */
export function useChartTooltip<T>(data: T[], xAccessor: (point: T, index: number) => number) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [hovered, setHovered] = useState<ChartHover>({ index: null, x: 0, y: 0 });

  const handleMove = useCallback(
    (clientX: number, clientY: number) => {
      const el = containerRef.current;
      if (!el || data.length === 0) return;
      const rect = el.getBoundingClientRect();
      const x = clientX - rect.left;
      let closest = 0;
      let closestDist = Number.POSITIVE_INFINITY;
      for (let i = 0; i < data.length; i += 1) {
        const point = data[i];
        if (point === undefined) continue;
        const dist = Math.abs(xAccessor(point, i) - x);
        if (dist < closestDist) {
          closestDist = dist;
          closest = i;
        }
      }
      setHovered({ index: closest, x, y: clientY - rect.top });
    },
    [data, xAccessor],
  );

  const handleLeave = useCallback(() => setHovered({ index: null, x: 0, y: 0 }), []);

  return {
    containerRef,
    hovered,
    handlers: {
      onMouseMove: (event: MouseEvent) => handleMove(event.clientX, event.clientY),
      onMouseLeave: handleLeave,
      onTouchMove: (event: TouchEvent) => {
        const touch = event.touches[0];
        if (touch) handleMove(touch.clientX, touch.clientY);
      },
      onTouchEnd: handleLeave,
    },
  };
}
