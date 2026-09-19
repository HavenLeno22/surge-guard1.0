import { X } from "lucide-react";
import { Dialog as RadixDialog } from "radix-ui";
import type { ReactNode } from "react";

import { cn } from "@/lib/cn";
import { IconButton } from "./IconButton";

export function Dialog({
  open,
  onOpenChange,
  title,
  description,
  children,
  footer,
  size = "md",
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description?: string;
  children?: ReactNode;
  footer?: ReactNode;
  size?: "sm" | "md" | "lg";
}) {
  return (
    <RadixDialog.Root open={open} onOpenChange={onOpenChange}>
      <RadixDialog.Portal>
        <RadixDialog.Overlay className="fixed inset-0 z-50 bg-canvas/70 backdrop-blur-[2px] animate-fade" />
        <RadixDialog.Content
          className={cn(
            "fixed top-1/2 left-1/2 z-50 w-[calc(100vw-32px)] -translate-x-1/2 -translate-y-1/2 rounded-lg border border-line-strong bg-surface-1 shadow-overlay animate-rise",
            size === "sm" && "max-w-sm",
            size === "md" && "max-w-md",
            size === "lg" && "max-w-2xl",
          )}
        >
          <div className="flex items-start justify-between gap-4 border-b border-line px-5 py-4">
            <div>
              <RadixDialog.Title className="text-base font-semibold text-ink-strong">
                {title}
              </RadixDialog.Title>
              {description && (
                <RadixDialog.Description className="mt-1 text-sm text-ink-muted">
                  {description}
                </RadixDialog.Description>
              )}
            </div>
            <RadixDialog.Close asChild>
              <IconButton aria-label="Close dialog" icon={<X size={16} />} size="sm" />
            </RadixDialog.Close>
          </div>
          {children && <div className="px-5 py-4">{children}</div>}
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
