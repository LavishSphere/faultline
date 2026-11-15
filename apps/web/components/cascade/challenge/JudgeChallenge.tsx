"use client";

import { useEffect, useState } from "react";
import type { ApiFailure, ScenarioPreset } from "@/lib/api";
import { ProvenanceBadge } from "../../ProvenanceBadge";
import {
  JUDGE_CHALLENGES_PATH,
  challengeAsPreset,
  getJudgeChallenges,
  surprisePick,
  type JudgeChallenge as Challenge,
  type JudgeChallengesResponse,
} from "./judgeChallenges";

type State = { kind: "loading" } | { kind: "ok"; data: JudgeChallengesResponse } | { kind: "error"; failure: ApiFailure };

/**
 * Judge's Challenge (issue #123, SPEC §9 P1): a judge throws a named surprise shock at the demo business.
 *
 * The shock list comes from GET /api/judge-challenges (ILLUSTRATIVE inputs). Picking one hands its exact ScenarioShock
 * to the workbench (`onPick`), which fills the sliders and posts it to POST /api/simulate; every number on screen is
 * that response (SIMULATED). "Surprise me" steps through the API's fixed `surprise_order` and shows the pick number:
 * deterministic, no hidden randomness.
 *
 * The workbench's `applyPreset` only changes its shock state; POST /api/optimize (with the Protect payroll switch, #56)
 * follows through the same debounced path the sliders use. This component sends no request of its own besides the GET.
 */
export function JudgeChallenge({
  activeId,
  onPick,
  disabled,
}: {
  /** Id of the preset the workbench is currently sending, if any. */
  activeId: string | null;
  /** `challenge` is the API item as served (for the incoming-shock card); `surprisePick` is k for a Surprise me pick. */
  onPick: (preset: ScenarioPreset, meta: { challenge: Challenge; surprisePick: number | null }) => void;
  disabled: boolean;
}) {
  const [state, setState] = useState<State>({ kind: "loading" });
  /** Number of "Surprise me" presses so far; pick k uses surprise_order[(k − 1) mod n]. */
  const [picks, setPicks] = useState(0);
  const [lastSurprise, setLastSurprise] = useState<{ k: number; id: string } | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    void getJudgeChallenges(controller.signal).then((res) => {
      if (controller.signal.aborted) return;
      setState(res.ok ? { kind: "ok", data: res.data } : { kind: "error", failure: res });
    });
    return () => controller.abort();
  }, []);

  const items = state.kind === "ok" ? state.data.items : [];
  const order = state.kind === "ok" ? state.data.surprise_order : [];
  const active = items.find((c) => c.id === activeId) ?? null;
  const off = disabled || items.length === 0;

  const pick = (id: string, surpriseK: number | null = null) => {
    const c = items.find((x) => x.id === id);
    if (c) onPick(challengeAsPreset(c), { challenge: c, surprisePick: surpriseK });
  };

  const surprise = () => {
    const k = picks + 1;
    const id = surprisePick(order, k);
    if (!id) return;
    setPicks(k);
    setLastSurprise({ k, id });
    pick(id, k);
  };

  let status: string;
  if (state.kind === "loading") status = `GET ${JUDGE_CHALLENGES_PATH} · request in flight`;
  else if (state.kind === "error")
    status =
      state.failure.status === 404
        ? `Judge's Challenge NOT AVAILABLE: this API build does not serve GET ${JUDGE_CHALLENGES_PATH}`
        : `Judge's Challenge NOT AVAILABLE: ${state.failure.error}`;
  else if (items.length === 0) status = state.data.notes.join(" ") || "Judge's Challenge NOT AVAILABLE: no challenges listed";
  else status = `${items.length} challenges from GET ${JUDGE_CHALLENGES_PATH}; results from POST /api/simulate`;

  return (
    <section
      aria-labelledby="judge-challenge-title"
      data-testid="judge-challenge"
      className="flex flex-col gap-2 rounded-md border border-accent/40 bg-bg/60 px-3 py-2.5"
    >
      <div className="flex flex-wrap items-center justify-between gap-x-2 gap-y-1">
        <h3 id="judge-challenge-title" className="text-[13px] font-medium uppercase tracking-[0.08em] text-text">
          Judge&apos;s Challenge
        </h3>
        <span className="flex flex-wrap items-center gap-1.5">
          <ProvenanceBadge kind="ILLUSTRATIVE" detail="shock" />
          <ProvenanceBadge kind="SIMULATED" detail="results" />
        </span>
      </div>

      <div className="grid grid-cols-1 gap-2 sm:grid-cols-[1fr_auto]">
        <label htmlFor="judge-challenge-select" className="sr-only">
          Pick a surprise shock
        </label>
        <select
          id="judge-challenge-select"
          value={active?.id ?? ""}
          onChange={(e) => pick(e.target.value)}
          disabled={off}
          className="w-full min-w-0 rounded-md border border-line-strong bg-bg px-2.5 py-1.5 font-mono text-xs text-text disabled:cursor-not-allowed disabled:opacity-60"
        >
          <option value="" disabled>
            Pick a surprise…
          </option>
          {items.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>
        <button
          type="button"
          onClick={surprise}
          disabled={off}
          aria-describedby="judge-surprise-note"
          className="rounded-md border border-accent/60 px-3 py-1.5 font-mono text-[11px] uppercase tracking-[0.12em] text-accent hover:bg-hover disabled:cursor-not-allowed disabled:opacity-60"
        >
          Surprise me
        </button>
      </div>

      <p id="judge-surprise-note" className="font-mono text-[10px] leading-snug text-muted">
        {order.length
          ? `${status} · Surprise me is deterministic: pick k = entry (k − 1) mod ${order.length} of the API's fixed order (next: pick ${picks + 1}).`
          : status}
      </p>

      {active ? (
        <div className="flex flex-col gap-1" aria-live="polite" data-testid="judge-challenge-active">
          <p className="text-xs leading-snug text-text-2">
            <span className="text-text">{active.name}.</span> {active.description}
            {lastSurprise && lastSurprise.id === active.id ? (
              <span className="text-muted"> (Surprise pick {lastSurprise.k})</span>
            ) : null}
          </p>
          <p className="break-words font-mono text-[10px] leading-snug text-muted" data-testid="judge-challenge-citation">
            Range: {active.range_citation}
          </p>
        </div>
      ) : null}
    </section>
  );
}
