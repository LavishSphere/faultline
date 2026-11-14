import { API_BASE, describeErrorBody, type ApiResult, type ScenarioPreset, type ScenarioShock } from "@/lib/api";

/**
 * GET /api/judge-challenges client (issue #123; services/api/routes/judge_challenges.py).
 *
 * The challenges are ILLUSTRATIVE *inputs*: named ScenarioShocks sized inside explore_shock_guidance.json. The browser
 * never computes anything from them; a picked shock is posted unchanged to POST /api/simulate, whose response is
 * the only source of numbers (SIMULATED).
 */
export const JUDGE_CHALLENGES_PATH = "/api/judge-challenges";

/** routes/judge_challenges.py `JudgeChallenge`. */
export interface JudgeChallenge {
  id: string;
  name: string;
  description: string;
  provenance: "ILLUSTRATIVE";
  guidance: { category: string; values: Record<string, Record<string, number>> };
  range_citation: string;
  shock: ScenarioShock;
}

/** routes/judge_challenges.py `JudgeChallengesResponse`. */
export interface JudgeChallengesResponse {
  status: "AVAILABLE" | "NOT AVAILABLE";
  provenance: "ILLUSTRATIVE";
  label: string;
  items: JudgeChallenge[];
  surprise_order: string[];
  notes: string[];
}

function isChallenge(x: unknown): x is JudgeChallenge {
  if (!x || typeof x !== "object") return false;
  const c = x as Record<string, unknown>;
  return (
    typeof c.id === "string" &&
    typeof c.name === "string" &&
    typeof c.description === "string" &&
    c.provenance === "ILLUSTRATIVE" &&
    typeof c.range_citation === "string" &&
    !!c.shock &&
    typeof c.shock === "object"
  );
}

/** Strict shape check: anything outside the contract is `malformed` (rendered NOT AVAILABLE), never patched up. */
export function checkJudgeChallenges(raw: unknown): string | null {
  if (!raw || typeof raw !== "object") return "body is not an object";
  const r = raw as Record<string, unknown>;
  if (r.status !== "AVAILABLE" && r.status !== "NOT AVAILABLE") return "unknown status";
  if (r.provenance !== "ILLUSTRATIVE") return "provenance is not ILLUSTRATIVE";
  if (!Array.isArray(r.items) || !r.items.every(isChallenge)) return "items do not match JudgeChallenge";
  if (!Array.isArray(r.surprise_order) || !r.surprise_order.every((s) => typeof s === "string")) return "bad surprise_order";
  const ids = new Set((r.items as JudgeChallenge[]).map((c) => c.id));
  if (r.surprise_order.length !== ids.size || !r.surprise_order.every((s) => ids.has(s as string)))
    return "surprise_order does not list every challenge exactly once";
  if (!Array.isArray(r.notes)) return "notes missing";
  return null;
}

/** GET /api/judge-challenges. Never throws; a 404 (older API build) is a normal NOT AVAILABLE state. */
export async function getJudgeChallenges(signal?: AbortSignal): Promise<ApiResult<JudgeChallengesResponse>> {
  try {
    const res = await fetch(`${API_BASE}${JUDGE_CHALLENGES_PATH}`, {
      headers: { Accept: "application/json" },
      cache: "no-store",
      signal: signal ? AbortSignal.any([signal, AbortSignal.timeout(4000)]) : AbortSignal.timeout(4000),
    });
    let body: unknown = null;
    try {
      body = await res.json();
    } catch {
      body = null;
    }
    if (!res.ok) {
      const { message, code } = describeErrorBody(body);
      return { ok: false, kind: "http", status: res.status, code, error: message ?? `HTTP ${res.status}` };
    }
    const problem = checkJudgeChallenges(body);
    if (problem) return { ok: false, kind: "malformed", status: res.status, error: `malformed judge-challenges payload: ${problem}` };
    return { ok: true, data: body as JudgeChallengesResponse };
  } catch (err) {
    if (signal?.aborted) return { ok: false, kind: "aborted", error: "aborted" };
    if (err instanceof DOMException && err.name === "TimeoutError") return { ok: false, kind: "timeout", error: "timed out" };
    return { ok: false, kind: "network", error: err instanceof Error ? err.message : "request failed" };
  }
}

/**
 * Deterministic "Surprise me": pick k (1-based) is entry (k − 1) mod n of the API's `surprise_order`.
 * No randomness; the pick number is shown to the viewer so the sequence is reproducible.
 */
export function surprisePick(order: readonly string[], k: number): string | null {
  if (order.length === 0 || k < 1) return null;
  return order[(k - 1) % order.length] ?? null;
}

/** A challenge as a CASCADE preset (sent exactly; slider moves override only the fields moved). */
export function challengeAsPreset(c: JudgeChallenge): ScenarioPreset {
  return { id: c.id, name: c.name, rationale: c.description, provenance: c.provenance, shock: c.shock };
}
