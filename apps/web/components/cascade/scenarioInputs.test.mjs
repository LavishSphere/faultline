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
// Shockwave sequencing (#165), tested at the end of this file: display order and grouping only.
import { actionsByNode, countFrame, dependencyLevels, peakOf } from "./shockwave.ts";

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

// Shockwave sequencing (#165): no figure is derived, only order, grouping and the count-up's end frame.
const NODES = ["Demand", "Sales", "Receipts", "Supplier", "Inventory", "Purchases", "Payables", "Rate", "Interest", "Payroll", "Revolver", "Cash"];
const EDGES = [
  ["Demand", "Sales"], ["Supplier", "Sales"], ["Supplier", "Purchases"], ["Demand", "Purchases"], ["Sales", "Receipts"],
  ["Sales", "Purchases"], ["Purchases", "Inventory"], ["Purchases", "Payables"], ["Rate", "Interest"], ["Revolver", "Interest"],
  ["Receipts", "Cash"], ["Payables", "Cash"], ["Interest", "Cash"], ["Payroll", "Cash"], ["Revolver", "Cash"],
];

test("dependency levels follow the served edges: every edge goes to a strictly later level, Cash last", () => {
  const lv = dependencyLevels(NODES, EDGES);
  for (const [s, t] of EDGES) assert.ok(lv.get(t) > lv.get(s), `${s} -> ${t}`);
  assert.equal(lv.get("Demand"), 0);
  assert.equal(lv.get("Supplier"), 0);
  assert.ok(lv.get("Sales") < lv.get("Receipts") && lv.get("Receipts") < lv.get("Cash"));
  assert.ok(lv.get("Purchases") < lv.get("Inventory") && lv.get("Purchases") < lv.get("Payables"));
  assert.equal(Math.max(...lv.values()), lv.get("Cash"));
});

test("dependency levels terminate on a cycle (not in the model)", () => {
  const lv = dependencyLevels(["a", "b"], [["a", "b"], ["b", "a"]]);
  assert.ok(lv.get("a") <= 2 && lv.get("b") <= 2);
});

test("count-up starts at the previous API value and its last frame is exactly the new one", () => {
  const to = -64515.38461538462;
  assert.equal(countFrame(-16900.1, to, 0), -16900.1);
  assert.equal(countFrame(-16900.1, to, 1), to);
  assert.equal(countFrame(-16900.1, to, 1.7), to);
  const mid = countFrame(0, to, 0.5);
  assert.ok(mid < 0 && mid > to);
});

test("peakOf returns the served entry with the largest |Δ|, first on ties", () => {
  assert.deepEqual(peakOf([1, -3, 3, 2]), { peak: -3, peakIdx: 1, maxAbs: 3 });
  assert.equal(peakOf([]), null);
});

test("actionsByNode groups plan actions on the node they act on, in API order, without summing", () => {
  const acts = [
    { action: "purchase_cut", week: 18, amount: 1126.92, share: null },
    { action: "revolver_draw", week: 5, amount: 1000, share: null },
    { action: "purchase_cut", week: 19, amount: 1653.85, share: null },
    { action: "payroll_cut", week: 7, amount: 500, share: 0.1 },
    { action: "something_new", week: 1, amount: 1, share: null },
  ];
  const g = actionsByNode(acts);
  assert.deepEqual(g.get("Purchases").map((a) => a.amount), [1126.92, 1653.85]);
  assert.equal(g.get("Revolver").length, 1);
  assert.equal(g.get("Payroll")[0].share, 0.1);
  assert.equal([...g.values()].flat().length, 4);
});
