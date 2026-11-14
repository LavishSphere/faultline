"use client";

import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  API_BASE,
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
} from "@/lib/api";
import { CascadeGraph, formatDelta } from "../CascadeGraph";
import { FinancialReadout } from "../FinancialReadout";
import { NotAvailable, Panel } from "../Panel";
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
  | { kind: "loading"; last: SimulateResponse | null }
  | { kind: "ok"; data: SimulateResponse; key: string; ms: number; at: Date; planned: boolean }
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
const USD = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
/** Whole-dollar display; rounding first so float noise never renders as "-$0". */
const usd = (n: number) => USD.format(Math.round(n) || 0);

export function CascadeWorkbench() {
  const [controls, setControls] = useState<ScenarioControls>(NO_SHOCK);
  const [mode, setMode] = useState<Mode>({ kind: "custom" });
  const [sim, setSim] = useState<SimState>({ kind: "loading", last: null });
  const [scenarios, setScenarios] = useState<ScenariosState>({ kind: "loading" });
  const [retry, setRetry] = useState(0);
  /** T from the most recent successful response; week sliders stay disabled until the API reports it. */
  const [horizon, setHorizon] = useState<number | null>(null);
  const lastGood = useRef<SimulateResponse | null>(null);
  const first = useRef(true);

  const [protect, setProtect] = useState(false);
  const [opt, setOpt] = useState<OptState>({ kind: "loading", last: null });
  const [applied, setApplied] = useState<Applied | null>(null);
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
  }, [optKey, retry]);

  // One in-flight /api/simulate at a time: a newer input aborts the older request before it can land.
  useEffect(() => {
    const controller = new AbortController();
    const body = JSON.parse(requestKey) as SimulateRequest;
    const delay = first.current ? 0 : DEBOUNCE_MS;
    first.current = false;
    const timer = setTimeout(async () => {
      setSim({ kind: "loading", last: lastGood.current });
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
        setHorizon(res.data.result.horizon_weeks);
        setSim({ kind: "ok", data: res.data, key: requestKey, ms: Math.round(performance.now() - started), at: new Date(), planned: body.plan !== undefined });
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
    setControls((c) => controlsFromShock(preset.shock, horizon, c));
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
        <CascadeGraph
          className="flex-1"
          deltas={data?.deltas ?? null}
          baseline={data?.baseline ?? null}
          result={data?.result ?? null}
          stale={stale}
        />
        <p className="border-t border-line px-4 py-2 text-xs leading-relaxed text-muted">
          {data ? (
            <>
              Node values: the API&apos;s Δ = scenario − baseline at its peak week (MATH_MODEL §5) for{" "}
              <span className="text-text-2">{data.deltas.scenario_name}</span> vs{" "}
              <span className="text-text-2">{data.deltas.baseline_name}</span>. Edge width and glow scale with the source
              node&apos;s |Δ| relative to its own range.
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
        className="xl:col-span-4"
        bodyClassName="px-4 py-3"
      >
        <fieldset disabled={controlsDisabled} className="flex flex-col gap-3 disabled:opacity-60">
          <legend className="sr-only">Scenario shock inputs sent to POST /api/simulate</legend>

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
                : `φ default ${DEFAULT_DEPENDENT_PCT}% = demo business φ (MATH_MODEL §10, assumed placeholder).`}
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

      <RecoveryPlan
        opt={opt}
        stale={opt.kind === "loading" || (opt.kind === "ok" && opt.key !== optKey)}
        applied={activePlan !== null}
        onApply={() => {
          if (opt.kind === "ok" && opt.key === optKey && opt.data.plan) setApplied({ optKey, plan: opt.data.plan });
        }}
        onClear={() => setApplied(null)}
        onRetry={() => setRetry((n) => n + 1)}
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
  const delta = (n: number) => formatDelta(n, "usd");
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
          sublabel={r && b && d ? `${delta(d.min_cash_delta)} vs baseline ${usd(b.min_cash)}` : undefined}
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
        <FinancialReadout
          label="Runway"
          value={r ? (r.runway_week === null ? { above: r.horizon_weeks } : r.runway_week) : null}
          format="weeks"
          prefix="week"
          unit={r && r.runway_week === null ? "weeks" : undefined}
          provenance={prov}
          size="fit"
          dimmed={stale}
          sublabel={
            r && b
              ? `first week C_t < 0 · API “${r.runway_label}” · baseline “${b.runway_label}”`
              : "First week with C_t < 0; “> T weeks” if cash stays ≥ 0."
          }
        />
        <FinancialReadout
          label="Ending cash"
          value={r ? r.ending_cash : null}
          format="usd"
          provenance={prov}
          size="fit"
          dimmed={stale}
          sublabel={r && b && d ? `week ${r.horizon_weeks} · ${delta(d.ending_cash_delta)} vs baseline ${usd(b.ending_cash)}` : undefined}
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
          {active.rationale ?? "No rationale provided."}{" "}
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
}: {
  checked: boolean;
  disabled: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <div className="mt-3 flex items-center justify-between gap-4 border-t border-line/70 pt-3">
      <div className="flex flex-col gap-0.5">
        <span id="protect-payroll-label" className="text-[13px] font-medium uppercase tracking-[0.08em] text-text">
          Protect payroll
        </span>
        <span id="protect-payroll-note" className="font-mono text-[10px] text-muted">
          {checked ? "On: the optimizer may not cut payroll (z_t = 0)" : "Off: payroll cuts allowed up to z̄"} · POST
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
          checked ? "bg-[var(--accent)]" : "bg-bg"
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
}: {
  opt: OptState;
  stale: boolean;
  applied: boolean;
  onApply: () => void;
  onClear: () => void;
  onRetry: () => void;
}) {
  const data = opt.kind === "ok" ? opt.data : opt.kind === "loading" ? opt.last : null;
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
        <NotAvailable
          endpoint="optimize"
          note="No recovery plan is shown until POST /api/optimize answers this exact scenario."
        />
      ) : (
        <div className={stale ? "opacity-60" : undefined} data-testid="recovery-plan" data-status={data.status}>
          {data.status === "OPTIMAL" ? (
            <OptimalPlan data={data} applied={applied} canApply={!stale} onApply={onApply} onClear={onClear} />
          ) : data.status === "NO FEASIBLE PLAN" ? (
            <div className="flex flex-col gap-1.5 rounded-md border border-fail/60 px-4 py-3 text-fail">
              <p className="font-mono text-sm font-semibold uppercase tracking-[0.12em]">NO FEASIBLE PLAN</p>
              <p className="text-sm leading-relaxed">{data.diagnostic ?? "NOT AVAILABLE: the API gave no diagnostic."}</p>
              <p className="font-mono text-xs">
                Smallest feasible floor:{" "}
                <span className="num" data-testid="max-feasible-floor">
                  {data.max_feasible_cash_floor === null ? "NOT AVAILABLE" : usd(data.max_feasible_cash_floor)}
                </span>
              </p>
              <p className="font-mono text-[10px] text-text-2">Solver: {data.solver_message}</p>
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
  canApply,
  onApply,
  onClear,
}: {
  data: OptimizeResponse;
  applied: boolean;
  canApply: boolean;
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
        <p>
          <span className="kicker">Objective</span>{" "}
          <span className="num text-text">{data.objective === null ? "NOT AVAILABLE" : data.objective.toLocaleString("en-US", { maximumFractionDigits: 2 })}</span>
          {data.disruption_cost !== null ? (
            <span className="text-muted"> · disruption cost {data.disruption_cost.toLocaleString("en-US", { maximumFractionDigits: 2 })}</span>
          ) : null}
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
            <button type="button" onClick={onApply} disabled={!canApply} className="rounded-md border border-viable/70 px-3 py-1.5 font-mono text-[11px] uppercase tracking-[0.12em] text-viable hover:bg-hover disabled:cursor-not-allowed disabled:opacity-50">
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
