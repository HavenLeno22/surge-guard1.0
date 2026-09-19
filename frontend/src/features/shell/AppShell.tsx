import { Outlet } from "react-router";

import { getSocketClient } from "@/realtime/RealtimeProvider";
import { useLive } from "@/realtime/store";
import { Button } from "@/ui/Button";
import { Sidebar } from "./Sidebar";
import { TopBar } from "./TopBar";

function ConnectionBanner() {
  const link = useLive((state) => state.link);

  if (link.state === "live" && !link.isStale) return null;

  let message: string | null = null;
  let showRetry = false;
  if (link.state === "reconnecting") message = "Reconnecting to SurgeGuard…";
  else if (link.state === "failed") {
    message = "Lost the live connection to SurgeGuard. Figures that stop refreshing are marked stale.";
    showRetry = true;
  } else if (link.state === "offline") message = "This device is offline.";
  else if (link.state === "live" && link.isStale) message = "No new data from SurgeGuard. Showing the last known state.";
  else if (link.state === "connecting" || link.state === "syncing" || link.state === "idle") return null;

  if (!message) return null;

  return (
    // <output> is a polite live region (role "status"), so a lost or restored link is announced.
    <output className="flex items-center justify-between gap-3 border-b border-attention/30 bg-attention/10 px-4 py-2 text-sm text-attention">
      <span>{message}</span>
      {showRetry && (
        <Button size="sm" variant="secondary" onClick={() => getSocketClient()?.retryNow()}>
          Retry now
        </Button>
      )}
    </output>
  );
}

export function AppShell() {
  return (
    <div className="grid min-h-dvh grid-cols-1 lg:grid-cols-[248px_1fr]">
      <aside className="hidden border-r border-line bg-surface-1/60 lg:block">
        <Sidebar />
      </aside>
      <div className="flex min-h-dvh min-w-0 flex-col">
        <TopBar />
        <ConnectionBanner />
        <main className="min-w-0 flex-1 px-4 py-5 sm:px-6 sm:py-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
