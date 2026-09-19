import { KeyValueList } from "@/components/data/KeyValueList";
import { formatInteger } from "@/lib/format";
import { AGGREGATION_LABEL } from "@/lib/labels";
import type { SiteHeadcount } from "@/types/contracts";

export function HeadcountExplainer({
  headcount,
  nameFor,
}: {
  headcount: SiteHeadcount;
  nameFor: (cameraId: string) => string;
}) {
  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-baseline gap-3">
        <span className="readout text-4xl text-ink-strong">
          {headcount.value === null ? "—" : formatInteger(headcount.value)}
        </span>
        <span className="text-sm text-ink-muted">{headcount.label}</span>
      </div>
      {headcount.upper_bound !== null && headcount.upper_bound !== headcount.value && (
        <p className="text-xs text-ink-faint">Up to {formatInteger(headcount.upper_bound)} accounting for overlap.</p>
      )}
      <p className="text-sm text-ink-secondary">{headcount.explanation}</p>
      <KeyValueList
        items={[
          { label: "Aggregation", value: AGGREGATION_LABEL[headcount.aggregation] },
          { label: "Contributing cameras", value: String(headcount.contributing_camera_ids.length) },
          { label: "Missing cameras", value: headcount.missing_camera_ids.length ? headcount.missing_camera_ids.map(nameFor).join(", ") : "None" },
        ]}
      />
      {headcount.areas.length > 0 && (
        <div className="flex flex-col gap-1.5">
          <span className="text-xs text-ink-faint">Coverage areas</span>
          {headcount.areas.map((area) => (
            <div key={area.coverage_area} className="flex items-center justify-between text-xs text-ink-secondary">
              <span>
                {area.coverage_area} {area.overlapping && <span className="text-ink-faint">(overlapping)</span>}
              </span>
              <span className="readout">
                {formatInteger(area.value)}
                {area.upper_bound !== area.value && ` / up to ${formatInteger(area.upper_bound)}`}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
