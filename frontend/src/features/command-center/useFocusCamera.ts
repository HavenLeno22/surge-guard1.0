import { useCallback } from "react";
import { useSearchParams } from "react-router";

import { useLive } from "@/realtime/store";

/** The focused camera lives in the URL (`?camera=`), defaulting to the primary. */
export function useFocusCamera(): [string | null, (cameraId: string) => void] {
  const [params, setParams] = useSearchParams();
  const primaryCameraId = useLive((state) => state.primaryCameraId);
  const cameraOrder = useLive((state) => state.cameraOrder);

  const requested = params.get("camera");
  const focusCameraId = requested && cameraOrder.includes(requested) ? requested : primaryCameraId;

  const setFocusCamera = useCallback(
    (cameraId: string) => {
      setParams(
        (previous) => {
          const next = new URLSearchParams(previous);
          next.set("camera", cameraId);
          return next;
        },
        { replace: true },
      );
    },
    [setParams],
  );

  return [focusCameraId, setFocusCamera];
}
