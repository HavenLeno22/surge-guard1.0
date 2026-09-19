import type { ReactNode } from "react";

import { cn } from "@/lib/cn";

export function EmptyState({
  icon,
  title,
  description,
  action,
  className,
}: {
  icon?: ReactNode;
  title: string;
  description?: string;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-col items-center gap-2 py-10 text-center", className)}>
      {icon && <div className="mb-1 text-ink-faint">{icon}</div>}
      <p className="text-sm font-medium text-ink-secondary">{title}</p>
      {description && <p className="max-w-sm text-xs text-ink-faint">{description}</p>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}
