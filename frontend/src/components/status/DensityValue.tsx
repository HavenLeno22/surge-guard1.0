import { formatDensity } from "@/lib/format";
import { cn } from "@/lib/cn";

/** Uncalibrated density is always "relative", never presented as persons per square metre. */
export function DensityValue({
  value,
  isMetric,
  className,
}: {
  value: number | null | undefined;
  isMetric: boolean;
  className?: string;
}) {
  const display = formatDensity(value, isMetric);
  return (
    <span className={cn("readout", className)}>
      {display.value}
      <span className="ml-1 text-xs text-ink-faint">{display.unit}</span>
    </span>
  );
}
