/**
 * GET /api/explore/chat/starters (#220): current-events management questions for the starter cards, each tied to a
 * news item the server retrieved. Shape (routes/explore_chat.py, being added):
 *   {provenance: "REAL (web, retrieved <UTC>)", generated_at, label,
 *    starters: [{question, headline, source_title, source_url, domain, published_date | null, tag}]}
 * 503 STARTERS_UNAVAILABLE when the server cannot build them. On any failure (404 on an older API, 503, network) the
 * UI falls back to static questions with no news line; nothing here is invented.
 */
import { requestJson, type ApiResult } from "./api";

export const CHAT_STARTERS_PATH = "/api/explore/chat/starters";

export const STARTER_TAGS = ["Leadership", "M&A", "Strategy", "Governance", "Workforce"] as const;
export type StarterTag = (typeof STARTER_TAGS)[number];

export interface NewsStarter {
  question: string;
  headline: string;
  source_title: string;
  source_url: string;
  domain: string;
  published_date: string | null;
  tag: StarterTag;
}

export interface StartersResponse {
  provenance: string;
  generated_at: string;
  label: string;
  starters: NewsStarter[];
}

const isObj = (v: unknown): v is Record<string, unknown> => !!v && typeof v === "object" && !Array.isArray(v);
const str = (v: unknown): v is string => typeof v === "string" && v.trim().length > 0;
const TAGS = new Set<string>(STARTER_TAGS);

/** Shape check; null when the body is usable. A starter with an unknown tag or a blank field refuses the whole body. */
export function checkStarters(v: unknown): string | null {
  if (!isObj(v)) return "not an object";
  if (!str(v.provenance) || !str(v.generated_at) || typeof v.label !== "string") return "provenance";
  if (!Array.isArray(v.starters) || v.starters.length === 0) return "starters";
  for (const [i, s] of v.starters.entries()) {
    if (!isObj(s)) return `starters[${i}]`;
    for (const k of ["question", "headline", "source_title", "source_url", "domain"]) if (!str(s[k])) return `starters[${i}].${k}`;
    if (!(s.published_date === null || str(s.published_date))) return `starters[${i}].published_date`;
    if (typeof s.tag !== "string" || !TAGS.has(s.tag)) return `starters[${i}].tag`;
  }
  return null;
}

/** An http(s) link, else null (javascript:, data: and relative urls are dropped). */
export function httpUrl(v: string): URL | null {
  try {
    const u = new URL(v);
    return u.protocol === "https:" || u.protocol === "http:" ? u : null;
  } catch {
    return null;
  }
}

/** "Nov 14, 2026" for a served date, in UTC; null when absent or unparseable. */
export function newsDate(v: string | null): string | null {
  if (!v) return null;
  const t = Date.parse(v);
  if (Number.isNaN(t)) return null;
  return new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" }).format(t);
}

/** GET /api/explore/chat/starters. Never throws; a body that fails the shape check is `malformed`. */
export async function getChatStarters(signal?: AbortSignal): Promise<ApiResult<StartersResponse>> {
  const res = await requestJson<StartersResponse>("GET", CHAT_STARTERS_PATH, 8000, signal);
  if (!res.ok) return res;
  const problem = checkStarters(res.data);
  return problem ? { ok: false, kind: "malformed", error: `malformed starters payload: ${problem}` } : res;
}
