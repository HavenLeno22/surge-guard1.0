import type { CountMethod } from "@/types/contracts";
import { cn } from "@/lib/cn";
import { countMethodLabel } from "@/lib/labels";

/** ESTIMATED must never read as TRACKED - this is the one place that distinction is drawn. */
export function CountMethodTag({ method, className }: { method: CountMethod; className?: string }) {
  return (
    <span
      className={cn(
        "text-2xs font-medium",
        method === "ESTIMATED" ? "text-ink-secondary" : "text-ink-faint",
        className,
      )}
    >
      {countMethodLabel(method)}
    </span>
  );
}
