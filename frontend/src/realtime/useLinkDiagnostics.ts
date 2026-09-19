import { useEffect, useState } from "react";

import { getSocketClient } from "./RealtimeProvider";
import type { LinkSnapshot } from "./socketClient";
import { useLive } from "./store";

/**
 * The link with its per-message counters current, for diagnostics.
 *
 * The store only hears about the link when its state or staleness changes, so
 * an incoming message does not wake every subscriber. Message counts and the
 * last-message time live on the running client, and are read here on a timer.
 */
export function useLinkDiagnostics(intervalMs = 1000): LinkSnapshot {
  const storeLink = useLive((state) => state.link);
  const [, setTick] = useState(0);

  useEffect(() => {
    const timer = setInterval(() => setTick((tick) => tick + 1), intervalMs);
    return () => clearInterval(timer);
  }, [intervalMs]);

  return getSocketClient()?.snapshot ?? storeLink;
}
