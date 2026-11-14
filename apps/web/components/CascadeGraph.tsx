"use client";

import { useMemo, useSyncExternalStore } from "react";
import {
  Background,
  BackgroundVariant,
  Handle,
  MarkerType,
  Position,
  ReactFlow,
  type Edge,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/base.css";
import type { CascadeDeltas, CascadeNodeName, NodeDelta, SimulationResult } from "@/lib/api";

/**
 * Cascade dependency network (MATH_MODEL §5). Nodes are the twelve model quantities of core/financials.py
 * `CASCADE_NODES`; edges are `CASCADE_EDGES` (served in `deltas.edges`).
 *
 * Without a `/api/simulate` response the graph is structure only (ILLUSTRATIVE): no values, uniform edges.
 * With one, every node shows its Δ read from `deltas.nodes[name].per_week` and edge emphasis is ∝ |Δ| of the
 * source node. Nothing here derives a financial figure; the only arithmetic is display scaling (see `emphasis`).
 */

type NodeRole = "shock" | "flow" | "constraint" | "sink";
type DeltaUnit = "usd" | "bp" | "pp";

interface NodeView {
  /** Peak Δ: the per_week entry with the largest |Δ| (first one on ties), exactly as served. */
  peak: number;
  peakWeek: number;
  atEnd: number;
  maxAbs: number;
  /** Display emphasis in [0, 1], ∝ |Δ| for this node. */
  emphasis: number;
}

interface CascadeNodeData extends Record<string, unknown> {
  label: CascadeNodeName;
  symbol: string;
  role: NodeRole;
  unit: DeltaUnit;
  /** undefined = no response yet (structure only); null = node missing from the response. */
  view: NodeView | null | undefined;
}

type CascadeNode = Node<CascadeNodeData, "cascade">;

const NODE_SPECS: { id: CascadeNodeName; symbol: string; role: NodeRole; unit: DeltaUnit; x: number; y: number }[] = [
  { id: "Demand", symbol: "S^dem_t", role: "shock", unit: "usd", x: 0, y: 40 },
  { id: "Supplier", symbol: "κ_t", role: "shock", unit: "pp", x: 0, y: 250 },
  { id: "Rate", symbol: "r_t", role: "shock", unit: "bp", x: 0, y: 440 },
  { id: "Sales", symbol: "S_t", role: "flow", x: 240, y: 140, unit: "usd" },
  { id: "Revolver", symbol: "B_t", role: "constraint", unit: "usd", x: 240, y: 540 },
  { id: "Receipts", symbol: "R_t", role: "flow", unit: "usd", x: 480, y: 20 },
  { id: "Purchases", symbol: "P_t", role: "flow", unit: "usd", x: 480, y: 250 },
  { id: "Interest", symbol: "J_t + Jᴿ_t", role: "flow", unit: "usd", x: 480, y: 440 },
  { id: "Inventory", symbol: "I_t", role: "constraint", unit: "usd", x: 720, y: 120 },
  { id: "Payables", symbol: "P_{t−Lp}", role: "flow", unit: "usd", x: 720, y: 300 },
  { id: "Payroll", symbol: "(1−z_t)W_t", role: "flow", unit: "usd", x: 720, y: 540 },
  { id: "Cash", symbol: "C_t", role: "sink", unit: "usd", x: 960, y: 300 },
];

/**
 * Structure shown before the first response; mirrors core/financials.py `CASCADE_EDGES`. Once a response arrives,
 * `deltas.edges` from the API is drawn instead. Relations are MATH_MODEL §2–§3 captions for the text list.
 */
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

const USD = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 0,
  signDisplay: "exceptZero",
});
const INT = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0, signDisplay: "exceptZero" });

/**
 * Display formatting of an API Δ. Unit conversion only (fraction → bp / pp). Rounded before formatting so float
 * noise (e.g. -1e-11) shows as an unsigned 0, never "-$0".
 */
export function formatDelta(value: number, unit: DeltaUnit): string {
  const whole = (n: number) => Math.round(n) || 0;
  if (unit === "bp") return `${INT.format(whole(value * 10_000))} bp`;
  if (unit === "pp") return `${INT.format(whole(value * 100))} pp`;
  return USD.format(whole(value));
}

/**
 * Display scaling for emphasis: |Δ| of a node relative to that node's own scale in this response
 * (the largest |value| it takes in the baseline or scenario path), clamped to [0, 1]. Units differ across nodes
 * (dollars, annual rate, availability share), so a shared absolute scale would hide the rate and supplier nodes.
 * Purely visual; no displayed number depends on it.
 */
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
  if (!delta || delta.per_week.length === 0) return null;
  let peakIdx = 0;
  let peak = delta.per_week[0] ?? 0;
  delta.per_week.forEach((d, i) => {
    if (Math.abs(d) > Math.abs(peak)) {
      peakIdx = i;
      peak = d;
    }
  });
  const peakWeek = result.weeks[peakIdx];
  if (peakWeek === undefined) return null;
  return {
    peak,
    peakWeek,
    atEnd: delta.at_end,
    maxAbs: delta.max_abs,
    emphasis: emphasis(delta, baseline, result),
  };
}

function describeView(label: string, unit: DeltaUnit, view: NodeView | null | undefined): string {
  if (view === undefined) return `${label}: no value (structure only)`;
  if (view === null) return `${label}: Δ not available in the response`;
  if (view.maxAbs === 0) return `${label}: no change versus baseline`;
  return `${label}: peak Δ ${formatDelta(view.peak, unit)} in week ${view.peakWeek}, Δ at end ${formatDelta(view.atEnd, unit)}`;
}

function CascadeNodeView({ data }: NodeProps<CascadeNode>) {
  const style = ROLE_STYLE[data.role];
  const isSink = data.role === "sink";
  const view = data.view;
  const changed = !!view && view.maxAbs > 0;
  return (
    <div
      className={`relative rounded-md border bg-elevated px-3 py-2.5 transition-[border-color,box-shadow] ${
        changed ? "border-risk/80" : style.border
      } ${isSink ? "w-[208px]" : "w-[184px]"}`}
      style={changed ? { boxShadow: `0 0 ${Math.round(4 + 14 * view.emphasis)}px -2px color-mix(in srgb, var(--risk) ${Math.round(18 + 40 * view.emphasis)}%, transparent)` } : undefined}
      title={describeView(data.label, data.unit, view)}
    >
      <Handle type="target" position={Position.Left} className="!size-1.5 !min-h-0 !min-w-0 !border-0 !bg-edge" />
      <div className="flex items-center justify-between gap-2">
        <span className={`font-mono text-[10px] uppercase tracking-[0.16em] ${style.tag}`}>{style.tagText}</span>
        <span className="font-mono text-[10px] text-muted">{data.symbol}</span>
      </div>
      <p className={`mt-1 font-medium text-text ${isSink ? "text-2xl" : "text-lg"}`}>{data.label}</p>
      {view === undefined ? (
        <p className="mt-1 font-mono text-[10px] uppercase tracking-[0.12em] text-muted">Δ not available</p>
      ) : view === null ? (
        <p className="mt-1 font-mono text-[10px] uppercase tracking-[0.12em] text-muted">Δ not in response</p>
      ) : view.maxAbs === 0 ? (
        <p className="mt-1 font-mono text-[10px] uppercase tracking-[0.12em] text-muted">Δ 0 · unchanged</p>
      ) : (
        <>
          <p className={`num mt-1 font-medium leading-tight text-text ${isSink ? "text-base" : "text-sm"}`}>
            {formatDelta(view.peak, data.unit)}
            <span className="ml-1.5 text-[10px] font-normal uppercase tracking-[0.1em] text-muted">
              peak · wk {view.peakWeek}
            </span>
          </p>
          <div className="mt-1.5 h-[3px] w-full overflow-hidden rounded-full bg-line" aria-hidden="true">
            <div
              className="h-full rounded-full bg-risk transition-[width]"
              style={{ width: `${Math.max(2, Math.round(view.emphasis * 100))}%` }}
            />
          </div>
        </>
      )}
      <Handle type="source" position={Position.Right} className="!size-1.5 !min-h-0 !min-w-0 !border-0 !bg-edge" />
    </div>
  );
}

const nodeTypes = { cascade: CascadeNodeView };

function subscribeReducedMotion(cb: () => void) {
  const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
  mq.addEventListener("change", cb);
  return () => mq.removeEventListener("change", cb);
}

/** prefers-reduced-motion, read on the client; the server snapshot assumes reduced (no animation). */
export function usePrefersReducedMotion(): boolean {
  return useSyncExternalStore(
    subscribeReducedMotion,
    () => window.matchMedia("(prefers-reduced-motion: reduce)").matches,
    () => true,
  );
}

export function CascadeGraph({
  deltas = null,
  baseline = null,
  result = null,
  stale = false,
  className = "",
}: {
  deltas?: CascadeDeltas | null;
  baseline?: SimulationResult | null;
  result?: SimulationResult | null;
  /** A newer request is in flight: the values shown belong to the previous response. */
  stale?: boolean;
  className?: string;
}) {
  const reduceMotion = usePrefersReducedMotion();
  const hasResponse = deltas !== null && baseline !== null && result !== null;

  const views = useMemo(() => {
    const out = new Map<string, NodeView | null | undefined>();
    for (const n of NODE_SPECS) out.set(n.id, hasResponse ? viewFor(deltas.nodes[n.id], baseline, result) : undefined);
    return out;
  }, [hasResponse, deltas, baseline, result]);

  const nodes = useMemo<CascadeNode[]>(
    () =>
      NODE_SPECS.map((n) => ({
        id: n.id,
        type: "cascade",
        position: { x: n.x, y: n.y },
        data: { label: n.id, symbol: n.symbol, role: n.role, unit: n.unit, view: views.get(n.id) },
        draggable: false,
        selectable: false,
        connectable: false,
        focusable: false,
      })),
    [views],
  );

  const known = useMemo(() => new Set<string>(NODE_SPECS.map((n) => n.id)), []);
  const edgeList = useMemo<[string, string][]>(
    () => (hasResponse ? deltas.edges.filter(([s, t]) => known.has(s) && known.has(t)) : STATIC_EDGES),
    [hasResponse, deltas, known],
  );

  const edges = useMemo<Edge[]>(
    () =>
      edgeList.map(([source, target]) => {
        const e = views.get(source)?.emphasis ?? 0;
        const hot = e > 0;
        return {
          id: `${source}->${target}`,
          source,
          target,
          type: "default",
          focusable: false,
          selectable: false,
          animated: hot && !reduceMotion,
          // Width ∝ |Δ| of the source node (display scaling above); unchanged edges keep the >= 3:1 --edge stroke.
          style: {
            stroke: hot ? "var(--risk)" : "var(--edge)",
            strokeWidth: 1.25 + 4.75 * e,
            filter: hot ? `drop-shadow(0 0 ${(2 + 4 * e).toFixed(1)}px color-mix(in srgb, var(--risk) 55%, transparent))` : undefined,
            transition: "stroke-width 150ms cubic-bezier(.22,1,.36,1)",
          },
          markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14 },
        };
      }),
    [edgeList, views, reduceMotion],
  );

  const ariaLabel = hasResponse
    ? `Cascade dependency network for scenario ${result.scenario_name} versus ${baseline.scenario_name}: twelve nodes with simulated changes. A text list follows.`
    : "Cascade dependency network, structure only with no values. A text list of dependencies follows.";

  return (
    <figure className={`flex min-h-0 flex-col ${className}`}>
      <div
        className={`relative min-h-[360px] flex-1 transition-opacity md:min-h-[520px] ${stale ? "opacity-60" : ""}`}
        role="img"
        aria-label={ariaLabel}
      >
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          fitView
          fitViewOptions={{ padding: 0.08 }}
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
      <figcaption className="sr-only max-md:not-sr-only max-md:border-t max-md:border-line max-md:px-4 max-md:py-3 max-md:text-xs max-md:leading-relaxed max-md:text-muted">
        <p className="max-md:mb-2 max-md:font-mono max-md:uppercase max-md:tracking-[0.16em]">
          {hasResponse ? "Node Δ vs baseline (from /api/simulate)" : "Dependencies (source → target), MATH_MODEL §2–§3"}
        </p>
        {hasResponse ? (
          <ul className="max-md:mb-3">
            {NODE_SPECS.map((n) => (
              <li key={n.id} className="num">
                {describeView(n.id, n.unit, views.get(n.id))}
              </li>
            ))}
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
