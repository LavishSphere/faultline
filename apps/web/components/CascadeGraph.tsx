"use client";

import { useMemo } from "react";
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

/**
 * Cascade dependency network (MATH_MODEL §5). Nodes are model quantities; edges are the
 * dependencies in MATH_MODEL §2–§3.
 *
 * In this shell the graph is ILLUSTRATIVE: structure only, no values, no animation implying flow.
 * When `/api/simulate` is wired, node Δ and edge emphasis (∝ |Δ|) come from its response only.
 */

type NodeRole = "shock" | "flow" | "constraint" | "sink";

interface CascadeNodeData extends Record<string, unknown> {
  label: string;
  symbol: string;
  role: NodeRole;
}

type CascadeNode = Node<CascadeNodeData, "cascade">;

const NODE_SPECS: { id: string; label: string; symbol: string; role: NodeRole; x: number; y: number }[] = [
  { id: "demand", label: "Demand", symbol: "m_t", role: "shock", x: 0, y: 40 },
  { id: "supplier", label: "Supplier", symbol: "κ_t", role: "shock", x: 0, y: 250 },
  { id: "rate", label: "Rate", symbol: "r_t", role: "shock", x: 0, y: 440 },
  { id: "sales", label: "Sales", symbol: "S_t", role: "flow", x: 240, y: 140 },
  { id: "revolver", label: "Revolver", symbol: "B_t", role: "constraint", x: 240, y: 540 },
  { id: "receipts", label: "Receipts", symbol: "R_t", role: "flow", x: 480, y: 20 },
  { id: "purchases", label: "Purchases", symbol: "P_t", role: "flow", x: 480, y: 250 },
  { id: "interest", label: "Interest", symbol: "J_t + Jᴿ_t", role: "flow", x: 480, y: 440 },
  { id: "inventory", label: "Inventory", symbol: "I_t", role: "constraint", x: 720, y: 120 },
  { id: "payables", label: "Payables", symbol: "P_{t−Lp}", role: "flow", x: 720, y: 300 },
  { id: "payroll", label: "Payroll", symbol: "W_t", role: "flow", x: 720, y: 540 },
  { id: "cash", label: "Cash", symbol: "C_t", role: "sink", x: 960, y: 300 },
];

/** [source, target, relation] from MATH_MODEL §2–§3. */
const EDGE_SPECS: [string, string, string][] = [
  ["demand", "sales", "m_t scales baseline demand"],
  ["supplier", "sales", "outage → lost sales λ_t"],
  ["supplier", "purchases", "backup premium π"],
  ["sales", "receipts", "collection timing a"],
  ["sales", "purchases", "replenish COGS (1−g)S_t"],
  ["purchases", "inventory", "stock in"],
  ["sales", "inventory", "stock out"],
  ["purchases", "payables", "supplier lag L_p"],
  ["rate", "interest", "r_t on term loan + revolver"],
  ["revolver", "interest", "revolver balance B_{t−1}"],
  ["receipts", "cash", "+ R_t"],
  ["payables", "cash", "− P_{t−Lp}"],
  ["interest", "cash", "− J_t − Jᴿ_t"],
  ["payroll", "cash", "− (1−z_t)W_t"],
  ["revolver", "cash", "+ y_t − q_t"],
];

const ROLE_STYLE: Record<NodeRole, { border: string; tag: string; tagText: string }> = {
  shock: { border: "border-risk/60", tag: "text-risk", tagText: "Shock input" },
  flow: { border: "border-line-strong", tag: "text-muted", tagText: "Flow" },
  constraint: { border: "border-line-strong border-dashed", tag: "text-muted", tagText: "Constraint" },
  sink: { border: "border-accent/70", tag: "text-accent-hover", tagText: "Balance" },
};

function CascadeNodeView({ data }: NodeProps<CascadeNode>) {
  const style = ROLE_STYLE[data.role];
  const isSink = data.role === "sink";
  return (
    <div
      className={`relative rounded-md border bg-elevated px-3 py-2.5 ${style.border} ${isSink ? "w-[200px]" : "w-[176px]"}`}
      aria-label={`${data.label} (${style.tagText}), no value`}
    >
      <Handle type="target" position={Position.Left} className="!size-1.5 !min-h-0 !min-w-0 !border-0 !bg-edge" />
      <div className="flex items-center justify-between gap-2">
        <span className={`font-mono text-[10px] uppercase tracking-[0.16em] ${style.tag}`}>{style.tagText}</span>
        <span className="font-mono text-[10px] text-muted">{data.symbol}</span>
      </div>
      <p className={`mt-1 font-medium text-text ${isSink ? "text-2xl" : "text-lg"}`}>
        {data.label}
      </p>
      <p className="mt-1 font-mono text-[10px] uppercase tracking-[0.12em] text-muted">Δ not available</p>
      <Handle type="source" position={Position.Right} className="!size-1.5 !min-h-0 !min-w-0 !border-0 !bg-edge" />
    </div>
  );
}

const nodeTypes = { cascade: CascadeNodeView };

export function CascadeGraph({ className = "" }: { className?: string }) {
  const nodes = useMemo<CascadeNode[]>(
    () =>
      NODE_SPECS.map((n) => ({
        id: n.id,
        type: "cascade",
        position: { x: n.x, y: n.y },
        data: { label: n.label, symbol: n.symbol, role: n.role },
        draggable: false,
        selectable: false,
        connectable: false,
        focusable: false,
      })),
    [],
  );

  const edges = useMemo<Edge[]>(
    () =>
      EDGE_SPECS.map(([source, target]) => ({
        id: `${source}->${target}`,
        source,
        target,
        type: "default",
        focusable: false,
        selectable: false,
        // Uniform width: emphasis ∝ |Δ| is reserved for real /api/simulate output.
        style: { stroke: "var(--edge)", strokeWidth: 1.25 },
        markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14 },
      })),
    [],
  );

  return (
    <figure className={`flex min-h-0 flex-col ${className}`}>
      <div
        className="relative min-h-[340px] flex-1 md:min-h-[480px]"
        role="img"
        aria-label="Illustrative cascade dependency network with twelve nodes and no values. A text list of dependencies follows."
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
        <p className="max-md:mb-2 max-md:font-mono max-md:uppercase max-md:tracking-[0.16em]">Dependencies (source → target), MATH_MODEL §2–§3</p>
        <ul>
          {EDGE_SPECS.map(([s, t, rel]) => {
            const label = (id: string) => NODE_SPECS.find((n) => n.id === id)?.label ?? id;
            return (
              <li key={`${s}-${t}`}>
                {label(s)} → {label(t)}: {rel}
              </li>
            );
          })}
        </ul>
      </figcaption>
    </figure>
  );
}
