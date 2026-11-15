// Presenter token (lib/presenter.ts): sessionStorage only, and only run + reveal requests carry it.
// Run: npm test. No network: fetch is a stub that records each request and answers a coded 503.
import assert from "node:assert/strict";
import { afterEach, beforeEach, test } from "node:test";

const TOKEN = "c4".repeat(32); // the `openssl rand -hex 32` shape; a test value, not a real token

class MemoryStorage {
  constructor() {
    this.map = new Map();
    this.writes = [];
  }
  getItem(k) {
    return this.map.has(k) ? this.map.get(k) : null;
  }
  setItem(k, v) {
    this.writes.push([k, String(v)]);
    this.map.set(k, String(v));
  }
  removeItem(k) {
    this.map.delete(k);
  }
}

let sent;
let session;
let local;

beforeEach(() => {
  sent = [];
  session = new MemoryStorage();
  local = new MemoryStorage();
  globalThis.window = {
    sessionStorage: session,
    localStorage: local,
    location: { search: "", href: "http://web.test/" },
    dispatchEvent() {
      return true;
    },
  };
  globalThis.fetch = async (url, init = {}) => {
    sent.push({ url: String(url), method: init.method ?? "GET", headers: { ...(init.headers ?? {}) } });
    return new Response(JSON.stringify({ code: "BUSY", message: "fixture: busy" }), {
      status: 503,
      headers: { "content-type": "application/json" },
    });
  };
});

afterEach(() => {
  delete globalThis.window;
});

const presenter = await import("./presenter.ts");
const { runReplay } = await import("./replay.ts");
const { getCases, getCaseEvidence } = await import("./replay.ts");
const { revealPrediction, getBenchmark } = await import("./benchmark.ts");
const { getHealth, getScenarios } = await import("./api.ts");

const CASE = { event_id: "fixture_case", as_of: "2026-01-01T00:00:00Z" };
const auth = (r) => Object.entries(r.headers).find(([k]) => k.toLowerCase() === "authorization")?.[1];

test("a token-shaped value is stored in sessionStorage only, never localStorage", () => {
  assert.equal(presenter.setPresenterToken(`  ${TOKEN} `), true);
  assert.equal(session.getItem(presenter.PRESENTER_TOKEN_KEY), TOKEN);
  assert.equal(local.writes.length, 0);
  assert.equal(presenter.getPresenterToken(), TOKEN);
  presenter.clearPresenterToken();
  assert.equal(presenter.getPresenterToken(), null);
  assert.equal(local.writes.length, 0);
});

test("anything not 64 lower-case hex is refused and nothing is stored", () => {
  for (const bad of ["", "abc", TOKEN.toUpperCase(), TOKEN + "0", "g".repeat(64), `Bearer ${TOKEN}`]) {
    assert.equal(presenter.setPresenterToken(bad), false, bad);
  }
  assert.equal(session.writes.length, 0);
  assert.equal(local.writes.length, 0);
  assert.deepEqual(presenter.presenterAuthHeader(), {});
});

test("a stored value that is not token-shaped is ignored", () => {
  session.setItem(presenter.PRESENTER_TOKEN_KEY, "not-a-token");
  assert.equal(presenter.getPresenterToken(), null);
  assert.deepEqual(presenter.presenterAuthHeader(), {});
});

test("blocked storage means no token, never a throw", () => {
  globalThis.window = {
    get sessionStorage() {
      throw new Error("blocked");
    },
    dispatchEvent() {
      return true;
    },
  };
  assert.equal(presenter.setPresenterToken(TOKEN), false);
  assert.equal(presenter.getPresenterToken(), null);
  assert.doesNotThrow(() => presenter.clearPresenterToken());
});

test("run and reveal carry the bearer token when one is stored", async () => {
  presenter.setPresenterToken(TOKEN);
  await runReplay(CASE, "agent_only");
  await revealPrediction("pred_fixture");
  assert.equal(sent.length, 2);
  assert.match(sent[0].url, /\/api\/replay\/run$/);
  assert.match(sent[1].url, /\/api\/replay\/pred_fixture\/reveal$/);
  for (const r of sent) assert.equal(auth(r), `Bearer ${TOKEN}`, r.url);
});

test("run and reveal carry no Authorization header without a token", async () => {
  await runReplay(CASE, "agent_only");
  await revealPrediction("pred_fixture");
  assert.equal(sent.length, 2);
  for (const r of sent) assert.equal(auth(r), undefined, r.url);
});

test("no other request ever carries the token", async () => {
  presenter.setPresenterToken(TOKEN);
  await getHealth();
  await getScenarios();
  await getCases();
  await getCaseEvidence(CASE);
  await getBenchmark();
  assert.equal(sent.length, 5);
  for (const r of sent) assert.equal(auth(r), undefined, r.url);
  for (const r of sent) assert.ok(!r.url.includes(TOKEN), r.url);
});
