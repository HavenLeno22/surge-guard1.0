import type { TimelineEntry } from "@/types/contracts";
import { EmptyState } from "@/components/data/EmptyState";
import { SeverityMark } from "@/components/status/SeverityMark";
import { formatAge } from "@/lib/format";
import { TIMELINE_TYPE_LABEL } from "@/lib/labels";

export function TimelineList({
  entries,
  now,
  className,
}: {
  entries: TimelineEntry[];
  now: number;
  className?: string;
}) {
  if (entries.length === 0) return <EmptyState title="No timeline entries yet" />;

  return (
    <ol className={className}>
      {entries.map((entry) => (
        <li key={entry.entry_id} className="flex gap-3 border-l border-line pb-4 pl-4 last:pb-0">
          <span className="-ml-[21px] mt-1 size-2 shrink-0 rounded-full border-2 border-surface-1 bg-ink-faint" aria-hidden="true" />
          <div className="flex flex-1 flex-col gap-0.5">
            <div className="flex items-center justify-between gap-2">
              <span className="text-sm text-ink">{entry.title}</span>
              <SeverityMark severity={entry.severity} showLabel={false} />
            </div>
            {entry.detail && <p className="text-xs text-ink-muted">{entry.detail}</p>}
            <div className="flex flex-wrap gap-x-3 gap-y-0.5 text-2xs text-ink-faint">
              <span>{formatAge((now - new Date(entry.occurred_at).getTime()) / 1000)}</span>
              <span className="text-ink-muted">{TIMELINE_TYPE_LABEL[entry.entry_type]}</span>
              {entry.actor && <span>By {entry.actor}</span>}
            </div>
          </div>
        </li>
      ))}
    </ol>
  );
}
