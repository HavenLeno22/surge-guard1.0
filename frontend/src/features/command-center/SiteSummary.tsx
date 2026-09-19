import { Link } from "react-router";

import { AlertCard } from "@/components/intel/AlertCard";
import { Panel } from "@/components/data/Panel";
import { StatBlock } from "@/components/data/StatBlock";
import { formatInteger } from "@/lib/format";
import { useLive } from "@/realtime/store";
import { Button } from "@/ui/Button";

export function SiteSummary() {
  const site = useLive((state) => state.site);
  const cameras = useLive((state) => state.cameras);

  return (
    <Panel
      title="Site"
      actions={
        <Button asChild size="sm" variant="ghost">
          <Link to="/site">View site</Link>
        </Button>
      }
      state={site ? "ready" : "waiting"}
    >
      {site && (
        <div className="flex flex-col gap-4">
          <div className="grid grid-cols-2 gap-4">
            <StatBlock
              label={site.headcount.label}
              value={site.headcount.value === null ? "—" : formatInteger(site.headcount.value)}
              detail={
                site.headcount.upper_bound !== null && site.headcount.upper_bound !== site.headcount.value
                  ? `Up to ${formatInteger(site.headcount.upper_bound)}`
                  : undefined
              }
            />
            <StatBlock
              label="Cameras contributing"
              value={`${site.cameras_contributing}/${site.cameras_total}`}
            />
          </div>
          {site.alerts.length > 0 ? (
            <div className="flex flex-col gap-2">
              {site.alerts.slice(0, 3).map((alert) => (
                <AlertCard
                  key={alert.alert_id}
                  alert={alert}
                  cameraName={alert.camera_id ? cameras[alert.camera_id]?.name : undefined}
                />
              ))}
              {site.alerts.length > 3 && (
                <Link to="/alerts" className="text-xs text-ink-muted hover:text-ink">
                  {site.alerts.length - 3} more alerts →
                </Link>
              )}
            </div>
          ) : (
            <p className="text-xs text-ink-faint">No active site alerts.</p>
          )}
        </div>
      )}
    </Panel>
  );
}
