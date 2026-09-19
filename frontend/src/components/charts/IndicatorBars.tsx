import type { IndicatorReading } from "@/types/contracts";
import { cn } from "@/lib/cn";
import { formatPercent } from "@/lib/format";
import { INDICATOR_LABEL, INDICATOR_ORDER } from "@/lib/labels";

/** The five stability pressures behind the Crowd Stability Index, weighted and ranked. */
export function IndicatorBars({ readings }: { readings: IndicatorReading[] }) {
  const byIndicator = new Map(readings.map((reading) => [reading.indicator, reading]));

  return (
    <div className="flex flex-col gap-3">
      {INDICATOR_ORDER.map((indicator) => {
        const reading = byIndicator.get(indicator);
        const available = reading?.available ?? false;
        const pressure = reading?.pressure ?? 0;
        const weight = reading?.weight ?? 0;

        return (
          <div key={indicator} className="flex flex-col gap-1">
            <div className="flex items-center justify-between text-xs">
              <span className={cn(available ? "text-ink-secondary" : "text-ink-faint")}>
                {INDICATOR_LABEL[indicator]}
              </span>
              <span className="text-ink-faint">weight {formatPercent(weight)}</span>
            </div>
            {available ? (
              <div className="h-1.5 w-full rounded-full bg-surface-3">
                <div
                  className="h-full rounded-full bg-ink-strong"
                  style={{ width: `${Math.min(Math.max(pressure, 0), 100)}%` }}
                />
              </div>
            ) : (
              <div className="hatch h-1.5 w-full rounded-full opacity-50" title={reading?.unavailable_reason ?? "Unavailable"} />
            )}
          </div>
        );
      })}
    </div>
  );
}
