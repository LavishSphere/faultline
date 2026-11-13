/**
 * GET /api/explore/search client: LIVE EXPLORE web search via Tavily (issue #60; services/api/routes/explore.py).
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

import { API_BASE } from "./api";

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
  if (code === "ADMIN_TOKEN_REQUIRED" || status === 403) return "admin_only";
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

/** GET /api/explore/search. Never throws: every failure is a typed, displayable result. */
export async function searchLiveExplore(
  q: string,
  maxResults: number = EXPLORE_DEFAULT_MAX_RESULTS,
  signal?: AbortSignal,
  timeoutMs = 20000,
): Promise<ExploreResult> {
  const url = `${API_BASE}${EXPLORE_SEARCH_PATH}?q=${encodeURIComponent(q)}&max_results=${encodeURIComponent(String(maxResults))}`;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(new DOMException("timeout", "TimeoutError")), timeoutMs);
  const onAbort = () => controller.abort(signal?.reason);
  if (signal?.aborted) onAbort();
  signal?.addEventListener("abort", onAbort, { once: true });
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
    const problem = checkExploreResponse(body);
    if (problem) return { ok: false, kind: "malformed", status: res.status, message: `malformed response: ${problem}` };
    return { ok: true, data: body as ExploreSearchResponse };
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
