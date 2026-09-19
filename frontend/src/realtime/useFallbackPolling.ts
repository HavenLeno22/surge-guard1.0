import { useEffect } from "react";

import { camerasApi, decisionsApi, siteApi, systemApi } from "@/api/platform";

import type { FallbackBatch } from "./reducers";
import { useLive } from "./store";

const POLL_INTERVAL_MS = 5_000;
/** Per-camera requests are bounded, so a large site cannot turn polling into a flood. */
const MAX_POLLED_CAMERAS = 4;

function fulfilled<T>(results: PromiseSettledResult<T>[]): T[] {
  return results.flatMap((result) => (result.status === "fulfilled" ? [result.value] : []));
}

/**
 * REST polling while the socket is down.
 *
 * The socket is the primary path; this only runs after it has failed to stay
 * connected, stops the moment it is live again, and writes through the same
 * reducers so the two paths cannot disagree. Paused while the tab is hidden.
 */
export function useFallbackPolling(): void {
  const linkState = useLive((state) => state.link.state);
  const active = linkState === "reconnecting" || linkState === "failed";

  useEffect(() => {
    if (!active) return;
    const controller = new AbortController();
    const { signal } = controller;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const schedule = () => {
      if (!signal.aborted) timer = setTimeout(poll, POLL_INTERVAL_MS);
    };

    async function poll() {
      if (document.visibilityState === "hidden") {
        schedule();
        return;
      }
      const batch: FallbackBatch = {};
      const [cameras, site, health, timeline] = await Promise.allSettled([
        camerasApi.list(signal),
        siteApi.analytics(signal),
        systemApi.health(signal),
        decisionsApi.timeline(50, signal),
      ]);
      if (signal.aborted) return;

      if (cameras.status === "fulfilled") {
        batch.cameras = cameras.value.cameras;
        const ids = cameras.value.cameras
          .filter((camera) => camera.enabled)
          .slice(0, MAX_POLLED_CAMERAS)
          .map((camera) => camera.camera_id);
        const [analyses, decisions] = await Promise.all([
          Promise.allSettled(ids.map((id) => camerasApi.analysis(id, signal))),
          Promise.allSettled(ids.map((id) => camerasApi.decisions(id, signal))),
        ]);
        if (signal.aborted) return;
        batch.analyses = fulfilled(analyses);
        batch.decisions = fulfilled(decisions);
      }
      if (site.status === "fulfilled") batch.site = site.value;
      if (health.status === "fulfilled") batch.health = health.value;
      if (timeline.status === "fulfilled") batch.timeline = timeline.value.entries;

      useLive.getState().receiveFallback(batch, Date.now());
      schedule();
    }

    void poll();
    return () => {
      controller.abort();
      if (timer !== null) clearTimeout(timer);
    };
  }, [active]);
}
