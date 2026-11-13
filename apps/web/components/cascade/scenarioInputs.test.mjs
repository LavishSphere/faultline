// Input-translation checks for the CASCADE controls (audit item 1 on PR #30). Pure functions, no network.
// Run: npm test (node's built-in runner; Node >= 22.18 strips the TypeScript types from scenarioInputs.ts).
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  NO_SHOCK,
  buildShock,
  controlsFromShock,
  editShock,
  isWholeWeekOutage,
  maxOutageWeeks,
  scenarioName,
} from "./scenarioInputs.ts";

const T = 26;
// The audit's reproduction: partial availability and a δ that is not on the 1% slider grid.
const PRESET = {
  name: "partial",
  demand: { delta: 0.155, start_week: 3, end_week: 8, recovery_weeks: 2 },
  rate: { delta_rate: 0.0175, start_week: 2 },
  supplier: { availability: 0.5, dependent_share: 0.37 },
};

test("one step on Δr changes only rate.delta_rate; every other preset field is sent exactly", () => {
  const c = { ...controlsFromShock(PRESET, T, NO_SHOCK), rateBp: 200 };
  const out = editShock(PRESET, c, new Set(["rateBp"]), T, PRESET.name);
  assert.deepEqual(out.demand, PRESET.demand);
  assert.deepEqual(out.supplier, PRESET.supplier);
  assert.deepEqual(out.rate, { delta_rate: 0.02, start_week: 2 });
});

test("no edits: the preset shock is passed through unchanged", () => {
  const c = controlsFromShock(PRESET, T, NO_SHOCK);
  const out = editShock(PRESET, c, new Set(), T, PRESET.name);
  assert.deepEqual({ ...out, name: PRESET.name }, PRESET);
});

test("moving δ overrides only delta; window and recovery keep the preset values", () => {
  const c = { ...controlsFromShock(PRESET, T, NO_SHOCK), demandPct: 17, demandStart: 9 };
  const out = editShock(PRESET, c, new Set(["demandPct"]), T, PRESET.name);
  assert.deepEqual(out.demand, { ...PRESET.demand, delta: 0.17 });
});

test("moving φ overrides only dependent_share; partial κ_t is kept", () => {
  const c = { ...controlsFromShock(PRESET, T, NO_SHOCK), dependentPct: 50 };
  const out = editShock(PRESET, c, new Set(["dependentPct"]), T, PRESET.name);
  assert.deepEqual(out.supplier, { availability: 0.5, dependent_share: 0.5 });
});

test("setting a touched shock to zero removes only that shock", () => {
  const c = { ...controlsFromShock(PRESET, T, NO_SHOCK), rateBp: 0 };
  const out = editShock(PRESET, c, new Set(["rateBp"]), T, PRESET.name);
  assert.equal(out.rate, undefined);
  assert.deepEqual(out.demand, PRESET.demand);
});

test("whole-week outage presets are editable on the sliders; partial ones are not", () => {
  assert.equal(isWholeWeekOutage(0.5, T), false);
  assert.equal(isWholeWeekOutage([1, 1, 0, 0, 0, ...Array(21).fill(1)], T), true);
  assert.equal(isWholeWeekOutage([1, 0, 1, 0, ...Array(22).fill(1)], T), false);
  const block = { supplier: { availability: [1, 1, 0, 0, 0, ...Array(21).fill(1)], dependent_share: 0.4 } };
  const c = { ...controlsFromShock(block, T, NO_SHOCK), outageWeeks: 4 };
  const out = editShock(block, c, new Set(["outageWeeks"]), T, "block");
  assert.deepEqual(out.supplier.availability, [1, 1, 0, 0, 0, 0, ...Array(20).fill(1)]);
  assert.equal(out.supplier.dependent_share, 0.4);
});

test("outage is capped at T − start + 1 weeks", () => {
  assert.equal(maxOutageWeeks(24, T), 3);
  const s = buildShock({ ...NO_SHOCK, outageWeeks: 10, outageStart: 24 }, T);
  assert.equal(s.supplier.availability.filter((k) => k === 0).length, 3);
});

test("scenario name includes φ", () => {
  const s = buildShock({ ...NO_SHOCK, outageWeeks: 3, dependentPct: 40 }, T);
  assert.match(s.name, /φ 40%/);
  assert.equal(scenarioName({}, T), "baseline");
  assert.equal(buildShock(NO_SHOCK, T).name, "baseline");
});
