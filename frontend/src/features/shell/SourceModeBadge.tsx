import type { SourceMode } from "@/types/contracts";
import { cn } from "@/lib/cn";
import { sourceModeLabel } from "@/lib/labels";

export function SourceModeBadge({
  mode,
  className,
}: {
  mode: SourceMode | string | null | undefined;
  className?: string;
}) {
  const isDemo = mode === "DEMO";
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-xs border px-1.5 py-0.5 text-2xs font-medium",
        isDemo ? "hatch border-ink-strong/30 text-ink-secondary" : "border-line-strong text-ink-muted",
        className,
      )}
    >
      {sourceModeLabel(mode)}
    </span>
  );
}
