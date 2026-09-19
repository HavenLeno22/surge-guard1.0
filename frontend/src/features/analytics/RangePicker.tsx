import type { SourceMode } from "@/types/contracts";
import { cn } from "@/lib/cn";
import { RANGE_PRESETS, type HistoryRange } from "./historyRange";

const segmentClass = (selected: boolean) =>
  cn(
    "min-h-8 rounded-sm px-2.5 py-1 text-xs font-medium transition-colors duration-120 ease-out-soft",
    selected ? "bg-surface-2 text-ink-strong" : "text-ink-muted hover:text-ink",
  );

export function RangePicker({
  range,
  onRangeChange,
  sourceMode,
  onSourceModeChange,
}: {
  range: HistoryRange;
  onRangeChange: (range: HistoryRange) => void;
  /** `null` while the deployment's own mode is not known yet. */
  sourceMode: SourceMode | null;
  onSourceModeChange: (mode: SourceMode) => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-4">
      <fieldset className="inline-flex min-w-0 rounded-control border border-line-strong p-0.5">
        <legend className="sr-only">Range</legend>
        {RANGE_PRESETS.map((preset) => (
          <button
            key={preset.label}
            type="button"
            aria-pressed={preset.label === range.label}
            onClick={() => onRangeChange(preset)}
            className={segmentClass(preset.label === range.label)}
          >
            {preset.label}
          </button>
        ))}
      </fieldset>
      <fieldset className="inline-flex min-w-0 rounded-control border border-line-strong p-0.5">
        <legend className="sr-only">Source Mode</legend>
        {(["LIVE", "DEMO"] as SourceMode[]).map((mode) => (
          <button
            key={mode}
            type="button"
            aria-pressed={mode === sourceMode}
            onClick={() => onSourceModeChange(mode)}
            className={segmentClass(mode === sourceMode)}
          >
            {mode === "LIVE" ? "Live" : "Demonstration"}
          </button>
        ))}
      </fieldset>
    </div>
  );
}
