import { useQuery } from "@tanstack/react-query";

import { decisionsApi } from "@/api/platform";
import { isApiError } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import { Panel } from "@/components/data/Panel";
import { StatusPill } from "@/components/status/StatusPill";
import { formatDateTime } from "@/lib/format";

/** Revision history of the primary camera's guidance - the backend only keeps this camera's history. */
export function GuidanceHistory() {
  const { data, isPending, isError, error, refetch } = useQuery({
    queryKey: queryKeys.decisionHistory,
    queryFn: ({ signal }) => decisionsApi.history(30, signal),
  });

  return (
    <Panel
      title="Guidance history"
      meta="Primary camera"
      state={isPending ? "loading" : isError ? "error" : data && data.reports.length === 0 ? "empty" : "ready"}
      stateMessage={isError && isApiError(error) ? error.message : "No guidance revisions recorded yet."}
      onRetry={() => refetch()}
    >
      {data && data.reports.length > 0 && (
        <ol className="flex flex-col divide-y divide-line">
          {data.reports.map((report) => (
            <li key={`${report.sequence}-${report.revision}`} className="flex flex-col gap-1 py-2.5">
              <div className="flex items-center justify-between gap-2">
                <StatusPill status={report.status} size="sm" />
                <span className="text-2xs text-ink-faint">{formatDateTime(report.generated_at)}</span>
              </div>
              <p className="text-xs text-ink-secondary">{report.situation_summary}</p>
            </li>
          ))}
        </ol>
      )}
    </Panel>
  );
}
