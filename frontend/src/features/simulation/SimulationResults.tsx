import { scaleLinear } from "d3-scale";
import { line as d3line, curveMonotoneX } from "d3-shape";
import { useMemo } from "react";

import { useElementWidth } from "@/components/charts/useElementWidth";
import { QueueForecast } from "@/components/intel/QueueForecast";
import { QueuePlan } from "@/components/intel/QueuePlan";
import { QueueNow } from "@/components/intel/QueueNow";
import { EmptyState } from "@/components/data/EmptyState";
import { SimulationLabel } from "@/components/status/SimulationLabel";
import { TONE_HEX } from "@/lib/status";
import type { SimulationRead } from "@/types/contracts";

const HEIGHT = 180;
const MARGIN = { top: 8, right: 12, bottom: 22, left: 40 };

function SeriesChart({ series }: { series: { minute: number; queue_length: number }[] }) {
  const { ref, width } = useElementWidth(640);
  const chart = useMemo(() => {
    const maxMinute = Math.max(1, ...series.map((p) => p.minute));
    const maxQueue = Math.max(1, ...series.map((p) => p.queue_length));
    const x = scaleLinear().domain([0, maxMinute]).range([MARGIN.left, Math.max(MARGIN.left + 1, width - MARGIN.right)]);
    const y = scaleLinear().domain([0, maxQueue * 1.1]).nice().range([HEIGHT - MARGIN.bottom, MARGIN.top]);
    const path = d3line<(typeof series)[number]>()
      .x((p) => x(p.minute))
      .y((p) => y(p.queue_length))
      .curve(curveMonotoneX)(series);
    return { x, y, path };
  }, [series, width]);

  return (
    <div ref={ref} className="flex min-w-0 flex-col gap-1">
      <span className="text-xs text-ink-muted">Simulated queue length, people</span>
      <svg width={width} height={HEIGHT} className="block max-w-full">
        <title>Simulated queue length over the run, in people, by simulated minute</title>
        {chart.y.ticks(4).map((tick) => (
          <g key={tick}>
            <line x1={MARGIN.left} x2={width - MARGIN.right} y1={chart.y(tick)} y2={chart.y(tick)} stroke="var(--color-line)" />
            <text x={MARGIN.left - 6} y={chart.y(tick)} dy="0.32em" textAnchor="end" className="fill-ink-faint text-[10px] tabular">
              {tick}
            </text>
          </g>
        ))}
        {chart.x.ticks(6).map((minute, index, ticks) => (
          <text
            key={minute}
            x={chart.x(minute)}
            y={HEIGHT - 6}
            textAnchor={index === ticks.length - 1 ? "end" : "middle"}
            className="fill-ink-faint text-[10px] tabular"
          >
            {`${minute} min`}
          </text>
        ))}
        {chart.path && <path d={chart.path} fill="none" stroke={TONE_HEX.neutral} strokeWidth={1.75} />}
      </svg>
    </div>
  );
}

export function SimulationResults({ result }: { result: SimulationRead | null }) {
  if (!result) return <EmptyState title="No simulation run yet" description="Set the parameters and run one." />;

  const zone = result.queue.queues[0];
  const forecast = result.forecast.forecasts[0];
  const plan = result.resources.plans[0];

  return (
    <div className="flex flex-col gap-5">
      <SimulationLabel>Simulation result</SimulationLabel>
      <SeriesChart series={result.series} />
      {zone ? (
        <div className="grid gap-5 lg:grid-cols-3">
          <section>
            <h3 className="mb-2 text-xs font-medium text-ink-faint">Now</h3>
            <QueueNow
              personCount={zone.person_count}
              formation={zone.formation}
              formationBasis={zone.formation_basis}
              waitMinutes={zone.wait.minutes}
              arrivalRate={zone.flow.arrival_rate_per_min}
              serviceRate={zone.flow.service_rate_per_min}
              rateSource={zone.flow.rate_source}
              simulated
            />
          </section>
          <section>
            <h3 className="mb-2 text-xs font-medium text-ink-faint">Next</h3>
            {forecast ? <QueueForecast forecast={forecast} /> : <EmptyState title="No forecast" />}
          </section>
          <section>
            <h3 className="mb-2 text-xs font-medium text-ink-faint">What to do</h3>
            {plan ? <QueuePlan plan={plan} /> : <EmptyState title="No plan" />}
          </section>
        </div>
      ) : (
        <EmptyState title="No queue in this run" />
      )}
    </div>
  );
}
