import type { ReactNode } from "react";

import { cn } from "@/lib/cn";

/** A hatched outline chip, never a hue - simulated data is labelled, not colour-coded. */
export function SimulationLabel({
  children = "Simulation",
  className,
}: {
  children?: ReactNode;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "hatch inline-flex items-center gap-1 rounded-xs border border-ink-strong/35 px-1.5 py-0.5 text-2xs font-medium text-ink-secondary",
        className,
      )}
    >
      {children}
    </span>
  );
}
