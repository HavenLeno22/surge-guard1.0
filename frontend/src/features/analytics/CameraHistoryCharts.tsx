import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";

import { historyApi } from "@/api/platform";
import { queryKeys } from "@/api/queryKeys";
import { isApiError } from "@/api/client";
import { TimeSeries } from "@/components/charts/TimeSeries";
import { Panel, type PanelState } from "@/components/data/Panel";
import { formatPercent } from "@/lib/format";
import { SITE_TIMELINE_ID } from "@/lib/labels";
import type { SourceMode } from "@/types/contracts";
import type { HistoryPoint } from "@/types/history";
import { HISTORY_REFRESH_MS, historyWindow, type HistoryRange } from "./historyRange";

const CSI_TICKS = [0, 20, 40, 60, 80, 100];

function pick(points: HistoryPoint[], field: keyof HistoryPoint): (number | null)[] {
  return points.map((point) => {
    const value = point[field];
    return typeof value === "number" ? value : null;
  });
}

/** Share of the range's samples whose people count was estimated rather than tracked. */
function estimatedShare(points: HistoryPoint[]): number {
  const samples = points.reduce((sum, point) => sum + point.samples, 0);
  if (samples === 0) return 0;
  return points.reduce((sum, point) => sum + point.estimated_share * point.samples, 0) / samples;
}

export function CameraHistoryCharts({
  scope,
  range,
  chosenMode,
}: {
  scope: string;
  range: HistoryRange;
  chosenMode: SourceMode | null;
}) {
  const isSite = scope === SITE_TIMELINE_ID;

  const query = useQuery({
    queryKey: queryKeys.historySeries(scope, range.label, chosenMode),
    queryFn: ({ signal }) => {
      const params = { ...historyWindow(range), resolution: range.resolution, sourceMode: chosenMode ?? undefined };
      return isSite ? historyApi.site(params, signal) : historyApi.camera(scope, params, signal);
    },
    refetchInterval: HISTORY_REFRESH_MS,
  });
  const { data } = query;

  const derived = useMemo(() => {
    const points = data?.points ?? [];
    return {
      points,
      t: points.map((point) => Date.parse(point.t)),
      xDomain: data ? ([Date.parse(data.start), Date.parse(data.end)] as [number, number]) : undefined,
      estimated: estimatedShare(points),
    };
  }, [data]);
  const { points, t, xDomain } = derived;

  const state: PanelState = query.isPending
    ? "loading"
    : query.isError
      ? "error"
      : points.length === 0
        ? "empty"
        : "ready";
  const stateMessage = query.isError
    ? isApiError(query.error)
      ? query.error.message
      : "History could not be loaded."
    : "No history recorded in this range yet.";
  const panelState = { state, stateMessage, onRetry: () => void query.refetch() };

  return (
    <div className="grid gap-5 xl:grid-cols-2">
      {isSite ? (
        <Panel
          title="Cameras contributing"
          meta="Fewest cameras feeding the site view in each interval"
          {...panelState}
        >
          <TimeSeries
            label="Cameras contributing to the site view over time"
            t={t}
            xDomain={xDomain}
            series={[{ key: "cameras", label: "Cameras", tone: "neutral", values: pick(points, "cameras_contributing_min") }]}
          />
        </Panel>
      ) : (
        <Panel title="Crowd Stability Index" meta="Mean, with the range seen in each interval" {...panelState}>
          <TimeSeries
            label="Crowd Stability Index over time"
            emptyMessage="No index was produced in this range."
            t={t}
            xDomain={xDomain}
            yDomain={[0, 100]}
            yTicks={CSI_TICKS}
            series={[{ key: "csi", label: "CSI mean", tone: "neutral", values: pick(points, "csi_mean") }]}
            band={{ low: pick(points, "csi_min"), high: pick(points, "csi_max"), tone: "neutral" }}
          />
        </Panel>
      )}

      <Panel
        title={isSite ? "Site headcount" : "People"}
        meta={derived.estimated > 0 ? `${formatPercent(derived.estimated)} of counts estimated, not tracked` : undefined}
        {...panelState}
      >
        <TimeSeries
          label={isSite ? "Site headcount over time" : "People in view over time"}
          t={t}
          xDomain={xDomain}
          series={[
            { key: "mean", label: "Mean", tone: "neutral", values: pick(points, "people_mean") },
            { key: "max", label: "Peak", tone: "muted", dashed: true, values: pick(points, "people_max") },
          ]}
        />
      </Panel>

      <Panel title="Queue length" {...panelState}>
        <TimeSeries
          label="Queue length over time"
          emptyMessage={isSite ? "No site queue was measured in this range." : "This camera measured no queue in this range."}
          t={t}
          xDomain={xDomain}
          series={[
            { key: "mean", label: "Mean", tone: "neutral", values: pick(points, "queue_length_mean") },
            { key: "max", label: "Longest", tone: "muted", dashed: true, values: pick(points, "queue_length_max") },
          ]}
        />
      </Panel>

      <Panel title="Estimated wait" meta="Minutes" {...panelState}>
        <TimeSeries
          label="Estimated wait over time, in minutes"
          emptyMessage="No wait could be estimated in this range."
          t={t}
          xDomain={xDomain}
          valueFormat={(value) => value.toFixed(1)}
          series={[
            { key: "mean", label: "Mean", tone: "neutral", values: pick(points, "wait_minutes_mean") },
            { key: "max", label: "Longest", tone: "muted", dashed: true, values: pick(points, "wait_minutes_max") },
          ]}
        />
      </Panel>
    </div>
  );
}
