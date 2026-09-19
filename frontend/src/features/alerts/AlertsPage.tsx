import { Link } from "react-router";

import { AlertCard } from "@/components/intel/AlertCard";
import { EmptyState } from "@/components/data/EmptyState";
import { Panel } from "@/components/data/Panel";
import { PageHeader } from "@/features/shell/PageHeader";
import { formatAge } from "@/lib/format";
import { useNow } from "@/lib/hooks/useNow";
import { useLive } from "@/realtime/store";
import { Button } from "@/ui/Button";

export function AlertsPage() {
  const site = useLive((state) => state.site);
  const cameras = useLive((state) => state.cameras);
  const timeline = useLive((state) => state.timeline);
  const now = useNow(5000);

  const history = timeline.filter((entry) => entry.entry_type === "ALERT" || entry.entry_type === "STATUS_CHANGE");

  return (
    <div className="flex flex-col gap-5">
      <PageHeader title="Alerts" description="Active site alerts, and the history of when they were raised and resolved." />

      <Panel title="Active alerts" state={!site ? "waiting" : site.alerts.length === 0 ? "empty" : "ready"} stateMessage="No active site alerts.">
        {site && site.alerts.length > 0 && (
          <div className="flex flex-col gap-2">
            {site.alerts.map((alert) => (
              <AlertCard
                key={alert.alert_id}
                alert={alert}
                cameraName={alert.camera_id ? cameras[alert.camera_id]?.name : undefined}
              />
            ))}
          </div>
        )}
      </Panel>

      <Panel
        title="History"
        actions={
          <Button asChild size="sm" variant="ghost">
            <Link to="/timeline">Full timeline</Link>
          </Button>
        }
        state={history.length === 0 ? "empty" : "ready"}
      >
        {history.length === 0 ? (
          <EmptyState title="No alert history yet" />
        ) : (
          <ol className="flex flex-col divide-y divide-line">
            {history.slice(0, 30).map((entry) => (
              <li key={entry.entry_id} className="flex items-center justify-between gap-3 py-2 text-sm">
                <span className="text-ink">{entry.title}</span>
                <span className="text-2xs text-ink-faint">
                  {formatAge((now - new Date(entry.occurred_at).getTime()) / 1000)}
                </span>
              </li>
            ))}
          </ol>
        )}
      </Panel>
    </div>
  );
}
