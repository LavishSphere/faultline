// Contract checks for the REVEAL and DECISION clients (issue #117). Pure functions, no network.
// Run: npm test. Every body below is a hand-built TEST FIXTURE shaped like the API's models, never shown in the UI;
// the checks under test only accept or refuse a body, they never compute a score.
import assert from "node:assert/strict";
import { test } from "node:test";
import { KNOWN_VERDICTS, checkRevealResponse, isSyntheticRef, readBenchmark } from "./benchmark.ts";
import { checkCaseEvidence, isSyntheticQuote } from "./replay.ts";

const SHA = "a".repeat(64);

function perEvent(i) {
  return {
    event_id: `fixture_${i}`,
    n_snapshots: 1,
    y: i % 2,
    prediction_ids: [`pid_${i}`],
    market_refs: ["kalshi:FIXTURE"],
    brier: { naive: 0.25, market: 0.2, agent_only: 0.1 },
    log_loss: { naive: 0.69, market: 0.6, agent_only: 0.3 },
    accuracy_at_0_5: { naive: 0, market: 1, agent_only: 1 },
  };
}

/** A scorecard fixture with n scored events; `over` replaces top-level keys. */
function card(n, over = {}) {
  const scored = n >= 5;
  return {
    label: scored ? "ILLUSTRATIVE: Synthetic demo fixtures" : "INSUFFICIENT DATA: No valid comparison",
    verdict: scored ? "No improvement measured" : "INSUFFICIENT DATA",
    caveat: scored && n < 30 ? `small sample: n = ${n} events (< 30)` : null,
    provenance: n === 0 ? null : "SYNTHETIC",
    agent_variant: "agent_only",
    forecasters: ["agent_only", "market", "naive"],
    market_label: "fixture market label",
    case_set: "synthetic",
    n_events: n,
    n_excluded: 0,
    exclusions_by_reason: {},
    exclusions: [],
    ignored_predictions: [],
    per_event: Array.from({ length: n }, (_, i) => perEvent(i)),
    summary: scored
      ? {
          agent_only: { mean_brier: 0.1, mean_log_loss: 0.3, accuracy_at_0_5: 1 },
          market: { mean_brier: 0.2, mean_log_loss: 0.6, accuracy_at_0_5: 1 },
          naive: { mean_brier: 0.25, mean_log_loss: 0.69, accuracy_at_0_5: 0 },
        }
      : null,
    comparison: scored
      ? {
          agent_variant: "agent_only",
          baseline: "market",
          metric: "brier",
          mean_delta_brier: -0.1,
          ci_low: -0.2,
          ci_high: 0.01,
          confidence: 0.95,
          n_resamples: 10000,
          seed: 7,
        }
      : null,
    official_blockers: [],
    ...over,
  };
}

function record(over = {}) {
  return {
    agent_variant: "agent_only",
    case_set: "synthetic",
    recorded_at: "2026-11-13T00:00:00Z",
    source: "compute_route",
    origin: "computed",
    run_id: null,
    file: "fixture.json",
    scorecard_sha256: SHA,
    snapshot_sha256: SHA,
    agent_models: ["ollama/fixture"],
    ...over,
  };
}

const body = (items, records = items.map(() => record())) => ({
  status: items.length ? "AVAILABLE" : "NOT AVAILABLE",
  provenance: "RECORDED_RUN",
  items,
  records,
  notes: [],
});

const accepted = (b) => assert.equal(typeof readBenchmark(b), "object", String(readBenchmark(b)));
const refused = (b, re) => {
  const r = readBenchmark(b);
  assert.equal(typeof r, "string", "expected the body to be refused");
  assert.match(r, re);
};

test("well-formed cards pass: n < 5 INSUFFICIENT DATA, and n = 5 with a caveat", () => {
  accepted(body([card(3)]));
  accepted(body([card(5)]));
  accepted(body([]));
});

test("case_set may be absent or null on cards and records (#117 item 3)", () => {
  accepted(body([card(5, { case_set: null })], [record({ case_set: null })]));
  const noSet = card(5);
  delete noSet.case_set;
  const noRecSet = record();
  delete noRecSet.case_set;
  accepted(body([noSet], [noRecSet]));
  refused(body([card(5, { case_set: "mixed" })]), /case_set/);
  refused(body([card(5)], [record({ case_set: "mixed" })]), /case_set/);
});

test("n >= 5 requires summary and comparison", () => {
  refused(body([card(5, { summary: null })]), /summary or comparison/);
  refused(body([card(5, { comparison: null })]), /summary or comparison/);
});

test("the verdict must be a known string, and AGENT_BETTER holds exactly when ci_high < 0", () => {
  assert.deepEqual([...KNOWN_VERDICTS].sort(), ["INSUFFICIENT DATA", "No improvement measured", "agent better than market"].sort());
  refused(body([card(5, { verdict: "agent beats market" })]), /known verdict/);
  const better = card(5, { verdict: "agent better than market" });
  refused(body([better]), /disagrees with the interval/); // ci_high = 0.01 >= 0
  accepted(body([{ ...better, comparison: { ...better.comparison, ci_high: -0.001 } }]));
  const none = card(5);
  refused(body([{ ...none, comparison: { ...none.comparison, ci_high: -0.001 } }]), /disagrees with the interval/);
  refused(body([card(5, { verdict: "INSUFFICIENT DATA" })]), /INSUFFICIENT DATA/);
});

test("n >= 30 carries no small-sample caveat", () => {
  accepted(body([card(30)]));
  refused(body([card(30, { caveat: "small sample" })]), /caveat/);
});

test("comparison.agent_variant must match the card's variant", () => {
  const c = card(5);
  refused(body([{ ...c, comparison: { ...c.comparison, agent_variant: "agent_plus_market" } }]), /differs from the card/);
  refused(body([{ ...c, comparison: { ...c.comparison, agent_variant: "oracle" } }]), /known variant/);
});

test("an OFFICIAL label needs REAL_HISTORICAL provenance and no official_blockers", () => {
  const official = { label: "OFFICIAL: Computed from 30 historical cases", case_set: "real" };
  accepted(body([card(30, { ...official, provenance: "REAL_HISTORICAL" })], [record({ case_set: "real" })]));
  refused(body([card(30, { ...official, provenance: "SYNTHETIC" })]), /OFFICIAL/);
  refused(body([card(30, { ...official, provenance: "REAL_HISTORICAL", official_blockers: ["x"] })]), /OFFICIAL/);
});

test("Literal values: variant, ignored reason and exclusion reasons are checked", () => {
  refused(body([card(5, { agent_variant: "oracle" })]), /known variant/);
  refused(
    body([card(5, { ignored_predictions: [{ prediction_id: "p", event_id: "e", as_of: "t", reason: "late" }] })]),
    /reason is not known/,
  );
  refused(body([card(5, { exclusions_by_reason: { peeked: 1 } })]), /unknown reason/);
});

// --- reveal --------------------------------------------------------------------------------------------------------

function reveal(market) {
  return {
    prediction: {
      prediction_id: "pid",
      event_id: "fixture_evt",
      as_of: "2025-01-01T00:00:00Z",
      agent_model: "ollama/fixture",
      model_digest: null,
      variant: "agent_plus_market",
      p_yes: 0.7,
      decision: "hedge",
      rationale: "fixture",
      evidence_ids: [],
      prompt_sha256: SHA,
      snapshot_sha256: SHA,
      temperature: 0,
      seed: null,
      recorded_at: "2025-01-01T00:00:00Z",
      provenance: "RECORDED_RUN",
      gated_prompt_sha256: null,
      attempts: 1,
      transcript_sha256: null,
      num_ctx: null,
      num_predict: null,
    },
    y: 1,
    sealed: { event_id: "fixture_evt", outcome: "YES", resolved_at: null, source_url: "u", provenance: "SYNTHETIC", notes: null },
    revealed_at: "t",
    persisted_at: "t",
    persist_seq: 1,
    reveal_seq: 2,
    event_first_revealed_at: "t",
    event_first_reveal_seq: 2,
    persisted_before_outcome_revealed: true,
    scores: { brier: 0.09, log_loss: 0.36, accuracy_at_0_5: 1 },
    baselines: { market, naive: { brier: 0.25, log_loss: 0.69 } },
  };
}

test("the reveal's market baseline must carry the API's label and ref (#117 item 4)", () => {
  const m = { p_yes: 0.35, brier: 0.42, log_loss: 1.05, label: "fixture label", ref: "synthetic:FIXTURE" };
  assert.equal(checkRevealResponse(reveal(m), "pid"), null);
  assert.equal(checkRevealResponse(reveal(null), "pid"), null);
  assert.equal(checkRevealResponse(reveal({ ...m, ref: null }), "pid"), null);
  const noLabel = { ...m };
  delete noLabel.label;
  assert.match(checkRevealResponse(reveal(noLabel), "pid") ?? "", /label/);
  assert.match(checkRevealResponse(reveal({ ...m, ref: 3 }), "pid") ?? "", /ref/);
  const p = reveal(m);
  assert.match(checkRevealResponse({ ...p, prediction: { ...p.prediction, decision: "buy" } }, "pid") ?? "", /decision/);
});

test("isSyntheticRef reads only the served ref", () => {
  assert.equal(isSyntheticRef("synthetic:FIXTURE"), true);
  assert.equal(isSyntheticRef("kalshi:FIXTURE"), false);
  assert.equal(isSyntheticRef(null), false);
});

// --- DECISION: market quotes ---------------------------------------------------------------------------------------

test("isSyntheticQuote is true for a synthetic venue, SYNTHETIC provenance, or a synthetic case (#117 C)", () => {
  const real = { venue: "kalshi", provenance: "REAL_HISTORICAL" };
  const realCase = { synthetic: false, provenance: "REAL_HISTORICAL" };
  assert.equal(isSyntheticQuote(real, realCase), false);
  assert.equal(isSyntheticQuote(real, null), false);
  assert.equal(isSyntheticQuote({ venue: "synthetic", provenance: "SYNTHETIC" }, realCase), true);
  assert.equal(isSyntheticQuote({ venue: "kalshi", provenance: "SYNTHETIC" }, realCase), true);
  assert.equal(isSyntheticQuote(real, { synthetic: true, provenance: "REAL_HISTORICAL" }), true);
  assert.equal(isSyntheticQuote(real, { synthetic: false, provenance: "SYNTHETIC" }), true);
});

const AS_OF = "2025-01-01T12:00:00Z";
const LABEL = "fixture market label";

function evidenceBody(quoteOver = {}, marketOver = {}) {
  return {
    status: "AVAILABLE",
    event_id: "fixture_evt",
    as_of: AS_OF,
    case_as_of: AS_OF,
    items: [],
    market_quotes: [
      {
        venue: "kalshi",
        market_id: "FIXTURE",
        p_yes: 0.5,
        quote_kind: "midpoint",
        ts: "2025-01-01T10:00:00Z",
        spread: null,
        volume: null,
        open_interest: null,
        period_seconds: null,
        label: LABEL,
        provenance: "REAL_HISTORICAL",
        ...quoteOver,
      },
    ],
    market_at_cutoff: {
      status: "AVAILABLE",
      label: LABEL,
      ref: "kalshi:FIXTURE",
      venue: "kalshi",
      market_id: "FIXTURE",
      quote_kind: "midpoint",
      ts: "2025-01-01T10:00:00Z",
      p_yes: 0.5,
      provenance: "REAL_HISTORICAL",
      note: null,
      ...marketOver,
    },
    excluded_by_reason: {},
    notes: [],
  };
}

test("label and provenance are required on quotes and market_at_cutoff (#117 F)", () => {
  const c = { event_id: "fixture_evt", as_of: AS_OF };
  assert.equal(checkCaseEvidence(evidenceBody(), c), null);
  const noQuoteLabel = evidenceBody();
  delete noQuoteLabel.market_quotes[0].label;
  assert.match(checkCaseEvidence(noQuoteLabel, c) ?? "", /missing "label"/);
  const noMarketLabel = evidenceBody();
  delete noMarketLabel.market_at_cutoff.label;
  assert.match(checkCaseEvidence(noMarketLabel, c) ?? "", /missing "label"/);
  const noProv = evidenceBody();
  delete noProv.market_quotes[0].provenance;
  assert.match(checkCaseEvidence(noProv, c) ?? "", /missing "provenance"/);
  const na = {
    status: "NOT AVAILABLE",
    label: LABEL,
    ref: null,
    venue: null,
    market_id: null,
    quote_kind: null,
    ts: null,
    p_yes: null,
    provenance: null,
    note: "none",
  };
  assert.equal(checkCaseEvidence({ ...evidenceBody(), market_at_cutoff: na }, c), null);
});
