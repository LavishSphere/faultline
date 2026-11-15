// Cockpit universe helpers (#197). Pure functions, no network. Run: npm test.
// Every body below is a hand-built TEST FIXTURE, never shown in the UI. The helpers pick which exact tool input the
// universe re-runs, compare a tool summary with the engine's re-run field by field, and price a reply's token usage.
import assert from "node:assert/strict";
import { test } from "node:test";
import { costLabel, drivesUniverse, engineInputs, networkRequest, optimizeMatch, replyCostUsd, simulateMatch } from "./universe.ts";

const shockA = { name: "TEST FIXTURE A", demand: null, rate: { delta_rate: 0.015, start_week: 1 }, supplier: null };
const shockB = { name: "TEST FIXTURE B", demand: null, rate: null, supplier: null };
const call = (name, input, status = "ok") => ({ name, input, result_status: status, result_summary: null, provenance: "SIMULATED" });

test("engineInputs takes the last ok simulate and optimize inputs verbatim", () => {
  const calls = [
    call("simulate", { shock: shockB }),
    call("list_scenarios", {}),
    call("simulate", { scenario_id: "x", shock: shockA }),
    call("simulate", { shock: shockB }, "error"),
    call("optimize", { scenario_id: "x", shock: shockA, protect_payroll: true }),
  ];
  const e = engineInputs(calls);
  assert.equal(e.simulate, calls[2].input);
  assert.equal(e.optimize, calls[4].input);
  assert.deepEqual(e.counts, { simulate: 2, optimize: 1 });
  assert.equal(e.sameShock, true);
  assert.equal(networkRequest(e).from, "simulate");
  assert.equal(networkRequest(e).request, calls[2].input);
});

test("an optimize-only turn drives the network with that call's own scenario and shock (no protect flag)", () => {
  const e = engineInputs([call("optimize", { scenario_id: "x", shock: shockA, protect_payroll: false })]);
  assert.deepEqual(networkRequest(e), { request: { scenario_id: "x", shock: shockA }, from: "optimize" });
});

test("different shocks are not paired; inputs without a shock or flag are ignored", () => {
  const e = engineInputs([call("simulate", { shock: shockA }), call("optimize", { shock: shockB, protect_payroll: true })]);
  assert.equal(e.sameShock, false);
  assert.equal(drivesUniverse([call("optimize", { shock: shockA })]), false);
  assert.equal(drivesUniverse([call("simulate", { shock: "nope" })]), false);
  assert.equal(drivesUniverse([call("decision", { frame_id: "f", p_yes: 0.4 })]), false);
});

const sim = { result: { min_cash: 1234.5678, cash: [10, 20, 30.004] }, first_week_below_floor: 7 };

test("simulateMatch compares only fields the summary carries, to the cent", () => {
  assert.equal(simulateMatch({ fixture: "x" }, sim), null);
  assert.equal(simulateMatch("text", sim), null);
  const rows = simulateMatch({ min_cash: 1234.57, ending_cash: 30.0, first_week_below_floor: 7 }, sim);
  assert.deepEqual(rows.map((r) => [r.field, r.equal]), [["min_cash", true], ["ending_cash", true], ["first_week_below_floor", true]]);
  const off = simulateMatch({ min_cash: 1200, first_week_below_floor: null }, sim);
  assert.deepEqual(off.map((r) => [r.field, r.equal]), [["min_cash", false], ["first_week_below_floor", false]]);
});

test("optimizeMatch compares status and min cash", () => {
  const rows = optimizeMatch({ status: "OPTIMAL", min_cash: 99.99 }, { status: "OPTIMAL", min_cash: 99.994 });
  assert.deepEqual(rows.map((r) => r.equal), [true, true]);
  const bad = optimizeMatch({ status: "NO FEASIBLE PLAN", min_cash: null }, { status: "OPTIMAL", min_cash: 5 });
  assert.deepEqual(bad.map((r) => r.equal), [false, false]);
});

test("replyCostUsd is usage × catalogue price, or null when either is missing", () => {
  const priced = { pricing: { input_per_mtok: 3, output_per_mtok: 15 } };
  const usage = { input_tokens: 1234, output_tokens: 567 };
  assert.ok(Math.abs(replyCostUsd(usage, priced) - 0.012207) < 1e-12);
  assert.equal(costLabel(replyCostUsd(usage, priced)), "$0.0122");
  assert.equal(replyCostUsd(null, priced), null);
  assert.equal(replyCostUsd(usage, { pricing: null }), null);
  assert.equal(replyCostUsd(usage, { pricing: { input_per_mtok: 3, output_per_mtok: null } }), null);
  assert.equal(costLabel(0.00001), "< $0.0001");
  assert.equal(costLabel(0), "$0.0000");
});
