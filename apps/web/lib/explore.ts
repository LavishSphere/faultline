/**
 * LIVE EXPLORE clients (services/api/routes/explore.py): GET /api/explore/search (issue #60, Tavily web search) and
 * POST /api/explore/analyze (issue #61, Tavily results -> local model -> cited evidence + MODEL-SUGGESTED inputs).
 *
 * Live Explore is current web content, explicitly NOT point-in-time. It is shown next to the Blind Replay and is
 * never fed into it (SPEC §3.3, §5; the API enforces that with tests/test_explore_separation.py).
 *
 * Types mirror the Pydantic models `ExploreSearchResponse` / `ExploreSearchItem` field for field. The shape check is
 * strict: an unexpected key or a wrong label makes the response `malformed`, rendered NOT AVAILABLE, never patched up.
 *
 * The browser never sends an admin token: in public mode the API answers 403 ADMIN_TOKEN_REQUIRED and the panel says
 * "admin only on the public demo".
 */

import { API_BASE, type ScenarioShock } from "./api";

export const EXPLORE_SEARCH_PATH = "/api/explore/search";
export const LIVE_EXPLORE_LABEL = "LIVE EXPLORE: current, not point-in-time";
export const TAVILY_ATTRIBUTION = "Search powered by Tavily";
/** routes/explore.py MAX_QUERY_CHARS / MAX_RESULTS / DEFAULT_MAX_RESULTS (input limits only; the API re-validates). */
export const EXPLORE_MAX_QUERY_CHARS = 200;
export const EXPLORE_MAX_RESULTS = 10;
export const EXPLORE_DEFAULT_MAX_RESULTS = 5;

/** routes/explore.py `ExploreSearchItem`. */
export interface ExploreSearchItem {
  title: string;
  url: string;
  snippet: string;
  score: number | null;
  /** Tavily's estimate of publish / last-update time (UTC ISO); null when absent or not an instant. */
  published_at: string | null;
  /** `published_date` exactly as Tavily sent it. */
  published_at_raw: string | null;
  /** When the API fetched this result (UTC ISO). */
  retrieved_at: string;
}

/** routes/explore.py `ExploreSearchResponse`. */
export interface ExploreSearchResponse {
  mode: "live_explore";
  label: typeof LIVE_EXPLORE_LABEL;
  provider: "tavily";
  attribution: typeof TAVILY_ATTRIBUTION;
  query: string;
  retrieved_at: string;
  cached: boolean;
  items: ExploreSearchItem[];
  notes: string[];
}

/**
 * `unavailable`: 503 LIVE_EXPLORE_UNAVAILABLE (no key on the server, key rejected, or quota reached).
 * `admin_only`: 403 (public mode). `rate_limited`: 429. `timeout`: 504 from the API or no answer in time.
 * `upstream`: 502. `validation`: 422. `not_found`: this API build has no Live Explore route.
 * `network`: API unreachable. `http`: any other status. `malformed`: 2xx outside the contract.
 */
export type ExploreErrorKind =
  | "unavailable"
  | "admin_only"
  | "rate_limited"
  | "timeout"
  | "upstream"
  | "validation"
  | "not_found"
  | "network"
  | "aborted"
  | "http"
  | "malformed";

export interface ExploreFailure {
  ok: false;
  kind: ExploreErrorKind;
  message: string;
  status?: number;
  code?: string;
  /** Seconds, from the Retry-After header of a 429. */
  retryAfterS?: number;
  /** Why a 503 LIVE_EXPLORE_UNAVAILABLE happened (`errors[0].type` from the API); absent when not sent. */
  reason?: UnavailableReason;
}

/** routes/explore.py `_unavailable`: no key on the server, key rejected by Tavily, or Tavily quota reached. */
export const UNAVAILABLE_REASONS = ["not_configured", "auth_rejected", "quota_exceeded"] as const;
export type UnavailableReason = (typeof UNAVAILABLE_REASONS)[number];

export type ExploreResult = { ok: true; data: ExploreSearchResponse } | ExploreFailure;

const isStr = (v: unknown): v is string => typeof v === "string";
const isStrOrNull = (v: unknown): v is string | null => v === null || typeof v === "string";
const isObj = (v: unknown): v is Record<string, unknown> => !!v && typeof v === "object" && !Array.isArray(v);
const isHttpUrl = (v: unknown): v is string => {
  if (!isStr(v)) return false;
  try {
    const u = new URL(v);
    return u.protocol === "https:" || u.protocol === "http:";
  } catch {
    return false;
  }
};

const TOP_KEYS = new Set([
  "mode", "label", "provider", "attribution", "query", "retrieved_at", "cached", "items", "notes",
]);
const ITEM_KEYS = new Set(["title", "url", "snippet", "score", "published_at", "published_at_raw", "retrieved_at"]);

function extraKey(obj: Record<string, unknown>, allowed: Set<string>, at: string): string | null {
  const extra = Object.keys(obj).find((k) => !allowed.has(k));
  return extra === undefined ? null : `${at} has non-contract key "${extra}"`;
}

/** Returns a problem description, or null when the body matches the #60 contract. */
export function checkExploreResponse(body: unknown): string | null {
  if (!isObj(body)) return "body is not an object";
  const extra = extraKey(body, TOP_KEYS, "body");
  if (extra) return extra;
  if (body.mode !== "live_explore") return "mode is not live_explore";
  if (body.label !== LIVE_EXPLORE_LABEL) return "label is not the LIVE EXPLORE label";
  if (body.provider !== "tavily" || body.attribution !== TAVILY_ATTRIBUTION) return "provider attribution missing";
  if (!isStr(body.query) || !isStr(body.retrieved_at)) return "query or retrieved_at missing";
  if (typeof body.cached !== "boolean") return "cached malformed";
  if (!Array.isArray(body.notes) || !body.notes.every(isStr)) return "notes malformed";
  if (!Array.isArray(body.items)) return "items missing";
  for (let i = 0; i < body.items.length; i++) {
    const it: unknown = body.items[i];
    const at = `items[${i}]`;
    if (!isObj(it)) return `${at} is not an object`;
    const itemExtra = extraKey(it, ITEM_KEYS, at);
    if (itemExtra) return itemExtra;
    if (!isStr(it.title) || !isStr(it.snippet)) return `${at} text missing`;
    if (!isHttpUrl(it.url)) return `${at}.url is not an http(s) URL`;
    if (!(it.score === null || (typeof it.score === "number" && Number.isFinite(it.score)))) return `${at}.score malformed`;
    if (!isStrOrNull(it.published_at) || !isStrOrNull(it.published_at_raw)) return `${at} published date malformed`;
    if (!isStr(it.retrieved_at)) return `${at}.retrieved_at missing`;
  }
  return null;
}

function kindFor(status: number, code: string | undefined): ExploreErrorKind {
  if (code === "LIVE_EXPLORE_UNAVAILABLE" || status === 503) return "unavailable";
  if (code === "ADMIN_TOKEN_REQUIRED" || status === 403 || status === 401) return "admin_only";
  if (status === 429) return "rate_limited";
  if (status === 504) return "timeout";
  if (status === 502) return "upstream";
  if (status === 422) return "validation";
  if (status === 404) return "not_found";
  return "http";
}

function readError(body: unknown): { message: string | null; code?: string; reason?: UnavailableReason } {
  if (!isObj(body)) return { message: null };
  const code = isStr(body.code) ? body.code : undefined;
  const errors = Array.isArray(body.errors) ? body.errors.filter(isObj) : [];
  const first = errors[0]?.type;
  const reason = UNAVAILABLE_REASONS.find((r) => r === first);
  const own = isStr(body.message) ? body.message : "";
  const issues = errors
    .map((e) => (isStr(e.msg) ? e.msg : ""))
    .filter((m) => m && m !== own)
    .join("; ");
  if (own.trim()) return { message: issues ? `${own} (${issues})` : own, code, reason };
  if (isStr(body.detail) && body.detail.trim()) return { message: body.detail, code, reason };
  return { message: issues || null, code, reason };
}

/** One Live Explore request. Never throws: every failure is a typed, displayable result. */
async function fetchExplore<T>(
  url: string,
  init: { method: "GET" | "POST"; body?: unknown },
  check: (body: unknown) => string | null,
  signal: AbortSignal | undefined,
  timeoutMs: number,
): Promise<{ ok: true; data: T } | ExploreFailure> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(new DOMException("timeout", "TimeoutError")), timeoutMs);
  const onAbort = () => controller.abort(signal?.reason);
  if (signal?.aborted) onAbort();
  signal?.addEventListener("abort", onAbort, { once: true });
  try {
    const res = await fetch(url, {
      method: init.method,
      headers:
        init.body === undefined
          ? { Accept: "application/json" }
          : { Accept: "application/json", "Content-Type": "application/json" },
      body: init.body === undefined ? undefined : JSON.stringify(init.body),
      cache: "no-store",
      signal: controller.signal,
    });
    let body: unknown = null;
    let parsed = true;
    try {
      body = await res.json();
    } catch {
      parsed = false;
    }
    if (!res.ok) {
      const { message, code, reason } = readError(body);
      const retry = Number.parseInt(res.headers.get("retry-after") ?? "", 10);
      return {
        ok: false,
        kind: kindFor(res.status, code),
        status: res.status,
        code,
        reason,
        message: message ?? `HTTP ${res.status}`,
        retryAfterS: Number.isFinite(retry) && retry > 0 ? retry : undefined,
      };
    }
    if (!parsed) return { ok: false, kind: "malformed", status: res.status, message: "response was not JSON" };
    const problem = check(body);
    if (problem) return { ok: false, kind: "malformed", status: res.status, message: `malformed response: ${problem}` };
    return { ok: true, data: body as T };
  } catch (err) {
    if (controller.signal.aborted) {
      const reason: unknown = controller.signal.reason;
      const timedOut = reason instanceof DOMException && reason.name === "TimeoutError";
      return timedOut
        ? { ok: false, kind: "timeout", message: `no answer within ${Math.round(timeoutMs / 1000)} s` }
        : { ok: false, kind: "aborted", message: "aborted" };
    }
    return { ok: false, kind: "network", message: err instanceof Error ? err.message : "request failed" };
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", onAbort);
  }
}

/** GET /api/explore/search. Never throws: every failure is a typed, displayable result. */
export async function searchLiveExplore(
  q: string,
  maxResults: number = EXPLORE_DEFAULT_MAX_RESULTS,
  signal?: AbortSignal,
  timeoutMs = 20000,
): Promise<ExploreResult> {
  const url = `${API_BASE}${EXPLORE_SEARCH_PATH}?q=${encodeURIComponent(q)}&max_results=${encodeURIComponent(String(maxResults))}`;
  return fetchExplore<ExploreSearchResponse>(url, { method: "GET" }, checkExploreResponse, signal, timeoutMs);
}

// ---------------------------------------------------------------------------------------------------------------
// POST /api/explore/analyze (issue #61): Tavily results -> local model -> cited evidence + MODEL-SUGGESTED inputs.
// Types mirror routes/explore.py `ExploreAnalysis` and agents/explore_analyst.py `Suggestion` field for field.
// ---------------------------------------------------------------------------------------------------------------

export const EXPLORE_ANALYZE_PATH = "/api/explore/analyze";
export const SUGGESTION_LABEL = "MODEL-SUGGESTED, HUMAN TO CONFIRM";
/** agents/explore_analyst.py DEFAULTS_LABEL: the model gave no usable number, so every value is a guidance default. */
export const DEFAULTS_LABEL = "GUIDANCE DEFAULTS, HUMAN TO CONFIRM";
export const DEFAULTS_NOTE = "The model gave no usable numbers; these are guidance defaults.";
/** routes/explore.py MAX_DECISION_CHARS (input limit only; the API re-validates). */
export const EXPLORE_MAX_DECISION_CHARS = 300;
/** The local model may take a while on a laptop; the API's own Ollama timeout is 180 s plus one repair turn. */
export const EXPLORE_ANALYZE_TIMEOUT_MS = 400_000;

export const SHOCK_BLOCKS = ["rate", "demand", "supplier"] as const;
export type ShockBlock = (typeof SHOCK_BLOCKS)[number];

export const ANALYSIS_STATUSES = [
  "ok",
  "no_sources",
  "no_cited_evidence",
  "model_unavailable",
  "model_output_invalid",
  "model_input_refused",
] as const;
export type AnalysisStatus = (typeof ANALYSIS_STATUSES)[number];

export const VALUE_SOURCES = ["model", "model_clamped", "guidance_default"] as const;
export type ValueSource = (typeof VALUE_SOURCES)[number];

/** routes/explore.py `ExploreSource`: one Tavily result given to the model. */
export interface ExploreSource extends ExploreSearchItem {
  source_id: string;
}

/** routes/explore.py `ExploreEvidenceCard`. `claim` is model-written; everything else is the Tavily result. */
export interface ExploreEvidenceCard {
  claim: string;
  source_id: string;
  source_url: string;
  source_title: string;
  snippet: string;
  published_at: string | null;
  published_at_raw: string | null;
  retrieved_at: string;
}

export interface ExploreRejectedClaim {
  claim: string;
  source_url: string | null;
  reason: string;
  message: string;
}

/** agents/explore_analyst.py `SuggestedParameter`. `value` is an INPUT, already inside [min, max]. */
export interface SuggestedParameter {
  block: ShockBlock;
  param: string;
  unit: string;
  integer: boolean;
  value: number;
  min: number;
  default: number;
  max: number;
  worse_when: "higher" | "lower" | null;
  source: ValueSource;
  model_value: number | null;
  rationale: string | null;
  note: string | null;
}

export interface ExploreSuggestion {
  /** MODEL-SUGGESTED only when at least one value is the model's (values_from_model > 0). */
  label: typeof SUGGESTION_LABEL | typeof DEFAULTS_LABEL;
  /** Parameters whose value is the model's number (source model or model_clamped). */
  values_from_model: number;
  category_id: string;
  category_name: string;
  parameters: SuggestedParameter[];
  shock: ScenarioShock;
  notes: string[];
}

export interface ExploreModelRun {
  agent_model: string;
  model_tag: string;
  model_digest: string | null;
  temperature: number;
  seed: number | null;
  attempts: number;
  prompt_sha256: string;
  sources_sha256: string;
  raw_output_sha256: string;
  latency_ms: number;
}

export interface ExploreGuidanceParam {
  block: ShockBlock;
  param: string;
  unit: string;
  integer: boolean;
  min: number;
  default: number;
  max: number;
  worse_when: "higher" | "lower" | null;
}

export interface ExploreGuidanceCategory {
  id: string;
  name: string;
  news_trigger: string;
  timing_guidance: string;
  rationale: string;
  basis: string;
  params: ExploreGuidanceParam[];
}

export interface ExploreGuidance {
  provenance: "ILLUSTRATIVE";
  label: string;
  horizon_weeks: number;
  categories: ExploreGuidanceCategory[];
}

/** routes/explore.py `ExploreAnalysis`. */
export interface ExploreAnalysis {
  mode: "live_explore";
  label: typeof LIVE_EXPLORE_LABEL;
  provider: "tavily";
  attribution: typeof TAVILY_ATTRIBUTION;
  decision_text: string;
  retrieved_at: string;
  cached: boolean;
  status: AnalysisStatus;
  status_message: string | null;
  sources: ExploreSource[];
  evidence: ExploreEvidenceCard[];
  rejected_claims: ExploreRejectedClaim[];
  suggestion: ExploreSuggestion | null;
  model: ExploreModelRun | null;
  guidance: ExploreGuidance;
  notes: string[];
}

export type AnalyzeResult = { ok: true; data: ExploreAnalysis } | ExploreFailure;

const ANALYSIS_KEYS = new Set([
  "mode", "label", "provider", "attribution", "decision_text", "retrieved_at", "cached", "status",
  "status_message", "sources", "evidence", "rejected_claims", "suggestion", "model", "guidance", "notes",
]);
const isFiniteNum = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);
const isBlock = (v: unknown): v is ShockBlock => SHOCK_BLOCKS.includes(v as ShockBlock);

function checkRange(p: Record<string, unknown>, at: string): string | null {
  if (!isBlock(p.block) || !isStr(p.param) || !isStr(p.unit) || typeof p.integer !== "boolean") return `${at} identity malformed`;
  if (!isFiniteNum(p.min) || !isFiniteNum(p.default) || !isFiniteNum(p.max)) return `${at} range malformed`;
  if (!(p.min <= p.default && p.default <= p.max)) return `${at} range out of order`;
  return null;
}

/**
 * Returns a problem description, or null when the body matches the #61 contract. Besides shape, it re-checks the
 * two honesty rules the UI relies on: every evidence card cites a URL listed in `sources`, and every suggested
 * value lies inside its stated range. A body that breaks either is rendered NOT AVAILABLE, never shown.
 */
export function checkAnalysisResponse(body: unknown): string | null {
  if (!isObj(body)) return "body is not an object";
  const extra = extraKey(body, ANALYSIS_KEYS, "body");
  if (extra) return extra;
  if (body.mode !== "live_explore" || body.label !== LIVE_EXPLORE_LABEL) return "not labeled LIVE EXPLORE";
  if (body.provider !== "tavily" || body.attribution !== TAVILY_ATTRIBUTION) return "provider attribution missing";
  if (!isStr(body.decision_text) || !isStr(body.retrieved_at) || typeof body.cached !== "boolean") return "header malformed";
  if (!ANALYSIS_STATUSES.includes(body.status as AnalysisStatus)) return "status unknown";
  if (!isStrOrNull(body.status_message)) return "status_message malformed";
  if (!Array.isArray(body.notes) || !body.notes.every(isStr)) return "notes malformed";

  if (!Array.isArray(body.sources)) return "sources missing";
  const urls = new Set<string>();
  for (let i = 0; i < body.sources.length; i++) {
    const s: unknown = body.sources[i];
    if (!isObj(s) || !isStr(s.source_id) || !isHttpUrl(s.url) || !isStr(s.title) || !isStr(s.snippet)) {
      return `sources[${i}] malformed`;
    }
    if (!isStr(s.retrieved_at)) return `sources[${i}].retrieved_at missing`;
    urls.add(s.url);
  }
  if (!Array.isArray(body.evidence)) return "evidence missing";
  for (let i = 0; i < body.evidence.length; i++) {
    const c: unknown = body.evidence[i];
    if (!isObj(c) || !isStr(c.claim) || !isStr(c.source_url) || !isStr(c.snippet) || !isStr(c.retrieved_at)) {
      return `evidence[${i}] malformed`;
    }
    if (!urls.has(c.source_url)) return `evidence[${i}] cites a url that is not among the Tavily sources`;
  }
  if (!Array.isArray(body.rejected_claims) || !body.rejected_claims.every((r) => isObj(r) && isStr(r.reason))) {
    return "rejected_claims malformed";
  }

  const g = body.guidance;
  if (!isObj(g) || g.provenance !== "ILLUSTRATIVE" || !isFiniteNum(g.horizon_weeks) || !Array.isArray(g.categories)) {
    return "guidance malformed";
  }
  for (const c of g.categories as unknown[]) {
    if (!isObj(c) || !isStr(c.id) || !isStr(c.name) || !Array.isArray(c.params)) return "guidance category malformed";
    for (const p of c.params as unknown[]) {
      const problem = isObj(p) ? checkRange(p, `guidance ${c.id}`) : "guidance param malformed";
      if (problem) return problem;
    }
  }

  const s = body.suggestion;
  if (s !== null) {
    if (!isObj(s) || !isStr(s.category_id) || !Array.isArray(s.parameters) || !isFiniteNum(s.values_from_model)) {
      return "suggestion malformed";
    }
    if (!isObj(s.shock)) return "suggestion.shock missing";
    // The label must tell the truth about where the numbers came from (audit of #121, B1).
    const fromModel = (s.parameters as unknown[]).filter(
      (p) => isObj(p) && (p.source === "model" || p.source === "model_clamped"),
    ).length;
    if (fromModel !== s.values_from_model) return "suggestion values_from_model does not match its parameters";
    if (s.label !== (fromModel > 0 ? SUGGESTION_LABEL : DEFAULTS_LABEL)) {
      return "suggestion label does not match where its numbers came from";
    }
    for (const p of s.parameters as unknown[]) {
      if (!isObj(p)) return "suggestion parameter malformed";
      const problem = checkRange(p, `suggestion ${String(p.block)}.${String(p.param)}`);
      if (problem) return problem;
      if (!isFiniteNum(p.value) || p.value < (p.min as number) || p.value > (p.max as number)) {
        return `suggestion ${String(p.block)}.${String(p.param)} is outside its stated range`;
      }
      if (!VALUE_SOURCES.includes(p.source as ValueSource)) return "suggestion parameter source unknown";
    }
  }
  if (body.status === "ok" && body.evidence.length === 0) return "status ok without cited evidence";
  return null;
}

/** POST /api/explore/analyze. Never throws. Spends Tavily credits and local-model time: call it only on submit. */
export async function analyzeLiveExplore(
  decisionText: string,
  signal?: AbortSignal,
  timeoutMs = EXPLORE_ANALYZE_TIMEOUT_MS,
): Promise<AnalyzeResult> {
  return fetchExplore<ExploreAnalysis>(
    `${API_BASE}${EXPLORE_ANALYZE_PATH}`,
    { method: "POST", body: { decision_text: decisionText } },
    checkAnalysisResponse,
    signal,
    timeoutMs,
  );
}

/** Values the human is editing, keyed by block then parameter, in the engine's own units (fractions, Δr). */
export type ShockValues = Partial<Record<ShockBlock, Record<string, number>>>;

/**
 * Guidance `mapping_to_scenario_shock` (agents/explore_analyst.py `shock_from_values`), translated only: the
 * browser builds the ScenarioShock INPUT, and POST /api/simulate validates it and computes every figure.
 */
export function shockFromValues(name: string, values: ShockValues, horizon: number): ScenarioShock {
  const shock: ScenarioShock = { name };
  const r = values.rate;
  if (r) shock.rate = { delta_rate: r.delta_rate!, start_week: r.start_week! };
  const d = values.demand;
  if (d) {
    shock.demand = {
      delta: d.delta!,
      start_week: d.start_week!,
      end_week: d.start_week! + d.duration_weeks! - 1,
      recovery_weeks: d.recovery_weeks!,
    };
  }
  const s = values.supplier;
  if (s) {
    const first = s.start_week!;
    const last = first + s.duration_weeks! - 1;
    shock.supplier = {
      availability: Array.from({ length: horizon }, (_, i) =>
        i + 1 >= first && i + 1 <= last ? s.availability_during_outage! : 1.0,
      ),
      dependent_share: s.dependent_share!,
    };
  }
  return shock;
}
