import { useEffect, useState } from "react";

/** Whether this browser tab is showing. Media that holds a connection should pause while it is not. */
export function useTabVisible(): boolean {
  const [visible, setVisible] = useState(() => document.visibilityState === "visible");
  useEffect(() => {
    function handleVisibility() {
      setVisible(document.visibilityState === "visible");
    }
    document.addEventListener("visibilitychange", handleVisibility);
    return () => document.removeEventListener("visibilitychange", handleVisibility);
  }, []);
  return visible;
}
