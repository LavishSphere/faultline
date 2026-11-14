"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { API_BASE } from "@/lib/api";
import {
  BENCHMARK_PATH,
  EXCLUSION_REASON_TEXT,
  SCORABLE_VARIANTS,
  firstPerVariant,
  getBenchmark,
  type BenchmarkResponse,
  type ExclusionReason,
  type Result,
  type ScorableVariant,
  type Scorecard as ScorecardData,
  type ScorecardRecord,
  type VariantCard,
} from "@/lib/benchmark";
import { Field, Panel } from "./Panel";
import type { ProvenanceInput } from "./ProvenanceBadge";
import { BUTTON_SECONDARY, FailureReport, Missing, Num } from "./reveal/ui";

/**
 * D.1 Benchmark (SPEC §6, MATH_MODEL §6): agent vs market-only vs naive (p = 0.5) on identical (event_id, as_of)
 * pairs, from the RECORDED RUN scorecards that GET /api/benchmark serves.
 *
 * GET /api/benchmark is read-only (it never computes, never reveals, never opens the prediction store), so it is
 * requested on load. For each variant the FIRST item the API serves is shown (its order: committed agent_only,
 * committed agent_plus_market, then computed ones), with that item's record (origin, recorded_at, run_id, model) as
 * provenance. `label`, `verdict`, `caveat`, `official_blockers` and the exclusions are the API's strings, shown
 * verbatim; every number is the API's. POST /api/benchmark/compute (admin only, reveals) is never called from here.
 *
 * Sealed-state honesty (#117): `revealedPredictionId` is set only after D.0's reveal succeeded, so no row is marked
 * "this forecast" while D.0 still says SEALED. The per-event table (which lists y for every scored event) starts
 * collapsed.
 */

type Load = { kind: "loading" } | { kind: "done"; result: Result<BenchmarkResponse> };

const segment =
  "rounded-[5px] px-3 py-1.5 font-mono text-[11px] uppercase tracking-[0.12em] transition-colors focus-visible:outline-offset-1";

export function Scorecard({ revealedPredictionId = null }: { revealedPredictionId?: string | null }) {
  const [load, setLoad] = useState<Load>({ kind: "loading" });
  const [picked, setPicked] = useState<ScorableVariant | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const fetchBenchmark = useCallback(async () => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setLoad({ kind: "loading" });
    const res = await getBenchmark(controller.signal);
    if (controller.signal.aborted) return;
    setLoad({ kind: "done", result: res });
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- the request's own loading state, set when it starts
    void fetchBenchmark();
    return () => abortRef.current?.abort();
  }, [fetchBenchmark]);

  const result = load.kind === "done" ? load.result : null;
  const data = result?.ok ? result.data : null;
  const failure = result && !result.ok ? result : null;
  const cards = data ? firstPerVariant(data) : {};
  // Default tab: the first variant the API served a card for (selection only).
  const variant: ScorableVariant = picked ?? SCORABLE_VARIANTS.find((v) => cards[v]) ?? SCORABLE_VARIANTS[0];
  const selected = cards[variant];

  // While the request is in flight nothing is known yet: no badge claims NOT AVAILABLE (or anything else).
  const headerBadges: ProvenanceInput[] =
    load.kind === "loading" ? [] : data && data.status === "AVAILABLE" ? [data.provenance] : ["NOT AVAILABLE"];

  return (
    <div className="flex flex-col gap-6">
      <Panel
        code="D.1"
        title="Benchmark · recorded scorecards"
        provenance={headerBadges}
      >
        <div className="flex flex-col gap-4">
          <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
            <div
              role="group"
              aria-label="Agent variant"
              className="flex w-full flex-wrap gap-1 rounded-md border border-line bg-bg/60 p-1 sm:w-fit"
            >
              {SCORABLE_VARIANTS.map((v) => (
                <button
                  key={v}
                  type="button"
                  aria-pressed={variant === v}
                  onClick={() => setPicked(v)}
                  className={`${segment} flex flex-1 items-center justify-center gap-2 sm:flex-none ${variant === v ? "bg-accent-soft text-text" : "text-muted hover:bg-hover hover:text-text"}`}
                >
                  <span>{v}</span>
                  {data && !cards[v] ? <span className="text-[9.5px] text-muted">n/a</span> : null}
                </button>
              ))}
            </div>
            <button
              type="button"
              disabled={load.kind === "loading"}
              onClick={() => void fetchBenchmark()}
              className={`w-fit ${BUTTON_SECONDARY} disabled:cursor-not-allowed disabled:text-muted`}
            >
              {load.kind === "loading" ? "Requesting…" : "Reload"}
            </button>
          </div>
          <p className="text-xs leading-relaxed text-muted">
            <code className="break-all text-text-2">GET {API_BASE}{BENCHMARK_PATH}</code> serves recorded scorecard
            snapshots only (verified hashes); it never computes or reveals. Each agent variant is scored separately
            against the same baselines; the first snapshot the API serves for a variant is shown.
          </p>
          <p role="status" aria-live="polite" className="sr-only">
            {load.kind === "loading" ? "Requesting benchmark" : data ? `Benchmark status ${data.status}` : ""}
          </p>
          {failure ? <FailureReport failure={failure} /> : null}
          {data ? (
            <div className="flex flex-col gap-1.5">
              <p className="font-mono text-[10.5px] uppercase tracking-[0.1em] text-text-2">
                status: {data.status} · provenance: {data.provenance}
              </p>
              {data.notes.length ? (
                <ul className="flex flex-col gap-1" aria-label="Notes from the API">
                  {data.notes.map((n, i) => (
                    <li key={i} className="break-words text-xs leading-relaxed text-muted">
                      {n}
                    </li>
                  ))}
                </ul>
              ) : null}
            </div>
          ) : null}
        </div>
      </Panel>

      {selected ? (
        <ScorecardCard entry={selected} revealedPredictionId={revealedPredictionId} />
      ) : (
        <EmptyScorecard variant={variant} status={data ? data.status : null} loading={load.kind === "loading"} />
      )}
    </div>
  );
}

// --- one scorecard ----------------------------------------------------------------------------------------------

/** Styling only, by exact match on the API's verdict string; an unknown string stays neutral. */
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

function isSynthetic(card: ScorecardData): boolean {
  return card.provenance === "SYNTHETIC" || card.case_set === "synthetic";
}

function cardBadges(card: ScorecardData): ProvenanceInput[] {
  const out: ProvenanceInput[] = ["RECORDED RUN"];
  if (card.provenance) out.push(card.provenance);
  if (card.case_set === "synthetic" && card.provenance !== "SYNTHETIC") out.push("SYNTHETIC");
  if (isSynthetic(card) || card.label.startsWith("ILLUSTRATIVE")) out.push("ILLUSTRATIVE");
  if (card.verdict === "INSUFFICIENT DATA") out.push("INSUFFICIENT DATA");
  return out;
}

const ORIGIN_TEXT: Record<ScorecardRecord["origin"], string> = {
  committed: "committed · data/recorded_runs in git (official run script)",
  computed: "computed · var/scorecards on this API server (admin compute)",
};

function ScorecardCard({ entry, revealedPredictionId }: { entry: VariantCard; revealedPredictionId: string | null }) {
  const { card, record, alsoServed } = entry;
  const agentKey = card.agent_variant;
  const cmp = card.comparison;
  const reasons = Object.entries(card.exclusions_by_reason);
  // Only a forecast D.0 has actually revealed is marked; a typed or ?prediction_id= id is not (#117).
  const mine = (ids: string[]) => !!revealedPredictionId && ids.includes(revealedPredictionId);

  return (
    <Panel code="D.2" title={`Scorecard · ${agentKey}`} provenance={cardBadges(card)} bodyClassName="p-0">
      <RecordStrip record={record} alsoServed={alsoServed} />

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
          // Not a <Tag>: that uppercases, and the caveat is shown in the API's own case.
          <p
            className="flex w-fit max-w-full items-baseline gap-1.5 rounded-sm border border-risk/60 px-1.5 py-[3px] font-mono text-[11px] leading-snug text-risk"
            title="Sample-size caveat from the API"
          >
            <span aria-hidden="true">!</span>
            <span data-testid="scorecard-caveat">{card.caveat}</span>
          </p>
        ) : null}
        {isSynthetic(card) ? (
          <p className="text-xs leading-relaxed text-risk">
            Synthetic demo fixtures: illustrative only, not evidence about real events.
          </p>
        ) : null}
        {card.official_blockers.length ? (
          <div className="flex flex-col gap-1">
            <p className="kicker">Not OFFICIAL because (official_blockers, from the API)</p>
            <ul className="flex flex-col gap-1">
              {card.official_blockers.map((b, i) => (
                <li key={i} className="break-words font-mono text-[11px] leading-relaxed text-text-2">
                  {b}
                </li>
              ))}
            </ul>
          </div>
        ) : null}
        <div className="flex flex-wrap gap-x-8 gap-y-2 pt-1">
          <Stat label="Events scored (n)" value={card.n_events} />
          <Stat label="Snapshots excluded" value={card.n_excluded} />
          <Stat label="Predictions ignored" value={card.ignored_predictions.length} />
        </div>
      </div>

      <div className="relative overflow-x-auto">
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
                    {f === "market" ? (
                      <span className="block max-w-[28rem] font-mono text-[10px] font-normal leading-snug text-muted">
                        {card.market_label}
                      </span>
                    ) : null}
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
          label="Δ Brier vs market (paired bootstrap CI)"
          preserveCase
          value={
            cmp ? (
              <span className="flex flex-col items-end gap-0.5">
                <span className="text-lg text-text">
                  <Num value={cmp.mean_delta_brier} precise />{" "}
                  <span className="text-text-2">
                    [<Num value={cmp.ci_low} precise />, <Num value={cmp.ci_high} precise />]
                  </span>
                </span>
                <span className="font-mono text-[10.5px] text-muted">
                  {cmp.agent_variant} − {cmp.baseline} · confidence <span className="num">{cmp.confidence}</span> · B ={" "}
                  <span className="num">{cmp.n_resamples}</span> · seed <span className="num">{cmp.seed}</span>
                </span>
              </span>
            ) : undefined
          }
        />
      </dl>

      <div className="border-t border-line px-5 py-4">
        <p className="kicker mb-2">Exclusions by reason (exclusions_by_reason, as sent)</p>
        {reasons.length === 0 ? (
          <p className="font-mono text-xs text-muted">None reported by the API.</p>
        ) : (
          <ul className="flex flex-col gap-2">
            {reasons.map(([reason, count]) => (
              <li key={reason} className="flex items-baseline justify-between gap-4 border-b border-line/70 pb-2 last:border-b-0">
                <span className="min-w-0">
                  <code className="break-all font-mono text-xs text-text-2">{reason}</code>
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
                <li key={`x-${i}`} className={`break-all ${mine(x.prediction_ids) ? "text-accent" : ""}`}>
                  <span className="text-text-2">{x.event_id}</span> · {x.as_of} · {x.reason}
                  {x.prediction_ids.length ? <> · {x.prediction_ids.join(", ")}</> : null}
                  {mine(x.prediction_ids) ? " · ← this forecast" : null}
                </li>
              ))}
              {card.ignored_predictions.map((x) => (
                <li key={`i-${x.prediction_id}`} className={`break-all ${mine([x.prediction_id]) ? "text-accent" : ""}`}>
                  ignored <span className="text-text-2">{x.prediction_id}</span> · {x.event_id} · {x.as_of} · {x.reason}
                  {mine([x.prediction_id]) ? " · ← this forecast" : null}
                </li>
              ))}
            </ul>
          </details>
        ) : null}
      </div>

      <PerEventTable card={card} isMine={mine} />

      <div className="flex flex-col gap-1 border-t border-line px-5 py-3 text-xs leading-relaxed text-muted">
        <p>
          Market-only uses the {card.market_label}. Lower Brier and log loss are better; Δ &lt; 0 means the agent&apos;s
          mean Brier was lower. Label, verdict, caveat and exclusions are the API&apos;s text, shown as sent.
        </p>
      </div>
    </Panel>
  );
}

/** Where this card came from: the API's ScorecardRecord for it, verbatim. */
function RecordStrip({ record, alsoServed }: { record: ScorecardRecord; alsoServed: ScorecardRecord[] }) {
  const cell = "flex min-w-0 flex-col gap-0.5";
  const key = "font-mono text-[10px] uppercase tracking-[0.12em] text-muted";
  const val = "break-all font-mono text-xs text-text-2";
  return (
    <div className="flex flex-col gap-3 border-b border-line bg-bg/40 px-5 py-3">
      <div className="grid grid-cols-1 gap-x-6 gap-y-2 sm:grid-cols-2 2xl:grid-cols-5">
        <div className={cell}>
          <span className={key}>Origin</span>
          <span className={val} data-testid="scorecard-origin">
            {ORIGIN_TEXT[record.origin]}
          </span>
        </div>
        <div className={cell}>
          <span className={key}>Case set</span>
          <span className={val} data-testid="scorecard-case-set">
            {record.case_set ?? <Missing>not sent</Missing>}
          </span>
        </div>
        <div className={cell}>
          <span className={key}>Recorded at</span>
          <span className={val} data-testid="scorecard-recorded-at">
            {record.recorded_at}
          </span>
        </div>
        <div className={cell}>
          <span className={key}>run_id</span>
          <span className={val} data-testid="scorecard-run-id">
            {record.run_id ?? <Missing>none (not an official run)</Missing>}
          </span>
        </div>
        <div className={cell}>
          <span className={key}>Model</span>
          <span className={val} data-testid="scorecard-models">
            {record.agent_models.length ? record.agent_models.join(", ") : <Missing>no scored forecast</Missing>}
          </span>
        </div>
      </div>
      <details className="rounded-md border border-line px-3 py-2">
        <summary className="cursor-pointer font-mono text-[11px] uppercase tracking-[0.12em] text-text-2">
          Snapshot file and hashes
        </summary>
        <dl className="mt-2 flex flex-col gap-1.5 font-mono text-[10.5px] text-muted">
          <div>
            <dt>source · file</dt>
            <dd className="break-all text-text-2">
              {record.source} · {record.file}
            </dd>
          </div>
          <div>
            <dt>scorecard_sha256</dt>
            <dd className="break-all text-text-2">{record.scorecard_sha256}</dd>
          </div>
          <div>
            <dt>snapshot_sha256</dt>
            <dd className="break-all text-text-2">{record.snapshot_sha256}</dd>
          </div>
        </dl>
      </details>
      {alsoServed.length ? (
        <div className="text-xs leading-relaxed text-muted">
          <p>The API also served these snapshots for this variant later in its order; not shown as cards:</p>
          <ul className="mt-1 flex flex-col gap-0.5 font-mono text-[10.5px]">
            {alsoServed.map((r) => (
              <li key={r.file} className="break-all">
                {r.origin} · case set {r.case_set ?? "not sent"} · {r.recorded_at} · {r.file}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
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

/**
 * Per-event scores, collapsed by default: the y column is the outcome of every scored event (#117), so it opens only
 * on an explicit click, never while D.0 is still sealed by accident of layout.
 */
function PerEventTable({ card, isMine }: { card: ScorecardData; isMine: (ids: string[]) => boolean }) {
  return (
    <details className="group border-t border-line" data-testid="per-event-outcomes">
      <summary className="cursor-pointer px-5 py-3 font-mono text-[11px] uppercase tracking-[0.12em] text-text-2 hover:text-text">
        Per-event outcomes (shows y of every scored event)
      </summary>
      <p className="kicker px-5 pt-1">Per-event Brier (averaged over each event&apos;s snapshots by the API)</p>
      {card.per_event.length === 0 ? (
        <p className="px-5 pb-4 pt-2 font-mono text-xs uppercase tracking-[0.08em] text-muted">
          Not available: no event was scored
        </p>
      ) : (
        <div className="relative overflow-x-auto">
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
              {card.per_event.map((e) => {
                const mine = isMine(e.prediction_ids);
                return (
                  <tr key={e.event_id} className={`border-b border-line/70 last:border-b-0 ${mine ? "bg-accent-soft" : ""}`}>
                    <th scope="row" className="px-5 py-2.5 font-mono text-xs font-normal text-text-2">
                      {e.event_id}
                      <span className="ml-2 text-muted">
                        ×<span className="num">{e.n_snapshots}</span>
                      </span>
                      {mine ? <span className="ml-2 text-accent">← this forecast</span> : null}
                      {e.market_refs.length ? (
                        <span className="block break-all text-[10px] text-muted">market: {e.market_refs.join(", ")}</span>
                      ) : null}
                    </th>
                    <td className="num px-3 py-2.5 text-right text-sm text-text-2">{e.y}</td>
                    {card.forecasters.map((f) => (
                      <td key={f} className="px-5 py-2.5 text-right text-sm text-text">
                        {typeof e.brier[f] === "number" ? <Num value={e.brier[f]} /> : <Missing />}
                      </td>
                    ))}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </details>
  );
}

/**
 * No served card for this variant (or no response yet): the structure, every value NOT AVAILABLE. No scorecard is
 * NOT AVAILABLE, not INSUFFICIENT DATA (#117): that verdict belongs to a served card with n < 5.
 */
function EmptyScorecard({
  variant,
  status,
  loading,
}: {
  variant: ScorableVariant;
  status: BenchmarkResponse["status"] | null;
  loading: boolean;
}) {
  const title = loading ? "Scorecard · requesting" : status === null ? "Scorecard · not loaded" : `Scorecard · ${variant}`;
  return (
    <Panel code="D.2" title={title} provenance={loading ? [] : "NOT AVAILABLE"} bodyClassName="p-0">
      <div className="flex flex-col gap-1.5 border-b border-line px-5 py-4">
        <p
          className="font-mono text-2xl font-medium uppercase tracking-[0.08em] text-muted md:text-3xl"
          data-testid="scorecard-empty"
        >
          {loading ? "Requesting" : "Not available"}
        </p>
        <p className="text-xs leading-relaxed text-muted">
          {loading
            ? `Waiting for GET ${BENCHMARK_PATH}; nothing is shown until it answers.`
            : status === null
              ? "No benchmark response, so no scorecard is shown."
              : `The API served no recorded scorecard for ${variant}. See the notes above; no number is shown in its place.`}
        </p>
      </div>
      <div className="relative overflow-x-auto">
        <table className="w-full min-w-[440px] border-collapse text-left">
          <caption className="sr-only">
            Mean forecast scores for agent, market-only and naive baseline. No recorded scorecard, so every cell is not
            available.
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
        <Field label="Δ Brier vs market (paired bootstrap CI)" preserveCase />
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
