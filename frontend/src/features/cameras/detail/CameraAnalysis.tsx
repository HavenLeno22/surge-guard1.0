import type { ReactNode } from "react";

import { EvidenceList } from "@/components/intel/EvidenceList";
import { CountMethodTag } from "@/components/status/CountMethodTag";
import { DensityValue } from "@/components/status/DensityValue";
import { formatInteger, formatNumber } from "@/lib/format";
import { useNow } from "@/lib/hooks/useNow";
import type { CameraAnalysis as CameraAnalysisData } from "@/types/contracts";

/** The camera's current crowd summary and evidence - not to be confused with the `CameraAnalysis` contract type. */
export function CameraAnalysisPanel({ analysis }: { analysis: CameraAnalysisData }) {
  const now = useNow(5000);
  const { crowd } = analysis;

  return (
    <div className="flex flex-col gap-4">
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <Stat label="People" value={formatInteger(crowd.person_count)} sub={<CountMethodTag method={crowd.count_method} />} />
        <Stat label="Density" value={<DensityValue value={crowd.density_max} isMetric={crowd.is_metric} />} />
        <Stat
          label="Speed"
          value={formatSpeed(crowd.median_speed, crowd.is_metric)}
          sub={crowd.baseline_speed !== null ? `baseline ${formatSpeed(crowd.baseline_speed, crowd.is_metric)}` : undefined}
        />
        <Stat label="Degraded" value={analysis.degraded ? "Yes" : "No"} sub={analysis.degraded_reason ?? undefined} />
      </div>
      {analysis.evidence && (
        <div>
          <h3 className="mb-2 text-xs font-medium text-ink-faint">Evidence</h3>
          <EvidenceList items={analysis.evidence.items} now={now} />
        </div>
      )}
    </div>
  );
}

/** Metres per second only on a calibrated camera; otherwise the tracker measures image pixels per second. */
function formatSpeed(value: number | null, isMetric: boolean): string {
  if (value === null) return "—";
  return isMetric ? `${formatNumber(value, 2)} m/s` : `${formatNumber(value, 0)} px/s`;
}

function Stat({ label, value, sub }: { label: string; value: ReactNode; sub?: ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-xs text-ink-faint">{label}</span>
      <span className="readout text-lg text-ink-strong">{value}</span>
      {sub && <span className="text-2xs text-ink-faint">{sub}</span>}
    </div>
  );
}
