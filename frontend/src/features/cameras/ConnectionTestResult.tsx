import { KeyValueList } from "@/components/data/KeyValueList";
import { formatDuration, formatFps, formatMs } from "@/lib/format";
import { STREAM_OUTCOME_LABEL } from "@/lib/labels";
import type { ConnectionTestRead } from "@/types/contracts";
import { Badge } from "@/ui/Badge";

export function ConnectionTestResult({ result }: { result: ConnectionTestRead }) {
  return (
    <div className="flex flex-col gap-3 rounded-control border border-line bg-surface-2/60 p-3">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium text-ink">{STREAM_OUTCOME_LABEL[result.outcome]}</span>
        <Badge tone={result.success ? "stable" : "critical"}>{result.success ? "Reachable" : "Failed"}</Badge>
      </div>
      <p className="text-xs text-ink-muted">{result.detail}</p>
      <KeyValueList
        items={[
          { label: "Resolution", value: result.width && result.height ? `${result.width}×${result.height}` : "—" },
          { label: "Reported fps", value: formatFps(result.reported_fps) },
          { label: "Measured fps", value: formatFps(result.measured_fps) },
          { label: "First frame", value: formatMs(result.first_frame_ms) },
          { label: "Frames read", value: `${result.frames_read} (${result.failed_reads} failed)` },
          { label: "Duration", value: formatDuration(result.duration_seconds) },
          ...(result.device_name ? [{ label: "Device", value: result.device_name }] : []),
        ]}
      />
    </div>
  );
}
