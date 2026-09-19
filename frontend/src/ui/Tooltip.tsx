import { Tooltip as RadixTooltip } from "radix-ui";
import type { ReactNode } from "react";

import { cn } from "@/lib/cn";

export const TooltipProvider = RadixTooltip.Provider;

export function Tooltip({
  content,
  children,
  side = "top",
  className,
}: {
  content: ReactNode;
  children: ReactNode;
  side?: "top" | "right" | "bottom" | "left";
  className?: string;
}) {
  return (
    <RadixTooltip.Root delayDuration={250}>
      <RadixTooltip.Trigger asChild>{children}</RadixTooltip.Trigger>
      <RadixTooltip.Portal>
        <RadixTooltip.Content
          side={side}
          sideOffset={6}
          className={cn(
            "z-50 max-w-64 rounded-sm border border-line-strong bg-surface-3 px-2.5 py-1.5 text-xs text-ink",
            "animate-fade",
            className,
          )}
        >
          {content}
          <RadixTooltip.Arrow className="fill-surface-3" />
        </RadixTooltip.Content>
      </RadixTooltip.Portal>
    </RadixTooltip.Root>
  );
}
