import { QueueNow } from "@/components/intel/QueueNow";
import { QueueForecast } from "@/components/intel/QueueForecast";
import { QueuePlan } from "@/components/intel/QueuePlan";
import { Panel, type PanelState } from "@/components/data/Panel";
import { EmptyState } from "@/components/data/EmptyState";
import { StaleBadge } from "@/components/status/StaleBadge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/ui/Tabs";
import type { CameraAnalysis } from "@/types/contracts";
import { useState } from "react";

export function QueueStrip({
  analysis,
  withheldReason = null,
  staleSeconds = null,
}: {
  analysis: CameraAnalysis | null | undefined;
  withheldReason?: string | null;
  staleSeconds?: number | null;
}) {
  const zones = analysis?.queue?.queues ?? [];
  const [activeZone, setActiveZone] = useState<string | undefined>(zones[0]?.zone_id);
  const zoneId = zones.some((z) => z.zone_id === activeZone) ? activeZone : zones[0]?.zone_id;

  let state: PanelState = "ready";
  if (withheldReason) state = "empty";
  else if (!analysis) state = "waiting";
  else if (analysis.queue?.unconfigured || zones.length === 0) state = "empty";
  else if (staleSeconds !== null) state = "stale";

  return (
    <Panel
      title="Queue intelligence"
      meta={staleSeconds !== null ? <StaleBadge isStale ageSeconds={staleSeconds} /> : undefined}
      state={state}
      stateMessage={withheldReason ?? "No queue zones are configured for this camera."}
    >
      {zones.length > 0 && (
        <Tabs value={zoneId} onValueChange={setActiveZone}>
          <TabsList>
            {zones.map((zone) => (
              <TabsTrigger key={zone.zone_id} value={zone.zone_id}>
                {zone.zone_name}
              </TabsTrigger>
            ))}
          </TabsList>
          {zones.map((zone) => {
            const forecast = analysis?.forecast?.forecasts.find((f) => f.zone_id === zone.zone_id);
            const plan = analysis?.resources?.plans.find((p) => p.zone_id === zone.zone_id);
            return (
              <TabsContent key={zone.zone_id} value={zone.zone_id} className="mt-4">
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
              </TabsContent>
            );
          })}
        </Tabs>
      )}
    </Panel>
  );
}
