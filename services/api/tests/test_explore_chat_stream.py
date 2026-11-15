"""POST /api/explore/chat/stream (#222): live tool steps as SSE, then the exact POST /api/explore/chat body.

Same scripted providers as tests/test_explore_chat.py (httpx2.MockTransport behind the real SDKs, no network).
The properties that matter: event order, `final` equal to the non-stream response, reply text never on the wire
before `final` (a withheld reply never at all), and every gate applying before any event is sent.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx2
import pytest
from test_explore_chat import (
    ADMIN,
    ANTHROPIC_KEY,
    LLAMA,
    OPENROUTER_KEY,
    OPENROUTER_MODELS,
    FakeProvider,
    Harness,
    oa_text,
    oa_tool_calls,
    tool_results_in,
)

from agents import explore_chat as chat
from agents import explore_chat_steps as steps
from routes import explore_chat as chat_routes


@pytest.fixture
def env(monkeypatch):
    """The same environment as tests/test_explore_chat.py's `env` fixture."""
    for name in ("FAULTLINE_MODE", "FAULTLINE_ADMIN_TOKEN", "FAULTLINE_PUBLIC_CHAT", "FAULTLINE_CHAT_MODELS",
                 "FAULTLINE_CHAT_PER_IP", "FAULTLINE_CHAT_CONCURRENCY", "FAULTLINE_CHAT_MAX_PRICE_PER_MTOK",
                 "TAVILY_API_KEY", "OPENAI_API_KEY", "FAULTLINE_RATE_LIMIT_PER_MIN"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", OPENROUTER_KEY)
    monkeypatch.setenv("ANTHROPIC_API_KEY", ANTHROPIC_KEY)
    monkeypatch.setenv("FAULTLINE_WEB_SEARCH_PROVIDER", "tavily")
    return monkeypatch


QUESTION = "What happens to cash in the bad quarter if we protect payroll?"
STREAM = "/api/explore/chat/stream"


def body(text: str = QUESTION, model_id: str = LLAMA) -> dict[str, Any]:
    return {"model_id": model_id, "messages": [{"role": "user", "content": text}]}


def parse_sse(raw: str) -> tuple[list[dict[str, Any]], list[str]]:
    """(data events in order, comment lines). Each event is one `data:` line followed by a blank line."""
    events: list[dict[str, Any]] = []
    comments: list[str] = []
    for block in raw.split("\n\n"):
        for line in block.splitlines():
            if line.startswith("data: "):
                events.append(json.loads(line[len("data: "):]))
            elif line.startswith(":"):
                comments.append(line)
    return events, comments


def stream(h: Harness, payload: dict[str, Any] | None = None, headers: dict[str, str] | None = None):
    return h.client.post(STREAM, json=payload or body(), headers=headers)


def two_tool_script() -> list:
    def final(b: dict[str, Any]) -> str:
        sim, opt = tool_results_in(b)
        return (f"In the bad quarter (SIMULATED) the lowest cash is ${sim['min_cash']:,.2f} in week "
                f"{sim['min_cash_week']}. With payroll protected the plan keeps cash at ${opt['min_cash']:,.2f}.")

    return [
        oa_tool_calls(("simulate", {"scenario_id": "bad-quarter", "shock": None}),
                      ("optimize", {"scenario_id": "bad-quarter", "shock": None, "protect_payroll": True})),
        oa_text(final),
    ]


# --------------------------------------------------------------------------- order and equality


def test_events_arrive_in_order_for_two_tool_calls(env):
    h = Harness(openrouter=FakeProvider(models=OPENROUTER_MODELS, replies=two_tool_script()))
    resp = stream(h)
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("text/event-stream")
    assert resp.headers["cache-control"] == "no-cache"
    assert resp.headers["x-accel-buffering"] == "no"
    events, _ = parse_sse(resp.text)
    assert [e["type"] for e in events] == ["start", "round", "tool_call", "tool_result", "tool_call", "tool_result",
                                           "final"]
    start, rnd, call1, res1, call2, res2, final = events
    assert start["model_id"] == LLAMA and start["provider"] == "openrouter" and start["started_at"]
    assert rnd == {"type": "round", "n": 1}
    assert (call1["id"], call1["name"], res1["id"], res1["name"]) == ("1.1", "simulate", "1.1", "simulate")
    assert (call2["id"], call2["name"], res2["id"], res2["name"]) == ("1.2", "optimize", "1.2", "optimize")
    assert call1["input_preview"] == "Simulating cash: bad-quarter"
    assert call2["input_preview"] == "Optimizing a recovery plan: bad-quarter · payroll protected"
    assert res1["result_status"] == res2["result_status"] == "ok"
    assert res1["provenance"] == "SIMULATED"

    # Previews are formatting of the engine's own summary (the same one in `final`), not new numbers.
    sim = final["response"]["tool_calls"][0]["result_summary"]
    assert res1["preview"] == (f"low point ${sim['min_cash']:,.0f} in week {sim['min_cash_week']} · "
                               f"ends at ${sim['ending_cash']:,.0f}")
    assert final["response"]["status"] == "ok"


def test_final_is_exactly_the_non_stream_response(env):
    plain = Harness(openrouter=FakeProvider(models=OPENROUTER_MODELS, replies=two_tool_script())).turn(QUESTION)
    assert plain.status_code == 200, plain.text
    events, _ = parse_sse(stream(Harness(openrouter=FakeProvider(models=OPENROUTER_MODELS,
                                                                  replies=two_tool_script()))).text)
    assert events[-1]["type"] == "final"
    assert events[-1]["response"] == plain.json()


def test_the_non_stream_route_is_unchanged_by_the_event_hook(env):
    """run_chat without on_event behaves as before (the JSON route passes no callback)."""
    h = Harness(openrouter=FakeProvider(models=OPENROUTER_MODELS, replies=two_tool_script()))
    out = h.turn(QUESTION).json()
    assert [c["name"] for c in out["tool_calls"]] == ["simulate", "optimize"] and out["status"] == "ok"


# --------------------------------------------------------------------------- reply text never leaks early


def test_a_withheld_reply_never_reaches_the_stream(env):
    canary = "CANARY-REPLY-7f3a"
    h = Harness(openrouter=FakeProvider(models=OPENROUTER_MODELS, replies=[
        oa_tool_calls(("simulate", {"scenario_id": "bad-quarter", "shock": None})),
        oa_text(f"{canary}: lowest cash is $987,654 (SIMULATED)."),
        oa_text(f"{canary} again: lowest cash is $987,654 (SIMULATED)."),  # the #221 repair round fails too
    ]))
    resp = stream(h)
    assert canary not in resp.text  # not before final, not in final
    events, _ = parse_sse(resp.text)
    final = events[-1]
    assert final["type"] == "final" and final["response"]["status"] == "error" and final["response"]["reply"] == ""
    assert any("figures the engine didn't produce" in n for n in final["response"]["notes"])


def test_an_ok_reply_appears_only_inside_final(env):
    h = Harness(openrouter=FakeProvider(models=OPENROUTER_MODELS, replies=two_tool_script()))
    events, _ = parse_sse(stream(h).text)
    reply = events[-1]["response"]["reply"]
    assert reply
    for e in events[:-1]:
        assert "lowest cash" not in json.dumps(e)
        assert set(e) <= {"type", "model_id", "provider", "started_at", "n", "id", "name", "input_preview",
                          "result_status", "provenance", "preview"}


def test_run_chat_events_carry_no_reply_text():
    """The hook itself: only round / tool_call / tool_result, never the text step."""
    seen: list[chat.ChatEvent] = []

    class Adapter:
        provider, model = "openrouter", "m"

        def __init__(self) -> None:
            self.steps = [chat.Step("", [chat.ToolRequest("a", "list_scenarios", {})], "tool_use", 1, 1),
                          chat.Step("SECRET-TEXT", [], "end", 1, 1)]

        def start(self, *_a: Any) -> None: ...

        async def step(self) -> chat.Step:
            return self.steps.pop(0)

        def add_tool_results(self, _r: Any) -> None: ...

    class Box:
        def specs(self) -> list[chat.ToolSpec]:
            return [chat.ToolSpec("list_scenarios", "d", {"type": "object", "properties": {}})]

        async def run(self, name: str, arguments: dict[str, Any]) -> chat.ToolOutcome:
            return chat.ToolOutcome("ok", "SYNTHETIC", {}, {"items": []})

    async def sink(ev: chat.ChatEvent) -> None:
        seen.append(ev)

    out = asyncio.run(chat.run_chat(Adapter(), Box(), [{"role": "user", "content": "hi"}], web_search=False,
                                    on_event=sink))
    assert out.reply == "SECRET-TEXT"
    assert [e.type for e in seen] == ["round", "tool_call", "tool_result"]
    assert "SECRET-TEXT" not in json.dumps([steps.event_payload(e) for e in seen])


# --------------------------------------------------------------------------- the same gates, before any event


def test_per_ip_limit_is_shared_with_the_json_route(env):
    env.setenv("FAULTLINE_CHAT_PER_IP", "2")
    h = Harness(openrouter=FakeProvider(models=OPENROUTER_MODELS, replies=[oa_text("Hi."), oa_text("Hi.")]))
    assert h.turn("hi").status_code == 200
    assert stream(h, body("hi")).status_code == 200
    limited = stream(h, body("hi"))
    assert limited.status_code == 429 and limited.json()["code"] == "RATE_LIMITED"
    assert int(limited.headers["retry-after"]) > 0
    assert "text/event-stream" not in limited.headers["content-type"]


def test_pause_budget_and_busy_refuse_before_streaming(env):
    env.setenv("FAULTLINE_CHAT_CONCURRENCY", "1")
    h = Harness()
    h.client.get("/api/explore/chat/status")
    state = h.app.state.faultline_chat

    state.active = 1
    busy = stream(h)
    assert busy.status_code == 503 and busy.json()["code"] == "BUSY"
    state.active = 0

    h.client.post("/api/explore/chat/pause", json={"paused": True})
    paused = stream(h)
    assert paused.status_code == 503 and paused.json()["code"] == "PAUSED"
    h.client.post("/api/explore/chat/pause", json={"paused": False})

    state.spent_today()
    state.spent_usd = 1e9
    over = stream(h)
    assert over.status_code == 503 and over.json()["code"] == "BUDGET"
    assert h.openrouter.chat_requests == []


def test_public_mode_stream_is_admin_only_unless_the_flag_is_on(env):
    env.setenv("FAULTLINE_MODE", "public")
    env.setenv("FAULTLINE_ADMIN_TOKEN", ADMIN)
    h = Harness(openrouter=FakeProvider(models=OPENROUTER_MODELS, replies=[oa_text("Hello."), oa_text("Hello.")]))
    refused = stream(h, body("hi"))
    assert refused.status_code == 401 and refused.json()["code"] == "ADMIN_TOKEN_REQUIRED"
    assert stream(h, body("hi"), headers={"Authorization": f"Bearer {ADMIN}"}).status_code == 200
    env.setenv("FAULTLINE_PUBLIC_CHAT", "1")
    assert stream(h, body("hi")).status_code == 200
    assert len(h.openrouter.chat_requests) == 2


def test_unknown_model_and_bad_body_are_422(env):
    h = Harness()
    assert stream(h, body(model_id="openrouter:nope/nothing")).status_code == 422
    assert stream(h, {"model_id": LLAMA, "messages": []}).status_code == 422
    assert stream(h, {**body(), "extra": 1}).status_code == 422


def test_price_cap_applies_to_the_stream(env):
    h = Harness()
    assert stream(h, body(model_id="openrouter:pricey/frontier-max")).status_code == 422


def test_provider_failure_mid_stream_is_an_error_event(env):
    h = Harness(openrouter=FakeProvider(models=OPENROUTER_MODELS, replies=[
        lambda _b: httpx2.Response(429, headers={"retry-after": "7"}, json={"error": {"message": "slow down"}})
        for _ in range(3)]))
    resp = stream(h)
    assert resp.status_code == 200
    events, _ = parse_sse(resp.text)
    assert [e["type"] for e in events] == ["start", "error"]
    assert events[-1]["code"] == "RATE_LIMITED" and events[-1]["status"] == 429
    assert h.app.state.faultline_chat.active == 0


def test_heartbeat_comments_while_a_tool_runs(env, monkeypatch):
    monkeypatch.setattr(chat_routes, "HEARTBEAT_S", 0.02)
    real_run = chat_routes.EngineToolBox.run

    async def slow_run(self, name: str, arguments: dict[str, Any]) -> chat.ToolOutcome:
        await asyncio.sleep(0.15)
        return await real_run(self, name, arguments)

    monkeypatch.setattr(chat_routes.EngineToolBox, "run", slow_run)
    h = Harness(openrouter=FakeProvider(models=OPENROUTER_MODELS, replies=[
        oa_tool_calls(("list_scenarios", {})), oa_text("Here are the scenarios (SYNTHETIC).")]))
    events, comments = parse_sse(stream(h).text)
    assert comments and all(c == ": heartbeat" for c in comments)
    assert events[-1]["type"] == "final" and events[-1]["response"]["status"] == "ok"


# --------------------------------------------------------------------------- previews


def test_previews_for_web_search_and_monte_carlo():
    web = chat.ToolOutcome("ok", "LIVE EXPLORE", {"query": "q"}, {"results": [
        {"domain": "sec.gov"}, {"domain": "cnbc.com"}, {"domain": "sec.gov"}, {"domain": "ft.com"},
        {"domain": "wsj.com"}]})
    assert steps.call_preview("web_search", {"query": "Nvidia CEO succession"}) == \
        "Searching the web: “Nvidia CEO succession”"
    assert steps.result_preview("web_search", web) == "5 sources: sec.gov, cnbc.com, ft.com, …"
    credited = chat.ToolOutcome("ok", "LIVE EXPLORE", {"query": "q"}, {"results": [{"domain": "cnbc.com"}],
                                "attribution": "Search powered by Tavily"})
    assert steps.result_preview("web_search", credited) == "1 source via Tavily: cnbc.com"
    mc = chat.ToolOutcome("ok", "SIMULATED", {}, {
        "n_paths": 20000, "best": {"id": "keep", "prob_best": 0.624, "ci95": [0.617, 0.631]},
        "options": [{"id": "keep", "label": "Keep"}, {"id": "sell", "label": "Sell"}]})
    assert steps.result_preview("monte_carlo_decision", mc) == "best: Keep 62% (CI 62-63%) · 20,000 paths"
    assert steps.call_preview("monte_carlo_decision", {
        "options": [{"id": "keep", "label": "Keep"}, {"id": "sell", "label": "Sell"}], "n_paths": 20000}) == \
        "Running Monte Carlo · 20,000 paths · Keep vs Sell"
    assert steps.call_preview("list_scenarios", {}) == "Reading the engine: scenarios"
    err = chat.ToolOutcome("error", "SIMULATED", {}, {"error": "shock failed validation"})
    assert steps.result_preview("simulate", err) == "error: shock failed validation"
    assert steps.call_preview("simulate", None) == "simulate: arguments were not a JSON object"


def test_a_repair_round_streams_only_a_count_and_tool_steps_keep_flowing(env):
    """#221 repair inside run_chat: the stream says a rewrite was asked for (a count, never the failed figures), and
    a tool call the model makes after the repair still streams."""
    canary = "CANARY-FIRST-DRAFT-91b2"
    h = Harness(openrouter=FakeProvider(models=OPENROUTER_MODELS, replies=[
        oa_tool_calls(("simulate", {"scenario_id": "bad-quarter", "shock": None})),
        oa_text(f"{canary}: lowest cash is $987,654 (SIMULATED)."),
        oa_tool_calls(("list_scenarios", {})),
        oa_text("The bad quarter is the hardest case (SIMULATED)."),
    ]))
    resp = stream(h)
    events, _ = parse_sse(resp.text)
    types = [e["type"] for e in events]
    assert types == ["start", "round", "tool_call", "tool_result", "repair", "round", "tool_call", "tool_result",
                     "final"]
    repair = events[4]
    assert repair["n"] == 1 and "rewrite" in repair["preview"]
    assert canary not in resp.text
    assert all("987,654" not in json.dumps(e) for e in events[:-1])
    assert events[6]["name"] == "list_scenarios" and events[6]["id"] == "2.1"
    assert events[-1]["response"]["status"] == "ok"
