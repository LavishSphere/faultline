/**
 * Shockwave sequencing for the CASCADE dependency network (#165). Pure display logic: it decides *when* a node lights
 * and *which* API value it shows, never *what* a value is. Every number passed through here is a field of a
 * POST /api/simulate or POST /api/optimize response.
 */

export interface PeakView {
  /** The per_week entry with the largest |Δ| (first one on ties), exactly as served. */
  peak: number;
  /** 0-based index into `per_week` of that entry. */
  peakIdx: number;
  maxAbs: number;
}

/** The peak entry of a node's Δ path, exactly as served; null for an empty path. */
export function peakOf(perWeek: readonly number[]): PeakView | null {
  if (perWeek.length === 0) return null;
  let peakIdx = 0;
  let peak = perWeek[0] ?? 0;
  let maxAbs = Math.abs(peak);
  perWeek.forEach((d, i) => {
    if (Math.abs(d) > maxAbs) {
      peakIdx = i;
      peak = d;
      maxAbs = Math.abs(d);
    }
  });
  return { peak, peakIdx, maxAbs };
}

/**
 * Dependency depth of each node: the longest path from a node with no incoming edge, over the edges the API serves
 * (core/financials.py `CASCADE_EDGES`). Demand → Sales → Receipts → Cash and Supplier → Purchases → Payables → Cash
 * come out in that order, so a pulse released level by level follows the dependencies. A cycle (not in the model)
 * cannot loop forever: depths are capped at the node count.
 */
export function dependencyLevels(nodes: readonly string[], edges: readonly (readonly [string, string])[]): Map<string, number> {
  const level = new Map<string, number>(nodes.map((n) => [n, 0]));
  const cap = nodes.length;
  for (let pass = 0; pass < cap; pass += 1) {
    let moved = false;
    for (const [s, t] of edges) {
      const ls = level.get(s);
      const lt = level.get(t);
      if (ls === undefined || lt === undefined) continue;
      if (lt < ls + 1 && ls + 1 <= cap) {
        level.set(t, ls + 1);
        moved = true;
      }
    }
    if (!moved) break;
  }
  return level;
}

/** Which recovery-plan action acts on which network node (MATH_MODEL §3–§4; the capex levers act on cash directly). */
export const ACTION_NODE: Readonly<Record<string, string>> = {
  purchase_cut: "Purchases",
  revolver_draw: "Revolver",
  revolver_repay: "Revolver",
  payroll_cut: "Payroll",
  use_backup_supplier: "Supplier",
  defer_capex: "Cash",
  delay_expansion: "Cash",
};

export interface PlanAction {
  action: string;
  week: number | null;
  amount: number | null;
  share: number | null;
}

/** The plan's actions grouped by the node they act on, in the API's order. Nothing is summed or derived. */
export function actionsByNode(actions: readonly PlanAction[]): Map<string, PlanAction[]> {
  const out = new Map<string, PlanAction[]>();
  for (const a of actions) {
    const node = ACTION_NODE[a.action];
    if (!node) continue;
    const list = out.get(node) ?? [];
    list.push(a);
    out.set(node, list);
  }
  return out;
}

/**
 * Count-up frame between two API values. `t` is the elapsed fraction; at t >= 1 the result is exactly `to`
 * (never an eased approximation), so the final frame always equals the API value.
 */
export function countFrame(from: number, to: number, t: number): number {
  if (t >= 1) return to;
  if (t <= 0) return from;
  const eased = 1 - Math.pow(1 - t, 3);
  return from + (to - from) * eased;
}
