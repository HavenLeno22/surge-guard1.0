import { create } from "zustand";

import type { Envelope } from "@/types/realtime";

import {
  applyEnvelope,
  applyFallback,
  type FallbackBatch,
  initialLiveData,
  type LiveData,
} from "./reducers";
import type { LinkSnapshot } from "./socketClient";

export const initialLink: LinkSnapshot = {
  state: "idle",
  attempts: 0,
  nextRetryAt: null,
  lastMessageAt: null,
  staleAfterSeconds: 30,
  isStale: false,
  connectedAt: null,
  resyncs: 0,
  messages: 0,
  lastCloseCode: null,
};

export interface LiveStore extends LiveData {
  link: LinkSnapshot;
  receive: (envelope: Envelope, receivedAt: number) => void;
  receiveFallback: (batch: FallbackBatch, receivedAt: number) => void;
  setLink: (link: LinkSnapshot) => void;
  reset: () => void;
}

/** Live operational state, written by the socket (and REST while it is down). */
export const useLive = create<LiveStore>()((set) => ({
  ...initialLiveData,
  link: initialLink,
  receive: (envelope, receivedAt) => set((state) => applyEnvelope(state, envelope, receivedAt)),
  receiveFallback: (batch, receivedAt) =>
    set((state) => applyFallback(state, batch, receivedAt)),
  setLink: (link) => set({ link }),
  reset: () => set({ ...initialLiveData, link: initialLink }),
}));
