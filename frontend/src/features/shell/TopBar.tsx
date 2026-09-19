import { StaleBadge } from "@/components/status/StaleBadge";
import { StateStrip } from "@/components/status/StateStrip";
import { StatusPill } from "@/components/status/StatusPill";
import { formatClock, formatCsi } from "@/lib/format";
import { useNow } from "@/lib/hooks/useNow";
import { useCameraFigures } from "@/realtime/cameraFigures";
import { useLive } from "@/realtime/store";
import { LinkIndicator } from "./LinkIndicator";
import { MobileNav } from "./MobileNav";
import { UserMenu } from "./UserMenu";

export function TopBar() {
  const now = useNow(1000);
  const primaryCameraId = useLive((state) => state.primaryCameraId);
  const { analysis, withheldReason, staleSeconds } = useCameraFigures(primaryCameraId);
  const decision = useLive((state) =>
    primaryCameraId ? state.decisions[primaryCameraId] : undefined,
  );
  // The last report stands in only while it is current: never for an offline
  // camera, and never once the backend itself calls it stale.
  const report = !withheldReason && decision && !decision.is_stale ? decision.report : null;

  const status = analysis?.stability.status ?? report?.status ?? null;
  const csi = analysis?.stability.csi_smoothed ?? report?.csi ?? null;
  const state = decision?.operational_state ?? "MONITORING";

  return (
    <header className="flex h-14 shrink-0 items-center justify-between gap-3 border-b border-line bg-surface-1/80 px-3 backdrop-blur-sm sm:px-5">
      <div className="flex items-center gap-3">
        <MobileNav />
        <StatusPill status={status} />
        <span className="readout hidden text-sm text-ink-secondary sm:inline">
          CSI <span className="text-ink-strong">{formatCsi(csi)}</span>
        </span>
        {staleSeconds !== null && <StaleBadge isStale ageSeconds={staleSeconds} className="hidden sm:inline-flex" />}
        <div className="hidden md:block">
          <StateStrip state={state} compact />
        </div>
      </div>
      <div className="flex items-center gap-3">
        <LinkIndicator className="hidden sm:inline-flex" />
        <span className="readout hidden text-sm text-ink-muted lg:inline">{formatClock(now)}</span>
        <UserMenu />
      </div>
    </header>
  );
}
