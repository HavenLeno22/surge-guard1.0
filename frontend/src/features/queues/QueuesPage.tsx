import { EmptyState } from "@/components/data/EmptyState";
import { PageHeader } from "@/features/shell/PageHeader";
import { useNow } from "@/lib/hooks/useNow";
import { cameraFigures } from "@/realtime/cameraFigures";
import { useLive } from "@/realtime/store";
import { PooledQueuePanel } from "./PooledQueuePanel";
import { QueueZoneCard } from "./QueueZoneCard";

export function QueuesPage() {
  const cameraOrder = useLive((state) => state.cameraOrder);
  const cameras = useLive((state) => state.cameras);
  const analyses = useLive((state) => state.analyses);
  const site = useLive((state) => state.site);
  const staleAfterSeconds = useLive((state) => state.link.staleAfterSeconds);
  const now = useNow(5000);

  const withheld: string[] = [];
  const cards = cameraOrder.flatMap((cameraId) => {
    const camera = cameras[cameraId];
    if (!camera) return [];
    const { analysis, withheldReason, staleSeconds } = cameraFigures(camera, analyses[cameraId], now, staleAfterSeconds);
    // An offline camera's queues are not shown with its last figures - listed below instead.
    if (withheldReason && camera.queue_zone_count > 0) withheld.push(withheldReason);
    if (!analysis?.queue || analysis.queue.unconfigured) return [];
    return analysis.queue.queues.map((metrics) => ({
      key: `${cameraId}:${metrics.zone_id}`,
      cameraName: camera.name,
      metrics,
      staleSeconds,
      forecast: analysis.forecast?.forecasts.find((f) => f.zone_id === metrics.zone_id),
      plan: analysis.resources?.plans.find((p) => p.zone_id === metrics.zone_id),
    }));
  });

  return (
    <div className="flex flex-col gap-5">
      <PageHeader title="Queues" description="Every queue zone: now, next, and what to do about it." />

      <PooledQueuePanel
        summary={site?.queue ?? null}
        queueZonesConfigured={cameraOrder.some((id) => (cameras[id]?.queue_zone_count ?? 0) > 0)}
        nameFor={(id) => cameras[id]?.name ?? id}
      />

      {withheld.length > 0 && (
        <ul className="flex flex-col gap-1 rounded-md border border-line bg-surface-1 px-4 py-3 text-sm text-ink-secondary">
          {withheld.map((reason) => (
            <li key={reason}>{reason}</li>
          ))}
        </ul>
      )}

      {cards.length === 0 ? (
        withheld.length === 0 && (
          <EmptyState title="No queue zones configured" description="Add a Queue zone to a camera to see it here." />
        )
      ) : (
        <div className="flex flex-col gap-5">
          {cards.map((card) => (
            <QueueZoneCard
              key={card.key}
              cameraName={card.cameraName}
              metrics={card.metrics}
              forecast={card.forecast}
              plan={card.plan}
              staleSeconds={card.staleSeconds}
            />
          ))}
        </div>
      )}
    </div>
  );
}
