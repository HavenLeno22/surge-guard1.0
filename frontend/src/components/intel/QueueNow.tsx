import type { QueueFormation, RateSource } from "@/types/contracts";
import { KeyValueList } from "@/components/data/KeyValueList";
import { formatInteger, formatRate, formatWait } from "@/lib/format";
import { FORMATION_LABEL, RATE_SOURCE_DESCRIPTION, RATE_SOURCE_LABEL } from "@/lib/labels";

/**
 * The queue as it is right now. Takes normalised fields rather than the raw
 * contract, so both a per-zone `QueueMetrics` and the pooled site summary can
 * feed the same view.
 */
export function QueueNow({
  personCount,
  formation,
  formationBasis,
  waitMinutes,
  arrivalRate,
  serviceRate,
  rateSource,
  simulated = false,
}: {
  personCount: number;
  formation?: QueueFormation;
  formationBasis?: string[];
  waitMinutes: number | null;
  arrivalRate: number;
  serviceRate: number;
  rateSource: RateSource;
  /** A simulated queue's "measured" rates were counted from synthetic departures, never observed ones. */
  simulated?: boolean;
}) {
  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-baseline gap-2">
        <span className="readout text-2xl text-ink-strong">{formatInteger(personCount)}</span>
        <span className="text-sm text-ink-muted">waiting</span>
        {formation && <span className="ml-1 text-xs text-ink-faint">{FORMATION_LABEL[formation]} formation</span>}
      </div>
      {formationBasis && formationBasis.length > 0 && (
        <p className="text-xs text-ink-faint">{formationBasis.join(", ")}</p>
      )}
      <KeyValueList
        items={[
          { label: "Wait", value: formatWait(waitMinutes, personCount) },
          { label: "Arrivals", value: formatRate(arrivalRate) },
          { label: "Service", value: formatRate(serviceRate) },
          { label: "Rate basis", value: RATE_SOURCE_LABEL[rateSource] },
        ]}
      />
      <p className="text-2xs text-ink-faint">
        {simulated && rateSource === "MEASURED"
          ? "Counted from the simulation's own departures, not observed ones."
          : RATE_SOURCE_DESCRIPTION[rateSource]}
      </p>
    </div>
  );
}
