/**
 * GET /api/vc-lenses client (issue #37; route from issue #25, services/api/routes/research.py).
 *
 * Types mirror the Pydantic response models field for field: `VcLensesPointInTime` (with `?as_of=`) and
 * `VcLensesLiveExplore` (no `as_of`), discriminated by `mode`. Errors use the routes' `RouteErrorBody`
 * `{code, message, errors: [{loc, msg, type}]}`.
 *
 * Kept in its own module rather than lib/api.ts's shared `requestJson`: that helper flattens field issues into one
 * message string and has no 404 kind, and Thesis Court shows both separately.
 *
 * The shape check is strict: any key outside the contract (top level, item or quote) makes the whole response
 * `malformed` → NOT AVAILABLE. In particular a point-in-time body can never carry Live Explore curation fields
 * (limitations, archive, access dates, quote notes) into the AS-OF view.
 *
 * Nothing here computes or filters. Which lenses were public at the cutoff is decided by the API
 * (`core.research.eligible_lenses`); the browser only checks the shape and renders what it got.
 */

import { API_BASE } from "./api";

export const VC_LENSES_PATH = "/api/vc-lenses";

export type QuoteKind = "documentary_fact" | "analyst_interpretation" | "quantitative_forecast";
export const QUOTE_KINDS: readonly QuoteKind[] = ["documentary_fact", "analyst_interpretation", "quantitative_forecast"];

/** routes/research.py `LensQuote` (point-in-time) / `LensQuoteNoted` (Live Explore adds `note`). */
export interface LensQuote {
  text: string;
  kind: QuoteKind;
  /** Live Explore only: curator note on the quote. */
  note?: string | null;
  /**
   * Not served by the #25 route yet. When the API sends `false`, the quote is marked "not scorable".
   * When absent, scorability is NOT AVAILABLE (never inferred in the browser).
   */
  scorable?: boolean;
}

/** routes/research.py `LensPointInTime`: content fields only, no curation metadata. */
export interface LensPointInTime {
  id: string;
  firm: string;
  title: string;
  url: string;
  /** Displayed publication date (YYYY-MM-DD); null when the page shows none or it is after as_of. */
  published_at: string | null;
  thesis: string;
  hypotheses: string[];
  quotes: LensQuote[];
}

/** routes/research.py `LensLiveExplore`: the full curated item with its sourcing. */
export interface LensLiveExplore extends LensPointInTime {
  source_type: string | null;
  authors: string[];
  published_at_basis: string | null;
  /** Conservative date the quoted text is proven public (YYYY-MM-DD). */
  available_at: string;
  available_at_basis: string;
  archived_url: string | null;
  archived_at: string | null;
  accessed_at: string;
  themes: string[];
  thesis_review: string | null;
  limitations: string[];
}

export type LensStatus = "AVAILABLE" | "NOT AVAILABLE";

interface VcLensesCommon {
  status: LensStatus;
  label: "RESEARCH CONTEXT";
  mode_label: string;
  /** Wire value; displayed as "REAL HISTORICAL". */
  provenance: "REAL_HISTORICAL";
  notes: string[];
}

export interface VcLensesPointInTime extends VcLensesCommon {
  mode: "point_in_time";
  /** The replay cutoff, normalized to UTC by the API. */
  as_of: string;
  items: LensPointInTime[];
  /** Curated lenses hidden because they were not provably public at as_of. */
  /** null when the API has no dataset to count from (PR #59); a number otherwise. */
  excluded_not_yet_public: number | null;
}

export interface VcLensesLiveExplore extends VcLensesCommon {
  mode: "live_explore";
  as_of: null;
  items: LensLiveExplore[];
}

export type VcLensesResponse = VcLensesPointInTime | VcLensesLiveExplore;

/** routes/__init__.py `FieldIssue`. */
export interface RouteFieldIssue {
  loc: (string | number)[];
  msg: string;
  type: string;
}

/** routes/__init__.py `RouteErrorBody`. */
export interface RouteErrorBody {
  code: string;
  message: string;
  errors: RouteFieldIssue[];
}

/**
 * Why a request failed. `network`/`timeout`: the API could not be reached. `validation`: 422 (message shown
 * verbatim). `not_found`: this API build does not serve the route. `http`: any other non-2xx.
 * `malformed`: a 2xx body that did not match the contract (rendered NOT AVAILABLE, never patched up).
 */
export type VcLensesErrorKind = "network" | "timeout" | "aborted" | "validation" | "not_found" | "http" | "malformed";

export interface VcLensesFailure {
  ok: false;
  kind: VcLensesErrorKind;
  message: string;
  status?: number;
  code?: string;
  errors: RouteFieldIssue[];
  /** Exact request URL, shown so the presenter can see what was asked. */
  url: string;
}

export type VcLensesResult = { ok: true; data: VcLensesResponse; url: string } | VcLensesFailure;

// --- shape checks (contract only; no values are computed or defaulted) -----------------------------------------

const isStr = (v: unknown): v is string => typeof v === "string";
const isStrOrNull = (v: unknown): v is string | null => v === null || typeof v === "string";
const isStrArray = (v: unknown): v is string[] => Array.isArray(v) && v.every(isStr);
const isObj = (v: unknown): v is Record<string, unknown> => !!v && typeof v === "object" && !Array.isArray(v);

/** Key sets of the #27 response models. `scorable` is the one forward-compatible key (issue #37 AC; boolean only). */
const TOP_KEYS_PIT = new Set([
  "mode", "status", "label", "mode_label", "provenance", "as_of", "items", "excluded_not_yet_public", "notes",
]);
const TOP_KEYS_LIVE = new Set(["mode", "status", "label", "mode_label", "provenance", "as_of", "items", "notes"]);
const ITEM_KEYS_PIT = new Set(["id", "firm", "title", "url", "published_at", "thesis", "hypotheses", "quotes"]);
const ITEM_KEYS_LIVE = new Set([
  ...ITEM_KEYS_PIT,
  "source_type", "authors", "published_at_basis", "available_at", "available_at_basis", "archived_url",
  "archived_at", "accessed_at", "themes", "thesis_review", "limitations",
]);
const QUOTE_KEYS_PIT = new Set(["text", "kind", "scorable"]);
const QUOTE_KEYS_LIVE = new Set(["text", "kind", "note", "scorable"]);

function extraKey(obj: Record<string, unknown>, allowed: Set<string>, at: string): string | null {
  const extra = Object.keys(obj).find((k) => !allowed.has(k));
  return extra === undefined ? null : `${at} has non-contract key "${extra}"`;
}

function checkQuote(q: unknown, at: string, live: boolean): string | null {
  if (!isObj(q)) return `${at} is not an object`;
  const extra = extraKey(q, live ? QUOTE_KEYS_LIVE : QUOTE_KEYS_PIT, at);
  if (extra) return extra;
  if (!isStr(q.text)) return `${at}.text missing`;
  if (!QUOTE_KINDS.includes(q.kind as QuoteKind)) return `${at}.kind is not a known quote kind`;
  if (q.note !== undefined && !isStrOrNull(q.note)) return `${at}.note malformed`;
  if (q.scorable !== undefined && typeof q.scorable !== "boolean") return `${at}.scorable malformed`;
  return null;
}

function checkItem(item: unknown, at: string, live: boolean): string | null {
  if (!isObj(item)) return `${at} is not an object`;
  const extra = extraKey(item, live ? ITEM_KEYS_LIVE : ITEM_KEYS_PIT, at);
  if (extra) return extra;
  for (const key of ["id", "firm", "title", "url", "thesis"]) {
    if (!isStr(item[key])) return `${at}.${key} missing`;
  }
  if (!isStrOrNull(item.published_at ?? null)) return `${at}.published_at malformed`;
  if (!isStrArray(item.hypotheses)) return `${at}.hypotheses malformed`;
  if (!Array.isArray(item.quotes)) return `${at}.quotes missing`;
  for (let i = 0; i < item.quotes.length; i++) {
    const problem = checkQuote(item.quotes[i], `${at}.quotes[${i}]`, live);
    if (problem) return problem;
  }
  if (live) {
    if (!isStr(item.available_at) || !isStr(item.accessed_at)) return `${at} sourcing dates missing`;
    if (!isStrArray(item.limitations)) return `${at}.limitations malformed`;
    if (!isStrOrNull(item.archived_url ?? null)) return `${at}.archived_url malformed`;
    if (!isStrOrNull(item.published_at_basis ?? null)) return `${at}.published_at_basis malformed`;
  }
  return null;
}

/** Returns a problem description, or null when the body matches the #25 contract. */
export function checkVcLensesResponse(body: unknown): string | null {
  if (!isObj(body)) return "body is not an object";
  if (body.mode !== "point_in_time" && body.mode !== "live_explore") return "mode is not point_in_time or live_explore";
  if (body.status !== "AVAILABLE" && body.status !== "NOT AVAILABLE") return "status malformed";
  if (body.label !== "RESEARCH CONTEXT") return "label is not RESEARCH CONTEXT";
  if (body.provenance !== "REAL_HISTORICAL") return "provenance is not REAL_HISTORICAL";
  if (!isStr(body.mode_label)) return "mode_label missing";
  if (!isStrArray(body.notes)) return "notes malformed";
  if (!Array.isArray(body.items)) return "items missing";
  const live = body.mode === "live_explore";
  const extra = extraKey(body, live ? TOP_KEYS_LIVE : TOP_KEYS_PIT, "body");
  if (extra) return extra;
  if (live) {
    if (body.as_of !== null && body.as_of !== undefined) return "live_explore carries an as_of";
  } else {
    if (!isStr(body.as_of)) return "as_of missing";
    const n = body.excluded_not_yet_public;
    if (n !== null && (typeof n !== "number" || !Number.isInteger(n) || n < 0)) return "excluded_not_yet_public malformed";
  }
  for (let i = 0; i < body.items.length; i++) {
    const problem = checkItem(body.items[i], `items[${i}]`, live);
    if (problem) return problem;
  }
  return null;
}

function readErrorBody(body: unknown): { message: string | null; code?: string; errors: RouteFieldIssue[] } {
  if (!isObj(body)) return { message: null, errors: [] };
  const code = isStr(body.code) ? body.code : undefined;
  const errors: RouteFieldIssue[] = Array.isArray(body.errors)
    ? body.errors.filter(isObj).map((e) => ({
        loc: Array.isArray(e.loc) ? e.loc.filter((x): x is string | number => isStr(x) || typeof x === "number") : [],
        msg: isStr(e.msg) ? e.msg : "",
        type: isStr(e.type) ? e.type : "",
      }))
    : [];
  if (isStr(body.message) && body.message.trim()) return { message: body.message, code, errors };
  // FastAPI's default `{detail}` (e.g. a 404 from an API build without this route).
  if (isStr(body.detail) && body.detail.trim()) return { message: body.detail, code, errors };
  return { message: null, code, errors };
}

/**
 * GET /api/vc-lenses. `asOf` is sent exactly as given (the API validates and normalizes it to UTC; the browser does
 * not parse it). Omit `asOf` for Live Explore. Never throws: every failure is a typed, displayable result.
 */
export async function getVcLenses(asOf?: string, signal?: AbortSignal, timeoutMs = 6000): Promise<VcLensesResult> {
  const url = `${API_BASE}${VC_LENSES_PATH}${asOf === undefined ? "" : `?as_of=${encodeURIComponent(asOf)}`}`;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(new DOMException("timeout", "TimeoutError")), timeoutMs);
  const onAbort = () => controller.abort(signal?.reason);
  if (signal?.aborted) onAbort();
  signal?.addEventListener("abort", onAbort, { once: true });
  const fail = (kind: VcLensesErrorKind, message: string, extra: Partial<VcLensesFailure> = {}): VcLensesFailure => ({
    ok: false,
    kind,
    message,
    errors: [],
    url,
    ...extra,
  });
  try {
    const res = await fetch(url, {
      method: "GET",
      headers: { Accept: "application/json" },
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
      const { message, code, errors } = readErrorBody(body);
      const kind: VcLensesErrorKind =
        res.status === 422 ? "validation" : res.status === 404 ? "not_found" : "http";
      return fail(kind, message ?? `HTTP ${res.status}`, { status: res.status, code, errors });
    }
    if (!parsed) return fail("malformed", "response was not JSON", { status: res.status });
    const problem = checkVcLensesResponse(body);
    if (problem) return fail("malformed", `malformed vc-lenses payload: ${problem}`, { status: res.status });
    return { ok: true, data: body as VcLensesResponse, url };
  } catch (err) {
    if (controller.signal.aborted) {
      const reason: unknown = controller.signal.reason;
      const timedOut = reason instanceof DOMException && reason.name === "TimeoutError";
      return timedOut ? fail("timeout", `no response within ${timeoutMs / 1000} s`) : fail("aborted", "aborted");
    }
    return fail("network", err instanceof Error ? err.message : "request failed");
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", onAbort);
  }
}
