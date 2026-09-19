import { useNow } from "@/lib/hooks/useNow";
import type { Camera } from "@/types/contracts";

import type { TimedAnalysis } from "./reducers";
import { useLive } from "./store";

/**
 * Whether a camera's figures may be shown, and how fresh they are.
 *
 * The store keeps a camera's last analysis after the camera stops producing
 * them, so reading it directly would present an offline camera's final frame as
 * the present. An offline or disabled camera shows no figures at all (never its
 * last values, never zero); a camera whose analyses have stopped arriving shows
 * them marked with their age.
 */
export interface CameraFigures {
  /** Safe to display: `null` when there is none yet, or when it is withheld. */
  analysis: TimedAnalysis | null;
  /** Why figures are withheld (camera offline or disabled), for the view to say so. */
  withheldReason: string | null;
  /** Seconds since the shown analysis arrived, once that is past the stale threshold. */
  staleSeconds: number | null;
}

export function cameraFigures(
  camera: Camera | undefined,
  latest: TimedAnalysis | undefined,
  now: number,
  staleAfterSeconds: number,
): CameraFigures {
  if (camera && (camera.status === "OFFLINE" || camera.status === "DISABLED")) {
    const name = camera.name || camera.display_id;
    return {
      analysis: null,
      withheldReason:
        camera.status === "DISABLED"
          ? `${name} is disabled, so it has no figures to show.`
          : `${name} is offline. Its figures are withheld until it reconnects.`,
      staleSeconds: null,
    };
  }
  if (!latest) return { analysis: null, withheldReason: null, staleSeconds: null };

  const ageSeconds = Math.max(0, (now - latest.receivedAt) / 1000);
  return {
    analysis: latest,
    withheldReason: null,
    staleSeconds: ageSeconds > staleAfterSeconds ? ageSeconds : null,
  };
}

/** {@link cameraFigures} for one camera from the live store, re-checked every few seconds. */
export function useCameraFigures(cameraId: string | null | undefined): CameraFigures {
  const camera = useLive((state) => (cameraId ? state.cameras[cameraId] : undefined));
  const latest = useLive((state) => (cameraId ? state.analyses[cameraId] : undefined));
  const staleAfterSeconds = useLive((state) => state.link.staleAfterSeconds);
  const now = useNow(5000);
  return cameraFigures(camera, latest, now, staleAfterSeconds);
}
