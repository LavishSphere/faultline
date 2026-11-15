"use client";

import { useCallback, useSyncExternalStore } from "react";
import {
  REPLAY_RUN_PATH,
  RUN_TIMEOUT_MS,
  runReplay,
  runStore,
  type ForecastVariant,
  type ReplayCasePublic,
  type ReplayFailure,
  type ReplayRun,
} from "@/lib/replay";

export type RunState =
  | { kind: "idle" }
  | { kind: "running"; request: string; /** Epoch ms of the click (this browser's clock), for the elapsed-time readout. */ startedAt: number }
  /** `waitedSeconds`: how long the browser waited before giving up (timeout or cancel); null for other failures. */
  | { kind: "failed"; failure: ReplayFailure; waitedSeconds: number | null }
  | { kind: "done"; run: ReplayRun };

/**
 * One run at a time for the whole page session (#117 B). The in-flight request lives at module scope, not in the
 * component, so switching case or variant, or leaving DECISION and coming back, neither aborts it nor lets a second
 * POST start beside it. Only the presenter's Cancel aborts it, and even then the server may still save the forecast,
 * so the key is marked unanswered in the run store.
 */
interface Flight {
  key: string;
  caseId: string;
  variant: ForecastVariant;
  startedAt: number;
  controller: AbortController;
}

let flight: Flight | null = null;
const failures = new Map<string, { failure: ReplayFailure; waitedSeconds: number | null }>();
const listeners = new Set<() => void>();
let version = 0;

function emit() {
  version += 1;
  listeners.forEach((l) => l());
}
function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}
const getVersion = () => version;
const getServerVersion = () => 0;

const secondsSince = (t: number) => Math.max(0, Math.round((Date.now() - t) / 1000));
const RUN_REQUEST = `POST ${REPLAY_RUN_PATH}`;

function startRun(c: Pick<ReplayCasePublic, "event_id" | "as_of">, variant: ForecastVariant) {
  if (flight) return; // the button is disabled too; this is the backstop
  const key = runStore.key(c.event_id, variant);
  const controller = new AbortController();
  const mine: Flight = { key, caseId: c.event_id, variant, startedAt: Date.now(), controller };
  flight = mine;
  failures.delete(key);
  emit();
  void runReplay(c, variant, controller.signal).then((res) => {
    if (flight !== mine) return; // cancelled: cancelRun already recorded what happened
    flight = null;
    if (res.ok) {
      runStore.put(res.data, variant);
    } else {
      const noAnswer = res.kind === "timeout" || res.kind === "aborted";
      if (noAnswer) runStore.markUnanswered(key);
      failures.set(key, {
        failure: res,
        waitedSeconds: res.kind === "timeout" ? RUN_TIMEOUT_MS / 1000 : noAnswer ? secondsSince(mine.startedAt) : null,
      });
    }
    emit();
  });
}

function cancelRun() {
  const f = flight;
  if (!f) return;
  flight = null;
  f.controller.abort();
  runStore.markUnanswered(f.key);
  failures.set(f.key, {
    failure: {
      ok: false,
      kind: "aborted",
      message: "Cancelled in this browser before the API answered.",
      request: RUN_REQUEST,
    },
    waitedSeconds: secondsSince(f.startedAt),
  });
  emit();
}

/**
 * POST /api/replay/run for one case + variant, only on an explicit `start()`. A successful run is kept in the
 * page-session run store so navigating away and back shows the run that was actually made.
 *
 * Returns, besides the state of this case + variant:
 * - `busy`: some run (any case, any variant) is in flight; Run must stay disabled;
 * - `busyWith`: which case + variant that run is for (null when idle);
 * - `priorRun`: a forecast for this case + variant was saved in this session, or a request for it got no answer
 *   (`"saved"` / `"unanswered"`), so a new run needs the presenter's confirmation;
 * - `caseId` and `predictionId` (served ids; predictionId is null before a run) for PR #93's
 *   `<IntegrityPanel caseId predictionId />`. Both are served ids, never derived.
 */
export function useReplayRun(c: ReplayCasePublic | null, variant: ForecastVariant) {
  const caseId = c?.event_id ?? null;
  const asOf = c?.as_of ?? null;
  const key = caseId ? runStore.key(caseId, variant) : "";
  useSyncExternalStore(subscribe, getVersion, getServerVersion);
  useSyncExternalStore(runStore.subscribe, runStore.version, () => 0);

  const start = useCallback(() => {
    if (!caseId || !asOf) return;
    startRun({ event_id: caseId, as_of: asOf }, variant);
  }, [caseId, asOf, variant]);

  const cancel = useCallback(() => cancelRun(), []);

  let state: RunState = { kind: "idle" };
  const stored = caseId ? runStore.get(caseId, variant) : undefined;
  const failed = key ? failures.get(key) : undefined;
  if (flight && flight.key === key) state = { kind: "running", request: RUN_REQUEST, startedAt: flight.startedAt };
  else if (failed) state = { kind: "failed", ...failed };
  else if (stored) state = { kind: "done", run: stored };

  const priorRun: "saved" | "unanswered" | null = stored
    ? "saved"
    : key && runStore.isUnanswered(key)
      ? "unanswered"
      : null;
  const busyWith = flight ? { caseId: flight.caseId, variant: flight.variant } : null;
  const predictionId = state.kind === "done" ? state.run.prediction.prediction_id : null;
  return { state, start, cancel, busy: flight !== null, busyWith, priorRun, caseId, predictionId };
}
