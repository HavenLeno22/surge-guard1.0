import { DropdownMenu as RadixDropdownMenu } from "radix-ui";
import type { ReactNode } from "react";

import { cn } from "@/lib/cn";

export const DropdownMenu = RadixDropdownMenu.Root;
export const DropdownMenuTrigger = RadixDropdownMenu.Trigger;

export function DropdownMenuContent({
  children,
  align = "end",
  className,
}: {
  children: ReactNode;
  align?: "start" | "center" | "end";
  className?: string;
}) {
  return (
    <RadixDropdownMenu.Portal>
      <RadixDropdownMenu.Content
        align={align}
        sideOffset={6}
        className={cn(
          "z-50 min-w-48 rounded-control border border-line-strong bg-surface-2 p-1 shadow-overlay",
          "animate-rise",
          className,
        )}
      >
        {children}
      </RadixDropdownMenu.Content>
    </RadixDropdownMenu.Portal>
  );
}

export function DropdownMenuItem({
  children,
  onSelect,
  danger = false,
  disabled,
  className,
}: {
  children: ReactNode;
  onSelect?: () => void;
  danger?: boolean;
  disabled?: boolean;
  className?: string;
}) {
  return (
    <RadixDropdownMenu.Item
      disabled={disabled}
      onSelect={onSelect}
      className={cn(
        "flex cursor-pointer items-center gap-2 rounded-sm px-2.5 py-1.5 text-sm outline-none",
        danger ? "text-critical-text" : "text-ink",
        "data-[highlighted]:bg-surface-3 data-[disabled]:cursor-not-allowed data-[disabled]:text-ink-faint",
        className,
      )}
    >
      {children}
    </RadixDropdownMenu.Item>
  );
}

export function DropdownMenuLabel({ children }: { children: ReactNode }) {
  return <RadixDropdownMenu.Label className="px-2.5 py-1.5 text-2xs text-ink-faint">{children}</RadixDropdownMenu.Label>;
}

export function DropdownMenuSeparator() {
  return <RadixDropdownMenu.Separator className="my-1 h-px bg-line" />;
}
