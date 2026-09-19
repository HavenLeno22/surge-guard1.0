import { useCallback, useState } from "react";

import type { StreamLayer } from "@/types/contracts";

export interface Preferences {
  defaultLayers: StreamLayer[];
  desktopNotifications: boolean;
}

const DEFAULT_PREFERENCES: Preferences = {
  defaultLayers: ["hud", "tracks", "zones"],
  desktopNotifications: false,
};

const STORAGE_KEY = "surgeguard:preferences";

function load(): Preferences {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULT_PREFERENCES;
    return { ...DEFAULT_PREFERENCES, ...(JSON.parse(raw) as Partial<Preferences>) };
  } catch {
    return DEFAULT_PREFERENCES;
  }
}

/** Local, per-device preferences - never sent to the backend. */
export function usePreferences(): [Preferences, (patch: Partial<Preferences>) => void] {
  const [preferences, setPreferences] = useState<Preferences>(load);

  const update = useCallback((patch: Partial<Preferences>) => {
    setPreferences((previous) => {
      const next = { ...previous, ...patch };
      try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
      } catch {
        // Private browsing or a full quota: the preference just does not persist.
      }
      return next;
    });
  }, []);

  return [preferences, update];
}
