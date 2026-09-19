import type { OperationalStatus } from "@/types/contracts";
import { cn } from "@/lib/cn";
import { STATUS_LABEL } from "@/lib/labels";
import { STATUS_TONE, TONE_BG, TONE_SOFT_BG, TONE_TEXT } from "@/lib/status";

/** Operational Status: the only place the five saturated hues carry meaning. */
export function StatusPill({
  status,
  size = "md",
  className,
}: {
  status: OperationalStatus | null;
  size?: "sm" | "md";
  className?: string;
}) {
  const tone = status ? STATUS_TONE[status] : "muted";
  const label = status ? STATUS_LABEL[status] : "No data";
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-xs font-medium",
        size === "sm" ? "px-1.5 py-0.5 text-2xs" : "px-2 py-1 text-xs",
        TONE_SOFT_BG[tone],
        TONE_TEXT[tone],
        className,
      )}
    >
      <span className={cn("size-1.5 rounded-full", TONE_BG[tone])} aria-hidden="true" />
      {label}
    </span>
  );
}
