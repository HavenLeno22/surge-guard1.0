/**
 * The Command Center socket.
 *
 * One connection carries every live update. The contract (backend
 * realtime/envelope.py) has three properties this client exists to honour:
 *
 * - **Snapshot first.** The first message is full state, `seq` 0. Applying it
 *   resets everything, so a reconnecting client is correct immediately.
 * - **Sequence numbers.** A gap means a message was missed. The client asks for
 *   a fresh snapshot (`resync`) once per gap rather than reconnecting.
 * - **Staleness.** Silence longer than `stale_after_seconds` is shown, never
 *   hidden: a frozen display that looks live is the failure this platform exists
 *   to prevent. Silence well past that closes the socket and reconnects, because
 *   a sleeping laptop can leave a socket "open" that nothing will ever arrive on.
 *
 * Close code 4401 means the session is not signed in: the client stops and
 * reports it, instead of retrying a connection that cannot succeed.
 */

import type { Envelope, WsEventType } from "@/types/realtime";

export type LinkState =
  | "idle"
  | "connecting"
  | "syncing"
  | "live"
  | "reconnecting"
  | "offline"
  | "failed"
  | "unauthorized";

export interface LinkSnapshot {
  state: LinkState;
  /** Consecutive failed connection attempts since the last snapshot. */
  attempts: number;
  /** When the next automatic attempt happens (epoch ms), while reconnecting. */
  nextRetryAt: number | null;
  lastMessageAt: number | null;
  staleAfterSeconds: number;
  isStale: boolean;
  connectedAt: number | null;
  resyncs: number;
  messages: number;
  lastCloseCode: number | null;
}

export interface SocketLike {
  readonly readyState: number;
  send(data: string): void;
  close(code?: number, reason?: string): void;
  onopen: ((event: Event) => void) | null;
  onmessage: ((event: MessageEvent) => void) | null;
  onclose: ((event: CloseEvent) => void) | null;
  onerror: ((event: Event) => void) | null;
}

export interface SocketClientOptions {
  url: () => string;
  onEnvelope: (envelope: Envelope, receivedAt: number) => void;
  onLink: (link: LinkSnapshot) => void;
  createSocket?: (url: string) => SocketLike;
  now?: () => number;
  setTimer?: (callback: () => void, ms: number) => unknown;
  clearTimer?: (handle: unknown) => void;
  random?: () => number;
  isOnline?: () => boolean;
  initialDelayMs?: number;
  maxDelayMs?: number;
  maxAttempts?: number;
  staleCheckMs?: number;
  /** Extra silence past the stale threshold before the socket is presumed dead. */
  deadAfterExtraMs?: number;
  /** Register environment listeners (online/offline, visibility). Off in tests. */
  watchEnvironment?: boolean;
}

export const CLOSE_UNAUTHORIZED = 4401;
const CLOSE_PRESUMED_DEAD = 4000;
const OPEN = 1;
const DEFAULT_STALE_AFTER_SECONDS = 30;

export function commandCenterUrl(location: Location = window.location): string {
  const protocol = location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${location.host}/ws/command-center`;
}

export class SocketClient {
  private readonly options: Required<
    Omit<SocketClientOptions, "url" | "onEnvelope" | "onLink">
  > &
    Pick<SocketClientOptions, "url" | "onEnvelope" | "onLink">;
  private socket: SocketLike | null = null;
  private running = false;
  private retryTimer: unknown = null;
  private staleTimer: unknown = null;
  private expectedSeq: number | null = null;
  private awaitingResync = false;
  private link: LinkSnapshot = {
    state: "idle",
    attempts: 0,
    nextRetryAt: null,
    lastMessageAt: null,
    staleAfterSeconds: DEFAULT_STALE_AFTER_SECONDS,
    isStale: false,
    connectedAt: null,
    resyncs: 0,
    messages: 0,
    lastCloseCode: null,
  };
  private readonly handleOnline = () => {
    if (this.running && (this.link.state === "offline" || this.link.state === "reconnecting")) {
      this.connectNow();
    }
  };
  private readonly handleOffline = () => {
    if (this.running && this.link.state !== "live") this.update({ state: "offline" });
  };
  private readonly handleVisibility = () => {
    if (
      this.running &&
      document.visibilityState === "visible" &&
      (this.link.state === "reconnecting" || this.link.state === "failed")
    ) {
      this.retryNow();
    }
  };

  constructor(options: SocketClientOptions) {
    this.options = {
      createSocket: (url) => new WebSocket(url) as unknown as SocketLike,
      now: () => Date.now(),
      setTimer: (callback, ms) => setTimeout(callback, ms),
      clearTimer: (handle) => clearTimeout(handle as ReturnType<typeof setTimeout>),
      random: Math.random,
      isOnline: () => (typeof navigator === "undefined" ? true : navigator.onLine !== false),
      initialDelayMs: 500,
      maxDelayMs: 8_000,
      maxAttempts: 20,
      staleCheckMs: 1_000,
      deadAfterExtraMs: 15_000,
      watchEnvironment: true,
      ...options,
    };
  }

  get snapshot(): LinkSnapshot {
    return this.link;
  }

  start(): void {
    if (this.running) return;
    this.running = true;
    if (this.options.watchEnvironment && typeof window !== "undefined") {
      window.addEventListener("online", this.handleOnline);
      window.addEventListener("offline", this.handleOffline);
      document.addEventListener("visibilitychange", this.handleVisibility);
    }
    this.scheduleStaleCheck();
    this.connect();
  }

  stop(): void {
    if (!this.running) return;
    this.running = false;
    if (this.options.watchEnvironment && typeof window !== "undefined") {
      window.removeEventListener("online", this.handleOnline);
      window.removeEventListener("offline", this.handleOffline);
      document.removeEventListener("visibilitychange", this.handleVisibility);
    }
    this.clearRetry();
    if (this.staleTimer !== null) {
      this.options.clearTimer(this.staleTimer);
      this.staleTimer = null;
    }
    const socket = this.socket;
    this.socket = null;
    if (socket) {
      socket.onopen = socket.onmessage = socket.onclose = socket.onerror = null;
      socket.close(1000, "Client stopped");
    }
    this.expectedSeq = null;
    this.update({ state: "idle", nextRetryAt: null, connectedAt: null, isStale: false });
  }

  /** Reconnect immediately, forgetting earlier failures - an operator asked for it. */
  retryNow(): void {
    if (!this.running) return;
    this.update({ attempts: 0 });
    this.connectNow();
  }

  // -- Connection -------------------------------------------------------------

  private connectNow(): void {
    this.clearRetry();
    if (this.socket) {
      const socket = this.socket;
      this.socket = null;
      socket.onopen = socket.onmessage = socket.onclose = socket.onerror = null;
      socket.close(1000, "Reconnecting");
    }
    this.connect();
  }

  private connect(): void {
    if (!this.running) return;
    if (!this.options.isOnline()) {
      this.update({ state: "offline", nextRetryAt: null });
      return;
    }

    this.update({
      state: this.link.attempts > 0 ? "reconnecting" : "connecting",
      nextRetryAt: null,
    });

    let socket: SocketLike;
    try {
      socket = this.options.createSocket(this.options.url());
    } catch {
      this.scheduleReconnect(null);
      return;
    }
    this.socket = socket;
    this.expectedSeq = null;
    this.awaitingResync = false;

    socket.onopen = () => {
      if (this.socket !== socket) return;
      this.update({ state: "syncing", connectedAt: this.options.now() });
    };
    socket.onmessage = (event) => {
      if (this.socket !== socket) return;
      this.receive(socket, event.data);
    };
    socket.onclose = (event) => {
      if (this.socket !== socket) return;
      this.socket = null;
      this.expectedSeq = null;
      if (!this.running) return;
      if (event.code === CLOSE_UNAUTHORIZED) {
        this.update({
          state: "unauthorized",
          connectedAt: null,
          nextRetryAt: null,
          lastCloseCode: event.code,
        });
        return;
      }
      this.scheduleReconnect(event.code);
    };
    socket.onerror = () => {
      // A close event always follows; reconnection is decided there.
    };
  }

  private scheduleReconnect(closeCode: number | null): void {
    const attempts = this.link.attempts + 1;
    if (attempts > this.options.maxAttempts) {
      this.update({
        state: "failed",
        attempts,
        connectedAt: null,
        nextRetryAt: null,
        lastCloseCode: closeCode,
      });
      return;
    }
    const base = Math.min(
      this.options.initialDelayMs * 2 ** (attempts - 1),
      this.options.maxDelayMs,
    );
    const jitter = 1 + (this.options.random() * 0.4 - 0.2);
    const delay = Math.round(base * jitter);
    this.update({
      state: this.options.isOnline() ? "reconnecting" : "offline",
      attempts,
      connectedAt: null,
      nextRetryAt: this.options.now() + delay,
      lastCloseCode: closeCode,
    });
    this.clearRetry();
    this.retryTimer = this.options.setTimer(() => {
      this.retryTimer = null;
      this.connect();
    }, delay);
  }

  private clearRetry(): void {
    if (this.retryTimer !== null) {
      this.options.clearTimer(this.retryTimer);
      this.retryTimer = null;
    }
  }

  // -- Messages -----------------------------------------------------------------

  private receive(socket: SocketLike, raw: unknown): void {
    if (typeof raw !== "string") return;
    let envelope: Envelope;
    try {
      envelope = JSON.parse(raw) as Envelope;
    } catch {
      return;
    }
    if (!envelope || typeof envelope.type !== "string" || typeof envelope.seq !== "number") return;

    const receivedAt = this.options.now();
    const type: WsEventType = envelope.type;

    if (type === "snapshot") {
      this.expectedSeq = envelope.seq + 1;
      this.awaitingResync = false;
      const staleAfter = (envelope.data as { stale_after_seconds?: unknown } | null)
        ?.stale_after_seconds;
      this.update({
        state: "live",
        attempts: 0,
        nextRetryAt: null,
        lastMessageAt: receivedAt,
        isStale: false,
        messages: this.link.messages + 1,
        staleAfterSeconds:
          typeof staleAfter === "number" && staleAfter > 0
            ? staleAfter
            : this.link.staleAfterSeconds,
      });
      this.options.onEnvelope(envelope, receivedAt);
      return;
    }

    if (this.expectedSeq !== null && envelope.seq !== this.expectedSeq && !this.awaitingResync) {
      this.awaitingResync = true;
      this.send(socket, "resync");
      this.update({ resyncs: this.link.resyncs + 1 });
    }
    this.expectedSeq = envelope.seq + 1;

    // Counters change on every message. They are kept on the snapshot for
    // diagnostics but only announced when staleness actually flips, so a
    // listener is not woken several times a second for nothing.
    const wasStale = this.link.isStale;
    this.link = {
      ...this.link,
      lastMessageAt: receivedAt,
      isStale: false,
      messages: this.link.messages + 1,
    };
    if (wasStale) this.options.onLink(this.link);

    if (type === "heartbeat") {
      this.send(socket, "pong");
    }
    this.options.onEnvelope(envelope, receivedAt);
  }

  private send(socket: SocketLike, action: "resync" | "pong"): void {
    if (socket.readyState !== OPEN) return;
    try {
      socket.send(JSON.stringify({ action, data: {} }));
    } catch {
      // The close handler will deal with a socket that can no longer send.
    }
  }

  // -- Staleness ------------------------------------------------------------------

  private scheduleStaleCheck(): void {
    this.staleTimer = this.options.setTimer(() => {
      this.staleTimer = null;
      if (!this.running) return;
      this.checkStale();
      this.scheduleStaleCheck();
    }, this.options.staleCheckMs);
  }

  private checkStale(): void {
    const { lastMessageAt, staleAfterSeconds, state, isStale } = this.link;
    if ((state !== "live" && state !== "syncing") || lastMessageAt === null) return;
    const silentMs = this.options.now() - lastMessageAt;
    const threshold = staleAfterSeconds * 1000;
    if (silentMs > threshold && !isStale) this.update({ isStale: true });
    if (silentMs > threshold + this.options.deadAfterExtraMs && this.socket) {
      // Do not wait for a closing handshake the network may never deliver.
      const socket = this.socket;
      this.socket = null;
      this.expectedSeq = null;
      socket.onopen = socket.onmessage = socket.onclose = socket.onerror = null;
      try {
        socket.close(CLOSE_PRESUMED_DEAD, "No messages; presumed dead");
      } catch {
        // Already closing.
      }
      this.scheduleReconnect(CLOSE_PRESUMED_DEAD);
    }
  }

  private update(patch: Partial<LinkSnapshot>): void {
    this.link = { ...this.link, ...patch };
    this.options.onLink(this.link);
  }
}
