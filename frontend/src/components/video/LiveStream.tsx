import { useCallback, useEffect, useRef, useState } from "react";

import { cameraStreamUrl } from "@/api/platform";
import type { StreamLayer } from "@/types/contracts";
import { cn } from "@/lib/cn";
import { useTabVisible } from "@/lib/hooks/useTabVisible";
import { Spinner } from "@/ui/Spinner";

type Phase = "connecting" | "loaded" | "failed";
const MAX_RETRIES = 3;
/** A 1x1 transparent GIF: loads instantly and fires no error event. */
const BLANK_IMAGE = "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7";

interface LiveStreamProps {
  cameraId: string;
  layers: StreamLayer[];
  running: boolean;
  statusDetail?: string | null;
  className?: string;
}

/**
 * The annotated MJPEG feed for one camera. Only ever mounts an `<img>` while
 * `running`, so an unfocused tile closes its connection instead of holding
 * one of the browser's ~6 per-origin slots open for nothing (spec s4). A hidden
 * browser tab counts as not running too: otherwise a few Command Center tabs
 * left in the background use up every slot and the visible tab's video never
 * connects.
 *
 * Keyed on identity so a camera or layer change gets a clean retry sequence
 * by remounting, rather than an effect resetting state on every change.
 */
export function LiveStream(props: LiveStreamProps) {
  const tabVisible = useTabVisible();
  const running = props.running && tabVisible;
  const resetKey = `${props.cameraId}:${running}:${props.layers.join(",")}`;
  return <LiveStreamSession key={resetKey} {...props} running={running} />;
}

function LiveStreamSession({ cameraId, layers, running, statusDetail, className }: LiveStreamProps) {
  const [phase, setPhase] = useState<Phase>("connecting");
  const [nonce, setNonce] = useState(0);
  const attemptRef = useRef(0);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, []);

  const streamUrl = cameraStreamUrl(cameraId, layers, nonce);

  // Removing an <img> does not end its MJPEG download in Chrome: the response
  // keeps streaming into a detached element and holds one of the ~6 per-origin
  // connections until the tab closes. A few camera or layer switches used every
  // slot, and the next stream stuck on "Connecting video". Pointing the element
  // at a blank image as it leaves the page aborts the download. Attaching sets
  // the stream back, because StrictMode detaches and re-attaches refs in dev.
  const attachStream = useCallback(
    (image: HTMLImageElement | null) => {
      if (!image) return;
      if (image.getAttribute("src") !== streamUrl) image.src = streamUrl;
      return () => {
        image.src = BLANK_IMAGE;
      };
    },
    [streamUrl],
  );

  function handleError() {
    const previous = attemptRef.current;
    attemptRef.current = previous + 1;
    if (attemptRef.current > MAX_RETRIES) {
      setPhase("failed");
      return;
    }
    const delay = 500 * 2 ** previous;
    timerRef.current = setTimeout(() => {
      setNonce((n) => n + 1);
      setPhase("connecting");
    }, delay);
  }

  return (
    <div className={cn("relative aspect-video w-full overflow-hidden rounded-md bg-canvas", className)}>
      {running && phase !== "failed" && (
        <img
          key={nonce}
          ref={attachStream}
          src={streamUrl}
          alt={`Live view: camera ${cameraId}`}
          className="h-full w-full object-contain"
          onLoad={() => setPhase("loaded")}
          onError={handleError}
        />
      )}
      {(!running || phase === "connecting") && (
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 text-ink-faint">
          {running && <Spinner size="sm" />}
          <span className="text-xs">{running ? "Connecting video…" : "Video paused"}</span>
        </div>
      )}
      {running && phase === "failed" && (
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-1 px-4 text-center text-ink-faint">
          <span className="text-xs font-medium text-ink-secondary">Video unavailable</span>
          {statusDetail && <span className="text-2xs">{statusDetail}</span>}
        </div>
      )}
    </div>
  );
}
