"use client";

import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";
import {
  runReplay,
  runStore,
  type ForecastVariant,
  type ReplayCasePublic,
  type ReplayFailure,
  type ReplayRun,
} from "@/lib/replay";

export type RunState =
  | { kind: "idle" }
  | { kind: "running"; request: string }
  | { kind: "failed"; failure: ReplayFailure }
  | { kind: "done"; run: ReplayRun };

/**
 * POST /api/replay/run for one case + variant, only on an explicit `start()`. A successful run is kept in the
 * page-session run store so navigating away and back shows the run that was actually made.
 *
 * Also returns `caseId` (the selected case's event_id) and `predictionId` (the served `prediction.prediction_id` of
 * the run shown, persisted server-side; null until a run succeeds), so a panel that needs them (e.g. PR #93's
 * `<IntegrityPanel caseId predictionId />`) is one line on DECISION. Both are served ids, never derived.
 */
export function useReplayRun(c: ReplayCasePublic | null, variant: ForecastVariant) {
  const caseId = c?.event_id ?? null;
  const asOf = c?.as_of ?? null;
  const key = caseId ? runStore.key(caseId, variant) : "";
  const [local, setLocal] = useState<{ key: string; state: RunState } | null>(null);
  const inflight = useRef<AbortController | null>(null);
  useSyncExternalStore(runStore.subscribe, runStore.version, () => 0);

  useEffect(() => () => inflight.current?.abort(), []);

  const start = useCallback(() => {
    if (!caseId || !asOf) return;
    inflight.current?.abort();
    const controller = new AbortController();
    inflight.current = controller;
    const k = runStore.key(caseId, variant);
    setLocal({ key: k, state: { kind: "running", request: "POST /api/replay/run" } });
    void runReplay({ event_id: caseId, as_of: asOf }, variant, controller.signal).then((res) => {
      if (controller.signal.aborted) return;
      if (res.ok) {
        runStore.put(res.data, variant);
        setLocal({ key: k, state: { kind: "done", run: res.data } });
      } else {
        setLocal({ key: k, state: { kind: "failed", failure: res } });
      }
    });
  }, [caseId, asOf, variant]);

  const cancel = useCallback(() => {
    inflight.current?.abort();
    setLocal(null);
  }, []);

  let state: RunState = { kind: "idle" };
  if (local && local.key === key) state = local.state;
  else if (caseId) {
    const stored = runStore.get(caseId, variant);
    if (stored) state = { kind: "done", run: stored };
  }
  const predictionId = state.kind === "done" ? state.run.prediction.prediction_id : null;
  return { state, start, cancel, caseId, predictionId };
}
