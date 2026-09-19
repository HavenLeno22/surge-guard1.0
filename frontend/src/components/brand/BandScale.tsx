import { cn } from "@/lib/cn";
import { formatCsi } from "@/lib/format";

/**
 * The Crowd Stability Index scale: five segments, Critical to Stable, with
 * ticks at 20/40/60/80. The product's one structural motif (spec s3.1) -
 * appears in the hero, the CSI instrument and the status bar.
 */
const SEGMENTS = [
  { tone: "critical", from: 0, to: 20 },
  { tone: "high", from: 20, to: 40 },
  { tone: "attention", from: 40, to: 60 },
  { tone: "observe", from: 60, to: 80 },
  { tone: "stable", from: 80, to: 100 },
] as const;

const SEGMENT_BG: Record<(typeof SEGMENTS)[number]["tone"], string> = {
  critical: "bg-critical",
  high: "bg-high",
  attention: "bg-attention",
  observe: "bg-observe",
  stable: "bg-stable",
};

export function BandScale({
  value,
  size = "md",
  showValue = false,
  className,
}: {
  /** Current CSI, 0-100. `null`/`undefined` draws the band with no marker. */
  value?: number | null;
  size?: "sm" | "md" | "lg";
  showValue?: boolean;
  className?: string;
}) {
  const clamped = typeof value === "number" ? Math.min(Math.max(value, 0), 100) : null;
  const height = size === "sm" ? "h-1.5" : size === "lg" ? "h-3" : "h-2";

  return (
    <div className={cn("flex flex-col gap-1.5", className)}>
      <div className={cn("relative flex w-full overflow-visible rounded-full", height)}>
        {SEGMENTS.map((segment) => (
          <div
            key={segment.tone}
            className={cn("h-full first:rounded-l-full last:rounded-r-full", SEGMENT_BG[segment.tone])}
            style={{ width: `${segment.to - segment.from}%` }}
          />
        ))}
        {[20, 40, 60, 80].map((tick) => (
          <div
            key={tick}
            aria-hidden="true"
            className="absolute top-0 h-full w-px bg-canvas/50"
            style={{ left: `${tick}%` }}
          />
        ))}
        {clamped !== null && (
          <div
            className="absolute top-1/2 size-3 -translate-y-1/2 -translate-x-1/2 rounded-full border-2 border-canvas bg-ink-strong shadow-[0_0_0_1px_var(--color-line-strong)]"
            style={{ left: `${clamped}%` }}
            aria-hidden="true"
          />
        )}
      </div>
      {showValue && (
        <div className="flex items-center justify-between text-2xs text-ink-faint">
          <span>Critical</span>
          <span className="readout text-ink-secondary">{formatCsi(clamped)}</span>
          <span>Stable</span>
        </div>
      )}
    </div>
  );
}
