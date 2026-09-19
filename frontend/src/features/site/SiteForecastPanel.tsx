import { QueueForecast } from "@/components/intel/QueueForecast";
import { EmptyState } from "@/components/data/EmptyState";
import type { SiteForecast } from "@/types/contracts";

export function SiteForecastPanel({ title, forecast }: { title: string; forecast: SiteForecast }) {
  return (
    <div className="flex flex-col gap-2">
      <h3 className="text-xs font-medium text-ink-faint">{title}</h3>
      {forecast.available && forecast.forecast ? (
        <>
          <QueueForecast forecast={forecast.forecast} />
          <p className="text-2xs text-ink-faint">{forecast.basis}</p>
        </>
      ) : (
        <EmptyState title="Withheld" description={forecast.withheld_reason ?? "Coverage is incomplete for this forecast."} />
      )}
    </div>
  );
}
