import type { ResourcePlan } from "@/types/contracts";
import { CapacityLadder } from "@/components/charts/CapacityLadder";
import { formatMinutes } from "@/lib/format";
import { Badge } from "@/ui/Badge";

/** What to do about it: the capacity ladder, and whether the recommendation actually holds. */
export function QueuePlan({ plan }: { plan: ResourcePlan }) {
  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-sm text-ink-secondary">
          {plan.zone_name}
          <span className="ml-2 text-xs text-ink-faint">Target wait {formatMinutes(plan.target_wait_minutes)}</span>
        </span>
        {!plan.feasible && <Badge tone="attention">Not achievable within limits</Badge>}
        {plan.provisional && <Badge tone="muted">Provisional</Badge>}
      </div>
      <CapacityLadder plan={plan} />
      {plan.expected_effect && <p className="text-2xs text-ink-faint">{plan.expected_effect}</p>}
    </div>
  );
}
