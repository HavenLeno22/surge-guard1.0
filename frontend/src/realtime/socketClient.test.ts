import { beforeEach, describe, expect, test } from "vitest";

import type { Envelope } from "@/types/realtime";

import { type LinkSnapshot, SocketClient, type SocketLike } from "./socketClient";

class FakeSocket implements SocketLike {
  readyState = 0;
  sent: string[] = [];
  closedWith: number | null = null;
  onopen: ((event: Event) => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onclose: ((event: CloseEvent) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;

  constructor(readonly url: string) {}

  send(data: string): void {
    this.sent.push(data);
  }

  close(code = 1000): void {
    this.closedWith = code;
  }

  open(): void {
    this.readyState = 1;
    this.onopen?.(new Event("open"));
  }

  message(envelope: Partial<Envelope> & { type: Envelope["type"]; seq: number }): void {
    this.onmessage?.(
      new MessageEvent("message", {
        data: JSON.stringify({ ts: "2026-09-17T10:00:00Z", camera_id: null, data: {}, ...envelope }),
      }),
    );
  }

  serverClose(code: number): void {
    this.readyState = 3;
    this.onclose?.({ code } as CloseEvent);
  }
}

class Harness {
  now = 1_000_000;
  sockets: FakeSocket[] = [];
  timers: { at: number; callback: () => void; id: number; cancelled: boolean }[] = [];
  links: LinkSnapshot[] = [];
  envelopes: Envelope[] = [];
  online = true;
  private nextId = 1;

  readonly client = new SocketClient({
    url: () => "ws://test/ws/command-center",
    onEnvelope: (envelope) => this.envelopes.push(envelope),
    onLink: (link) => this.links.push(link),
    createSocket: (url) => {
      const socket = new FakeSocket(url);
      this.sockets.push(socket);
      return socket;
    },
    now: () => this.now,
    setTimer: (callback, ms) => {
      const timer = { at: this.now + ms, callback, id: this.nextId++, cancelled: false };
      this.timers.push(timer);
      return timer.id;
    },
    clearTimer: (id) => {
      const timer = this.timers.find((candidate) => candidate.id === id);
      if (timer) timer.cancelled = true;
    },
    random: () => 0.5, // no jitter
    isOnline: () => this.online,
    watchEnvironment: false,
  });

  get socket(): FakeSocket {
    const socket = this.sockets.at(-1);
    if (!socket) throw new Error("no socket");
    return socket;
  }

  get link(): LinkSnapshot {
    return this.client.snapshot;
  }

  advance(ms: number): void {
    const target = this.now + ms;
    for (;;) {
      const due = this.timers
        .filter((timer) => !timer.cancelled && timer.at <= target)
        .sort((a, b) => a.at - b.at)[0];
      if (!due) break;
      this.now = due.at;
      due.cancelled = true;
      due.callback();
    }
    this.now = target;
  }

  connectLive(staleAfterSeconds = 30): void {
    this.socket.open();
    this.socket.message({ type: "snapshot", seq: 0, data: { stale_after_seconds: staleAfterSeconds } });
  }
}

let harness: Harness;

beforeEach(() => {
  harness = new Harness();
  harness.client.start();
});

describe("SocketClient", () => {
  test("goes live on the snapshot, not on open", () => {
    harness.socket.open();
    expect(harness.link.state).toBe("syncing");

    harness.socket.message({ type: "snapshot", seq: 0, data: { stale_after_seconds: 30 } });
    expect(harness.link.state).toBe("live");
    expect(harness.envelopes.map((envelope) => envelope.type)).toEqual(["snapshot"]);
  });

  test("answers every heartbeat with pong", () => {
    harness.connectLive();
    harness.socket.message({ type: "heartbeat", seq: 1 });

    expect(harness.socket.sent).toEqual([JSON.stringify({ action: "pong", data: {} })]);
  });

  test("asks for a resync once per sequence gap, not on every later message", () => {
    harness.connectLive();
    harness.socket.message({ type: "camera.status", seq: 1 });
    harness.socket.message({ type: "camera.status", seq: 3 }); // seq 2 missed
    harness.socket.message({ type: "camera.status", seq: 4 });
    harness.socket.message({ type: "camera.status", seq: 6 }); // still awaiting the snapshot

    const resyncs = harness.socket.sent.filter((message) => message.includes("resync"));
    expect(resyncs).toHaveLength(1);
    expect(harness.link.resyncs).toBe(1);

    // The fresh snapshot ends the gap; a new gap asks again.
    harness.socket.message({ type: "snapshot", seq: 7, data: { stale_after_seconds: 30 } });
    harness.socket.message({ type: "camera.status", seq: 9 });
    expect(harness.socket.sent.filter((message) => message.includes("resync"))).toHaveLength(2);
  });

  test("reconnects with a doubling backoff, capped, and gives up after the limit", () => {
    harness.connectLive();
    harness.socket.serverClose(1006);
    expect(harness.link.state).toBe("reconnecting");
    expect(harness.link.nextRetryAt).toBe(harness.now + 500);

    harness.advance(500);
    expect(harness.sockets).toHaveLength(2);
    harness.socket.serverClose(1006);
    expect(harness.link.nextRetryAt).toBe(harness.now + 1_000);

    for (let attempt = 3; attempt <= 20; attempt += 1) {
      harness.advance(8_000);
      harness.socket.serverClose(1006);
    }
    expect(harness.link.nextRetryAt === null || harness.link.state === "reconnecting").toBe(true);
    harness.advance(8_000);
    harness.socket.serverClose(1006);
    expect(harness.link.state).toBe("failed");

    harness.client.retryNow();
    expect(harness.link.state).toBe("connecting");
    expect(harness.link.attempts).toBe(0);
  });

  test("a successful snapshot resets the failure count", () => {
    harness.socket.serverClose(1006);
    harness.advance(500);
    harness.connectLive();
    expect(harness.link.attempts).toBe(0);
  });

  test("close code 4401 stops and reports that sign-in is needed", () => {
    harness.socket.open();
    harness.socket.serverClose(4401);

    expect(harness.link.state).toBe("unauthorized");
    harness.advance(60_000);
    expect(harness.sockets).toHaveLength(1);
  });

  test("silence past the threshold is reported as stale, and any message clears it", () => {
    harness.connectLive(10);
    harness.advance(10_500);
    expect(harness.link.isStale).toBe(false);
    harness.advance(1_000);
    expect(harness.link.isStale).toBe(true);

    harness.socket.message({ type: "heartbeat", seq: 1 });
    expect(harness.link.isStale).toBe(false);
    expect(harness.links.at(-1)?.isStale).toBe(false);
  });

  test("a socket silent long past the threshold is abandoned and reconnected", () => {
    harness.connectLive(10);
    harness.advance(26_000);

    expect(harness.sockets[0]?.closedWith).toBe(4000);
    expect(harness.link.state).toBe("reconnecting");
    harness.advance(500);
    expect(harness.sockets).toHaveLength(2);
  });

  test("offline browsers wait instead of burning attempts", () => {
    harness.online = false;
    harness.socket.serverClose(1006);
    expect(harness.link.state).toBe("offline");
  });

  test("stop closes the socket and goes idle", () => {
    harness.connectLive();
    harness.client.stop();

    expect(harness.sockets[0]?.closedWith).toBe(1000);
    expect(harness.link.state).toBe("idle");
  });
});
