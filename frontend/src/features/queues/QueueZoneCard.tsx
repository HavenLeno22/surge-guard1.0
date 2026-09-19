import { EmptyState } from "@/components/data/EmptyState";
import { Panel } from "@/components/data/Panel";
import { QueueForecast } from "@/components/intel/QueueForecast";
import { QueueNow } from "@/components/intel/QueueNow";
import { QueuePlan } from "@/components/intel/QueuePlan";
import { StaleBadge } from "@/components/status/StaleBadge";
import type { QueueForecast as QueueForecastData, QueueMetrics, ResourcePlan } from "@/types/contracts";

export function QueueZoneCard({
  cameraName,
  metrics,
  forecast,
  plan,
  staleSeconds = null,
}: {
  cameraName: string;
  staleSeconds?: number | null;
  metrics: QueueMetrics;
  forecast?: QueueForecastData;
  plan?: ResourcePlan;
}) {
  return (
    <Panel
      title={metrics.zone_name}
      meta={
        <span className="inline-flex items-center gap-2">
          {cameraName}
          {staleSeconds !== null && <StaleBadge isStale ageSeconds={staleSeconds} />}
        </span>
      }
      state={staleSeconds !== null ? "stale" : "ready"}
    >
      <div className="grid gap-5 lg:grid-cols-3">
        <section>
          <h3 className="mb-2 text-xs font-medium text-ink-faint">Now</h3>
          <QueueNow
            personCount={metrics.person_count}
            formation={metrics.formation}
            formationBasis={metrics.formation_basis}
            waitMinutes={metrics.wait.minutes}
            arrivalRate={metrics.flow.arrival_rate_per_min}
            serviceRate={metrics.flow.service_rate_per_min}
            rateSource={metrics.flow.rate_source}
          />
        </section>
        <section>
          <h3 className="mb-2 text-xs font-medium text-ink-faint">Next</h3>
          {forecast ? <QueueForecast forecast={forecast} /> : <EmptyState title="No forecast yet" />}
        </section>
        <section>
          <h3 className="mb-2 text-xs font-medium text-ink-faint">What to do</h3>
          {plan ? <QueuePlan plan={plan} /> : <EmptyState title="No plan available" />}
        </section>
      </div>
    </Panel>
  );
}
