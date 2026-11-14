"use client";

import { useEffect, useMemo, useState } from "react";
import { Field, Panel } from "../Panel";
import type { ApiResult } from "@/lib/api";
import {
  DECISION_FRAMES_PATH,
  DECISION_PATH,
  NO_SAFE_POLICY,
  evaluateDecision,
  frameForCase,
  getDecisionFrames,
  type DecisionResponse,
  type FramesResponse,
  type PolicyResult,
} from "@/lib/decision";
import type { Decision } from "@/lib/replay";

/**
 * B.4-B.6: the ACT / WAIT / HEDGE split view (SPEC §2 Screen B, MATH_MODEL §8, issue #55).
 *
 * One POST /api/decision per probability: at the agent's forecast p (from the run) and at the market-implied p (when
 * the API served one). Every payoff, E[V], feasibility flag, recommendation and break-even p* is the API's; nothing is
 * computed here. With neither p, one request at p = 0 is made only to read V(a, YES), V(a, NO) and feasibility (they
 * do not depend on p); its E[V] and recommendation are not shown.
 *
 * The frame comes from `frameForCase` (explicit id rules). When no rule matches, nothing is selected and no request
 * is sent until the presenter picks a frame, so a forecast is never plugged into another question's payoffs.
 */

export interface ProbabilityInput {
  p: number;
  /** Shown verbatim next to every E[V] taken at this p. */
  label: string;
}

const CODES: Record<string, string> = { ACT: "B.4", WAIT: "B.5", HEDGE: "B.6" };
const USD = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 2 });
const fmtUsd = (v: number | null) => (v === null ? undefined : USD.format(v));
const fmtP = (p: number) => p.toFixed(4);

type Load<T> = { kind: "loading" } | { kind: "done"; result: ApiResult<T> };

function useDecision(frameId: string | null, p: number | null): Load<DecisionResponse> | null {
  const [state, setState] = useState<{ key: string; load: Load<DecisionResponse> } | null>(null);
  const key = frameId !== null && p !== null ? `${frameId}@${p}` : null;
  useEffect(() => {
    if (frameId === null || p === null || key === null) return;
    const ctrl = new AbortController();
    void evaluateDecision({ frame_id: frameId, p_yes: p }, ctrl.signal).then((result) => {
      if (!ctrl.signal.aborted) setState({ key, load: { kind: "done", result } });
    });
    return () => ctrl.abort();
  }, [frameId, p, key]);
  if (key === null) return null;
  return state && state.key === key ? state.load : { kind: "loading" };
}

export function SplitView({
  caseRef,
  chosen,
  agent,
  market,
}: {
  /** The selected replay case (id + SYNTHETIC flag), used only to choose the frame. */
  caseRef: { event_id: string; synthetic: boolean } | null;
  chosen: Decision | null;
  agent: ProbabilityInput | null;
  market: ProbabilityInput | null;
}) {
  const [frames, setFrames] = useState<Load<FramesResponse>>({ kind: "loading" });
  // The presenter's pick applies to the case it was made on; a new case starts from frameForCase again.
  const [picked, setPicked] = useState<{ caseId: string | null; frameId: string } | null>(null);

  useEffect(() => {
    const ctrl = new AbortController();
    void getDecisionFrames(ctrl.signal).then((result) => {
      if (!ctrl.signal.aborted) setFrames({ kind: "done", result });
    });
    return () => ctrl.abort();
  }, []);

  const list = useMemo(
    () => (frames.kind === "done" && frames.result.ok ? frames.result.data.frames : []),
    [frames],
  );
  const caseId = caseRef ? caseRef.event_id : null;
  const servedIds = list.map((f) => f.id);
  const pickedHere = picked && picked.caseId === caseId && servedIds.includes(picked.frameId) ? picked.frameId : null;
  const frameId = pickedHere ?? frameForCase(caseRef, servedIds);
  const frame = list.find((f) => f.id === frameId) ?? null;

  const atAgent = useDecision(frameId, agent ? agent.p : null);
  const atMarket = useDecision(frameId, market ? market.p : null);
  const payoffsOnly = useDecision(frameId, agent || market ? null : 0);
  const base = [atAgent, atMarket, payoffsOnly].find((s) => s?.kind === "done" && s.result.ok);
  const values = base && base.kind === "done" && base.result.ok ? base.result.data : null;

  if (frames.kind === "loading") {
    return <p className="font-mono text-[11px] text-muted">Loading GET {DECISION_FRAMES_PATH}</p>;
  }
  if (!frames.result.ok) {
    return (
      <Panel code="B.4-6" title="ACT / WAIT / HEDGE" provenance="NOT AVAILABLE">
        <p className="font-mono text-sm uppercase tracking-[0.08em] text-muted">Not available</p>
        <p className="mt-1 font-mono text-[11px] text-muted">
          GET {DECISION_FRAMES_PATH} failed: {frames.result.error}
        </p>
      </Panel>
    );
  }

  return (
    <div className="flex min-w-0 flex-col gap-4">
      <div className="flex min-w-0 flex-col gap-3 rounded-lg border border-line bg-elevated p-4 md:flex-row md:items-end md:justify-between">
        <label className="flex min-w-0 flex-col gap-1.5">
          <span className="kicker">Decision frame (ILLUSTRATIVE policies, SYNTHETIC business)</span>
          <select
            id="decision-frame"
            value={frameId ?? ""}
            onChange={(e) => setPicked(e.target.value ? { caseId, frameId: e.target.value } : null)}
            className="w-full min-w-0 rounded-md border border-line bg-bg px-2 py-1.5 font-mono text-xs text-text md:w-auto"
          >
            {frameId === null ? <option value="">Choose a decision frame</option> : null}
            {list.map((f) => (
              <option key={f.id} value={f.id}>
                {f.id}
              </option>
            ))}
          </select>
        </label>
        {frame ? (
          <p className="min-w-0 text-xs leading-relaxed text-text-2 md:max-w-[60%] md:text-right">
            <span className="text-muted">YES:</span> {frame.yes_means} <span className="text-muted">· NO:</span>{" "}
            {frame.no_means}
          </p>
        ) : null}
      </div>

      {frame === null ? (
        <Panel code="B.4-6" title="ACT / WAIT / HEDGE" provenance="NOT AVAILABLE">
          <p className="font-mono text-sm uppercase tracking-[0.08em] text-muted">Choose a decision frame</p>
          <p className="mt-1 text-xs leading-relaxed text-muted">
            {caseRef ? `No decision frame is mapped to ${caseRef.event_id}.` : "No case selected."} Pick the frame that
            matches the question; no payoff is requested until then.
          </p>
        </Panel>
      ) : null}

      {frame && !frame.forecast_sensitive && frame.caveat ? (
        <div role="note" className="rounded-lg border border-risk/60 bg-risk/10 px-4 py-3">
          <p className="font-mono text-[11px] uppercase tracking-[0.14em] text-risk">Forecast does not change the call</p>
          <p className="mt-1 text-sm leading-relaxed text-text">{frame.caveat}</p>
        </div>
      ) : null}

      {frame ? (
        <div className="grid min-w-0 grid-cols-1 gap-3 md:grid-cols-2">
          <Recommendation which="agent" input={agent} state={atAgent} />
          <Recommendation which="market" input={market} state={atMarket} />
        </div>
      ) : null}

      <div className="grid min-w-0 grid-cols-1 gap-4 md:grid-cols-3">
        {(frame?.policies ?? []).map((fp) => {
          const row = (s: Load<DecisionResponse> | null) =>
            s?.kind === "done" && s.result.ok ? s.result.data.policies.find((x) => x.name === fp.name) ?? null : null;
          const v = values?.policies.find((x) => x.name === fp.name) ?? null;
          const isChosen = chosen !== null && chosen.toUpperCase() === fp.name;
          return (
            <div key={fp.name} data-policy={fp.name} className="flex min-w-0 flex-col">
            <Panel
              code={CODES[fp.name]}
              title={fp.name}
              provenance={values ? ["SIMULATED", "SYNTHETIC"] : "NOT AVAILABLE"}
              provenanceDetail="payoffs"
              className={`flex-1 ${isChosen ? "border-accent" : ""}`}
            >
              <div className="flex items-start justify-between gap-3">
                <p className="text-sm leading-relaxed text-text-2">{fp.summary}</p>
                {isChosen ? (
                  <span className="shrink-0 font-mono text-[10px] uppercase tracking-[0.14em] text-accent">
                    Model chose
                  </span>
                ) : null}
              </div>
              <Feasibility v={v} />
              <dl className="mt-3">
                <Field label="V(a, YES) · min cash" preserveCase value={fmtUsd(v?.value_if_yes ?? null)} />
                <Field label="V(a, NO) · min cash" preserveCase value={fmtUsd(v?.value_if_no ?? null)} />
                <Field
                  label={agent ? `E[V] at ${agent.label}` : "E[V] at agent p"}
                  preserveCase
                  value={fmtUsd(row(atAgent)?.expected_value ?? null)}
                />
                <Field
                  label={market ? `E[V] at ${market.label}` : "E[V] at market p"}
                  preserveCase
                  value={fmtUsd(row(atMarket)?.expected_value ?? null)}
                />
              </dl>
              <Breaches v={v} />
              <details className="mt-3">
                <summary className="cursor-pointer font-mono text-[10px] uppercase tracking-[0.14em] text-muted">
                  Fees ({fp.fees.length})
                </summary>
                <ul className="mt-2 flex flex-col gap-1.5">
                  {fp.fees.map((f) => (
                    <li key={f.item} className="text-xs leading-relaxed text-text-2">
                      {f.item}: <span className="num">{f.amount}</span> ({f.when}
                      {f.in_payoff ? ", in payoff" : ", not in payoff"})
                    </li>
                  ))}
                </ul>
              </details>
            </Panel>
            </div>
          );
        })}
      </div>

      <p className="font-mono text-[11px] leading-relaxed text-muted">
        {values ? values.payoff : "lowest simulated cash balance"} · from POST {DECISION_PATH} (core.decision,
        MATH_MODEL §8), one request per probability. SIMULATED payoffs of a SYNTHETIC business, never trading P&amp;L.
        {frame?.not_modelled_note ? ` ${frame.not_modelled_note}` : ""}
      </p>
    </div>
  );
}

function Feasibility({ v }: { v: PolicyResult | null }) {
  if (!v) {
    return <p className="mt-3 font-mono text-[10px] uppercase tracking-[0.14em] text-muted">Feasibility: not available</p>;
  }
  const ok = v.feasible_in_both;
  return (
    <p
      className={`mt-3 inline-flex w-fit items-center gap-1.5 rounded border px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-[0.14em] ${
        ok ? "border-viable/60 text-viable" : "border-fail/60 bg-fail/10 text-fail"
      }`}
    >
      <span aria-hidden>{ok ? "✓" : "✕"}</span>
      {ok ? "Feasible in both states" : `Infeasible if ${!v.feasible_if_yes && !v.feasible_if_no ? "YES and NO" : !v.feasible_if_yes ? "YES" : "NO"}`}
    </p>
  );
}

function Breaches({ v }: { v: PolicyResult | null }) {
  if (!v || v.feasible_in_both) return null;
  const all = [...v.breaches_if_yes.map((b) => `YES: ${b}`), ...v.breaches_if_no.map((b) => `NO: ${b}`)];
  return (
    <ul className="mt-2 flex flex-col gap-1">
      {all.map((b) => (
        <li key={b} className="break-words font-mono text-[11px] leading-relaxed text-fail">
          {b}
        </li>
      ))}
    </ul>
  );
}

function Recommendation({
  which,
  input,
  state,
}: {
  which: "agent" | "market";
  input: ProbabilityInput | null;
  state: Load<DecisionResponse> | null;
}) {
  const title = which === "agent" ? "Recommendation at agent p" : "Recommendation at market p";
  let body;
  if (!input) {
    body = (
      <p className="font-mono text-sm uppercase tracking-[0.08em] text-muted">
        Not available{" "}
        <span className="normal-case tracking-normal">
          {which === "agent" ? "(run the agent first)" : "(no market price at the cutoff)"}
        </span>
      </p>
    );
  } else if (!state || state.kind === "loading") {
    body = <p className="font-mono text-[11px] text-muted">POST {DECISION_PATH} in flight</p>;
  } else if (!state.result.ok) {
    body = (
      <p className="font-mono text-[11px] text-fail">
        Not available: POST {DECISION_PATH} failed ({state.result.code ?? state.result.kind}): {state.result.error}
      </p>
    );
  } else {
    const d = state.result.data;
    const none = d.recommendation === NO_SAFE_POLICY;
    body = (
      <div className="flex flex-col gap-1.5">
        <p className={`display text-3xl italic md:text-4xl ${none ? "text-fail" : "text-text"}`}>{d.recommendation}</p>
        <p className="num font-mono text-[11px] text-muted">
          {input.label} = {fmtP(d.p_yes)}
        </p>
        <p className="text-xs leading-relaxed text-text-2">
          {d.break_even.status === "AVAILABLE" && d.break_even.p_star !== null
            ? `Break-even p* = ${fmtP(d.break_even.p_star)} between ${d.break_even.policies.join(" and ")}.`
            : d.break_even.note}
        </p>
      </div>
    );
  }
  return (
    <div className="min-w-0 rounded-lg border border-line bg-elevated p-4">
      <p className="kicker mb-2">{title}</p>
      {body}
    </div>
  );
}
