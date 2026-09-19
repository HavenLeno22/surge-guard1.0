import { useMemo, useState } from "react";

import { TimelineList } from "@/components/intel/TimelineList";
import { Panel } from "@/components/data/Panel";
import { PageHeader } from "@/features/shell/PageHeader";
import { SITE_TIMELINE_ID } from "@/lib/labels";
import { useNow } from "@/lib/hooks/useNow";
import { useLive } from "@/realtime/store";
import { EvidenceHistory } from "./EvidenceHistory";
import { GuidanceHistory } from "./GuidanceHistory";
import { TimelineFilters, type TimelineFilterState } from "./TimelineFilters";

export function TimelinePage() {
  const timeline = useLive((state) => state.timeline);
  const cameras = useLive((state) => state.cameras);
  const cameraOrder = useLive((state) => state.cameraOrder);
  const now = useNow(5000);

  const [filters, setFilters] = useState<TimelineFilterState>({ type: "ALL", severity: "ALL", cameraId: "ALL" });

  const cameraOptions = [
    { value: SITE_TIMELINE_ID, label: "Site" },
    ...cameraOrder.map((id) => ({ value: id, label: cameras[id]?.name ?? id })),
  ];

  const filtered = useMemo(
    () =>
      timeline.filter(
        (entry) =>
          (filters.type === "ALL" || entry.entry_type === filters.type) &&
          (filters.severity === "ALL" || entry.severity === filters.severity) &&
          (filters.cameraId === "ALL" || entry.camera_id === filters.cameraId),
      ),
    [timeline, filters],
  );

  return (
    <div className="flex flex-col gap-5">
      <PageHeader title="Timeline" description="Every observation, status change, alert and operator action." />

      <div className="grid gap-5 lg:grid-cols-2">
        <GuidanceHistory />
        <EvidenceHistory />
      </div>

      <Panel title="Full timeline" actions={<TimelineFilters value={filters} onChange={setFilters} cameraOptions={cameraOptions} />} state={filtered.length === 0 ? "empty" : "ready"} stateMessage="No entries match these filters.">
        <TimelineList entries={filtered} now={now} />
      </Panel>
    </div>
  );
}
