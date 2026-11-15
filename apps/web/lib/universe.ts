/**
 * The cockpit's "business universe" on /explore (#197): which engine requests a chat turn drives, and the facts shown
 * next to a reply. Pure functions; no number here is a result. The universe POSTs the exact `tool_calls[].input` the
 * chat server ran (it is a body /api/simulate or /api/optimize accepts, routes/explore_chat.py) and draws the engine's
 * response, so the picture is the engine's, never the model's words and never the browser's arithmetic.
 */
import type { OptimizeRequest, OptimizeResponse, ScenarioShock, SimulateRequest, SimulateResponse } from "./api";
import type { ChatModel, ChatToolCall, ChatUsage } from "./chat";

const isObj = (v: unknown): v is Record<string, unknown> => !!v && typeof v === "object" && !Array.isArray(v);

/** The engine requests one chat turn drives, each the exact body of one tool call (or null). */
export interface EngineInputs {
  /** The last ok `simulate` call's input, verbatim. */
  simulate: SimulateRequest | null;
  /** The last ok `optimize` call's input, verbatim. */
  optimize: OptimizeRequest | null;
  /** How many ok simulate / optimize calls the turn made (the universe shows the last of each). */
  counts: { simulate: number; optimize: number };
  /**
   * The optimizer's plan is drawn on the network only when both calls ran the same shock; otherwise the network is
   * the simulate call's and the plan stays in its own readout.
   */
  sameShock: boolean;
}

function asSimulate(input: Record<string, unknown>): SimulateRequest | null {
  if (!isObj(input.shock)) return null;
  if (!(input.scenario_id === undefined || typeof input.scenario_id === "string")) return null;
  return input as unknown as SimulateRequest;
}

function asOptimize(input: Record<string, unknown>): OptimizeRequest | null {
  if (typeof input.protect_payroll !== "boolean") return null;
  return asSimulate(input) ? (input as unknown as OptimizeRequest) : null;
}

/** Shock identity for "same shock": the server sends the canonical dump, so equal shocks serialize equally. */
function shockKey(r: { scenario_id?: string; shock: ScenarioShock }): string {
  return JSON.stringify(r.shock);
}

export function engineInputs(calls: readonly ChatToolCall[]): EngineInputs {
  let simulate: SimulateRequest | null = null;
  let optimize: OptimizeRequest | null = null;
  const counts = { simulate: 0, optimize: 0 };
  for (const c of calls) {
    if (c.result_status !== "ok") continue;
    if (c.name === "simulate") {
      const r = asSimulate(c.input);
      if (r) {
        simulate = r;
        counts.simulate += 1;
      }
    } else if (c.name === "optimize") {
      const r = asOptimize(c.input);
      if (r) {
        optimize = r;
        counts.optimize += 1;
      }
    }
  }
  const sameShock = !!simulate && !!optimize && shockKey(simulate) === shockKey(optimize);
  return { simulate, optimize, counts, sameShock };
}

/** True when the turn has anything for the universe to re-run. */
export function drivesUniverse(calls: readonly ChatToolCall[]): boolean {
  const e = engineInputs(calls);
  return e.simulate !== null || e.optimize !== null;
}

/**
 * When the model only optimized, the network still needs POST /api/simulate for its node values: that request is the
 * optimize call's own `scenario_id` + `shock` (no plan), and the universe labels it as such.
 */
export function networkRequest(e: EngineInputs): { request: SimulateRequest; from: "simulate" | "optimize" } | null {
  if (e.simulate) return { request: e.simulate, from: "simulate" };
  if (e.optimize) {
    const { protect_payroll: _ignored, ...rest } = e.optimize;
    void _ignored;
    return { request: rest, from: "optimize" };
  }
  return null;
}

// ---- "Does the engine re-run agree with what the model was shown?" -------------------------------------------------

export interface MatchRow {
  field: string;
  /** The value in the tool's result_summary (what the model saw), or undefined if it was not there. */
  shown: unknown;
  /** The same field from the engine re-run. */
  engine: number | string | null;
  equal: boolean;
}

/** Two dollar figures agree when they are the same to the cent (the chat server rounds its summary to cents). */
function sameCents(shown: unknown, engine: number | null): boolean {
  if (engine === null) return shown === null;
  return typeof shown === "number" && Math.abs(shown - engine) <= 0.005 + 1e-9;
}

function sameExact(shown: unknown, engine: number | string | null): boolean {
  return shown === engine;
}

/** Field-by-field check of a simulate tool result against the engine re-run of its exact input. */
export function simulateMatch(summary: unknown, res: SimulateResponse): MatchRow[] | null {
  if (!isObj(summary)) return null;
  const rows: MatchRow[] = [
    { field: "min_cash", shown: summary.min_cash, engine: res.result.min_cash, equal: false },
    { field: "ending_cash", shown: summary.ending_cash, engine: res.result.cash[res.result.cash.length - 1] ?? null, equal: false },
    { field: "first_week_below_floor", shown: summary.first_week_below_floor, engine: res.first_week_below_floor ?? null, equal: false },
  ];
  return present(
    summary,
    rows.map((r) => ({
      ...r,
      equal: r.field === "first_week_below_floor" ? sameExact(r.shown, r.engine) : sameCents(r.shown, r.engine as number | null),
    })),
  );
}

/** Only the fields the summary actually carries are compared; none at all → null (NOT AVAILABLE, not "differs"). */
function present(summary: Record<string, unknown>, rows: MatchRow[]): MatchRow[] | null {
  const kept = rows.filter((r) => Object.prototype.hasOwnProperty.call(summary, r.field));
  return kept.length ? kept : null;
}

/** Field-by-field check of an optimize tool result against the engine re-run of its exact input. */
export function optimizeMatch(summary: unknown, res: OptimizeResponse): MatchRow[] | null {
  if (!isObj(summary)) return null;
  return present(summary, [
    { field: "status", shown: summary.status, engine: res.status, equal: sameExact(summary.status, res.status) },
    { field: "min_cash", shown: summary.min_cash, engine: res.min_cash, equal: sameCents(summary.min_cash, res.min_cash) },
  ]);
}

// ---- Model race facts --------------------------------------------------------------------------------------------

/**
 * Token cost of one reply at the catalogue's published prices: input_tokens × input $/M + output_tokens × output $/M,
 * divided by 10^6. Null (NOT AVAILABLE) when the provider reported no usage or the catalogue publishes no price for
 * either side; never a guess. It is an estimate at list price, not a bill.
 */
export function replyCostUsd(usage: ChatUsage | null, model: ChatModel | null): number | null {
  const p = model?.pricing;
  if (!usage || !p) return null;
  if (typeof p.input_per_mtok !== "number" || typeof p.output_per_mtok !== "number") return null;
  return (usage.input_tokens * p.input_per_mtok + usage.output_tokens * p.output_per_mtok) / 1_000_000;
}

const COST = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 4, maximumFractionDigits: 4 });

/** "$0.0123"; values under a hundredth of a cent read "< $0.0001". Formatting only. */
export function costLabel(usd: number): string {
  if (usd > 0 && usd < 0.0001) return "< $0.0001";
  return COST.format(usd);
}
