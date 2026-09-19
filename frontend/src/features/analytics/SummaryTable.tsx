import { DataTable, type DataTableColumn } from "@/components/data/DataTable";
import { formatCsi, formatDuration, formatInteger, formatMinutes, formatPercent } from "@/lib/format";
import type { HistorySummaryItem } from "@/types/history";
import { Badge } from "@/ui/Badge";

function BaselineBadge({ available, learningTitle }: { available: boolean; learningTitle?: string }) {
  // Not an Operational Status, so it never borrows a status colour.
  if (available) return <Badge tone="neutral">Available</Badge>;
  return (
    <span title={learningTitle}>
      <Badge tone="muted">Learning</Badge>
    </span>
  );
}

function summaryColumns(
  nameFor: (id: string) => string,
  baselineMinSamples: number | null,
): DataTableColumn<HistorySummaryItem>[] {
  const learningTitle =
    baselineMinSamples === null ? undefined : `A baseline needs at least ${baselineMinSamples} recorded buckets`;
  return [
    { key: "camera", header: "Camera", cell: (item) => nameFor(item.camera_id) },
    { key: "observed", header: "Observed", cell: (item) => formatDuration(item.observed_seconds) },
    {
      key: "baseline",
      header: "Baseline",
      cell: (item) => <BaselineBadge available={item.baseline_available} learningTitle={learningTitle} />,
    },
    { key: "csi", header: "CSI mean / min", cell: (item) => `${formatCsi(item.csi_mean)} / ${formatCsi(item.csi_min)}` },
    { key: "people", header: "People mean / max", cell: (item) => `${formatInteger(item.people_mean)} / ${formatInteger(item.people_max)}` },
    { key: "queue", header: "Queue max", cell: (item) => formatInteger(item.queue_length_max) },
    { key: "wait", header: "Wait max", cell: (item) => formatMinutes(item.wait_minutes_max) },
    { key: "estimated", header: "Estimated counts", cell: (item) => formatPercent(item.estimated_share) },
  ];
}

export function SummaryTable({
  items,
  nameFor,
  baselineMinSamples,
}: {
  items: HistorySummaryItem[];
  nameFor: (id: string) => string;
  baselineMinSamples: number | null;
}) {
  return (
    <DataTable
      getRowKey={(item) => item.camera_id}
      rows={items}
      emptyMessage="No history recorded in this range yet."
      columns={summaryColumns(nameFor, baselineMinSamples)}
    />
  );
}
