import type { EvidenceItem } from "@/types/contracts";
import { formatAge, formatNumber } from "@/lib/format";
import { SeverityMark } from "@/components/status/SeverityMark";
import { EmptyState } from "@/components/data/EmptyState";

/** Whole numbers (counts) read as whole numbers; measurements keep one decimal. */
function formatMetric(value: number): string {
  return formatNumber(value, Number.isInteger(value) ? 0 : 1);
}

export function EvidenceList({ items, now }: { items: EvidenceItem[]; now?: number }) {
  if (items.length === 0) return <EmptyState title="No evidence yet" description="Conditions are nominal." />;

  return (
    <ul className="flex flex-col divide-y divide-line">
      {items.map((item, index) => {
        const ageSeconds = now ? (now - new Date(item.observed_at).getTime()) / 1000 : null;
        return (
          <li key={`${item.evidence_type}-${item.frame_seq}-${index}`} className="flex flex-col gap-1.5 py-2.5">
            <div className="flex items-center justify-between gap-2">
              <span className="text-sm font-medium text-ink">{item.headline}</span>
              <SeverityMark severity={item.severity} showLabel={false} />
            </div>
            <p className="text-xs text-ink-muted">{item.detail}</p>
            {item.metrics.length > 0 && (
              <div className="flex flex-wrap gap-x-3 gap-y-0.5 text-2xs text-ink-faint">
                {item.metrics.map((metric) => (
                  <span key={metric.label}>
                    {metric.label}: {formatMetric(metric.value)}
                    {metric.unit}
                    {metric.baseline !== null && ` (baseline ${formatMetric(metric.baseline)}${metric.unit})`}
                  </span>
                ))}
              </div>
            )}
            {ageSeconds !== null && <span className="text-2xs text-ink-faint">{formatAge(ageSeconds)}</span>}
          </li>
        );
      })}
    </ul>
  );
}
