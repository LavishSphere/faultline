/**
 * FAULTLINE API client.
 *
 * Rules (AGENTS.md §4, cascade-ui skill):
 * - The browser never computes authoritative numbers. Every figure shown comes from a response here.
 * - Anything not yet served by the API is listed in PENDING_ENDPOINTS and renders NOT AVAILABLE.
 *
 * Wired: `/api/health`, `POST /api/simulate` and `GET /api/scenarios` (contract: issue #25).
 * `HealthResponse` is a tolerant reading of issue #1's acceptance criteria. The simulate types mirror the Pydantic
 * models in `services/api/core/financials.py` field for field: keep them in sync (or generate them from
 * `/openapi.json` once the routes land).
 */

// `||` (not `??`) so an empty NEXT_PUBLIC_API_BASE also falls back to the local default.
export const API_BASE: string = (process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000").replace(/\/+$/, "");

/**
 * Why a request failed. `network`/`timeout`: the API could not be reached. `http`: any non-2xx other than 422.
 * `validation`: a 422 whose server message is shown verbatim. `malformed`: a 2xx body that did not match the typed
 * contract (rendered NOT AVAILABLE, never coerced into numbers).
 */
export type ApiErrorKind = "network" | "timeout" | "aborted" | "http" | "validation" | "malformed";

export interface ApiFailure {
  ok: false;
  error: string;
  kind?: ApiErrorKind;
  status?: number;
  /** Machine-readable `code` from the API error body (models.ErrorCode, or e.g. INFEASIBLE_INPUT), when sent. */
  code?: string;
}

export type ApiResult<T> = { ok: true; data: T } | ApiFailure;

/** Raw `/api/health` payload as described by issue #1. All fields optional until the contract is fixed. */
export interface HealthResponse {
  status?: string;
  /** Issue #1: "ollama reachable (+ installed model tags)". Either a boolean or a nested object. */
  ollama?: boolean | { reachable?: boolean; models?: string[] };
  models?: string[];
  ollama_models?: string[];
  [key: string]: unknown;
}

export type ModelAvailability = "available" | "unavailable" | "unknown";

/** What the UI actually needs from `/api/health`. Derived only from fields the API returned. */
export interface HealthSummary {
  status: string | null;
  model: ModelAvailability;
  modelTags: string[];
  checkedAt: Date;
}

function asStringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((v): v is string => typeof v === "string") : [];
}

export function summarizeHealth(raw: HealthResponse, checkedAt: Date = new Date()): HealthSummary {
  let reachable: boolean | undefined;
  let tags: string[] = [];

  if (typeof raw.ollama === "boolean") {
    reachable = raw.ollama;
  } else if (raw.ollama && typeof raw.ollama === "object") {
    if (typeof raw.ollama.reachable === "boolean") reachable = raw.ollama.reachable;
    tags = asStringArray(raw.ollama.models);
  }
  if (tags.length === 0) tags = asStringArray(raw.ollama_models);
  if (tags.length === 0) tags = asStringArray(raw.models);

  let model: ModelAvailability = "unknown";
  if (reachable === false) model = "unavailable";
  else if (reachable === true) model = tags.length > 0 ? "available" : "unavailable";

  return {
    status: typeof raw.status === "string" ? raw.status : null,
    model,
    modelTags: tags,
    checkedAt,
  };
}

/** `[{loc, msg}]` field issues → "shock.demand: msg; …" (the `body` prefix is dropped). */
function describeIssues(list: unknown): string | null {
  if (!Array.isArray(list)) return null;
  const parts = list
    .map((d) => {
      if (!d || typeof d !== "object") return null;
      const item = d as Record<string, unknown>;
      if (typeof item.msg !== "string") return null;
      const loc = Array.isArray(item.loc) ? item.loc.filter((x) => x !== "body").join(".") : "";
      return loc ? `${loc}: ${item.msg}` : item.msg;
    })
    .filter((x): x is string => x !== null);
  return parts.length ? parts.join("; ") : null;
}

/**
 * Pull the server's own message out of an error body. Handles the routes' `RouteErrorBody`
 * `{code, message, errors: [{loc, msg, type}]}` (issue #25; field issues are appended because the 422 message
 * itself is generic), `errors.FaultlineError` `{code, message}`, and FastAPI's default `{detail}`.
 */
export function describeErrorBody(body: unknown): { message: string | null; code?: string } {
  if (!body || typeof body !== "object") return { message: null };
  const b = body as Record<string, unknown>;
  const code = typeof b.code === "string" ? b.code : undefined;
  const issues = describeIssues(b.errors);
  if (typeof b.message === "string" && b.message.trim()) {
    return { message: issues ? `${b.message}\n${issues}` : b.message, code };
  }
  if (issues) return { message: issues, code };
  const detail = b.detail;
  if (typeof detail === "string" && detail.trim()) return { message: detail, code };
  if (detail && typeof detail === "object" && !Array.isArray(detail)) {
    const inner = describeErrorBody(detail);
    if (inner.message) return { message: inner.message, code: inner.code ?? code };
  }
  const detailIssues = describeIssues(detail);
  if (detailIssues) return { message: detailIssues, code };
  return { message: null, code };
}

async function requestJson<T>(
  method: "GET" | "POST",
  path: string,
  timeoutMs: number,
  signal?: AbortSignal,
  body?: unknown,
): Promise<ApiResult<T>> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(new DOMException("timeout", "TimeoutError")), timeoutMs);
  const onAbort = () => controller.abort(signal?.reason);
  if (signal?.aborted) onAbort();
  signal?.addEventListener("abort", onAbort, { once: true });
  try {
    const res = await fetch(`${API_BASE}${path}`, {
      method,
      headers:
        body === undefined
          ? { Accept: "application/json" }
          : { Accept: "application/json", "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
      cache: "no-store",
      signal: controller.signal,
    });
    if (!res.ok) {
      let parsed: unknown = null;
      try {
        parsed = await res.json();
      } catch {
        parsed = null;
      }
      const { message, code } = describeErrorBody(parsed);
      return {
        ok: false,
        kind: res.status === 422 ? "validation" : "http",
        status: res.status,
        code,
        error: message ?? `HTTP ${res.status}`,
      };
    }
    try {
      return { ok: true, data: (await res.json()) as T };
    } catch {
      return { ok: false, kind: "malformed", status: res.status, error: "response was not JSON" };
    }
  } catch (err) {
    if (controller.signal.aborted) {
      const reason: unknown = controller.signal.reason;
      const timedOut = reason instanceof DOMException && reason.name === "TimeoutError";
      return timedOut
        ? { ok: false, kind: "timeout", error: "timed out" }
        : { ok: false, kind: "aborted", error: "aborted" };
    }
    return { ok: false, kind: "network", error: err instanceof Error ? err.message : "request failed" };
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", onAbort);
  }
}

/** GET /api/health. Never throws; an unreachable API is a normal, displayed state. */
export async function getHealth(signal?: AbortSignal): Promise<ApiResult<HealthSummary>> {
  const res = await requestJson<HealthResponse>("GET", "/api/health", 4000, signal);
  if (!res.ok) return res;
  if (!res.data || typeof res.data !== "object") return { ok: false, kind: "malformed", error: "malformed health payload" };
  return { ok: true, data: summarizeHealth(res.data) };
}

/**
 * Endpoints the screens need but that are not wired yet (SPEC §8 "Suggested API contract").
 * Panels reference these by key so the NOT AVAILABLE state names exactly what is missing.
 * No stub here returns data: there is nothing to return until the API serves it.
 * (`simulate` stays listed for the DECISION screen's ACT/WAIT/HEDGE branches, which are not wired to it yet.)
 */
export const PENDING_ENDPOINTS = {
  // REWIND / DECISION call GET /api/cases/{case_id}/evidence and POST /api/replay/run through lib/replay.ts.
  // `replayRun` stays for ThesisCourt, which is not wired to a run.
  replayRun: "POST /api/replay/run",
  reveal: "POST /api/replay/{prediction_id}/reveal",
  simulate: "POST /api/simulate",
  optimize: "POST /api/optimize",
  benchmark: "GET /api/benchmark",
} as const;

export type PendingEndpoint = keyof typeof PENDING_ENDPOINTS;

// ---------------------------------------------------------------------------------------------------------------
// POST /api/simulate and GET /api/scenarios (issue #25). Types mirror services/api/core/financials.py.
// The browser builds only the *inputs* (a ScenarioShock); every output figure is read from the response as-is.
// ---------------------------------------------------------------------------------------------------------------

/** core/financials.py `DemandShock`: m_t = 1-δ on [t1, t2], then linear recovery to 1 over ρ weeks. */
export interface DemandShock {
  /** δ, a fraction in [0, 1]. */
  delta: number;
  start_week: number;
  end_week: number;
  recovery_weeks?: number;
}

/** core/financials.py `RateShock`: r_t = r^base_t + Δr · 1[t >= t_r]. */
export interface RateShock {
  /** Δr, annual fraction (0.02 = +200 bp). */
  delta_rate: number;
  start_week: number;
}

/** core/financials.py `SupplierOutage`: κ_t availability (constant or length-T list) and dependent share φ. */
export interface SupplierOutage {
  availability: number | number[];
  dependent_share: number;
}

/** core/financials.py `ScenarioShock`. All shocks absent = baseline. */
export interface ScenarioShock {
  name?: string;
  demand?: DemandShock | null;
  rate?: RateShock | null;
  supplier?: SupplierOutage | null;
}

/** core/financials.py `ActionPlan`. Not sent by the cascade screen until the optimizer is wired (#17). */
export interface ActionPlan {
  use_backup_supplier?: boolean;
  defer_capex?: boolean;
  delay_expansion?: boolean;
  purchase_cut?: number | number[];
  revolver_draw?: number | number[];
  revolver_repay?: number | number[];
  payroll_cut?: number | number[];
}

/** POST /api/simulate request body (issue #25). */
export interface SimulateRequest {
  scenario_id?: string;
  shock: ScenarioShock;
  plan?: ActionPlan;
}

/** core/financials.py `SimulationResult`: per-week paths (index t-1 holds week t) plus the cash summary. */
export interface SimulationResult {
  provenance: string;
  scenario_name: string;
  horizon_weeks: number;
  weeks: number[];
  demand_multiplier: number[];
  supplier_availability: number[];
  lost_sales_fraction: number[];
  rate: number[];
  /** S^core_t = m_t Σ_ℓ S^base_{ℓ,t}: base-store demand (the outage and premium base, #38). */
  core_demand: number[];
  /** S^dem_t = S^core_t + (1-x_e) X_t: total demand (the Demand cascade node). */
  demand: number[];
  sales: number[];
  lost_sales: number[];
  receipts: number[];
  backup_premium: number[];
  purchases: number[];
  payables_paid: number[];
  inventory: number[];
  term_loan_principal: number[];
  interest: number[];
  amortization: number[];
  revolver_interest: number[];
  total_interest: number[];
  revolver_draw: number[];
  revolver_repay: number[];
  revolver_balance: number[];
  payroll: number[];
  opex: number[];
  capex: number[];
  expansion_outflow: number[];
  backup_fee: number[];
  cash_0: number;
  cash: number[];
  min_cash: number;
  /** First week attaining min_cash. */
  min_cash_week: number;
  ending_cash: number;
  /** First week with C_t < 0; null when cash never goes negative within the horizon ("> T weeks"). */
  runway_week: number | null;
  runway_label: string;
}

/** The twelve §5 cascade nodes, keyed exactly as core/financials.py `CASCADE_NODES`. */
export const CASCADE_NODE_NAMES = [
  "Demand",
  "Sales",
  "Receipts",
  "Supplier",
  "Inventory",
  "Purchases",
  "Payables",
  "Rate",
  "Interest",
  "Payroll",
  "Revolver",
  "Cash",
] as const;

export type CascadeNodeName = (typeof CASCADE_NODE_NAMES)[number];

/** core/financials.py `NodeDelta`: Δ_t = scenario_t - baseline_t for one node. */
export interface NodeDelta {
  /** SimulationResult field the node reads (e.g. "total_interest" for Interest). */
  field: string;
  per_week: number[];
  max_abs: number;
  at_end: number;
}

/** core/financials.py `CascadeDeltas`: output of `cascade_deltas(baseline, scenario)`. */
export interface CascadeDeltas {
  provenance: string;
  baseline_name: string;
  scenario_name: string;
  nodes: Record<string, NodeDelta>;
  /** Directed (source, target) pairs, `CASCADE_EDGES`. */
  edges: [string, string][];
  min_cash_delta: number;
  ending_cash_delta: number;
}

/** POST /api/simulate response (issue #25). */
export interface SimulateResponse {
  /** Wire label for the computed figures ("SIMULATED"). */
  provenance: string;
  /** Wire label for the business inputs ("SYNTHETIC": fictional demo business). */
  business_provenance: string;
  baseline: SimulationResult;
  result: SimulationResult;
  deltas: CascadeDeltas;
}

const isNum = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);
const isNumArray = (v: unknown, len: number): v is number[] =>
  Array.isArray(v) && v.length === len && v.every(isNum);

/** Shape check on the fields the cascade screen reads. Anything off → "malformed" → NOT AVAILABLE. */
function checkSimulation(v: unknown): string | null {
  if (!v || typeof v !== "object") return "simulation result missing";
  const r = v as Record<string, unknown>;
  if (!isNum(r.horizon_weeks) || r.horizon_weeks < 1) return "horizon_weeks missing";
  const T = r.horizon_weeks;
  for (const key of ["weeks", "cash", "demand", "sales", "rate", "supplier_availability"]) {
    if (!isNumArray(r[key], T)) return `${key} does not match horizon_weeks`;
  }
  if (!isNum(r.min_cash) || !isNum(r.min_cash_week) || !isNum(r.ending_cash)) return "cash summary missing";
  if (!(r.runway_week === null || isNum(r.runway_week))) return "runway_week malformed";
  if (typeof r.scenario_name !== "string" || typeof r.provenance !== "string") return "labels missing";
  return null;
}

function checkSimulateResponse(v: unknown): string | null {
  if (!v || typeof v !== "object") return "empty body";
  const r = v as Record<string, unknown>;
  if (typeof r.provenance !== "string" || typeof r.business_provenance !== "string") return "provenance labels missing";
  const problem = checkSimulation(r.baseline) ?? checkSimulation(r.result);
  if (problem) return problem;
  const T = (r.result as { horizon_weeks: number }).horizon_weeks;
  if ((r.baseline as { horizon_weeks: number }).horizon_weeks !== T) return "baseline and result horizons differ";
  const d = r.deltas as Record<string, unknown> | undefined;
  if (!d || typeof d !== "object" || !d.nodes || typeof d.nodes !== "object") return "deltas missing";
  if (!Array.isArray(d.edges)) return "deltas.edges missing";
  if (!isNum(d.min_cash_delta) || !isNum(d.ending_cash_delta)) return "deltas cash summary missing";
  for (const [name, node] of Object.entries(d.nodes as Record<string, unknown>)) {
    const n = node as Record<string, unknown> | null;
    if (!n || !isNumArray(n.per_week, T) || !isNum(n.max_abs) || !isNum(n.at_end)) {
      return `deltas.nodes.${name} malformed`;
    }
  }
  return null;
}

/**
 * POST /api/simulate. Never throws. A 422 carries the server's message (and `code`, e.g. INFEASIBLE_INPUT);
 * a 404 means this API build does not serve the route yet.
 */
export async function simulate(req: SimulateRequest, signal?: AbortSignal): Promise<ApiResult<SimulateResponse>> {
  const res = await requestJson<SimulateResponse>("POST", "/api/simulate", 8000, signal, req);
  if (!res.ok) return res;
  const problem = checkSimulateResponse(res.data);
  if (problem) return { ok: false, kind: "malformed", error: `malformed simulate payload: ${problem}` };
  return res;
}

/** One named stress scenario from `data/scenarios.json` (issue #19), as served by GET /api/scenarios. */
export interface ScenarioPreset {
  id: string;
  name: string;
  rationale: string | null;
  provenance: string | null;
  shock: ScenarioShock;
}

export interface ScenariosSummary {
  presets: ScenarioPreset[];
  /** Server note, e.g. "NOT AVAILABLE" while scenarios.json does not exist yet. */
  note: string | null;
}

/**
 * GET /api/scenarios body. The #25 route returns `{status: "AVAILABLE" | "NOT AVAILABLE", items, notes: string[]}`;
 * a bare array or `{scenarios: [...]}` is also accepted. Items without an id and a shock object are dropped,
 * not guessed at.
 */
export function readScenarios(raw: unknown): ScenariosSummary {
  let list: unknown[] = [];
  let note: string | null = null;
  if (Array.isArray(raw)) {
    list = raw;
  } else if (raw && typeof raw === "object") {
    const r = raw as Record<string, unknown>;
    list = Array.isArray(r.items) ? r.items : Array.isArray(r.scenarios) ? r.scenarios : [];
    const notes = Array.isArray(r.notes) ? r.notes.filter((n): n is string => typeof n === "string") : [];
    if (notes.length) note = notes.join(" ");
    else if (typeof r.note === "string") note = r.note;
    else if (typeof r.status === "string" && r.status !== "AVAILABLE") note = r.status;
  }
  const presets: ScenarioPreset[] = [];
  for (const item of list) {
    if (!item || typeof item !== "object") continue;
    const it = item as Record<string, unknown>;
    const id = typeof it.id === "string" ? it.id : typeof it.scenario_id === "string" ? it.scenario_id : null;
    const shock = it.shock && typeof it.shock === "object" ? (it.shock as ScenarioShock) : null;
    if (!id || !shock) continue;
    const name = typeof it.name === "string" ? it.name : typeof it.label === "string" ? it.label : (shock.name ?? id);
    const rationale =
      typeof it.rationale === "string" ? it.rationale : typeof it.description === "string" ? it.description : null;
    presets.push({ id, name, rationale, provenance: typeof it.provenance === "string" ? it.provenance : null, shock });
  }
  return { presets, note };
}

/** GET /api/scenarios. Never throws; a 404 (route not served yet) is a normal NOT AVAILABLE state. */
export async function getScenarios(signal?: AbortSignal): Promise<ApiResult<ScenariosSummary>> {
  const res = await requestJson<unknown>("GET", "/api/scenarios", 4000, signal);
  if (!res.ok) return res;
  return { ok: true, data: readScenarios(res.data) };
}
