// "Ask the engine" chat client checks (issue #186). Pure functions, no network. Run: npm test.
// Every body below is a hand-built TEST FIXTURE shaped like the chat contract, never shown in the UI. The checks under
// test only accept or refuse a body, group models, or map a tool call to its engine route; they compute no result.
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  CHAT_LABEL,
  CHAT_MAX_CHARS,
  CHAT_MAX_MESSAGES,
  CHAT_PROVENANCE,
  checkChatResponse,
  checkModelsResponse,
  contextLabel,
  describeChatFailure,
  featuredModels,
  groupModels,
  pickerGroups,
  initialModel,
  messageProblem,
  priceLabel,
  SseParser,
  applyStreamEvent,
  readStreamEvent,
  streamChat,
} from "./chat.ts";
import { PRESENTER_KEY, clearPresenterToken, presenterHeaders, setPresenterToken } from "./presenter.ts";

const model = (id, provider, available = true, note = null) => ({ id, label: `Label ${id}`, provider, available, note });

function reply(over = {}) {
  return {
    status: "ok",
    provenance: CHAT_PROVENANCE,
    label: CHAT_LABEL,
    model_id: "m-a",
    provider: "anthropic",
    reply: "fixture reply",
    tool_calls: [
      { name: "simulate", input: { shock: {} }, result_status: "ok", result_summary: "fixture summary", provenance: "SIMULATED" },
    ],
    usage: { input_tokens: 10, output_tokens: 20 },
    notes: [],
    ...over,
  };
}

test("models listing: a valid body passes", () => {
  const body = { models: [model("m-a", "anthropic"), model("m-b", "openai", false, "no key")], default: "m-a" };
  assert.equal(checkModelsResponse(body), null);
  assert.equal(checkModelsResponse({ models: [], default: null }), null);
});

test("models listing: shape errors are refused", () => {
  assert.match(checkModelsResponse(null), /models/);
  assert.match(checkModelsResponse({ models: [model("x", "mystery")], default: null }), /unknown provider/);
  assert.match(checkModelsResponse({ models: [{ ...model("x", "openai"), available: "yes" }], default: null }), /availability/);
  assert.match(checkModelsResponse({ models: [model("x", "openai"), model("x", "openai")], default: null }), /duplicate/);
  assert.match(checkModelsResponse({ models: [], default: 3 }), /default/);
});

test("models are grouped OpenRouter, OpenAI, Anthropic regardless of server order", () => {
  const groups = groupModels([model("a1", "anthropic"), model("o1", "openai"), model("r1", "openrouter"), model("a2", "anthropic")]);
  assert.deepEqual(groups.map((g) => g.provider), ["openrouter", "openai", "anthropic"]);
  assert.deepEqual(groups[2].models.map((m) => m.id), ["a1", "a2"]);
  assert.deepEqual(groupModels([model("o1", "openai")]).map((g) => g.provider), ["openai"]);
});

test("picker groups: open weights vs closed APIs only from the served field; provider grouping otherwise", () => {
  const open = { ...model("llama", "openrouter"), open_weights: true };
  const gemini = { ...model("gemini", "openrouter"), open_weights: false };
  const grok = { ...model("grok", "openrouter"), open_weights: false };
  const claude = { ...model("claude", "anthropic"), open_weights: false };
  const groups = pickerGroups([gemini, open, claude, grok]);
  assert.deepEqual(groups.map((g) => g.label), ["Open weights · self-hostable", "Closed APIs"]);
  assert.deepEqual(groups[0].models.map((m) => m.id), ["llama"]);
  assert.deepEqual(groups[1].models.map((m) => m.id), ["gemini", "claude", "grok"]);
  // A model without the field is never put under the open heading.
  assert.deepEqual(pickerGroups([open, model("x", "openrouter")]).map((g) => g.key), ["open", "unknown"]);
  // No field anywhere: provider grouping, and the OpenRouter label does not claim the models are open.
  const fallback = pickerGroups([model("r1", "openrouter"), model("a1", "anthropic")]);
  assert.deepEqual(fallback.map((g) => g.key), ["openrouter", "anthropic"]);
  assert.ok(!/open/i.test(fallback[0].label.replace(/openrouter/i, "")));
  assert.match(checkModelsResponse({ models: [{ ...model("x", "openai"), open_weights: "yes" }], default: null }), /open_weights/);
});

test("the server default is preselected only when it is available", () => {
  assert.equal(initialModel({ models: [model("a", "openai"), model("b", "anthropic")], default: "b" }), "b");
  assert.equal(initialModel({ models: [model("a", "openai"), model("b", "anthropic", false)], default: "b" }), null);
  assert.equal(initialModel({ models: [model("a", "openai")], default: null }), null);
  assert.equal(initialModel({ models: [model("a", "openai")], default: "gone" }), null);
});

test("chat reply: a valid body passes, including usage null and the non-ok statuses", () => {
  assert.equal(checkChatResponse(reply()), null);
  assert.equal(checkChatResponse(reply({ usage: null })), null);
  assert.equal(checkChatResponse(reply({ status: "unavailable", reply: "", tool_calls: [], notes: ["no key"] })), null);
  assert.equal(checkChatResponse(reply({ status: "error" })), null);
  // The #193 backend sends result_summary as an object of engine fields.
  const objSummary = { name: "optimize", input: { shock: {}, protect_payroll: true }, result_status: "ok", result_summary: { status: "OPTIMAL" }, provenance: "SIMULATED" };
  assert.equal(checkChatResponse(reply({ tool_calls: [objSummary] })), null);
  assert.match(checkChatResponse(reply({ tool_calls: [{ ...objSummary, result_summary: 3 }] })), /result/);
  assert.match(checkChatResponse(reply({ tool_calls: [{ ...objSummary, result_summary: [1] }] })), /result/);
});

test("chat reply: an unknown status is rejected", () => {
  assert.equal(checkChatResponse(reply({ status: "streaming" })), "unknown status");
  assert.equal(checkChatResponse(reply({ status: "OK" })), "unknown status");
  assert.equal(checkChatResponse(reply({ status: undefined })), "unknown status");
});

test("chat reply: other shape errors are rejected", () => {
  assert.match(checkChatResponse(reply({ provenance: "SIMULATED" })), /LIVE EXPLORE/);
  assert.match(checkChatResponse(reply({ provider: "mystery" })), /provider/);
  assert.match(checkChatResponse(reply({ reply: null })), /reply/);
  assert.match(checkChatResponse(reply({ tool_calls: null })), /tool_calls/);
  assert.match(checkChatResponse(reply({ tool_calls: [{ name: "simulate", input: "x", result_status: "ok", result_summary: null, provenance: "SIMULATED" }] })), /input/);
  assert.match(checkChatResponse(reply({ tool_calls: [{ name: "simulate", input: {}, result_status: "ok", result_summary: null }] })), /provenance/);
  assert.match(checkChatResponse(reply({ usage: { input_tokens: -1, output_tokens: 2 } })), /usage/);
  assert.match(checkChatResponse(reply({ usage: { input_tokens: 1.5, output_tokens: 2 } })), /usage/);
  assert.match(checkChatResponse(reply({ notes: [1] })), /notes/);
});

test("message limits mirror the server: 4,000 characters, 20 messages", () => {
  assert.equal(messageProblem("hello", []), null);
  assert.match(messageProblem("   ", []), /Type/);
  assert.equal(messageProblem("x".repeat(CHAT_MAX_CHARS), []), null);
  assert.match(messageProblem("x".repeat(CHAT_MAX_CHARS + 1), []), /4,000/);
  const full = Array.from({ length: CHAT_MAX_MESSAGES - 1 }, (_, i) => ({ role: i % 2 ? "assistant" : "user", content: "x" }));
  assert.equal(messageProblem("one more", full), null);
  assert.match(messageProblem("one too many", [...full, { role: "assistant", content: "x" }]), /20-message limit/);
});

test("failures map to honest messages", () => {
  assert.equal(describeChatFailure({ ok: false, kind: "http", status: 429, code: "RATE_LIMITED", error: "slow down" }).heading, "Limit reached, try again in a few minutes.");
  assert.equal(describeChatFailure({ ok: false, kind: "http", status: 503, code: "PAUSED", error: "x" }).kind, "paused");
  assert.equal(describeChatFailure({ ok: false, kind: "http", status: 503, code: "BUSY", error: "x" }).kind, "busy");
  assert.equal(describeChatFailure({ ok: false, kind: "http", status: 503, code: "LIVE_EXPLORE_UNAVAILABLE", error: "no key" }).detail, "no key");
  assert.equal(describeChatFailure({ ok: false, kind: "http", status: 403, error: "admin" }).heading, "Chat is disabled on the public demo right now.");
  assert.equal(describeChatFailure({ ok: false, kind: "http", status: 401, error: "admin" }).kind, "admin");
  assert.equal(describeChatFailure({ ok: false, kind: "http", status: 502, code: "UPSTREAM_ERROR", error: "x" }).kind, "upstream");
  assert.equal(describeChatFailure({ ok: false, kind: "validation", status: 422, error: "too long" }).detail, "too long");
  assert.equal(describeChatFailure({ ok: false, kind: "network", error: "failed" }).kind, "unreachable");
  assert.equal(describeChatFailure({ ok: false, kind: "malformed", error: "bad" }).kind, "malformed");
  assert.equal(describeChatFailure({ ok: false, kind: "http", status: 500, error: "HTTP 500" }).detail, null);
});

test("catalogue fields: context length and per-million prices are checked when served", () => {
  const m = { ...model("x", "openrouter"), context_length: 131072, pricing: { input_per_mtok: 0.2, output_per_mtok: 0.6 } };
  assert.equal(checkModelsResponse({ models: [m], default: null, featured: ["x"] }), null);
  assert.equal(checkModelsResponse({ models: [{ ...m, pricing: null, context_length: null }], default: null }), null);
  assert.match(checkModelsResponse({ models: [{ ...m, context_length: "big" }], default: null }), /context_length/);
  assert.match(checkModelsResponse({ models: [{ ...m, pricing: { input_per_mtok: -1 } }], default: null }), /pricing/);
  assert.match(checkModelsResponse({ models: [m], default: null, featured: "x" }), /featured/);
  assert.equal(contextLabel(m), "131K ctx");
  assert.equal(contextLabel({ ...m, context_length: 1_000_000 }), "1M ctx");
  assert.equal(contextLabel(model("y", "openai")), null);
  assert.equal(priceLabel(m), "$0.20 in · $0.60 out /M tok");
  assert.equal(priceLabel({ ...m, pricing: { output_per_mtok: 15 } }), "n/a in · $15.00 out /M tok");
  assert.equal(priceLabel(model("y", "openai")), null);
});

test("featured models: listed ids only, deduplicated, in provider order", () => {
  const models = [model("c", "anthropic"), model("g", "openai"), model("l", "openrouter"), model("q", "openrouter")];
  const ids = featuredModels({ models, default: null, featured: ["c", "missing", "g", "l", "c"] }).map((m) => m.id);
  assert.deepEqual(ids, ["l", "g", "c"]);
  assert.deepEqual(featuredModels({ models, default: null }), []);
});

// ---- streaming (#222) and presenter mode -------------------------------------------------------------------------
// Bodies below are hand-built TEST FIXTURES shaped like the stream contract, never real model output.

test("SSE parser: events split across chunks, CRLF, comments and multi-line data", () => {
  const p = new SseParser();
  assert.deepEqual(p.feed('data: {"type":"ro'), []);
  assert.deepEqual(p.feed('und","n":1}\n\n: heartbeat\n\n'), ['{"type":"round","n":1}']);
  assert.deepEqual(p.feed("data: a\r\ndata: b\r"), []);
  assert.deepEqual(p.feed("\n\r\n"), ["a\nb"]);
  assert.deepEqual(p.feed("event: x\nid: 3\ndata:no-space\n\n"), ["no-space"]);
  assert.deepEqual(p.feed(": only a comment\n\n"), []);
});

test("stream events: shapes are checked, unknown or malformed ones are dropped", () => {
  assert.deepEqual(readStreamEvent('{"type":"round","n":2}'), { type: "round", n: 2 });
  assert.equal(readStreamEvent('{"type":"tool_call","id":"1.1"}'), null);
  assert.equal(readStreamEvent('{"type":"reply_delta","text":"hi"}'), null); // no such event: never shown
  assert.equal(readStreamEvent("not json"), null);
  assert.equal(readStreamEvent(JSON.stringify({ type: "final", response: { status: "ok" } })), null);
  assert.equal(readStreamEvent(JSON.stringify({ type: "final", response: reply() })).type, "final");
});

test("live steps: a call runs, then ticks to ok or error with the server's preview", () => {
  let steps = applyStreamEvent([], { type: "tool_call", id: "1.1", name: "web_search", input_preview: "Searching the web: “x”" });
  steps = applyStreamEvent(steps, { type: "tool_call", id: "1.2", name: "simulate", input_preview: "Simulating cash: bad-quarter" });
  assert.deepEqual(steps.map((s) => s.status), ["running", "running"]);
  steps = applyStreamEvent(steps, { type: "tool_result", id: "1.1", name: "web_search", result_status: "ok", preview: "8 sources: sec.gov", provenance: "LIVE EXPLORE" });
  steps = applyStreamEvent(steps, { type: "tool_result", id: "1.2", name: "simulate", result_status: "error", preview: "error: bad", provenance: "SIMULATED" });
  assert.deepEqual(steps.map((s) => [s.status, s.preview]), [["ok", "8 sources: sec.gov"], ["error", "error: bad"]]);
  const repair = readStreamEvent('{"type":"repair","n":2,"preview":"Checking figures: 2 figures not in any tool result"}');
  steps = applyStreamEvent(steps, repair);
  assert.deepEqual(steps.at(-1), { id: "repair-2", name: "repair", input: "Checking figures: 2 figures not in any tool result", status: "note", preview: null });
});

function sseResponse(lines, status = 200) {
  const enc = new TextEncoder();
  const body = new ReadableStream({
    start(c) {
      for (const l of lines) c.enqueue(enc.encode(l));
      c.close();
    },
  });
  return new Response(body, { status, headers: { "content-type": "text/event-stream" } });
}

async function withFetch(impl, fn) {
  const real = globalThis.fetch;
  globalThis.fetch = impl;
  try {
    return await fn();
  } finally {
    globalThis.fetch = real;
  }
}

const ASK = { model_id: "m-a", messages: [{ role: "user", content: "q" }] };
const jsonResponse = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

test("streamChat: steps reach onEvent before final; final is the checked response", async () => {
  const seen = [];
  const res = await withFetch(
    async () =>
      sseResponse([
        'data: {"type":"start","model_id":"m-a","provider":"anthropic","started_at":"2026-11-15T00:00:00Z"}\n\n',
        'data: {"type":"tool_call","id":"1.1","name":"simulate","input_preview":"Simulating cash"}\n\n',
        ": heartbeat\n\n",
        `data: ${JSON.stringify({ type: "final", response: reply() })}\n\n`,
      ]),
    () => streamChat(ASK, (e) => seen.push(e.type)),
  );
  assert.equal(res.ok, true);
  assert.equal(res.data.reply, "fixture reply");
  assert.deepEqual(seen, ["start", "tool_call"]);
});

test("streamChat: an error event is a failure with the server's code, never retried", async () => {
  let calls = 0;
  const res = await withFetch(
    async () => {
      calls += 1;
      return sseResponse([
        'data: {"type":"start","model_id":"m","provider":"openai","started_at":""}\n\n',
        'data: {"type":"error","code":"UPSTREAM_ERROR","message":"No reply was made up.","status":502}\n\n',
      ]);
    },
    () => streamChat(ASK, () => {}),
  );
  assert.equal(res.ok, false);
  assert.equal(res.status, 502);
  assert.equal(res.code, "UPSTREAM_ERROR");
  assert.equal(calls, 1);
});

test("streamChat: 404 or a stream that ends before final falls back to POST /api/explore/chat", async () => {
  for (const first of [() => new Response("{}", { status: 404 }), () => sseResponse(['data: {"type":"round","n":1}\n\n'])]) {
    const urls = [];
    const notices = [];
    const res = await withFetch(
      async (url) => {
        urls.push(String(url));
        return urls.length === 1 ? first() : jsonResponse(reply());
      },
      () => streamChat(ASK, (e) => notices.push(e.type)),
    );
    assert.equal(res.ok, true);
    assert.match(urls[0], /\/api\/explore\/chat\/stream$/);
    assert.match(urls[1], /\/api\/explore\/chat$/);
    assert.equal(notices.at(-1), "fallback");
  }
});

test("streamChat: a refusal (429) is returned as is, with no fallback", async () => {
  const urls = [];
  const res = await withFetch(
    async (url) => {
      urls.push(String(url));
      return jsonResponse({ code: "RATE_LIMITED", message: "Chat limit reached" }, 429);
    },
    () => streamChat(ASK, () => {}),
  );
  assert.equal(res.ok, false);
  assert.equal(res.status, 429);
  assert.equal(res.code, "RATE_LIMITED");
  assert.equal(urls.length, 1);
});

function fakeStorage() {
  const m = new Map();
  return { getItem: (k) => m.get(k) ?? null, setItem: (k, v) => m.set(k, String(v)), removeItem: (k) => m.delete(k) };
}

function withStorage(value, fn) {
  const had = Object.getOwnPropertyDescriptor(globalThis, "localStorage");
  Object.defineProperty(globalThis, "localStorage", { value, configurable: true, writable: true });
  const restore = () => (had ? Object.defineProperty(globalThis, "localStorage", had) : delete globalThis.localStorage);
  try {
    const out = fn();
    return out instanceof Promise ? out.finally(restore) : (restore(), out);
  } catch (err) {
    restore();
    throw err;
  }
}

test("presenter mode: Authorization is sent only when a token is stored", async () => {
  await withStorage(fakeStorage(), async () => {
    assert.deepEqual(presenterHeaders(), {});
    const sent = [];
    const capture = async (_url, init) => {
      sent.push(new Headers(init.headers).get("authorization"));
      return new Response("{}", { status: 404 });
    };
    await withFetch(capture, () => streamChat(ASK, () => {}));
    assert.ok(setPresenterToken("  tok-fixture  "));
    assert.equal(globalThis.localStorage.getItem(PRESENTER_KEY), "tok-fixture");
    await withFetch(capture, () => streamChat(ASK, () => {}));
    // The stream, then its 404 fallback, twice: no header without a token, Bearer with one.
    assert.deepEqual(sent, [null, null, "Bearer tok-fixture", "Bearer tok-fixture"]);
    clearPresenterToken();
    assert.deepEqual(presenterHeaders(), {});
  });
});

test("presenter mode: storage that throws means presenter mode is off, never a crash", () => {
  const boom = () => {
    throw new Error("blocked");
  };
  withStorage({ getItem: boom, setItem: boom, removeItem: boom }, () => {
    assert.deepEqual(presenterHeaders(), {});
    assert.equal(setPresenterToken("x"), false);
    clearPresenterToken();
  });
});
