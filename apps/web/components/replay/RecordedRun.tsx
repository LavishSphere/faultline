"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Field } from "../Panel";
import { ProvenanceBadge } from "../ProvenanceBadge";
import { FailureNote, Hash } from "./ReplayParts";
import {
  formatInstantUtc,
  getRecorded,
  recordedPath,
  type ForecastVariant,
  type RecordedForecast,
  type RecordedResponse,
  type ReplayCasePublic,
  type ReplayResult,
} from "@/lib/replay";

export type RecordedState =
  | { kind: "no_case" }
  | { kind: "loading"; key: string }
  | { kind: "done"; key: string; result: ReplayResult<RecordedResponse> };

/**
 * GET /api/replay/recorded for the selected case + variant (#116): the committed RECORDED RUN forecast, served
 * verbatim from a row whose hashes the server recomputed. Read-only and public, so it is fetched on selection.
 */
export function useRecordedRun(c: ReplayCasePublic | null, variant: ForecastVariant): RecordedState {
  const key = c ? `${c.event_id}|${variant}` : "";
  const [state, setState] = useState<RecordedState>({ kind: "no_case" });
  useEffect(() => {
    if (!c) return;
    const controller = new AbortController();
    // eslint-disable-next-line react-hooks/set-state-in-effect -- a real request starts for this case + variant
    setState({ kind: "loading", key });
    void getRecorded(c.event_id, variant, controller.signal).then((result) => {
      if (!controller.signal.aborted) setState({ kind: "done", key, result });
    });
    return () => controller.abort();
  }, [c, variant, key]);
  if (!c) return { kind: "no_case" };
  // A state for another case or variant is never shown for this one.
  return state.kind !== "no_case" && state.key === key ? state : { kind: "loading", key };
}

/** The newest committed forecast for the selection, or null. */
export function recordedForecast(state: RecordedState): RecordedForecast | null {
  return state.kind === "done" && state.result.ok ? (state.result.data.items[0] ?? null) : null;
}

const DECISION_LABEL = { act: "Act", wait: "Wait", hedge: "Hedge" } as const;

/**
 * The committed forecast, verbatim: p(YES), decision, rationale, cited evidence, and its provenance (run_id,
 * recorded_at, model, hashes). `primary` when the live run is admin-gated (public demo): then this is the forecast
 * the screen shows, still labeled RECORDED RUN, never presented as a live answer.
 */
export function RecordedRun({
  state,
  variant,
  primary,
}: {
  state: RecordedState;
  variant: ForecastVariant;
  primary: boolean;
}) {
  if (state.kind === "no_case") {
    return <p className="font-mono text-[11px] uppercase tracking-[0.12em] text-muted">Recorded run: no case selected</p>;
  }
  if (state.kind === "loading") {
    return (
      <p className="font-mono text-[11px] text-muted" aria-live="polite">
        Loading the committed recorded run (GET {recordedPath(state.key.split("|")[0] ?? "", variant)})
      </p>
    );
  }
  const { result } = state;
  if (!result.ok) return <FailureNote failure={result} />;
  const f = result.data.items[0];
  if (!f) {
    return (
      <div className="flex flex-col gap-1" data-testid="recorded-not-available">
        <p className="font-mono text-[11px] uppercase tracking-[0.12em] text-muted">Recorded run: not available</p>
        {result.data.notes.map((n) => (
          <p key={n} className="break-words text-[11px] leading-relaxed text-muted">
            {n}
          </p>
        ))}
      </div>
    );
  }
  const older = result.data.items.length - 1;
  return (
    <div className="flex min-w-0 flex-col gap-4" data-testid="recorded-run">
      <div className="flex flex-wrap items-center gap-1.5">
        <ProvenanceBadge kind="RECORDED_RUN" />
        <ProvenanceBadge kind={f.case_synthetic ? "SYNTHETIC" : "REAL_HISTORICAL"} detail="case" />
        {primary ? (
          <span className="font-mono text-[11px] text-muted">Live runs are admin-only on the public demo.</span>
        ) : null}
      </div>
      <div className="flex flex-wrap items-baseline gap-x-6 gap-y-2">
        <div>
          <p className="kicker">P(YES) · recorded</p>
          <p className="num text-3xl text-text" data-testid="recorded-p">
            {f.p_yes.toFixed(3)}
          </p>
        </div>
        <div>
          <p className="kicker">Decision</p>
          <p className="font-mono text-lg uppercase tracking-[0.08em] text-text" data-testid="recorded-decision">
            {DECISION_LABEL[f.decision]}
          </p>
        </div>
      </div>
      <div>
        <p className="kicker">Rationale (verbatim)</p>
        <p className="mt-1 whitespace-pre-wrap break-words text-sm leading-relaxed text-text-2">{f.rationale}</p>
      </div>
      <div>
        <p className="kicker">Cited evidence</p>
        {f.cited_evidence.length === 0 ? (
          <p className="mt-1 font-mono text-[11px] uppercase tracking-[0.1em] text-risk">The run cited no evidence.</p>
        ) : (
          <ol className="mt-1 flex flex-col">
            {f.cited_evidence.map((e, i) => (
              <li key={e.evidence_id} className="flex gap-3 border-b border-line/70 py-1.5 last:border-b-0">
                <span className="num text-xs text-muted">[{i + 1}]</span>
                <span className="min-w-0 flex-1">
                  <span className="num block break-all text-xs text-text-2">{e.evidence_id}</span>
                  <span className="block break-words text-sm text-text">
                    {e.title ?? (
                      <span className="font-mono text-[11px] uppercase tracking-[0.1em] text-muted">
                        Not in the run&apos;s snapshot
                      </span>
                    )}
                  </span>
                </span>
              </li>
            ))}
          </ol>
        )}
      </div>
      <dl className="grid grid-cols-1 gap-x-8 md:grid-cols-2">
        <Field label="Run id" value={<span className="break-all">{f.run_id}</span>} />
        <Field label="Recorded at" value={formatInstantUtc(f.recorded_at) ?? undefined} />
        <Field label="Model" value={<span className="break-all">{f.agent_model}</span>} />
        <Field label="Variant" value={f.agent_variant} />
        <Field label="Prediction id" value={<span className="break-all">{f.prediction_id}</span>} />
        <Field label="Prompt sha256" value={<Hash value={f.prompt_sha256} />} />
        <Field label="Snapshot sha256" value={<Hash value={f.snapshot_sha256} />} />
        <Field label="Row sha256" value={<Hash value={f.row_sha256} />} />
      </dl>
      {older > 0 ? (
        <p className="font-mono text-[11px] text-muted">
          {older} older committed forecast{older === 1 ? "" : "s"} for this case and variant not shown.
        </p>
      ) : null}
      {result.data.notes.length ? (
        <ul className="flex flex-col gap-1">
          {result.data.notes.map((n) => (
            <li key={n} className="break-words font-mono text-[11px] leading-relaxed text-risk">
              {n}
            </li>
          ))}
        </ul>
      ) : null}
      <div className="flex flex-col gap-1 border-l border-line pl-3">
        <Link
          href={`/reveal?prediction_id=${encodeURIComponent(f.prediction_id)}`}
          className="font-mono text-[11px] uppercase tracking-[0.14em] text-accent hover:text-link-hover"
          data-testid="use-recorded"
        >
          Use recorded forecast in REVEAL →
        </Link>
        <p className="text-[11px] leading-relaxed text-muted">
          Fills REVEAL&apos;s prediction id. Reveal is disabled on the public demo (admin only); there the scorecard shows
          the committed results.
        </p>
      </div>
    </div>
  );
}
