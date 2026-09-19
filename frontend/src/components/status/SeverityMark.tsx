import { AlertTriangle, Info, OctagonAlert } from "lucide-react";

import type { Severity } from "@/types/contracts";
import { cn } from "@/lib/cn";
import { SEVERITY_LABEL } from "@/lib/labels";
import { SEVERITY_TONE, TONE_TEXT } from "@/lib/status";

const ICON: Record<Severity, typeof Info> = {
  INFO: Info,
  WARNING: AlertTriangle,
  CRITICAL: OctagonAlert,
};

export function SeverityMark({
  severity,
  showLabel = true,
  className,
}: {
  severity: Severity;
  showLabel?: boolean;
  className?: string;
}) {
  const tone = SEVERITY_TONE[severity];
  const Icon = ICON[severity];
  return (
    <span className={cn("inline-flex items-center gap-1.5 text-xs", TONE_TEXT[tone], className)}>
      <Icon size={13} />
      {showLabel && SEVERITY_LABEL[severity]}
    </span>
  );
}
