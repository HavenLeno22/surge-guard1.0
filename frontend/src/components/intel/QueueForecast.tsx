import type { QueueForecast as QueueForecastData } from "@/types/contracts";
import { ForecastFan } from "@/components/charts/ForecastFan";
import { GROWTH_LABEL } from "@/lib/labels";
import { Badge } from "@/ui/Badge";

const GROWTH_TONE = {
  STABLE: "neutral",
  SHRINKING: "stable",
  GROWING: "attention",
  ABNORMAL_GROWTH: "critical",
  INSUFFICIENT_HISTORY: "muted",
} as const;

/** What the queue is expected to do next: both forecast methods, their consensus, and why. */
export function QueueForecast({ forecast }: { forecast: QueueForecastData }) {
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <span className="text-sm text-ink-secondary">{forecast.zone_name}</span>
        <Badge tone={GROWTH_TONE[forecast.growth.pattern]}>{GROWTH_LABEL[forecast.growth.pattern]}</Badge>
      </div>
      <ForecastFan forecast={forecast} />
    </div>
  );
}
