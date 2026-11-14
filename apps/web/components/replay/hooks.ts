"use client";

import { useCallback, useEffect, useState, useSyncExternalStore } from "react";
import {
  EVIDENCE_PATH_TEMPLATE,
  getCaseEvidence,
  getCases,
  getReplayRoutes,
  selectionStore,
  type CaseEvidenceResponse,
  type CasesResponse,
  type ReplayCasePublic,
  type ReplayFailure,
  type ReplayResult,
  type ReplayRoutes,
} from "@/lib/replay";

/** A real request's lifecycle. "loading" is shown only while the request is in flight. */
export type Load<T> = { kind: "loading" } | { kind: "done"; result: ReplayResult<T> };

/** GET /api/cases on mount, plus a manual retry. */
export function useReplayCases(): { load: Load<CasesResponse>; retry: () => void } {
  const [load, setLoad] = useState<Load<CasesResponse>>({ kind: "loading" });
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    void getCases(controller.signal).then((result) => {
      if (!controller.signal.aborted) setLoad({ kind: "done", result });
    });
    return () => controller.abort();
  }, [attempt]);
  const retry = useCallback(() => {
    setLoad({ kind: "loading" });
    setAttempt((n) => n + 1);
  }, []);
  return { load, retry };
}

/** Route presence from /openapi.json; null while that request is in flight. */
export function useReplayRoutes(): ReplayRoutes | null {
  const [routes, setRoutes] = useState<ReplayRoutes | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    void getReplayRoutes(controller.signal).then((r) => {
      if (!controller.signal.aborted) setRoutes(r);
    });
    return () => controller.abort();
  }, []);
  return routes;
}

/** The shared selected case id (REWIND sets it, DECISION reads it). */
export function useSelectedCaseId(): [string | null, (id: string | null) => void] {
  const id = useSyncExternalStore(selectionStore.subscribe, selectionStore.get, selectionStore.getServer);
  return [id, selectionStore.set];
}

/** The selected case from the served list; falls back to the only case when exactly one is served. */
export function useSelectedCase(load: Load<CasesResponse>): {
  cases: ReplayCasePublic[];
  selected: ReplayCasePublic | null;
  select: (id: string | null) => void;
} {
  const [id, select] = useSelectedCaseId();
  const cases = load.kind === "done" && load.result.ok ? load.result.data.items : [];
  const match = cases.find((c) => c.event_id === id) ?? null;
  const selected = match ?? (cases.length === 1 ? cases[0]! : null);
  return { cases, selected, select };
}

export type EvidenceState =
  | { kind: "no_case" }
  | { kind: "checking" }
  | { kind: "absent"; failure: ReplayFailure }
  | { kind: "loading" }
  | { kind: "done"; result: ReplayResult<CaseEvidenceResponse> };

/**
 * GET /api/cases/{case_id}/evidence for the selected case (the gate's view at the case cutoff). Not requested when
 * /openapi.json says the route is not registered; when route presence is unknown the request itself reports it.
 */
export function useCaseEvidence(c: ReplayCasePublic | null, routes: ReplayRoutes | null): EvidenceState {
  const [state, setState] = useState<{ key: string; result: ReplayResult<CaseEvidenceResponse> } | null>(null);
  const key = c ? `${c.event_id}|${c.as_of}` : "";
  const absent = routes?.evidence === "absent";
  const ready = !!c && routes !== null && !absent;

  useEffect(() => {
    if (!ready || !c) return;
    const controller = new AbortController();
    void getCaseEvidence(c, controller.signal).then((result) => {
      if (!controller.signal.aborted) setState({ key, result });
    });
    return () => controller.abort();
    // `key` captures the case identity; `c` itself is a fresh object per render of the list.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, ready]);

  if (!c) return { kind: "no_case" };
  if (routes === null) return { kind: "checking" };
  if (absent) {
    return {
      kind: "absent",
      failure: {
        ok: false,
        kind: "route_missing",
        message: "This API build does not register the evidence route (checked /openapi.json).",
        request: `GET ${EVIDENCE_PATH_TEMPLATE}`,
      },
    };
  }
  if (!state || state.key !== key) return { kind: "loading" };
  return { kind: "done", result: state.result };
}
