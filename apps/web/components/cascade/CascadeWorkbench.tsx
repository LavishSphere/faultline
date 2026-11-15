"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  API_BASE,
  floorOf,
  getScenarios,
  optimize,
  simulate,
  type ActionPlan,
  type ApiFailure,
  type OptimizeRequest,
  type OptimizeResponse,
  type ScenarioPreset,
  type ScenarioShock,
  type ScenariosSummary,
  type SimulateRequest,
  type SimulateResponse,
  type SimulationResult,
} from "@/lib/api";
import { usd, usdCentsFloor, usdDelta } from "@/lib/format";
import { usePrefersReducedMotion } from "../CascadeGraph";
import { CashNegativeReadout, MinCashSublabel, payrollOffNote } from "../CashReadouts";
import { FinancialReadout } from "../FinancialReadout";
import { NotAvailable, Panel } from "../Panel";
import { JudgeChallenge } from "./challenge/JudgeChallenge";
import { IncomingShock, type IncomingShockInfo } from "./challenge/IncomingShock";
import type { JudgeChallenge as Challenge } from "./challenge/judgeChallenges";
import { CashTimeline, type TimelineSeries } from "./CashTimeline";
import { ShockwaveGraph, type GraphPlan } from "./ShockwaveGraph";
import type { ProvenanceInput } from "../ProvenanceBadge";
import {
  DEFAULT_DEPENDENT_PCT,
  NO_SHOCK,
  buildShock,
  controlsFromShock,
  editShock,
  fmt,
  isWholeWeekOutage,
  maxOutageWeeks,
  outageWeekCount,
  type ControlKey,
  type ScenarioControls,
} from "./scenarioInputs";

/** Debounce for slider-driven requests (cascade-ui skill: ~150 ms). */
const DEBOUNCE_MS = 150;

type SimState =
  | { kind: "loading"; last: SimulateResponse | null; meta?: { planned: boolean; seq: number } }
  | { kind: "ok"; data: SimulateResponse; key: string; ms: number; at: Date; planned: boolean; seq: number }
  | { kind: "error"; failure: ApiFailure };

type OptState =
  | { kind: "loading"; last: OptimizeResponse | null }
  | { kind: "ok"; data: OptimizeResponse; key: string; ms: number; at: Date }
  | { kind: "error"; failure: ApiFailure };

/** A plan applied from /api/optimize, valid only for the exact optimize request (shock + protect) it answered. */
type Applied = { optKey: string; plan: ActionPlan };

type ScenariosState = { kind: "loading" } | { kind: "ok"; data: ScenariosSummary } | { kind: "error"; failure: ApiFailure };

/** A preset is sent exactly; `touched` lists the controls moved since choosing it (only those override it). */
type Mode = { kind: "custom" } | { kind: "preset"; preset: ScenarioPreset; touched: ReadonlySet<ControlKey> };

/**
 * Provenance labels the simulate route may send (mirrors the Pydantic `Literal`s in routes/simulate.py).
 * Anything else is treated as a malformed response, never displayed as a guess.
 */
const SIMULATED_LABELS = new Set(["SIMULATED"]);
const BUSINESS_LABELS = new Set(["SYNTHETIC", "ILLUSTRATIVE"]);

function unreachable(f: ApiFailure): boolean {
  return f.kind === "network" || f.kind === "timeout";
}

const TIME = new Intl.DateTimeFormat("en-US", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });

export function CascadeWorkbench() {
  const [controls, setControls] = useState<ScenarioControls>(NO_SHOCK);
  const [mode, setMode] = useState<Mode>({ kind: "custom" });
  const [sim, setSim] = useState<SimState>({ kind: "loading", last: null });
  const [scenarios, setScenarios] = useState<ScenariosState>({ kind: "loading" });
  const [retry, setRetry] = useState(0);
  /** T from the most recent successful response; week sliders stay disabled until the API reports it. */
  const [horizon, setHorizon] = useState<number | null>(null);
  const lastGood = useRef<SimulateResponse | null>(null);
  /** Whether `lastGood` answered a request with a plan, and its response number (re-draws the cash path). */
  const lastMeta = useRef<{ planned: boolean; seq: number }>({ planned: false, seq: 0 });
  const first = useRef(true);
  /** The latest response to the shock alone (no plan), so the cash timeline can show it next to an applied plan. */
  const [unplanned, setUnplanned] = useState<{ key: string; result: SimulationResult } | null>(null);
  /** Judge's Challenge card over the network (#165): text from GET /api/judge-challenges only. */
  const [incoming, setIncoming] = useState<IncomingShockInfo | null>(null);
  const dismissIncoming = useCallback(() => setIncoming(null), []);
  const reduce = usePrefersReducedMotion();

  const [protect, setProtect] = useState(false);
  const [opt, setOpt] = useState<OptState>({ kind: "loading", last: null });
  const [applied, setApplied] = useState<Applied | null>(null);
  /** Optimize has its own retry, so retrying one request never re-sends the other. */
  const [optRetry, setOptRetry] = useState(0);
  const lastOpt = useRef<OptimizeResponse | null>(null);
  const firstOpt = useRef(true);

  const scenario = useMemo<SimulateRequest>(() => {
    if (mode.kind === "preset" && horizon !== null) {
      if (mode.touched.size === 0) return { scenario_id: mode.preset.id, shock: mode.preset.shock };
      // Edited preset: no scenario_id, because the shock is no longer the catalog entry.
      return { shock: editShock(mode.preset.shock, controls, mode.touched, horizon, mode.preset.name) };
    }
    return { shock: buildShock(controls, horizon) };
  }, [mode, controls, horizon]);
  const optRequest: OptimizeRequest = { ...scenario, protect_payroll: protect };
  const optKey = JSON.stringify(optRequest);
  const scenarioKey = JSON.stringify(scenario);
  /** The applied plan only while the shock and switch are exactly the ones it was solved for. */
  const activePlan = applied !== null && applied.optKey === optKey ? applied.plan : null;
  const request: SimulateRequest = activePlan ? { ...scenario, plan: activePlan } : scenario;
  const requestKey = JSON.stringify(request);
  /** The shock actually sent: slider readouts show its values, not the rounded slider positions. */
  const sent: ScenarioShock = request.shock;

  // One in-flight /api/optimize at a time, same debounce + abort pattern as /api/simulate below.
  useEffect(() => {
    const controller = new AbortController();
    const body = JSON.parse(optKey) as OptimizeRequest;
    const delay = firstOpt.current ? 0 : DEBOUNCE_MS;
    firstOpt.current = false;
    const timer = setTimeout(async () => {
      setOpt({ kind: "loading", last: lastOpt.current });
      const started = performance.now();
      const res = await optimize(body, controller.signal);
      if (controller.signal.aborted) return;
      if (res.ok && (!SIMULATED_LABELS.has(res.data.provenance) || !BUSINESS_LABELS.has(res.data.business_provenance))) {
        lastOpt.current = null;
        setOpt({
          kind: "error",
          failure: { ok: false, kind: "malformed", error: `unknown provenance label "${res.data.provenance}"` },
        });
      } else if (res.ok) {
        lastOpt.current = res.data;
        setOpt({ kind: "ok", data: res.data, key: optKey, ms: Math.round(performance.now() - started), at: new Date() });
      } else {
        lastOpt.current = null;
        setOpt({ kind: "error", failure: res });
      }
    }, delay);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [optKey, optRetry]);

  // One in-flight /api/simulate at a time: a newer input aborts the older request before it can land.
  useEffect(() => {
    const controller = new AbortController();
    const body = JSON.parse(requestKey) as SimulateRequest;
    const delay = first.current ? 0 : DEBOUNCE_MS;
    first.current = false;
    const timer = setTimeout(async () => {
      setSim({ kind: "loading", last: lastGood.current, meta: lastMeta.current });
      const started = performance.now();
      const res = await simulate(body, controller.signal);
      if (controller.signal.aborted) return;
      if (res.ok && (!SIMULATED_LABELS.has(res.data.provenance) || !BUSINESS_LABELS.has(res.data.business_provenance))) {
        lastGood.current = null;
        setSim({
          kind: "error",
          failure: {
            ok: false,
            kind: "malformed",
            error: `unknown provenance label (provenance "${res.data.provenance}", business_provenance "${res.data.business_provenance}")`,
          },
        });
      } else if (res.ok) {
        lastGood.current = res.data;
        const planned = body.plan !== undefined;
        lastMeta.current = { planned, seq: lastMeta.current.seq + 1 };
        setHorizon(res.data.result.horizon_weeks);
        if (!planned) setUnplanned({ key: requestKey, result: res.data.result });
        setSim({ kind: "ok", data: res.data, key: requestKey, ms: Math.round(performance.now() - started), at: new Date(), planned, seq: lastMeta.current.seq });
      } else {
        // Never show an older scenario's numbers as if they answered this request.
        if (unreachable(res) || res.status === 404) lastGood.current = null;
        setSim({ kind: "error", failure: res });
      }
    }, delay);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [requestKey, retry]);

  useEffect(() => {
    const controller = new AbortController();
    void getScenarios(controller.signal).then((res) => {
      if (controller.signal.aborted) return;
      setScenarios(res.ok ? { kind: "ok", data: res.data } : { kind: "error", failure: res });
    });
    return () => controller.abort();
  }, [retry]);

  const data = sim.kind === "ok" ? sim.data : sim.kind === "loading" ? sim.last : null;
  // Dimmed both while waiting out the debounce and while the request is in flight.
  const stale = data !== null && (sim.kind === "loading" || (sim.kind === "ok" && sim.key !== requestKey));
  const failure = sim.kind === "error" ? sim.failure : null;
  const apiDown = failure !== null && (unreachable(failure) || failure.status === 404);
  const controlsDisabled = horizon === null || apiDown;

  // Validated against SIMULATED_LABELS / BUSINESS_LABELS before `data` is ever set.
  const labels: ProvenanceInput[] = data
    ? [data.provenance as ProvenanceInput, data.business_provenance as ProvenanceInput]
    : ["NOT AVAILABLE"];
  const business = labels[1] ?? "NOT AVAILABLE";
  /** Did the response on screen answer a request with an applied plan? */
  const dataPlanned = sim.kind === "ok" ? sim.planned : sim.kind === "loading" ? (sim.meta?.planned ?? false) : false;
  const drawKey = String(sim.kind === "ok" ? sim.seq : sim.kind === "loading" ? (sim.meta?.seq ?? 0) : 0);

  // The optimizer's answer for exactly the current inputs (#127: no earlier plan is ever shown while one is pending).
  const optPending = opt.kind === "loading" || (opt.kind === "ok" && opt.key !== optKey);
  const optCurrent = opt.kind === "ok" && opt.key === optKey ? opt.data : null;
  const graphPlan = useMemo<GraphPlan | null>(
    () =>
      optCurrent && optCurrent.status === "OPTIMAL" && optCurrent.actions
        ? { actions: optCurrent.actions, applied: activePlan !== null }
        : null,
    [optCurrent, activePlan],
  );

  const floor = data ? floorOf(data) : null;
  const unplannedCash = unplanned !== null && unplanned.key === scenarioKey ? unplanned.result.cash : null;
  const timeline: TimelineSeries[] = data
    ? [
        { id: "baseline", label: "baseline", values: data.baseline.cash, source: "POST /api/simulate" },
        {
          id: "scenario",
          label: "scenario",
          values: dataPlanned ? unplannedCash : data.result.cash,
          source: "POST /api/simulate",
        },
        {
          id: "plan",
          label: "with recovery plan",
          values: optCurrent?.status === "OPTIMAL" ? optCurrent.cash : null,
          source: "POST /api/optimize",
        },
      ]
    : [];

  const update = (patch: Partial<ScenarioControls>) => {
    setControls((c) => ({ ...c, ...patch }));
    setMode((m) =>
      m.kind === "preset" ? { ...m, touched: new Set([...m.touched, ...(Object.keys(patch) as ControlKey[])]) } : m,
    );
  };

  const choosePreset = (id: string) => {
    if (id === "") {
      setMode({ kind: "custom" });
      return;
    }
    if (scenarios.kind !== "ok" || horizon === null) return;
    const preset = scenarios.data.presets.find((p) => p.id === id);
    if (!preset) return;
    setIncoming(null);
    applyPreset(preset);
  };

  /** Fill the sliders from a preset's shock and send it exactly (also used by the Judge's Challenge, #123). */
  const applyPreset = (preset: ScenarioPreset, meta?: { challenge: Challenge; surprisePick: number | null }) => {
    if (horizon === null) return;
    if (meta) {
      const c = meta.challenge;
      setIncoming((prev) => ({
        seq: (prev?.seq ?? 0) + 1,
        id: c.id,
        name: c.name,
        description: c.description,
        rangeCitation: c.range_citation,
        surprisePick: meta.surprisePick,
      }));
    }
    setControls((c) => controlsFromShock(preset.shock, horizon, c));
    // Setting `mode` changes `scenario`, hence both request keys: /api/simulate and /api/optimize (#56) re-run through
    // their usual debounced effects. A plan applied for the previous shock no longer matches `optKey`, so it is dropped.
    setMode({ kind: "preset", preset, touched: new Set() });
  };

  const reset = () => {
    setControls(NO_SHOCK);
    setMode({ kind: "custom" });
  };

  const T = horizon ?? 1;
  const d = sent.demand ?? null;
  const r = sent.rate ?? null;
  const s = sent.supplier ?? null;
  // A partial-availability preset (0 < κ_t < 1) cannot be expressed as whole outage weeks: lock those sliders.
  const outageLocked =
    mode.kind === "preset" && !!mode.preset.shock.supplier && !isWholeWeekOutage(mode.preset.shock.supplier.availability, T);
  const outageCount = s ? outageWeekCount(s.availability, T) : 0;
  const outageFirst = s && Array.isArray(s.availability) ? s.availability.findIndex((k) => k < 1) + 1 : 0;

  return (
    // Projector layout (xl): readout strip, then graph (8 cols) beside a compact input column (4 cols), so readouts,
    // the graph with its badges and every slider fit in one 1920×1080 viewport. DOM order is also the phone order.
    <div className="grid grid-cols-1 gap-5 xl:grid-cols-12">
      <Readouts className="xl:col-span-12" data={data} stale={stale} labels={labels} sim={sim} onRetry={() => setRetry((n) => n + 1)} />

      <Panel
        code="C.0"
        title="Dependency network"
        provenance={data ? labels : "ILLUSTRATIVE"}
        provenanceDetail={data ? undefined : "Structure only, no values"}
        className="xl:col-span-8"
        bodyClassName="flex flex-col p-0"
      >
        <ShockwaveGraph
          className="flex-1"
          data={data}
          stale={stale}
          protect={protect}
          plan={graphPlan}
          incomingActive={incoming !== null}
          overlay={
            <>
              {incoming ? <IncomingShock key={incoming.seq} info={incoming} reduce={reduce} onDone={dismissIncoming} /> : null}
              <OptimizerChip opt={opt} pending={optPending} current={optCurrent} applied={activePlan !== null} protect={protect} reduce={reduce} />
            </>
          }
        />
        <p className="border-t border-line px-4 py-2 text-xs leading-relaxed text-muted">
          {data ? (
            <>
              Node values: the API&apos;s Δ = scenario − baseline at its peak week (MATH_MODEL §5) for{" "}
              <span className="text-text-2">{data.deltas.scenario_name}</span> vs{" "}
              <span className="text-text-2">{data.deltas.baseline_name}</span>. When a response lands, a pulse follows the
              API&apos;s edges in dependency order and each changed node counts from its previous API value to the new
              one. Edge width and glow scale with the source node&apos;s |Δ| relative to its own range; green edges and
              chips are the recovery plan from POST /api/optimize.
            </>
          ) : (
            <>
              Nodes and edges follow MATH_MODEL §2–§3. No magnitudes are shown until{" "}
              <code className="font-mono text-text-2">POST /api/simulate</code> answers.
            </>
          )}
        </p>
      </Panel>

      <Panel
        code="C.1"
        title="Scenario inputs"
        provenance={data ? business : "NOT AVAILABLE"}
        provenanceDetail={data ? "inputs" : undefined}
        className="xl:col-span-4 xl:row-span-2"
        bodyClassName="px-4 py-3"
      >
        <fieldset disabled={controlsDisabled} className="flex flex-col gap-3 disabled:opacity-60">
          <legend className="sr-only">Scenario shock inputs sent to POST /api/simulate</legend>

          <JudgeChallenge activeId={mode.kind === "preset" ? mode.preset.id : null} onPick={applyPreset} disabled={controlsDisabled} />

          <PresetPicker scenarios={scenarios} mode={mode} onChoose={choosePreset} disabled={controlsDisabled} />

          <ControlGroup title="Demand shock" note="δ, window [t1, t2], recovery ρ · MATH_MODEL §1">
            <Range id="cascade-demand-delta" label="Drop δ" value={controls.demandPct} min={0} max={90} display={d ? fmt.pct(d.delta) : "0%"} onChange={(v) => update({ demandPct: v })} />
            <Range id="cascade-demand-start" label="Start t1" value={controls.demandStart} min={1} max={T} display={`wk ${d?.start_week ?? controls.demandStart}`} onChange={(v) => update({ demandStart: v })} inactive={!d} />
            <Range id="cascade-demand-end" label="End t2" value={controls.demandEnd} min={1} max={T} display={`wk ${d?.end_week ?? controls.demandEnd}`} onChange={(v) => update({ demandEnd: v })} inactive={!d} />
            <Range id="cascade-demand-recovery" label="Recovery ρ" value={controls.demandRecovery} min={0} max={horizon ?? 0} display={`${d ? (d.recovery_weeks ?? 0) : controls.demandRecovery} wk`} onChange={(v) => update({ demandRecovery: v })} inactive={!d} />
          </ControlGroup>

          <ControlGroup title="Rate shock" note="Δr from week t_r · MATH_MODEL §1">
            <Range id="cascade-rate-delta" label="Δr" value={controls.rateBp} min={-300} max={800} step={25} display={r ? fmt.bp(r.delta_rate) : "0 bp"} onChange={(v) => update({ rateBp: v })} />
            <Range id="cascade-rate-start" label="Start t_r" value={controls.rateStart} min={1} max={T} display={`wk ${r?.start_week ?? controls.rateStart}`} onChange={(v) => update({ rateStart: v })} inactive={!r} />
          </ControlGroup>

          <ControlGroup title="Supplier outage" note="κ_t = 0 in outage weeks; λ_t = φ(1 − κ_t) · MATH_MODEL §1">
            <Range id="cascade-outage-weeks" label="Outage" value={controls.outageWeeks} min={0} max={horizon === null ? 0 : maxOutageWeeks(controls.outageStart, horizon)} display={outageLocked ? "κ partial" : `${outageCount} wk`} onChange={(v) => update({ outageWeeks: v })} disabled={outageLocked} />
            <Range id="cascade-outage-start" label="Start" value={controls.outageStart} min={1} max={T} display={`wk ${outageFirst > 0 ? outageFirst : controls.outageStart}`} onChange={(v) => update({ outageStart: v })} inactive={!s} disabled={outageLocked} />
            <Range id="cascade-outage-share" label="Dependent φ" value={controls.dependentPct} min={0} max={100} step={5} display={s ? fmt.pct(s.dependent_share) : `${controls.dependentPct}%`} onChange={(v) => update({ dependentPct: v })} inactive={!s} />
            <p className="font-mono text-[10px] leading-snug text-muted">
              {outageLocked
                ? "Preset κ_t is partial, not whole weeks: outage sliders are locked so it is sent exactly. Reset to edit."
                : `φ default ${DEFAULT_DEPENDENT_PCT}% = demo business φ (MATH_MODEL §10, assumed; signed off 2026-11-12).`}
            </p>
          </ControlGroup>

          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line/70 pt-3">
            <button
              type="button"
              onClick={reset}
              className="rounded-md border border-line-strong px-3 py-1.5 font-mono text-[11px] uppercase tracking-[0.12em] text-text-2 hover:bg-hover hover:text-text disabled:cursor-not-allowed"
            >
              Reset to baseline
            </button>
            <span className="font-mono text-[10px] text-muted">debounced {DEBOUNCE_MS} ms · one request in flight</span>
          </div>
        </fieldset>

        <PayrollToggle
          checked={protect}
          disabled={controlsDisabled}
          onChange={(v) => setProtect(v)}
          cap={(opt.kind === "ok" ? opt.data : opt.kind === "loading" ? opt.last : null)?.payroll_cut_cap ?? null}
        />

        {apiDown ? (
          <p className="mt-3 text-xs leading-relaxed text-muted">
            Inputs are disabled: the simulator at <code className="font-mono text-text-2">{API_BASE}</code> is not
            answering.
          </p>
        ) : horizon === null && sim.kind === "loading" ? (
          <p className="mt-3 text-xs leading-relaxed text-muted">
            Inputs unlock when the API reports the horizon T (request in flight).
          </p>
        ) : null}
      </Panel>

      <Panel
        code="C.4"
        title={`Cash path · ${data ? data.result.horizon_weeks : "T"} weeks`}
        provenance={labels}
        className="xl:col-span-8"
        bodyClassName="px-4 py-3"
      >
        {data ? (
          <CashTimeline
            weeks={data.result.weeks}
            series={timeline}
            floor={
              floor
                ? { ...floor, of: dataPlanned ? "the scenario with the recovery plan applied" : "the scenario" }
                : null
            }
            stale={stale}
            reduce={reduce}
            drawKey={drawKey}
          />
        ) : (
          <NotAvailable note="No cash path is drawn until POST /api/simulate answers." />
        )}
      </Panel>

      <RecoveryPlan
        opt={opt}
        stale={opt.kind === "loading" || (opt.kind === "ok" && opt.key !== optKey)}
        applied={activePlan !== null}
        onApply={() => {
          if (opt.kind === "ok" && opt.key === optKey && opt.data.plan) setApplied({ optKey, plan: opt.data.plan });
        }}
        onClear={() => setApplied(null)}
        onRetry={() => setOptRetry((n) => n + 1)}
        reduce={reduce}
      />
    </div>
  );
}

function Readouts({
  className,
  data,
  stale,
  labels,
  sim,
  onRetry,
}: {
  className?: string;
  data: SimulateResponse | null;
  stale: boolean;
  labels: ProvenanceInput[];
  sim: SimState;
  onRetry: () => void;
}) {
  const r = data?.result ?? null;
  const b = data?.baseline ?? null;
  const d = data?.deltas ?? null;
  const prov: ProvenanceInput = labels[0] ?? "NOT AVAILABLE";

  return (
    <Panel code="C.2" title="Financial readout" provenance={labels} className={className} bodyClassName="flex flex-col gap-3 px-5 py-3">
      <RequestStatus sim={sim} stale={stale} data={data} onRetry={onRetry} />
      <div className="grid grid-cols-1 gap-x-8 gap-y-5 sm:grid-cols-2 xl:grid-cols-4">
        <FinancialReadout
          label="Minimum cash"
          value={r ? r.min_cash : null}
          format="usd"
          provenance={prov}
          size="fit"
          dimmed={stale}
          sublabel={data ? <MinCashSublabel data={data} /> : undefined}
        />
        <FinancialReadout
          label="Week of minimum cash"
          value={r ? r.min_cash_week : null}
          format="weeks"
          prefix="week"
          unit={r ? `of ${r.horizon_weeks}` : undefined}
          provenance={prov}
          size="fit"
          dimmed={stale}
          sublabel={b ? `baseline: week ${b.min_cash_week}` : undefined}
        />
        <CashNegativeReadout data={data} provenance={prov} dimmed={stale} />
        <FinancialReadout
          label="Ending cash"
          value={r ? r.ending_cash : null}
          format="usd"
          provenance={prov}
          size="fit"
          dimmed={stale}
          sublabel={r && b && d ? `week ${r.horizon_weeks} · ${usdDelta(d.ending_cash_delta)} vs baseline ${usd(b.ending_cash)}` : undefined}
        />
      </div>
    </Panel>
  );
}

function RequestStatus({
  sim,
  stale,
  data,
  onRetry,
}: {
  sim: SimState;
  stale: boolean;
  data: SimulateResponse | null;
  onRetry: () => void;
}) {
  let tone = "text-muted";
  let body: ReactNode;
  const context = data ? (
    <span className="text-muted">
      {" "}
      · <span className="text-text-2">{data.result.scenario_name}</span>{sim.kind === "ok" && sim.planned ? <span className="text-viable"> with recovery plan</span> : null} vs {data.baseline.scenario_name} · C_0{" "}
      {usd(data.result.cash_0)} · T = {data.result.horizon_weeks} wk · fictional demo business
    </span>
  ) : null;
  if (sim.kind === "loading") {
    body = (
      <>
        <span className="text-info">●</span> POST /api/simulate · request in flight
        {sim.last ? " · previous response shown dimmed" : ""}
      </>
    );
  } else if (sim.kind === "ok") {
    body = (
      <>
        <span className="text-viable">●</span> POST /api/simulate · 200 · {sim.ms} ms · {TIME.format(sim.at)}
        {stale ? " · input changed, request pending (debounce)" : ""}
        {context}
      </>
    );
  } else {
    const f = sim.failure;
    tone = "text-fail";
    const head =
      f.kind === "validation"
        ? `422 rejected by the API${f.code ? ` · ${f.code}` : ""}`
        : f.status === 404
          ? "404 · this API build does not serve POST /api/simulate (issue #25)"
          : f.kind === "network" || f.kind === "timeout"
            ? `API unreachable at ${API_BASE} (${f.error})`
            : f.kind === "malformed"
              ? "Response did not match the simulate contract"
              : `HTTP ${f.status ?? "error"}${f.code ? ` · ${f.code}` : ""}`;
    body = (
      <span className="flex flex-col gap-1">
        <span>
          <span aria-hidden="true">■ </span>
          {head}
        </span>
        {f.kind === "validation" || f.kind === "malformed" || (f.kind === "http" && f.status !== 404) ? (
          <span className="whitespace-pre-wrap break-words text-text-2">{f.error}</span>
        ) : null}
        <span className="text-muted">Readouts are NOT AVAILABLE for this request; no earlier figures are carried over.</span>
      </span>
    );
  }
  return (
    <div
      className={`flex flex-wrap items-start justify-between gap-3 font-mono text-[11px] leading-relaxed ${tone}`}
      role="status"
      aria-live="polite"
    >
      <div className="min-w-0">{body}</div>
      {sim.kind === "error" ? (
        <button
          type="button"
          onClick={onRetry}
          className="shrink-0 rounded-md border border-line-strong px-2.5 py-1 font-mono text-[10.5px] uppercase tracking-[0.12em] text-text-2 hover:bg-hover hover:text-text"
        >
          Retry request
        </button>
      ) : null}
    </div>
  );
}

function PresetPicker({
  scenarios,
  mode,
  onChoose,
  disabled,
}: {
  scenarios: ScenariosState;
  mode: Mode;
  onChoose: (id: string) => void;
  disabled: boolean;
}) {
  const presets = scenarios.kind === "ok" ? scenarios.data.presets : [];
  const active = mode.kind === "preset" ? mode.preset : null;
  const edited = mode.kind === "preset" && mode.touched.size > 0;
  /** A Judge's Challenge (#123) is not a catalog preset; its description is already shown in the challenge block. */
  const challenge = active !== null && !presets.some((p) => p.id === active.id);
  let status: string;
  if (scenarios.kind === "loading") status = "GET /api/scenarios · request in flight";
  else if (scenarios.kind === "error")
    status =
      scenarios.failure.status === 404
        ? "Presets NOT AVAILABLE: GET /api/scenarios is not served by this API build"
        : `Presets NOT AVAILABLE: ${scenarios.failure.error}`;
  else if (presets.length === 0)
    status = scenarios.data.note ?? "Presets NOT AVAILABLE: the API lists no scenarios yet";
  else status = `${presets.length} named scenario${presets.length === 1 ? "" : "s"} from GET /api/scenarios`;

  return (
    <div className="flex flex-col gap-1.5">
      <div className="grid grid-cols-[6.5rem_1fr] items-center gap-3">
        <label htmlFor="cascade-preset" className="kicker">
          Preset
        </label>
        <select
          id="cascade-preset"
          value={active?.id ?? ""}
          onChange={(e) => onChoose(e.target.value)}
          disabled={disabled || presets.length === 0}
          className="w-full min-w-0 rounded-md border border-line-strong bg-bg px-2.5 py-1.5 font-mono text-xs text-text disabled:cursor-not-allowed disabled:opacity-60"
        >
          <option value="">Custom (sliders below)</option>
          {active && challenge ? (
            <option value={active.id}>Judge&apos;s Challenge: {active.name}</option>
          ) : null}
          {presets.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </select>
      </div>
      <p className="font-mono text-[10px] text-muted">{status}</p>
      {active ? (
        <p className="text-xs leading-snug text-text-2">
          {challenge ? null : <>{active.rationale ?? "No rationale provided."} </>}
          <span className="text-muted">
            {edited
              ? "Edited: only the sliders you moved override the preset; every other field is sent exactly as served."
              : `Sent exactly as served${active.provenance ? ` (${active.provenance})` : ""}.`}
          </span>
        </p>
      ) : null}
    </div>
  );
}

function ControlGroup({ title, note, children }: { title: string; note: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-1.5 border-t border-line/70 pt-2.5">
      <div className="flex flex-wrap items-baseline justify-between gap-x-2">
        <span className="text-[13px] font-medium uppercase tracking-[0.08em] text-text">{title}</span>
        <span className="font-mono text-[10px] tracking-[0.02em] text-muted">{note}</span>
      </div>
      {children}
    </div>
  );
}

function Range({
  id,
  label,
  value,
  min,
  max,
  step = 1,
  display,
  onChange,
  inactive = false,
  disabled = false,
}: {
  id: string;
  label: string;
  value: number;
  min: number;
  max: number;
  step?: number;
  /** The value actually sent in the request (or the slider position when this shock is off). */
  display: string;
  onChange: (v: number) => void;
  /** The shock this belongs to is off, so this value is not sent. Muted text (≥ 4.5:1), not opacity. */
  inactive?: boolean;
  disabled?: boolean;
}) {
  const tone = inactive ? "text-muted" : "text-text-2";
  return (
    <div className="grid grid-cols-[6.5rem_1fr_4.75rem] items-center gap-3">
      <label htmlFor={id} className={`font-mono text-[11px] tracking-[0.04em] ${tone}`}>
        {label}
      </label>
      <input
        id={id}
        type="range"
        min={min}
        max={Math.max(min, max)}
        step={step}
        value={Math.min(Math.max(value, min), Math.max(min, max))}
        onChange={(e) => onChange(Number(e.target.value))}
        aria-valuetext={display}
        disabled={disabled}
        className="h-1.5 w-full cursor-pointer accent-[var(--accent)] disabled:cursor-not-allowed disabled:opacity-50"
      />
      <output htmlFor={id} className={`num text-right text-xs ${inactive ? "text-muted" : "text-text"}`}>
        {display}
      </output>
    </div>
  );
}

function PayrollToggle({
  checked,
  disabled,
  onChange,
  cap,
}: {
  checked: boolean;
  disabled: boolean;
  onChange: (v: boolean) => void;
  /** z̄ as served by POST /api/optimize; null until it answers. */
  cap: number | null;
}) {
  return (
    <div
      className={`mt-3 flex items-center justify-between gap-4 rounded-md border px-3 py-2.5 transition-[border-color,background-color] ${
        checked ? "border-viable/70 bg-[color-mix(in_srgb,var(--viable)_7%,transparent)]" : "border-line/70"
      }`}
    >
      <div className="flex flex-col gap-0.5">
        <span id="protect-payroll-label" className={`text-[13px] font-medium uppercase tracking-[0.08em] ${checked ? "text-viable" : "text-text"}`}>
          Protect payroll
        </span>
        <span id="protect-payroll-note" className="font-mono text-[10px] text-muted">
          {checked ? "On: the optimizer may not cut payroll (z_t = 0)" : payrollOffNote(cap)} · POST
          /api/optimize
        </span>
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-labelledby="protect-payroll-label"
        aria-describedby="protect-payroll-note"
        disabled={disabled}
        onClick={() => onChange(!checked)}
        className={`relative h-6 w-11 shrink-0 rounded-full border border-line-strong transition-colors disabled:cursor-not-allowed disabled:opacity-60 ${
          checked ? "border-viable bg-[var(--viable)]" : "bg-bg"
        }`}
      >
        <span
          className={`absolute top-1/2 size-4 -translate-y-1/2 rounded-full transition-[left] ${
            checked ? "left-[1.4rem] bg-bg" : "left-0.5 bg-muted"
          }`}
          aria-hidden="true"
        />
      </button>
    </div>
  );
}

/** Indeterminate bar: rendered only while a POST /api/optimize is pending (it carries no progress figure). */
function SolvingBar({ reduce, tone = "accent" }: { reduce: boolean; tone?: "accent" | "viable" }) {
  return (
    <div className="relative h-[3px] w-full overflow-hidden rounded-full bg-line" aria-hidden="true">
      <div
        className={`absolute inset-y-0 left-0 w-2/5 rounded-full ${tone === "viable" ? "bg-viable" : "bg-accent"} ${reduce ? "" : "fx-solving"}`}
      />
    </div>
  );
}

/**
 * Optimizer state over the network (#165), top right: solving (only while a request is pending or debouncing),
 * the plan on the graph, or NO FEASIBLE PLAN with the API's highest feasible floor. Text from the response only.
 */
function OptimizerChip({
  opt,
  pending,
  current,
  applied,
  protect,
  reduce,
}: {
  opt: OptState;
  pending: boolean;
  current: OptimizeResponse | null;
  applied: boolean;
  protect: boolean;
  reduce: boolean;
}) {
  const base =
    "pointer-events-none absolute right-3 top-3 z-20 hidden max-w-[min(22rem,calc(100%-1.5rem))] flex-col gap-1.5 rounded-md border bg-elevated/90 px-3 py-2 font-mono text-[10.5px] backdrop-blur-[12px] md:flex";
  if (pending)
    return (
      <div className={`${base} border-accent/50`} data-testid="optimizer-chip" data-state="solving">
        <p className="uppercase tracking-[0.14em] text-accent">
          Optimizer · solving{protect ? " · payroll locked" : ""}
        </p>
        <SolvingBar reduce={reduce} />
        <p className="text-muted">
          {opt.kind === "loading" ? "POST /api/optimize in flight" : "waiting for inputs to settle (debounce)"} · no earlier
          plan shown
        </p>
      </div>
    );
  if (opt.kind === "error")
    return (
      <div className={`${base} border-fail/60`} data-testid="optimizer-chip" data-state="error">
        <p className="uppercase tracking-[0.14em] text-fail">Optimizer NOT AVAILABLE</p>
        <p className="text-muted">See C.3 Recovery plan</p>
      </div>
    );
  if (!current) return null;
  if (current.status === "NO FEASIBLE PLAN")
    return (
      <div
        className={`${base} border-fail ${reduce ? "" : "fx-infeasible"}`}
        style={{ boxShadow: "0 0 0 1px color-mix(in srgb, var(--fail) 55%, transparent), 0 0 30px 0 color-mix(in srgb, var(--fail) 18%, transparent)" }}
        data-testid="optimizer-chip"
        data-state="infeasible"
      >
        <p className="font-semibold uppercase tracking-[0.14em] text-fail">■ No plan holds the floor</p>
        <p className="text-text-2">
          Highest floor a plan can hold{" "}
          <span className="num text-sm text-fail">
            {current.max_feasible_cash_floor === null ? "NOT AVAILABLE" : usdCentsFloor(current.max_feasible_cash_floor)}
          </span>
        </p>
        <p className="text-muted">{current.protect_payroll ? "with payroll protected · " : ""}solver answer in C.3</p>
      </div>
    );
  if (current.status !== "OPTIMAL") return null;
  const n = current.actions?.length ?? 0;
  return (
    <div className={`${base} border-viable/60`} data-testid="optimizer-chip" data-state="optimal">
      <p className="uppercase tracking-[0.14em] text-viable">
        Recovery plan · {applied ? "applied" : "proposed"}
      </p>
      <p className="text-text-2">
        {n === 0 ? "No action needed for this shock" : `${n} action${n === 1 ? "" : "s"} shown on the nodes they act on`}
        {current.min_cash !== null ? (
          <>
            {" "}
            · min C_t <span className="num text-text">{usd(current.min_cash)}</span>
          </>
        ) : null}
      </p>
    </div>
  );
}

const ACTION_LABELS: Record<string, string> = {
  use_backup_supplier: "Use backup supplier",
  defer_capex: "Defer non-critical capex",
  delay_expansion: "Delay expansion",
  purchase_cut: "Purchase cut",
  revolver_draw: "Revolver draw",
  revolver_repay: "Revolver repayment",
  payroll_cut: "Payroll cut",
};

function RecoveryPlan({
  opt,
  stale,
  applied,
  onApply,
  onClear,
  onRetry,
  reduce,
}: {
  opt: OptState;
  stale: boolean;
  applied: boolean;
  onApply: () => void;
  onClear: () => void;
  onRetry: () => void;
  reduce: boolean;
}) {
  // Only an answer to the current inputs is rendered. While the debounce runs or a request is in flight, the
  // previous plan is withheld: it may hold payroll cuts the switch now forbids, or be OPTIMAL where the new answer
  // is NO FEASIBLE PLAN.
  const pending = stale || opt.kind === "loading";
  const data = opt.kind === "ok" && !pending ? opt.data : null;
  const provenance: ProvenanceInput[] = data
    ? [data.provenance as ProvenanceInput, data.business_provenance as ProvenanceInput]
    : ["NOT AVAILABLE"];

  let status: ReactNode;
  if (opt.kind === "loading") status = <><span className="text-info">●</span> POST /api/optimize · request in flight</>;
  else if (opt.kind === "ok")
    status = (
      <>
        <span className="text-viable">●</span> POST /api/optimize · 200 · {opt.ms} ms · {TIME.format(opt.at)}
        {stale ? " · input changed, request pending (debounce)" : ""}
      </>
    );
  else
    status = (
      <span className="text-fail">
        ■ {opt.failure.kind === "validation" ? `422 rejected${opt.failure.code ? ` · ${opt.failure.code}` : ""}` : opt.failure.status === 404 ? "404 · this API build does not serve POST /api/optimize" : `${opt.failure.kind}${opt.failure.status ? ` · HTTP ${opt.failure.status}` : ""}`}
        {" · "}
        {opt.failure.error}
      </span>
    );

  return (
    <Panel code="C.3" title="Recovery plan" provenance={provenance} className="xl:col-span-12" bodyClassName="flex flex-col gap-3 px-5 py-3">
      <div className="flex flex-wrap items-start justify-between gap-3 font-mono text-[11px] leading-relaxed text-muted" role="status" aria-live="polite">
        <div className="min-w-0">
          {status}
          {data ? (
            <span>
              {" "}
              · <span className="text-text-2">{data.scenario_name}</span> · protect payroll{" "}
              {data.protect_payroll ? "on" : "off"} · least-harmful plan from the MILP (MATH_MODEL §4)
            </span>
          ) : null}
        </div>
        {opt.kind === "error" ? (
          <button type="button" onClick={onRetry} className="shrink-0 rounded-md border border-line-strong px-2.5 py-1 font-mono text-[10.5px] uppercase tracking-[0.12em] text-text-2 hover:bg-hover hover:text-text">
            Retry request
          </button>
        ) : null}
      </div>

      {data === null ? (
        <div data-testid="recovery-plan" data-status={pending ? "PENDING" : "NOT AVAILABLE"} className="flex flex-col gap-2.5">
          {pending ? (
            <div className="flex max-w-md flex-col gap-1.5">
              <p className="font-mono text-[11px] uppercase tracking-[0.14em] text-accent">MILP solving · scipy.optimize.milp</p>
              <SolvingBar reduce={reduce} />
            </div>
          ) : null}
          <NotAvailable
            note={
              pending
                ? "Solving for the current inputs… No earlier plan is shown while POST /api/optimize answers."
                : "No recovery plan is shown until POST /api/optimize answers this exact scenario."
            }
          />
        </div>
      ) : (
        <div data-testid="recovery-plan" data-status={data.status}>
          {data.status === "OPTIMAL" ? (
            <OptimalPlan data={data} applied={applied} onApply={onApply} onClear={onClear} />
          ) : data.status === "NO FEASIBLE PLAN" ? (
            <div
              className={`grid grid-cols-1 gap-4 rounded-md border border-fail bg-[color-mix(in_srgb,var(--fail)_7%,transparent)] px-5 py-4 text-fail lg:grid-cols-[1.6fr_1fr] ${reduce ? "" : "fx-infeasible"}`}
              style={{ boxShadow: "0 0 0 1px color-mix(in srgb, var(--fail) 55%, transparent), 0 0 30px 0 color-mix(in srgb, var(--fail) 18%, transparent)" }}
            >
              <div className="flex flex-col gap-1.5">
                <p className="font-mono text-xl font-semibold uppercase tracking-[0.14em] md:text-2xl">NO FEASIBLE PLAN</p>
                <p className="text-sm leading-relaxed text-text">{data.diagnostic ?? "NOT AVAILABLE: the API gave no diagnostic."}</p>
                <p className="font-mono text-[10px] text-text-2">Solver: {data.solver_message}</p>
              </div>
              <div className="flex flex-col gap-1 border-fail/40 lg:border-l lg:pl-4">
                <p className="kicker !text-fail">Highest floor a plan can hold:</p>
                <p className="num text-3xl font-medium leading-none tracking-tight md:text-4xl" data-testid="max-feasible-floor">
                  {data.max_feasible_cash_floor === null ? "NOT AVAILABLE" : usdCentsFloor(data.max_feasible_cash_floor)}
                </p>
                <p className="font-mono text-[10px] text-text-2">
                  {data.protect_payroll ? "with payroll protected (z_t = 0)" : "with payroll cuts allowed"} · API
                  max_feasible_cash_floor, rounded down to the cent
                </p>
              </div>
            </div>
          ) : (
            <div className="flex flex-col gap-1 rounded-md border border-fail/60 px-4 py-3 text-fail">
              <p className="font-mono text-sm font-semibold uppercase tracking-[0.12em]">SOLVER ERROR · no plan</p>
              <p className="whitespace-pre-wrap break-words font-mono text-xs">{data.solver_message}</p>
            </div>
          )}
        </div>
      )}
    </Panel>
  );
}

function OptimalPlan({
  data,
  applied,
  onApply,
  onClear,
}: {
  data: OptimizeResponse;
  applied: boolean;
  onApply: () => void;
  onClear: () => void;
}) {
  const actions = data.actions ?? [];
  const binding = data.binding_constraints ?? [];
  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-[2fr_1fr]">
      <div className="flex flex-col gap-1.5">
        <p className="kicker">Chosen actions ({actions.length})</p>
        {actions.length === 0 ? (
          <p className="text-sm text-text-2">No action needed: cash stays above the floor without any recovery action.</p>
        ) : (
          <ul className="max-h-48 overflow-y-auto font-mono text-xs text-text-2" data-testid="chosen-actions">
            {actions.map((a, i) => (
              <li key={`${a.action}-${a.week ?? "x"}-${i}`} className="flex justify-between gap-3 border-b border-line/50 py-0.5">
                <span>
                  {ACTION_LABELS[a.action] ?? a.action}
                  {a.week !== null ? ` · week ${a.week}` : ""}
                  {/* F15: a purchase cut reaches cash only when that week's supplier bill falls due (MATH_MODEL §3). */}
                  {a.action === "purchase_cut" && data.supplier_lag_weeks !== undefined ? (
                    <span className="text-muted"> (reaches cash {data.supplier_lag_weeks} wk later: supplier lag L_p)</span>
                  ) : null}
                </span>
                <span className="num text-text">
                  {a.amount !== null ? usd(a.amount) : "yes"}
                  {a.share !== null ? ` (z = ${a.share.toFixed(4)})` : ""}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
      <div className="flex flex-col gap-2 font-mono text-xs">
        <p>
          <span className="kicker">Min cash after plan</span>{" "}
          <span className="num text-text" data-testid="plan-min-cash">{data.min_cash === null ? "NOT AVAILABLE" : usd(data.min_cash)}</span>
          {data.min_cash_week !== null ? <span className="text-muted"> · week {data.min_cash_week}</span> : null}
        </p>
        {/* F16: lead with the disruption cost (non-cash harm, MATH_MODEL §4.4); the objective is cost − ε·μ. */}
        <p>
          <span className="kicker">Disruption cost</span>{" "}
          <span className="num text-text">
            {data.disruption_cost === null ? "NOT AVAILABLE" : data.disruption_cost.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
          </span>
          <span className="text-muted"> (non-cash)</span>
          <span className="text-muted">
            {" "}
            · objective{" "}
            {data.objective === null ? "NOT AVAILABLE" : data.objective.toLocaleString("en-US", { maximumFractionDigits: 2 })} = cost − ε ×
            min cash (MATH_MODEL §4)
          </span>
        </p>
        <div>
          <p className="kicker">Binding constraints</p>
          {binding.length === 0 ? (
            <p className="text-muted">none</p>
          ) : (
            <ul className="text-text-2" data-testid="binding-constraints">
              {binding.map((b) => (
                <li key={b}>{b}</li>
              ))}
            </ul>
          )}
        </div>
        <div className="flex flex-wrap gap-2 pt-1">
          {applied ? (
            <button type="button" onClick={onClear} className="rounded-md border border-line-strong px-3 py-1.5 font-mono text-[11px] uppercase tracking-[0.12em] text-text-2 hover:bg-hover hover:text-text">
              Remove plan
            </button>
          ) : (
            <button type="button" onClick={onApply} className="rounded-md border border-viable/70 px-3 py-1.5 font-mono text-[11px] uppercase tracking-[0.12em] text-viable hover:bg-hover">
              Apply plan
            </button>
          )}
          <span className="self-center text-[10px] text-muted">
            {applied ? "Readouts and graph: POST /api/simulate with recovery plan" : "Sends this plan to POST /api/simulate"}
          </span>
        </div>
      </div>
    </div>
  );
}
