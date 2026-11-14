"use client";

import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  optimize,
  simulate,
  type ApiFailure,
  type OptimizeResponse,
  type ScenarioShock,
  type SimulateResponse,
} from "@/lib/api";
import {
  DEFAULTS_NOTE,
  SUGGESTION_LABEL,
  shockFromValues,
  type ExploreAnalysis,
  type ExploreGuidanceCategory,
  type ExploreGuidanceParam,
  type ShockBlock,
  type ShockValues,
  type ValueSource,
} from "@/lib/explore";
import { CascadeGraph, formatDelta } from "../CascadeGraph";
import { FinancialReadout } from "../FinancialReadout";
import { NotAvailable, Panel } from "../Panel";
import type { ProvenanceInput } from "../ProvenanceBadge";
import { fmt } from "../cascade/scenarioInputs";

/**
 * LIVE EXPLORE scenario (issue #61): the model's suggestion as editable INPUTS, then the human's confirmation, then
 * POST /api/simulate and POST /api/optimize (#47) for exactly the confirmed shock and Protect payroll setting.
 * Nothing is computed here: the browser maps the confirmed inputs to a ScenarioShock (the guidance file's own
 * mapping) and every figure shown is read from those responses. Before Confirm, no request is sent; after an edit,
 * the old plan is withheld until the human confirms again.
 */

type Origin = ValueSource | "human";
type Key = `${ShockBlock}.${string}`;

type SimState =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "ok"; data: SimulateResponse }
  | { kind: "error"; failure: ApiFailure };

type OptState =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "ok"; data: OptimizeResponse }
  | { kind: "error"; failure: ApiFailure };

const SIMULATED_LABELS = new Set(["SIMULATED"]);
const BUSINESS_LABELS = new Set(["SYNTHETIC", "ILLUSTRATIVE"]);

const PARAM_LABEL: Record<string, string> = {
  delta_rate: "Rate rise Δr",
  delta: "Demand drop δ",
  availability_during_outage: "Supplier availability κ",
  dependent_share: "Dependent share φ",
  start_week: "Start week",
  duration_weeks: "Duration",
  recovery_weeks: "Recovery ρ",
};
const BLOCK_LABEL: Record<ShockBlock, string> = {
  rate: "Rate shock",
  demand: "Demand shock",
  supplier: "Supplier outage",
};
const ORIGIN_LABEL: Record<Origin, string> = {
  model: "Model-suggested",
  model_clamped: "Model-suggested, moved into range",
  guidance_default: "Guidance default",
  human: "Edited by you",
};

const USD = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
const usd = (n: number) => USD.format(Math.round(n) || 0);

const keyOf = (p: { block: ShockBlock; param: string }): Key => `${p.block}.${p.param}`;

/** Display only: Δr in basis points, fractions in percent, weeks as integers. */
function show(p: ExploreGuidanceParam, v: number): string {
  if (p.param === "delta_rate") return fmt.bp(v);
  if (p.integer) return p.param === "start_week" ? `wk ${v}` : `${v} wk`;
  return fmt.pct(v);
}

/** Slider step in engine units: 5 bp, half a percentage point, or one week. */
function stepOf(p: ExploreGuidanceParam): number {
  if (p.integer) return 1;
  return p.param === "delta_rate" ? 0.0005 : 0.005;
}

interface Inputs {
  values: Record<Key, number>;
  origin: Record<Key, Origin>;
  enabled: ShockBlock[];
}

/** The suggestion's values when it is for this category, otherwise the category's guidance defaults. */
function inputsFor(category: ExploreGuidanceCategory, analysis: ExploreAnalysis): Inputs {
  const values = {} as Record<Key, number>;
  const origin = {} as Record<Key, Origin>;
  const suggestion = analysis.suggestion?.category_id === category.id ? analysis.suggestion : null;
  for (const p of category.params) {
    const s = suggestion?.parameters.find((x) => x.block === p.block && x.param === p.param);
    values[keyOf(p)] = s ? s.value : p.default;
    origin[keyOf(p)] = s ? s.source : "guidance_default";
  }
  return { values, origin, enabled: [...new Set(category.params.map((p) => p.block))] };
}

export function ExploreScenario({ analysis }: { analysis: ExploreAnalysis }) {
  const categories = analysis.guidance.categories;
  const horizon = analysis.guidance.horizon_weeks;
  const suggestion = analysis.suggestion;
  const [categoryId, setCategoryId] = useState(suggestion?.category_id ?? "");
  const category = categories.find((c) => c.id === categoryId) ?? null;
  const [inputs, setInputs] = useState<Inputs | null>(() => (category ? inputsFor(category, analysis) : null));
  const [protect, setProtect] = useState(false);
  const [confirmed, setConfirmed] = useState<{ shock: ScenarioShock; key: string; protect: boolean } | null>(null);
  const [sim, setSim] = useState<SimState>({ kind: "idle" });
  const [opt, setOpt] = useState<OptState>({ kind: "idle" });

  const choose = (id: string) => {
    setCategoryId(id);
    const next = categories.find((c) => c.id === id);
    setInputs(next ? inputsFor(next, analysis) : null);
  };

  const shock = useMemo<ScenarioShock | null>(() => {
    if (!category || !inputs) return null;
    const values: ShockValues = {};
    for (const p of category.params) {
      if (!inputs.enabled.includes(p.block)) continue;
      (values[p.block] ??= {})[p.param] = inputs.values[keyOf(p)]!;
    }
    return shockFromValues(`live explore: ${category.name} (human-confirmed inputs)`, values, horizon);
  }, [category, inputs, horizon]);
  const shockKey = shock ? JSON.stringify(shock) : "";
  const stale = confirmed !== null && confirmed.key !== shockKey;
  // The plan also answers the Protect payroll setting: flipping it withholds the plan until Confirm is pressed again.
  const planStale = stale || (confirmed !== null && confirmed.protect !== protect);

  const inflight = useRef<AbortController | null>(null);
  useEffect(() => () => inflight.current?.abort(), []);

  // POST /api/simulate and POST /api/optimize run only here: once each per click on Confirm, for exactly the
  // confirmed shock (and, for the optimizer, the Protect payroll setting at that moment).
  async function confirm() {
    if (!shock) return;
    inflight.current?.abort();
    const controller = new AbortController();
    inflight.current = controller;
    const protectNow = protect;
    setConfirmed({ shock, key: shockKey, protect: protectNow });
    setSim({ kind: "loading" });
    setOpt({ kind: "loading" });
    const [res, plan] = await Promise.all([
      simulate({ shock }, controller.signal),
      optimize({ shock, protect_payroll: protectNow }, controller.signal),
    ]);
    if (controller.signal.aborted) return;
    if (res.ok && (!SIMULATED_LABELS.has(res.data.provenance) || !BUSINESS_LABELS.has(res.data.business_provenance))) {
      setSim({ kind: "error", failure: { ok: false, kind: "malformed", error: "unknown provenance label" } });
    } else {
      setSim(res.ok ? { kind: "ok", data: res.data } : { kind: "error", failure: res });
    }
    if (plan.ok && (!SIMULATED_LABELS.has(plan.data.provenance) || !BUSINESS_LABELS.has(plan.data.business_provenance))) {
      setOpt({ kind: "error", failure: { ok: false, kind: "malformed", error: "unknown provenance label" } });
    } else {
      setOpt(plan.ok ? { kind: "ok", data: plan.data } : { kind: "error", failure: plan });
    }
  }

  const update = (p: ExploreGuidanceParam, v: number) =>
    setInputs((cur) =>
      cur ? { ...cur, values: { ...cur.values, [keyOf(p)]: v }, origin: { ...cur.origin, [keyOf(p)]: "human" } } : cur,
    );
  const toggle = (block: ShockBlock, on: boolean) =>
    setInputs((cur) =>
      cur ? { ...cur, enabled: on ? [...cur.enabled, block] : cur.enabled.filter((b) => b !== block) } : cur,
    );

  const blocks = category ? [...new Set(category.params.map((p) => p.block))] : [];
  const fromSuggestion = suggestion !== null && suggestion.category_id === categoryId;
  // MODEL-SUGGESTED only when the API says at least one number is the model's own (audit of #121, B1).
  const modelNumbers = fromSuggestion && suggestion.values_from_model > 0;
  const anyEnabled = inputs !== null && inputs.enabled.length > 0;

  return (
    <>
      <Panel
        code="X.3"
        title="Scenario inputs · confirm before the engine runs"
        provenance={modelNumbers ? ["MODEL-SUGGESTED", "ILLUSTRATIVE"] : ["ILLUSTRATIVE"]}
        provenanceDetail={modelNumbers ? "human to confirm" : category ? "guidance defaults" : "guidance ranges"}
        className="xl:col-span-5"
        bodyClassName="flex flex-col gap-4 px-5 py-4"
      >
        <p className="text-xs leading-relaxed text-muted">
          {modelNumbers ? (
            <>
              <span className="font-mono uppercase tracking-[0.08em] text-info">{SUGGESTION_LABEL}.</span> The local
              model proposed {suggestion.values_from_model} of these {suggestion.parameters.length} numbers from the
              cited evidence (each input below says which); every one is inside the finance owner&apos;s guidance range
              for its category. They are stress-test inputs for the SYNTHETIC demo business, not forecasts. Edit
              anything, then confirm.
            </>
          ) : fromSuggestion ? (
            <>
              <span className="font-mono uppercase tracking-[0.08em] text-muted">ILLUSTRATIVE.</span> {DEFAULTS_NOTE}{" "}
              The model chose this category from the cited evidence; every number is the finance owner&apos;s guidance
              default, not a model or market estimate. Edit anything, then confirm.
            </>
          ) : suggestion || category ? (
            <>
              Guidance defaults (ILLUSTRATIVE) for the category you chose; no model numbers. Edit them, then confirm.
            </>
          ) : (
            <>
              No model suggestion for this request. Choose a guidance category to start from its ILLUSTRATIVE defaults,
              edit them, then confirm.
            </>
          )}
        </p>

        <div className="flex flex-col gap-1.5">
          <label htmlFor="explore-category" className="kicker">
            Guidance category
          </label>
          <select
            id="explore-category"
            value={categoryId}
            onChange={(e) => choose(e.target.value)}
            className="w-full min-w-0 rounded-md border border-line-strong bg-bg px-2.5 py-2 text-sm text-text"
          >
            <option value="">Choose a category…</option>
            {categories.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
                {suggestion?.category_id === c.id ? " (model's choice)" : ""}
              </option>
            ))}
          </select>
          {category ? (
            <p className="text-xs leading-relaxed text-text-2">
              {category.news_trigger} <span className="text-muted">{category.timing_guidance}</span>
            </p>
          ) : null}
          {fromSuggestion && suggestion.notes.length ? (
            <ul className="list-disc pl-5 text-[11px] leading-relaxed text-muted">
              {suggestion.notes.map((n, i) => (
                <li key={i}>{n}</li>
              ))}
            </ul>
          ) : null}
        </div>

        {category && inputs
          ? blocks.map((block) => {
              const on = inputs.enabled.includes(block);
              return (
                <fieldset key={block} className="flex flex-col gap-3 border-t border-line/70 pt-3">
                  <legend className="sr-only">{BLOCK_LABEL[block]} inputs</legend>
                  <label className="flex items-center gap-2.5 text-[13px] font-medium uppercase tracking-[0.08em] text-text">
                    <input
                      type="checkbox"
                      checked={on}
                      onChange={(e) => toggle(block, e.target.checked)}
                      className="size-4 accent-[var(--accent)]"
                    />
                    {BLOCK_LABEL[block]}
                    {!on ? <span className="font-mono text-[10px] normal-case tracking-normal text-muted">off, not sent</span> : null}
                  </label>
                  {category.params
                    .filter((p) => p.block === block)
                    .map((p) => (
                      <ParamInput
                        key={keyOf(p)}
                        p={p}
                        value={inputs.values[keyOf(p)]!}
                        origin={inputs.origin[keyOf(p)]!}
                        rationale={
                          fromSuggestion
                            ? (suggestion.parameters.find((x) => x.block === p.block && x.param === p.param) ?? null)
                            : null
                        }
                        disabled={!on}
                        onChange={(v) => update(p, v)}
                      />
                    ))}
                </fieldset>
              );
            })
          : null}

        <PayrollSwitch checked={protect} onChange={setProtect} />

        <div className="flex flex-col gap-2 border-t border-line pt-4">
          <div className="flex flex-wrap items-center gap-3">
            <button
              type="button"
              disabled={!shock || !anyEnabled}
              onClick={() => void confirm()}
              className="rounded-md border border-accent/70 bg-accent-soft px-4 py-2.5 font-mono text-[11px] uppercase tracking-[0.14em] text-text transition-colors hover:bg-accent/20 disabled:cursor-not-allowed disabled:opacity-50"
            >
              Confirm inputs and run the engine
            </button>
            {category && fromSuggestion === false && suggestion?.category_id ? (
              <button
                type="button"
                onClick={() => choose(suggestion.category_id)}
                className="rounded-md border border-line-strong px-3 py-2 font-mono text-[11px] uppercase tracking-[0.12em] text-text-2 hover:bg-hover hover:text-text"
              >
                Back to the model&apos;s category
              </button>
            ) : null}
          </div>
          <p className="text-xs leading-relaxed text-muted">
            {!category
              ? "Choose a category first."
              : !anyEnabled
                ? "Every shock is off: turn one on to confirm."
                : stale
                  ? "Inputs changed since you confirmed. The results show the previously confirmed inputs; confirm again to re-run."
                  : planStale
                    ? "Protect payroll changed since you confirmed. The recovery plan is withheld; confirm again to re-solve."
                    : confirmed
                      ? "Confirmed. POST /api/simulate and POST /api/optimize compute every figure below."
                      : "Nothing has been computed yet. Confirm sends these inputs to POST /api/simulate and POST /api/optimize."}
          </p>
        </div>
      </Panel>

      <Results className="xl:col-span-7" sim={sim} stale={stale} confirmed={confirmed !== null} />

      <RecoveryPlan className="xl:col-span-12" opt={opt} stale={planStale} confirmed={confirmed !== null} />
    </>
  );
}

function ParamInput({
  p,
  value,
  origin,
  rationale,
  disabled,
  onChange,
}: {
  p: ExploreGuidanceParam;
  value: number;
  origin: Origin;
  rationale: { rationale: string | null; note: string | null; model_value: number | null } | null;
  disabled: boolean;
  onChange: (v: number) => void;
}) {
  const id = `explore-${p.block}-${p.param}`;
  const label = PARAM_LABEL[p.param] ?? p.param;
  const range = `Guidance range ${show(p, p.min)} to ${show(p, p.max)} · default ${show(p, p.default)}`;
  return (
    <div className="flex min-w-0 flex-col gap-1.5">
      <div className="flex items-baseline justify-between gap-3">
        <label htmlFor={id} className="font-mono text-[11px] tracking-[0.04em] text-text-2">
          {label}
        </label>
        <output htmlFor={id} className={`num text-sm ${disabled ? "text-muted" : "text-text"}`}>
          {show(p, value)}
        </output>
      </div>
      <input
        id={id}
        type="range"
        min={p.min}
        max={p.max}
        step={stepOf(p)}
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(Number(e.target.value))}
        aria-valuetext={show(p, value)}
        aria-describedby={`${id}-range`}
        className="h-1.5 w-full cursor-pointer accent-[var(--accent)] disabled:cursor-not-allowed disabled:opacity-50"
      />
      <p id={`${id}-range`} className="flex flex-wrap justify-between gap-x-3 font-mono text-[10px] leading-snug text-muted">
        <span>{range}</span>
        <span className={origin === "human" ? "text-text-2" : origin === "guidance_default" ? "" : "text-info"}>
          {ORIGIN_LABEL[origin]}
        </span>
      </p>
      {rationale && origin !== "human" && (rationale.rationale || rationale.note) ? (
        <p className="text-[11px] leading-snug text-muted">
          {rationale.rationale ? (
            <>
              <span className="uppercase tracking-[0.08em]">Model rationale:</span>{" "}
              <q className="text-text-2">{rationale.rationale}</q>{" "}
            </>
          ) : null}
          {rationale.note}
        </p>
      ) : null}
    </div>
  );
}

function Results({
  className,
  sim,
  stale,
  confirmed,
}: {
  className?: string;
  sim: SimState;
  stale: boolean;
  confirmed: boolean;
}) {
  const data = sim.kind === "ok" ? sim.data : null;
  const labels: ProvenanceInput[] = data
    ? [data.provenance as ProvenanceInput, data.business_provenance as ProvenanceInput]
    : ["NOT AVAILABLE"];
  const prov: ProvenanceInput = labels[0] ?? "NOT AVAILABLE";
  const r = data?.result ?? null;
  const b = data?.baseline ?? null;
  const d = data?.deltas ?? null;
  const delta = (n: number) => formatDelta(n, "usd");

  let status: string;
  let tone = "text-muted";
  if (!confirmed) status = "Waiting for you to confirm the inputs. No request has been sent.";
  else if (sim.kind === "loading") status = "POST /api/simulate · request in flight";
  else if (sim.kind === "error") {
    tone = "text-fail";
    const f = sim.failure;
    status = `${f.kind === "validation" ? `422 rejected by the API${f.code ? ` · ${f.code}` : ""}` : f.kind === "network" || f.kind === "timeout" ? "API unreachable" : `HTTP ${f.status ?? "error"}`}: ${f.error}. Readouts are NOT AVAILABLE.`;
  } else if (data) {
    status = `POST /api/simulate · 200 · ${data.result.scenario_name} vs ${data.baseline.scenario_name} · fictional demo business${stale ? " · inputs changed since, confirm again to re-run" : ""}`;
  } else status = "";

  return (
    <Panel
      code="X.4"
      title="Cascade · deterministic engine"
      provenance={labels}
      provenanceDetail={data ? "on confirmed inputs" : undefined}
      className={className}
      bodyClassName="flex flex-col gap-4 p-0"
    >
      <p role="status" aria-live="polite" className={`px-5 pt-4 font-mono text-[11px] leading-relaxed ${tone}`}>
        {status}
      </p>
      <div className="grid grid-cols-1 gap-x-8 gap-y-5 px-5 sm:grid-cols-2">
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
          label="Runway"
          value={r ? (r.runway_week === null ? { above: r.horizon_weeks } : r.runway_week) : null}
          format="weeks"
          prefix="week"
          unit={r && r.runway_week === null ? "weeks" : undefined}
          provenance={prov}
          size="fit"
          dimmed={stale}
          sublabel={r && b ? `first week C_t < 0 · API “${r.runway_label}” · baseline “${b.runway_label}”` : undefined}
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
        />
        <FinancialReadout
          label="Ending cash"
          value={r ? r.ending_cash : null}
          format="usd"
          provenance={prov}
          size="fit"
          dimmed={stale}
          sublabel={r && b && d ? `${delta(d.ending_cash_delta)} vs baseline ${usd(b.ending_cash)}` : undefined}
        />
      </div>
      {/* React Flow needs a definite height: the same flex chain as the CASCADE screen (a min-height alone gives 0). */}
      <div className="flex flex-1 flex-col border-t border-line">
        <CascadeGraph className="flex-1" deltas={d} baseline={b} result={r} stale={stale} />
      </div>
    </Panel>
  );
}

function PayrollSwitch({ checked, onChange }: { checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <div className="flex items-center justify-between gap-4 border-t border-line/70 pt-3">
      <div className="flex min-w-0 flex-col gap-0.5">
        <span id="explore-protect-label" className="text-[13px] font-medium uppercase tracking-[0.08em] text-text">
          Protect payroll
        </span>
        <span id="explore-protect-note" className="font-mono text-[10px] text-muted">
          {checked ? "On: the optimizer may not cut payroll (z_t = 0)" : "Off: payroll cuts allowed up to z̄"} · sent
          to POST /api/optimize on Confirm
        </span>
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-labelledby="explore-protect-label"
        aria-describedby="explore-protect-note"
        onClick={() => onChange(!checked)}
        className={`relative h-6 w-11 shrink-0 rounded-full border border-line-strong transition-colors ${
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

/**
 * POST /api/optimize answer for the CONFIRMED inputs, shown verbatim (same rendering rules as the CASCADE screen,
 * #127). A stale (inputs or Protect payroll changed since Confirm) or in-flight plan is withheld, never shown.
 */
function RecoveryPlan({
  className,
  opt,
  stale,
  confirmed,
}: {
  className?: string;
  opt: OptState;
  stale: boolean;
  confirmed: boolean;
}) {
  const pending = stale || opt.kind === "loading";
  const data = opt.kind === "ok" && !pending ? opt.data : null;
  const provenance: ProvenanceInput[] = data
    ? [data.provenance as ProvenanceInput, data.business_provenance as ProvenanceInput]
    : ["NOT AVAILABLE"];

  let status: ReactNode;
  if (!confirmed) status = "Waiting for you to confirm the inputs. No request has been sent.";
  else if (opt.kind === "loading") status = "POST /api/optimize · request in flight";
  else if (opt.kind === "error") {
    const f = opt.failure;
    status = (
      <span className="text-fail">
        {f.kind === "validation" ? `422 rejected${f.code ? ` · ${f.code}` : ""}` : f.status === 404 ? "404 · this API build does not serve POST /api/optimize" : `${f.kind}${f.status ? ` · HTTP ${f.status}` : ""}`}
        {" · "}
        {f.error}
      </span>
    );
  } else if (stale) status = "Inputs changed since you confirmed: plan withheld until you confirm again.";
  else if (data) {
    status = `POST /api/optimize · 200 · ${data.scenario_name} · protect payroll ${data.protect_payroll ? "on" : "off"} · least-harmful plan from the MILP (MATH_MODEL §4)`;
  } else status = "";

  return (
    <Panel code="X.5" title="Recovery plan · deterministic optimizer" provenance={provenance} className={className} bodyClassName="flex flex-col gap-3 px-5 py-4">
      <p role="status" aria-live="polite" className="font-mono text-[11px] leading-relaxed text-muted">
        {status}
      </p>
      {data === null ? (
        <div data-testid="explore-recovery-plan" data-status={pending && confirmed ? "PENDING" : "NOT AVAILABLE"}>
          <NotAvailable
            note={
              !confirmed
                ? "Confirm sends the inputs to POST /api/optimize; nothing is solved before that."
                : pending
                  ? "No earlier plan is shown while it does not answer the current inputs."
                  : "No recovery plan for this request."
            }
          />
        </div>
      ) : (
        <div data-testid="explore-recovery-plan" data-status={data.status}>
          {data.status === "OPTIMAL" ? (
            <OptimalPlan data={data} />
          ) : data.status === "NO FEASIBLE PLAN" ? (
            <div className="flex flex-col gap-1.5 rounded-md border border-fail/60 px-4 py-3 text-fail">
              <p className="font-mono text-sm font-semibold uppercase tracking-[0.12em]">NO FEASIBLE PLAN</p>
              <p className="text-sm leading-relaxed">{data.diagnostic ?? "NOT AVAILABLE: the API gave no diagnostic."}</p>
              <p className="font-mono text-xs">
                Highest floor a plan can hold:{" "}
                <span className="num" data-testid="explore-max-feasible-floor">
                  {data.max_feasible_cash_floor === null ? "NOT AVAILABLE" : usd(data.max_feasible_cash_floor)}
                </span>
              </p>
              <p className="font-mono text-[10px] text-text-2">Solver: {data.solver_message}</p>
            </div>
          ) : (
            <div className="flex flex-col gap-1 rounded-md border border-fail/60 px-4 py-3 text-fail">
              <p className="font-mono text-sm font-semibold uppercase tracking-[0.12em]">SOLVER ERROR · no plan</p>
              <p className="whitespace-pre-wrap font-mono text-xs">{data.solver_message}</p>
            </div>
          )}
        </div>
      )}
    </Panel>
  );
}

function OptimalPlan({ data }: { data: OptimizeResponse }) {
  const actions = data.actions ?? [];
  const binding = data.binding_constraints ?? [];
  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-[2fr_1fr]">
      <div className="flex min-w-0 flex-col gap-1.5">
        <p className="kicker">Chosen actions ({actions.length})</p>
        {actions.length === 0 ? (
          <p className="text-sm text-text-2">No action needed: cash stays above the floor without any recovery action.</p>
        ) : (
          <ul className="max-h-48 overflow-y-auto font-mono text-xs text-text-2" data-testid="explore-chosen-actions">
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
      <div className="flex min-w-0 flex-col gap-2 font-mono text-xs">
        <p>
          <span className="kicker">Min cash after plan</span>{" "}
          <span className="num text-text" data-testid="explore-plan-min-cash">{data.min_cash === null ? "NOT AVAILABLE" : usd(data.min_cash)}</span>
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
            <ul className="text-text-2">
              {binding.map((b) => (
                <li key={b}>{b}</li>
              ))}
            </ul>
          )}
        </div>
        <p className="text-[10px] text-muted">
          The plan is the solver&apos;s proposal for the SYNTHETIC demo business; FAULTLINE executes nothing.
        </p>
      </div>
    </div>
  );
}
