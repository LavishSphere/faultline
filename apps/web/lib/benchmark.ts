/**
 * REVEAL + scorecard client (issue #50): `POST /api/replay/{prediction_id}/reveal` and `GET /api/benchmark`.
 *
 * Contracts: issue #44 (routes, not built yet) and the Pydantic models in PR #29's `services/api/core/evaluator.py`
 * (`Scorecard`, `Comparison`, `ForecasterSummary`, `EventScore`, `ScoreExclusion`, `IgnoredPrediction`,
 * `RevealedOutcome`, `SealedOutcome`) and `services/api/models.py` (`Prediction`). Field names here are copied from
 * those models. Until #44 lands, both routes 404 with FastAPI's default body and the UI shows
 * NOT AVAILABLE "route pending (#44)".
 *
 * Nothing here computes a score, a mean, an interval or a verdict. The shape checks only confirm that the fields the
 * UI renders are present and typed; a body that fails them is `malformed` → NOT AVAILABLE, never patched up.
 * Keys outside the checked set are ignored (never rendered).
 *
 * Kept out of lib/api.ts (issue #50 scope) because reveal needs 404/409 kinds that the shared helper does not have.
 */

import { API_BASE } from "./api";

export const BENCHMARK_PATH = "/api/benchmark";
export const revealPath = (predictionId: string) => `/api/replay/${encodeURIComponent(predictionId)}/reveal`;

// --- wire types (mirror the Pydantic models) -------------------------------------------------------------------

/** models.ForecastVariant. Only the first two can be scored (`build_scorecard` refuses `hosted_comparator`). */
export type ForecastVariant = "agent_only" | "agent_plus_market" | "hosted_comparator";
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

/** Per-prediction scores, computed server-side by evaluator.brier / log_loss / correct_at_half. */
export interface PredictionScores {
  brier: number;
  log_loss: number;
  accuracy_at_0_5: number;
}

/**
 * POST /api/replay/{prediction_id}/reveal response. ASSUMED shape (issue #44 says only "the outcome + per-prediction
 * scores"): the fields of evaluator.RevealedOutcome plus `scores`. Listed as a contract question on the PR.
 */
export interface RevealResponse {
  prediction: Prediction;
  y: 0 | 1;
  sealed: SealedOutcome;
  revealed_at: string;
  persisted_at: string;
  persist_seq?: number;
  reveal_seq?: number;
  event_first_revealed_at?: string;
  event_first_reveal_seq?: number;
  /** RevealedOutcome.persisted_before_outcome_revealed (computed by the API from audit_log order). */
  persisted_before_outcome_revealed: boolean;
  scores: PredictionScores;
}

/** evaluator.ExclusionReason. */
export type ExclusionReason =
  | "no_persisted_prediction"
  | "persisted_after_outcome_revealed"
  | "multiple_predictions"
  | "contamination_likely"
  | "market_not_available"
  | "sealed_outcome_not_available";

/** Plain-language meaning of each reason (docs/EVALUATION_PROTOCOL.md §6 on PR #29). Text only, no data. */
export const EXCLUSION_REASON_TEXT: Record<ExclusionReason, string> = {
  no_persisted_prediction: "No forecast was persisted for this snapshot.",
  persisted_after_outcome_revealed: "Every forecast for this snapshot was saved after the event's outcome was first revealed.",
  multiple_predictions: "More than one forecast was saved before reveal; none is chosen.",
  contamination_likely: "The model probably saw this event in pretraining (contamination_flag = likely).",
  market_not_available: "No market quote within 24 h before the cutoff, so there is no market baseline.",
  sealed_outcome_not_available: "No sealed outcome file exists for this event.",
};

export interface ScoreExclusion {
  event_id: string;
  as_of: string;
  reason: ExclusionReason | string;
  prediction_ids: string[];
}

export interface IgnoredPrediction {
  prediction_id: string;
  event_id: string;
  as_of: string;
  reason: "persisted_after_outcome_revealed" | string;
}

export interface EventScore {
  event_id: string;
  n_snapshots: number;
  y: number;
  prediction_ids: string[];
  /** Keyed by forecaster ("naive", "market", agent variant). */
  brier: Record<string, number>;
  log_loss: Record<string, number>;
  accuracy_at_0_5: Record<string, number>;
}

export interface ForecasterSummary {
  mean_brier: number;
  mean_log_loss: number;
  accuracy_at_0_5: number;
}

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

/** evaluator.Scorecard. `label`, `verdict` and `caveat` are display strings set by the API (MATH_MODEL §6). */
export interface Scorecard {
  label: string;
  verdict: string;
  caveat: string | null;
  /** null when no event could be scored. */
  provenance: "REAL_HISTORICAL" | "SYNTHETIC" | null;
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
}

/**
 * GET /api/benchmark body. ASSUMED: either one `Scorecard` (as `build_scorecard` returns), or an envelope
 * `{status?, items: Scorecard[], notes?}` like the other routes when the API serves several (one per variant or per
 * dataset). Synthetic and real are never pooled server-side; each card is rendered on its own.
 */
export interface BenchmarkData {
  scorecards: Scorecard[];
  status: string | null;
  notes: string[];
}

// --- failures --------------------------------------------------------------------------------------------------

/**
 * `route_pending`: the API answered 404 without a FAULTLINE error code (FastAPI's default `{detail}`), i.e. this build
 * does not serve the route (#44). `not_revealable`: 409 NOT_REVEALABLE. `outcome_not_available`: 404 with code
 * NOT_FOUND (no sealed outcome for the event). `validation`: 422. `http`: any other non-2xx (message verbatim).
 * `malformed`: a 2xx body that does not match the contract.
 */
export type BenchmarkErrorKind =
  | "network"
  | "timeout"
  | "aborted"
  | "route_pending"
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
const isStrArray = (v: unknown): v is string[] => Array.isArray(v) && v.every(isStr);
const isNumRecord = (v: unknown): v is Record<string, number> => isObj(v) && Object.values(v).every(isNum);

function checkPrediction(p: unknown, at: string): string | null {
  if (!isObj(p)) return `${at} missing`;
  for (const k of ["prediction_id", "event_id", "as_of", "agent_model", "variant", "decision", "rationale"]) {
    if (!isStr(p[k])) return `${at}.${k} missing`;
  }
  for (const k of ["prompt_sha256", "snapshot_sha256", "recorded_at"]) {
    if (!isStr(p[k])) return `${at}.${k} missing`;
  }
  if (!isNum(p.p_yes) || p.p_yes < 0 || p.p_yes > 1) return `${at}.p_yes is not a probability`;
  if (!isNum(p.temperature)) return `${at}.temperature missing`;
  if (!(p.seed === null || p.seed === undefined || isInt(p.seed))) return `${at}.seed malformed`;
  if (!isStrOrNull(p.model_digest ?? null)) return `${at}.model_digest malformed`;
  if (!isStrArray(p.evidence_ids)) return `${at}.evidence_ids malformed`;
  if (!isStr(p.provenance) || !PROVENANCE_VALUES.includes(p.provenance)) return `${at}.provenance is not a known value`;
  return null;
}

function checkSealed(s: unknown, at: string): string | null {
  if (!isObj(s)) return `${at} missing`;
  if (!isStr(s.event_id)) return `${at}.event_id missing`;
  if (s.outcome !== "YES" && s.outcome !== "NO") return `${at}.outcome is not YES or NO`;
  if (!isStrOrNull(s.resolved_at ?? null)) return `${at}.resolved_at malformed`;
  if (!isStr(s.source_url)) return `${at}.source_url missing`;
  if (!isStrOrNull(s.notes ?? null)) return `${at}.notes malformed`;
  if (s.provenance !== "REAL_HISTORICAL" && s.provenance !== "SYNTHETIC") return `${at}.provenance is not REAL_HISTORICAL or SYNTHETIC`;
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
  if (!isStr(body.revealed_at) || !isStr(body.persisted_at)) return "revealed_at / persisted_at missing";
  if (typeof body.persisted_before_outcome_revealed !== "boolean") return "persisted_before_outcome_revealed missing";
  const s = body.scores;
  if (!isObj(s) || !isNum(s.brier) || !isNum(s.log_loss) || !isNum(s.accuracy_at_0_5)) return "scores missing";
  return null;
}

function checkScorecard(c: unknown, at: string): string | null {
  if (!isObj(c)) return `${at} is not an object`;
  if (!isStr(c.label) || !c.label.trim()) return `${at}.label missing`;
  if (!isStr(c.verdict) || !c.verdict.trim()) return `${at}.verdict missing`;
  if (!isStrOrNull(c.caveat ?? null)) return `${at}.caveat malformed`;
  if (!(c.provenance === null || c.provenance === "REAL_HISTORICAL" || c.provenance === "SYNTHETIC")) {
    return `${at}.provenance is not REAL_HISTORICAL, SYNTHETIC or null`;
  }
  if (!isStr(c.agent_variant)) return `${at}.agent_variant missing`;
  if (!isStrArray(c.forecasters) || c.forecasters.length === 0) return `${at}.forecasters missing`;
  if (!isStr(c.market_label)) return `${at}.market_label missing`;
  if (!isInt(c.n_events) || c.n_events < 0) return `${at}.n_events malformed`;
  if (!isInt(c.n_excluded) || c.n_excluded < 0) return `${at}.n_excluded malformed`;
  if (!isObj(c.exclusions_by_reason) || !Object.values(c.exclusions_by_reason).every(isInt)) {
    return `${at}.exclusions_by_reason malformed`;
  }
  if (!Array.isArray(c.exclusions)) return `${at}.exclusions missing`;
  for (let i = 0; i < c.exclusions.length; i++) {
    const x = c.exclusions[i];
    if (!isObj(x) || !isStr(x.event_id) || !isStr(x.as_of) || !isStr(x.reason) || !isStrArray(x.prediction_ids ?? [])) {
      return `${at}.exclusions[${i}] malformed`;
    }
  }
  if (!Array.isArray(c.ignored_predictions)) return `${at}.ignored_predictions missing`;
  for (let i = 0; i < c.ignored_predictions.length; i++) {
    const x = c.ignored_predictions[i];
    if (!isObj(x) || !isStr(x.prediction_id) || !isStr(x.event_id) || !isStr(x.as_of) || !isStr(x.reason)) {
      return `${at}.ignored_predictions[${i}] malformed`;
    }
  }
  if (!Array.isArray(c.per_event)) return `${at}.per_event missing`;
  if (c.per_event.length !== c.n_events) return `${at}.per_event length differs from n_events`;
  for (let i = 0; i < c.per_event.length; i++) {
    const e = c.per_event[i];
    if (!isObj(e) || !isStr(e.event_id) || !isInt(e.n_snapshots) || (e.y !== 0 && e.y !== 1)) {
      return `${at}.per_event[${i}] malformed`;
    }
    if (!isStrArray(e.prediction_ids)) return `${at}.per_event[${i}].prediction_ids malformed`;
    if (!isNumRecord(e.brier) || !isNumRecord(e.log_loss) || !isNumRecord(e.accuracy_at_0_5)) {
      return `${at}.per_event[${i}] scores malformed`;
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
    if (!isStr(k.agent_variant)) return `${at}.comparison.agent_variant missing`;
  }
  return null;
}

/** Accepts one Scorecard or `{items: Scorecard[]}`; returns the parsed data or a problem string. */
export function readBenchmark(body: unknown): BenchmarkData | string {
  if (!isObj(body)) return "body is not an object";
  if ("label" in body && "verdict" in body) {
    const problem = checkScorecard(body, "scorecard");
    return problem ?? { scorecards: [body as unknown as Scorecard], status: null, notes: [] };
  }
  if (!Array.isArray(body.items)) return "body is neither a Scorecard nor {items: Scorecard[]}";
  for (let i = 0; i < body.items.length; i++) {
    const problem = checkScorecard(body.items[i], `items[${i}]`);
    if (problem) return problem;
  }
  const notes = Array.isArray(body.notes) ? body.notes.filter(isStr) : [];
  return { scorecards: body.items as Scorecard[], status: isStr(body.status) ? body.status : null, notes };
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
): Promise<{ ok: true; status: number; body: unknown; parsed: boolean; request: string } | BenchmarkFailure> {
  const url = `${API_BASE}${path}`;
  const label = `${method} ${url}`;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(new DOMException("timeout", "TimeoutError")), timeoutMs);
  const onAbort = () => controller.abort(signal?.reason);
  if (signal?.aborted) onAbort();
  signal?.addEventListener("abort", onAbort, { once: true });
  try {
    const res = await fetch(url, { method, headers: { Accept: "application/json" }, cache: "no-store", signal: controller.signal });
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
      if (res.status === 409) kind = "not_revealable";
      else if (res.status === 404) kind = code === undefined ? "route_pending" : "outcome_not_available";
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
 * POST /api/replay/{prediction_id}/reveal. This is a logged, state-changing call: the server records the reveal, and
 * any forecast for the same event persisted afterwards is excluded from scoring. Call it only on an explicit click.
 * Never throws.
 */
export async function revealPrediction(predictionId: string, signal?: AbortSignal): Promise<Result<RevealResponse>> {
  const res = await request("POST", revealPath(predictionId), 10_000, signal);
  if (!res.ok) return res;
  if (!res.parsed) return { ok: false, kind: "malformed", message: "response was not JSON", status: res.status, request: res.request };
  const problem = checkRevealResponse(res.body, predictionId);
  if (problem) {
    return { ok: false, kind: "malformed", message: `malformed reveal payload: ${problem}`, status: res.status, request: res.request };
  }
  return { ok: true, data: res.body as RevealResponse, request: res.request };
}

/**
 * GET /api/benchmark?agent_variant=… . `build_scorecard` reveals (and logs) every scorable persisted prediction, so
 * this is also called only on an explicit click. The query parameter name is ASSUMED (it mirrors
 * `build_scorecard(agent_variant=…)`); the UI shows the variant the API reports, not the one requested.
 */
export async function getBenchmark(variant: ScorableVariant, signal?: AbortSignal): Promise<Result<BenchmarkData>> {
  const res = await request("GET", `${BENCHMARK_PATH}?agent_variant=${encodeURIComponent(variant)}`, 20_000, signal);
  if (!res.ok) return res;
  if (!res.parsed) return { ok: false, kind: "malformed", message: "response was not JSON", status: res.status, request: res.request };
  const data = readBenchmark(res.body);
  if (typeof data === "string") {
    return { ok: false, kind: "malformed", message: `malformed benchmark payload: ${data}`, status: res.status, request: res.request };
  }
  return { ok: true, data, request: res.request };
}
