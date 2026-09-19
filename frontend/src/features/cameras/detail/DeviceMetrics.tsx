import { KeyValueList } from "@/components/data/KeyValueList";
import { formatDuration, formatFps, formatMs, formatPercent } from "@/lib/format";
import type { CameraMetrics } from "@/types/contracts";

export function DeviceMetrics({ metrics }: { metrics: CameraMetrics }) {
  return (
    <KeyValueList
      items={[
        { label: "Resolution", value: metrics.native_width && metrics.native_height ? `${metrics.native_width}×${metrics.native_height}` : "—" },
        { label: "Analysis resolution", value: metrics.analysis_width && metrics.analysis_height ? `${metrics.analysis_width}×${metrics.analysis_height}` : "—" },
        { label: "Source fps", value: formatFps(metrics.source_fps) },
        { label: "Achieved fps", value: formatFps(metrics.achieved_fps) },
        { label: "Frame age", value: formatDuration(metrics.frame_age_seconds) },
        { label: "Inference", value: formatMs(metrics.inference_ms) },
        { label: "Processing", value: formatMs(metrics.processing_ms) },
        { label: "Pipeline latency", value: formatMs(metrics.pipeline_latency_ms) },
        { label: "Network RTT", value: formatMs(metrics.network_rtt_ms) },
        { label: "Frames dropped", value: `${metrics.frames_dropped} of ${metrics.frames_processed}` },
        { label: "Reconnections", value: String(metrics.reconnections) },
        ...(metrics.device_name ? [{ label: "Device", value: metrics.device_name }] : []),
        ...(metrics.battery_percent !== null
          ? [{ label: "Battery", value: formatPercent(metrics.battery_percent / 100) }]
          : []),
      ]}
    />
  );
}
