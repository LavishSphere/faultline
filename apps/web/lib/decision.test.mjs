// Case -> decision frame mapping (issue #55 review). Pure function, no network. Ids are the committed demo case ids.
import assert from "node:assert/strict";
import { test } from "node:test";
import { frameForCase } from "./decision.ts";

const SERVED = ["fomc-rate-decision", "cpi-surprise", "supply-disruption"];

test("FOMC cases open the FOMC frame", () => {
  for (const id of ["fomc-2026-jun", "fomc-2026-jul", "fomc-2026-sep", "fomc-2026-oct"]) {
    assert.equal(frameForCase({ event_id: id, synthetic: false }, SERVED), "fomc-rate-decision");
  }
});

test("the SYNTHETIC distributor-depot case opens the supply-disruption frame, never FOMC", () => {
  assert.equal(frameForCase({ event_id: "synthetic_distributor-depot", synthetic: true }, SERVED), "supply-disruption");
});

test("CPI ids open the CPI frame", () => {
  assert.equal(frameForCase({ event_id: "cpi-2026-aug", synthetic: false }, SERVED), "cpi-surprise");
  assert.equal(frameForCase({ event_id: "us_cpi_2026-09", synthetic: false }, SERVED), "cpi-surprise");
});

test("no match selects nothing (no fallback to the first frame)", () => {
  assert.equal(frameForCase({ event_id: "ecb-2026-oct", synthetic: false }, SERVED), null);
  assert.equal(frameForCase({ event_id: "depot-strike", synthetic: false }, SERVED), null); // not SYNTHETIC
  assert.equal(frameForCase(null, SERVED), null);
});

test("a mapped frame the API does not serve selects nothing", () => {
  assert.equal(frameForCase({ event_id: "fomc-2026-jul" }, ["cpi-surprise"]), null);
});
