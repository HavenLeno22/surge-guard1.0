import { EmptyState } from "@/components/data/EmptyState";
import { formatPercent } from "@/lib/format";
import type { Hotspot } from "@/types/contracts";

export function HotspotPanel({ hotspot }: { hotspot: Hotspot | null }) {
  if (!hotspot) return <EmptyState title="No hotspot identified" description="No location stands out from the rest of the site right now." />;

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium text-ink">{hotspot.label}</span>
        <span className="readout text-lg text-ink-strong">{Math.round(hotspot.score)}</span>
      </div>
      {hotspot.reasons.length > 0 && (
        <ul className="list-inside list-disc text-xs text-ink-muted">
          {hotspot.reasons.map((reason, index) => (
            <li key={index}>{reason}</li>
          ))}
        </ul>
      )}
      <div className="flex flex-col gap-2">
        {hotspot.factors.map((factor) => (
          <div key={factor.key} className="flex flex-col gap-1">
            <div className="flex items-center justify-between text-xs">
              <span className="text-ink-secondary">{factor.label}</span>
              <span className="text-ink-faint">weight {formatPercent(factor.weight)}</span>
            </div>
            <div className="h-1 w-full rounded-full bg-surface-3">
              <div className="h-full rounded-full bg-ink-strong" style={{ width: `${Math.min(Math.max(factor.contribution * 100, 0), 100)}%` }} />
            </div>
            <span className="text-2xs text-ink-faint">{factor.detail}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
