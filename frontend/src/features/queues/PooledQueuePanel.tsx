import { KeyValueList } from "@/components/data/KeyValueList";
import { Panel } from "@/components/data/Panel";
import { formatInteger, formatRate, formatWait } from "@/lib/format";
import { AGGREGATION_LABEL, RATE_SOURCE_LABEL } from "@/lib/labels";
import type { SiteQueueSummary } from "@/types/contracts";

export function PooledQueuePanel({
  summary,
  queueZonesConfigured,
  nameFor,
}: {
  summary: SiteQueueSummary | null;
  /** Some camera has a queue zone, so an absent summary means none of them is contributing right now. */
  queueZonesConfigured: boolean;
  nameFor: (cameraId: string) => string;
}) {
  return (
    <Panel
      title="Site-wide queue"
      state={summary ? "ready" : "empty"}
      stateMessage={
        queueZonesConfigured
          ? "No camera with a queue zone is contributing right now, so there is no site-wide queue."
          : "No queue zones are configured across the site."
      }
    >
      {summary && (
        <div className="flex flex-col gap-4">
          <div className="flex items-baseline gap-3">
            <span className="readout text-3xl text-ink-strong">{formatInteger(summary.queue_length)}</span>
            <span className="text-sm text-ink-muted">
              waiting{summary.upper_bound !== summary.queue_length ? ` (up to ${formatInteger(summary.upper_bound)})` : ""}
            </span>
          </div>
          <KeyValueList
            items={[
              { label: "Aggregation", value: AGGREGATION_LABEL[summary.aggregation] },
              { label: "Wait", value: formatWait(summary.wait_minutes, summary.queue_length) },
              { label: "Arrivals", value: formatRate(summary.arrival_rate_per_min) },
              { label: "Capacity", value: formatRate(summary.effective_capacity_per_min) },
              { label: "Counters", value: `${summary.active_counters} of ${summary.total_counters} open` },
              { label: "Rate basis", value: RATE_SOURCE_LABEL[summary.rate_source] },
            ]}
          />
          {summary.missing_camera_ids.length > 0 && (
            <p className="text-2xs text-ink-faint">
              Leaves out {summary.missing_camera_ids.map(nameFor).join(", ")}, which {summary.missing_camera_ids.length === 1 ? "is" : "are"} not contributing.
            </p>
          )}
        </div>
      )}
    </Panel>
  );
}
