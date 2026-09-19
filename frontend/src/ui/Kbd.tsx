import type { ReactNode } from "react";

import { cn } from "@/lib/cn";

export function Kbd({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <kbd
      className={cn(
        "rounded-xs border border-line-strong bg-surface-2 px-1.5 py-0.5 font-mono text-2xs text-ink-secondary",
        className,
      )}
    >
      {children}
    </kbd>
  );
}
