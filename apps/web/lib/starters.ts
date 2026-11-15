/**
 * GET /api/explore/chat/starters (#220): current-events management questions for the starter cards, each tied to a
 * news item the server retrieved. Shape (routes/explore_chat.py, being added):
 *   {provenance: "REAL (web, retrieved <UTC>)", generated_at, label,
 *    starters: [{question, headline, source_title, source_url, domain, published_date | null, tag}]}
 * 503 STARTERS_UNAVAILABLE when the server cannot build them (with Retry-After: 15 while its startup refresh is still
 * running, #234). On any failure (404 on an older API, 503, network) the UI shows the static questions below with no
 * news line; on a 503 or a timeout it asks again quietly (STARTERS_RETRIES times, STARTERS_RETRY_MS apart) and swaps
 * the news questions in when they arrive. Nothing here is invented.
 */
import { requestJson, type ApiFailure, type ApiResult } from "./api";

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

/** A starter card: a question only, never a result. `news` is set only for a question the server tied to a story. */
export interface StarterItem {
  tag: StarterTag;
  title: string;
  prompt: string;
  news?: NewsStarter;
}

export const MAX_STARTER_CARDS = 4;

/**
 * Standard questions, shown when there are no news questions: real, named companies and a neutral decision each, in
 * the news questions' voice. No allegation about anyone, and nothing about cash, wages or payroll (#234).
 */
export const STATIC_STARTERS: readonly StarterItem[] = [
  { tag: "Leadership", title: "Should Meta keep Mark Zuckerberg as CEO?", prompt: "Should Meta keep Mark Zuckerberg as CEO? Give me the odds." },
  { tag: "Leadership", title: "Should Nvidia's board pick an outside CEO?", prompt: "Should Nvidia's board pick an outside CEO when succession comes? Give me the odds." },
  { tag: "M&A", title: "Should Disney sell ABC?", prompt: "Should Disney sell ABC? Give me the odds and the main risks." },
  {
    tag: "Strategy",
    title: "Should Apple move iPhone production out of China faster?",
    prompt: "Should Apple move iPhone production out of China faster? Give me the odds and the main risks.",
  },
];

/**
 * The cards for a news response: its questions first (at most MAX_STARTER_CARDS), then standard questions to keep
 * the card count fixed, so swapping the news in never changes the layout. Padded cards carry no `news`.
 */
export function newsCards(data: StartersResponse): StarterItem[] {
  const cards: StarterItem[] = data.starters
    .slice(0, MAX_STARTER_CARDS)
    .map((s) => ({ tag: s.tag, title: s.question, prompt: s.question, news: s }));
  const titles = new Set(cards.map((s) => s.title));
  for (const s of STATIC_STARTERS) {
    if (cards.length >= MAX_STARTER_CARDS) break;
    if (!titles.has(s.title)) cards.push(s);
  }
  return cards;
}

export const STARTERS_RETRIES = 3;
export const STARTERS_RETRY_MS = 15_000;

/** Worth asking again: the server is still preparing (503) or the request timed out. 404 / malformed / network: no. */
export function startersRetryable(r: ApiFailure): boolean {
  return r.kind === "timeout" || (r.kind === "http" && r.status === 503);
}

/** Resolves after `ms`, or at once when `signal` aborts. */
export function waitMs(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((done) => {
    if (signal?.aborted) return done();
    const t = setTimeout(done, ms);
    signal?.addEventListener("abort", () => { clearTimeout(t); done(); }, { once: true });
  });
}

/**
 * Ask for the news starters; after a retryable failure ask again up to STARTERS_RETRIES more times, STARTERS_RETRY_MS
 * apart. `onResult` gets the first failure (the UI settles on the standard questions) and the success, if one comes.
 * Stops on abort. `fetchOnce` and `wait` are injectable for tests.
 */
export async function loadStartersWithRetry(
  onResult: (r: ApiResult<StartersResponse>) => void,
  signal?: AbortSignal,
  fetchOnce: (signal?: AbortSignal) => Promise<ApiResult<StartersResponse>> = getChatStarters,
  wait: (ms: number, signal?: AbortSignal) => Promise<void> = waitMs,
): Promise<void> {
  for (let attempt = 0; attempt <= STARTERS_RETRIES; attempt++) {
    const r = await fetchOnce(signal);
    if (signal?.aborted) return;
    if (r.ok) return onResult(r);
    if (attempt === 0) onResult(r);
    if (!startersRetryable(r) || attempt === STARTERS_RETRIES) return;
    await wait(STARTERS_RETRY_MS, signal);
    if (signal?.aborted) return;
  }
}
