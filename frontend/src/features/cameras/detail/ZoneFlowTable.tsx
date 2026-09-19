import { DataTable } from "@/components/data/DataTable";
import { formatInteger, formatRate } from "@/lib/format";
import { ZONE_TYPE_LABEL } from "@/lib/labels";
import type { ZoneFlowReport } from "@/types/contracts";

export function ZoneFlowTable({ report }: { report: ZoneFlowReport | null | undefined }) {
  if (!report || report.zones.length === 0) {
    return <p className="text-xs text-ink-faint">No zone flow data yet.</p>;
  }

  return (
    <DataTable
      getRowKey={(zone) => zone.zone_id}
      rows={report.zones}
      columns={[
        { key: "name", header: "Zone", cell: (zone) => zone.zone_name },
        { key: "type", header: "Type", cell: (zone) => ZONE_TYPE_LABEL[zone.zone_type] },
        { key: "occupancy", header: "Occupancy", cell: (zone) => formatInteger(zone.occupancy) },
        { key: "entries", header: "Entries", cell: (zone) => formatRate(zone.entry_rate_per_min) },
        { key: "exits", header: "Exits", cell: (zone) => formatRate(zone.exit_rate_per_min) },
      ]}
    />
  );
}
