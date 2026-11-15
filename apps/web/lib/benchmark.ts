/**
 * REVEAL + scorecard client (issue #50): `POST /api/replay/{prediction_id}/reveal` and `GET /api/benchmark`.
 *
 * Types copy the Pydantic models on main field for field:
 * - `services/api/routes/replay.py`: `RevealResponse`, `PredictionScores`, `Baselines`, `MarketBaselineScores`,
 *   `NaiveBaselineScores` (#76);
 * - `services/api/routes/benchmark.py`: `BenchmarkResponse`, `ScorecardRecord` (#91);
 * - `services/api/core/evaluator.py`: `Scorecard`, `Comparison`, `ForecasterSummary`, `EventScore`,
 *   `ScoreExclusion`, `IgnoredPrediction`, `SealedOutcome`;
 * - `services/api/models.py`: `Prediction`, `ApiError`.
 *
 * Nothing here computes a score, a mean, an interval or a verdict. The shape checks confirm that the fields the UI
 * renders are present and typed, and spot-check a few of the API's display rules (MATH_MODEL §6) and invariants as
 * defence in depth (see `checkScorecard`). They cannot prove a card correct: a card that passes is shown as the
 * API's claim, labeled with its provenance. A body that fails is `malformed` → NOT AVAILABLE, never patched up.
 * Keys outside the checked set are not rendered.
 *
 * `POST /api/benchmark/compute` (admin only, reveals outcomes) is deliberately NOT wrapped here: the UI never calls it.
 */

import { API_BASE } from "./api";
import { presenterAuthHeader } from "./presenter";

export const BENCHMARK_PATH = "/api/benchmark";
export const revealPath = (predictionId: string) => `/api/replay/${encodeURIComponent(predictionId)}/reveal`;

// --- wire types (mirror the Pydantic models) -------------------------------------------------------------------

/** models.ForecastVariant. */
export type ForecastVariant = "agent_only" | "agent_plus_market" | "hosted_comparator";
/** routes/benchmark.ScoredVariant, in the API's VARIANT_ORDER. */
export const SCORABLE_VARIANTS = ["agent_only", "agent_plus_market"] as const;
export type ScorableVariant = (typeof SCORABLE_VARIANTS)[number];

/** models.Provenance wire values. */
export type WireProvenanceValue = "REAL_HISTORICAL" | "SYNTHETIC" | "RECORDED_RUN" | "SIMULATED" | "ILLUSTRATIVE";
const PROVENANCE_VALUES: readonly string[] = ["REAL_HISTORICAL", "SYNTHETIC", "RECORDED_RUN", "SIMULATED", "ILLUSTRATIVE"];

/** models.Prediction: the persisted forecast. */
export interface Prediction {
  prediction_id: string;
  event_id: string;
  as_of: string;
  agent_model: string;
  model_digest: string | null;
  variant: ForecastVariant;
  p_yes: number;
  decision: "act" | "wait" | "hedge";
  rationale: string;
  evidence_ids: string[];
  prompt_sha256: string;
  snapshot_sha256: string;
  temperature: number;
  seed: number | null;
  recorded_at: string;
  provenance: WireProvenanceValue;
  /** SHA-256 of the temporal gate's rendered prompt (before any repair turn). null only on non-model records. */
  gated_prompt_sha256: string | null;
  /** 1 = first answer validated; 2 = validated after the one schema repair. */
  attempts: number | null;
  transcript_sha256: string | null;
  num_ctx: number | null;
  num_predict: number | null;
}

/** evaluator.SealedOutcome (file format of data/sealed_outcomes/<event_id>.json). */
export interface SealedOutcome {
  event_id: string;
  outcome: "YES" | "NO";
  resolved_at: string | null;
  source_url: string;
  provenance: WireProvenanceValue;
  notes: string | null;
}

/** replay.PredictionScores: computed server-side by evaluator.brier / log_loss / correct_at_half. */
export interface PredictionScores {
  brier: number;
  log_loss: number;
  /** 1.0 if p > 0.5 called it right (p = 0.5 counts as NO), else 0.0. */
  accuracy_at_0_5: number;
}

/** replay.MarketBaselineScores. */
export interface MarketBaselineScores {
  /** Market-implied probability (price-derived) fixed by the gate before reveal. */
  p_yes: number;
  brier: number;
  log_loss: number;
  /** The API's label for this baseline price (synthetic or market-implied), shown verbatim (#117). */
  label: string;
  /** `"<venue>:<market_id>"` frozen before reveal; a `synthetic:` ref is a case author's price, not a market. */
  ref: string | null;
}

/** A synthetic-venue baseline ref (PR #111): never a real market. Read from the served ref only. */
export function isSyntheticRef(ref: string | null | undefined): boolean {
  return typeof ref === "string" && ref.startsWith("synthetic:");
}

/** replay.NaiveBaselineScores: scores of the constant forecast p = 0.5. */
export interface NaiveBaselineScores {
  brier: number;
  log_loss: number;
}

/** replay.Baselines. `market: null` = market baseline NOT AVAILABLE at this as_of. */
export interface Baselines {
  market: MarketBaselineScores | null;
  naive: NaiveBaselineScores;
}

/** replay.RevealResponse (contract fixed by the lead on #44). */
export interface RevealResponse {
  prediction: Prediction;
  y: 0 | 1;
  sealed: SealedOutcome;
  revealed_at: string;
  persisted_at: string;
  persist_seq: number;
  reveal_seq: number;
  event_first_revealed_at: string;
  event_first_reveal_seq: number;
  /** persist_seq < event_first_reveal_seq, decided by the API. False: the benchmark ignores this forecast. */
  persisted_before_outcome_revealed: boolean;
  scores: PredictionScores;
  baselines: Baselines;
  /** Content hash of the case record the forecast was made from, frozen with the prediction (#180). Optional: an
   * older API omits it, and the unsealing line then says NOT AVAILABLE. */
  case_sha256?: string;
}

/** evaluator.ExclusionReason. */
export type ExclusionReason =
  | "no_persisted_prediction"
  | "persisted_after_outcome_revealed"
  | "multiple_predictions"
  | "contamination_likely"
  | "market_not_available"
  | "sealed_outcome_not_available"
  | "context_mismatch";

/**
 * UI gloss for each reason (docs/EVALUATION_PROTOCOL.md §6). Shown under the API's reason key, never instead of it.
 */
export const EXCLUSION_REASON_TEXT: Record<ExclusionReason, string> = {
  no_persisted_prediction: "No forecast was persisted for this snapshot.",
  persisted_after_outcome_revealed: "Every forecast for this snapshot was saved after the event's outcome was first revealed.",
  multiple_predictions: "More than one forecast was saved before reveal; none is chosen.",
  contamination_likely: "The model probably saw this event in pretraining (contamination_flag = likely).",
  market_not_available: "No market quote within 24 h before the cutoff, so there is no market baseline.",
  sealed_outcome_not_available: "No sealed outcome file exists for this event.",
  context_mismatch: "The forecast's input could not be re-derived from the committed case data with the same hashes.",
};

/** evaluator.ScoreExclusion. */
export interface ScoreExclusion {
  event_id: string;
  as_of: string;
  reason: ExclusionReason;
  prediction_ids: string[];
}

/** evaluator.IgnoredPrediction. */
export interface IgnoredPrediction {
  prediction_id: string;
  event_id: string;
  as_of: string;
  reason: "persisted_after_outcome_revealed";
}

/** evaluator.EventScore (averaged over the event's snapshots by the API). */
export interface EventScore {
  event_id: string;
  n_snapshots: number;
  y: number;
  prediction_ids: string[];
  /** "venue:market_id" of the market baseline used. */
  market_refs: string[];
  /** Keyed by forecaster ("naive", "market", agent variant). */
  brier: Record<string, number>;
  log_loss: Record<string, number>;
  accuracy_at_0_5: Record<string, number>;
  /**
   * The persisted forecast's p_yes behind this row's agent scores (#180). Set only on a single-snapshot row; null (or
   * absent, on a card recorded before #180) = NOT AVAILABLE. The API refuses a card whose p disagrees with the row's
   * own Brier / log loss, and checks a committed card's p against its run's rows.
   */
  agent_p_yes?: number | null;
  /** The market baseline price (market-implied, price-derived) the gate froze before reveal; same rules as agent_p_yes. */
  market_p_yes?: number | null;
}

/** evaluator.ForecasterSummary. */
export interface ForecasterSummary {
  mean_brier: number;
  mean_log_loss: number;
  accuracy_at_0_5: number;
}

/** evaluator.Comparison. */
export interface Comparison {
  agent_variant: ForecastVariant;
  baseline: "market";
  metric: "brier";
  /** agent - market; negative means the agent had lower (better) Brier. */
  mean_delta_brier: number;
  ci_low: number;
  ci_high: number;
  confidence: number;
  n_resamples: number;
  seed: number;
}

/** Case-set tag (PR #111). Older snapshots may omit it or send null; neither rejects the response. */
export type CaseSet = "real" | "synthetic";

/** evaluator.Scorecard. `label`, `verdict` and `caveat` are display strings set by the API (MATH_MODEL §6). */
export interface Scorecard {
  label: string;
  verdict: string;
  caveat: string | null;
  /** null when no event could be scored. */
  provenance: WireProvenanceValue | null;
  agent_variant: ForecastVariant;
  forecasters: string[];
  market_label: string;
  n_events: number;
  n_excluded: number;
  exclusions_by_reason: Record<string, number>;
  exclusions: ScoreExclusion[];
  ignored_predictions: IgnoredPrediction[];
  per_event: EventScore[];
  summary: Record<string, ForecasterSummary> | null;
  comparison: Comparison | null;
  /** Why a real-historical scorecard is not OFFICIAL; empty when it is. */
  official_blockers: string[];
  case_set?: CaseSet | null;
}

/** routes/benchmark.ScorecardRecord: where items[i] came from, and its hashes. */
export interface ScorecardRecord {
  agent_variant: ScorableVariant;
  /** real or synthetic case set (PR #111); absent or null on an API that does not send it. */
  case_set?: CaseSet | null;
  recorded_at: string;
  source: "compute_route" | "record_runs_script";
  /** committed: data/recorded_runs/ in git (official run script); computed: var/scorecards/ on that server. */
  origin: "committed" | "computed";
  run_id: string | null;
  /** Snapshot file name (no directory). */
  file: string;
  scorecard_sha256: string;
  snapshot_sha256: string;
  /** agent_model of every scored forecast. */
  agent_models: string[];
}

/** routes/benchmark.BenchmarkResponse. `records[i]` describes `items[i]`. */
export interface BenchmarkResponse {
  status: "AVAILABLE" | "NOT AVAILABLE";
  provenance: "RECORDED_RUN";
  items: Scorecard[];
  records: ScorecardRecord[];
  notes: string[];
}

/** One variant's card as the UI shows it: the FIRST served item for that variant (the API's own precedence). */
export interface VariantCard {
  variant: ScorableVariant;
  /** Index in `items` / `records`. */
  index: number;
  card: Scorecard;
  record: ScorecardRecord;
  /** Other snapshots the API also served for this variant (later in its order); not shown as cards. */
  alsoServed: ScorecardRecord[];
}

/** One plain-words line per scored variant (#124): what the model was shown. UI copy, not data. */
export const VARIANT_PLAIN: Record<ScorableVariant, string> = {
  agent_only: "Agent only: the model saw evidence, no market price",
  agent_plus_market: "Agent + market: the model also saw the market price at the cutoff",
};

/**
 * The API's notes that name this variant (e.g. "No recorded scorecard for agent_plus_market (NOT AVAILABLE).").
 * Selection only: matched on the variant key as a whole word, strings returned verbatim.
 */
export function notesForVariant(notes: string[], variant: ScorableVariant): string[] {
  const word = new RegExp(`(^|[^a-z_])${variant}($|[^a-z_])`);
  return notes.filter((n) => word.test(n));
}

/** First item per variant, in the API's order. Selection only: nothing is merged, pooled or re-ranked. */
export function firstPerVariant(data: BenchmarkResponse): Partial<Record<ScorableVariant, VariantCard>> {
  const out: Partial<Record<ScorableVariant, VariantCard>> = {};
  data.records.forEach((record, index) => {
    const card = data.items[index];
    if (!card) return;
    const seen = out[record.agent_variant];
    if (seen) seen.alsoServed.push(record);
    else out[record.agent_variant] = { variant: record.agent_variant, index, card, record, alsoServed: [] };
  });
  return out;
}

// --- failures --------------------------------------------------------------------------------------------------

/**
 * `admin_required`: 401/403 ADMIN_TOKEN_REQUIRED (public mode). `route_missing`: 404 without a FAULTLINE error code
 * (FastAPI's default `{detail}`), i.e. that API build does not serve the route. `not_revealable`: 409 NOT_REVEALABLE.
 * `outcome_not_available`: 404 with code NOT_FOUND (no sealed outcome for the event). `validation`: 422.
 * `http`: any other non-2xx (message verbatim). `malformed`: a 2xx body that does not match the contract.
 */
export type BenchmarkErrorKind =
  | "network"
  | "timeout"
  | "aborted"
  | "admin_required"
  | "route_missing"
  | "not_revealable"
  | "outcome_not_available"
  | "validation"
  | "http"
  | "malformed";

export interface BenchmarkFailure {
  ok: false;
  kind: BenchmarkErrorKind;
  message: string;
  status?: number;
  code?: string;
  /** Method + exact request URL, shown so the presenter can see what was asked. */
  request: string;
}

export type Result<T> = { ok: true; data: T; request: string } | BenchmarkFailure;

// --- shape checks (contract only; nothing computed or defaulted) -----------------------------------------------

const isObj = (v: unknown): v is Record<string, unknown> => !!v && typeof v === "object" && !Array.isArray(v);
const isStr = (v: unknown): v is string => typeof v === "string";
const isStrOrNull = (v: unknown): v is string | null => v === null || typeof v === "string";
const isNum = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);
const isInt = (v: unknown): v is number => isNum(v) && Number.isInteger(v);
const isIntOrNull = (v: unknown): v is number | null => v === null || isInt(v);
const isStrArray = (v: unknown): v is string[] => Array.isArray(v) && v.every(isStr);
const isNumRecord = (v: unknown): v is Record<string, number> => isObj(v) && Object.values(v).every(isNum);
const isSha = (v: unknown): v is string => isStr(v) && /^[0-9a-f]{64}$/.test(v);
const isShaOrNull = (v: unknown): v is string | null => v === null || isSha(v);
const isScorable = (v: unknown): v is ScorableVariant => (SCORABLE_VARIANTS as readonly unknown[]).includes(v);
const FORECAST_VARIANTS: readonly string[] = ["agent_only", "agent_plus_market", "hosted_comparator"];
const isForecastVariant = (v: unknown): v is ForecastVariant => isStr(v) && FORECAST_VARIANTS.includes(v);
const DECISIONS: readonly string[] = ["act", "wait", "hedge"];
const isCaseSetOrAbsent = (v: unknown) => v === undefined || v === null || v === "real" || v === "synthetic";

const EXCLUSION_REASONS = Object.keys(EXCLUSION_REASON_TEXT);

/**
 * MATH_MODEL §6 display rules, as constants only for the consistency check below (the API applies them; the UI
 * never derives a verdict, label or caveat from them).
 */
const MIN_EVENTS = 5;
const SMALL_SAMPLE_EVENTS = 30;
const INSUFFICIENT_DATA = "INSUFFICIENT DATA";
const AGENT_BETTER = "agent better than market";
const NO_IMPROVEMENT = "No improvement measured";
/** core/evaluator.py verdict strings: every verdict the API can send. */
export const KNOWN_VERDICTS: readonly string[] = [AGENT_BETTER, NO_IMPROVEMENT, INSUFFICIENT_DATA];

function checkPrediction(p: unknown, at: string): string | null {
  if (!isObj(p)) return `${at} missing`;
  for (const k of ["prediction_id", "event_id", "as_of", "agent_model", "rationale", "recorded_at"]) {
    if (!isStr(p[k])) return `${at}.${k} missing`;
  }
  if (!isForecastVariant(p.variant)) return `${at}.variant is not a known variant`;
  if (!isStr(p.decision) || !DECISIONS.includes(p.decision)) return `${at}.decision is not act/wait/hedge`;
  if (!isSha(p.prompt_sha256) || !isSha(p.snapshot_sha256)) return `${at} prompt/snapshot sha256 malformed`;
  if (!isNum(p.p_yes) || p.p_yes < 0 || p.p_yes > 1) return `${at}.p_yes is not a probability`;
  if (!isNum(p.temperature)) return `${at}.temperature missing`;
  if (!isIntOrNull(p.seed)) return `${at}.seed malformed`;
  if (!isStrOrNull(p.model_digest)) return `${at}.model_digest malformed`;
  if (!isStrArray(p.evidence_ids)) return `${at}.evidence_ids malformed`;
  if (!isStr(p.provenance) || !PROVENANCE_VALUES.includes(p.provenance)) return `${at}.provenance is not a known value`;
  if (!isShaOrNull(p.gated_prompt_sha256) || !isShaOrNull(p.transcript_sha256)) return `${at} audit sha256 malformed`;
  if (!(p.attempts === null || p.attempts === 1 || p.attempts === 2)) return `${at}.attempts is not 1, 2 or null`;
  if (!isIntOrNull(p.num_ctx) || !isIntOrNull(p.num_predict)) return `${at} num_ctx / num_predict malformed`;
  return null;
}

function checkSealed(s: unknown, at: string): string | null {
  if (!isObj(s)) return `${at} missing`;
  if (!isStr(s.event_id)) return `${at}.event_id missing`;
  if (s.outcome !== "YES" && s.outcome !== "NO") return `${at}.outcome is not YES or NO`;
  if (!isStrOrNull(s.resolved_at)) return `${at}.resolved_at malformed`;
  if (!isStr(s.source_url)) return `${at}.source_url missing`;
  if (!isStrOrNull(s.notes)) return `${at}.notes malformed`;
  if (!isStr(s.provenance) || !PROVENANCE_VALUES.includes(s.provenance)) return `${at}.provenance is not a known value`;
  return null;
}

/** Returns a problem description, or null when the body has every field the reveal panel renders. */
export function checkRevealResponse(body: unknown, requestedId: string): string | null {
  if (!isObj(body)) return "body is not an object";
  const problem = checkPrediction(body.prediction, "prediction") ?? checkSealed(body.sealed, "sealed");
  if (problem) return problem;
  const pred = body.prediction as Record<string, unknown>;
  const sealed = body.sealed as Record<string, unknown>;
  if (pred.prediction_id !== requestedId) return "prediction.prediction_id differs from the requested id";
  if (sealed.event_id !== pred.event_id) return "sealed.event_id differs from prediction.event_id";
  if (body.y !== 0 && body.y !== 1) return "y is not 0 or 1";
  // Consistency of two API fields, not a computation: y must encode sealed.outcome.
  if ((body.y === 1) !== (sealed.outcome === "YES")) return "y disagrees with sealed.outcome";
  for (const k of ["revealed_at", "persisted_at", "event_first_revealed_at"]) {
    if (!isStr(body[k])) return `${k} missing`;
  }
  for (const k of ["persist_seq", "reveal_seq", "event_first_reveal_seq"]) {
    if (!isInt(body[k])) return `${k} missing`;
  }
  if (typeof body.persisted_before_outcome_revealed !== "boolean") return "persisted_before_outcome_revealed missing";
  if (body.case_sha256 !== undefined && !isSha(body.case_sha256)) return "case_sha256 malformed";
  const s = body.scores;
  if (!isObj(s) || !isNum(s.brier) || !isNum(s.log_loss) || !isNum(s.accuracy_at_0_5)) return "scores missing";
  const b = body.baselines;
  if (!isObj(b)) return "baselines missing";
  if (!isObj(b.naive) || !isNum(b.naive.brier) || !isNum(b.naive.log_loss)) return "baselines.naive malformed";
  if (b.market !== null) {
    const m = b.market;
    if (!isObj(m) || !isNum(m.p_yes) || m.p_yes < 0 || m.p_yes > 1 || !isNum(m.brier) || !isNum(m.log_loss)) {
      return "baselines.market malformed";
    }
    // #117: the label is shown verbatim and the ref decides the SYNTHETIC badge, so both must be served.
    if (!isStr(m.label) || !m.label.trim()) return "baselines.market.label missing";
    if (!isStrOrNull(m.ref)) return "baselines.market.ref malformed";
  }
  return null;
}

function checkScorecard(c: unknown, at: string): string | null {
  if (!isObj(c)) return `${at} is not an object`;
  if (!isStr(c.label) || !c.label.trim()) return `${at}.label missing`;
  if (!isStr(c.verdict) || !c.verdict.trim()) return `${at}.verdict missing`;
  if (!isStrOrNull(c.caveat)) return `${at}.caveat malformed`;
  if (!(c.provenance === null || (isStr(c.provenance) && PROVENANCE_VALUES.includes(c.provenance)))) {
    return `${at}.provenance is not a known value or null`;
  }
  if (!isForecastVariant(c.agent_variant)) return `${at}.agent_variant is not a known variant`;
  if (!isStrArray(c.forecasters) || c.forecasters.length === 0) return `${at}.forecasters missing`;
  if (!isStr(c.market_label)) return `${at}.market_label missing`;
  if (!isInt(c.n_events) || c.n_events < 0) return `${at}.n_events malformed`;
  if (!isInt(c.n_excluded) || c.n_excluded < 0) return `${at}.n_excluded malformed`;
  if (!isObj(c.exclusions_by_reason) || !Object.values(c.exclusions_by_reason).every(isInt)) {
    return `${at}.exclusions_by_reason malformed`;
  }
  const unknownReason = Object.keys(c.exclusions_by_reason).find((r) => !EXCLUSION_REASONS.includes(r));
  if (unknownReason !== undefined) return `${at}.exclusions_by_reason has unknown reason "${unknownReason}"`;
  if (!Array.isArray(c.exclusions)) return `${at}.exclusions missing`;
  for (let i = 0; i < c.exclusions.length; i++) {
    const x = c.exclusions[i];
    if (!isObj(x) || !isStr(x.event_id) || !isStr(x.as_of) || !EXCLUSION_REASONS.includes(x.reason as string)) {
      return `${at}.exclusions[${i}] malformed`;
    }
    if (!isStrArray(x.prediction_ids)) return `${at}.exclusions[${i}].prediction_ids malformed`;
  }
  if (!Array.isArray(c.ignored_predictions)) return `${at}.ignored_predictions missing`;
  for (let i = 0; i < c.ignored_predictions.length; i++) {
    const x = c.ignored_predictions[i];
    if (!isObj(x) || !isStr(x.prediction_id) || !isStr(x.event_id) || !isStr(x.as_of)) {
      return `${at}.ignored_predictions[${i}] malformed`;
    }
    if (x.reason !== "persisted_after_outcome_revealed") return `${at}.ignored_predictions[${i}].reason is not known`;
  }
  if (!Array.isArray(c.per_event)) return `${at}.per_event missing`;
  if (c.per_event.length !== c.n_events) return `${at}.per_event length differs from n_events`;
  for (let i = 0; i < c.per_event.length; i++) {
    const e = c.per_event[i];
    if (!isObj(e) || !isStr(e.event_id) || !isInt(e.n_snapshots) || (e.y !== 0 && e.y !== 1)) {
      return `${at}.per_event[${i}] malformed`;
    }
    if (!isStrArray(e.prediction_ids) || !isStrArray(e.market_refs)) return `${at}.per_event[${i}] ids/refs malformed`;
    if (!isNumRecord(e.brier) || !isNumRecord(e.log_loss) || !isNumRecord(e.accuracy_at_0_5)) {
      return `${at}.per_event[${i}] scores malformed`;
    }
    for (const k of ["agent_p_yes", "market_p_yes"] as const) {
      const q = e[k];
      if (q !== undefined && q !== null && !(isNum(q) && q >= 0 && q <= 1)) return `${at}.per_event[${i}].${k} is not a probability`;
    }
  }
  if (c.summary !== null) {
    if (!isObj(c.summary)) return `${at}.summary malformed`;
    for (const [k, v] of Object.entries(c.summary)) {
      if (!isObj(v) || !isNum(v.mean_brier) || !isNum(v.mean_log_loss) || !isNum(v.accuracy_at_0_5)) {
        return `${at}.summary.${k} malformed`;
      }
    }
  }
  if (c.comparison !== null) {
    const k = c.comparison;
    if (!isObj(k)) return `${at}.comparison malformed`;
    for (const f of ["mean_delta_brier", "ci_low", "ci_high", "confidence"]) {
      if (!isNum(k[f])) return `${at}.comparison.${f} missing`;
    }
    if (!isInt(k.n_resamples) || !isInt(k.seed)) return `${at}.comparison n_resamples / seed missing`;
    if (!isForecastVariant(k.agent_variant)) return `${at}.comparison.agent_variant is not a known variant`;
    if (k.agent_variant !== c.agent_variant) return `${at}.comparison.agent_variant differs from the card's variant`;
    if (k.baseline !== "market" || k.metric !== "brier") return `${at}.comparison baseline/metric not market/brier`;
  }
  if (!isStrArray(c.official_blockers)) return `${at}.official_blockers missing`;
  if (!isCaseSetOrAbsent(c.case_set)) return `${at}.case_set is not real, synthetic or null`;
  // Defence in depth: some of the API's own display rules (MATH_MODEL §6), checked, never applied. A card that
  // breaks one is not shown. Passing them does not make the card correct; the API remains the source of truth.
  if (!KNOWN_VERDICTS.includes(c.verdict)) return `${at}.verdict is not a known verdict`;
  if (c.n_events < MIN_EVENTS && (c.verdict !== INSUFFICIENT_DATA || c.summary !== null || c.comparison !== null)) {
    return `${at}: n = ${c.n_events} < ${MIN_EVENTS} but the card is not INSUFFICIENT DATA without summary/comparison`;
  }
  if (c.n_events >= MIN_EVENTS) {
    if (!isObj(c.summary) || !isObj(c.comparison)) {
      return `${at}: n = ${c.n_events} >= ${MIN_EVENTS} but summary or comparison is missing`;
    }
    if (c.verdict === INSUFFICIENT_DATA) return `${at}: n = ${c.n_events} >= ${MIN_EVENTS} but the verdict is INSUFFICIENT DATA`;
    if ((c.verdict === AGENT_BETTER) !== (c.comparison.ci_high as number) < 0) {
      return `${at}: verdict "${c.verdict}" disagrees with the interval (ci_high < 0 exactly when "${AGENT_BETTER}")`;
    }
  }
  if (c.n_events >= MIN_EVENTS && c.n_events < SMALL_SAMPLE_EVENTS && c.caveat === null) {
    return `${at}: n = ${c.n_events} < ${SMALL_SAMPLE_EVENTS} but no small-sample caveat`;
  }
  if (c.n_events >= SMALL_SAMPLE_EVENTS && c.caveat !== null) {
    return `${at}: n = ${c.n_events} >= ${SMALL_SAMPLE_EVENTS} but a small-sample caveat is set`;
  }
  if (c.label.startsWith("OFFICIAL") && (c.provenance !== "REAL_HISTORICAL" || c.official_blockers.length > 0)) {
    return `${at}: labeled OFFICIAL but not REAL_HISTORICAL with no official_blockers`;
  }
  return null;
}

function checkRecord(r: unknown, at: string): string | null {
  if (!isObj(r)) return `${at} is not an object`;
  if (!isScorable(r.agent_variant)) return `${at}.agent_variant is not a scored variant`;
  if (!isStr(r.recorded_at)) return `${at}.recorded_at missing`;
  if (r.source !== "compute_route" && r.source !== "record_runs_script") return `${at}.source is not a known value`;
  if (r.origin !== "committed" && r.origin !== "computed") return `${at}.origin is not committed or computed`;
  if (!isStrOrNull(r.run_id)) return `${at}.run_id malformed`;
  if (!isStr(r.file) || !r.file) return `${at}.file missing`;
  if (!isSha(r.scorecard_sha256) || !isSha(r.snapshot_sha256)) return `${at} sha256 malformed`;
  if (!isStrArray(r.agent_models)) return `${at}.agent_models malformed`;
  if (!isCaseSetOrAbsent(r.case_set)) return `${at}.case_set is not real, synthetic or null`;
  return null;
}

/** Validates a GET /api/benchmark body; returns it typed, or a problem string. */
export function readBenchmark(body: unknown): BenchmarkResponse | string {
  if (!isObj(body)) return "body is not an object";
  if (body.status !== "AVAILABLE" && body.status !== "NOT AVAILABLE") return "status is not AVAILABLE or NOT AVAILABLE";
  if (body.provenance !== "RECORDED_RUN") return "provenance is not RECORDED_RUN";
  if (!Array.isArray(body.items) || !Array.isArray(body.records)) return "items / records missing";
  if (!isStrArray(body.notes)) return "notes missing";
  if (body.items.length !== body.records.length) return "records do not pair one-to-one with items";
  if ((body.status === "AVAILABLE") !== body.items.length > 0) return "status disagrees with the number of items";
  for (let i = 0; i < body.items.length; i++) {
    const problem = checkScorecard(body.items[i], `items[${i}]`) ?? checkRecord(body.records[i], `records[${i}]`);
    if (problem) return problem;
    const item = body.items[i] as Record<string, unknown>;
    const rec = body.records[i] as Record<string, unknown>;
    if (item.agent_variant !== rec.agent_variant) return `records[${i}].agent_variant differs from items[${i}]`;
  }
  return body as unknown as BenchmarkResponse;
}

// --- requests ----------------------------------------------------------------------------------------------------

function readErrorBody(body: unknown): { message: string | null; code?: string } {
  if (!isObj(body)) return { message: null };
  const code = isStr(body.code) ? body.code : undefined;
  if (isStr(body.message) && body.message.trim()) return { message: body.message, code };
  if (isStr(body.detail) && body.detail.trim()) return { message: body.detail, code };
  return { message: null, code };
}

async function request(
  method: "GET" | "POST",
  path: string,
  timeoutMs: number,
  signal: AbortSignal | undefined,
  /** true only for the reveal: attach the presenter token, if one is stored (lib/presenter.ts). */
  presenterAuth = false,
): Promise<{ ok: true; status: number; body: unknown; parsed: boolean; request: string } | BenchmarkFailure> {
  const url = `${API_BASE}${path}`;
  const label = `${method} ${url}`;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(new DOMException("timeout", "TimeoutError")), timeoutMs);
  const onAbort = () => controller.abort(signal?.reason);
  if (signal?.aborted) onAbort();
  signal?.addEventListener("abort", onAbort, { once: true });
  try {
    const headers = { Accept: "application/json", ...(presenterAuth ? presenterAuthHeader() : {}) };
    const res = await fetch(url, { method, headers, cache: "no-store", signal: controller.signal });
    let body: unknown = null;
    let parsed = true;
    try {
      body = await res.json();
    } catch {
      parsed = false;
    }
    if (!res.ok) {
      const { message, code } = readErrorBody(body);
      let kind: BenchmarkErrorKind = "http";
      if ((res.status === 401 || res.status === 403) && code === "ADMIN_TOKEN_REQUIRED") kind = "admin_required";
      else if (res.status === 409) kind = "not_revealable";
      else if (res.status === 404) kind = code === undefined ? "route_missing" : "outcome_not_available";
      else if (res.status === 422) kind = "validation";
      return { ok: false, kind, message: message ?? `HTTP ${res.status}`, status: res.status, code, request: label };
    }
    return { ok: true, status: res.status, body, parsed, request: label };
  } catch (err) {
    if (controller.signal.aborted) {
      const reason: unknown = controller.signal.reason;
      const timedOut = reason instanceof DOMException && reason.name === "TimeoutError";
      return timedOut
        ? { ok: false, kind: "timeout", message: `no response within ${timeoutMs / 1000} s`, request: label }
        : { ok: false, kind: "aborted", message: "aborted", request: label };
    }
    return { ok: false, kind: "network", message: err instanceof Error ? err.message : "request failed", request: label };
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", onAbort);
  }
}

/**
 * POST /api/replay/{prediction_id}/reveal. A logged, state-changing call: the server records the reveal, and any
 * forecast for the same event persisted afterwards is excluded from scoring. Call it only on an explicit click.
 * In public mode the API refuses it (401/403 ADMIN_TOKEN_REQUIRED) unless FAULTLINE_PUBLIC_INFERENCE=1; the presenter
 * token (lib/presenter.ts, sessionStorage only) is sent only when one is stored in this tab.
 * Never throws.
 */
export async function revealPrediction(predictionId: string, signal?: AbortSignal): Promise<Result<RevealResponse>> {
  const res = await request("POST", revealPath(predictionId), 10_000, signal, true);
  if (!res.ok) return res;
  if (!res.parsed) return { ok: false, kind: "malformed", message: "response was not JSON", status: res.status, request: res.request };
  const problem = checkRevealResponse(res.body, predictionId);
  if (problem) {
    return { ok: false, kind: "malformed", message: `malformed reveal payload: ${problem}`, status: res.status, request: res.request };
  }
  return { ok: true, data: res.body as RevealResponse, request: res.request };
}

/**
 * GET /api/benchmark: recorded scorecard snapshots only. Read-only on the server (never reveals, never opens the
 * prediction store or the sealed folder), so it is safe to request on page load. Never throws.
 */
export async function getBenchmark(signal?: AbortSignal): Promise<Result<BenchmarkResponse>> {
  const res = await request("GET", BENCHMARK_PATH, 15_000, signal);
  if (!res.ok) return res;
  if (!res.parsed) return { ok: false, kind: "malformed", message: "response was not JSON", status: res.status, request: res.request };
  const data = readBenchmark(res.body);
  if (typeof data === "string") {
    return { ok: false, kind: "malformed", message: `malformed benchmark payload: ${data}`, status: res.status, request: res.request };
  }
  return { ok: true, data, request: res.request };
}
