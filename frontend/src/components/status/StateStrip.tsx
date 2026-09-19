import type { OperationalState } from "@/types/contracts";
import { cn } from "@/lib/cn";
import { STATE_LABEL, STATE_ORDER } from "@/lib/labels";

/**
 * Operator workflow phase as a neutral five-step strip in ink intensities -
 * this never borrows the Operational Status palette (design spec s3.2): the
 * state is "where the operator is", not "how bad it is".
 */
export function StateStrip({
  state,
  compact = false,
  className,
}: {
  state: OperationalState;
  compact?: boolean;
  className?: string;
}) {
  const index = STATE_ORDER.indexOf(state);
  return (
    <div className={cn("flex flex-col gap-1", className)}>
      <div className="flex items-center gap-1">
        {STATE_ORDER.map((step, stepIndex) => (
          <span
            key={step}
            aria-hidden="true"
            className={cn(
              "h-1.5 rounded-full transition-colors duration-160 ease-out-soft",
              compact ? "w-4" : "w-6",
              stepIndex <= index ? "bg-ink-strong" : "bg-line-strong",
            )}
          />
        ))}
      </div>
      {!compact && <span className="text-xs text-ink-secondary">{STATE_LABEL[state]}</span>}
    </div>
  );
}
