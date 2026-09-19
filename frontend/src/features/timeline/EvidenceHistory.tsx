import { useQuery } from "@tanstack/react-query";

import { decisionsApi } from "@/api/platform";
import { isApiError } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import { EvidenceList } from "@/components/intel/EvidenceList";
import { Panel } from "@/components/data/Panel";
import { useNow } from "@/lib/hooks/useNow";

export function EvidenceHistory() {
  const now = useNow(5000);
  const { data, isPending, isError, error, refetch } = useQuery({
    queryKey: queryKeys.evidenceHistory,
    queryFn: ({ signal }) => decisionsApi.evidenceHistory(signal),
  });

  return (
    <Panel
      title="Evidence history"
      meta={data ? `${data.analysed} analysed, ${data.total} kept` : undefined}
      state={isPending ? "loading" : isError ? "error" : data && data.items.length === 0 ? "empty" : "ready"}
      stateMessage={isError && isApiError(error) ? error.message : "No evidence recorded yet."}
      onRetry={() => refetch()}
    >
      {data && data.items.length > 0 && <EvidenceList items={data.items} now={now} />}
    </Panel>
  );
}
