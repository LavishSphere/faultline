"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { isSyntheticRef, revealPrediction, revealPath, type Result, type RevealResponse } from "@/lib/benchmark";
import { API_BASE } from "@/lib/api";
import { Field, Panel } from "../Panel";
import { ProvenanceBadge } from "../ProvenanceBadge";
import { BUTTON_PRIMARY, FailureReport, Missing, Num } from "./ui";

/**
 * D.0 Historical outcome (SPEC §2 Screen D, §5). The presenter names a persisted prediction (prefilled from
 * `?prediction_id=` when the DECISION screen links here) and clicks Reveal. Only a successful reveal response puts an
 * outcome or a score on screen; 401/403 (public demo), 409 and 404 are shown as the API sent them. The reveal is never
 * sent automatically: the server logs it, and forecasts for the same event saved afterwards no longer count.
 *
 * `onPredictionId` reports the id the presenter is working with (the `?prediction_id=` prefill, then each submitted
 * id) for panels that need it before a reveal (#93's IntegrityPanel once merged). `onRevealed` fires only when the
 * API answered the reveal with a valid 2xx body; the scorecard marks "this forecast" only from that id (#117), so
 * nothing about the forecast's event is highlighted while this panel still says SEALED.
 */

type View =
  | { kind: "idle" }
  | { kind: "loading"; id: string }
  | { kind: "done"; id: string; result: Result<RevealResponse> };

function readQueryId(): string {
  try {
    return new URLSearchParams(window.location.search).get("prediction_id")?.trim() ?? "";
  } catch {
    return "";
  }
}

export function RevealPanel({
  onPredictionId,
  onRevealed,
}: { onPredictionId?: (id: string) => void; onRevealed?: (id: string) => void } = {}) {
  const [draft, setDraft] = useState("");
  const [view, setView] = useState<View>({ kind: "idle" });
  const abortRef = useRef<AbortController | null>(null);
  const reportRef = useRef(onPredictionId);

  useEffect(() => {
    reportRef.current = onPredictionId;
  }, [onPredictionId]);

  useEffect(() => {
    const fromQuery = readQueryId();
    if (fromQuery) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- one-time read of the URL after hydration (static export)
      setDraft(fromQuery);
      reportRef.current?.(fromQuery);
    }
    return () => abortRef.current?.abort();
  }, []);

  const id = draft.trim();
  const loading = view.kind === "loading";
  const result = view.kind === "done" ? view.result : null;
  const revealed = result?.ok ? result.data : null;
  // A result belongs to the id it was requested for; editing the id hides it.
  const stale = view.kind === "done" && view.id !== id;

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!id || loading) return;
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    onPredictionId?.(id);
    setView({ kind: "loading", id });
    const res = await revealPrediction(id, controller.signal);
    if (controller.signal.aborted) return;
    setView({ kind: "done", id, result: res });
    if (res.ok) onRevealed?.(res.data.prediction.prediction_id);
  }

  const shown = stale ? null : revealed;
  const failure = !stale && result && !result.ok ? result : null;
  // The public demo refuses before anything is read: the outcome is still sealed, not missing.
  const gated = failure?.kind === "admin_required";

  return (
    <Panel
      code="D.0"
      title="Historical outcome"
      provenance={shown ? ["REVEALED", shown.sealed.provenance] : failure && !gated ? "NOT AVAILABLE" : "SEALED"}
      provenanceDetail={shown ? undefined : gated ? "public demo" : failure ? undefined : "until reveal"}
    >
      <div className="flex flex-col gap-6">
        <form onSubmit={submit} className="flex flex-col gap-2">
          <label htmlFor="reveal-prediction-id" className="kicker">
            Persisted prediction · prediction_id
          </label>
          <div className="flex flex-col gap-2 sm:flex-row xl:flex-col 2xl:flex-row">
            <input
              id="reveal-prediction-id"
              type="text"
              autoComplete="off"
              spellCheck={false}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              placeholder="prediction_id from the DECISION screen"
              aria-describedby="reveal-help"
              className="num min-w-0 flex-1 rounded-md border border-line-strong bg-bg px-3 py-2.5 text-base text-text placeholder:text-muted/70 focus:border-accent focus:outline-none"
            />
            <button type="submit" disabled={!id || loading} className={BUTTON_PRIMARY}>
              {loading ? "Revealing…" : "Reveal outcome"}
            </button>
          </div>
          <p id="reveal-help" className="text-xs leading-relaxed text-muted">
            {id ? (
              <>
                Sends <code className="break-all text-text-2">POST {API_BASE}{revealPath(id)}</code>. The reveal is
                logged; any forecast for this event saved after it is excluded from scoring. Admin only on the public
                demo.
              </>
            ) : (
              <>Disabled: no prediction id. The outcome stays sealed server-side until a persisted forecast is named.</>
            )}
          </p>
        </form>

        <p role="status" aria-live="polite" className="sr-only">
          {loading ? "Requesting reveal" : shown ? `Outcome revealed: ${shown.sealed.outcome}` : ""}
        </p>

        {failure ? <FailureReport failure={failure} /> : null}
        {shown ? <Revealed data={shown} /> : null}
        {!shown && (!failure || gated) ? (
          <div className="flex flex-col gap-1.5">
            <p className="font-mono text-2xl font-medium uppercase tracking-[0.08em] text-muted md:text-3xl">Sealed</p>
            <p className="text-xs leading-relaxed text-muted">
              This panel shows no outcome until reveal; recorded scorecards (D.2) list outcomes of events already
              scored.
            </p>
          </div>
        ) : null}
      </div>
    </Panel>
  );
}

function Revealed({ data }: { data: RevealResponse }) {
  const { prediction: p, sealed, scores } = data;
  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-2">
        <p className="kicker">Outcome · {sealed.event_id}</p>
        <p
          className={`display text-[clamp(3rem,5vw,4.5rem)] leading-none ${sealed.outcome === "YES" ? "text-viable" : "text-fail"}`}
        >
          {sealed.outcome}
        </p>
        <p className="font-mono text-[11px] text-muted">
          y = <span className="num text-text-2">{data.y}</span> · resolved{" "}
          <span className="text-text-2">{sealed.resolved_at ?? "not stated"}</span>
        </p>
        <a
          href={sealed.source_url}
          target="_blank"
          rel="noopener noreferrer"
          className="w-fit break-all font-mono text-[11px] text-accent underline decoration-line-strong underline-offset-4 hover:text-link-hover"
        >
          Settlement source<span aria-hidden="true"> ↗</span>
          <span className="sr-only"> (opens in a new tab)</span>
        </a>
        {sealed.notes ? <p className="text-xs leading-relaxed text-muted">{sealed.notes}</p> : null}
      </div>

      {!data.persisted_before_outcome_revealed ? (
        <p role="note" className="rounded-md border border-dashed border-risk/60 px-3 py-2 text-xs leading-relaxed text-risk">
          The API reports this forecast was saved after this event&apos;s outcome was first revealed. It does not count
          in the scorecard.
        </p>
      ) : null}

      <div>
        <div className="mb-2 flex flex-wrap items-center gap-1.5">
          <p className="kicker mr-1">This forecast</p>
          <ProvenanceBadge kind="FORECAST" />
          <ProvenanceBadge kind={p.provenance} />
        </div>
        <dl>
          <Field label="p_yes (model)" preserveCase value={<Num value={p.p_yes} />} />
          <Field label="Decision" value={<span className="font-mono uppercase">{p.decision}</span>} />
          <Field label="Variant" value={<span className="font-mono">{p.variant}</span>} />
          <Field label="Model" value={<span className="break-all font-mono text-xs">{p.agent_model}</span>} />
          <Field label="as_of" preserveCase value={<span className="font-mono text-xs">{p.as_of}</span>} />
          <Field label="Persisted" value={<span className="font-mono text-xs">{data.persisted_at}</span>} />
          <Field label="Revealed" value={<span className="font-mono text-xs">{data.revealed_at}</span>} />
        </dl>
      </div>

      <div>
        <div className="mb-2 flex flex-wrap items-center gap-1.5">
          <p className="kicker mr-1">Score for this one prediction</p>
          <ProvenanceBadge kind="REVEALED" />
        </div>
        <dl>
          <Field label="Brier (p − y)²" preserveCase value={<Num value={scores.brier} className="text-lg" />} />
          <Field label="Log loss" preserveCase value={<Num value={scores.log_loss} />} />
          <Field label="Correct at 0.5 threshold (1 = yes)" preserveCase value={<Num value={scores.accuracy_at_0_5} />} />
        </dl>
      </div>

      <Baselines data={data} />
      <p className="-mt-3 text-xs leading-relaxed text-muted">
        Lower Brier and log loss are better. One case is not evidence of anything general; see the scorecard.
      </p>

      <details className="group rounded-md border border-line px-3 py-2">
        <summary className="cursor-pointer font-mono text-[11px] uppercase tracking-[0.12em] text-text-2">
          Audit hashes
        </summary>
        <dl className="mt-2 flex flex-col gap-1.5 font-mono text-[10.5px] text-muted">
          <div>
            <dt>prediction_id</dt>
            <dd className="break-all text-text-2">{p.prediction_id}</dd>
          </div>
          <div>
            <dt>prompt_sha256 (what the model answered)</dt>
            <dd className="break-all text-text-2">{p.prompt_sha256}</dd>
          </div>
          <div>
            <dt>gated_prompt_sha256 (temporal gate, before any repair turn)</dt>
            <dd className="break-all text-text-2">{p.gated_prompt_sha256 ?? <Missing />}</dd>
          </div>
          <div>
            <dt>snapshot_sha256</dt>
            <dd className="break-all text-text-2">{p.snapshot_sha256}</dd>
          </div>
          <div>
            <dt>transcript_sha256 · attempts</dt>
            <dd className="break-all text-text-2">
              {p.transcript_sha256 ?? <Missing />} ·{" "}
              {p.attempts === null ? <Missing /> : <span className="num">{p.attempts}</span>}
            </dd>
          </div>
          <div>
            <dt>model_digest · temperature · seed</dt>
            <dd className="break-all text-text-2">
              {p.model_digest ?? <Missing />} · <span className="num">{p.temperature}</span> ·{" "}
              {p.seed === null ? <Missing>none</Missing> : <span className="num">{p.seed}</span>}
            </dd>
          </div>
          <div>
            <dt>audit_log persist_seq · reveal_seq · event_first_reveal_seq</dt>
            <dd className="break-all text-text-2">
              <span className="num">{data.persist_seq}</span> · <span className="num">{data.reveal_seq}</span> ·{" "}
              <span className="num">{data.event_first_reveal_seq}</span> (event first revealed{" "}
              {data.event_first_revealed_at})
            </dd>
          </div>
        </dl>
      </details>
    </div>
  );
}

/**
 * Naive (p = 0.5) and market-only scores on this same event, as the API computed them. The market row's label is
 * the API's, verbatim (#117); a `synthetic:` ref, or a SYNTHETIC case, also gets a SYNTHETIC badge.
 */
function Baselines({ data }: { data: RevealResponse }) {
  const { market, naive } = data.baselines;
  const synthetic = !!market && (isSyntheticRef(market.ref) || data.sealed.provenance === "SYNTHETIC");
  const head = "py-2 font-mono text-[10.5px] font-normal uppercase tracking-[0.14em] text-muted";
  return (
    <div>
      <div className="mb-2 flex flex-wrap items-center gap-1.5">
        <p className="kicker mr-1">Baselines on this event</p>
        <ProvenanceBadge kind="REVEALED" />
      </div>
      <div className="relative overflow-x-auto">
        <table className="w-full min-w-[300px] border-collapse text-left">
          <caption className="sr-only">Brier and log loss of this forecast and of the two baselines, from the API.</caption>
          <thead>
            <tr className="border-b border-line">
              <th scope="col" className={head}>Forecaster</th>
              <th scope="col" className={`${head} pl-3 text-right`}>p_yes</th>
              <th scope="col" className={`${head} pl-3 text-right`}>Brier</th>
              <th scope="col" className={`${head} pl-3 text-right`}>Log loss</th>
            </tr>
          </thead>
          <tbody className="text-sm">
            <tr className="border-b border-line/70">
              <th scope="row" className="py-2 font-medium text-text">This forecast</th>
              <td className="pl-3 text-right text-text-2"><Num value={data.prediction.p_yes} /></td>
              <td className="pl-3 text-right text-text"><Num value={data.scores.brier} /></td>
              <td className="pl-3 text-right text-text-2"><Num value={data.scores.log_loss} /></td>
            </tr>
            <tr className="border-b border-line/70">
              <th scope="row" className="py-2 font-medium text-text">
                <span className="flex flex-wrap items-center gap-1.5">
                  Market-only
                  {synthetic ? <ProvenanceBadge kind="SYNTHETIC" /> : null}
                </span>
                {market ? (
                  <>
                    <span className="block font-mono text-[10px] font-normal leading-snug text-muted" data-testid="reveal-market-label">
                      {market.label}
                    </span>
                    {market.ref ? (
                      <span className="block break-all font-mono text-[10px] font-normal text-muted">{market.ref}</span>
                    ) : null}
                  </>
                ) : null}
              </th>
              {market ? (
                <>
                  <td className="pl-3 text-right text-text-2"><Num value={market.p_yes} /></td>
                  <td className="pl-3 text-right text-text"><Num value={market.brier} /></td>
                  <td className="pl-3 text-right text-text-2"><Num value={market.log_loss} /></td>
                </>
              ) : (
                <td colSpan={3} className="pl-3 text-right text-xs">
                  <Missing>Not available at this as_of</Missing>
                </td>
              )}
            </tr>
            <tr>
              <th scope="row" className="py-2 font-medium text-text">
                Naive
                <span className="block font-mono text-[10px] font-normal text-muted">constant p = 0.5</span>
              </th>
              <td className="pl-3 text-right text-muted">
                <span aria-hidden="true">—</span>
                <span className="sr-only">constant forecast, see the row label</span>
              </td>
              <td className="pl-3 text-right text-text"><Num value={naive.brier} /></td>
              <td className="pl-3 text-right text-text-2"><Num value={naive.log_loss} /></td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  );
}
