/**
 * Blind Replay client: GET /api/cases, GET /api/cases/{case_id}/evidence and POST /api/replay/run (all on main).
 *
 * Types mirror the server field for field; keep them in sync:
 * - services/api/models.py: `ReplayCasePublic`, `Prediction`, `ErrorCode`;
 * - services/api/routes/cases.py: `CasesResponse`, `CaseEvidenceResponse`, `GatedEvidence`, `GatedQuote`,
 *   `MarketAtCutoff`;
 * - services/api/routes/replay.py: `ReplayRunResponse`, `SkepticReview`; agents/skeptic.py `SkepticProblem`.
 *
 * Rules (AGENTS.md §4, SPEC §5):
 * - Nothing here computes a forecast, a probability or a verdict. Responses are shape-checked and rendered as-is.
 * - A pre-reveal response that carries ANY outcome-like key (models.OUTCOME_FIELD_PATTERN) is refused as
 *   `leak`, never displayed. The only exception mirrors the server's: `outcome: "YES"` directly on a market quote.
 * - Evidence or a quote stamped after the case cutoff is refused as `malformed`; the browser never filters it out
 *   and shows the rest, because the gate (core/temporal_gate.py) is the only thing allowed to decide admissibility.
 * - Every key set is strict: a key the contract does not name makes the body `malformed` (NOT AVAILABLE).
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
/** The run route's `ReplayRunRequest.variant`. `hosted_comparator` exists on `Prediction` but is never run here. */
export type ForecastVariant = "agent_only" | "agent_plus_market";
export type Decision = "act" | "wait" | "hedge";
/**
 * markets/base.py `Venue`. `synthetic` (PR #111, issue #102; accepted ahead of its merge) is a fictional price written
 * by a case author for a SYNTHETIC case: never a real market, never collected, no raw payload.
 */
export type Venue = "kalshi" | "polymarket" | "synthetic";
const VENUES: readonly Venue[] = ["kalshi", "polymarket", "synthetic"];
const isVenue = (v: unknown): v is Venue => VENUES.includes(v as Venue);
/** markets/base.py `QuoteKind` (the gate projects quotes from the normalizer, which adds `price_history_point`). */
/** `synthetic` is the only kind a synthetic-venue quote may have, and no real quote may have it (PR #111). */
export type QuoteKind = "midpoint" | "candle_close" | "last_trade" | "price_history_point" | "synthetic";
const QUOTE_KINDS: readonly QuoteKind[] = ["midpoint", "candle_close", "last_trade", "price_history_point", "synthetic"];

/** models.py `ErrorCode`, every value. */
export type ErrorCode =
  | "MODEL_UNAVAILABLE"
  | "NO_FEASIBLE_PLAN"
  | "NOT_REVEALABLE"
  | "INSUFFICIENT_DATA"
  | "NOT_FOUND"
  | "VALIDATION_ERROR"
  | "INFEASIBLE_INPUT"
  | "DATA_UNAVAILABLE"
  | "DATA_INVALID"
  | "MODEL_OUTPUT_INVALID"
  | "PROMPT_TOO_LONG"
  | "PROMPT_NOT_VERIFIED"
  | "ADMIN_TOKEN_REQUIRED"
  | "PREDICTION_EXISTS";

/** The two variants `ReplayRunRequest` accepts. */
export const RUN_VARIANTS: readonly { id: ForecastVariant; label: string; detail: string }[] = [
  { id: "agent_only", label: "Agent only", detail: "Point-in-time evidence; no market price in the prompt." },
  {
    id: "agent_plus_market",
    label: "Agent + market",
    detail: "Same evidence plus the as-of market quote. Refused (INSUFFICIENT_DATA) when the case has none.",
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
  /** Only the items the temporal gate admits at the case cutoff. */
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

/** models.py `Prediction`, as persisted before any reveal (the run route sets the audit fields on every run). */
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
  /** sha256 of the exact prompt the model answered (incl. a repair turn when attempts = 2). */
  prompt_sha256: string;
  snapshot_sha256: string;
  temperature: number;
  seed: number | null;
  recorded_at: string;
  provenance: WireProvenance;
  /** sha256 of the temporal gate's rendered prompt, before any repair turn. */
  gated_prompt_sha256: string | null;
  /** 1 = first answer validated; 2 = validated after the one schema repair. */
  attempts: 1 | 2 | null;
  transcript_sha256: string | null;
  num_ctx: number | null;
  num_predict: number | null;
}

/** agents/skeptic.py `ProblemCode`. */
export type SkepticProblemCode =
  | "UNKNOWN_EVIDENCE_ID"
  | "UNKNOWN_CITED_ID"
  | "POSSIBLE_UNKNOWN_ID"
  | "P_YES_OUT_OF_RANGE"
  | "INVALID_DECISION"
  | "RATIONALE_LENGTH"
  | "UNCITED_CLAIM"
  | "CITATION_NOT_LISTED"
  | "DUPLICATE_EVIDENCE_ID"
  | "NO_EVIDENCE_CITED";

/** agents/skeptic.py `SkepticProblem`. */
export interface SkepticProblem {
  code: SkepticProblemCode;
  severity: "error" | "warning";
  message: string;
  evidence_id: string | null;
  sentence: string | null;
}

/**
 * routes/cases.py `MarketAtCutoff`: the market-only baseline at the cutoff, chosen by the gate's fixed rule.
 * `status === "NOT AVAILABLE"` means every quote field is null and `note` says why. `p_yes` is price-derived.
 */
export interface MarketAtCutoff {
  status: "AVAILABLE" | "NOT AVAILABLE";
  /** Server label text, shown verbatim. Optional here while PR #111 may change it. */
  label?: string;
  /** `"<venue>:<market_id>"`. */
  ref: string | null;
  venue: Venue | null;
  market_id: string | null;
  quote_kind: QuoteKind | null;
  ts: string | null;
  p_yes: number | null;
  /** The case file's provenance (REAL_HISTORICAL or SYNTHETIC). Optional here while PR #111 is open. */
  provenance?: WireProvenance | null;
  note: string | null;
}

/** routes/replay.py `ReplayRunResponse` (pre-reveal; no outcome-like field). */
export interface ReplayRunResponse {
  prediction: Prediction;
  /** Warnings only: an error-level problem is a 422 and nothing is saved. */
  skeptic: { problems: SkepticProblem[] };
  market_at_cutoff: MarketAtCutoff;
  persisted_at: string;
  persist_seq: number;
  record_sha256: string;
  event_first_reveal_seq: number | null;
  /** Saved after this event's result was revealed in this store: not blind; the benchmark ignores it. */
  persisted_after_event_reveal: boolean;
  store_first_reveal_seq: number | null;
  /** Saved after some reveal in this store: cannot be OFFICIAL. */
  persisted_after_any_reveal: boolean;
  /** Server's plain-language warning when either flag is true; null otherwise. */
  audit_note: string | null;
}

/** The run as the screen keeps it: exactly the served body. */
export type ReplayRun = ReplayRunResponse;

/** routes/cases.py `GatedEvidence`: one admitted item exactly as the prompt shows it. */
export interface EvidenceItem {
  evidence_id: string;
  title: string;
  published_at: string;
  available_at: string;
  source_url: string;
  content: string;
  provenance: WireProvenance;
}

/** routes/cases.py `GatedQuote`: per market, the last quote within 24h before as_of. */
export interface GatedQuote {
  venue: Venue;
  market_id: string;
  p_yes: number;
  quote_kind: QuoteKind;
  ts: string;
  spread: number | null;
  volume: string | null;
  open_interest: string | null;
  period_seconds: number | null;
  /** Server label text, shown verbatim. Optional while PR #111 is open. */
  label?: string;
  /** Not served on main; PR #111's quotes carry it (SYNTHETIC exactly when venue is synthetic). */
  provenance?: WireProvenance;
}

/**
 * A synthetic benchmark price (venue `synthetic` or provenance SYNTHETIC): always shown with a SYNTHETIC badge and
 * the server's label, never as a real market, and with no raw payload. Read from served fields only.
 */
export function isSyntheticQuote(q: { venue: Venue | null; provenance?: WireProvenance | null }): boolean {
  return q.venue === "synthetic" || q.provenance === "SYNTHETIC";
}

/** Venue/kind/provenance must agree (PR #111's rule); a mismatch would mislabel a price, so it is refused. */
function syntheticMismatch(q: Record<string, unknown>, at: string): string | null {
  const venue = q.venue === "synthetic";
  if (venue !== (q.quote_kind === "synthetic")) return `${at}: quote_kind "synthetic" and venue "synthetic" disagree`;
  if (venue && q.provenance !== undefined && q.provenance !== null && q.provenance !== "SYNTHETIC") {
    return `${at}: a synthetic-venue quote is labelled ${String(q.provenance)} (refused)`;
  }
  return null;
}

/** routes/cases.py `CaseEvidenceResponse` (GET /api/cases/{case_id}/evidence). */
export interface CaseEvidenceResponse {
  status: "AVAILABLE" | "NOT AVAILABLE";
  event_id: string;
  /** The cutoff applied (this client never asks for an earlier one, so it equals `case_as_of`). */
  as_of: string;
  case_as_of: string;
  items: EvidenceItem[];
  market_quotes: GatedQuote[];
  market_at_cutoff: MarketAtCutoff;
  /** Counts of excluded items by reason; their ids and content are never served. */
  excluded_by_reason: Record<string, number>;
  notes: string[];
}

// --------------------------------------------------------------------------------------------- results

/**
 * `route_missing`: this API build has no such route (FastAPI's bare 404). `not_found`: a coded 404 (unknown case).
 * `admin_required`: 401/403 (public mode: run and reveal need the admin token). `model_unavailable`: 503.
 * `conflict`: 409 PREDICTION_EXISTS. `data_invalid`: 500 DATA_INVALID. `validation`: 422 (VALIDATION_ERROR,
 * INSUFFICIENT_DATA, PROMPT_TOO_LONG, PROMPT_NOT_VERIFIED, MODEL_OUTPUT_INVALID incl. skeptic rejection).
 * `leak`: a pre-reveal body carried an outcome-like key and was refused. `malformed`: a 2xx body off contract.
 */
export type ReplayErrorKind =
  | "network"
  | "timeout"
  | "aborted"
  | "route_missing"
  | "not_found"
  | "admin_required"
  | "validation"
  | "conflict"
  | "data_invalid"
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
const isInt = (v: unknown): v is number => typeof v === "number" && Number.isInteger(v);
const isPosInt = (v: unknown): v is number => isInt(v) && v > 0;
const isNullOr = <T>(v: unknown, ok: (x: unknown) => x is T): v is T | null => v === null || ok(v);
const isWireProvenance = (v: unknown): v is WireProvenance => WIRE_PROVENANCES.includes(v as WireProvenance);
const SHA256 = /^[0-9a-f]{64}$/;
const isSha = (v: unknown): v is string => isStr(v) && SHA256.test(v);

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

/** Every key in `keys` must be present, and nothing outside `keys` + `optional` may be: otherwise off contract. */
function exactKeys(
  obj: Record<string, unknown>,
  keys: readonly string[],
  at: string,
  optional: readonly string[] = [],
): string | null {
  const allowed = new Set([...keys, ...optional]);
  const extra = Object.keys(obj).find((k) => !allowed.has(k));
  if (extra !== undefined) return `${at} has non-contract key "${extra}"`;
  const missing = keys.find((k) => !(k in obj));
  return missing === undefined ? null : `${at} is missing "${missing}"`;
}

const CASE_KEYS = [
  "event_id", "title", "as_of", "horizon_days", "question_criteria", "evidence_ids", "market_quote_id",
  "snapshot_hash", "synthetic", "contamination_flag", "provenance",
] as const;

function checkCase(c: unknown, at: string): string | null {
  if (!isObj(c)) return `${at} is not an object`;
  const keys = exactKeys(c, CASE_KEYS, at);
  if (keys) return keys;
  for (const k of ["event_id", "title", "question_criteria"]) if (!isStr(c[k])) return `${at}.${k} missing`;
  if (!isInstant(c.as_of)) return `${at}.as_of is not an ISO instant`;
  if (!isPosInt(c.horizon_days)) return `${at}.horizon_days malformed`;
  if (!isStrArray(c.evidence_ids)) return `${at}.evidence_ids malformed`;
  if (!isNullOr(c.market_quote_id, isStr)) return `${at}.market_quote_id malformed`;
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
  const keys = exactKeys(body, ["status", "items", "notes"], "body");
  if (keys) return keys;
  if (body.status !== "AVAILABLE" && body.status !== "NOT AVAILABLE") return "status malformed";
  if (!Array.isArray(body.items)) return "items missing";
  if (!isStrArray(body.notes)) return "notes malformed";
  for (let i = 0; i < body.items.length; i++) {
    const problem = checkCase(body.items[i], `items[${i}]`);
    if (problem) return problem;
  }
  return null;
}

const PREDICTION_KEYS = [
  "prediction_id", "event_id", "as_of", "agent_model", "model_digest", "variant", "p_yes", "decision", "rationale",
  "evidence_ids", "prompt_sha256", "snapshot_sha256", "temperature", "seed", "recorded_at", "provenance",
  "gated_prompt_sha256", "attempts", "transcript_sha256", "num_ctx", "num_predict",
] as const;

function checkPrediction(p: unknown, at: string): string | null {
  if (!isObj(p)) return `${at} is not an object`;
  const keys = exactKeys(p, PREDICTION_KEYS, at);
  if (keys) return keys;
  for (const k of ["prediction_id", "event_id", "agent_model", "rationale"]) if (!isStr(p[k])) return `${at}.${k} missing`;
  if (!isInstant(p.as_of) || !isInstant(p.recorded_at)) return `${at} timestamps malformed`;
  if (!isProb(p.p_yes)) return `${at}.p_yes is not a probability in [0, 1]`;
  if (!["act", "wait", "hedge"].includes(p.decision as string)) return `${at}.decision is not act/wait/hedge`;
  if (!["agent_only", "agent_plus_market", "hosted_comparator"].includes(p.variant as string)) {
    return `${at}.variant malformed`;
  }
  if (!isStrArray(p.evidence_ids)) return `${at}.evidence_ids malformed`;
  if (!isSha(p.prompt_sha256)) return `${at}.prompt_sha256 malformed`;
  if (!isSha(p.snapshot_sha256)) return `${at}.snapshot_sha256 malformed`;
  if (!isNullOr(p.model_digest, isStr)) return `${at}.model_digest malformed`;
  if (typeof p.temperature !== "number" || !Number.isFinite(p.temperature) || p.temperature < 0) {
    return `${at}.temperature malformed`;
  }
  if (!isNullOr(p.seed, isInt)) return `${at}.seed malformed`;
  if (!isWireProvenance(p.provenance)) return `${at}.provenance is not a known wire label`;
  if (!isNullOr(p.gated_prompt_sha256, isSha)) return `${at}.gated_prompt_sha256 malformed`;
  if (!(p.attempts === null || p.attempts === 1 || p.attempts === 2)) return `${at}.attempts is not 1, 2 or null`;
  if (!isNullOr(p.transcript_sha256, isSha)) return `${at}.transcript_sha256 malformed`;
  if (!isNullOr(p.num_ctx, isPosInt)) return `${at}.num_ctx malformed`;
  if (!isNullOr(p.num_predict, isPosInt)) return `${at}.num_predict malformed`;
  return null;
}

const SKEPTIC_CODES: readonly SkepticProblemCode[] = [
  "UNKNOWN_EVIDENCE_ID", "UNKNOWN_CITED_ID", "POSSIBLE_UNKNOWN_ID", "P_YES_OUT_OF_RANGE", "INVALID_DECISION",
  "RATIONALE_LENGTH", "UNCITED_CLAIM", "CITATION_NOT_LISTED", "DUPLICATE_EVIDENCE_ID", "NO_EVIDENCE_CITED",
];

function checkSkeptic(v: unknown): string | null {
  if (!isObj(v)) return "skeptic is not an object";
  const keys = exactKeys(v, ["problems"], "skeptic");
  if (keys) return keys;
  if (!Array.isArray(v.problems)) return "skeptic.problems missing";
  for (let i = 0; i < v.problems.length; i++) {
    const p: unknown = v.problems[i];
    const at = `skeptic.problems[${i}]`;
    if (!isObj(p)) return `${at} is not an object`;
    const allowed = new Set(["code", "severity", "message", "evidence_id", "sentence"]);
    const extra = Object.keys(p).find((k) => !allowed.has(k));
    if (extra !== undefined) return `${at} has non-contract key "${extra}"`;
    if (!SKEPTIC_CODES.includes(p.code as SkepticProblemCode)) return `${at}.code is not a known skeptic code`;
    if (p.severity !== "error" && p.severity !== "warning") return `${at}.severity malformed`;
    if (!isStr(p.message)) return `${at}.message missing`;
    if (!(p.evidence_id === undefined || isNullOr(p.evidence_id, isStr))) return `${at}.evidence_id malformed`;
    if (!(p.sentence === undefined || isNullOr(p.sentence, isStr))) return `${at}.sentence malformed`;
  }
  return null;
}

const MARKET_KEYS = ["status", "ref", "venue", "market_id", "quote_kind", "ts", "p_yes", "note"] as const;
/** On main both are always served; kept optional so PR #111 cannot turn the panel into "malformed". */
const MARKET_OPTIONAL_KEYS = ["label", "provenance"] as const;

/** `MarketAtCutoff`, including the server's invariant that NOT AVAILABLE carries no quote value. */
function checkMarketAtCutoff(m: unknown, at: string, asOf: string): string | null {
  if (!isObj(m)) return `${at} is not an object`;
  const keys = exactKeys(m, MARKET_KEYS, at, MARKET_OPTIONAL_KEYS);
  if (keys) return keys;
  if (m.label !== undefined && !isStr(m.label)) return `${at}.label malformed`;
  if (!isNullOr(m.note, isStr)) return `${at}.note malformed`;
  if (m.status === "NOT AVAILABLE") {
    const quoteFields = ["ref", "venue", "market_id", "quote_kind", "ts", "p_yes", "provenance"];
    const filled = quoteFields.find((k) => m[k] !== null && m[k] !== undefined);
    return filled ? `${at} is NOT AVAILABLE but carries "${filled}"` : null;
  }
  if (m.status !== "AVAILABLE") return `${at}.status malformed`;
  if (!isStr(m.ref) || !isStr(m.market_id)) return `${at} ids missing`;
  if (!isVenue(m.venue)) return `${at}.venue malformed`;
  if (!QUOTE_KINDS.includes(m.quote_kind as QuoteKind)) return `${at}.quote_kind malformed`;
  if (!isInstant(m.ts)) return `${at}.ts malformed`;
  if (Date.parse(m.ts) > Date.parse(asOf)) return `${at} is stamped after the cutoff (refused)`;
  if (!isProb(m.p_yes)) return `${at}.p_yes is not in [0, 1]`;
  if (!(m.provenance === undefined || isNullOr(m.provenance, isWireProvenance))) {
    return `${at}.provenance is not a known wire label`;
  }
  return syntheticMismatch(m, at);
}

const RUN_KEYS = [
  "prediction", "skeptic", "market_at_cutoff", "persisted_at", "persist_seq", "record_sha256",
  "event_first_reveal_seq", "persisted_after_event_reveal", "store_first_reveal_seq", "persisted_after_any_reveal",
  "audit_note",
] as const;

/** Checks a POST /api/replay/run body against `ReplayRunResponse`; returns it typed, or a problem description. */
export function readReplayRun(body: unknown): ReplayRun | string {
  if (!isObj(body)) return "body is not an object";
  const keys = exactKeys(body, RUN_KEYS, "body");
  if (keys) return keys;
  const problem = checkPrediction(body.prediction, "prediction") ?? checkSkeptic(body.skeptic);
  if (problem) return problem;
  const asOf = (body.prediction as Prediction).as_of;
  const market = checkMarketAtCutoff(body.market_at_cutoff, "market_at_cutoff", asOf);
  if (market) return market;
  if (!isInstant(body.persisted_at)) return "persisted_at malformed";
  if (!isInt(body.persist_seq)) return "persist_seq malformed";
  if (!isSha(body.record_sha256)) return "record_sha256 malformed";
  if (!isNullOr(body.event_first_reveal_seq, isInt)) return "event_first_reveal_seq malformed";
  if (!isNullOr(body.store_first_reveal_seq, isInt)) return "store_first_reveal_seq malformed";
  if (typeof body.persisted_after_event_reveal !== "boolean") return "persisted_after_event_reveal malformed";
  if (typeof body.persisted_after_any_reveal !== "boolean") return "persisted_after_any_reveal malformed";
  if (!isNullOr(body.audit_note, isStr)) return "audit_note malformed";
  return body as unknown as ReplayRun;
}

/**
 * True when the server says this forecast was saved after a reveal (this event's, or any in the store). Such a run
 * is not blind and can never count toward an OFFICIAL scorecard. Read straight from the served flags.
 */
export function savedAfterReveal(run: ReplayRun): boolean {
  return run.persisted_after_event_reveal || run.persisted_after_any_reveal;
}

/** True when a skeptic report has an error-level problem. The server answers 422 for those; kept as a backstop. */
export function skepticRejected(problems: SkepticProblem[] | null): boolean {
  return !!problems && problems.some((p) => p.severity === "error");
}

const EVIDENCE_KEYS = [
  "evidence_id", "title", "published_at", "available_at", "source_url", "content", "provenance",
] as const;
const QUOTE_KEYS = [
  "venue", "market_id", "p_yes", "quote_kind", "ts", "spread", "volume", "open_interest", "period_seconds",
] as const;
const QUOTE_OPTIONAL_KEYS = ["label", "provenance"] as const;
const EVIDENCE_BODY_KEYS = [
  "status", "event_id", "as_of", "case_as_of", "items", "market_quotes", "market_at_cutoff", "excluded_by_reason",
  "notes",
] as const;

/**
 * Shape + cutoff check for the evidence body. An item or quote stamped after the cutoff makes the WHOLE response
 * malformed: the browser does not silently drop it.
 */
export function checkCaseEvidence(body: unknown, c: Pick<ReplayCasePublic, "event_id" | "as_of">): string | null {
  if (!isObj(body)) return "body is not an object";
  const keys = exactKeys(body, EVIDENCE_BODY_KEYS, "body");
  if (keys) return keys;
  if (body.status !== "AVAILABLE" && body.status !== "NOT AVAILABLE") return "status malformed";
  if (body.event_id !== c.event_id) return "event_id does not match the selected case";
  if (!isInstant(body.as_of) || !isInstant(body.case_as_of)) return "as_of / case_as_of missing";
  if (Date.parse(body.as_of) !== Date.parse(c.as_of)) return "as_of does not match the case cutoff";
  if (Date.parse(body.case_as_of) !== Date.parse(c.as_of)) return "case_as_of does not match the case cutoff";
  if (!Array.isArray(body.items) || !Array.isArray(body.market_quotes)) return "items / market_quotes missing";
  if (!isStrArray(body.notes)) return "notes malformed";
  if (!isObj(body.excluded_by_reason) || !Object.values(body.excluded_by_reason).every(isInt)) {
    return "excluded_by_reason malformed";
  }
  const cutoff = Date.parse(c.as_of);
  for (let i = 0; i < body.items.length; i++) {
    const e: unknown = body.items[i];
    const at = `items[${i}]`;
    if (!isObj(e)) return `${at} is not an object`;
    const x = exactKeys(e, EVIDENCE_KEYS, at);
    if (x) return x;
    for (const k of ["evidence_id", "title", "source_url", "content"]) if (!isStr(e[k])) return `${at}.${k} missing`;
    if (!isInstant(e.published_at) || !isInstant(e.available_at)) return `${at} timestamps malformed`;
    if (Date.parse(e.available_at) > cutoff) return `${at} has available_at after the cutoff (refused)`;
    if (!isWireProvenance(e.provenance)) return `${at}.provenance is not a known wire label`;
  }
  for (let i = 0; i < body.market_quotes.length; i++) {
    const q: unknown = body.market_quotes[i];
    const at = `market_quotes[${i}]`;
    if (!isObj(q)) return `${at} is not an object`;
    const x = exactKeys(q, QUOTE_KEYS, at, QUOTE_OPTIONAL_KEYS);
    if (x) return x;
    if (!isStr(q.market_id)) return `${at}.market_id missing`;
    if (q.label !== undefined && !isStr(q.label)) return `${at}.label malformed`;
    if (q.provenance !== undefined && !isWireProvenance(q.provenance)) return `${at}.provenance malformed`;
    if (!isVenue(q.venue)) return `${at}.venue malformed`;
    const mismatch = syntheticMismatch(q, at);
    if (mismatch) return mismatch;
    if (!QUOTE_KINDS.includes(q.quote_kind as QuoteKind)) return `${at}.quote_kind malformed`;
    if (!isInstant(q.ts)) return `${at}.ts malformed`;
    if (Date.parse(q.ts) > cutoff) return `${at} is stamped after the cutoff (refused)`;
    if (!isProb(q.p_yes)) return `${at}.p_yes is not in [0, 1]`;
    if (!isNullOr(q.spread, (v): v is number => typeof v === "number")) return `${at}.spread malformed`;
    if (!isNullOr(q.volume, isStr) || !isNullOr(q.open_interest, isStr)) return `${at} volume fields malformed`;
    if (!isNullOr(q.period_seconds, isInt)) return `${at}.period_seconds malformed`;
  }
  return checkMarketAtCutoff(body.market_at_cutoff, "market_at_cutoff", c.as_of);
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
      // Public mode: run and reveal are admin-only (routes/replay.py require_admin_in_public_mode).
      if (status === 401 || status === 403) return fail("admin_required", msg, { status, code });
      if (status === 409 && code === "PREDICTION_EXISTS") return fail("conflict", msg, { status, code });
      if (status === 422) return fail("validation", msg, { status, code });
      if (code === "DATA_INVALID") return fail("data_invalid", msg, { status, code });
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
/**
 * routes/cases.py `case_evidence`. `as_of` is omitted on purpose: its default (and maximum) is the case's own
 * cutoff, so the client never re-encodes the served instant. The response's `as_of` is checked against the case.
 */
export const evidencePath = (caseId: string) => `/api/cases/${encodeURIComponent(caseId)}/evidence`;
export const EVIDENCE_PATH_TEMPLATE = "/api/cases/{case_id}/evidence";

/** GET /api/cases. Never throws. */
export async function getCases(signal?: AbortSignal): Promise<ReplayResult<CasesResponse>> {
  const res = await request("GET", CASES_PATH, 6000, signal);
  if (!res.ok) return res;
  const problem = checkCasesResponse(res.data);
  if (problem) return { ok: false, kind: "malformed", message: `malformed cases payload: ${problem}`, request: res.request };
  return { ok: true, data: res.data as CasesResponse, request: res.request };
}

/** GET /api/cases/{case_id}/evidence: what the temporal gate admits at the case cutoff. Never throws. */
export async function getCaseEvidence(
  c: Pick<ReplayCasePublic, "event_id" | "as_of">,
  signal?: AbortSignal,
): Promise<ReplayResult<CaseEvidenceResponse>> {
  const res = await request("GET", evidencePath(c.event_id), 6000, signal);
  if (!res.ok) return res;
  const problem = checkCaseEvidence(res.data, c);
  if (problem) {
    return { ok: false, kind: "malformed", message: `malformed evidence payload: ${problem}`, request: res.request };
  }
  return { ok: true, data: res.data as CaseEvidenceResponse, request: res.request };
}

/**
 * POST /api/replay/run `{case_id, variant}` (routes/replay.py). Only ever called from an explicit click: it runs the
 * local model and persists a prediction before any reveal. Generous timeout because a local model can be slow; no
 * progress is invented. In public mode the route is admin-only (401/403 ADMIN_TOKEN_REQUIRED); this client never
 * sends a token, so the public demo shows that refusal, never a substitute forecast.
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
 * so the run button can say "route not served" without POSTing to a model. `unknown` when the schema is not
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
 * Typed stub: retrieving a committed RECORDED RUN prediction for a case before its reveal. #91's `GET /api/benchmark`
 * serves post-reveal scorecards only, which DECISION must not show. Needed: e.g. `GET /api/replay/recorded?case_id=`
 * returning the persisted `Prediction[]` with hashes. Never fetches, never returns data.
 */
export const RECORDED_RUNS_PENDING: ReplayFailure = {
  ok: false,
  kind: "pending",
  message: "No pre-reveal route serves committed RECORDED RUN predictions yet (GET /api/benchmark is post-reveal scorecards only).",
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
