import type { DecisionConfidence } from "@/types/contracts";
import { cn } from "@/lib/cn";
import { formatPercent } from "@/lib/format";
import { CONFIDENCE_FACTOR_LABEL } from "@/lib/labels";

export function ConfidenceMeter({
  confidence,
  className,
}: {
  confidence: DecisionConfidence;
  className?: string;
}) {
  const pct = Math.round(Math.min(Math.max(confidence.value, 0), 1) * 100);
  const limiting = confidence.limiting_factor;
  return (
    <div className={cn("flex flex-col gap-1", className)}>
      <div className="flex items-center justify-between text-xs">
        <span className="text-ink-muted">Confidence</span>
        <span className="readout text-ink-secondary">{formatPercent(confidence.value)}</span>
      </div>
      <div className="h-1 w-full rounded-full bg-surface-3">
        <div className="h-full rounded-full bg-ink-strong" style={{ width: `${pct}%` }} />
      </div>
      {limiting && (
        <span className="text-2xs text-ink-faint">
          Limited by {CONFIDENCE_FACTOR_LABEL[limiting].toLowerCase()}
        </span>
      )}
    </div>
  );
}
