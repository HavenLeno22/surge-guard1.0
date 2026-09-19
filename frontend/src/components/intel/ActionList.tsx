import type { RecommendedAction } from "@/types/contracts";
import { EmptyState } from "@/components/data/EmptyState";
import { cn } from "@/lib/cn";
import { formatPercent } from "@/lib/format";
import { RECOMMENDATION_LABEL } from "@/lib/labels";
import { PRIORITY_TONE } from "@/lib/status";
import { Badge } from "@/ui/Badge";

export function ActionList({ actions }: { actions: RecommendedAction[] }) {
  if (actions.length === 0) return <EmptyState title="No actions recommended" description="Continue normal monitoring." />;

  return (
    <ol className="flex flex-col divide-y divide-line">
      {[...actions]
        .sort((a, b) => a.priority - b.priority)
        .map((action) => (
          <li key={action.rule_id} className="flex flex-col gap-1.5 py-2.5">
            <div className="flex items-start justify-between gap-2">
              <span className="text-sm font-medium text-ink">{action.action}</span>
              <Badge tone={PRIORITY_TONE[action.urgency]}>{action.urgency}</Badge>
            </div>
            <p className="text-xs text-ink-muted">{action.rationale}</p>
            <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5 text-2xs text-ink-faint">
              <span>{RECOMMENDATION_LABEL[action.recommendation_type]}</span>
              <span>Confidence {formatPercent(action.confidence)}</span>
              <span className={cn("font-mono", "text-ink-faint")}>{action.rule_id}</span>
            </div>
          </li>
        ))}
    </ol>
  );
}
