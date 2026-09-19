import type { OperationalStatus } from "@/types/contracts";
import { cn } from "@/lib/cn";
import { formatPercent } from "@/lib/format";
import { STATUS_LABEL } from "@/lib/labels";
import { CSI_BANDS, STATUS_TONE, TONE_BG } from "@/lib/status";

/** Time spent in each Operational Status band over a range, as one stacked bar. */
export function StatusShareBar({ share }: { share: Partial<Record<OperationalStatus, number>> }) {
  const bands = [...CSI_BANDS].reverse().map((band) => band.status); // Stable first, reading left to right
  const total = bands.reduce((sum, status) => sum + (share[status] ?? 0), 0);
  if (total <= 0) return <p className="text-xs text-ink-faint">No status samples in this range.</p>;

  return (
    <div className="flex flex-col gap-2">
      <div className="flex h-2.5 w-full overflow-hidden rounded-full bg-surface-3">
        {bands.map((status) => {
          const fraction = (share[status] ?? 0) / total;
          if (fraction <= 0) return null;
          return (
            <div
              key={status}
              className={TONE_BG[STATUS_TONE[status]]}
              style={{ width: `${fraction * 100}%` }}
              title={`${STATUS_LABEL[status]}: ${formatPercent(fraction)}`}
            />
          );
        })}
      </div>
      <div className="flex flex-wrap gap-x-3 gap-y-1 text-2xs text-ink-faint">
        {bands.map((status) => {
          const fraction = (share[status] ?? 0) / total;
          if (fraction <= 0) return null;
          return (
            <span key={status} className="inline-flex items-center gap-1">
              <span className={cn("size-1.5 rounded-full", TONE_BG[STATUS_TONE[status]])} />
              {STATUS_LABEL[status]} {formatPercent(fraction)}
            </span>
          );
        })}
      </div>
    </div>
  );
}
