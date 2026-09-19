import { EvidenceList } from "@/components/intel/EvidenceList";
import { Panel } from "@/components/data/Panel";
import { StaleBadge } from "@/components/status/StaleBadge";
import { useNow } from "@/lib/hooks/useNow";
import type { EvidenceReport } from "@/types/contracts";

export function EvidencePanel({
  evidence,
  withheldReason = null,
  staleSeconds = null,
}: {
  evidence: EvidenceReport | null;
  withheldReason?: string | null;
  staleSeconds?: number | null;
}) {
  const now = useNow(5000);
  const count = evidence?.items.length ?? 0;

  return (
    <Panel
      title="Evidence"
      meta={
        staleSeconds !== null ? (
          <StaleBadge isStale ageSeconds={staleSeconds} />
        ) : evidence ? (
          `${count} ${count === 1 ? "item" : "items"}`
        ) : undefined
      }
      state={withheldReason ? "empty" : !evidence ? "waiting" : staleSeconds !== null ? "stale" : "ready"}
      stateMessage={withheldReason ?? undefined}
    >
      {evidence && <EvidenceList items={evidence.items} now={now} />}
    </Panel>
  );
}
