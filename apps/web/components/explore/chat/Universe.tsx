"use client";

import { useEffect, useId, useMemo, useState } from "react";
import {
  floorOf,
  optimize,
  simulate,
  type ApiFailure,
  type ApiResult,
  type OptimizeRequest,
  type OptimizeResponse,
  type SimulateRequest,
  type SimulateResponse,
} from "@/lib/api";
import type { ChatToolCall } from "@/lib/chat";
import { usd, weekRanges } from "@/lib/format";
import {
  engineInputs,
  networkRequest,
  optimizeMatch,
  simulateMatch,
  type EngineInputs,
  type MatchRow,
} from "@/lib/universe";
import { CashTimeline, type TimelineSeries } from "../../cascade/CashTimeline";
import { ShockwaveGraph, type GraphPlan } from "../../cascade/ShockwaveGraph";
import { FinancialReadout } from "../../FinancialReadout";
import { ProvenanceBadge } from "../../ProvenanceBadge";
import "./universe.css";

/**
 * The business universe (#197): the right half of the cockpit. For the selected answer it POSTs the exact
 * `tool_calls[].input` of the model's last simulate and optimize calls to /api/simulate and /api/optimize and draws
 * the engine's responses on the CASCADE network (shockwave, floor, plan chips, payroll shield) and the 26-week cash
 * path. Nothing is taken from the reply text and nothing is computed here: a failed re-request is NOT AVAILABLE.
 */

export interface UniverseSource {
  /** Stable id of the answer (changes when another answer is selected, which replays the universe). */
  key: string;
  /** "Answer 2 · claude-fixture" */
  title: string;
  /** Short tab label in a race ("A · model"). */
  tab?: string;
  calls: readonly ChatToolCall[];
}

type Req<T> = { kind: "none" } | { kind: "loading" } | { kind: "done"; result: ApiResult<T> };

/**
 * Engine requests for this page session, keyed by the exact request body: one request per distinct body, shared by
 * every view of it (the universe, the agreement check, an earlier answer clicked again). A failure is dropped from
 * the map, so Retry sends it again.
 */
const simCache = new Map<string, Promise<ApiResult<SimulateResponse>>>();
const optCache = new Map<string, Promise<ApiResult<OptimizeResponse>>>();

function useEngine<Q, T>(
  request: Q | null,
  cache: Map<string, Promise<ApiResult<T>>>,
  run: (q: Q) => Promise<ApiResult<T>>,
  retry: number,
): Req<T> {
  const key = request ? JSON.stringify(request) : null;
  const [state, setState] = useState<{ key: string | null; req: Req<T> }>({ key: null, req: { kind: "none" } });
  useEffect(() => {
    if (!key || !request) return;
    let live = true;
    let pending = cache.get(key);
    if (!pending) {
      pending = run(request);
      cache.set(key, pending);
    }
    void pending.then((result) => {
      if (!result.ok && cache.get(key) === pending) cache.delete(key);
      if (live) setState({ key, req: { kind: "done", result } });
    });
    return () => {
      live = false;
    };
    // `request` is identified by `key` (its exact JSON).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, retry]);
  if (!key) return { kind: "none" };
  if (state.key !== key) return { kind: "loading" };
  return state.req;
}

interface EngineRun {
  inputs: EngineInputs;
  network: { request: SimulateRequest; from: "simulate" | "optimize" } | null;
  sim: Req<SimulateResponse>;
  opt: Req<OptimizeResponse>;
}

function useEngineRun(calls: readonly ChatToolCall[] | null, retry: number): EngineRun {
  const inputs = useMemo(() => engineInputs(calls ?? []), [calls]);
  const network = useMemo(() => networkRequest(inputs), [inputs]);
  const sim = useEngine<SimulateRequest, SimulateResponse>(network?.request ?? null, simCache, (q) => simulate(q), retry);
  const opt = useEngine<OptimizeRequest, OptimizeResponse>(inputs.optimize, optCache, (q) => optimize(q), retry);
  return { inputs, network, sim, opt };
}

function failureText(f: ApiFailure): string {
  if (f.kind === "network" || f.kind === "timeout") return "The engine could not be reached.";
  if (f.kind === "malformed") return "The engine's answer did not match its contract.";
  return f.error || `The engine refused this input${f.status ? ` (HTTP ${f.status})` : ""}.`;
}

/**
 * The engine's baseline (no shock), fetched once the first question is sent, so the first answer's shockwave ripples
 * out from it. Nothing is sent to the engine on page load (the LIVE EXPLORE workbench below promises the same).
 */
const BASELINE_REQUEST: SimulateRequest = { shock: {} };

export function Universe({
  sources,
  reduce,
  focusKey,
  armed,
}: {
  sources: readonly UniverseSource[];
  reduce: boolean;
  /** The source to open on (a race answer clicked); default the first. */
  focusKey?: string;
  /** A question has been sent: the baseline may be fetched. */
  armed: boolean;
}) {
  const [tab, setTab] = useState(0);
  const [retry, setRetry] = useState(0);
  const a = sources[0] ?? null;
  const b = sources[1] ?? null;
  const runA = useEngineRun(a?.calls ?? null, retry);
  const runB = useEngineRun(b?.calls ?? null, retry);
  const sourcesKey = `${sources.map((s) => s.key).join("|")}#${focusKey ?? ""}`;
  const [lastKey, setLastKey] = useState(sourcesKey);
  if (lastKey !== sourcesKey) {
    setLastKey(sourcesKey);
    setTab(Math.max(0, focusKey ? sources.findIndex((s) => s.key === focusKey) : 0));
  }
  const active = tab === 1 && b ? b : a;
  const run = tab === 1 && b ? runB : runA;
  const tabsId = useId();
  const baseline = useEngine<SimulateRequest, SimulateResponse>(armed ? BASELINE_REQUEST : null, simCache, (q) => simulate(q), retry);

  return (
    <section
      aria-labelledby={`${tabsId}-title`}
      className="universe-sky relative flex min-w-0 flex-col overflow-hidden rounded-xl border border-line"
      data-testid="universe"
    >
      <header className="flex flex-col gap-3 border-b border-line/70 px-4 pb-4 pt-5 md:px-6">
        <div className="flex min-w-0 flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="kicker">
              <span className="text-text-2">F.1</span> · business universe
            </p>
            <h2 id={`${tabsId}-title`} className="display mt-1 text-[clamp(2rem,3.2vw,3.25rem)] leading-none text-text">
              The engine&apos;s <em>view</em>
            </h2>
          </div>
          <span className="flex flex-wrap items-center gap-1.5">
            <ProvenanceBadge kind="SIMULATED" />
            <ProvenanceBadge kind="SYNTHETIC" detail="demo business" />
          </span>
        </div>
        <p className="font-mono text-[11px] leading-relaxed text-muted" data-testid="universe-caption">
          {active ? (
            <>
              <span className="text-text-2">{active.title}</span> · Engine re-ran this exact input: the network and cash
              path are POST /api/simulate and /api/optimize answers, not the model&apos;s words.
            </>
          ) : (
            <>
              Ask a question. When the model calls simulate or optimize, the engine re-runs that exact input here and the
              shockwave ripples through the network. Until then: structure only, no values.
            </>
          )}
        </p>
        {b ? (
          <div role="tablist" aria-label="Race: whose engine run to show" className="flex min-w-0 flex-wrap gap-2">
            {[a, b].map((s, i) =>
              s ? (
                <button
                  key={s.key}
                  type="button"
                  role="tab"
                  aria-selected={tab === i}
                  onClick={() => setTab(i)}
                  className={`min-w-0 max-w-full truncate rounded-full border px-3 py-1 font-mono text-[11px] ${
                    tab === i ? "border-accent bg-accent-soft text-text" : "border-line-strong text-text-2 hover:bg-hover"
                  }`}
                  data-testid="universe-tab"
                >
                  {s.tab ?? s.title}
                </button>
              ) : null,
            )}
          </div>
        ) : null}
      </header>
      <UniverseBody
        replayKey={active?.key ?? "idle"}
        run={run}
        has={!!active}
        baseline={baseline.kind === "done" && baseline.result.ok ? baseline.result.data : null}
        reduce={reduce}
        onRetry={() => setRetry((n) => n + 1)}
      />
    </section>
  );
}

function UniverseBody({
  replayKey,
  run,
  has,
  baseline,
  reduce,
  onRetry,
}: {
  replayKey: string;
  run: EngineRun;
  has: boolean;
  baseline: SimulateResponse | null;
  reduce: boolean;
  onRetry: () => void;
}) {
  const { inputs, network, sim, opt } = run;
  const simData = sim.kind === "done" && sim.result.ok ? sim.result.data : null;
  // The network stays mounted, so moving from one engine answer to the next releases the shockwave between them.
  // Idle (or an answer with no engine call): the engine's baseline. While a re-run is in flight: the last picture,
  // dimmed. Never a value that is not one of these responses.
  const current = simData ?? (!network ? baseline : null);
  const [lastGraph, setLastGraph] = useState<SimulateResponse | null>(null);
  if (current && current !== lastGraph) setLastGraph(current);
  const graphData = current ?? (sim.kind === "loading" ? lastGraph : null);
  const showingBaseline = !network && current !== null && current === baseline;
  const optData = opt.kind === "done" && opt.result.ok ? opt.result.data : null;
  const simFail = sim.kind === "done" && !sim.result.ok ? sim.result : null;
  const optFail = opt.kind === "done" && !opt.result.ok ? opt.result : null;
  const protect = inputs.optimize?.protect_payroll === true;
  // Plan chips only on the network of the very shock the optimizer solved (otherwise they would describe another run).
  const planOnNetwork = !!inputs.optimize && (network?.from === "optimize" || inputs.sameShock);
  const plan: GraphPlan | null =
    planOnNetwork && optData && optData.status === "OPTIMAL" && optData.actions ? { actions: optData.actions, applied: false } : null;
  const floor = simData ? floorOf(simData) : null;
  const status = !has || !network ? "idle" : sim.kind === "loading" || opt.kind === "loading" ? "loading" : simFail ? "error" : "ok";

  const timeline: TimelineSeries[] = simData
    ? [
        { id: "baseline", label: "baseline", values: simData.baseline.cash, source: "POST /api/simulate" },
        { id: "scenario", label: "scenario", values: simData.result.cash, source: "POST /api/simulate" },
        ...(inputs.optimize
          ? [
              {
                id: "plan" as const,
                label: "with the optimizer's plan",
                values: planOnNetwork && optData?.status === "OPTIMAL" ? optData.cash : null,
                source: "POST /api/optimize",
              },
            ]
          : []),
      ]
    : [];

  return (
    <div
      className="flex min-w-0 flex-col"
      data-testid="universe-body"
      data-status={status}
      data-engine-min-cash={simData ? String(simData.result.min_cash) : undefined}
      data-engine-first-below={simData ? String(simData.first_week_below_floor ?? "none") : undefined}
    >
      {has && !network ? (
        <p className="border-b border-line/70 px-4 py-3 font-mono text-[11px] uppercase tracking-[0.12em] text-muted md:px-6" data-testid="universe-no-engine">
          This answer called no simulate or optimize tool: nothing for the engine to re-run. Showing the baseline.
        </p>
      ) : null}

      {network ? (
        <div
          key={replayKey}
          className={`grid grid-cols-2 gap-px border-b border-line/70 bg-line/60 sm:grid-cols-4 ${reduce ? "" : "universe-replay"}`}
          data-testid="universe-readouts"
        >
          <Cell>
            {simFail ? (
              <NA label="Minimum cash" />
            ) : (
              <FinancialReadout
                label="Minimum cash"
                value={simData ? simData.result.min_cash : null}
                format="usd"
                provenance="SIMULATED"
                size="md"
                dimmed={sim.kind === "loading"}
                sublabel={simData ? `week ${simData.result.min_cash_week} · scenario` : undefined}
              />
            )}
          </Cell>
          <Cell>
            <p className="kicker">Cash floor</p>
            {floor ? (
              <p className={`num mt-1 text-2xl font-medium ${floor.firstBelow !== null ? "text-fail" : "text-text"}`} data-testid="universe-floor">
                {usd(floor.floor)}
              </p>
            ) : (
              <p className="mt-1 font-mono text-sm uppercase text-muted">{simData ? "Not available" : "…"}</p>
            )}
            {floor ? (
              <p className={`mt-1 text-xs ${floor.firstBelow !== null ? "font-medium text-fail" : "text-muted"}`} data-testid="universe-below">
                {floor.firstBelow === null
                  ? "stays above it"
                  : `below it in week${floor.weeksBelow.length === 1 ? "" : "s"} ${weekRanges(floor.weeksBelow)}`}
              </p>
            ) : null}
          </Cell>
          <Cell>
            <p className="kicker">Recovery plan</p>
            <PlanStatus has={!!inputs.optimize} opt={opt} data={optData} />
          </Cell>
          <Cell>
            <p className="kicker">Payroll</p>
            {inputs.optimize ? (
              <p className={`mt-1 text-sm font-medium ${protect ? "text-viable" : "text-risk"}`} data-testid="universe-payroll">
                {protect ? "Protected (protect_payroll: true)" : "Not protected (protect_payroll: false)"}
              </p>
            ) : (
              <p className="mt-1 text-sm text-muted">No optimize call: the switch was not set.</p>
            )}
          </Cell>
        </div>
      ) : null}

      <div className="universe-graph relative min-w-0">
        {simFail ? (
          <div className="flex min-h-[320px] flex-col items-start justify-center gap-2 px-6 py-8" role="alert" data-testid="universe-failed">
            <p className="font-mono text-2xl font-medium uppercase tracking-[0.08em] text-muted">Not available</p>
            <p className="max-w-prose text-sm text-text-2">{failureText(simFail)} No picture is drawn instead of the engine&apos;s.</p>
            <button type="button" onClick={onRetry} className="rounded-md border border-line-strong px-3 py-1.5 font-mono text-[11px] uppercase tracking-[0.12em] text-text-2 hover:bg-hover hover:text-text">
              Retry the engine
            </button>
          </div>
        ) : (
          <ShockwaveGraph
            data={graphData}
            stale={sim.kind === "loading"}
            protect={simData ? protect : false}
            plan={simData ? plan : null}
          />
        )}
        {showingBaseline ? (
          <p className="pointer-events-none absolute left-4 top-3 rounded-sm border border-line bg-elevated/80 px-2 py-1 font-mono text-[10.5px] uppercase tracking-[0.12em] text-muted backdrop-blur-[12px]" data-testid="universe-baseline">
            Baseline · no shock · POST /api/simulate
          </p>
        ) : null}
        {sim.kind === "loading" ? (
          <p className="pointer-events-none absolute left-4 top-3 rounded-sm border border-line bg-elevated/80 px-2 py-1 font-mono text-[10.5px] uppercase tracking-[0.12em] text-muted backdrop-blur-[12px]" role="status">
            Re-running POST /api/simulate…
          </p>
        ) : null}
      </div>

      {network && !simFail ? (
        <div className="border-t border-line/70 px-4 py-3 md:px-6">
          <p className="kicker mb-2">
            {simData ? `${simData.result.horizon_weeks}-week` : "Weekly"} cash path · weeks below the floor in red
          </p>
          {simData ? (
            <CashTimeline
              weeks={simData.result.weeks}
              series={timeline}
              floor={floor ? { ...floor, of: "the scenario" } : null}
              stale={sim.kind === "loading"}
              reduce={reduce}
              drawKey={JSON.stringify(network.request)}
            />
          ) : (
            <p className="font-mono text-[11px] uppercase tracking-[0.12em] text-muted">Waiting for POST /api/simulate…</p>
          )}
          {inputs.optimize && !planOnNetwork ? (
            <p className="mt-2 text-xs text-muted" data-testid="universe-plan-other-shock">
              The optimize call ran a different shock from the simulate call, so its plan is not drawn on this network.
            </p>
          ) : null}
          {optFail ? (
            <p className="mt-2 text-xs text-muted" data-testid="universe-opt-failed">
              Optimizer re-run NOT AVAILABLE: {failureText(optFail)}
            </p>
          ) : null}
        </div>
      ) : null}

      {network ? <Provenance inputs={inputs} network={network} sim={simData} opt={optData} /> : null}
    </div>
  );
}

function Cell({ children }: { children: React.ReactNode }) {
  return <div className="min-w-0 bg-elevated/70 px-4 py-3 backdrop-blur-[12px]">{children}</div>;
}

function NA({ label }: { label: string }) {
  return (
    <div>
      <p className="kicker">{label}</p>
      <p className="mt-1 font-mono text-lg uppercase text-muted">Not available</p>
    </div>
  );
}

function PlanStatus({ has, opt, data }: { has: boolean; opt: Req<OptimizeResponse>; data: OptimizeResponse | null }) {
  if (!has) return <p className="mt-1 text-sm text-muted">No optimize call in this answer.</p>;
  if (opt.kind === "loading") return <p className="mt-1 font-mono text-sm text-muted">Re-running…</p>;
  if (!data) return <p className="mt-1 font-mono text-sm uppercase text-muted">Not available</p>;
  if (data.status === "OPTIMAL") {
    return (
      <div data-testid="universe-plan" data-status={data.status}>
        <p className="mt-1 font-mono text-sm font-semibold uppercase tracking-[0.08em] text-viable">Optimal</p>
        <p className="mt-0.5 text-xs text-muted">
          {data.actions?.length ?? 0} action{data.actions?.length === 1 ? "" : "s"}
          {data.min_cash !== null ? ` · min cash ${usd(data.min_cash)}` : ""}
        </p>
      </div>
    );
  }
  return (
    <div data-testid="universe-plan" data-status={data.status}>
      <p className="mt-1 font-mono text-sm font-semibold uppercase tracking-[0.08em] text-fail">{data.status}</p>
      {data.binding_constraints?.length ? (
        <p className="mt-0.5 break-words text-xs text-fail">binding: {data.binding_constraints.join(", ")}</p>
      ) : data.diagnostic ? (
        <p className="mt-0.5 break-words text-xs text-fail">{data.diagnostic}</p>
      ) : null}
    </div>
  );
}

function MatchList({ title, rows }: { title: string; rows: MatchRow[] | null }) {
  if (!rows) return null;
  return (
    <div className="min-w-0">
      <p className="kicker mb-1">{title}</p>
      <ul className="flex flex-col gap-0.5 font-mono text-[11px]">
        {rows.map((r) => (
          <li key={r.field} className="flex min-w-0 flex-wrap gap-x-2" data-testid="universe-match" data-equal={r.equal ? "true" : "false"}>
            <span className={r.equal ? "text-viable" : "text-fail"}>
              <span aria-hidden="true">{r.equal ? "✓ " : "✕ "}</span>
              {r.equal ? "same" : "differs"}
            </span>
            <span className="text-text-2">{r.field}</span>
            {!r.equal ? (
              <span className="break-all text-muted">
                model saw {JSON.stringify(r.shown ?? null)} · engine {JSON.stringify(r.engine)}
              </span>
            ) : null}
          </li>
        ))}
      </ul>
    </div>
  );
}

function Provenance({
  inputs,
  network,
  sim,
  opt,
}: {
  inputs: EngineInputs;
  network: { request: SimulateRequest; from: "simulate" | "optimize" };
  sim: SimulateResponse | null;
  opt: OptimizeResponse | null;
}) {
  return (
    <details className="group border-t border-line/70 px-4 py-3 md:px-6" data-testid="universe-provenance">
      <summary className="cursor-pointer list-none font-mono text-[11px] uppercase tracking-[0.12em] text-text-2 hover:text-text">
        <span aria-hidden="true" className="mr-1 inline-block transition-transform group-open:rotate-90">▸</span>
        What the engine re-ran
        {inputs.counts.simulate > 1 || inputs.counts.optimize > 1 ? (
          <span className="ml-2 normal-case tracking-normal text-muted">
            (the model called simulate {inputs.counts.simulate}× and optimize {inputs.counts.optimize}×; the last of each is shown)
          </span>
        ) : null}
      </summary>
      <div className="mt-3 grid min-w-0 grid-cols-1 gap-4 lg:grid-cols-2">
        <div className="min-w-0">
          <p className="kicker mb-1">
            POST /api/simulate · {network.from === "simulate" ? "the simulate call's exact input" : "the optimize call's scenario and shock"}
          </p>
          <pre className="max-h-48 overflow-auto whitespace-pre-wrap break-all rounded-md border border-line bg-bg/60 p-2 font-mono text-[10.5px] text-text-2" data-testid="universe-sim-request">
            {JSON.stringify(network.request, null, 2)}
          </pre>
        </div>
        {inputs.optimize ? (
          <div className="min-w-0">
            <p className="kicker mb-1">POST /api/optimize · the optimize call&apos;s exact input</p>
            <pre className="max-h-48 overflow-auto whitespace-pre-wrap break-all rounded-md border border-line bg-bg/60 p-2 font-mono text-[10.5px] text-text-2">
              {JSON.stringify(inputs.optimize, null, 2)}
            </pre>
          </div>
        ) : null}
      </div>
      <p className="mt-2 text-[11px] text-muted">
        {sim ? `${sim.provenance} on ${sim.business_provenance} inputs` : ""}
        {opt ? ` · optimizer ${opt.provenance}` : ""}
      </p>
    </details>
  );
}

/** Re-run vs tool-result check for one answer, shown under the reply (and in the race). */
export function EngineAgreement({ calls }: { calls: readonly ChatToolCall[] }) {
  const run = useEngineRun(calls, 0);
  const simCall = [...calls].reverse().find((c) => c.name === "simulate" && c.result_status === "ok");
  const optCall = [...calls].reverse().find((c) => c.name === "optimize" && c.result_status === "ok");
  const sim = run.inputs.simulate && run.sim.kind === "done" && run.sim.result.ok ? run.sim.result.data : null;
  const opt = run.opt.kind === "done" && run.opt.result.ok ? run.opt.result.data : null;
  const simRows = sim && simCall ? simulateMatch(simCall.result_summary, sim) : null;
  const optRows = opt && optCall ? optimizeMatch(optCall.result_summary, opt) : null;
  if (!run.network) return null;
  const pending = run.sim.kind === "loading" || run.opt.kind === "loading";
  const failed = (run.sim.kind === "done" && !run.sim.result.ok) || (run.opt.kind === "done" && !run.opt.result.ok);
  const all = [...(simRows ?? []), ...(optRows ?? [])];
  const verdict = pending ? "pending" : failed ? "na" : all.length === 0 ? "na" : all.every((r) => r.equal) ? "same" : "differs";
  return (
    <div className="flex min-w-0 flex-col gap-2 rounded-md border border-line bg-bg/40 p-3" data-testid="engine-agreement" data-verdict={verdict}>
      <p className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <span className="kicker !text-text-2">Engine re-run vs the tool results the model saw</span>
        <ProvenanceBadge kind="SIMULATED" />
      </p>
      {pending ? (
        <p className="font-mono text-[11px] text-muted">Re-running the exact inputs…</p>
      ) : verdict === "na" ? (
        <p className="font-mono text-[11px] uppercase tracking-[0.1em] text-muted">Not available: the re-run failed or the summary has no comparable fields.</p>
      ) : (
        <div className="grid min-w-0 grid-cols-1 gap-3 sm:grid-cols-2">
          <MatchList title="simulate" rows={simRows} />
          <MatchList title="optimize" rows={optRows} />
        </div>
      )}
    </div>
  );
}
