import { formatAge } from "@/lib/format";
import { cn } from "@/lib/cn";

/** Stale data is always visibly marked with its age (principle: a frozen display is more dangerous than a failed one). */
export function StaleBadge({
  isStale,
  ageSeconds,
  className,
}: {
  isStale: boolean;
  ageSeconds?: number | null;
  className?: string;
}) {
  if (!isStale) return null;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-xs bg-attention/10 px-1.5 py-0.5 text-2xs font-medium text-attention",
        className,
      )}
    >
      Stale{typeof ageSeconds === "number" ? `, updated ${formatAge(ageSeconds)}` : ""}
    </span>
  );
}
