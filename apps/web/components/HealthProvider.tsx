"use client";

import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { API_BASE, getHealth, type HealthSummary } from "@/lib/api";

/**
 * Real `/api/health` status shared by the header chip and the screens.
 * "checking" is shown only while a request is actually in flight.
 */
export type HealthState =
  | { kind: "checking"; previous: HealthState | null }
  | { kind: "online"; health: HealthSummary }
  | { kind: "unreachable"; error: string; checkedAt: Date };

interface HealthContextValue {
  state: HealthState;
  apiBase: string;
  recheck: () => void;
}

const HealthContext = createContext<HealthContextValue | null>(null);

const POLL_MS = 30_000;

export function HealthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<HealthState>({ kind: "checking", previous: null });
  const inflight = useRef<AbortController | null>(null);

  const check = useCallback(async () => {
    inflight.current?.abort();
    const controller = new AbortController();
    inflight.current = controller;
    setState((prev) => ({ kind: "checking", previous: prev.kind === "checking" ? prev.previous : prev }));
    const res = await getHealth(controller.signal);
    if (controller.signal.aborted) return;
    setState(
      res.ok
        ? { kind: "online", health: res.data }
        : { kind: "unreachable", error: res.error, checkedAt: new Date() },
    );
  }, []);

  useEffect(() => {
    // Initial check + polling: each tick is a real request, so the chip only ever reflects responses.
    const first = setTimeout(() => void check(), 0);
    const timer = setInterval(() => void check(), POLL_MS);
    return () => {
      clearTimeout(first);
      clearInterval(timer);
      inflight.current?.abort();
    };
  }, [check]);

  return (
    <HealthContext.Provider value={{ state, apiBase: API_BASE, recheck: () => void check() }}>
      {children}
    </HealthContext.Provider>
  );
}

export function useHealth(): HealthContextValue {
  const ctx = useContext(HealthContext);
  if (!ctx) throw new Error("useHealth must be used inside <HealthProvider>");
  return ctx;
}

/** Most recent settled result (while a re-check is in flight, keep showing the last answer). */
export function settled(state: HealthState): Exclude<HealthState, { kind: "checking" }> | null {
  if (state.kind !== "checking") return state;
  return state.previous && state.previous.kind !== "checking" ? state.previous : null;
}
