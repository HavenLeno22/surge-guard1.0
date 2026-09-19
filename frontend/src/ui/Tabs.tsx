import { Tabs as RadixTabs } from "radix-ui";
import type { ReactNode } from "react";

import { cn } from "@/lib/cn";

export const Tabs = RadixTabs.Root;

export function TabsList({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <RadixTabs.List
      className={cn("inline-flex items-center gap-1 rounded-control bg-surface-2 p-1", className)}
    >
      {children}
    </RadixTabs.List>
  );
}

export function TabsTrigger({
  value,
  children,
  className,
}: {
  value: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <RadixTabs.Trigger
      value={value}
      className={cn(
        "rounded-sm px-3 py-1.5 text-xs font-medium text-ink-muted transition-colors duration-120 ease-out-soft",
        "hover:text-ink data-[state=active]:bg-surface-3 data-[state=active]:text-ink-strong",
        "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ink-strong",
        className,
      )}
    >
      {children}
    </RadixTabs.Trigger>
  );
}

export function TabsContent({
  value,
  children,
  className,
}: {
  value: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <RadixTabs.Content value={value} className={cn("focus-visible:outline-none", className)}>
      {children}
    </RadixTabs.Content>
  );
}
