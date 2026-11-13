/**
 * Blind Replay client: GET /api/cases (issue #25, merged), POST /api/replay/run (issue #44, contract only),
 * and GET /api/cases/{id}/evidence?as_of= (SPEC §8; no route and no issue yet).
 *
 * Types mirror services/api/models.py field for field (`ReplayCasePublic`, `Prediction`, `EvidenceItem`,
 * `MarketQuoteRef`) and routes/cases.py `CasesResponse`; keep them in sync.
 *
 * Rules (AGENTS.md §4, SPEC §5):
 * - Nothing here computes a forecast, a probability or a verdict. Responses are shape-checked and rendered as-is.
 * - A pre-reveal response that carries ANY outcome-like key (models.OUTCOME_FIELD_PATTERN) is refused as
 *   `leak`, never displayed. The only exception mirrors the server's: `outcome: "YES"` directly on a market quote.
 * - Evidence or a quote stamped after the case cutoff is refused as `malformed`; the browser never filters it out
 *   and shows the rest, because the gate (core/temporal_gate.py) is the only thing allowed to decide admissibility.
 * - A route this API build does not serve is `route_missing` and renders NOT AVAILABLE naming the pending issue.
 */

import { API_BASE } from "./api";

// --------------------------------------------------------------------------------------------- wire types

export type WireProvenance = "REAL_HISTORICAL" | "SYNTHETIC" | "RECORDED_RUN" | "SIMULATED" | "ILLUSTRATIVE";
const WIRE_PROVENANCES: readonly WireProvenance[] = [
  "REAL_HISTORICAL",
  "SYNTHETIC",
  "RECORDED_RUN",
  "SIMULATED",
  "ILLUSTRATIVE",
];

export type ContaminationFlag = "unknown" | "likely" | "unlikely";
export type ForecastVariant = "agent_only" | "agent_plus_market";
export type Decision = "act" | "wait" | "hedge";

/** The two variants `PredictionStore.save` accepts (PR #29). `hosted_comparator` is never run from this screen. */
export const RUN_VARIANTS: readonly { id: ForecastVariant; label: string; detail: string }[] = [
  { id: "agent_only", label: "Agent only", detail: "Point-in-time evidence; no market price in the prompt." },
  {
    id: "agent_plus_market",
    label: "Agent + market",
    detail: "Same evidence plus the as-of market quote, when the case has one.",
  },
];

/** models.py `ReplayCasePublic`. */
export interface ReplayCasePublic {
  event_id: string;
  title: string;
  /** Knowledge cutoff (ISO 8601, timezone-aware). */
  as_of: string;
  horizon_days: number;
  /** The settlement RULE text (never the result). */
  question_criteria: string;
  evidence_ids: string[];
  market_quote_id: string | null;
  snapshot_hash: string;
  synthetic: boolean;
  contamination_flag: ContaminationFlag;
  provenance: WireProvenance;
}

/** routes/cases.py `CasesResponse`. */
export interface CasesResponse {
  status: "AVAILABLE" | "NOT AVAILABLE";
  items: ReplayCasePublic[];
  notes: string[];
}

/** models.py `Prediction`, as #44's run response is expected to carry it (persisted before any reveal). */
export interface Prediction {
  prediction_id: string;
  event_id: string;
  as_of: string;
  agent_model: string;
  model_digest: string | null;
  variant: ForecastVariant | "hosted_comparator";
  p_yes: number;
  decision: Decision;
  rationale: string;
  evidence_ids: string[];
  prompt_sha256: string;
  snapshot_sha256: string;
  temperature: number;
  seed: number | null;
  recorded_at: string;
  provenance: WireProvenance;
}

/** agents/skeptic.py `SkepticProblem` (PR #40). */
export interface SkepticProblem {
  code: string;
  severity: string;
  message: string;
  evidence_id?: string | null;
  sentence?: string | null;
}

/**
 * POST /api/replay/run, normalized. #44 does not fix the envelope, so both a bare `Prediction` and
 * `{prediction, skeptic?: {problems}}` are accepted. Anything else is malformed.
 */
export interface ReplayRun {
  prediction: Prediction;
  /** null when the response did not include a skeptic report (NOT AVAILABLE, not "no problems"). */
  skeptic: SkepticProblem[] | null;
}

/** models.py `EvidenceItem`. */
export interface EvidenceItem {
  evidence_id: string;
  event_id: string;
  title: string;
  source_url: string;
  archive_url: string | null;
  published_at: string;
  observed_at: string;
  available_at: string;
  content_sha256: string;
  content: string;
  retrospective_unverified: boolean;
  provenance: WireProvenance;
}

/** models.py `MarketQuoteRef`. `p_yes` is price-derived, never a "true probability". */
export interface MarketQuoteRef {
  quote_id: string;
  venue: "kalshi" | "polymarket";
  market_id: string;
  ts: string;
  p_yes: number;
  quote_kind: "midpoint" | "candle_close" | "last_trade";
  raw_payload_sha256: string;
  provenance: WireProvenance;
  label: string;
}

/**
 * Proposed body of GET /api/cases/{id}/evidence?as_of= (not served yet; described in the PR so the backend can
 * match it): the gate's admitted evidence plus the as-of quote(s), shaped like `CasesResponse`.
 */
export interface CaseEvidenceResponse {
  status: "AVAILABLE" | "NOT AVAILABLE";
  as_of: string;
  items: EvidenceItem[];
  market_quotes: MarketQuoteRef[];
  notes: string[];
}

// --------------------------------------------------------------------------------------------- results

/**
 * `route_missing`: this API build has no such route (FastAPI's bare 404). `not_found`: the route answered with a
 * coded 404 (e.g. unknown case). `forbidden`: 401/403 (public mode admin gate, #28). `model_unavailable`: 503
 * MODEL_UNAVAILABLE. `leak`: a pre-reveal body carried an outcome-like key and was refused. `malformed`: a 2xx body
 * that did not match the contract.
 */
export type ReplayErrorKind =
  | "network"
  | "timeout"
  | "aborted"
  | "route_missing"
  | "not_found"
  | "forbidden"
  | "validation"
  | "model_unavailable"
  | "http"
  | "malformed"
  | "leak"
  | "pending";

export interface ReplayFailure {
  ok: false;
  kind: ReplayErrorKind;
  message: string;
  status?: number;
  code?: string;
  /** "METHOD /path" actually requested (or that would be requested), shown so the presenter sees what was asked. */
  request: string;
}

export type ReplayResult<T> = { ok: true; data: T; request: string } | ReplayFailure;

// --------------------------------------------------------------------------------------------- shape checks

const isStr = (v: unknown): v is string => typeof v === "string";
const isStrArray = (v: unknown): v is string[] => Array.isArray(v) && v.every(isStr);
const isObj = (v: unknown): v is Record<string, unknown> => !!v && typeof v === "object" && !Array.isArray(v);
const isProb = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v) && v >= 0 && v <= 1;
const isInstant = (v: unknown): v is string => isStr(v) && Number.isFinite(Date.parse(v));
const isWireProvenance = (v: unknown): v is WireProvenance => WIRE_PROVENANCES.includes(v as WireProvenance);
const SHA256 = /^[0-9a-f]{64}$/;

/** Mirrors models.OUTCOME_FIELD_PATTERN. */
const OUTCOME_KEY = /outcome|resolution|resolved|settle|result|winner|final_price/i;

/**
 * JSON paths of outcome-like keys anywhere in a pre-reveal body. Mirrors routes/cases.py `outcome_key_paths`,
 * including its one exception: the market side marker `"outcome": "YES"` directly on a `market_quotes[i]` object.
 */
export function outcomeKeyPaths(body: unknown): string[] {
  const found: string[] = [];
  const walk = (node: unknown, path: string, inQuote: boolean) => {
    if (Array.isArray(node)) {
      node.forEach((v, i) => walk(v, `${path}[${i}]`, path === "market_quotes"));
    } else if (isObj(node)) {
      for (const [key, value] of Object.entries(node)) {
        const here = path ? `${path}.${key}` : key;
        const sideMarker = inQuote && key === "outcome" && value === "YES";
        if (OUTCOME_KEY.test(key) && !sideMarker) found.push(here);
        walk(value, here, false);
      }
    }
  };
  walk(body, "", false);
  return found;
}

const CASE_KEYS = new Set([
  "event_id", "title", "as_of", "horizon_days", "question_criteria", "evidence_ids", "market_quote_id",
  "snapshot_hash", "synthetic", "contamination_flag", "provenance",
]);

function extraKey(obj: Record<string, unknown>, allowed: Set<string>, at: string): string | null {
  const extra = Object.keys(obj).find((k) => !allowed.has(k));
  return extra === undefined ? null : `${at} has non-contract key "${extra}"`;
}

function checkCase(c: unknown, at: string): string | null {
  if (!isObj(c)) return `${at} is not an object`;
  const extra = extraKey(c, CASE_KEYS, at);
  if (extra) return extra;
  for (const k of ["event_id", "title", "question_criteria"]) if (!isStr(c[k])) return `${at}.${k} missing`;
  if (!isInstant(c.as_of)) return `${at}.as_of is not an ISO instant`;
  if (typeof c.horizon_days !== "number" || !Number.isInteger(c.horizon_days) || c.horizon_days <= 0) {
    return `${at}.horizon_days malformed`;
  }
  if (!isStrArray(c.evidence_ids)) return `${at}.evidence_ids malformed`;
  if (!(c.market_quote_id === null || c.market_quote_id === undefined || isStr(c.market_quote_id))) {
    return `${at}.market_quote_id malformed`;
  }
  if (!isStr(c.snapshot_hash) || !/^sha256:[0-9a-f]{64}$/.test(c.snapshot_hash)) return `${at}.snapshot_hash malformed`;
  if (typeof c.synthetic !== "boolean") return `${at}.synthetic malformed`;
  if (!["unknown", "likely", "unlikely"].includes(c.contamination_flag as string)) {
    return `${at}.contamination_flag malformed`;
  }
  if (!isWireProvenance(c.provenance)) return `${at}.provenance is not a known wire label`;
  return null;
}

export function checkCasesResponse(body: unknown): string | null {
  if (!isObj(body)) return "body is not an object";
  const extra = extraKey(body, new Set(["status", "items", "notes"]), "body");
  if (extra) return extra;
  if (body.status !== "AVAILABLE" && body.status !== "NOT AVAILABLE") return "status malformed";
  if (!Array.isArray(body.items)) return "items missing";
  if (!isStrArray(body.notes)) return "notes malformed";
  for (let i = 0; i < body.items.length; i++) {
    const problem = checkCase(body.items[i], `items[${i}]`);
    if (problem) return problem;
  }
  return null;
}

const PREDICTION_KEYS = new Set([
  "prediction_id", "event_id", "as_of", "agent_model", "model_digest", "variant", "p_yes", "decision", "rationale",
  "evidence_ids", "prompt_sha256", "snapshot_sha256", "temperature", "seed", "recorded_at", "provenance",
]);

function checkPrediction(p: unknown, at: string): string | null {
  if (!isObj(p)) return `${at} is not an object`;
  const extra = extraKey(p, PREDICTION_KEYS, at);
  if (extra) return extra;
  for (const k of ["prediction_id", "event_id", "agent_model", "rationale"]) if (!isStr(p[k])) return `${at}.${k} missing`;
  if (!isInstant(p.as_of) || !isInstant(p.recorded_at)) return `${at} timestamps malformed`;
  if (!isProb(p.p_yes)) return `${at}.p_yes is not a probability in [0, 1]`;
  if (!["act", "wait", "hedge"].includes(p.decision as string)) return `${at}.decision is not act/wait/hedge`;
  if (!["agent_only", "agent_plus_market", "hosted_comparator"].includes(p.variant as string)) {
    return `${at}.variant malformed`;
  }
  if (!isStrArray(p.evidence_ids)) return `${at}.evidence_ids malformed`;
  if (!isStr(p.prompt_sha256) || !SHA256.test(p.prompt_sha256)) return `${at}.prompt_sha256 malformed`;
  if (!isStr(p.snapshot_sha256) || !SHA256.test(p.snapshot_sha256)) return `${at}.snapshot_sha256 malformed`;
  if (!(p.model_digest === null || p.model_digest === undefined || isStr(p.model_digest))) {
    return `${at}.model_digest malformed`;
  }
  if (typeof p.temperature !== "number" || !Number.isFinite(p.temperature)) return `${at}.temperature malformed`;
  if (!(p.seed === null || p.seed === undefined || Number.isInteger(p.seed))) return `${at}.seed malformed`;
  if (!isWireProvenance(p.provenance)) return `${at}.provenance is not a known wire label`;
  return null;
}

function readSkeptic(v: unknown): SkepticProblem[] | null | "malformed" {
  if (v === undefined || v === null) return null;
  if (!isObj(v) || !Array.isArray(v.problems)) return "malformed";
  const out: SkepticProblem[] = [];
  for (const p of v.problems) {
    if (!isObj(p) || !isStr(p.code) || !isStr(p.severity) || !isStr(p.message)) return "malformed";
    out.push({
      code: p.code,
      severity: p.severity,
      message: p.message,
      evidence_id: isStr(p.evidence_id) ? p.evidence_id : null,
      sentence: isStr(p.sentence) ? p.sentence : null,
    });
  }
  return out;
}

/** Normalizes the run body to `ReplayRun`, or returns a problem description. */
export function readReplayRun(body: unknown): ReplayRun | string {
  if (!isObj(body)) return "body is not an object";
  const wrapped = isObj(body.prediction);
  if (wrapped) {
    const extra = extraKey(body, new Set(["prediction", "skeptic"]), "body");
    if (extra) return extra;
  }
  const raw = wrapped ? body.prediction : body;
  const problem = checkPrediction(raw, wrapped ? "prediction" : "body");
  if (problem) return problem;
  const skeptic = wrapped ? readSkeptic(body.skeptic) : null;
  if (skeptic === "malformed") return "skeptic report malformed";
  const p = raw as unknown as Prediction;
  return {
    prediction: { ...p, model_digest: p.model_digest ?? null, seed: p.seed ?? null },
    skeptic,
  };
}

/** True when a skeptic report has an error-level problem: such a forecast must not be displayed as valid. */
export function skepticRejected(problems: SkepticProblem[] | null): boolean {
  return !!problems && problems.some((p) => p.severity.toLowerCase() === "error");
}

const EVIDENCE_KEYS = new Set([
  "evidence_id", "event_id", "title", "source_url", "archive_url", "published_at", "observed_at", "available_at",
  "content_sha256", "content", "retrospective_unverified", "provenance",
]);
const QUOTE_KEYS = new Set([
  "quote_id", "venue", "market_id", "ts", "p_yes", "quote_kind", "raw_payload_sha256", "provenance", "label",
  "outcome",
]);

/**
 * Shape + cutoff check for the evidence body. An item or quote stamped after the cutoff makes the WHOLE response
 * malformed: the browser does not silently drop it.
 */
export function checkCaseEvidence(body: unknown, asOf: string): string | null {
  if (!isObj(body)) return "body is not an object";
  const extra = extraKey(body, new Set(["status", "as_of", "items", "market_quotes", "notes"]), "body");
  if (extra) return extra;
  if (body.status !== "AVAILABLE" && body.status !== "NOT AVAILABLE") return "status malformed";
  if (!isInstant(body.as_of)) return "as_of missing";
  if (Date.parse(body.as_of) !== Date.parse(asOf)) return "as_of does not match the case cutoff";
  if (!Array.isArray(body.items) || !Array.isArray(body.market_quotes)) return "items / market_quotes missing";
  if (!isStrArray(body.notes)) return "notes malformed";
  const cutoff = Date.parse(asOf);
  for (let i = 0; i < body.items.length; i++) {
    const e = body.items[i];
    const at = `items[${i}]`;
    if (!isObj(e)) return `${at} is not an object`;
    const x = extraKey(e, EVIDENCE_KEYS, at);
    if (x) return x;
    for (const k of ["evidence_id", "title", "source_url", "content", "content_sha256"]) {
      if (!isStr(e[k])) return `${at}.${k} missing`;
    }
    if (!isInstant(e.published_at) || !isInstant(e.available_at) || !isInstant(e.observed_at)) {
      return `${at} timestamps malformed`;
    }
    if (Date.parse(e.available_at) > cutoff) return `${at} has available_at after the cutoff (refused)`;
    if (e.retrospective_unverified === true) return `${at} is retrospective_unverified (refused)`;
    if (!isWireProvenance(e.provenance)) return `${at}.provenance is not a known wire label`;
  }
  for (let i = 0; i < body.market_quotes.length; i++) {
    const q = body.market_quotes[i];
    const at = `market_quotes[${i}]`;
    if (!isObj(q)) return `${at} is not an object`;
    const x = extraKey(q, QUOTE_KEYS, at);
    if (x) return x;
    if (!isStr(q.quote_id) || !isStr(q.market_id) || !isStr(q.label)) return `${at} ids missing`;
    if (q.venue !== "kalshi" && q.venue !== "polymarket") return `${at}.venue malformed`;
    if (!isInstant(q.ts)) return `${at}.ts malformed`;
    if (Date.parse(q.ts) > cutoff) return `${at} is stamped after the cutoff (refused)`;
    if (!isProb(q.p_yes)) return `${at}.p_yes is not in [0, 1]`;
    if (!isWireProvenance(q.provenance)) return `${at}.provenance is not a known wire label`;
  }
  return null;
}

// --------------------------------------------------------------------------------------------- transport

function readErrorBody(body: unknown): { message: string | null; code?: string; hasCode: boolean } {
  if (!isObj(body)) return { message: null, hasCode: false };
  const code = isStr(body.code) ? body.code : undefined;
  const issues = Array.isArray(body.errors)
    ? body.errors
        .filter(isObj)
        .map((e) => {
          const loc = Array.isArray(e.loc) ? e.loc.filter((x) => x !== "body").join(".") : "";
          return isStr(e.msg) ? (loc ? `${loc}: ${e.msg}` : e.msg) : null;
        })
        .filter((x): x is string => x !== null)
    : [];
  const tail = issues.length ? `\n${issues.join("; ")}` : "";
  if (isStr(body.message) && body.message.trim()) return { message: body.message + tail, code, hasCode: !!code };
  if (isStr(body.detail) && body.detail.trim()) return { message: body.detail, code, hasCode: !!code };
  return { message: issues.length ? issues.join("; ") : null, code, hasCode: !!code };
}

async function request(
  method: "GET" | "POST",
  path: string,
  timeoutMs: number,
  signal?: AbortSignal,
  payload?: unknown,
  /** false only for /openapi.json, whose schema names (e.g. SimulationResult) are not case data. */
  refuseOutcomeKeys = true,
): Promise<ReplayResult<unknown>> {
  const label = `${method} ${path}`;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(new DOMException("timeout", "TimeoutError")), timeoutMs);
  const onAbort = () => controller.abort(signal?.reason);
  if (signal?.aborted) onAbort();
  signal?.addEventListener("abort", onAbort, { once: true });
  const fail = (kind: ReplayErrorKind, message: string, extra: Partial<ReplayFailure> = {}): ReplayFailure => ({
    ok: false,
    kind,
    message,
    request: label,
    ...extra,
  });
  try {
    const res = await fetch(`${API_BASE}${path}`, {
      method,
      headers:
        payload === undefined
          ? { Accept: "application/json" }
          : { Accept: "application/json", "Content-Type": "application/json" },
      body: payload === undefined ? undefined : JSON.stringify(payload),
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
      const { message, code, hasCode } = readErrorBody(body);
      const status = res.status;
      const msg = message ?? `HTTP ${status}`;
      // FastAPI's own 404/405 for an unregistered path has no `code`; a route's coded 404 does.
      if ((status === 404 || status === 405) && !hasCode) return fail("route_missing", msg, { status });
      if (status === 404) return fail("not_found", msg, { status, code });
      if (status === 401 || status === 403) return fail("forbidden", msg, { status, code });
      if (status === 422) return fail("validation", msg, { status, code });
      if (status === 503 && code === "MODEL_UNAVAILABLE") return fail("model_unavailable", msg, { status, code });
      return fail("http", msg, { status, code });
    }
    if (!parsed) return fail("malformed", "response was not JSON", { status: res.status });
    const leaked = refuseOutcomeKeys ? outcomeKeyPaths(body) : [];
    // Key paths only, never values: the values are exactly what must not be shown pre-reveal.
    if (leaked.length) {
      return fail("leak", `response carried outcome-like keys and was refused: ${leaked.join(", ")}`, {
        status: res.status,
      });
    }
    return { ok: true, data: body, request: label };
  } catch (err) {
    if (controller.signal.aborted) {
      const reason: unknown = controller.signal.reason;
      const timedOut = reason instanceof DOMException && reason.name === "TimeoutError";
      return timedOut ? fail("timeout", `no response within ${Math.round(timeoutMs / 1000)} s`) : fail("aborted", "aborted");
    }
    return fail("network", err instanceof Error ? err.message : "request failed");
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", onAbort);
  }
}

export const CASES_PATH = "/api/cases";
export const REPLAY_RUN_PATH = "/api/replay/run";
export const evidencePath = (caseId: string, asOf: string) =>
  `/api/cases/${encodeURIComponent(caseId)}/evidence?as_of=${encodeURIComponent(asOf)}`;

/** GET /api/cases. Never throws. */
export async function getCases(signal?: AbortSignal): Promise<ReplayResult<CasesResponse>> {
  const res = await request("GET", CASES_PATH, 6000, signal);
  if (!res.ok) return res;
  const problem = checkCasesResponse(res.data);
  if (problem) return { ok: false, kind: "malformed", message: `malformed cases payload: ${problem}`, request: res.request };
  return { ok: true, data: res.data as CasesResponse, request: res.request };
}

/** GET /api/cases/{id}/evidence?as_of=<case cutoff>. `as_of` is always the case's own cutoff, sent as served. */
export async function getCaseEvidence(
  c: Pick<ReplayCasePublic, "event_id" | "as_of">,
  signal?: AbortSignal,
): Promise<ReplayResult<CaseEvidenceResponse>> {
  const res = await request("GET", evidencePath(c.event_id, c.as_of), 6000, signal);
  if (!res.ok) return res;
  const problem = checkCaseEvidence(res.data, c.as_of);
  if (problem) {
    return { ok: false, kind: "malformed", message: `malformed evidence payload: ${problem}`, request: res.request };
  }
  return { ok: true, data: res.data as CaseEvidenceResponse, request: res.request };
}

/**
 * POST /api/replay/run `{case_id, variant}` (issue #44). Only ever called from an explicit click: it runs the local
 * model and persists a prediction. Generous timeout because a local model can be slow; no progress is invented.
 */
export async function runReplay(
  c: Pick<ReplayCasePublic, "event_id" | "as_of">,
  variant: ForecastVariant,
  signal?: AbortSignal,
): Promise<ReplayResult<ReplayRun>> {
  const caseId = c.event_id;
  const res = await request("POST", REPLAY_RUN_PATH, 180_000, signal, { case_id: caseId, variant });
  if (!res.ok) return res;
  const run = readReplayRun(res.data);
  if (typeof run === "string") {
    return { ok: false, kind: "malformed", message: `malformed replay-run payload: ${run}`, request: res.request };
  }
  if (run.prediction.event_id !== caseId) {
    return { ok: false, kind: "malformed", message: "replay-run payload is for a different case", request: res.request };
  }
  if (Date.parse(run.prediction.as_of) !== Date.parse(c.as_of)) {
    return {
      ok: false,
      kind: "malformed",
      message: "replay-run payload's as_of does not match the case's knowledge cutoff",
      request: res.request,
    };
  }
  return { ok: true, data: run, request: res.request };
}

export type RoutePresence = "present" | "absent" | "unknown";
export interface ReplayRoutes {
  replayRun: RoutePresence;
  evidence: RoutePresence;
}

/**
 * Which replay routes this API build registers, read from FastAPI's `/openapi.json` (a GET with no side effects),
 * so the run button can say "route pending (#44)" without POSTing to a model. `unknown` when the schema is not
 * served (e.g. disabled in public mode): the screen then lets the request itself report what happened.
 */
export async function getReplayRoutes(signal?: AbortSignal): Promise<ReplayRoutes> {
  const res = await request("GET", "/openapi.json", 5000, signal, undefined, false);
  if (!res.ok || !isObj(res.data) || !isObj(res.data.paths)) return { replayRun: "unknown", evidence: "unknown" };
  const paths = Object.keys(res.data.paths);
  const runPaths = res.data.paths[REPLAY_RUN_PATH];
  return {
    replayRun: isObj(runPaths) && isObj(runPaths.post) ? "present" : "absent",
    evidence: paths.some((p) => /^\/api\/cases\/\{[^}]+\}\/evidence$/.test(p)) ? "present" : "absent",
  };
}

/**
 * Typed stub: retrieving a committed RECORDED RUN for a case. #44 commits recorded-run rows but defines no route
 * that serves them (needed: e.g. `GET /api/replay/recorded?case_id=` returning `Prediction[]`). Never fetches,
 * never returns data.
 */
export const RECORDED_RUNS_PENDING: ReplayFailure = {
  ok: false,
  kind: "pending",
  message: "No route serves committed RECORDED RUN rows yet (#44 commits them; a read route is a follow-up).",
  request: "GET /api/replay/recorded?case_id= (proposed)",
};

// --------------------------------------------------------------------------------------------- display helpers

/** `Knowledge cutoff` display text: "YYYY-MM-DD HH:MM UTC" of the served instant. Formatting only. */
export function formatCutoffUtc(iso: string): string | null {
  const ms = Date.parse(iso);
  if (!Number.isFinite(ms)) return null;
  const d = new Date(ms);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getUTCFullYear()}-${p(d.getUTCMonth() + 1)}-${p(d.getUTCDate())} ${p(d.getUTCHours())}:${p(d.getUTCMinutes())} UTC`;
}

/** Same instant with seconds, for audit fields (recorded_at, available_at). */
export function formatInstantUtc(iso: string): string | null {
  const ms = Date.parse(iso);
  if (!Number.isFinite(ms)) return null;
  return new Date(ms).toISOString().replace("T", " ").replace(/\.\d{3}Z$/, " UTC");
}

// --------------------------------------------------------------------------------------------- shared selection

/**
 * The selected case id, shared by REWIND and DECISION across client-side navigation. Only the id is kept (in
 * memory, mirrored to sessionStorage as a per-tab convenience); case data is always re-read from the API.
 */
const SELECTION_KEY = "faultline.replay.case";
let selected: string | null | undefined;
const listeners = new Set<() => void>();

function readSelection(): string | null {
  if (selected !== undefined) return selected;
  try {
    selected = typeof window === "undefined" ? null : window.sessionStorage.getItem(SELECTION_KEY);
  } catch {
    selected = null;
  }
  return selected;
}

export const selectionStore = {
  get: readSelection,
  getServer: (): string | null => null,
  set(id: string | null) {
    selected = id;
    try {
      if (id === null) window.sessionStorage.removeItem(SELECTION_KEY);
      else window.sessionStorage.setItem(SELECTION_KEY, id);
    } catch {
      // storage blocked: the in-memory selection still works for this page view
    }
    listeners.forEach((l) => l());
  },
  subscribe(listener: () => void) {
    listeners.add(listener);
    return () => listeners.delete(listener);
  },
};

/**
 * Runs made in this page session, keyed by `${event_id}|${variant}`, so returning to DECISION shows the run that was
 * actually made instead of an empty panel. Memory only: a reload shows nothing until a new run (or a recorded-run
 * route) supplies one. The persisted copy lives server-side (PredictionStore).
 */
const runs = new Map<string, ReplayRun>();
const runListeners = new Set<() => void>();
let runsVersion = 0;

export const runStore = {
  key: (eventId: string, variant: ForecastVariant) => `${eventId}|${variant}`,
  get: (eventId: string, variant: ForecastVariant): ReplayRun | undefined => runs.get(`${eventId}|${variant}`),
  put(run: ReplayRun, variant: ForecastVariant) {
    runs.set(`${run.prediction.event_id}|${variant}`, run);
    runsVersion += 1;
    runListeners.forEach((l) => l());
  },
  version: () => runsVersion,
  subscribe(listener: () => void) {
    runListeners.add(listener);
    return () => runListeners.delete(listener);
  },
};
