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
  initialModel,
  messageProblem,
  priceLabel,
} from "./chat.ts";

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
