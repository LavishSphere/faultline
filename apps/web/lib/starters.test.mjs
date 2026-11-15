// Starter cards (#234): retry-then-swap and the standard questions. Pure functions, no network. Run: npm test.
// Every body below is a hand-built TEST FIXTURE shaped like GET /api/explore/chat/starters, never shown in the UI.
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  loadStartersWithRetry,
  MAX_STARTER_CARDS,
  newsCards,
  STARTERS_RETRIES,
  STARTERS_RETRY_MS,
  STATIC_STARTERS,
  startersRetryable,
} from "./starters.ts";

const starter = (q) => ({
  question: q,
  headline: `TEST FIXTURE headline for ${q}`,
  source_title: "TEST FIXTURE",
  source_url: "https://example.com/a",
  domain: "example.com",
  published_date: null,
  tag: "Leadership",
});
const body = (n) => ({
  provenance: "REAL (web, retrieved 2026-11-15T06:00:00Z)",
  generated_at: "2026-11-15T06:00:00Z",
  label: "TEST FIXTURE",
  starters: Array.from({ length: n }, (_, i) => starter(`Should TEST FIXTURE company ${i} act?`)),
});
const unavailable = { ok: false, kind: "http", status: 503, error: "HTTP 503" };
const timedOut = { ok: false, kind: "timeout", error: "timed out" };

/** A scripted fetcher plus a wait that records delays and returns at once. */
function script(results) {
  const waits = [];
  let calls = 0;
  return {
    fetchOnce: async () => results[Math.min(calls++, results.length - 1)],
    wait: async (ms) => void waits.push(ms),
    waits,
    get calls() {
      return calls;
    },
  };
}

test("a 503 shows the standard questions, then a retry swaps in the news questions", async () => {
  const s = script([unavailable, unavailable, { ok: true, data: body(4) }]);
  const seen = [];
  await loadStartersWithRetry((r) => seen.push(r), undefined, s.fetchOnce, s.wait);
  assert.equal(s.calls, 3);
  assert.deepEqual(s.waits, [STARTERS_RETRY_MS, STARTERS_RETRY_MS]);
  assert.equal(STARTERS_RETRY_MS, 15_000);
  assert.equal(seen.length, 2); // the first failure (standard cards), then the news; the second 503 is quiet
  assert.equal(seen[0].ok, false);
  assert.equal(seen[1].ok, true);
  const cards = newsCards(seen[1].data);
  assert.equal(cards.length, MAX_STARTER_CARDS);
  assert.ok(cards.every((c) => c.news));
});

test("a timeout is retried too; at most STARTERS_RETRIES retries, then it stays on the standard questions", async () => {
  const s = script([timedOut]);
  const seen = [];
  await loadStartersWithRetry((r) => seen.push(r), undefined, s.fetchOnce, s.wait);
  assert.equal(STARTERS_RETRIES, 3);
  assert.equal(s.calls, 1 + STARTERS_RETRIES);
  assert.equal(s.waits.length, STARTERS_RETRIES);
  assert.equal(seen.length, 1);
  assert.equal(seen[0].ok, false);
});

test("404, malformed and network failures are not retried", async () => {
  for (const r of [
    { ok: false, kind: "http", status: 404, error: "HTTP 404" },
    { ok: false, kind: "malformed", error: "malformed" },
    { ok: false, kind: "network", error: "down" },
  ]) {
    assert.equal(startersRetryable(r), false);
    const s = script([r]);
    await loadStartersWithRetry(() => {}, undefined, s.fetchOnce, s.wait);
    assert.equal(s.calls, 1);
  }
  assert.equal(startersRetryable(unavailable), true);
  assert.equal(startersRetryable(timedOut), true);
});

test("an abort stops the retries and reports nothing more", async () => {
  const ctrl = new AbortController();
  const s = script([unavailable, { ok: true, data: body(4) }]);
  const seen = [];
  const wait = async () => ctrl.abort();
  await loadStartersWithRetry((r) => seen.push(r), ctrl.signal, s.fetchOnce, wait);
  assert.equal(s.calls, 1);
  assert.equal(seen.length, 1);
});

test("fewer news questions are padded with standard ones: always four cards, padded ones have no news", () => {
  const cards = newsCards(body(2));
  assert.equal(cards.length, MAX_STARTER_CARDS);
  assert.equal(cards.filter((c) => c.news).length, 2);
  assert.deepEqual(cards.slice(2).map((c) => c.title), STATIC_STARTERS.slice(0, 2).map((c) => c.title));
  assert.equal(newsCards(body(6)).length, MAX_STARTER_CARDS);
});

test("standard questions: four real-company decisions, no scandal, cash or wage words, no news line", () => {
  assert.equal(STATIC_STARTERS.length, MAX_STARTER_CARDS);
  assert.deepEqual(STATIC_STARTERS.map((s) => s.tag), ["Leadership", "Leadership", "M&A", "Strategy"]);
  for (const s of STATIC_STARTERS) {
    assert.match(s.title, /^Should .+\?$/);
    assert.ok(s.prompt.startsWith(s.title.slice(0, -1)), s.prompt);
    assert.doesNotMatch(`${s.title} ${s.prompt}`, /scandal|cash|wage|payroll|floor|fraud|allege|misconduct/i);
    assert.equal(s.news, undefined);
  }
});
