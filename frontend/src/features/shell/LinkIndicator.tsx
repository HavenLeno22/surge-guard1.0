import { cn } from "@/lib/cn";
import { formatClock } from "@/lib/format";
import { getSocketClient } from "@/realtime/RealtimeProvider";
import type { LinkState } from "@/realtime/socketClient";
import { useLinkDiagnostics } from "@/realtime/useLinkDiagnostics";
import { Tooltip } from "@/ui/Tooltip";

const DOT_CLASS: Record<LinkState, string> = {
  idle: "bg-ink-faint",
  connecting: "bg-ink-muted animate-breathe",
  syncing: "bg-ink-muted animate-breathe",
  live: "bg-stable",
  reconnecting: "bg-attention animate-breathe",
  offline: "bg-ink-faint",
  failed: "bg-critical",
  unauthorized: "bg-critical",
};

const LABEL: Record<LinkState, string> = {
  idle: "Not connected",
  connecting: "Connecting",
  syncing: "Syncing",
  live: "Live",
  reconnecting: "Reconnecting",
  offline: "Offline",
  failed: "Connection failed",
  unauthorized: "Sign-in required",
};

/** The Command Center socket's health, everywhere an operator needs to see it. */
export function LinkIndicator({ className }: { className?: string }) {
  // Diagnostics, so "Last message" in the tooltip keeps moving between state changes.
  const link = useLinkDiagnostics();
  const label = link.isStale && link.state === "live" ? "Stale" : LABEL[link.state];
  const detail =
    link.state === "reconnecting" && link.nextRetryAt
      ? `Retrying at ${formatClock(link.nextRetryAt)} (attempt ${link.attempts})`
      : link.lastMessageAt
        ? `Last message ${formatClock(link.lastMessageAt)}`
        : "No messages yet";

  return (
    <Tooltip content={detail}>
      <button
        type="button"
        onClick={() => {
          if (link.state === "failed" || link.state === "reconnecting") getSocketClient()?.retryNow();
        }}
        className={cn(
          "inline-flex items-center gap-1.5 rounded-xs px-1.5 py-1 text-xs text-ink-secondary",
          (link.state === "failed" || link.state === "reconnecting") && "cursor-pointer hover:bg-surface-2",
          link.isStale && "text-attention",
          className,
        )}
      >
        <span className={cn("size-1.5 rounded-full", link.isStale ? "bg-attention" : DOT_CLASS[link.state])} aria-hidden="true" />
        {label}
      </button>
    </Tooltip>
  );
}
