import { useEffect, useRef, useState } from "react";

import { cameraSnapshotUrl } from "@/api/platform";
import type { StreamLayer } from "@/types/contracts";
import { cn } from "@/lib/cn";
import { useTabVisible } from "@/lib/hooks/useTabVisible";

/**
 * A still refreshed on an interval instead of an open MJPEG connection - what
 * camera grid tiles use, so a dozen tiles cost a dozen short requests instead
 * of a dozen held-open sockets (spec s4: at most two live streams at once).
 */
export function SnapshotImage({
  cameraId,
  layers,
  intervalMs = 4000,
  active = true,
  alt,
  className,
}: {
  cameraId: string;
  layers: StreamLayer[];
  intervalMs?: number;
  active?: boolean;
  alt: string;
  className?: string;
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [nonce, setNonce] = useState(0);
  const [visible, setVisible] = useState(true);
  const tabVisible = useTabVisible();
  // 503 while the camera has no frame (offline, connecting): say so instead of a broken image.
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const el = containerRef.current;
    if (!el || typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver(([entry]) => setVisible(entry?.isIntersecting ?? true), {
      threshold: 0.1,
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const running = active && visible && tabVisible;

  useEffect(() => {
    if (!running) return;
    // The first frame comes from mounting the <img> itself; this only
    // schedules the refreshes after it.
    const timer = setInterval(() => setNonce((n) => n + 1), intervalMs);
    return () => clearInterval(timer);
  }, [running, intervalMs]);

  return (
    <div ref={containerRef} className={cn("relative aspect-video w-full overflow-hidden bg-canvas", className)}>
      {running && (
        <img
          src={cameraSnapshotUrl(cameraId, layers, nonce)}
          alt={alt}
          className={cn("h-full w-full object-cover", failed && "invisible")}
          loading="lazy"
          onLoad={() => setFailed(false)}
          onError={() => setFailed(true)}
        />
      )}
      {failed && (
        <p className="absolute inset-0 flex items-center justify-center px-4 text-center text-xs text-ink-faint">
          No picture from this camera right now
        </p>
      )}
    </div>
  );
}
