"""Chat web_search through Anthropic / OpenAI server-side web search (#214).

Both SDKs are mocked at the HTTP layer (httpx2.MockTransport) with response bodies in the documented shapes, so the
real SDK parses them; no test touches the network. Covers: the result shape, citations mapped to urls, the
MODEL-WRITTEN summary excluded from the figure check, provider order, pause_turn, timeouts, caps, and the wall.
"""

from __future__ import annotations

import ast
import asyncio
import json
import re
from pathlib import Path
from typing import Any

import httpx2
import pytest
from test_explore_chat import (
    ADMIN,
    ANTHROPIC_KEY,
    ANTHROPIC_LIST,
    OPENAI_KEY,
    OPENROUTER_KEY,
    OPENROUTER_MODELS,
    FakeProvider,
    Harness,
    oa_text,
    oa_tool_calls,
)

from agents import explore_chat as chat
from agents import explore_web_search as web
from config import get_settings
from routes import explore_chat as chat_routes

CITED = "Nvidia reported quarterly revenue of $57.0 billion, the company said on Nov. 19."
SUMMARY = "Analysts expect revenue of $65 billion next quarter."  # a figure ONLY in the model's prose
URL_A = "https://News.Example.com/nvidia-ceo"
URL_B = "https://other.example.org/governance"


def search_block(tool_id: str = "srvtoolu_1") -> list[dict[str, Any]]:
    return [
        {"type": "server_tool_use", "id": tool_id, "name": "web_search", "input": {"query": "Nvidia CEO"}},
        {"type": "web_search_tool_result", "tool_use_id": tool_id, "content": [
            {"type": "web_search_result", "url": URL_B, "title": "Governance page", "encrypted_content": "EqQ",
             "page_age": None},
            {"type": "web_search_result", "url": URL_A, "title": "Nvidia CEO news", "encrypted_content": "EqR",
             "page_age": "November 3, 2026"},
        ]},
    ]


def text_blocks() -> list[dict[str, Any]]:
    return [
        {"type": "text", "text": SUMMARY + " ", "citations": None},
        {"type": "text", "text": "Nvidia's quarterly revenue was $57.0 billion.", "citations": [
            {"type": "web_search_result_location", "url": URL_A, "title": "Nvidia CEO news", "encrypted_index": "Eo8",
             "cited_text": CITED}]},
    ]


def an_reply(content: list[dict[str, Any]], stop_reason: str = "end_turn"):
    def reply(_body: dict[str, Any]) -> httpx2.Response:
        return httpx2.Response(200, json={
            "id": "msg_ws", "type": "message", "role": "assistant", "model": web.ANTHROPIC_SEARCH_MODEL,
            "content": content, "stop_reason": stop_reason, "stop_sequence": None,
            "usage": {"input_tokens": 900, "output_tokens": 120, "server_tool_use": {"web_search_requests": 1}}})
    return reply


def oai_reply(_body: dict[str, Any]) -> httpx2.Response:
    text = "Nvidia's revenue was $57.0 billion ([example.com](https://news.example.com/a)). Leadership is stable."
    start = text.index("([")
    return httpx2.Response(200, json={
        "id": "resp_1", "object": "response", "created_at": 0, "status": "completed", "model": web.OPENAI_SEARCH_MODEL,
        "output": [
            {"type": "web_search_call", "id": "ws_1", "status": "completed",
             "action": {"type": "search", "query": "Nvidia CEO"}},
            {"type": "message", "id": "msg_1", "role": "assistant", "status": "completed", "content": [
                {"type": "output_text", "text": text, "logprobs": [], "annotations": [
                    {"type": "url_citation", "url": "https://news.example.com/a", "title": "Nvidia news",
                     "start_index": start, "end_index": text.index(")", text.index("](")) + 2}]}]}],
        "parallel_tool_calls": True, "tool_choice": "auto", "tools": [], "temperature": 1.0, "top_p": 1.0,
        "incomplete_details": None, "error": None, "instructions": None, "metadata": {},
        "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15,
                  "input_tokens_details": {"cached_tokens": 0}, "output_tokens_details": {"reasoning_tokens": 0}}})


@pytest.fixture
def env(monkeypatch):
    for name in ("FAULTLINE_MODE", "FAULTLINE_ADMIN_TOKEN", "FAULTLINE_PUBLIC_CHAT", "FAULTLINE_CHAT_MODELS",
                 "FAULTLINE_CHAT_PER_IP", "FAULTLINE_CHAT_CONCURRENCY", "FAULTLINE_CHAT_MAX_PRICE_PER_MTOK",
                 "TAVILY_API_KEY", "OPENAI_API_KEY", "FAULTLINE_RATE_LIMIT_PER_MIN", "FAULTLINE_CHAT_WEB_PER_IP_DAY",
                 "FAULTLINE_CHAT_WEB_DAILY", "FAULTLINE_WEB_SEARCH_PROVIDER"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", OPENROUTER_KEY)
    monkeypatch.setenv("ANTHROPIC_API_KEY", ANTHROPIC_KEY)
    return monkeypatch


def factory(anthropic: FakeProvider | None = None, openai: FakeProvider | None = None) -> chat.ClientFactory:
    transports = {}
    if anthropic is not None:
        transports["anthropic"] = anthropic.transport()
    if openai is not None:
        transports["openai"] = openai.transport()
    return chat.ClientFactory(transports)


def run_tool(provider: FakeProvider, *, kind: str = "anthropic", quota=None) -> chat.ToolOutcome:
    clients = factory(anthropic=provider) if kind == "anthropic" else factory(openai=provider)
    box = chat_routes.EngineToolBox(get_settings(), None, web_quota=quota, web_clients=clients)
    return asyncio.run(box.run("web_search", {"query": "Nvidia CEO Jensen Huang succession 2026"}))


# --------------------------------------------------------------------------- leakage wall (written first)


def test_module_imports_nothing_from_the_replay_side():
    tree = ast.parse(Path(web.__file__).read_text(encoding="utf-8"))
    imported = {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    imported |= {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    banned = ("core.temporal_gate", "core.store", "core.evaluator", "core.provenance", "core.forecasting",
              "agents.provider", "agents.local_ollama", "routes.replay", "routes.cases", "routes.benchmark", "markets")
    assert not [m for m in imported if m.startswith(banned)], imported
    assert "sealed_outcomes" not in Path(web.__file__).read_text(encoding="utf-8")


def test_the_separation_sweep_flags_the_module_name():
    from test_explore_separation import live_explore_refs
    assert live_explore_refs("from agents import explore_web_search")
    assert live_explore_refs("import agents.explore_web_search")


# --------------------------------------------------------------------------- provider order


@pytest.mark.parametrize(("forced", "keys", "expected"), [
    (None, {"TAVILY_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY"}, "tavily"),
    (None, {"ANTHROPIC_API_KEY", "OPENAI_API_KEY"}, "anthropic"),
    (None, {"OPENAI_API_KEY"}, "openai"),
    (None, set(), None),
    ("auto", {"ANTHROPIC_API_KEY"}, "anthropic"),
    ("bogus", {"OPENAI_API_KEY"}, "openai"),  # an unknown value behaves as auto
    ("openai", {"TAVILY_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY"}, "openai"),
    ("anthropic", {"TAVILY_API_KEY"}, None),  # a forced provider without its key: no web_search, no silent switch
    ("TAVILY", {"TAVILY_API_KEY", "ANTHROPIC_API_KEY"}, "tavily"),
])
def test_provider_order(monkeypatch, forced, keys, expected):
    for name in ("TAVILY_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "FAULTLINE_WEB_SEARCH_PROVIDER"):
        monkeypatch.delenv(name, raising=False)
    for name in keys:
        monkeypatch.setenv(name, "k-" + "x" * 30)
    if forced is not None:
        monkeypatch.setenv("FAULTLINE_WEB_SEARCH_PROVIDER", forced)
    assert web.provider_from_env() == expected
    box = chat_routes.EngineToolBox(get_settings(), None)
    assert box.web is (expected is not None)
    assert ("web_search" in [s.name for s in box.specs()]) is (expected is not None)


def test_health_reports_the_provider_name_only(env):
    from fastapi.testclient import TestClient

    from main import create_app
    body = TestClient(create_app()).get("/api/health").json()
    assert body["web_search_provider"] == "anthropic"
    assert ANTHROPIC_KEY not in json.dumps(body)


# --------------------------------------------------------------------------- Anthropic: shape, citations, request


def test_anthropic_result_shape_and_citations_map_to_urls(env):
    provider = FakeProvider(replies=[an_reply(search_block() + text_blocks())])
    out = run_tool(provider)
    assert out.status == "ok" and out.provenance == "LIVE EXPLORE"
    s = out.summary
    assert set(s) == {"provenance", "retrieved_at", "query", "results", "attribution", "note", "summary",
                      "summary_label"}
    assert re.fullmatch(r"REAL \(web, retrieved \d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ\)", s["provenance"])
    assert s["attribution"] == "Search by Anthropic Claude web search" and "verbatim page quotes" in s["note"]
    assert s["summary_label"] == "MODEL-WRITTEN search summary" and SUMMARY in s["summary"]
    cited, uncited = s["results"]  # cited results first
    assert set(cited) == {"title", "url", "domain", "published_date", "snippet"}
    assert cited["url"] == URL_A and cited["domain"] == "news.example.com"
    assert cited["snippet"] == CITED and cited["published_date"] == "November 3, 2026"
    assert uncited["url"] == URL_B and uncited["snippet"] == "" and uncited["published_date"] is None
    assert SUMMARY not in json.dumps(s["results"])  # model prose never lands in a snippet

    (req,) = provider.chat_requests
    body = req["json"]
    assert body["model"] == "claude-sonnet-5-5" and body["max_tokens"] == 1500
    assert body["tools"] == [{"type": "web_search_20250305", "name": "web_search", "max_uses": 3}]
    assert "citations" in body["system"]


def test_anthropic_search_error_block_and_no_results_is_a_tool_error(env):
    blocks = [{"type": "server_tool_use", "id": "s1", "name": "web_search", "input": {"query": "q"}},
              {"type": "web_search_tool_result", "tool_use_id": "s1",
               "content": {"type": "web_search_tool_result_error", "error_code": "too_many_requests"}},
              {"type": "text", "text": "I could not search.", "citations": None}]
    out = run_tool(FakeProvider(replies=[an_reply(blocks)]))
    assert out.status == "error" and "results" not in out.summary and "no_results" in out.summary["error"]


def test_pause_turn_is_resumed_with_the_paused_turn(env):
    paused = search_block()
    provider = FakeProvider(replies=[an_reply(paused, "pause_turn"), an_reply(text_blocks())])
    out = run_tool(provider)
    assert out.status == "ok" and out.summary["results"][0]["snippet"] == CITED
    first, second = (r["json"] for r in provider.chat_requests)
    assert len(first["messages"]) == 1
    assert [m["role"] for m in second["messages"]] == ["user", "assistant"]  # no extra "continue" user message
    assert second["messages"][1]["content"][0]["type"] == "server_tool_use"


def test_pause_turn_is_resumed_at_most_twice(env):
    provider = FakeProvider(replies=[an_reply(search_block(f"s{i}"), "pause_turn") for i in range(3)])
    out = run_tool(provider)  # a 4th request would raise "unexpected extra provider call"
    assert len(provider.chat_requests) == 1 + web.MAX_PAUSE_RESUMES
    assert out.status == "ok"  # the results it did return are real search results (no snippets, no prose)
    assert all(r["snippet"] == "" for r in out.summary["results"]) and out.summary["summary"] == ""


# --------------------------------------------------------------------------- failures: never fake results


def _raise_timeout(_request):
    raise httpx2.ReadTimeout("timed out")


def test_timeout_is_a_tool_error_never_results(env):
    env.setenv("FAULTLINE_WEB_SEARCH_PROVIDER", "anthropic")
    clients = chat.ClientFactory({"anthropic": httpx2.MockTransport(_raise_timeout)})
    box = chat_routes.EngineToolBox(get_settings(), None, web_clients=clients)
    out = asyncio.run(box.run("web_search", {"query": "Nvidia"}))
    assert out.status == "error" and set(out.summary) == {"error"} and "timeout" in out.summary["error"]


def test_overall_deadline_is_a_tool_error(env, monkeypatch):
    monkeypatch.setattr(web, "SEARCH_TIMEOUT_S", 0.05)

    async def slow(_request):
        await asyncio.sleep(1)
        return httpx2.Response(200, json={})

    clients = chat.ClientFactory({"anthropic": httpx2.MockTransport(slow)})
    with pytest.raises(web.WebSearchError) as err:
        asyncio.run(web.search("anthropic", "Nvidia", clients))
    assert err.value.kind == "timeout"


@pytest.mark.parametrize(("status", "kind"), [(401, "auth"), (429, "rate_limited"), (500, "upstream")])
def test_http_errors_map_to_a_kind_and_never_echo_the_body(env, status, kind):
    body = {"type": "error", "error": {"type": "x", "message": "key sk-ant-SECRET is bad"}}
    out = run_tool(FakeProvider(replies=[lambda _b: httpx2.Response(status, json=body)]))
    assert out.status == "error" and kind in out.summary["error"] and "SECRET" not in json.dumps(out.summary)


# --------------------------------------------------------------------------- OpenAI fallback


def test_openai_result_shape_and_model_written_snippets(env):
    env.delenv("ANTHROPIC_API_KEY")
    env.setenv("OPENAI_API_KEY", OPENAI_KEY)
    provider = FakeProvider(replies=[oai_reply])
    out = run_tool(provider, kind="openai")
    assert out.status == "ok"
    s = out.summary
    assert s["attribution"] == "Search by OpenAI web search" and "model-written" in s["note"]
    (hit,) = s["results"]
    assert hit["url"] == "https://news.example.com/a" and hit["title"] == "Nvidia news"
    assert hit["snippet"] == "Nvidia's revenue was $57.0 billion" and hit["snippet_label"].startswith("MODEL-WRITTEN")
    body = provider.chat_requests[0]["json"]
    assert body["tools"] == [{"type": "web_search"}] and body["model"] == web.OPENAI_SEARCH_MODEL
    # The figure check sees titles and urls only, never OpenAI's text.
    assert chat.unverified_numbers("Revenue was $57.0 billion.", [chat.figure_sources(s)]) == ["$57.0 billion"]


# --------------------------------------------------------------------------- Anthropic -> OpenAI fallback (#221)


def _anthropic_fails_then(openai: FakeProvider | None) -> tuple[chat.ToolOutcome, FakeProvider | None]:
    transports = {"anthropic": httpx2.MockTransport(_raise_timeout)}
    if openai is not None:
        transports["openai"] = openai.transport()
    box = chat_routes.EngineToolBox(get_settings(), None, web_clients=chat.ClientFactory(transports))
    return asyncio.run(box.run("web_search", {"query": "Nvidia CEO"})), openai


def test_a_failed_anthropic_search_is_retried_once_on_openai_with_openai_attribution(env):
    env.setenv("FAULTLINE_WEB_SEARCH_PROVIDER", "anthropic")
    env.setenv("OPENAI_API_KEY", OPENAI_KEY)
    out, openai = _anthropic_fails_then(FakeProvider(replies=[oai_reply]))
    assert out.status == "ok" and len(openai.chat_requests) == 1
    assert out.summary["attribution"] == "Search by OpenAI web search"
    assert "Tavily" not in json.dumps(out.summary) and "Anthropic" not in out.summary["attribution"]


def test_both_searches_failing_is_one_tool_error_with_no_results(env):
    env.setenv("FAULTLINE_WEB_SEARCH_PROVIDER", "anthropic")
    env.setenv("OPENAI_API_KEY", OPENAI_KEY)
    body = {"error": {"message": "nope", "type": "server_error"}}
    out, openai = _anthropic_fails_then(FakeProvider(replies=[lambda _b: httpx2.Response(500, json=body)]))
    assert out.status == "error" and set(out.summary) == {"error"} and "upstream" in out.summary["error"]
    assert len(openai.chat_requests) == 1  # one fallback try, never more


def test_no_openai_key_means_no_fallback(env):
    env.setenv("FAULTLINE_WEB_SEARCH_PROVIDER", "anthropic")
    out, _ = _anthropic_fails_then(None)
    assert out.status == "error" and "timeout" in out.summary["error"]


def test_tavily_attribution_appears_only_on_tavily_results(env):
    env.setenv("OPENAI_API_KEY", OPENAI_KEY)
    for provider, reply in (("anthropic", an_reply(search_block() + text_blocks())), ("openai", oai_reply)):
        env.setenv("FAULTLINE_WEB_SEARCH_PROVIDER", provider)
        fake = FakeProvider(replies=[reply])
        clients = factory(**{provider: fake})
        box = chat_routes.EngineToolBox(get_settings(), None, web_clients=clients)
        out = asyncio.run(box.run("web_search", {"query": "Nvidia CEO"}))
        assert out.status == "ok" and "Tavily" not in json.dumps(out.summary), provider


# --------------------------------------------------------------------------- the figure check, through the route


def _brief(figure: str) -> str:
    return f"**Evidence:** Nvidia revenue was {figure} (Nvidia CEO news, November 3, 2026, {URL_A})."


@pytest.mark.parametrize(("figure", "ok"), [("$57.0 billion", True), ("$65 billion", False)])
def test_summary_is_not_a_source_for_the_figure_check(env, figure, ok):
    h = Harness(openrouter=FakeProvider(models=OPENROUTER_MODELS, replies=[
                    oa_tool_calls(("web_search", {"query": "Nvidia revenue"})), oa_text(_brief(figure)),
                    *([] if ok else [oa_text(_brief(figure))])]),  # a failing reply gets one repair round (#221)
                anthropic=FakeProvider(models=ANTHROPIC_LIST, replies=[an_reply(search_block() + text_blocks())]))
    out = h.turn("Should Nvidia keep Jensen Huang as CEO?").json()
    call = out["tool_calls"][0]
    assert call["result_status"] == "ok" and SUMMARY in call["result_summary"]["summary"]  # the model saw it
    if ok:  # in the cited_text: passes
        assert out["status"] == "ok", out["notes"]
        assert not any("Links in this reply" in n for n in out["notes"])
    else:  # only in the MODEL-WRITTEN summary: withheld
        assert out["status"] == "error" and out["reply"] == ""
        assert any("withheld" in n and "$65 billion" in n for n in out["notes"])


def test_daily_caps_still_apply_to_llm_search(env):
    env.setenv("FAULTLINE_CHAT_WEB_PER_IP_DAY", "1")
    env.setenv("FAULTLINE_ADMIN_TOKEN", ADMIN)
    search = ("web_search", {"query": "Meta CEO governance"})
    h = Harness(openrouter=FakeProvider(models=OPENROUTER_MODELS, replies=[
                    oa_tool_calls(search), oa_text("Done."), oa_tool_calls(search), oa_text("Done."),
                    oa_tool_calls(search), oa_text("Done.")]),
                anthropic=FakeProvider(models=ANTHROPIC_LIST, replies=[
                    an_reply(search_block() + text_blocks()), an_reply(search_block() + text_blocks())]))
    assert h.turn("Should Meta keep Mark Zuckerberg as CEO?").json()["tool_calls"][0]["result_status"] == "ok"
    second = h.turn("And Nvidia?").json()["tool_calls"][0]
    assert second["result_status"] == "error" and "daily limit for this visitor" in second["result_summary"]["error"]
    assert len(h.anthropic.chat_requests) == 1  # the refused call never reached the provider
    admin = h.turn("And Nvidia?", headers={"Authorization": f"Bearer {ADMIN}"}).json()
    assert admin["tool_calls"][0]["result_status"] == "ok"


def _tavily_fails(status: int) -> httpx2.MockTransport:
    return httpx2.MockTransport(lambda _req: httpx2.Response(status, json={"detail": "TEST FIXTURE failure"}))


def test_a_failed_tavily_search_falls_back_to_anthropic_with_anthropic_attribution(env):
    """Tavily is the preferred provider when its key is set; a Tavily outage or quota error must not stall the turn."""
    env.setenv("TAVILY_API_KEY", "tvly-TESTFIXTURE0000000000000000")
    env.delenv("FAULTLINE_WEB_SEARCH_PROVIDER", raising=False)
    fake = FakeProvider(replies=[an_reply(search_block() + text_blocks())])
    box = chat_routes.EngineToolBox(get_settings(), _tavily_fails(500), web_clients=factory(anthropic=fake))
    assert box.web_provider == "tavily"
    out = asyncio.run(box.run("web_search", {"query": "Nvidia CEO"}))
    assert out.status == "ok" and out.summary["results"]
    assert "Anthropic" in out.summary["attribution"] and "Tavily" not in json.dumps(out.summary)


def test_tavily_failing_with_no_backup_key_is_one_tool_error(env):
    env.setenv("TAVILY_API_KEY", "tvly-TESTFIXTURE0000000000000000")
    env.delenv("FAULTLINE_WEB_SEARCH_PROVIDER", raising=False)
    env.delenv("ANTHROPIC_API_KEY", raising=False)
    env.delenv("OPENAI_API_KEY", raising=False)
    box = chat_routes.EngineToolBox(get_settings(), _tavily_fails(500), web_clients=chat.ClientFactory({}))
    out = asyncio.run(box.run("web_search", {"query": "Nvidia CEO"}))
    assert out.status == "error" and set(out.summary) == {"error"} and "No results were made up" in out.summary["error"]
