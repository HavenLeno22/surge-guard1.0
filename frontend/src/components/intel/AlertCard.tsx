import type { SiteAlert } from "@/types/contracts";
import { SeverityMark } from "@/components/status/SeverityMark";
import { cn } from "@/lib/cn";
import { ALERT_KIND_LABEL } from "@/lib/labels";
import { SEVERITY_TONE } from "@/lib/status";

export function AlertCard({
  alert,
  cameraName,
  className,
}: {
  alert: SiteAlert;
  /** The display name of `alert.camera_id`, when the caller knows it. */
  cameraName?: string;
  className?: string;
}) {
  const tone = SEVERITY_TONE[alert.severity];
  return (
    <div
      className={cn(
        "flex flex-col gap-1.5 rounded-control border px-3 py-2.5",
        tone === "critical" ? "border-critical/30 bg-critical/6" : tone === "attention" ? "border-attention/30 bg-attention/6" : "border-line bg-surface-2/60",
        className,
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="text-sm font-medium text-ink">{alert.title}</span>
        <SeverityMark severity={alert.severity} />
      </div>
      <p className="text-xs text-ink-muted">{alert.explanation}</p>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5 text-2xs text-ink-faint">
        <span>{ALERT_KIND_LABEL[alert.kind]}</span>
        {alert.camera_id && <span className="text-ink-muted">{cameraName ?? alert.camera_id}</span>}
      </div>
      {alert.evidence.length > 0 && (
        <ul className="mt-0.5 list-inside list-disc text-2xs text-ink-faint">
          {alert.evidence.map((line, index) => (
            <li key={index}>{line}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
