import { Panel } from "@/components/data/Panel";
import { PageHeader } from "@/features/shell/PageHeader";
import { useLive } from "@/realtime/store";
import { FlowMap } from "./FlowMap";
import { HeadcountExplainer } from "./HeadcountExplainer";
import { HotspotPanel } from "./HotspotPanel";
import { PressureList } from "./PressureList";
import { SiteForecastPanel } from "./SiteForecastPanel";

export function SitePage() {
  const site = useLive((state) => state.site);
  const cameras = useLive((state) => state.cameras);

  return (
    <div className="flex flex-col gap-5">
      <PageHeader title="Site" description="Every camera, one picture of the venue." />

      <Panel title="Headcount" state={site ? "ready" : "waiting"}>
        {site && <HeadcountExplainer headcount={site.headcount} nameFor={(id) => cameras[id]?.name ?? id} />}
      </Panel>

      <Panel title="Flow map" state={site ? "ready" : "waiting"}>
        {site && <FlowMap nodes={site.flow_nodes} links={site.flow_links} />}
      </Panel>

      <div className="grid gap-5 lg:grid-cols-2">
        <Panel title="Hotspot" state={site ? "ready" : "waiting"}>
          {site && <HotspotPanel hotspot={site.hotspot} />}
        </Panel>
        <Panel title="Time to pressure" state={site ? "ready" : "waiting"}>
          {site && <PressureList items={site.time_to_pressure} />}
        </Panel>
      </div>

      <div className="grid gap-5 lg:grid-cols-2">
        <Panel title="Forecasts" state={site ? "ready" : "waiting"}>
          {site && (
            <div className="flex flex-col gap-5">
              <SiteForecastPanel title="Demand" forecast={site.demand_forecast} />
              <SiteForecastPanel title="Queue" forecast={site.queue_forecast} />
            </div>
          )}
        </Panel>
        <Panel
          title="Staffing plan"
          state={site ? (site.resource_plan ? "ready" : "empty") : "waiting"}
          stateMessage={site?.resource_plan_withheld_reason ?? "No staffing plan available."}
        >
          {site?.resource_plan && (
            <p className="text-sm text-ink">{site.resource_plan.rationale}</p>
          )}
        </Panel>
      </div>
    </div>
  );
}
