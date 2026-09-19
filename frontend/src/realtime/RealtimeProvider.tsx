import { type ReactNode, useEffect } from "react";

import { UNAUTHORIZED_EVENT } from "@/api/client";

import { SocketClient, commandCenterUrl } from "./socketClient";
import { useLive } from "./store";
import { useFallbackPolling } from "./useFallbackPolling";

let activeClient: SocketClient | null = null;

/** The running socket client, for diagnostics and a manual retry. */
export function getSocketClient(): SocketClient | null {
  return activeClient;
}

/**
 * Owns the Command Center socket for as long as a signed-in operator is in the app.
 *
 * Mounted inside the auth gate, so the socket never opens for a visitor who is
 * not signed in, and closes the moment they sign out.
 */
export function RealtimeProvider({ children }: { children: ReactNode }) {
  useEffect(() => {
    const client = new SocketClient({
      url: () => commandCenterUrl(),
      onEnvelope: (envelope, receivedAt) => useLive.getState().receive(envelope, receivedAt),
      onLink: (link) => {
        useLive.getState().setLink(link);
        if (link.state === "unauthorized") {
          window.dispatchEvent(new CustomEvent(UNAUTHORIZED_EVENT));
        }
      },
    });
    activeClient = client;
    client.start();
    return () => {
      client.stop();
      if (activeClient === client) activeClient = null;
      useLive.getState().reset();
    };
  }, []);

  useFallbackPolling();

  return children;
}
