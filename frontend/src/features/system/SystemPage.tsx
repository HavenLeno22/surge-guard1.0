import { useQuery } from "@tanstack/react-query";

import { systemApi } from "@/api/platform";
import { queryKeys } from "@/api/queryKeys";
import { isApiError } from "@/api/client";
import { KeyValueList } from "@/components/data/KeyValueList";
import { Panel } from "@/components/data/Panel";
import { HealthDot } from "@/components/status/HealthDot";
import { PageHeader } from "@/features/shell/PageHeader";
import { HardwarePanel } from "./HardwarePanel";
import { LinkIndicator } from "@/features/shell/LinkIndicator";
import { formatDateTime, formatFps, formatInteger, formatMs } from "@/lib/format";
import { COMPONENT_LABEL, HEALTH_LABEL, WORKER_STATE_LABEL } from "@/lib/labels";
import { useLive } from "@/realtime/store";
import { useLinkDiagnostics } from "@/realtime/useLinkDiagnostics";

export function SystemPage() {
  const health = useLive((state) => state.health);
  const pipeline = useLive((state) => state.pipeline);
  const perception = useLive((state) => state.perception);
  const link = useLinkDiagnostics();

  const infoQuery = useQuery({ queryKey: queryKeys.systemInfo, queryFn: ({ signal }) => systemApi.info(signal) });
  const ingestQuery = useQuery({
    queryKey: queryKeys.perceptionStatus,
    queryFn: ({ signal }) => systemApi.perceptionStatus(signal),
  });
  const streamQuery = useQuery({
    queryKey: queryKeys.streamStatus,
    queryFn: ({ signal }) => systemApi.streamStatus(signal),
  });

  return (
    <div className="flex flex-col gap-5">
      <PageHeader title="System" description="Component health, the alert hardware, the pipeline, and the realtime link." />

      <Panel title="Component health" state={health ? "ready" : "waiting"}>
        {health && (
          <ul className="flex flex-col divide-y divide-line">
            {health.components.map((component) => (
              <li key={component.component} className="flex items-center justify-between gap-3 py-2 text-sm">
                <span className="flex items-center gap-2 text-ink">
                  <HealthDot status={component.status} />
                  {COMPONENT_LABEL[component.component]}
                </span>
                <span className="text-xs text-ink-faint">{component.detail ?? HEALTH_LABEL[component.status]}</span>
              </li>
            ))}
          </ul>
        )}
      </Panel>

      <HardwarePanel />

      <div className="grid gap-5 lg:grid-cols-2">
        <Panel title="Pipeline" state={pipeline ? "ready" : "waiting"}>
          {pipeline && (
            <KeyValueList
              items={[
                { label: "State", value: WORKER_STATE_LABEL[pipeline.state] },
                { label: "Running", value: pipeline.running ? "Yes" : "No" },
                { label: "Source Mode", value: pipeline.source_mode === "LIVE" ? "Live" : "Demonstration" },
                { label: "Model", value: pipeline.model_name ?? "—" },
                { label: "Device", value: pipeline.device ? `${pipeline.device.name} (${pipeline.device.precision})` : "—" },
                { label: "Fallback reason", value: pipeline.device?.fallback_reason ?? "None" },
                { label: "Achieved fps", value: formatFps(pipeline.throughput?.achieved_fps) },
                { label: "Frames dropped", value: String(pipeline.throughput?.frames_dropped ?? 0) },
                { label: "Restarts", value: `${pipeline.restart_attempts} attempts, ${pipeline.total_restarts} total` },
                { label: "Degraded", value: pipeline.degraded ? (pipeline.degraded_reason ?? "Yes") : "No" },
              ]}
            />
          )}
        </Panel>

        <Panel title="Realtime link" state="ready">
          <div className="flex flex-col gap-3">
            <LinkIndicator />
            <KeyValueList
              items={[
                { label: "Messages received", value: formatInteger(link.messages) },
                { label: "Resyncs", value: formatInteger(link.resyncs) },
                { label: "Reconnect attempts", value: formatInteger(link.attempts) },
                { label: "Stale threshold", value: `${link.staleAfterSeconds}s` },
              ]}
            />
          </div>
        </Panel>
      </div>

      <div className="grid gap-5 lg:grid-cols-2">
        <Panel
          title="Ingest"
          state={ingestQuery.isPending ? "loading" : ingestQuery.isError ? "error" : "ready"}
          stateMessage={ingestQuery.isError && isApiError(ingestQuery.error) ? ingestQuery.error.message : undefined}
          onRetry={() => ingestQuery.refetch()}
        >
          {ingestQuery.data && (
            <KeyValueList
              items={[
                { label: "Has result", value: ingestQuery.data.has_result ? "Yes" : "No" },
                { label: "Received", value: formatInteger(ingestQuery.data.received) },
                { label: "Degraded received", value: formatInteger(ingestQuery.data.degraded_received) },
                { label: "Age", value: formatMs(ingestQuery.data.age_seconds !== null ? ingestQuery.data.age_seconds * 1000 : null) },
                { label: "Inference (latest)", value: formatMs(perception?.result.inference_ms) },
              ]}
            />
          )}
        </Panel>

        <Panel
          title="Video stream"
          state={streamQuery.isPending ? "loading" : streamQuery.isError ? "error" : "ready"}
          stateMessage={streamQuery.isError && isApiError(streamQuery.error) ? streamQuery.error.message : undefined}
          onRetry={() => streamQuery.refetch()}
        >
          {streamQuery.data && (
            <KeyValueList
              items={[
                { label: "Available", value: streamQuery.data.available ? "Yes" : "No" },
                { label: "Has frame", value: streamQuery.data.has_frame ? "Yes" : "No" },
                { label: "Viewers", value: String(streamQuery.data.viewers) },
                { label: "Worker state", value: WORKER_STATE_LABEL[streamQuery.data.worker_state] },
              ]}
            />
          )}
        </Panel>
      </div>

      <Panel
        title="Build"
        state={infoQuery.isPending ? "loading" : infoQuery.isError ? "error" : "ready"}
        stateMessage={infoQuery.isError && isApiError(infoQuery.error) ? infoQuery.error.message : undefined}
        onRetry={() => infoQuery.refetch()}
      >
        {infoQuery.data && (
          <KeyValueList
            items={[
              { label: "Name", value: infoQuery.data.name },
              { label: "Version", value: infoQuery.data.version },
              { label: "Environment", value: infoQuery.data.environment },
              { label: "API version", value: infoQuery.data.api_version },
              { label: "Analysis fps target", value: formatFps(infoQuery.data.analysis_fps) },
              { label: "Server time", value: formatDateTime(infoQuery.data.server_time) },
              { label: "Operator", value: infoQuery.data.operator_name },
            ]}
          />
        )}
      </Panel>
    </div>
  );
}
