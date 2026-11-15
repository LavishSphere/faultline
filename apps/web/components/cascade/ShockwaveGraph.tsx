"use client";

import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import {
  Background,
  BackgroundVariant,
  BaseEdge,
  Handle,
  MarkerType,
  Position,
  ReactFlow,
  getBezierPath,
  type Edge,
  type EdgeProps,
  type Node,
  type NodeChange,
  type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/base.css";
import "./cascade-fx.css";
import { floorOf, type CascadeNodeName, type NodeDelta, type SimulateResponse, type SimulationResult } from "@/lib/api";
import { usd, weekRanges } from "@/lib/format";
import { formatDelta, usePrefersReducedMotion } from "../CascadeGraph";
import { actionsByNode, countFrame, dependencyLevels, peakOf, type PlanAction } from "./shockwave";

/**
 * CASCADE dependency network with the shockwave (#165). Same nodes, edges and Δ semantics as `CascadeGraph`
 * (MATH_MODEL §5: Δ = scenario − baseline at each node's peak week, read from `deltas.nodes`), plus motion:
 *
 * - When a POST /api/simulate response lands, a pulse is released along the API's `deltas.edges` in dependency order
 *   (`dependencyLevels`). Each node whose value changed lights when the pulse reaches it and counts from its value in
 *   the previous response to its value in this one; the last frame is exactly the new API value. Before the pulse
 *   arrives a node keeps showing the previous response's value, never an invented one.
 * - The Cash node and its callout turn red when the API reports `first_week_below_floor`.
 * - Protect payroll wraps the Payroll node in a shield (the switch is an input, so this is shown at once).
 * - A recovery plan from POST /api/optimize (only an answer to the current inputs) is drawn on the nodes it acts on,
 *   with the API's per-week amounts; nothing is summed in the browser.
 *
 * prefers-reduced-motion: no pulse, no count-up; the final state renders immediately.
 */

type NodeRole = "shock" | "flow" | "constraint" | "sink";
type DeltaUnit = "usd" | "bp" | "pp";

/** Delay between dependency levels, and the count-up length once a node is reached. */
const STEP_MS = 260;
const COUNT_MS = 560;
/** Extra lead before the pulse while the incoming-shock card is on screen. */
const INCOMING_LEAD_MS = 650;

interface NodeView {
  peak: number;
  peakWeek: number;
  atEnd: number;
  maxAbs: number;
  emphasis: number;
}

type View = NodeView | null | undefined;

interface FloorView {
  floor: number;
  firstBelow: number | null;
  weeksBelow: number[];
}

interface Snapshot {
  views: Map<string, View>;
  /** undefined = no response; null = this API build does not report the floor. */
  floor: FloorView | null | undefined;
}

export interface GraphPlan {
  actions: PlanAction[];
  /** The plan is applied: the node values are POST /api/simulate with this plan. */
  applied: boolean;
}

interface WaveHit {
  id: number;
  delay: number;
}

interface CascadeNodeData extends Record<string, unknown> {
  label: CascadeNodeName;
  symbol: string;
  role: NodeRole;
  unit: DeltaUnit;
  view: View;
  prev: View;
  floor: FloorView | null | undefined;
  hit: WaveHit | null;
  reduce: boolean;
  shield: boolean;
  plan: { items: PlanAction[]; applied: boolean; place: "above" | "below" } | null;
}

type CascadeNode = Node<CascadeNodeData, "cascade">;

interface PulseEdgeData extends Record<string, unknown> {
  emphasis: number;
  pulse: { id: number; delay: number; dur: number } | null;
  plan: boolean;
  reduce: boolean;
}

type PulseEdge = Edge<PulseEdgeData, "pulse">;

const NODE_SPECS: { id: CascadeNodeName; symbol: string; role: NodeRole; unit: DeltaUnit; x: number; y: number }[] = [
  { id: "Demand", symbol: "S^dem_t", role: "shock", unit: "usd", x: 0, y: 40 },
  { id: "Supplier", symbol: "κ_t", role: "shock", unit: "pp", x: 0, y: 250 },
  { id: "Rate", symbol: "r_t", role: "shock", unit: "bp", x: 0, y: 440 },
  { id: "Sales", symbol: "S_t", role: "flow", unit: "usd", x: 240, y: 140 },
  { id: "Revolver", symbol: "B_t", role: "constraint", unit: "usd", x: 240, y: 540 },
  { id: "Receipts", symbol: "R_t", role: "flow", unit: "usd", x: 480, y: 20 },
  { id: "Purchases", symbol: "P_t", role: "flow", unit: "usd", x: 480, y: 250 },
  { id: "Interest", symbol: "J_t + Jᴿ_t", role: "flow", unit: "usd", x: 480, y: 440 },
  { id: "Inventory", symbol: "I_t", role: "constraint", unit: "usd", x: 720, y: 120 },
  { id: "Payables", symbol: "P_{t−Lp}", role: "flow", unit: "usd", x: 720, y: 300 },
  { id: "Payroll", symbol: "(1−z_t)W_t", role: "flow", unit: "usd", x: 720, y: 540 },
  { id: "Cash", symbol: "C_t", role: "sink", unit: "usd", x: 960, y: 290 },
];

/** Where a node's plan chip sits, so it never covers a neighbour (bottom-row nodes put it above). */
const PLAN_PLACE: Partial<Record<CascadeNodeName, "above" | "below">> = { Payroll: "above", Revolver: "above", Purchases: "above" };

/** Structure before the first response; mirrors core/financials.py `CASCADE_EDGES` (the API's list is used after). */
const STATIC_EDGES: [CascadeNodeName, CascadeNodeName][] = [
  ["Demand", "Sales"],
  ["Supplier", "Sales"],
  ["Supplier", "Purchases"],
  ["Demand", "Purchases"],
  ["Sales", "Receipts"],
  ["Sales", "Purchases"],
  ["Purchases", "Inventory"],
  ["Purchases", "Payables"],
  ["Rate", "Interest"],
  ["Revolver", "Interest"],
  ["Receipts", "Cash"],
  ["Payables", "Cash"],
  ["Interest", "Cash"],
  ["Payroll", "Cash"],
  ["Revolver", "Cash"],
];

const RELATIONS: Record<string, string> = {
  "Demand->Sales": "m_t scales baseline demand",
  "Supplier->Sales": "outage → lost sales λ_t",
  "Supplier->Purchases": "backup premium π on λ_t",
  "Demand->Purchases": "backup premium π(1−g)S^core_t λ_t",
  "Sales->Receipts": "collection timing a",
  "Sales->Purchases": "replenish COGS (1−g)S_t",
  "Purchases->Inventory": "I_t = I_{t−1} − v_t",
  "Purchases->Payables": "supplier lag L_p",
  "Rate->Interest": "r_t on term loan + revolver",
  "Revolver->Interest": "revolver balance B_{t−1}",
  "Receipts->Cash": "+ R_t",
  "Payables->Cash": "− P_{t−Lp}",
  "Interest->Cash": "− J_t − Jᴿ_t",
  "Payroll->Cash": "− (1−z_t)W_t",
  "Revolver->Cash": "+ y_t − q_t",
};

const ROLE_STYLE: Record<NodeRole, { border: string; tag: string; tagText: string }> = {
  shock: { border: "border-risk/60", tag: "text-risk", tagText: "Shock input" },
  flow: { border: "border-line-strong", tag: "text-muted", tagText: "Flow" },
  constraint: { border: "border-line-strong border-dashed", tag: "text-muted", tagText: "Constraint" },
  sink: { border: "border-accent/70", tag: "text-accent-hover", tagText: "Balance" },
};

const ACTION_SHORT: Record<string, string> = {
  purchase_cut: "Purchase cut",
  revolver_draw: "Revolver draw",
  revolver_repay: "Revolver repay",
  payroll_cut: "Payroll cut",
  use_backup_supplier: "Backup supplier",
  defer_capex: "Defer capex",
  delay_expansion: "Delay expansion",
};

/** Display scaling only (same rule as CascadeGraph): |Δ| relative to the node's own range in this response. */
function emphasis(delta: NodeDelta, baseline: SimulationResult, result: SimulationResult): number {
  if (delta.max_abs === 0) return 0;
  const b = (baseline as unknown as Record<string, unknown>)[delta.field];
  const r = (result as unknown as Record<string, unknown>)[delta.field];
  let scale = 0;
  for (const path of [b, r]) {
    if (Array.isArray(path)) for (const v of path) if (typeof v === "number") scale = Math.max(scale, Math.abs(v));
  }
  if (scale === 0) return 1;
  return Math.min(1, delta.max_abs / scale);
}

function viewFor(delta: NodeDelta | undefined, baseline: SimulationResult, result: SimulationResult): NodeView | null {
  if (!delta) return null;
  const p = peakOf(delta.per_week);
  if (!p) return null;
  const peakWeek = result.weeks[p.peakIdx];
  if (peakWeek === undefined) return null;
  return { peak: p.peak, peakWeek, atEnd: delta.at_end, maxAbs: delta.max_abs, emphasis: emphasis(delta, baseline, result) };
}

/** What the node displays, as a string: a node is "hit" by the pulse only when this changes. */
function viewKey(v: View, unit: DeltaUnit): string {
  if (v === undefined) return "u";
  if (v === null) return "n";
  if (v.maxAbs === 0) return "0";
  return `${formatDelta(v.peak, unit)}@${v.peakWeek}`;
}

function floorKey(f: FloorView | null | undefined): string {
  if (f === undefined) return "u";
  if (f === null) return "n";
  return `${f.floor}:${f.firstBelow ?? "-"}`;
}

function describeView(label: string, unit: DeltaUnit, view: View): string {
  if (view === undefined) return `${label}: no value (structure only)`;
  if (view === null) return `${label}: Δ not available in the response`;
  if (view.maxAbs === 0) return `${label}: no change versus baseline`;
  return `${label}: peak Δ ${formatDelta(view.peak, unit)} in week ${view.peakWeek}, Δ at end ${formatDelta(view.atEnd, unit)}`;
}

/**
 * Wave timing for one node. Without a hit (or under reduced motion) the final API value is returned at once.
 * With one, the previous response's value is held until the pulse arrives, then counts to the new value; the last
 * frame is exactly `target` (`countFrame` returns `to` at t >= 1).
 */
function useWave(hit: WaveHit | null, reduce: boolean, from: number | null, target: number | null) {
  const [tick, setTick] = useState<{ id: number; value: number | null; done: boolean } | null>(null);
  const id = hit?.id ?? null;
  const delay = hit?.delay ?? 0;
  useEffect(() => {
    if (id === null || reduce) return;
    let raf = 0;
    const timer = setTimeout(() => {
      const start = performance.now();
      const step = (now: number) => {
        const t = (now - start) / COUNT_MS;
        const value = from === null || target === null ? target : countFrame(from, target, t);
        setTick({ id, value, done: t >= 1 });
        if (t < 1) raf = requestAnimationFrame(step);
      };
      raf = requestAnimationFrame(step);
    }, delay);
    return () => {
      clearTimeout(timer);
      cancelAnimationFrame(raf);
    };
  }, [id, delay, reduce, from, target]);

  if (id === null || reduce) return { arrived: true, value: target, done: true };
  if (!tick || tick.id !== id) return { arrived: false, value: from, done: false };
  return { arrived: true, value: tick.value, done: tick.done };
}

function LockIcon({ className = "" }: { className?: string }) {
  return (
    <svg viewBox="0 0 16 16" aria-hidden="true" className={className} fill="none" stroke="currentColor" strokeWidth="1.6">
      <path d="M8 1.5 2.75 3.6v4.1c0 3.1 2.2 5.6 5.25 6.8 3.05-1.2 5.25-3.7 5.25-6.8V3.6L8 1.5Z" strokeLinejoin="round" />
      <rect x="5.6" y="7.1" width="4.8" height="3.6" rx="0.6" />
      <path d="M6.6 7.1V6a1.4 1.4 0 0 1 2.8 0v1.1" />
    </svg>
  );
}

function PlanChip({ items, applied, place }: { items: PlanAction[]; applied: boolean; place: "above" | "below" }) {
  const first = items[0];
  if (!first) return null;
  const shown = items.slice(0, 3);
  const rest = items.slice(3);
  const restWeeks = rest.map((a) => a.week).filter((w): w is number => w !== null);
  return (
    <div
      data-testid="graph-plan-chip"
      className={`fx-fade-in pointer-events-none absolute left-0 z-10 w-full rounded-md border border-viable/70 bg-elevated/95 px-2.5 py-1.5 font-mono text-[10px] leading-snug text-text-2 backdrop-blur-[12px] ${
        place === "above" ? "bottom-full mb-2" : "top-full mt-2"
      }`}
      style={{ boxShadow: "0 0 18px -4px color-mix(in srgb, var(--viable) 55%, transparent)" }}
    >
      <p className="flex items-center justify-between gap-2 uppercase tracking-[0.12em] text-viable">
        <span>
          {ACTION_SHORT[first.action] ?? first.action} ×{items.length}
        </span>
        <span className="text-[9px] text-muted">{applied ? "applied" : "proposed"}</span>
      </p>
      <ul>
        {shown.map((a, i) => (
          <li key={`${a.action}-${a.week ?? "x"}-${i}`} className="flex justify-between gap-2">
            <span className="text-muted">{a.week !== null ? `wk ${a.week}` : "plan"}</span>
            <span className="num text-text" data-testid="graph-plan-amount">
              {a.amount !== null ? usd(a.amount) : "yes"}
              {a.share !== null ? ` · z ${a.share.toFixed(2)}` : ""}
            </span>
          </li>
        ))}
      </ul>
      {rest.length > 0 ? (
        <p className="text-muted">
          +{rest.length} more{restWeeks.length ? ` · wk ${weekRanges(restWeeks)}` : ""} (C.3)
        </p>
      ) : null}
    </div>
  );
}

function CashFloorCallout({ floor }: { floor: FloorView | null | undefined }) {
  if (floor === undefined) return null;
  if (floor === null)
    return <p className="mt-2 font-mono text-[10px] uppercase tracking-[0.12em] text-muted">floor NOT AVAILABLE</p>;
  if (floor.firstBelow === null)
    return (
      <p className="mt-2 font-mono text-[10px] uppercase tracking-[0.12em] text-viable" data-testid="cash-node-floor">
        ▲ above the {usd(floor.floor)} floor
      </p>
    );
  return (
    <p
      className="mt-2 whitespace-nowrap rounded-sm bg-fail px-2 py-1 font-mono text-[10px] font-semibold uppercase tracking-[0.08em] text-bg"
      data-testid="cash-node-floor"
    >
      ▼ below floor from week {floor.firstBelow}
    </p>
  );
}

function CascadeNodeView({ data }: NodeProps<CascadeNode>) {
  const style = ROLE_STYLE[data.role];
  const isSink = data.role === "sink";
  const prevPeak = data.prev && data.prev.maxAbs > 0 ? data.prev.peak : data.prev ? 0 : null;
  const target = data.view ? data.view.peak : null;
  const wave = useWave(data.hit, data.reduce, prevPeak, target);
  // Until the pulse reaches this node it is "updating": the previous response's figure, dimmed, and none of that
  // response's status (no "unchanged", no floor badge), so the node never contradicts the readouts above it.
  // Every status shown is the current response's.
  const waiting = !wave.arrived;
  const view = wave.arrived ? data.view : data.prev;
  const floor = wave.arrived ? data.floor : undefined;
  const below = isSink && !waiting && !!floor && floor.firstBelow !== null;
  const changed = !waiting && !!view && view.maxAbs > 0;
  const shown = wave.arrived && view && view.maxAbs > 0 && wave.value !== null ? wave.value : view?.peak ?? 0;

  const border = below ? "border-fail" : changed ? "border-risk/80" : style.border;
  const glow = below
    ? "0 0 0 1px color-mix(in srgb, var(--fail) 60%, transparent), 0 0 22px 2px color-mix(in srgb, var(--fail) 28%, transparent)"
    : changed && view
      ? `0 0 ${Math.round(4 + 14 * view.emphasis)}px -2px color-mix(in srgb, var(--risk) ${Math.round(18 + 40 * view.emphasis)}%, transparent)`
      : undefined;
  const hitClass = data.hit && !data.reduce && wave.arrived ? (below ? "fx-node-hit-fail" : "fx-node-hit") : "";

  return (
    <div className="relative">
      {data.shield ? (
        <div
          aria-hidden="true"
          className={`${data.reduce ? "" : "fx-shield-on"} pointer-events-none absolute -inset-2 rounded-lg border-2 border-viable`}
          style={{
            boxShadow:
              "0 0 0 2px color-mix(in srgb, var(--viable) 55%, transparent), 0 0 18px 2px color-mix(in srgb, var(--viable) 22%, transparent)",
          }}
        />
      ) : null}
      {data.shield ? (
        <span
          className="absolute -top-5 right-0 z-10 flex items-center gap-1 rounded-sm border border-viable bg-elevated px-1.5 py-0.5 font-mono text-[9px] font-semibold uppercase tracking-[0.14em] text-viable"
          data-testid="payroll-shield"
        >
          <LockIcon className="size-3" />
          Protected · z_t = 0
        </span>
      ) : null}
      <div
        className={`relative rounded-md border bg-elevated px-3 py-2.5 transition-[border-color] ${border} ${hitClass} ${
          isSink ? "w-[224px]" : "w-[184px]"
        }`}
        style={{ boxShadow: glow }}
        title={describeView(data.label, data.unit, data.view)}
        data-testid={`graph-node-${data.label}`}
        data-wave={data.hit && !wave.done ? "running" : "settled"}
      >
        <Handle type="target" position={Position.Left} className="!size-1.5 !min-h-0 !min-w-0 !border-0 !bg-edge" />
        <div className="flex items-center justify-between gap-2">
          <span className={`font-mono text-[10px] uppercase tracking-[0.16em] ${below ? "text-fail" : style.tag}`}>
            {style.tagText}
          </span>
          <span className="font-mono text-[10px] text-muted">{data.symbol}</span>
        </div>
        <p className={`mt-1 font-medium ${below ? "text-fail" : "text-text"} ${isSink ? "text-2xl" : "text-lg"}`}>{data.label}</p>
        {waiting ? (
          <div className="num mt-1 leading-tight text-muted" data-testid={`graph-pending-${data.label}`}>
            {view && view.maxAbs > 0 ? (
              <span className={`font-medium opacity-50 ${isSink ? "text-lg" : "text-sm"}`}>{formatDelta(view.peak, data.unit)}</span>
            ) : null}
            <span className="ml-1.5 font-mono text-[10px] uppercase tracking-[0.12em]">
              {view && view.maxAbs > 0 ? "updating…" : "Δ · updating…"}
            </span>
          </div>
        ) : view === undefined ? (
          <p className="mt-1 font-mono text-[10px] uppercase tracking-[0.12em] text-muted">Δ not available</p>
        ) : view === null ? (
          <p className="mt-1 font-mono text-[10px] uppercase tracking-[0.12em] text-muted">Δ not in response</p>
        ) : view.maxAbs === 0 ? (
          <p className="mt-1 font-mono text-[10px] uppercase tracking-[0.12em] text-muted">Δ 0 · unchanged</p>
        ) : (
          <>
            <div className={`num mt-1 font-medium leading-tight ${below ? "text-fail" : "text-text"} ${isSink ? "text-lg" : "text-sm"}`}>
              <span data-testid={`graph-value-${data.label}`}>{formatDelta(shown, data.unit)}</span>
              <span className="ml-1.5 text-[10px] font-normal uppercase tracking-[0.1em] text-muted">peak · wk {view.peakWeek}</span>
            </div>
            <div className="mt-1.5 h-[3px] w-full overflow-hidden rounded-full bg-line" aria-hidden="true">
              <div
                className={`h-full rounded-full transition-[width] duration-500 ${below ? "bg-fail" : "bg-risk"}`}
                style={{ width: `${Math.max(2, Math.round(view.emphasis * 100))}%` }}
              />
            </div>
          </>
        )}
        {isSink && waiting ? (
          <p className="mt-2 font-mono text-[10px] uppercase tracking-[0.12em] text-muted">floor · updating…</p>
        ) : isSink ? (
          <CashFloorCallout floor={floor} />
        ) : null}
        <Handle type="source" position={Position.Right} className="!size-1.5 !min-h-0 !min-w-0 !border-0 !bg-edge" />
      </div>
      {data.plan ? <PlanChip items={data.plan.items} applied={data.plan.applied} place={data.plan.place} /> : null}
    </div>
  );
}

function PulseEdgeView({ sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, markerEnd, data }: EdgeProps<PulseEdge>) {
  const [path] = getBezierPath({ sourceX, sourceY, sourcePosition, targetX, targetY, targetPosition });
  const e = data?.emphasis ?? 0;
  const hot = e > 0;
  const plan = !!data?.plan;
  const stroke = plan ? "var(--viable)" : hot ? "var(--risk)" : "var(--edge)";
  const glowColor = plan ? "var(--viable)" : "var(--risk)";
  return (
    <>
      <BaseEdge
        path={path}
        markerEnd={markerEnd}
        className={plan && !data?.reduce ? "fx-plan-flow" : undefined}
        style={{
          stroke,
          strokeWidth: plan ? 2.5 + 3 * e : 1.25 + 4.75 * e,
          filter:
            hot || plan
              ? `drop-shadow(0 0 ${(plan ? 4 : 2 + 4 * e).toFixed(1)}px color-mix(in srgb, ${glowColor} 60%, transparent))`
              : undefined,
          transition: "stroke-width 300ms cubic-bezier(.22,1,.36,1), stroke 300ms cubic-bezier(.22,1,.36,1)",
        }}
      />
      {data?.pulse && !data.reduce ? (
        <path
          key={data.pulse.id}
          d={path}
          pathLength={1}
          fill="none"
          className="fx-pulse"
          stroke="var(--accent-hover)"
          strokeWidth={5}
          strokeLinecap="round"
          style={{
            animationDelay: `${data.pulse.delay}ms`,
            animationDuration: `${data.pulse.dur}ms`,
            filter: "drop-shadow(0 0 6px var(--accent))",
          }}
        />
      ) : null}
    </>
  );
}

const nodeTypes = { cascade: CascadeNodeView };
const edgeTypes = { pulse: PulseEdgeView };

function snapshotOf(data: SimulateResponse | null): Snapshot {
  const views = new Map<string, View>();
  for (const n of NODE_SPECS) views.set(n.id, data ? viewFor(data.deltas.nodes[n.id], data.baseline, data.result) : undefined);
  return { views, floor: data ? floorOf(data) : undefined };
}

export function ShockwaveGraph({
  data,
  stale = false,
  protect,
  plan,
  incomingActive = false,
  overlay,
  className = "",
}: {
  data: SimulateResponse | null;
  /** A newer request is in flight: the values shown belong to the previous response. */
  stale?: boolean;
  /** The Protect payroll switch (an input): the Payroll node is shielded while it is on. */
  protect: boolean;
  /** The optimizer's plan for exactly the current inputs, or null (pending, infeasible, error, none). */
  plan: GraphPlan | null;
  /** The incoming-shock card is on screen: the pulse waits for it. */
  incomingActive?: boolean;
  /** Floating panels drawn over the canvas (incoming shock, optimizer state). */
  overlay?: ReactNode;
  className?: string;
}) {
  const reduce = usePrefersReducedMotion();
  const snapshot = useMemo(() => snapshotOf(data), [data]);

  // "Previous props in state": when a new response arrives, remember the one before it and number the wave.
  const [track, setTrack] = useState<{ snap: Snapshot; prev: Snapshot | null; id: number; lead: number }>({
    snap: snapshot,
    prev: null,
    id: 0,
    lead: 0,
  });
  if (track.snap !== snapshot) {
    setTrack({ snap: snapshot, prev: track.snap, id: track.id + 1, lead: incomingActive ? INCOMING_LEAD_MS : 0 });
  }
  const prev = track.snap === snapshot ? track.prev : track.snap;

  const edgeList = useMemo<[string, string][]>(() => {
    const known = new Set<string>(NODE_SPECS.map((n) => n.id));
    return data ? data.deltas.edges.filter(([s, t]) => known.has(s) && known.has(t)) : STATIC_EDGES;
  }, [data]);

  const levels = useMemo(() => dependencyLevels(NODE_SPECS.map((n) => n.id), edgeList), [edgeList]);

  /** Nodes the pulse reaches in this wave: those whose displayed value (or the Cash floor state) changed. */
  const hits = useMemo(() => {
    const out = new Map<string, WaveHit>();
    if (reduce || !prev || prev.views.size === 0 || !data) return out;
    if ([...prev.views.values()].every((v) => v === undefined)) return out; // first response: nothing to propagate from
    for (const n of NODE_SPECS) {
      const changed =
        viewKey(prev.views.get(n.id), n.unit) !== viewKey(snapshot.views.get(n.id), n.unit) ||
        (n.id === "Cash" && floorKey(prev.floor) !== floorKey(snapshot.floor));
      if (changed) out.set(n.id, { id: track.id, delay: track.lead + (levels.get(n.id) ?? 0) * STEP_MS });
    }
    return out;
  }, [reduce, prev, data, snapshot, levels, track.id, track.lead]);

  const planByNode = useMemo(() => (plan ? actionsByNode(plan.actions) : new Map<string, PlanAction[]>()), [plan]);

  // Measured node sizes, fed back into every `nodes` array. React Flow hides a node (visibility: hidden) whose
  // user object carries no `measured` size until it re-measures it; passing the last size back keeps nodes visible
  // when a response replaces the node objects (seen as a hidden Payroll shield in CI).
  const [dims, setDims] = useState<ReadonlyMap<string, { width: number; height: number }>>(new Map());
  const onNodesChange = useCallback((changes: NodeChange<CascadeNode>[]) => {
    const sized = changes.filter(
      (c): c is NodeChange<CascadeNode> & { type: "dimensions"; id: string; dimensions: { width: number; height: number } } =>
        c.type === "dimensions" && !!c.dimensions,
    );
    if (sized.length === 0) return;
    setDims((prev) => {
      let next: Map<string, { width: number; height: number }> | null = null;
      for (const c of sized) {
        const old = prev.get(c.id);
        if (old && old.width === c.dimensions.width && old.height === c.dimensions.height) continue;
        next ??= new Map(prev);
        next.set(c.id, { width: c.dimensions.width, height: c.dimensions.height });
      }
      return next ?? prev;
    });
  }, []);

  const nodes = useMemo<CascadeNode[]>(
    () =>
      NODE_SPECS.map((n) => {
        const items = planByNode.get(n.id);
        return {
          id: n.id,
          type: "cascade",
          position: { x: n.x, y: n.y },
          measured: dims.get(n.id),
          data: {
            label: n.id,
            symbol: n.symbol,
            role: n.role,
            unit: n.unit,
            view: snapshot.views.get(n.id),
            prev: prev ? prev.views.get(n.id) : snapshot.views.get(n.id),
            floor: snapshot.floor,
            hit: hits.get(n.id) ?? null,
            reduce,
            shield: n.id === "Payroll" && protect,
            plan: items && plan ? { items, applied: plan.applied, place: PLAN_PLACE[n.id] ?? "below" } : null,
          },
          draggable: false,
          selectable: false,
          connectable: false,
          focusable: false,
        };
      }),
    [snapshot, prev, hits, reduce, protect, planByNode, plan, dims],
  );

  const edges = useMemo<PulseEdge[]>(
    () =>
      edgeList.map(([source, target]) => {
        const hitT = hits.get(target);
        const ls = levels.get(source) ?? 0;
        const lt = levels.get(target) ?? ls + 1;
        return {
          id: `${source}->${target}`,
          source,
          target,
          type: "pulse",
          focusable: false,
          selectable: false,
          data: {
            emphasis: snapshot.views.get(source)?.emphasis ?? 0,
            pulse: hitT ? { id: hitT.id, delay: track.lead + ls * STEP_MS, dur: Math.max(1, lt - ls) * STEP_MS } : null,
            plan: planByNode.has(source) && source !== "Cash",
            reduce,
          },
          markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14 },
        };
      }),
    [edgeList, hits, levels, snapshot, planByNode, reduce, track.lead],
  );

  const ariaLabel = data
    ? `Cascade dependency network for scenario ${data.result.scenario_name} versus ${data.baseline.scenario_name}: twelve nodes with simulated changes. A text list follows.`
    : "Cascade dependency network, structure only with no values. A text list of dependencies follows.";

  return (
    <figure className={`flex min-h-0 flex-col ${className}`}>
      <div className="relative min-h-[380px] flex-1 md:min-h-[540px]">
        <div className={`absolute inset-0 transition-opacity duration-300 ${stale ? "opacity-60" : ""}`} role="img" aria-label={ariaLabel}>
          <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            nodeTypes={nodeTypes}
            edgeTypes={edgeTypes}
            fitView
            fitViewOptions={{ padding: 0.1 }}
            nodesDraggable={false}
            nodesConnectable={false}
            elementsSelectable={false}
            nodesFocusable={false}
            edgesFocusable={false}
            panOnDrag={false}
            panOnScroll={false}
            zoomOnScroll={false}
            zoomOnPinch={false}
            zoomOnDoubleClick={false}
            preventScrolling={false}
            minZoom={0.2}
            style={{ background: "transparent" }}
          >
            <Background variant={BackgroundVariant.Dots} gap={24} size={1} />
          </ReactFlow>
        </div>
        {overlay}
      </div>
      <figcaption className="sr-only max-md:not-sr-only max-md:border-t max-md:border-line max-md:px-4 max-md:py-3 max-md:text-xs max-md:leading-relaxed max-md:text-muted">
        <p className="max-md:mb-2 max-md:font-mono max-md:uppercase max-md:tracking-[0.16em]">
          {data ? "Node Δ vs baseline (from /api/simulate)" : "Dependencies (source → target), MATH_MODEL §2–§3"}
        </p>
        {data ? (
          <ul className="max-md:mb-3">
            {NODE_SPECS.map((n) => (
              <li key={n.id} className="num">
                {describeView(n.id, n.unit, snapshot.views.get(n.id))}
              </li>
            ))}
            {snapshot.floor ? (
              <li className="num">
                Cash floor {usd(snapshot.floor.floor)}:{" "}
                {snapshot.floor.firstBelow === null ? "stays above it" : `below it from week ${snapshot.floor.firstBelow}`}
              </li>
            ) : null}
            {protect ? <li>Payroll: protected (Protect payroll on, z_t = 0)</li> : null}
          </ul>
        ) : null}
        <ul>
          {edgeList.map(([s, t]) => (
            <li key={`${s}-${t}`}>
              {s} → {t}
              {RELATIONS[`${s}->${t}`] ? `: ${RELATIONS[`${s}->${t}`]}` : ""}
            </li>
          ))}
        </ul>
      </figcaption>
    </figure>
  );
}
