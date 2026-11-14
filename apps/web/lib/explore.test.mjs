// LIVE EXPLORE client checks (issue #61). Pure functions, no network. Run: npm test.
// Every body below is a hand-built TEST FIXTURE shaped like routes/explore.py `ExploreAnalysis`, never shown in the UI.
// The checks under test only accept or refuse a body, or translate inputs into a ScenarioShock; they compute no result.
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  DEFAULTS_LABEL,
  LIVE_EXPLORE_LABEL,
  SUGGESTION_LABEL,
  TAVILY_ATTRIBUTION,
  checkAnalysisResponse,
  shockFromValues,
} from "./explore.ts";

const URL_A = "https://news-a.example/story";
const URL_B = "https://news-b.example/story";
const AT = "2026-11-14T15:00:00Z";

function source(id, url) {
  return {
    source_id: id, title: `Title ${id}`, url, snippet: `snippet ${id}`, score: 0.5, published_at: null,
    published_at_raw: null, retrieved_at: AT,
  };
}

const RATE_PARAMS = [
  { block: "rate", param: "delta_rate", unit: "Δr", integer: false, min: 0.0025, default: 0.005, max: 0.01, worse_when: "higher" },
  { block: "rate", param: "start_week", unit: "t", integer: true, min: 1, default: 1, max: 7, worse_when: "lower" },
];

function analysis(over = {}) {
  return {
    mode: "live_explore",
    label: LIVE_EXPLORE_LABEL,
    provider: "tavily",
    attribution: TAVILY_ATTRIBUTION,
    decision_text: "fixture decision",
    retrieved_at: AT,
    cached: false,
    status: "ok",
    status_message: null,
    sources: [source("S1", URL_A), source("S2", URL_B)],
    evidence: [
      { claim: "fixture claim", source_id: "S1", source_url: URL_A, source_title: "Title S1", snippet: "snippet S1",
        published_at: null, published_at_raw: null, retrieved_at: AT },
    ],
    rejected_claims: [],
    suggestion: {
      label: DEFAULTS_LABEL,
      values_from_model: 0,
      category_id: "central-bank-rate-surprise",
      category_name: "Central-bank rate surprise",
      parameters: RATE_PARAMS.map((p) => ({ ...p, value: p.default, source: "guidance_default", model_value: null,
        rationale: null, note: null })),
      shock: { name: "x", rate: { delta_rate: 0.005, start_week: 1 }, demand: null, supplier: null },
      notes: [],
    },
    model: null,
    guidance: {
      provenance: "ILLUSTRATIVE",
      label: "ILLUSTRATIVE: modelling guidance, not forecasts",
      horizon_weeks: 26,
      categories: [{ id: "central-bank-rate-surprise", name: "Central-bank rate surprise", news_trigger: "t",
        timing_guidance: "g", rationale: "r", basis: "b", params: RATE_PARAMS }],
    },
    notes: [],
    ...over,
  };
}

test("a contract-shaped analysis is accepted", () => {
  assert.equal(checkAnalysisResponse(analysis()), null);
  assert.equal(checkAnalysisResponse(analysis({ status: "model_unavailable", evidence: [], suggestion: null })), null);
});

test("an evidence card citing a url that is not a Tavily source is refused", () => {
  const body = analysis();
  body.evidence[0].source_url = "https://made-up.example/x";
  assert.match(checkAnalysisResponse(body), /not among the Tavily sources/);
});

test("a suggested value outside its stated range is refused", () => {
  const body = analysis();
  body.suggestion.parameters[0].value = 0.5;
  assert.match(checkAnalysisResponse(body), /outside its stated range/);
});

test("any label other than LIVE EXPLORE is refused", () => {
  assert.match(checkAnalysisResponse(analysis({ label: "REAL HISTORICAL" })), /LIVE EXPLORE/);
  assert.match(checkAnalysisResponse(analysis({ suggestion_label: SUGGESTION_LABEL })), /non-contract key/);
  assert.match(checkAnalysisResponse(analysis({ extra: 1 })), /non-contract key/);
});

test("status ok without cited evidence is refused", () => {
  assert.match(checkAnalysisResponse(analysis({ evidence: [] })), /without cited evidence/);
});

test("shockFromValues follows the guidance mapping_to_scenario_shock", () => {
  const shock = shockFromValues(
    "fixture",
    {
      rate: { delta_rate: 0.005, start_week: 2 },
      demand: { delta: 0.1, start_week: 2, duration_weeks: 4, recovery_weeks: 3 },
      supplier: { availability_during_outage: 0.2, start_week: 3, duration_weeks: 2, dependent_share: 0.4 },
    },
    26,
  );
  assert.deepEqual(shock.rate, { delta_rate: 0.005, start_week: 2 });
  assert.deepEqual(shock.demand, { delta: 0.1, start_week: 2, end_week: 5, recovery_weeks: 3 });
  assert.equal(shock.supplier.availability.length, 26);
  assert.deepEqual(shock.supplier.availability.slice(0, 5), [1, 1, 0.2, 0.2, 1]);
  assert.equal(shock.supplier.dependent_share, 0.4);
  assert.deepEqual(shockFromValues("none", {}, 26), { name: "none" });
});

test("an all-default suggestion labeled MODEL-SUGGESTED is refused; one model value requires the model label", () => {
  const spoofed = analysis();
  spoofed.suggestion.label = SUGGESTION_LABEL; // every parameter is guidance_default
  assert.match(checkAnalysisResponse(spoofed), /label does not match/);

  const partial = analysis();
  partial.suggestion.parameters[0].source = "model";
  partial.suggestion.parameters[0].model_value = 0.005;
  partial.suggestion.values_from_model = 1;
  assert.match(checkAnalysisResponse(partial), /label does not match/); // still says GUIDANCE DEFAULTS
  partial.suggestion.label = SUGGESTION_LABEL;
  assert.equal(checkAnalysisResponse(partial), null);

  const miscounted = analysis();
  miscounted.suggestion.values_from_model = 2;
  assert.match(checkAnalysisResponse(miscounted), /values_from_model/);
});
