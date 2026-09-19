import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { historyApi } from "@/api/platform";
import { queryKeys } from "@/api/queryKeys";
import { isApiError } from "@/api/client";
import { StatusShareBar } from "@/components/charts/StatusShareBar";
import { Panel } from "@/components/data/Panel";
import { PageHeader } from "@/features/shell/PageHeader";
import { SITE_TIMELINE_ID } from "@/lib/labels";
import { useLive } from "@/realtime/store";
import type { SourceMode } from "@/types/contracts";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/ui/Tabs";
import { CameraHistoryCharts } from "./CameraHistoryCharts";
import { DEFAULT_RANGE, HISTORY_REFRESH_MS, historyWindow, type HistoryRange } from "./historyRange";
import { RangePicker } from "./RangePicker";
import { SummaryTable } from "./SummaryTable";

export function AnalyticsPage() {
  const cameraOrder = useLive((state) => state.cameraOrder);
  const cameras = useLive((state) => state.cameras);
  const [range, setRange] = useState<HistoryRange>(DEFAULT_RANGE);
  // `null` until the operator picks a mode. History is recorded tagged with the
  // deployment's own mode and the backend answers in that mode when none is
  // given, then says which it used - so nothing waits on the socket and no
  // request is spent guessing.
  const [chosenMode, setChosenMode] = useState<SourceMode | null>(null);
  const [scope, setScope] = useState(SITE_TIMELINE_ID);

  const summaryQuery = useQuery({
    queryKey: queryKeys.historySummary(range.label, chosenMode),
    queryFn: ({ signal }) =>
      historyApi.summary({ ...historyWindow(range), sourceMode: chosenMode ?? undefined }, signal),
    refetchInterval: HISTORY_REFRESH_MS,
  });
  const summary = summaryQuery.data;
  const sourceMode = chosenMode ?? summary?.source_mode ?? null;

  const nameFor = (id: string) => (id === SITE_TIMELINE_ID ? "Whole site" : (cameras[id]?.name ?? id));
  const items = summary ? [...(summary.site ? [summary.site] : []), ...summary.cameras] : [];
  const cameraItems = summary?.cameras ?? [];

  const summaryState = summaryQuery.isPending ? "loading" : summaryQuery.isError ? "error" : "ready";
  const summaryError = isApiError(summaryQuery.error) ? summaryQuery.error.message : "History could not be loaded.";

  return (
    <div className="flex flex-col gap-5">
      <PageHeader title="Analytics" description="Stored history: trends, baseline availability and time in each band." />

      <RangePicker range={range} onRangeChange={setRange} sourceMode={sourceMode} onSourceModeChange={setChosenMode} />

      {summary && !summary.recording && (
        <p className="rounded-md border border-attention/30 bg-surface-1 px-4 py-3 text-sm text-ink-secondary">
          History recording is turned off on this deployment, so nothing new is being stored. Existing records are still shown.
        </p>
      )}

      <Panel
        title="Summary"
        meta={
          summary
            ? `Recorded in ${summary.bucket_seconds}-second buckets and kept for ${summary.retention_days} days`
            : undefined
        }
        state={summaryState}
        stateMessage={summaryError}
        onRetry={() => summaryQuery.refetch()}
      >
        <SummaryTable items={items} nameFor={nameFor} baselineMinSamples={summary?.baseline_min_samples ?? null} />
      </Panel>

      <Panel
        title="Time in each band"
        meta="Share of analysed windows per camera"
        state={summaryState === "ready" && cameraItems.length === 0 ? "empty" : summaryState}
        stateMessage={summaryQuery.isError ? summaryError : "No camera history in this range yet."}
        onRetry={() => summaryQuery.refetch()}
      >
        <ul className="grid gap-x-8 gap-y-4 md:grid-cols-2">
          {cameraItems.map((item) => (
            <li key={item.camera_id} className="flex flex-col gap-2">
              <span className="text-sm text-ink">{nameFor(item.camera_id)}</span>
              <StatusShareBar share={item.status_share} />
            </li>
          ))}
        </ul>
      </Panel>

      <Tabs value={scope} onValueChange={setScope}>
        <TabsList>
          <TabsTrigger value={SITE_TIMELINE_ID}>Whole site</TabsTrigger>
          {cameraOrder.map((id) => (
            <TabsTrigger key={id} value={id}>
              {nameFor(id)}
            </TabsTrigger>
          ))}
        </TabsList>
        <TabsContent value={scope} className="mt-4">
          <CameraHistoryCharts scope={scope} range={range} chosenMode={chosenMode} />
        </TabsContent>
      </Tabs>
    </div>
  );
}
