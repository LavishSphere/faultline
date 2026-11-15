"use client";

import { useSyncExternalStore } from "react";
import type { ApiResult } from "./api";
import type { ChatModelsResponse } from "./chat";

/**
 * The Explore chat's own route results, shared with the header chip (#236) so the chip never re-fetches them.
 * ChatPanel publishes what GET /api/explore/chat/models and /status returned; the chip only reads. Nothing here is
 * computed or invented: `models` is the raw ApiResult, `paused` is the status route's own boolean.
 */
export interface ChatPresence {
  /** null until the models request settles. */
  models: ApiResult<ChatModelsResponse> | null;
  paused: boolean;
  /** Re-requests models and status (wired by ChatPanel); null when no chat is mounted. */
  recheck: (() => void) | null;
}

const EMPTY: ChatPresence = { models: null, paused: false, recheck: null };
let current: ChatPresence = EMPTY;
const listeners = new Set<() => void>();

function emit() {
  listeners.forEach((l) => l());
}

export function publishChatPresence(next: Partial<ChatPresence>): void {
  current = { ...current, ...next };
  emit();
}

export function clearChatPresence(): void {
  current = EMPTY;
  emit();
}

function subscribe(l: () => void) {
  listeners.add(l);
  return () => {
    listeners.delete(l);
  };
}

export function useChatPresence(): ChatPresence {
  return useSyncExternalStore(
    subscribe,
    () => current,
    () => EMPTY,
  );
}
