import type { PrimaryCause } from "@/types/contracts";
import { EmptyState } from "@/components/data/EmptyState";
import { formatPercent } from "@/lib/format";

export function CausesList({ causes }: { causes: PrimaryCause[] }) {
  if (causes.length === 0) return <EmptyState title="No primary causes identified" />;

  return (
    <ul className="flex flex-col gap-2.5">
      {causes.map((cause) => (
        <li key={cause.indicator} className="flex flex-col gap-1">
          <div className="flex items-center justify-between text-sm">
            <span className="text-ink">{cause.label}</span>
            <span className="readout text-ink-secondary">{formatPercent(cause.contribution_pct / 100)}</span>
          </div>
          <div className="h-1 w-full rounded-full bg-surface-3">
            <div className="h-full rounded-full bg-ink-strong" style={{ width: `${Math.min(cause.contribution_pct, 100)}%` }} />
          </div>
          {cause.detail && <p className="text-xs text-ink-faint">{cause.detail}</p>}
        </li>
      ))}
    </ul>
  );
}
