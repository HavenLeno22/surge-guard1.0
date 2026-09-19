import { toast } from "sonner";

import { LayerToggle } from "@/components/video/LayerToggle";
import { Switch } from "@/ui/Switch";
import { usePreferences } from "./usePreferences";

export function PreferencesPanel() {
  const [preferences, setPreferences] = usePreferences();

  async function toggleNotifications(enabled: boolean) {
    if (!enabled) {
      setPreferences({ desktopNotifications: false });
      return;
    }
    if (typeof Notification === "undefined") {
      toast.error("This browser does not support desktop notifications.");
      return;
    }
    const permission = await Notification.requestPermission();
    if (permission !== "granted") {
      toast.error("Notification permission was not granted.");
      return;
    }
    setPreferences({ desktopNotifications: true });
  }

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-col gap-2">
        <span className="text-sm text-ink-secondary">Default overlays</span>
        <LayerToggle
          value={preferences.defaultLayers}
          onChange={(defaultLayers) => setPreferences({ defaultLayers })}
        />
        <p className="text-xs text-ink-faint">Applied when a stream view opens. Stored on this device only.</p>
      </div>

      <div className="flex items-center justify-between gap-3">
        <span className="text-sm text-ink-secondary">Desktop notifications for critical alerts</span>
        <Switch
          aria-label="Desktop notifications for critical alerts"
          checked={preferences.desktopNotifications}
          onCheckedChange={(checked) => void toggleNotifications(checked)}
        />
      </div>
    </div>
  );
}
