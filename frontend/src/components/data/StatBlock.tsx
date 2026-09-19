import type { ReactNode } from "react";

import { cn } from "@/lib/cn";
import type { Tone } from "@/lib/status";
import { TONE_TEXT } from "@/lib/status";

export function StatBlock({
  label,
  value,
  unit,
  tone,
  detail,
  className,
}: {
  label: string;
  value: ReactNode;
  unit?: string;
  tone?: Tone;
  detail?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-col gap-1", className)}>
      <span className="text-xs text-ink-faint">{label}</span>
      <span className={cn("readout text-2xl", tone ? TONE_TEXT[tone] : "text-ink-strong")}>
        {value}
        {unit && <span className="ml-1 text-sm text-ink-muted">{unit}</span>}
      </span>
      {detail && <span className="text-xs text-ink-faint">{detail}</span>}
    </div>
  );
}
