import type { ReactNode } from "react";

import { cn } from "@/lib/cn";
import { TONE_SOFT_BG, TONE_TEXT, type Tone } from "@/lib/status";

export function Badge({
  tone = "neutral",
  children,
  className,
}: {
  tone?: Tone;
  children: ReactNode;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-xs px-1.5 py-0.5 text-xs font-medium",
        TONE_SOFT_BG[tone],
        TONE_TEXT[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}
