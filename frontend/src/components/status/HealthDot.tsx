import type { HealthStatus } from "@/types/contracts";
import { cn } from "@/lib/cn";
import { HEALTH_LABEL } from "@/lib/labels";
import { HEALTH_TONE, TONE_BG } from "@/lib/status";

/** Decorative - pair with visible text, since the colour alone is never the only signal. */
export function HealthDot({ status, className }: { status: HealthStatus; className?: string }) {
  return (
    <span
      className={cn("inline-block size-2 rounded-full", TONE_BG[HEALTH_TONE[status]], className)}
      aria-hidden="true"
      title={HEALTH_LABEL[status]}
    />
  );
}
