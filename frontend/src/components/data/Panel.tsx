import type { ReactNode } from "react";

import { cn } from "@/lib/cn";
import { Skeleton } from "@/ui/Skeleton";
import { EmptyState } from "./EmptyState";
import { ErrorState } from "./ErrorState";
import { WaitingState } from "./WaitingState";

export type PanelState = "ready" | "loading" | "empty" | "waiting" | "error" | "stale";

export function Panel({
  title,
  meta,
  actions,
  state = "ready",
  stateMessage,
  onRetry,
  children,
  className,
  bodyClassName,
}: {
  title?: string;
  meta?: ReactNode;
  actions?: ReactNode;
  state?: PanelState;
  stateMessage?: string;
  onRetry?: () => void;
  children?: ReactNode;
  className?: string;
  bodyClassName?: string;
}) {
  return (
    <section
      className={cn(
        // min-w-0: a panel in a grid or flex track may shrink below its content's width.
        "flex min-w-0 flex-col rounded-md border border-line bg-surface-1",
        state === "stale" && "border-attention/25",
        className,
      )}
    >
      {(title || actions || meta) && (
        <header className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2 border-b border-line px-4 py-3">
          <div className="flex items-baseline gap-2 min-w-0">
            {title && <h2 className="truncate text-sm font-semibold text-ink-strong">{title}</h2>}
            {meta && <span className="truncate text-xs text-ink-faint">{meta}</span>}
          </div>
          {actions && <div className="flex max-w-full flex-wrap items-center gap-1.5">{actions}</div>}
        </header>
      )}
      <div className={cn("flex-1 p-4", bodyClassName)}>
        {state === "loading" && (
          <div className="flex flex-col gap-2">
            <Skeleton className="h-4 w-3/5" />
            <Skeleton className="h-4 w-4/5" />
            <Skeleton className="h-4 w-2/5" />
          </div>
        )}
        {state === "empty" && <EmptyState title={stateMessage ?? "Nothing here yet"} />}
        {state === "waiting" && <WaitingState description={stateMessage} />}
        {state === "error" && <ErrorState description={stateMessage} onRetry={onRetry} />}
        {(state === "ready" || state === "stale") && children}
      </div>
    </section>
  );
}
