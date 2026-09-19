import type { ResourcePlan } from "@/types/contracts";
import { cn } from "@/lib/cn";
import { formatInteger, formatMinutes, formatPercent } from "@/lib/format";
import { Badge } from "@/ui/Badge";

function countersLabel(count: number): string {
  return `${count} ${count === 1 ? "counter" : "counters"}`;
}

/** Every counter count the planner tried, ascending, so an operator sees the tradeoff. */
export function CapacityLadder({ plan }: { plan: ResourcePlan }) {
  const maxQueue = Math.max(1, ...plan.options.map((option) => option.projected_queue));

  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-center gap-3 px-2.5 text-2xs text-ink-faint" aria-hidden="true">
        <span className="w-20 shrink-0">Open</span>
        <span className="flex-1">Queue in {formatInteger(plan.horizon_minutes)} min</span>
        <span className="w-10 shrink-0 text-right">People</span>
        <span className="w-16 shrink-0 text-right">Wait</span>
      </div>
      <ul className="flex flex-col gap-1.5">
        {plan.options.map((option) => {
          const isCurrent = option.active_counters === plan.current.active_counters;
          const isRecommended = option.active_counters === plan.recommended.active_counters;
          return (
            <li
              key={option.active_counters}
              className={cn(
                "flex flex-wrap items-center gap-x-3 gap-y-1 rounded-control border px-2.5 py-1.5 text-xs",
                isRecommended ? "border-line-strong bg-surface-2" : "border-line bg-surface-2/50",
              )}
            >
              <span className="w-20 shrink-0 text-ink-secondary">{countersLabel(option.active_counters)}</span>
              <div className="h-1.5 min-w-16 flex-1 rounded-full bg-surface-3" aria-hidden="true">
                <div
                  className={cn("h-full rounded-full", option.clears_target ? "bg-stable" : "bg-ink-faint")}
                  style={{ width: `${(option.projected_queue / maxQueue) * 100}%` }}
                />
              </div>
              <span className="w-10 shrink-0 text-right tabular text-ink">{formatInteger(option.projected_queue)}</span>
              <span className="w-16 shrink-0 text-right tabular text-ink-muted">
                {formatMinutes(option.projected_wait_minutes)}
              </span>
              {(isCurrent || isRecommended) && (
                <span className="flex basis-full justify-end gap-1.5 sm:basis-auto">
                  {isCurrent && <Badge tone="neutral">Current</Badge>}
                  {isRecommended && (
                    <Badge tone={option.clears_target ? "stable" : "neutral"}>Recommended</Badge>
                  )}
                </span>
              )}
            </li>
          );
        })}
      </ul>
      {plan.options.some((option) => option.clears_target) && (
        <p className="mt-1 flex items-center gap-1.5 text-2xs text-ink-faint">
          <span className="inline-block size-1.5 rounded-full bg-stable" aria-hidden="true" />
          Meets the {formatMinutes(plan.target_wait_minutes)} wait target
        </p>
      )}
      <p className="text-2xs text-ink-muted">
        {plan.rationale}
        {plan.confidence ? ` Confidence ${formatPercent(plan.confidence)}.` : ""}
      </p>
    </div>
  );
}
