import { scaleLinear } from "d3-scale";
import { area as d3area, line as d3line, curveMonotoneX } from "d3-shape";
import { useMemo } from "react";

import type { ForecastMethod, QueueForecast } from "@/types/contracts";
import { formatInteger, formatPercent } from "@/lib/format";
import { FORECAST_METHOD_LABEL } from "@/lib/labels";
import { TONE_HEX } from "@/lib/status";
import { useElementWidth } from "./useElementWidth";

const HEIGHT = 150;
const MARGIN = { top: 8, right: 10, bottom: 22, left: 30 };

/**
 * Methods are told apart by stroke, not hue: forecasts are not Operational
 * Statuses, so they never borrow a status colour.
 */
const METHOD_STROKE: Record<ForecastMethod, { color: string; width: number; dash?: string }> = {
  CONSENSUS: { color: TONE_HEX.neutral, width: 2 },
  TREND: { color: TONE_HEX.muted, width: 1.25, dash: "4 3" },
  FLOW_BALANCE: { color: TONE_HEX.muted, width: 1.25, dash: "1 3" },
};

function MethodSwatch({ method }: { method: ForecastMethod }) {
  const stroke = METHOD_STROKE[method];
  return (
    <svg width="16" height="6" aria-hidden="true">
      <line x1="0" x2="16" y1="3" y2="3" stroke={stroke.color} strokeWidth={stroke.width} strokeDasharray={stroke.dash} strokeLinecap="round" />
    </svg>
  );
}

/** Queue length forecast, both methods plus their consensus and its confidence band. */
export function ForecastFan({ forecast }: { forecast: QueueForecast }) {
  const { ref: measureRef, width } = useElementWidth(320);
  const drawn = forecast.methods.filter((method) => method.points.length > 0);
  const withheld = forecast.methods.filter((method) => method.points.length === 0);

  const scales = useMemo(() => {
    // Only what is drawn sets the scale: the consensus band, and each method's expected line.
    const allValues = [
      forecast.current_length,
      ...forecast.methods.flatMap((m) =>
        m.points.flatMap((p) => (m.method === "CONSENSUS" ? [p.expected, p.lower, p.upper] : [p.expected])),
      ),
    ];
    const maxHorizon = Math.max(5, ...forecast.methods.flatMap((m) => m.points.map((p) => p.horizon_minutes)));
    const maxValue = Math.max(1, ...allValues);
    const x = scaleLinear().domain([0, maxHorizon]).range([MARGIN.left, Math.max(MARGIN.left + 1, width - MARGIN.right)]);
    const y = scaleLinear().domain([0, maxValue * 1.15]).nice().range([HEIGHT - MARGIN.bottom, MARGIN.top]);
    return { x, y };
  }, [forecast, width]);

  return (
    <div ref={measureRef} className="flex min-w-0 flex-col gap-2">
      {drawn.length > 0 && (
        <svg width={width} height={HEIGHT} className="block max-w-full">
          <title>{`Forecast queue length for ${forecast.zone_name}, in people, over the next ${scales.x.domain()[1]} minutes`}</title>
          {scales.y.ticks(3).map((tick) => (
            <g key={tick}>
              <line x1={MARGIN.left} x2={width - MARGIN.right} y1={scales.y(tick)} y2={scales.y(tick)} stroke="var(--color-line)" />
              <text x={MARGIN.left - 6} y={scales.y(tick)} dy="0.32em" textAnchor="end" className="fill-ink-faint text-[10px] tabular">
                {tick}
              </text>
            </g>
          ))}
          {scales.x.ticks(4).map((minute, index, ticks) => (
            <text
              key={minute}
              x={scales.x(minute)}
              y={HEIGHT - 6}
              textAnchor={index === 0 ? "start" : index === ticks.length - 1 ? "end" : "middle"}
              className="fill-ink-faint text-[10px] tabular"
            >
              {minute === 0 ? "Now" : `+${minute} min`}
            </text>
          ))}
          {drawn.map((method) => {
            const points = [
              { minute: 0, expected: forecast.current_length, lower: forecast.current_length, upper: forecast.current_length },
              ...method.points.map((p) => ({ minute: p.horizon_minutes, expected: p.expected, lower: p.lower, upper: p.upper })),
            ];
            const stroke = METHOD_STROKE[method.method];
            const bandPath =
              method.method === "CONSENSUS"
                ? d3area<(typeof points)[number]>()
                    .x((p) => scales.x(p.minute))
                    .y0((p) => scales.y(p.lower))
                    .y1((p) => scales.y(p.upper))
                    .curve(curveMonotoneX)(points)
                : null;
            const linePath = d3line<(typeof points)[number]>()
              .x((p) => scales.x(p.minute))
              .y((p) => scales.y(p.expected))
              .curve(curveMonotoneX)(points);
            return (
              <g key={method.method}>
                {bandPath && <path d={bandPath} fill={stroke.color} opacity={0.12} stroke="none" />}
                {linePath && (
                  <path
                    d={linePath}
                    fill="none"
                    stroke={stroke.color}
                    strokeWidth={stroke.width}
                    strokeDasharray={stroke.dash}
                    strokeLinecap="round"
                  />
                )}
              </g>
            );
          })}
        </svg>
      )}

      {drawn.length > 0 && (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-2xs text-ink-muted">
          {drawn.map((method) => (
            <span key={method.method} className="inline-flex items-center gap-1.5">
              <MethodSwatch method={method.method} />
              {FORECAST_METHOD_LABEL[method.method]}
            </span>
          ))}
          {forecast.method_agreement !== null && (
            <span className="text-ink-faint">Methods agree {formatPercent(forecast.method_agreement)}</span>
          )}
        </div>
      )}

      {withheld.length > 0 && (
        <ul className="flex flex-col gap-0.5 text-2xs text-ink-faint">
          {withheld.map((method) => (
            <li key={method.method}>
              <span className="text-ink-muted">{FORECAST_METHOD_LABEL[method.method]}:</span>{" "}
              {method.unavailable_reason ?? "not available for this window."}
            </li>
          ))}
        </ul>
      )}

      <p className="text-xs text-ink-muted">
        <span className="tabular text-ink">{formatInteger(forecast.current_length)}</span> in the queue now.{" "}
        {forecast.growth.explanation}
      </p>
    </div>
  );
}
