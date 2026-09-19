import { X } from "lucide-react";
import { Dialog as RadixDialog } from "radix-ui";
import type { ReactNode } from "react";

import { cn } from "@/lib/cn";
import { IconButton } from "./IconButton";

/** A panel sliding in from the side (desktop) or bottom (mobile forms, drawers). */
export function Drawer({
  open,
  onOpenChange,
  title,
  children,
  footer,
  side = "right",
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  children?: ReactNode;
  footer?: ReactNode;
  side?: "left" | "right" | "bottom";
}) {
  return (
    <RadixDialog.Root open={open} onOpenChange={onOpenChange}>
      <RadixDialog.Portal>
        <RadixDialog.Overlay className="fixed inset-0 z-50 bg-canvas/70 backdrop-blur-[2px] animate-fade" />
        <RadixDialog.Content
          className={cn(
            "fixed z-50 flex flex-col border-line-strong bg-surface-1 shadow-overlay",
            side === "right" &&
              "inset-y-0 right-0 w-full max-w-md border-l data-[state=open]:animate-[rise_220ms_var(--ease-out-soft)_both]",
            side === "left" &&
              "inset-y-0 left-0 w-full max-w-xs border-r data-[state=open]:animate-[rise_220ms_var(--ease-out-soft)_both]",
            side === "bottom" &&
              "inset-x-0 bottom-0 max-h-[85dvh] rounded-t-lg border-t data-[state=open]:animate-[rise_220ms_var(--ease-out-soft)_both]",
          )}
        >
          <div className="flex items-center justify-between gap-4 border-b border-line px-5 py-4">
            <RadixDialog.Title className="text-base font-semibold text-ink-strong">
              {title}
            </RadixDialog.Title>
            <RadixDialog.Close asChild>
              <IconButton aria-label="Close" icon={<X size={16} />} size="sm" />
            </RadixDialog.Close>
          </div>
          <div className="flex-1 overflow-y-auto px-5 py-4">{children}</div>
          {footer && (
            <div className="flex items-center justify-end gap-2 border-t border-line px-5 py-4">
              {footer}
            </div>
          )}
        </RadixDialog.Content>
      </RadixDialog.Portal>
    </RadixDialog.Root>
  );
}
