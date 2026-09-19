import { Sparkline } from "@/components/charts/Sparkline";
import { Panel } from "@/components/data/Panel";
import { formatCsi, formatInteger } from "@/lib/format";
import { useLive } from "@/realtime/store";

/** Ring-buffered trends for this browser tab's session only - long range lives in /analytics. */
export function SessionTrends({
  cameraId,
  withheld = false,
}: {
  cameraId: string | null;
  /** The camera is offline or disabled: its session history stays drawn, but it has no current value. */
  withheld?: boolean;
}) {
  const trend = useLive((state) => (cameraId ? state.trends[cameraId] : undefined)) ?? [];
  const siteTrend = useLive((state) => state.siteTrend);

  const csiValues = trend.map((p) => p.csi);
  const peopleValues = trend.map((p) => p.people);
  const headcountValues = siteTrend.map((p) => p.headcount);

  const lastCsi = withheld ? null : (trend.at(-1)?.csi ?? null);
  const lastPeople = withheld ? null : (trend.at(-1)?.people ?? null);
  const lastHeadcount = siteTrend.at(-1)?.headcount ?? null;

  return (
    <Panel title="Session trends" meta="This session" state={trend.length > 1 || siteTrend.length > 1 ? "ready" : "empty"}>
      <div className="flex flex-col gap-4">
        <TrendRow label="CSI, this camera" value={lastCsi === null ? "—" : formatCsi(lastCsi)} data={csiValues} tone="neutral" />
        <TrendRow label="People, this camera" value={lastPeople === null ? "—" : formatInteger(lastPeople)} data={peopleValues} tone="neutral" />
        <TrendRow label="Site headcount" value={lastHeadcount === null ? "—" : formatInteger(lastHeadcount)} data={headcountValues} tone="neutral" />
      </div>
    </Panel>
  );
}

function TrendRow({
  label,
  value,
  data,
  tone,
}: {
  label: string;
  value: string;
  data: (number | null)[];
  tone: "stable" | "observe" | "neutral";
}) {
  return (
    <div className="flex items-center justify-between gap-3">
      <div>
        <p className="text-xs text-ink-faint">{label}</p>
        <p className="readout text-lg text-ink-strong">{value}</p>
      </div>
      <Sparkline data={data} tone={tone} fill />
    </div>
  );
}
