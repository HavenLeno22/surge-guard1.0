import type { ReactNode } from "react";

import { cn } from "@/lib/cn";

export interface KeyValueItem {
  label: string;
  value: ReactNode;
}

export function KeyValueList({ items, className }: { items: KeyValueItem[]; className?: string }) {
  return (
    <dl className={cn("flex flex-col divide-y divide-line", className)}>
      {items.map((item) => (
        <div key={item.label} className="flex items-center justify-between gap-4 py-2 text-sm">
          <dt className="text-ink-muted">{item.label}</dt>
          <dd className="text-right text-ink">{item.value}</dd>
        </div>
      ))}
    </dl>
  );
}
