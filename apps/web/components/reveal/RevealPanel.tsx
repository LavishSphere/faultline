"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { revealPrediction, revealPath, type Result, type RevealResponse } from "@/lib/benchmark";
import { API_BASE } from "@/lib/api";
import { Field, Panel } from "../Panel";
import { ProvenanceBadge } from "../ProvenanceBadge";
import { BUTTON_PRIMARY, FailureReport, Missing, Num } from "./ui";

/**
 * D.0 Historical outcome (SPEC §2 Screen D, §5). The presenter names a persisted prediction (prefilled from
 * `?prediction_id=` when the DECISION screen links here) and clicks Reveal. Only a successful reveal response puts an
 * outcome or a score on screen; 409 / 404 are shown as the API sent them. The reveal is never sent automatically:
 * the server logs it, and forecasts for the same event saved afterwards no longer count.
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

export function RevealPanel() {
  const [draft, setDraft] = useState("");
  const [view, setView] = useState<View>({ kind: "idle" });
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    const fromQuery = readQueryId();
    // eslint-disable-next-line react-hooks/set-state-in-effect -- one-time read of the URL after hydration (static export)
    if (fromQuery) setDraft(fromQuery);
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
    setView({ kind: "loading", id });
    const res = await revealPrediction(id, controller.signal);
    if (controller.signal.aborted) return;
    setView({ kind: "done", id, result: res });
  }

  const shown = stale ? null : revealed;
  const failure = !stale && result && !result.ok ? result : null;

  return (
    <Panel
      code="D.0"
      title="Historical outcome"
      provenance={shown ? ["REVEALED", shown.sealed.provenance] : failure ? "NOT AVAILABLE" : "SEALED"}
      provenanceDetail={shown ? undefined : failure ? undefined : "until reveal"}
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
                logged; any forecast for this event saved after it is excluded from scoring.
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
        {!shown && !failure ? (
          <div className="flex flex-col gap-1.5">
            <p className="font-mono text-2xl font-medium uppercase tracking-[0.08em] text-muted md:text-3xl">Sealed</p>
            <p className="text-xs leading-relaxed text-muted">
              No outcome and no score are shown until the API returns a successful reveal for a persisted forecast.
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
        <p className="mt-2 text-xs leading-relaxed text-muted">
          Lower Brier and log loss are better. One case is not evidence of anything general; see the scorecard.
        </p>
      </div>

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
            <dt>prompt_sha256</dt>
            <dd className="break-all text-text-2">{p.prompt_sha256}</dd>
          </div>
          <div>
            <dt>snapshot_sha256</dt>
            <dd className="break-all text-text-2">{p.snapshot_sha256}</dd>
          </div>
          <div>
            <dt>model_digest · temperature · seed</dt>
            <dd className="break-all text-text-2">
              {p.model_digest ?? <Missing />} · <span className="num">{p.temperature}</span> ·{" "}
              {p.seed === null || p.seed === undefined ? <Missing>none</Missing> : <span className="num">{p.seed}</span>}
            </dd>
          </div>
        </dl>
      </details>
    </div>
  );
}
