// Monte Carlo readers (#210). Pure functions, no network. Run: npm test.
// The bodies are the TEST FIXTURES in e2e/fixtures (contract shapes, hand-picked numbers), never shown in the product.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { ciLabel, metricValue, monteCarloCalls, pct, readCash, readDecision, readInternalData, safeUrl, tornadoRows } from "./montecarlo.ts";

const fixture = (name) => JSON.parse(readFileSync(new URL(`../e2e/fixtures/${name}.fixture.json`, import.meta.url), "utf8")).result_summary;
const call = (name, result_summary, status = "ok") => ({ name, input: {}, result_status: status, result_summary, provenance: "SIMULATED" });

test("pct formats a probability to one decimal and refuses out-of-range values", () => {
  assert.equal(pct(0.783), "78.3%");
  assert.equal(pct(0), "0.0%");
  assert.equal(pct(1), "100.0%");
  assert.equal(pct(null), null);
  assert.equal(pct(1.2), null);
  assert.equal(ciLabel([0.777, 0.789]), "95% CI 77.7–78.9%");
  assert.equal(ciLabel(null), null);
});

test("readDecision copies the engine fields verbatim", () => {
  const raw = fixture("mc-decision").monte_carlo;
  const d = readDecision(call("monte_carlo_decision", fixture("mc-decision")));
  assert.ok(d);
  assert.equal(d.best.probBest, raw.best.prob_best);
  assert.deepEqual(d.best.ci95, raw.best.ci95);
  assert.equal(d.nPaths, raw.n_paths);
  assert.equal(d.options.length, raw.options.length);
  assert.deepEqual(d.binEdges, raw.options[0].histogram.bin_edges);
  assert.deepEqual(d.options[1].counts, raw.options[1].histogram.counts);
  assert.equal(d.options[0].p50, raw.options[0].p50);
});

test("readDecision drops counts that do not fit the edges and unsafe source links", () => {
  const body = structuredClone(fixture("mc-decision"));
  body.monte_carlo.options[0].histogram.counts = [1, 2, 3];
  delete body.monte_carlo.best;
  const d = readDecision(call("monte_carlo_decision", body));
  assert.equal(d.options[0].counts, null);
  assert.equal(d.best, null);
  const unsafe = d.assumptions.find((a) => a.name === "Export-control shock");
  assert.equal(unsafe.source.url, null);
  assert.equal(safeUrl("javascript:alert(1)"), null);
  assert.equal(safeUrl("https://example.com/x").protocol, "https:");
});

test("differing bin edges across options mean no shared histogram", () => {
  const body = structuredClone(fixture("mc-decision"));
  body.monte_carlo.options[1].histogram.bin_edges = body.monte_carlo.options[1].histogram.bin_edges.map((e) => e + 1);
  assert.equal(readDecision(call("monte_carlo_decision", body)).binEdges, null);
});

test("tornadoRows orders by served swing, largest first, missing swings last", () => {
  const rows = tornadoRows([
    { driver: "a", swing: 3 },
    { driver: "b", swing: null },
    { driver: "c", swing: 22 },
    { driver: "d", swing: 9 },
  ]);
  assert.deepEqual(rows.map((r) => r.driver), ["c", "d", "a", "b"]);
});

test("readCash keeps both sides and refuses bands of the wrong length", () => {
  const raw = fixture("mc-cash").monte_carlo;
  const c = readCash(call("monte_carlo_cash", fixture("mc-cash")));
  assert.equal(c.noPlan.probBelowFloorAny, raw.no_plan.prob_below_floor_any);
  assert.equal(c.withPlan.probBelowFloorAny, raw.with_plan.prob_below_floor_any);
  assert.deepEqual(c.noPlan.bands.p50, raw.no_plan.bands.p50);
  assert.equal(c.floor, raw.floor);
  const body = structuredClone(fixture("mc-cash"));
  body.monte_carlo.no_plan.bands.p5 = body.monte_carlo.no_plan.bands.p5.slice(1);
  body.monte_carlo.with_plan = null;
  const short = readCash(call("monte_carlo_cash", body));
  assert.equal(short.noPlan.bands, null);
  assert.equal(short.withPlan, null);
});

test("readInternalData uses the served columns; monteCarloCalls keeps only ok calls of the three tools", () => {
  const t = readInternalData(call("query_internal_data", fixture("internal-data")));
  assert.deepEqual(t.columns, ["supplier", "share_of_cogs", "lead_time_weeks", "region"]);
  assert.equal(t.rows.length, 3);
  const picked = monteCarloCalls([
    call("simulate", {}),
    call("monte_carlo_cash", {}, "error"),
    call("monte_carlo_decision", {}),
    call("query_internal_data", {}),
  ]);
  assert.deepEqual(picked.map((c) => c.name), ["monte_carlo_decision", "query_internal_data"]);
});

test("metricValue formats in the served unit", () => {
  assert.equal(metricValue(18, "%"), "18%");
  assert.equal(metricValue(1250000, "USD"), "$1.25M");
  assert.equal(metricValue(null, "%"), null);
});
