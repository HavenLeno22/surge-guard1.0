import type { CameraConnectionStatus } from "@/types/contracts";
import { cn } from "@/lib/cn";
import { CAMERA_STATUS_LABEL } from "@/lib/labels";
import { CAMERA_STATUS_PULSES, CAMERA_STATUS_TONE, TONE_BG, TONE_TEXT } from "@/lib/status";

export function CameraStatus({
  status,
  className,
}: {
  status: CameraConnectionStatus;
  className?: string;
}) {
  const tone = CAMERA_STATUS_TONE[status];
  return (
    <span className={cn("inline-flex items-center gap-1.5 text-xs", TONE_TEXT[tone], className)}>
      <span
        className={cn(
          "size-1.5 rounded-full",
          TONE_BG[tone],
          CAMERA_STATUS_PULSES[status] && "animate-breathe",
        )}
      />
      {CAMERA_STATUS_LABEL[status]}
    </span>
  );
}
