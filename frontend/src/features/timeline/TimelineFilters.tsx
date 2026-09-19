import type { Severity, TimelineEntryType } from "@/types/contracts";
import { SEVERITY_LABEL, TIMELINE_TYPE_LABEL } from "@/lib/labels";
import { Select } from "@/ui/Select";

export interface TimelineFilterState {
  type: TimelineEntryType | "ALL";
  severity: Severity | "ALL";
  cameraId: string;
}

export function TimelineFilters({
  value,
  onChange,
  cameraOptions,
}: {
  value: TimelineFilterState;
  onChange: (value: TimelineFilterState) => void;
  cameraOptions: { value: string; label: string }[];
}) {
  return (
    <div className="flex flex-wrap gap-3">
      <Select
        aria-label="Filter by type"
        value={value.type}
        onValueChange={(type) => onChange({ ...value, type: type as TimelineFilterState["type"] })}
        options={[
          { value: "ALL", label: "All types" },
          ...(Object.keys(TIMELINE_TYPE_LABEL) as TimelineEntryType[]).map((type) => ({
            value: type,
            label: TIMELINE_TYPE_LABEL[type],
          })),
        ]}
        className="w-44"
      />
      <Select
        aria-label="Filter by severity"
        value={value.severity}
        onValueChange={(severity) => onChange({ ...value, severity: severity as TimelineFilterState["severity"] })}
        options={[
          { value: "ALL", label: "All severities" },
          ...(Object.keys(SEVERITY_LABEL) as Severity[]).map((severity) => ({
            value: severity,
            label: SEVERITY_LABEL[severity],
          })),
        ]}
        className="w-40"
      />
      <Select
        aria-label="Filter by camera"
        value={value.cameraId}
        onValueChange={(cameraId) => onChange({ ...value, cameraId })}
        options={[{ value: "ALL", label: "All cameras" }, ...cameraOptions]}
        className="w-44"
      />
    </div>
  );
}
