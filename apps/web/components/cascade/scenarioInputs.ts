import type { DemandShock, RateShock, ScenarioShock, SupplierOutage } from "@/lib/api";

/**
 * Scenario *inputs* for POST /api/simulate. The browser only translates slider positions into a
 * core/financials.py `ScenarioShock`; it never evaluates the model. Nothing here is a result.
 */
export interface ScenarioControls {
  /** δ as a whole percent (0 = no demand shock). */
  demandPct: number;
  demandStart: number;
  demandEnd: number;
  /** ρ, linear recovery weeks after the window. */
  demandRecovery: number;
  /** Δr in basis points (0 = no rate shock). */
  rateBp: number;
  rateStart: number;
  /** Weeks of full primary-supplier outage, κ_t = 0 (0 = no outage). */
  outageWeeks: number;
  outageStart: number;
  /** φ, share of sales dependent on the primary supplier, whole percent. */
  dependentPct: number;
}

export type ControlKey = keyof ScenarioControls;

/**
 * Default φ: the demo business's `scenario_parameters.supplier_outage_dependent_share` (0.4, a MATH_MODEL §10
 * assumed placeholder). The API does not serve that field yet, so this input default mirrors it.
 */
export const DEFAULT_DEPENDENT_PCT = 40;

/** All shocks off: the request is the baseline scenario. Window positions are only where the sliders start. */
export const NO_SHOCK: ScenarioControls = {
  demandPct: 0,
  demandStart: 4,
  demandEnd: 9,
  demandRecovery: 4,
  rateBp: 0,
  rateStart: 1,
  outageWeeks: 0,
  outageStart: 4,
  dependentPct: DEFAULT_DEPENDENT_PCT,
};

const DEMAND_KEYS: readonly ControlKey[] = ["demandPct", "demandStart", "demandEnd", "demandRecovery"];
const RATE_KEYS: readonly ControlKey[] = ["rateBp", "rateStart"];
const OUTAGE_KEYS: readonly ControlKey[] = ["outageWeeks", "outageStart"];

const trim = (n: number, digits: number) => `${Number(n.toFixed(digits))}`;
const signed = (s: string) => (s.startsWith("-") || s === "0" ? s : `+${s}`);

/** Display of the δ / Δr / φ actually sent (unrounded beyond 2 dp), so a preset's 0.155 reads 15.5%, not 16%. */
export const fmt = {
  pct: (fraction: number) => `${trim(fraction * 100, 2)}%`,
  bp: (rate: number) => `${signed(trim(rate * 10_000, 1))} bp`,
};

/** Number of weeks with κ_t < 1 in an availability input (constant or length-T list). */
export function outageWeekCount(availability: number | number[], horizon: number): number {
  if (!Array.isArray(availability)) return availability < 1 ? horizon : 0;
  return availability.filter((k) => k < 1).length;
}

/**
 * Whether an availability input is exactly "κ_t = 0 for one contiguous block of weeks, 1 otherwise",
 * i.e. what the outage sliders can express. Partial availability (0 < κ_t < 1) is not.
 */
export function isWholeWeekOutage(availability: number | number[], horizon: number): boolean {
  const kappa = Array.isArray(availability) ? availability : Array.from({ length: horizon }, () => availability);
  if (kappa.some((k) => k !== 0 && k !== 1)) return false;
  const zeros = kappa.map((k, i) => (k === 0 ? i : -1)).filter((i) => i >= 0);
  const first = zeros[0];
  const last = zeros[zeros.length - 1];
  return first === undefined || last === undefined || last - first + 1 === zeros.length;
}

/** Last outage week the sliders allow: an outage starting at `start` can last at most T − start + 1 weeks. */
export function maxOutageWeeks(start: number, horizon: number): number {
  return Math.max(0, horizon - start + 1);
}

function availabilityFromControls(c: ScenarioControls, horizon: number): number[] {
  const last = c.outageStart + Math.min(c.outageWeeks, maxOutageWeeks(c.outageStart, horizon)) - 1;
  return Array.from({ length: horizon }, (_, i) => (i + 1 >= c.outageStart && i + 1 <= last ? 0 : 1));
}

function demandFromControls(c: ScenarioControls): DemandShock {
  return { delta: c.demandPct / 100, start_week: c.demandStart, end_week: c.demandEnd, recovery_weeks: c.demandRecovery };
}

function rateFromControls(c: ScenarioControls): RateShock {
  return { delta_rate: c.rateBp / 10_000, start_week: c.rateStart };
}

/** Human-readable name for a slider-built shock, sent as `shock.name` and echoed back as `scenario_name`. */
export function scenarioName(shock: ScenarioShock, horizon: number | null): string {
  const parts: string[] = [];
  const d = shock.demand;
  if (d) parts.push(`demand −${fmt.pct(d.delta)} wk ${d.start_week}–${d.end_week}`);
  if (shock.rate) parts.push(`rate ${fmt.bp(shock.rate.delta_rate).replace(" ", "")} from wk ${shock.rate.start_week}`);
  const s = shock.supplier;
  if (s && horizon !== null) {
    const outage = isWholeWeekOutage(s.availability, horizon)
      ? `supplier outage ${outageWeekCount(s.availability, horizon)} wk`
      : "supplier κ_t partial";
    parts.push(`${outage}, φ ${fmt.pct(s.dependent_share)}`);
  }
  return parts.length ? parts.join(" · ") : "baseline";
}

/**
 * Controls → ScenarioShock (Custom mode). Week bounds are not cross-checked (e.g. end before start): the API
 * validates and its 422 message is shown, so the server stays the single authority on what a valid scenario is.
 */
export function buildShock(c: ScenarioControls, horizon: number | null): ScenarioShock {
  const shock: ScenarioShock = {};
  if (c.demandPct > 0) shock.demand = demandFromControls(c);
  if (c.rateBp !== 0) shock.rate = rateFromControls(c);
  if (c.outageWeeks > 0 && horizon !== null) {
    shock.supplier = { availability: availabilityFromControls(c, horizon), dependent_share: c.dependentPct / 100 };
  }
  const name = scenarioName(shock, horizon);
  return { name: name === "baseline" ? name : `custom: ${name}`, ...shock };
}

/**
 * A preset's exact shock with only the controls the viewer actually moved applied on top (audit fix: never
 * re-derive untouched fields from rounded slider positions). Untouched fields are passed through unchanged,
 * so one step on Δr changes only `rate.delta_rate`.
 */
export function editShock(
  base: ScenarioShock,
  c: ScenarioControls,
  touched: ReadonlySet<ControlKey>,
  horizon: number,
  baseName: string,
): ScenarioShock {
  const any = (keys: readonly ControlKey[]) => keys.some((k) => touched.has(k));
  const out: ScenarioShock = {};

  let demand: DemandShock | null | undefined = base.demand;
  if (any(DEMAND_KEYS)) {
    if (touched.has("demandPct") && c.demandPct === 0) demand = null;
    else if (!base.demand) demand = c.demandPct > 0 ? demandFromControls(c) : null;
    else {
      demand = { ...base.demand };
      if (touched.has("demandPct")) demand.delta = c.demandPct / 100;
      if (touched.has("demandStart")) demand.start_week = c.demandStart;
      if (touched.has("demandEnd")) demand.end_week = c.demandEnd;
      if (touched.has("demandRecovery")) demand.recovery_weeks = c.demandRecovery;
    }
  }
  if (demand) out.demand = demand;

  let rate: RateShock | null | undefined = base.rate;
  if (any(RATE_KEYS)) {
    if (touched.has("rateBp") && c.rateBp === 0) rate = null;
    else if (!base.rate) rate = c.rateBp !== 0 ? rateFromControls(c) : null;
    else {
      rate = { ...base.rate };
      if (touched.has("rateBp")) rate.delta_rate = c.rateBp / 10_000;
      if (touched.has("rateStart")) rate.start_week = c.rateStart;
    }
  }
  if (rate) out.rate = rate;

  let supplier: SupplierOutage | null | undefined = base.supplier;
  if (any(OUTAGE_KEYS)) {
    // Only reachable when the preset's κ_t is a whole-week block (the sliders are locked otherwise), so rebuilding
    // the block from the controls reproduces it except for the moved field.
    supplier =
      c.outageWeeks > 0
        ? {
            availability: availabilityFromControls(c, horizon),
            dependent_share: touched.has("dependentPct")
              ? c.dependentPct / 100
              : (base.supplier?.dependent_share ?? c.dependentPct / 100),
          }
        : null;
  } else if (supplier && touched.has("dependentPct")) {
    supplier = { ...supplier, dependent_share: c.dependentPct / 100 };
  }
  if (supplier) out.supplier = supplier;

  const edited = touched.size ? ` (edited) · ${scenarioName(out, horizon)}` : "";
  return { name: `${baseName}${edited}`, ...out };
}

/**
 * Slider positions for a preset's shock. Positions are rounded to the slider steps, but the preset is still sent
 * exactly (see `editShock`); only fields the viewer moves take a slider value.
 */
export function controlsFromShock(shock: ScenarioShock, horizon: number, prev: ScenarioControls): ScenarioControls {
  const next: ScenarioControls = { ...prev, demandPct: 0, rateBp: 0, outageWeeks: 0 };
  if (shock.demand) {
    next.demandPct = Math.round(shock.demand.delta * 100);
    next.demandStart = shock.demand.start_week;
    next.demandEnd = shock.demand.end_week;
    next.demandRecovery = shock.demand.recovery_weeks ?? 0;
  }
  if (shock.rate) {
    next.rateBp = Math.round(shock.rate.delta_rate * 10_000);
    next.rateStart = shock.rate.start_week;
  }
  if (shock.supplier) {
    const a = shock.supplier.availability;
    const kappa = Array.isArray(a) ? a : Array.from({ length: horizon }, () => a);
    const out = kappa.map((k, i) => (k < 1 ? i + 1 : 0)).filter((w) => w > 0);
    const firstOut = out[0];
    if (firstOut !== undefined) {
      next.outageWeeks = out.length;
      next.outageStart = firstOut;
    }
    next.dependentPct = Math.round(shock.supplier.dependent_share * 100);
  }
  return next;
}
