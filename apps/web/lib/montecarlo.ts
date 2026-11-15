/**
 * Monte Carlo results from the chat's engine tools (#210): `monte_carlo_decision`, `monte_carlo_cash` and
 * `query_internal_data`. The server runs the simulation in Python and puts the full engine response in
 * `result_summary.monte_carlo` (internal data: `result_summary` itself).
 *
 * Honesty rules (AGENTS.md §4): nothing here computes a result. The readers only check shapes and copy fields; a field
 * that is missing or not a finite number becomes `null`, and the UI renders it NOT AVAILABLE. The only operations are
 * display ones: formatting, ordering rows by a served value, and scaling served counts to pixel heights.
 */
import type { ChatToolCall } from "./chat";

export const MC_DECISION_TOOL = "monte_carlo_decision";
export const MC_CASH_TOOL = "monte_carlo_cash";
export const INTERNAL_DATA_TOOL = "query_internal_data";

const isObj = (v: unknown): v is Record<string, unknown> => !!v && typeof v === "object" && !Array.isArray(v);
const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);
const str = (v: unknown): string | null => (typeof v === "string" && v.trim() ? v.trim() : null);
const bool = (v: unknown): boolean | null => (typeof v === "boolean" ? v : null);
const nums = (v: unknown, len?: number): number[] | null => {
  if (!Array.isArray(v) || v.length === 0) return null;
  if (len !== undefined && v.length !== len) return null;
  return v.every((x) => typeof x === "number" && Number.isFinite(x)) ? (v as number[]) : null;
};
const ci = (v: unknown): [number, number] | null => {
  const a = nums(v, 2);
  return a ? [a[0]!, a[1]!] : null;
};

export interface McSource {
  url: URL | null;
  title: string | null;
  note: string | null;
}

export interface McAssumption {
  optionId: string | null;
  name: string | null;
  kind: string | null;
  distribution: string | null;
  params: Record<string, unknown> | null;
  probability: number | null;
  source: McSource | null;
  /** Per-assumption provenance label, when the engine sends one (cash runs: ILLUSTRATIVE). */
  provenance: string | null;
}

export interface McRun {
  provenance: string | null;
  label: string | null;
  nPaths: number | null;
  seed: number | string | null;
  inputSha256: string | null;
  runtimeMs: number | null;
}

export interface McOption {
  id: string;
  label: string | null;
  mean: number | null;
  sd: number | null;
  p5: number | null;
  p25: number | null;
  p50: number | null;
  p75: number | null;
  p95: number | null;
  probBelowZero: number | null;
  /** Share of paths where this option is best (ties split evenly; the served shares sum to 1), and its Wilson 95% CI. */
  probBest: number | null;
  probBestCi95: [number, number] | null;
  /** Downside: mean metric over this option's worst 5% of paths (CVaR 5%, MATH_MODEL §11.1), as served. */
  expectedShortfall5: number | null;
  /** Bin counts as served; null when missing or not one shorter than the shared edges. */
  counts: number[] | null;
}

export interface McPairwise {
  a: string;
  b: string;
  probABetter: number | null;
  ci95: [number, number] | null;
}

export interface McSensitivity {
  optionId: string | null;
  driver: string | null;
  lowP50: number | null;
  highP50: number | null;
  swing: number | null;
}

export interface McDecision extends McRun {
  question: string | null;
  metric: { name: string | null; unit: string | null; higherIsBetter: boolean | null };
  options: McOption[];
  /** The shared histogram edges (first option's), or null when any option's edges differ. */
  binEdges: number[] | null;
  pairwise: McPairwise[];
  best: { id: string | null; probBest: number | null; ci95: [number, number] | null } | null;
  sensitivity: McSensitivity[];
  assumptions: McAssumption[];
}

export interface McCashSide {
  bands: { p5: number[]; p25: number[]; p50: number[]; p75: number[]; p95: number[] } | null;
  probBelowFloorAny: number | null;
  probBelowFloorCi95: [number, number] | null;
  probNegativeAny: number | null;
  probBelowFloorByWeek: number[] | null;
  minCash: { p5: number | null; p50: number | null; p95: number | null } | null;
}

export interface McCash extends McRun {
  synthetic: boolean | null;
  weeks: number | null;
  floor: number | null;
  noPlan: McCashSide | null;
  withPlan: McCashSide | null;
  plan: McPlan | null;
  assumptions: McAssumption[];
  notes: string[];
}

export interface McPlanAction {
  action: string | null;
  week: number | null;
  amount: number | null;
  share: number | null;
}

/** The recovery plan the with-plan run applied: one /api/optimize solve on the central shock. */
export interface McPlan {
  status: string | null;
  actions: McPlanAction[] | null;
  centralMinCash: number | null;
  /** A string or a structured diagnostic, shown as served. */
  diagnostic: unknown;
}

export interface InternalData {
  provenance: string | null;
  table: string | null;
  columns: string[];
  rows: Record<string, unknown>[];
  aggregate: Record<string, unknown> | null;
}

/** http(s) only: any other scheme (javascript:, data:) is dropped, so the link is never rendered. */
export function safeUrl(v: unknown): URL | null {
  const s = str(v);
  if (!s) return null;
  try {
    const u = new URL(s);
    return u.protocol === "https:" || u.protocol === "http:" ? u : null;
  } catch {
    return null;
  }
}

function runOf(m: Record<string, unknown>): McRun {
  const seed = num(m.seed) ?? str(m.seed);
  return {
    provenance: str(m.provenance),
    label: str(m.label),
    nPaths: num(m.n_paths),
    seed,
    inputSha256: str(m.input_sha256),
    runtimeMs: num(m.runtime_ms),
  };
}

function assumptionsOf(v: unknown): McAssumption[] {
  if (!Array.isArray(v)) return [];
  return v.filter(isObj).map((a) => {
    const s = isObj(a.source) ? a.source : null;
    return {
      optionId: str(a.option_id),
      name: str(a.name),
      kind: str(a.kind),
      distribution: str(a.distribution),
      params: isObj(a.params) ? a.params : null,
      probability: num(a.probability),
      source: s ? { url: safeUrl(s.url), title: str(s.title), note: str(s.note) } : null,
      provenance: str(a.provenance),
    };
  });
}

/** The engine response of a tool call (`result_summary.monte_carlo`), or null. */
function mcOf(call: ChatToolCall): Record<string, unknown> | null {
  const s = call.result_summary;
  return isObj(s) && isObj(s.monte_carlo) ? s.monte_carlo : null;
}

/** Read a decision Monte Carlo. Null when the body is not a decision run (no options list). */
export function readDecision(call: ChatToolCall): McDecision | null {
  const m = mcOf(call);
  if (!m || !Array.isArray(m.options)) return null;
  const metric = isObj(m.metric) ? m.metric : {};
  let binEdges: number[] | null = null;
  let edgesAgree = true;
  const options: McOption[] = m.options.filter(isObj).flatMap((o) => {
    const id = str(o.id);
    if (!id) return [];
    const h = isObj(o.histogram) ? o.histogram : null;
    const edges = h ? nums(h.bin_edges) : null;
    let counts = h ? nums(h.counts) : null;
    if (edges) {
      if (!binEdges) binEdges = edges;
      else if (edges.length !== binEdges.length || edges.some((e, i) => e !== binEdges![i])) edgesAgree = false;
    }
    if (counts && (!edges || counts.length !== edges.length - 1 || counts.some((c) => c < 0))) counts = null;
    return [
      {
        id,
        label: str(o.label),
        mean: num(o.mean),
        sd: num(o.sd),
        p5: num(o.p5),
        p25: num(o.p25),
        p50: num(o.p50),
        p75: num(o.p75),
        p95: num(o.p95),
        probBelowZero: num(o.prob_below_zero),
        probBest: num(o.prob_best),
        probBestCi95: ci(o.prob_best_ci95),
        expectedShortfall5: num(o.expected_shortfall_5),
        counts,
      },
    ];
  });
  const best = isObj(m.best) ? { id: str(m.best.id), probBest: num(m.best.prob_best), ci95: ci(m.best.ci95) } : null;
  const pairwise = (Array.isArray(m.pairwise) ? m.pairwise : []).filter(isObj).flatMap((p) => {
    const a = str(p.a);
    const b = str(p.b);
    return a && b ? [{ a, b, probABetter: num(p.prob_a_better), ci95: ci(p.ci95) }] : [];
  });
  const sensitivity = (Array.isArray(m.sensitivity) ? m.sensitivity : []).filter(isObj).map((s) => ({
    optionId: str(s.option_id),
    driver: str(s.driver),
    lowP50: num(s.low_p50),
    highP50: num(s.high_p50),
    swing: num(s.swing),
  }));
  return {
    ...runOf(m),
    question: str(m.question),
    metric: { name: str(metric.name), unit: str(metric.unit), higherIsBetter: bool(metric.higher_is_better) },
    options,
    binEdges: edgesAgree ? binEdges : null,
    pairwise,
    best,
    sensitivity,
    assumptions: assumptionsOf(m.assumptions),
  };
}

function sideOf(v: unknown, weeks: number | null): McCashSide | null {
  if (!isObj(v)) return null;
  const len = weeks ?? undefined;
  const b = isObj(v.bands) ? v.bands : null;
  const p5 = b ? nums(b.p5, len) : null;
  const p25 = b ? nums(b.p25, len) : null;
  const p50 = b ? nums(b.p50, len) : null;
  const p75 = b ? nums(b.p75, len) : null;
  const p95 = b ? nums(b.p95, len) : null;
  const sameLen = p5 && p25 && p50 && p75 && p95 && [p25, p50, p75, p95].every((a) => a.length === p5.length);
  const mc = isObj(v.min_cash) ? v.min_cash : null;
  return {
    bands: sameLen ? { p5: p5!, p25: p25!, p50: p50!, p75: p75!, p95: p95! } : null,
    probBelowFloorAny: num(v.prob_below_floor_any),
    probBelowFloorCi95: ci(v.prob_below_floor_ci95),
    probNegativeAny: num(v.prob_negative_any),
    probBelowFloorByWeek: nums(v.prob_below_floor_by_week, len),
    minCash: mc ? { p5: num(mc.p5), p50: num(mc.p50), p95: num(mc.p95) } : null,
  };
}

/** Read a cash Monte Carlo. Null when the body is not a cash run (no `no_plan` side). */
export function readCash(call: ChatToolCall): McCash | null {
  const m = mcOf(call);
  if (!m || !isObj(m.no_plan)) return null;
  const weeks = num(m.weeks);
  return {
    ...runOf(m),
    synthetic: bool(m.synthetic),
    weeks,
    floor: num(m.floor),
    noPlan: sideOf(m.no_plan, weeks),
    withPlan: sideOf(m.with_plan, weeks),
    plan: isObj(m.plan) ? planOf(m.plan) : null,
    assumptions: assumptionsOf(m.assumptions),
    notes: Array.isArray(m.notes) ? m.notes.filter((n): n is string => typeof n === "string" && !!n.trim()) : [],
  };
}

function planOf(p: Record<string, unknown>): McPlan {
  return {
    status: str(p.status),
    actions: Array.isArray(p.actions)
      ? p.actions.filter(isObj).map((a) => ({ action: str(a.action), week: num(a.week), amount: num(a.amount), share: num(a.share) }))
      : null,
    centralMinCash: num(p.central_min_cash),
    diagnostic: p.diagnostic ?? null,
  };
}

/** Read a query_internal_data result. Null when there is no rows list. */
export function readInternalData(call: ChatToolCall): InternalData | null {
  const s = call.result_summary;
  if (!isObj(s) || !Array.isArray(s.rows)) return null;
  const rows = s.rows.filter(isObj);
  const served = Array.isArray(s.columns) ? s.columns.filter((c): c is string => typeof c === "string") : [];
  const columns = served.length ? served : rows[0] ? Object.keys(rows[0]) : [];
  return { provenance: str(s.provenance), table: str(s.table), columns, rows, aggregate: isObj(s.aggregate) ? s.aggregate : null };
}

/** The ok Monte Carlo / internal-data calls of one reply, in the order they ran. */
export function monteCarloCalls(calls: readonly ChatToolCall[]): ChatToolCall[] {
  return calls.filter(
    (c) => c.result_status === "ok" && (c.name === MC_DECISION_TOOL || c.name === MC_CASH_TOOL || c.name === INTERNAL_DATA_TOOL),
  );
}

/** Assumptions grouped by `option_id` in first-seen order; rows without one form a shared group (key null) first. */
export function groupAssumptions(rows: readonly McAssumption[]): { optionId: string | null; rows: McAssumption[] }[] {
  const groups = new Map<string | null, McAssumption[]>();
  if (rows.some((r) => r.optionId === null)) groups.set(null, []);
  for (const r of rows) {
    const g = groups.get(r.optionId);
    if (g) g.push(r);
    else groups.set(r.optionId, [r]);
  }
  return [...groups].map(([optionId, rs]) => ({ optionId, rows: rs }));
}

/** Sensitivity rows sorted by served swing, largest first; rows without a swing go last in served order. Display only. */
export function tornadoRows(rows: readonly McSensitivity[]): McSensitivity[] {
  return rows
    .map((r, i) => ({ r, i }))
    .sort((x, y) => {
      if (x.r.swing === null && y.r.swing === null) return x.i - y.i;
      if (x.r.swing === null) return 1;
      if (y.r.swing === null) return -1;
      return Math.abs(y.r.swing) - Math.abs(x.r.swing) || x.i - y.i;
    })
    .map((x) => x.r);
}

// ---- formatting (display only) -------------------------------------------------------------------------------------

/** A probability in [0, 1] as a percentage to one decimal: 0.7834 → "78.3%". Null or out of range → null. */
export function pct(p: number | null): string | null {
  if (p === null || p < 0 || p > 1) return null;
  return `${(p * 100).toFixed(1)}%`;
}

/** "95% CI 77.7–78.9%" from a served interval; null when it is missing or out of range. */
export function ciLabel(c: [number, number] | null): string | null {
  if (!c) return null;
  const lo = pct(c[0]);
  const hi = pct(c[1]);
  return lo && hi ? `95% CI ${lo.slice(0, -1)}–${hi}` : null;
}

const INT = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });
export const count = (n: number | null): string | null => (n === null ? null : INT.format(n));

const isMoney = (unit: string | null) => !!unit && /^(usd|\$|dollars?)$/i.test(unit);
/** "USD bn" / "USD m" / "USD k": dollars in a served scale, shown as "$606.7bn". */
const SCALED_USD = /^(?:usd|\$)\s*(bn|b|m|mn|k)$/i;
const SIG = new Intl.NumberFormat("en-US", { maximumSignificantDigits: 4 });
const COMPACT_USD = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", notation: "compact", maximumFractionDigits: 2 });
const FULL_USD = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
const COMPACT = new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 2 });
const PLAIN = new Intl.NumberFormat("en-US", { maximumFractionDigits: 3 });

/** A metric value in its unit, compact ("$1.24M", "12.5 %"); null → null. `full` gives the unrounded-to-compact form. */
export function metricValue(v: number | null, unit: string | null, full = false): string | null {
  if (v === null) return null;
  if (isMoney(unit)) return (full ? FULL_USD : COMPACT_USD).format(v);
  const scaled = unit ? SCALED_USD.exec(unit) : null;
  if (scaled) return `${v < 0 ? "−" : ""}$${(full ? PLAIN : SIG).format(Math.abs(v))}${scaled[1]!.toLowerCase()}`;
  const n = full || Math.abs(v) < 10_000 ? PLAIN.format(v) : COMPACT.format(v);
  if (!unit) return n;
  return unit === "%" ? `${n}%` : `${n} ${unit}`;
}

/** Cash in dollars, compact for chart axes and tiles: "$1.2M". */
export const cash = (v: number | null, full = false): string | null =>
  v === null ? null : (full ? FULL_USD : COMPACT_USD).format(v);

/** The first 12 hex characters of a SHA-256 for display; the full hash is copied. */
export const shortSha = (h: string | null): string | null => (h ? h.slice(0, 12) : null);

const PARAM = new Intl.NumberFormat("en-US", { maximumFractionDigits: 4, useGrouping: false });

/** Assumption params as "key=value" pairs; numbers to at most 4 decimals (0.30000000000000004 → 0.3). */
export function paramsLabel(p: Record<string, unknown> | null): string | null {
  if (!p) return null;
  const parts = Object.entries(p).map(
    ([k, v]) => `${k}=${typeof v === "number" ? PARAM.format(v) : typeof v === "object" ? JSON.stringify(v) : String(v)}`,
  );
  return parts.length ? parts.join(", ") : null;
}

/** A table cell exactly as served: numbers with grouping, objects as JSON, null/undefined → null. */
export function cell(v: unknown): string | null {
  if (v === null || v === undefined) return null;
  if (typeof v === "number") return Number.isFinite(v) ? v.toLocaleString("en-US", { maximumFractionDigits: 4 }) : null;
  if (typeof v === "string") return v;
  if (typeof v === "boolean") return String(v);
  return JSON.stringify(v);
}
