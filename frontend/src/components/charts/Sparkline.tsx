import { extent } from "d3-array";
import { scaleLinear } from "d3-scale";
import { area as d3area, line as d3line, curveMonotoneX } from "d3-shape";
import { useId, useMemo } from "react";

import { TONE_HEX, type Tone } from "@/lib/status";

interface Point {
  index: number;
  value: number | null;
}

/** A minimal inline trend line - no axes by definition. For "this session" strips, not analysis. */
export function Sparkline({
  data,
  width = 120,
  height = 32,
  tone = "neutral",
  fill = false,
}: {
  data: (number | null)[];
  width?: number;
  height?: number;
  tone?: Tone;
  fill?: boolean;
}) {
  const gradientId = useId();
  const color = TONE_HEX[tone];

  const paths = useMemo(() => {
    const points: Point[] = data.map((value, index) => ({ index, value }));
    const values = points.map((p) => p.value).filter((v): v is number => v !== null);
    if (values.length < 2) return null;
    const [minValue, maxValue] = extent(values);
    const yDomain: [number, number] =
      minValue === maxValue ? [(minValue ?? 0) - 1, (maxValue ?? 0) + 1] : [minValue ?? 0, maxValue ?? 1];
    const x = scaleLinear().domain([0, data.length - 1]).range([1, width - 1]);
    const y = scaleLinear().domain(yDomain).range([height - 3, 3]);

    const line = d3line<Point>()
      .defined((p) => p.value !== null)
      .x((p) => x(p.index))
      .y((p) => y(p.value as number))
      .curve(curveMonotoneX)(points);

    const area = fill
      ? d3area<Point>()
          .defined((p) => p.value !== null)
          .x((p) => x(p.index))
          .y0(height)
          .y1((p) => y(p.value as number))
          .curve(curveMonotoneX)(points)
      : null;

    return { line, area };
  }, [data, width, height, fill]);

  if (!paths?.line) {
    return <svg width={width} height={height} role="presentation" aria-hidden="true" />;
  }

  return (
    <svg width={width} height={height} role="presentation" aria-hidden="true">
      {paths.area && (
        <defs>
          <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity="0.25" />
            <stop offset="100%" stopColor={color} stopOpacity="0" />
          </linearGradient>
        </defs>
      )}
      {paths.area && <path d={paths.area} fill={`url(#${gradientId})`} stroke="none" />}
      <path
        d={paths.line}
        fill="none"
        stroke={color}
        strokeWidth={1.5}
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </svg>
  );
}
