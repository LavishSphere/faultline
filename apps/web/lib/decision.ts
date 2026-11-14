/**
 * ACT / WAIT / HEDGE split view client (issue #55). Mirrors services/api/routes/decision.py field for field.
 *
 * Every payoff, E[V], feasibility flag, recommendation and break-even p* is computed by the API
 * (core.decision.evaluate_policies, MATH_MODEL §8). The browser only displays them; a body that does not match the
 * contract is refused as `malformed` and renders NOT AVAILABLE, never coerced into numbers.
 */
import { requestJson, type ApiResult } from "./api";

export const DECISION_FRAMES_PATH = "/api/decision/frames";
export const DECISION_PATH = "/api/decision";

export interface Fee {
  item: string;
  amount: string;
  when: string;
  in_payoff: boolean;
}

export interface FramePolicy {
  name: string;
  summary: string;
  provenance: "ILLUSTRATIVE";
  fees: Fee[];
}

export interface FrameSummary {
  id: string;
  question_type: string;
  provenance: "ILLUSTRATIVE";
  question_template: string;
  yes_means: string;
  no_means: string;
  no_state_models: string | null;
  not_modelled_note: string | null;
  forecast_sensitive: boolean;
  caveat: string | null;
  protect_payroll: boolean;
  policies: FramePolicy[];
}

export interface FramesResponse {
  provenance: "ILLUSTRATIVE";
  business_provenance: "SYNTHETIC" | "ILLUSTRATIVE";
  status: string;
  payoff: string;
  frames: FrameSummary[];
}

export interface DecisionRequest {
  frame_id: string;
  p_yes: number;
  protect_payroll?: boolean;
}

export interface PolicyResult {
  name: string;
  summary: string;
  value_if_yes: number | null;
  value_if_no: number | null;
  value_week_if_yes: number | null;
  value_week_if_no: number | null;
  expected_value: number | null;
  feasible_if_yes: boolean;
  feasible_if_no: boolean;
  feasible_in_both: boolean;
  breaches_if_yes: string[];
  breaches_if_no: string[];
}

export interface BreakEven {
  status: "AVAILABLE" | "NOT AVAILABLE";
  policies: string[];
  p_star: number | null;
  note: string;
}

export interface DecisionResponse {
  provenance: "SIMULATED";
  business_provenance: "SYNTHETIC" | "ILLUSTRATIVE";
  frame_provenance: "ILLUSTRATIVE";
  frame_id: string;
  question_type: string;
  p_yes: number;
  protect_payroll: boolean;
  payoff: string;
  constraints_checked: string[];
  policies: PolicyResult[];
  recommendation: string;
  break_even: BreakEven;
  forecast_sensitive: boolean;
  caveat: string | null;
  not_modelled_note: string | null;
  no_state_models: string | null;
}

export const NO_SAFE_POLICY = "NO SAFE POLICY";

const isObj = (v: unknown): v is Record<string, unknown> => !!v && typeof v === "object" && !Array.isArray(v);
const isNum = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);
const numOrNull = (v: unknown) => v === null || isNum(v);
const strOrNull = (v: unknown) => v === null || typeof v === "string";
const strList = (v: unknown) => Array.isArray(v) && v.every((x) => typeof x === "string");

function checkFrames(v: unknown): string | null {
  if (!isObj(v) || v.provenance !== "ILLUSTRATIVE" || !Array.isArray(v.frames)) return "not a frames listing";
  for (const [i, f] of v.frames.entries()) {
    if (!isObj(f) || typeof f.id !== "string" || typeof f.forecast_sensitive !== "boolean") return `frames[${i}]`;
    if (!strOrNull(f.caveat) || !strOrNull(f.not_modelled_note) || !Array.isArray(f.policies)) return `frames[${i}]`;
  }
  return null;
}

function checkDecision(v: unknown, req: DecisionRequest): string | null {
  if (!isObj(v) || v.provenance !== "SIMULATED") return "missing SIMULATED provenance";
  if (v.frame_id !== req.frame_id || v.p_yes !== req.p_yes) return "response is for a different request";
  if (typeof v.recommendation !== "string" || typeof v.forecast_sensitive !== "boolean") return "recommendation";
  if (!strOrNull(v.caveat) || !strOrNull(v.not_modelled_note)) return "caveat";
  const be = v.break_even;
  if (!isObj(be) || (be.status !== "AVAILABLE" && be.status !== "NOT AVAILABLE") || !numOrNull(be.p_star)) {
    return "break_even";
  }
  if (be.status === "AVAILABLE" && !isNum(be.p_star)) return "break_even.p_star";
  if (!Array.isArray(v.policies)) return "policies";
  for (const [i, p] of v.policies.entries()) {
    if (!isObj(p) || typeof p.name !== "string") return `policies[${i}]`;
    if (!numOrNull(p.value_if_yes) || !numOrNull(p.value_if_no) || !numOrNull(p.expected_value)) {
      return `policies[${i}] values`;
    }
    if (typeof p.feasible_in_both !== "boolean" || !strList(p.breaches_if_yes) || !strList(p.breaches_if_no)) {
      return `policies[${i}] feasibility`;
    }
  }
  return null;
}

/** GET /api/decision/frames. Never throws. */
export async function getDecisionFrames(signal?: AbortSignal): Promise<ApiResult<FramesResponse>> {
  const res = await requestJson<FramesResponse>("GET", DECISION_FRAMES_PATH, 6000, signal);
  if (!res.ok) return res;
  const problem = checkFrames(res.data);
  return problem ? { ok: false, kind: "malformed", error: `malformed frames payload: ${problem}` } : res;
}

/** POST /api/decision. Never throws. A 422 carries the server's message and code. */
export async function evaluateDecision(
  req: DecisionRequest,
  signal?: AbortSignal,
): Promise<ApiResult<DecisionResponse>> {
  const res = await requestJson<DecisionResponse>("POST", DECISION_PATH, 8000, signal, req);
  if (!res.ok) return res;
  const problem = checkDecision(res.data, req);
  return problem ? { ok: false, kind: "malformed", error: `malformed decision payload: ${problem}` } : res;
}

/**
 * Which decision frame a replay case belongs to, by explicit rule on its id (cases carry no question type yet).
 * `fomc-*` -> the FOMC frame; ids naming CPI -> the CPI frame; SYNTHETIC cases about a distributor / supplier / depot
 * -> the supply-disruption frame. Anything else -> null: no frame is selected and no POST /api/decision is sent until
 * the presenter picks one, so a forecast is never plugged into another question's payoffs. The frame must also be in
 * the served listing.
 */
export function frameForCase(
  c: { event_id: string; synthetic?: boolean } | null,
  servedFrameIds: readonly string[],
): string | null {
  if (!c) return null;
  const id = c.event_id.toLowerCase();
  const synthetic = c.synthetic === true || id.startsWith("synthetic");
  let frame: string | null = null;
  if (/^fomc-/.test(id)) frame = "fomc-rate-decision";
  else if (/(^|[-_])cpi([-_]|$)/.test(id)) frame = "cpi-surprise";
  else if (synthetic && /distributor|supplier|depot/.test(id)) frame = "supply-disruption";
  return frame !== null && servedFrameIds.includes(frame) ? frame : null;
}
