"use client";

import { useEffect, useRef, useState } from "react";
import { API_BASE } from "@/lib/api";
import {
  BENCHMARK_PATH,
  EXCLUSION_REASON_TEXT,
  SCORABLE_VARIANTS,
  getBenchmark,
  type BenchmarkData,
  type ExclusionReason,
  type Result,
  type ScorableVariant,
  type Scorecard as ScorecardData,
} from "@/lib/benchmark";
import { Field, Panel } from "./Panel";
import type { ProvenanceInput } from "./ProvenanceBadge";
import { BUTTON_PRIMARY, BUTTON_SECONDARY, FailureReport, Missing, Num, Tag } from "./reveal/ui";

/**
 * D.1 Scorecard (SPEC §6, MATH_MODEL §6): agent vs market-only vs naive (p = 0.5) on identical (event_id, as_of)
 * pairs, from GET /api/benchmark (`evaluator.build_scorecard`).
 *
 * The browser computes nothing. `label` (OFFICIAL / ILLUSTRATIVE / INSUFFICIENT DATA), `verdict` and `caveat` are the
 * API's strings, rendered verbatim; the means, the ONE Δ Brier interval and every exclusion count are the API's
 * numbers. When the API sends `summary: null` / `comparison: null` (n < 5), those slots are NOT AVAILABLE and only the
 * per-event scores are listed. Each scorecard the API returns is rendered on its own; nothing is pooled or merged.
 *
 * Not requested on page load: building the scorecard reveals (and logs) every scorable persisted prediction, so it
 * runs only when the presenter clicks.
 */

type View =
  | { kind: "idle" }
  | { kind: "loading"; variant: ScorableVariant }
  | { kind: "done"; variant: ScorableVariant; result: Result<BenchmarkData> };

const segment =
  "rounded-[5px] px-3 py-1.5 font-mono text-[11px] uppercase tracking-[0.12em] transition-colors focus-visible:outline-offset-1";

export function Scorecard() {
  const [variant, setVariant] = useState<ScorableVariant>("agent_only");
  const [view, setView] = useState<View>({ kind: "idle" });
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => () => abortRef.current?.abort(), []);

  async function run(v: ScorableVariant) {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setView({ kind: "loading", variant: v });
    const res = await getBenchmark(v, controller.signal);
    if (controller.signal.aborted) return;
    setView({ kind: "done", variant: v, result: res });
  }

  const result = view.kind === "done" ? view.result : null;
  const data = result?.ok ? result.data : null;
  const failure = result && !result.ok ? result : null;

  return (
    <div className="flex flex-col gap-6">
      <Panel
        code="D.1"
        title="Scorecard · agent vs market-only vs naive"
        provenance={data && data.scorecards.length ? [...new Set(data.scorecards.flatMap(cardBadges))] : "NOT AVAILABLE"}
        provenanceDetail={view.kind === "idle" ? "not requested" : undefined}
      >
        <div className="flex flex-col gap-4">
          <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
            <div
              role="group"
              aria-label="Agent variant to score"
              className="flex w-full gap-1 rounded-md border border-line bg-bg/60 p-1 sm:w-fit"
            >
              {SCORABLE_VARIANTS.map((v) => (
                <button
                  key={v}
                  type="button"
                  aria-pressed={variant === v}
                  onClick={() => setVariant(v)}
                  className={`${segment} flex-1 sm:flex-none ${variant === v ? "bg-accent-soft text-text" : "text-muted hover:bg-hover hover:text-text"}`}
                >
                  {v}
                </button>
              ))}
            </div>
            <button
              type="button"
              disabled={view.kind === "loading"}
              onClick={() => void run(variant)}
              className={BUTTON_PRIMARY}
            >
              {view.kind === "loading" ? "Requesting…" : "Compute scorecard"}
            </button>
          </div>
          <p className="text-xs leading-relaxed text-muted">
            Sends <code className="break-all text-text-2">GET {API_BASE}{BENCHMARK_PATH}?agent_variant={variant}</code>.
            The API scores every persisted forecast made before its event&apos;s first reveal; doing so reveals (and
            logs) them. Each agent variant is scored separately against the same baselines.
          </p>
          <p role="status" aria-live="polite" className="sr-only">
            {view.kind === "loading" ? "Requesting scorecard" : data ? `${data.scorecards.length} scorecard(s) received` : ""}
          </p>
          {failure ? <FailureReport failure={failure} /> : null}
          {failure && failure.kind !== "aborted" ? (
            <button type="button" onClick={() => void run(view.kind === "done" ? view.variant : variant)} className={`w-fit ${BUTTON_SECONDARY}`}>
              Retry request
            </button>
          ) : null}
          {data ? (
            <div className="flex flex-col gap-1.5">
              {data.status ? (
                <p className="font-mono text-[10.5px] uppercase tracking-[0.1em] text-text-2">status: {data.status}</p>
              ) : null}
              {data.notes.map((n, i) => (
                <p key={i} className="text-xs leading-relaxed text-muted">
                  {n}
                </p>
              ))}
              {data.scorecards.length === 0 ? (
                <Missing>Not available: the API returned no scorecard</Missing>
              ) : null}
            </div>
          ) : null}
        </div>
      </Panel>

      {data && view.kind === "done" ? (
        data.scorecards.map((card, i) => (
          <ScorecardCard key={`${card.agent_variant}-${card.provenance ?? "none"}-${i}`} card={card} requested={view.variant} index={i} />
        ))
      ) : (
        <EmptyScorecard />
      )}
    </div>
  );
}

// --- one scorecard ----------------------------------------------------------------------------------------------

const VERDICT_TONE: Record<string, string> = {
  "agent better than market": "text-viable",
  "No improvement measured": "text-text",
  "INSUFFICIENT DATA": "text-risk",
};

function forecasterName(key: string, agentVariant: string): string {
  if (key === "naive") return "Naive baseline (p = 0.5)";
  if (key === "market") return "Market-only";
  if (key === agentVariant) return "Agent";
  return key;
}

function cardBadges(card: ScorecardData): ProvenanceInput[] {
  const out: ProvenanceInput[] = [];
  if (card.provenance) out.push(card.provenance);
  if (card.provenance === "SYNTHETIC") out.push("ILLUSTRATIVE");
  if (card.verdict === "INSUFFICIENT DATA") out.push("INSUFFICIENT DATA");
  if (out.length === 0) out.push("NOT AVAILABLE");
  return out;
}

function ScorecardCard({ card, requested, index }: { card: ScorecardData; requested: ScorableVariant; index: number }) {
  const agentKey = card.agent_variant;
  const cmp = card.comparison;
  const ciLabel = `Δ Brier vs market (paired bootstrap, ${cmp ? `${+(cmp.confidence * 100).toFixed(2)}%` : "95%"} CI)`;
  const reasons = Object.entries(card.exclusions_by_reason);

  return (
    <Panel code={`D.${2 + index}`} title={`Scorecard · ${agentKey}`} provenance={cardBadges(card)} bodyClassName="p-0">
      <div className="flex flex-col gap-3 border-b border-line px-5 py-4">
        <p className="font-mono text-[13px] tracking-[0.04em] text-text-2" data-testid="scorecard-label">
          {card.label}
        </p>
        <p
          className={`display text-[clamp(2rem,3.2vw,3.25rem)] leading-[1.05] ${VERDICT_TONE[card.verdict] ?? "text-text"}`}
          data-testid="scorecard-verdict"
        >
          {card.verdict}
        </p>
        {card.caveat ? (
          <Tag className="w-fit border-risk/60 text-risk" title="Sample-size caveat from the API">
            <span aria-hidden="true">!</span>
            <span>{card.caveat}</span>
          </Tag>
        ) : null}
        {card.agent_variant !== requested ? (
          <p className="text-xs text-risk">
            Requested <code>{requested}</code>; the API scored <code>{card.agent_variant}</code>. Shown as the API sent it.
          </p>
        ) : null}
        <div className="flex flex-wrap gap-x-8 gap-y-2 pt-1">
          <Stat label="Events scored (n)" value={card.n_events} />
          <Stat label="Snapshots excluded" value={card.n_excluded} />
          <Stat label="Predictions ignored" value={card.ignored_predictions.length} />
        </div>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full min-w-[480px] border-collapse text-left">
          <caption className="sr-only">
            Mean scores per forecaster on the same events, as computed by the API.
            {card.summary ? "" : " The API sent no means for this sample, so every cell is not available."}
          </caption>
          <thead>
            <tr className="border-b border-line">
              {["Forecaster", "Mean Brier", "Mean log loss", "Accuracy at 0.5"].map((c, i) => (
                <th
                  key={c}
                  scope="col"
                  className={`px-5 py-3 font-mono text-[10.5px] font-normal uppercase tracking-[0.16em] text-muted ${i ? "text-right" : ""}`}
                >
                  {c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {card.forecasters.map((f) => {
              const s = card.summary?.[f];
              return (
                <tr key={f} className="border-b border-line/70 last:border-b-0">
                  <th scope="row" className="px-5 py-3.5 text-base font-medium text-text">
                    {forecasterName(f, agentKey)}
                    <span className="ml-2 font-mono text-[10.5px] font-normal text-muted">{f}</span>
                  </th>
                  {s ? (
                    <>
                      <td className="px-5 py-3.5 text-right text-lg text-text"><Num value={s.mean_brier} /></td>
                      <td className="px-5 py-3.5 text-right text-lg text-text-2"><Num value={s.mean_log_loss} /></td>
                      <td className="px-5 py-3.5 text-right text-lg text-text-2"><Num value={s.accuracy_at_0_5} /></td>
                    </>
                  ) : (
                    [0, 1, 2].map((k) => (
                      <td key={k} className="num px-5 py-3.5 text-right text-lg text-muted">
                        <span aria-hidden="true">—</span>
                        <span className="sr-only">not available</span>
                      </td>
                    ))
                  )}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <dl className="border-t border-line px-5 py-2">
        <Field
          label={ciLabel}
          preserveCase
          value={
            cmp ? (
              <span className="flex flex-col items-end gap-0.5">
                <span className="text-lg text-text">
                  <Num value={cmp.mean_delta_brier} signed />{" "}
                  <span className="text-text-2">
                    [<Num value={cmp.ci_low} signed />, <Num value={cmp.ci_high} signed />]
                  </span>
                </span>
                <span className="font-mono text-[10.5px] text-muted">
                  {cmp.agent_variant} − {cmp.baseline} · B = <span className="num">{cmp.n_resamples}</span> · seed{" "}
                  <span className="num">{cmp.seed}</span>
                </span>
              </span>
            ) : undefined
          }
        />
      </dl>

      <div className="border-t border-line px-5 py-4">
        <p className="kicker mb-2">Exclusions by reason</p>
        {reasons.length === 0 ? (
          <p className="font-mono text-xs text-muted">None reported by the API.</p>
        ) : (
          <ul className="flex flex-col gap-2">
            {reasons.map(([reason, count]) => (
              <li key={reason} className="flex items-baseline justify-between gap-4 border-b border-line/70 pb-2 last:border-b-0">
                <span className="min-w-0">
                  <code className="font-mono text-xs text-text-2">{reason}</code>
                  {reason in EXCLUSION_REASON_TEXT ? (
                    <span className="block text-xs leading-relaxed text-muted">
                      {EXCLUSION_REASON_TEXT[reason as ExclusionReason]}
                    </span>
                  ) : null}
                </span>
                <span className="num text-lg text-text">{count}</span>
              </li>
            ))}
          </ul>
        )}
        {card.exclusions.length > 0 || card.ignored_predictions.length > 0 ? (
          <details className="mt-3 rounded-md border border-line px-3 py-2">
            <summary className="cursor-pointer font-mono text-[11px] uppercase tracking-[0.12em] text-text-2">
              Excluded snapshots and ignored predictions
            </summary>
            <ul className="mt-2 flex flex-col gap-1.5 font-mono text-[10.5px] text-muted">
              {card.exclusions.map((x, i) => (
                <li key={`x-${i}`} className="break-all">
                  <span className="text-text-2">{x.event_id}</span> · {x.as_of} · {x.reason}
                  {x.prediction_ids.length ? <> · {x.prediction_ids.join(", ")}</> : null}
                </li>
              ))}
              {card.ignored_predictions.map((x) => (
                <li key={`i-${x.prediction_id}`} className="break-all">
                  ignored <span className="text-text-2">{x.prediction_id}</span> · {x.event_id} · {x.as_of} · {x.reason}
                </li>
              ))}
            </ul>
          </details>
        ) : null}
      </div>

      <PerEventTable card={card} />

      <div className="flex flex-col gap-1 border-t border-line px-5 py-3 text-xs leading-relaxed text-muted">
        <p>
          Market-only uses the {card.market_label}. Lower Brier and log loss are better; Δ &lt; 0 means the agent&apos;s
          mean Brier was lower. Label, verdict and caveat are the API&apos;s text, shown as sent.
        </p>
      </div>
    </Panel>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="num text-2xl font-medium leading-none text-text">{value}</span>
      <span className="font-mono text-[10.5px] uppercase tracking-[0.12em] text-muted">{label}</span>
    </div>
  );
}

function PerEventTable({ card }: { card: ScorecardData }) {
  return (
    <div className="border-t border-line">
      <p className="kicker px-5 pt-4">Per-event Brier (averaged over each event&apos;s snapshots by the API)</p>
      {card.per_event.length === 0 ? (
        <p className="px-5 pb-4 pt-2 font-mono text-xs uppercase tracking-[0.08em] text-muted">
          Not available: no event was scored
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[520px] border-collapse text-left">
            <caption className="sr-only">Brier score per event and forecaster, from the API.</caption>
            <thead>
              <tr className="border-b border-line">
                <th scope="col" className="px-5 py-2.5 font-mono text-[10.5px] font-normal uppercase tracking-[0.16em] text-muted">
                  Event
                </th>
                <th scope="col" className="px-3 py-2.5 text-right font-mono text-[10.5px] font-normal uppercase tracking-[0.16em] text-muted">
                  y
                </th>
                {card.forecasters.map((f) => (
                  <th
                    key={f}
                    scope="col"
                    className="px-5 py-2.5 text-right font-mono text-[10.5px] font-normal uppercase tracking-[0.16em] text-muted"
                  >
                    {forecasterName(f, card.agent_variant)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {card.per_event.map((e) => (
                <tr key={e.event_id} className="border-b border-line/70 last:border-b-0">
                  <th scope="row" className="px-5 py-2.5 font-mono text-xs font-normal text-text-2">
                    {e.event_id}
                    <span className="ml-2 text-muted">
                      ×<span className="num">{e.n_snapshots}</span>
                    </span>
                  </th>
                  <td className="num px-3 py-2.5 text-right text-sm text-text-2">{e.y}</td>
                  {card.forecasters.map((f) => (
                    <td key={f} className="px-5 py-2.5 text-right text-sm text-text">
                      {typeof e.brier[f] === "number" ? <Num value={e.brier[f]} /> : <Missing />}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

/** Before any request: the structure, with every value NOT AVAILABLE. */
function EmptyScorecard() {
  return (
    <Panel code="D.2" title="Scorecard · not requested" provenance="NOT AVAILABLE" bodyClassName="p-0">
      <div className="overflow-x-auto">
        <table className="w-full min-w-[440px] border-collapse text-left">
          <caption className="sr-only">
            Mean forecast scores for agent, market-only and naive baseline. No scorecard has been requested, so every
            cell is not available.
          </caption>
          <thead>
            <tr className="border-b border-line">
              {["Forecaster", "Mean Brier", "Mean log loss", "Accuracy at 0.5"].map((c, i) => (
                <th
                  key={c}
                  scope="col"
                  className={`px-5 py-3 font-mono text-[10.5px] font-normal uppercase tracking-[0.16em] text-muted ${i ? "text-right" : ""}`}
                >
                  {c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {["Agent", "Market-only", "Naive baseline (p = 0.5)"].map((r) => (
              <tr key={r} className="border-b border-line/70 last:border-b-0">
                <th scope="row" className="px-5 py-3.5 text-base font-medium text-text">
                  {r}
                </th>
                {[0, 1, 2].map((k) => (
                  <td key={k} className="num px-5 py-3.5 text-right text-lg text-muted">
                    <span aria-hidden="true">—</span>
                    <span className="sr-only">not available</span>
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <dl className="border-t border-line px-5 py-2">
        <Field label="Events scored (n)" preserveCase />
        <Field label="Δ Brier vs market (paired bootstrap, 95% CI)" preserveCase />
        <Field label="Sample-size caveat (from the API)" preserveCase />
        <Field label="Exclusions by reason" preserveCase />
      </dl>
      <p className="border-t border-line px-5 py-3 text-xs leading-relaxed text-muted">
        Display rules (MATH_MODEL §6), applied by the API: fewer than 5 events → INSUFFICIENT DATA with per-event scores
        only; 5 to 29 → small-sample caveat; &ldquo;agent better than market&rdquo; only when the whole interval is below
        zero, otherwise &ldquo;No improvement measured&rdquo;.
      </p>
    </Panel>
  );
}
