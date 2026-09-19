import { CameraStatus } from "@/components/status/CameraStatus";
import { cn } from "@/lib/cn";
import { useLive } from "@/realtime/store";

export function FocusCameraSwitcher({
  focusCameraId,
  onSelect,
}: {
  focusCameraId: string | null;
  onSelect: (cameraId: string) => void;
}) {
  const cameraOrder = useLive((state) => state.cameraOrder);
  const cameras = useLive((state) => state.cameras);

  if (cameraOrder.length <= 1) return null;

  return (
    <div className="flex flex-wrap gap-1.5" role="tablist" aria-label="Camera">
      {cameraOrder.map((cameraId) => {
        const camera = cameras[cameraId];
        if (!camera) return null;
        const active = cameraId === focusCameraId;
        return (
          <button
            key={cameraId}
            type="button"
            role="tab"
            aria-selected={active}
            onClick={() => onSelect(cameraId)}
            className={cn(
              "flex items-center gap-2 rounded-control border px-2.5 py-1.5 text-xs transition-colors duration-120 ease-out-soft",
              active
                ? "border-line-strong bg-surface-2 text-ink-strong"
                : "border-line text-ink-muted hover:bg-surface-2/60 hover:text-ink",
            )}
          >
            {camera.name}
            <CameraStatus status={camera.status} className="text-2xs" />
          </button>
        );
      })}
    </div>
  );
}
