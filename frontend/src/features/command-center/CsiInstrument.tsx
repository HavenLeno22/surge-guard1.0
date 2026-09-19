import { CsiGauge } from "@/components/charts/CsiGauge";
import { IndicatorBars } from "@/components/charts/IndicatorBars";
import { ConfidenceMeter } from "@/components/status/ConfidenceMeter";
import { StaleBadge } from "@/components/status/StaleBadge";
import { Panel } from "@/components/data/Panel";
import type { StabilityAssessment } from "@/types/contracts";

export function CsiInstrument({
  assessment,
  withheldReason = null,
  staleSeconds = null,
}: {
  assessment: StabilityAssessment | null;
  withheldReason?: string | null;
  staleSeconds?: number | null;
}) {
  return (
    <Panel
      title="Crowd Stability Index"
      meta={staleSeconds !== null ? <StaleBadge isStale ageSeconds={staleSeconds} /> : undefined}
      state={withheldReason ? "empty" : !assessment ? "waiting" : staleSeconds !== null ? "stale" : "ready"}
      stateMessage={withheldReason ?? "No analysis yet for this camera."}
    >
      {assessment && (
        <div className="flex flex-col items-center gap-5 sm:flex-row sm:items-start sm:justify-between">
          <CsiGauge value={assessment.csi_smoothed} />
          <div className="flex w-full flex-col gap-4 sm:max-w-xs">
            <IndicatorBars readings={assessment.breakdown.readings} />
            <ConfidenceMeter confidence={assessment.confidence} />
          </div>
        </div>
      )}
    </Panel>
  );
}
