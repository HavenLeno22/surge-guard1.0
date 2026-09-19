import { extent } from "d3-array";
import { scaleLinear, scaleTime } from "d3-scale";
import { area as d3area, line as d3line, curveMonotoneX } from "d3-shape";
import { useMemo, useState } from "react";

import { DataTable, type DataTableColumn } from "@/components/data/DataTable";
import { formatDate, formatDateTime, formatShortClock } from "@/lib/format";
import { cn } from "@/lib/cn";
import { TONE_HEX, type Tone } from "@/lib/status";
import { Button } from "@/ui/Button";
import { useChartTooltip } from "./useChartTooltip";
import { useElementWidth } from "./useElementWidth";

export interface TimeSeriesLine {
  key: string;
  label: string;
  tone: Tone;
  /** Dashed lines tell two series of one tone apart without spending another colour. */
  dashed?: boolean;
  values: (number | null)[];
}

const HEIGHT = 200;
const MARGIN = { top: 10, right: 12, bottom: 24, left: 38 };
const HOUR_MS = 3_600_000;

export function TimeSeries({
  t,
  series,
  band,
  xDomain,
  yDomain,
  yTicks,
  valueFormat = (value) => value.toFixed(0),
  label,
  emptyMessage = "No data in this range.",
  className,
}: {
  /** Epoch ms per sample, aligned with each series' `values`. */
  t: number[];
  series: TimeSeriesLine[];
  /** An optional min-max band (e.g. CSI mean with range) drawn behind the lines. */
  band?: { low: (number | null)[]; high: (number | null)[]; tone: Tone };
  /** The requested window (epoch ms). Without it the axis spans the data, hiding gaps at either end. */
  xDomain?: [number, number];
  /** A fixed scale, for measures with a natural range such as CSI 0-100. */
  yDomain?: [number, number];
  yTicks?: number[];
  valueFormat?: (value: number) => string;
  /** Accessible name for the chart. */
  label: string;
  /** Shown when the range has samples but none carry this measure. */
  emptyMessage?: string;
  className?: string;
}) {
  const [showTable, setShowTable] = useState(false);
  const { ref: measureRef, width } = useElementWidth(600);

  const scales = useMemo(() => {
    const [minT, maxT] = xDomain ?? extent(t);
    const x = scaleTime()
      .domain([new Date(minT ?? 0), new Date(maxT ?? 0)])
      .range([MARGIN.left, Math.max(MARGIN.left + 1, width - MARGIN.right)]);

    let domain = yDomain;
    if (!domain) {
      const allValues = [
        ...series.flatMap((s) => s.values),
        ...(band ? [...band.low, ...band.high] : []),
      ].filter((v): v is number => v !== null);
      const [minValue, maxValue] = extent(allValues);
      const lo = minValue ?? 0;
      const hi = maxValue ?? 1;
      const pad = (hi - lo) * 0.12 || 1;
      // Counts, lengths and waits are never negative: do not invent a negative axis.
      domain = [lo >= 0 ? Math.max(0, lo - pad) : lo - pad, hi + pad];
    }
    const y = scaleLinear().domain(domain).range([HEIGHT - MARGIN.bottom, MARGIN.top]);
    return { x, y };
  }, [t, series, band, xDomain, yDomain, width]);

  const xPositions = useMemo(() => t.map((ms) => scales.x(new Date(ms))), [t, scales]);
  const { containerRef, hovered, handlers } = useChartTooltip(xPositions, (position) => position);

  const [domainStart, domainEnd] = scales.x.domain();
  const spanMs = (domainEnd?.getTime() ?? 0) - (domainStart?.getTime() ?? 0);
  const tickLabel = spanMs > 48 * HOUR_MS ? formatDate : formatShortClock;
  const pointLabel = spanMs > 12 * HOUR_MS ? formatDateTime : formatShortClock;

  const hasValues = series.some((s) => s.values.some((v) => v !== null));

  if (t.length === 0 || !hasValues) {
    return <p className="text-xs text-ink-muted">{emptyMessage}</p>;
  }

  const valueTicks = yTicks ?? scales.y.ticks(4);
  const timeTicks = scales.x.ticks(Math.max(2, Math.floor((width - MARGIN.left - MARGIN.right) / 110)));

  return (
    <div ref={measureRef} className={cn("flex min-w-0 flex-col gap-2", className)}>
      <div className="flex items-center justify-between">
        {series.length > 1 ? (
          <div className="flex flex-wrap gap-x-3 gap-y-1 text-2xs text-ink-muted">
            {series.map((s) => (
              <span key={s.key} className="inline-flex items-center gap-1.5">
                <svg width="14" height="6" aria-hidden="true">
                  <line
                    x1="0"
                    x2="14"
                    y1="3"
                    y2="3"
                    stroke={TONE_HEX[s.tone]}
                    strokeWidth={1.75}
                    strokeDasharray={s.dashed ? "3 2" : undefined}
                  />
                </svg>
                {s.label}
              </span>
            ))}
          </div>
        ) : (
          <span />
        )}
        <Button size="sm" variant="ghost" onClick={() => setShowTable((v) => !v)}>
          {showTable ? "Show chart" : "Show as table"}
        </Button>
      </div>

      {showTable ? (
        <DataTable
          getRowKey={(row) => String(row.t)}
          rows={t.map((ms, index) => ({
            t: ms,
            ...Object.fromEntries(series.map((s) => [s.key, s.values[index] ?? null])),
          }))}
          columns={[
            { key: "t", header: "Time", cell: (row) => pointLabel(row.t) },
            ...series.map(
              (s): DataTableColumn<Record<string, number | null>> => ({
                key: s.key,
                header: s.label,
                cell: (row) => (row[s.key] === null ? "—" : valueFormat(row[s.key] as number)),
              }),
            ),
          ]}
        />
      ) : (
        <div ref={containerRef} className="relative select-none" {...handlers}>
          <svg width={width} height={HEIGHT} className="block max-w-full">
            <title>{label}</title>
            {valueTicks.map((tick) => (
              <g key={tick}>
                <line
                  x1={MARGIN.left}
                  x2={width - MARGIN.right}
                  y1={scales.y(tick)}
                  y2={scales.y(tick)}
                  stroke="var(--color-line)"
                  strokeWidth={1}
                />
                <text x={MARGIN.left - 8} y={scales.y(tick)} textAnchor="end" dy="0.32em" className="fill-ink-faint text-[10px] tabular">
                  {valueFormat(tick)}
                </text>
              </g>
            ))}

            {timeTicks.map((tick) => (
              <text
                key={tick.getTime()}
                x={scales.x(tick)}
                y={HEIGHT - 6}
                textAnchor="middle"
                className="fill-ink-faint text-[10px] tabular"
              >
                {tickLabel(tick)}
              </text>
            ))}

            {band &&
              (() => {
                const points = t.map((ms, index) => ({
                  x: scales.x(new Date(ms)),
                  low: band.low[index] ?? null,
                  high: band.high[index] ?? null,
                }));
                const areaPath = d3area<(typeof points)[number]>()
                  .defined((p) => p.low !== null && p.high !== null)
                  .x((p) => p.x)
                  .y0((p) => scales.y(p.low as number))
                  .y1((p) => scales.y(p.high as number))
                  .curve(curveMonotoneX)(points);
                return areaPath ? (
                  <path d={areaPath} fill={TONE_HEX[band.tone]} opacity={0.14} stroke="none" />
                ) : null;
              })()}

            {series.map((s) => {
              const points = t.map((ms, index) => ({ x: scales.x(new Date(ms)), value: s.values[index] ?? null }));
              const path = d3line<(typeof points)[number]>()
                .defined((p) => p.value !== null)
                .x((p) => p.x)
                .y((p) => scales.y(p.value as number))
                .curve(curveMonotoneX)(points);
              return path ? (
                <path
                  key={s.key}
                  d={path}
                  fill="none"
                  stroke={TONE_HEX[s.tone]}
                  strokeWidth={1.75}
                  strokeDasharray={s.dashed ? "4 3" : undefined}
                />
              ) : null;
            })}

            {hovered.index !== null && (
              <line
                x1={xPositions[hovered.index]}
                x2={xPositions[hovered.index]}
                y1={MARGIN.top}
                y2={HEIGHT - MARGIN.bottom}
                stroke="var(--color-line-strong)"
                strokeWidth={1}
              />
            )}
            {hovered.index !== null &&
              series.map((s) => {
                const value = s.values[hovered.index as number];
                if (value === null || value === undefined) return null;
                return (
                  <circle
                    key={s.key}
                    cx={xPositions[hovered.index as number]}
                    cy={scales.y(value)}
                    r={3}
                    fill={TONE_HEX[s.tone]}
                  />
                );
              })}
          </svg>
          {hovered.index !== null && t[hovered.index] !== undefined && (
            <div
              className="pointer-events-none absolute z-10 -translate-x-1/2 rounded-sm border border-line-strong bg-surface-3 px-2 py-1.5 text-2xs whitespace-nowrap text-ink shadow-overlay"
              style={{
                left: Math.min(Math.max(xPositions[hovered.index] ?? hovered.x, 70), width - 70),
                top: 0,
              }}
            >
              <div className="mb-0.5 text-ink-faint">{pointLabel(t[hovered.index as number])}</div>
              {series.map((s) => {
                const value = s.values[hovered.index as number];
                return (
                  <div key={s.key} className="flex items-center gap-1.5 tabular">
                    <span className="size-1.5 rounded-full" style={{ backgroundColor: TONE_HEX[s.tone] }} />
                    {s.label}: {value === null || value === undefined ? "—" : valueFormat(value)}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
