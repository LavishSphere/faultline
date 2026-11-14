/**
 * FAULTLINE API client.
 *
 * Rules (AGENTS.md §4, cascade-ui skill):
 * - The browser never computes authoritative numbers. Every figure shown comes from a response here.
 * - Anything not yet served by the API is listed in PENDING_ENDPOINTS and renders NOT AVAILABLE.
 *
 * Wired: `/api/health`, `POST /api/simulate`, `GET /api/scenarios` (contract: issue #25) and `POST /api/optimize` (#47).
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

/**
 * Raw `/api/health` payload: `models.HealthResponse` (services/api/routes/health.py). Fields stay optional so an
 * older or partial build is read tolerantly; nothing missing is filled in.
 */
export interface HealthResponse {
  status?: string;
  /** Ollama reachable at OLLAMA_BASE_URL (a boolean in models.HealthResponse; an object in early drafts). */
  ollama?: boolean | { reachable?: boolean; models?: string[] };
  /** Ollama reachable AND the configured replay model is installed: the authoritative readiness flag. */
  model_ready?: boolean;
  ollama_status?: {
    reachable?: boolean;
    models?: string[];
    required_model?: string;
    required_model_present?: boolean;
    error?: string | null;
  };
  notices?: string[];
  models?: string[];
  ollama_models?: string[];
  [key: string]: unknown;
}

export type ModelAvailability = "available" | "unavailable" | "unknown";

/** What the UI actually needs from `/api/health`. Derived only from fields the API returned. */
export interface HealthSummary {
  status: string | null;
  model: ModelAvailability;
  /** Every model tag installed in Ollama, as listed. */
  modelTags: string[];
  /** The replay model the API is configured to run (`ollama_status.required_model`); null when not reported. */
  requiredModel: string | null;
  /** The Ollama probe's own error text, when it sent one. */
  modelError: string | null;
  checkedAt: Date;
}

function asStringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((v): v is string => typeof v === "string") : [];
}

/**
 * Readiness comes from `model_ready` whenever the API sends it (#163). This used to read only `ollama` and a
 * top-level model list; `models.HealthResponse` nests the list under `ollama_status`, so with `ollama: true` the
 * list looked empty and a ready model was reported as "Local model unavailable".
 */
export function summarizeHealth(raw: HealthResponse, checkedAt: Date = new Date()): HealthSummary {
  let reachable: boolean | undefined;
  let tags: string[] = [];
  const st = raw.ollama_status && typeof raw.ollama_status === "object" ? raw.ollama_status : null;

  if (typeof raw.ollama === "boolean") {
    reachable = raw.ollama;
  } else if (raw.ollama && typeof raw.ollama === "object") {
    if (typeof raw.ollama.reachable === "boolean") reachable = raw.ollama.reachable;
    tags = asStringArray(raw.ollama.models);
  }
  if (reachable === undefined && typeof st?.reachable === "boolean") reachable = st.reachable;
  if (tags.length === 0) tags = asStringArray(st?.models);
  if (tags.length === 0) tags = asStringArray(raw.ollama_models);
  if (tags.length === 0) tags = asStringArray(raw.models);

  let model: ModelAvailability = "unknown";
  if (typeof raw.model_ready === "boolean") model = raw.model_ready ? "available" : "unavailable";
  else if (typeof st?.required_model_present === "boolean") model = st.required_model_present ? "available" : "unavailable";
  else if (reachable === false) model = "unavailable";
  else if (reachable === true) model = tags.length > 0 ? "available" : "unavailable";

  return {
    status: typeof raw.status === "string" ? raw.status : null,
    model,
    modelTags: tags,
    requiredModel: typeof st?.required_model === "string" && st.required_model ? st.required_model : null,
    modelError: typeof st?.error === "string" && st.error ? st.error : null,
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

export async function requestJson<T>(
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

/** core/financials.py `ActionPlan`. The cascade screen sends only a plan /api/optimize returned ("Apply plan", #56). */
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
  /**
   * The business's liquidity floor C_min (MATH_MODEL §4.1, §10), read from the fixture; null when it sets none.
   * Optional: an older API build does not send it, and the floor line then reads NOT AVAILABLE.
   */
  min_cash_floor?: number | null;
  /** First week of `result` with C_t < C_min, computed server-side; null if cash never falls below it. */
  first_week_below_floor?: number | null;
  /** Every week of `result` with C_t < C_min, ascending, computed server-side; empty if none. */
  weeks_below_floor?: number[];
}

/** The simulate response's floor fields, or null when this API build does not send them (NOT AVAILABLE). */
export function floorOf(
  r: SimulateResponse,
): { floor: number; firstBelow: number | null; weeksBelow: number[] } | null {
  if (r.min_cash_floor === undefined || r.min_cash_floor === null || r.weeks_below_floor === undefined) return null;
  return { floor: r.min_cash_floor, firstBelow: r.first_week_below_floor ?? null, weeksBelow: r.weeks_below_floor };
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
  if (!(r.min_cash_floor === undefined || r.min_cash_floor === null || isNum(r.min_cash_floor))) return "min_cash_floor malformed";
  const first = r.first_week_below_floor;
  if (!(first === undefined || first === null || isNum(first))) return "first_week_below_floor malformed";
  const below = r.weeks_below_floor;
  if (!(below === undefined || (Array.isArray(below) && below.every(isNum)))) return "weeks_below_floor malformed";
  if (Array.isArray(below) && (below[0] ?? null) !== (first ?? null)) {
    return "first_week_below_floor does not match weeks_below_floor";
  }
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

// ---------------------------------------------------------------------------------------------------------------
// POST /api/optimize (issues #47, #56). Types mirror services/api/core/optimizer.py `OptimizationResult`.
// Every figure is the solver's; the browser formats it and never computes a plan, a cash path or a floor.
// ---------------------------------------------------------------------------------------------------------------

/** POST /api/optimize request body: the same shock model as /api/simulate, plus the payroll-protection switch. */
export interface OptimizeRequest {
  scenario_id?: string;
  shock: ScenarioShock;
  protect_payroll: boolean;
}

export type OptimizeStatus = "OPTIMAL" | "NO FEASIBLE PLAN" | "SOLVER ERROR";

/** core/optimizer.py `ChosenAction`. `week`/`amount` are null for the yes/no decisions. */
export interface ChosenAction {
  action: string;
  week: number | null;
  /** Dollars; for payroll_cut, the dollars not paid (z_t W_t). */
  amount: number | null;
  /** payroll_cut only: the share z_t. */
  share: number | null;
}

/** POST /api/optimize response. For NO FEASIBLE PLAN / SOLVER ERROR every plan field is null (nothing invented). */
export interface OptimizeResponse {
  provenance: string;
  business_provenance: string;
  status: OptimizeStatus;
  solver_message: string;
  scenario_name: string;
  protect_payroll: boolean;
  plan: ActionPlan | null;
  actions: ChosenAction[] | null;
  cash: number[] | null;
  revolver_balance: number[] | null;
  inventory: number[] | null;
  min_cash: number | null;
  min_cash_week: number | null;
  binding_constraints: string[] | null;
  objective: number | null;
  disruption_cost: number | null;
  /** NO FEASIBLE PLAN: the highest minimum cash any plan can reach (the floor would have to be lowered to this). */
  max_feasible_cash_floor: number | null;
  diagnostic: string | null;
  /** z̄, the configured payroll-cut cap per week (MATH_MODEL §4, §10); optional for older API builds (#157). */
  payroll_cut_cap?: number;
  /** L_p, the supplier payment lag in weeks (MATH_MODEL §3, §10); optional for older API builds (#157). */
  supplier_lag_weeks?: number;
}

const OPTIMIZE_STATUSES = new Set<string>(["OPTIMAL", "NO FEASIBLE PLAN", "SOLVER ERROR"]);

function checkOptimizeResponse(v: unknown): string | null {
  if (!v || typeof v !== "object") return "empty body";
  const r = v as Record<string, unknown>;
  if (typeof r.provenance !== "string" || typeof r.business_provenance !== "string") return "provenance labels missing";
  if (typeof r.status !== "string" || !OPTIMIZE_STATUSES.has(r.status)) return "unknown status";
  if (typeof r.solver_message !== "string") return "solver_message missing";
  if (r.status === "OPTIMAL") {
    if (!r.plan || typeof r.plan !== "object") return "plan missing";
    if (!Array.isArray(r.actions) || !Array.isArray(r.binding_constraints)) return "actions or binding constraints missing";
    if (!Array.isArray(r.cash) || !r.cash.every(isNum)) return "cash path missing";
    if (!isNum(r.min_cash) || !isNum(r.min_cash_week) || !isNum(r.objective)) return "min cash or objective missing";
  }
  if (r.status === "NO FEASIBLE PLAN" && !(r.max_feasible_cash_floor === null || isNum(r.max_feasible_cash_floor))) {
    return "max_feasible_cash_floor malformed";
  }
  if (!(r.payroll_cut_cap === undefined || isNum(r.payroll_cut_cap))) return "payroll_cut_cap malformed";
  if (!(r.supplier_lag_weeks === undefined || isNum(r.supplier_lag_weeks))) return "supplier_lag_weeks malformed";
  return null;
}

/**
 * POST /api/optimize. Never throws. NO FEASIBLE PLAN and SOLVER ERROR are 200 answers (the `status` field), not
 * failures; a 422 carries the server's coded message like /api/simulate.
 */
export async function optimize(req: OptimizeRequest, signal?: AbortSignal): Promise<ApiResult<OptimizeResponse>> {
  const res = await requestJson<OptimizeResponse>("POST", "/api/optimize", 15000, signal, req);
  if (!res.ok) return res;
  const problem = checkOptimizeResponse(res.data);
  if (problem) return { ok: false, kind: "malformed", error: `malformed optimize payload: ${problem}` };
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
