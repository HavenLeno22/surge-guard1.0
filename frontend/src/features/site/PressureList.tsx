import { EmptyState } from "@/components/data/EmptyState";
import { formatMinutes } from "@/lib/format";
import { Badge } from "@/ui/Badge";
import type { TimeToPressure } from "@/types/contracts";

export function PressureList({ items }: { items: TimeToPressure[] }) {
  if (items.length === 0) return <EmptyState title="No pressure projections available" />;

  return (
    <ul className="flex flex-col divide-y divide-line">
      {items.map((item, index) => (
        <li key={index} className="flex flex-col gap-1 py-2.5">
          <div className="flex items-center justify-between gap-2">
            <span className="text-sm text-ink">{item.label}</span>
            {item.already_exceeded ? (
              <Badge tone="critical">Already exceeded</Badge>
            ) : item.within_horizon && item.minutes !== null ? (
              <Badge tone="attention">{formatMinutes(item.minutes)}</Badge>
            ) : (
              <Badge tone="neutral">Beyond {item.horizon_minutes} min</Badge>
            )}
          </div>
          <p className="text-xs text-ink-faint">{item.explanation}</p>
        </li>
      ))}
    </ul>
  );
}
