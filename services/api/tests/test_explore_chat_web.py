"""LIVE EXPLORE chat (#200): real-world decision briefs. The prompt-independent parts: web_search gating and daily
caps, the REAL web label and result shape, and the figure check on numbers cited from web snippets.

Providers and Tavily are mocked at the HTTP layer; no test touches the network.
"""

from __future__ import annotations

import asyncio
import json
import re
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from test_explore_chat import (
    ADMIN,
    ANTHROPIC_KEY,
    OPENROUTER_KEY,
    OPENROUTER_MODELS,
    FakeProvider,
    Harness,
    oa_text,
    oa_tool_calls,
)

from agents import explore_chat as chat
from config import get_settings
from routes import explore_chat as chat_routes

SNIPPET = "Nvidia reported full-year revenue of $130.5 billion, up from the year before, the company said."
TAVILY_BODY = {"query": "q", "response_time": 0.1, "results": [
    {"title": "Nvidia results", "url": "https://News.Example.com/nvidia-results", "content": SNIPPET, "score": 0.9,
     "published_date": "Wed, 26 Feb 2026 21:00:00 GMT"},
    {"title": "Undated page", "url": "https://other.example.org/p", "content": "No figures here.", "score": 0.5},
]}


def tavily_transport() -> httpx.MockTransport:
    return httpx.MockTransport(lambda req: httpx.Response(200, json=TAVILY_BODY))


@pytest.fixture
def env(monkeypatch):
    """As test_explore_chat.env, plus the web_search caps cleared."""
    for name in ("FAULTLINE_MODE", "FAULTLINE_ADMIN_TOKEN", "FAULTLINE_PUBLIC_CHAT", "FAULTLINE_CHAT_MODELS",
                 "FAULTLINE_CHAT_PER_IP", "FAULTLINE_CHAT_CONCURRENCY", "FAULTLINE_CHAT_MAX_PRICE_PER_MTOK",
                 "TAVILY_API_KEY", "OPENAI_API_KEY", "FAULTLINE_RATE_LIMIT_PER_MIN", "FAULTLINE_CHAT_WEB_PER_IP_DAY",
                 "FAULTLINE_CHAT_WEB_DAILY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", OPENROUTER_KEY)
    monkeypatch.setenv("ANTHROPIC_API_KEY", ANTHROPIC_KEY)
    monkeypatch.setenv("FAULTLINE_WEB_SEARCH_PROVIDER", "tavily")  # #214: these tests pin the Tavily web_search path
    return monkeypatch


@pytest.fixture
def web_env(env):
    env.setenv("TAVILY_API_KEY", "test-tavily-" + "t" * 24)
    return env


def web_harness(*replies) -> Harness:
    h = Harness(openrouter=FakeProvider(models=OPENROUTER_MODELS, replies=list(replies)))
    h.app.dependency_overrides[chat_routes.get_chat_tavily_transport] = tavily_transport
    return h


# --------------------------------------------------------------------------- label and result shape


def test_web_search_result_shape_and_real_label(web_env):
    box = chat_routes.EngineToolBox(get_settings(), tavily_transport())
    out = asyncio.run(box.run("web_search", {"query": "Nvidia annual revenue"}))
    assert out.status == "ok" and out.provenance == "LIVE EXPLORE"
    s = out.summary
    assert set(s) == {"provenance", "retrieved_at", "query", "results", "attribution", "note"}
    assert re.fullmatch(r"REAL \(web, retrieved \d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ\)", s["provenance"])
    assert datetime.fromisoformat(s["retrieved_at"]).tzinfo is not None and s["query"] == "Nvidia annual revenue"
    first, second = s["results"]
    assert set(first) == {"title", "url", "domain", "published_date", "snippet"}
    assert first["domain"] == "news.example.com" and first["snippet"] == SNIPPET
    assert first["published_date"] == "2026-02-26T21:00:00+00:00" and second["published_date"] is None
    sent = json.loads(out.for_model())  # the model sees the REAL label, not the generic one
    assert sent["provenance"] == s["provenance"] and sent["status"] == "ok"


def test_web_search_is_not_offered_without_a_key_and_the_prompt_says_framework_only(env):
    h = Harness(openrouter=FakeProvider(models=OPENROUTER_MODELS, replies=[oa_text("Hello.")]))
    h.turn("Should Meta keep Mark Zuckerberg as CEO?")
    body = h.openrouter.chat_requests[0]["json"]
    assert "web_search" not in [t["function"]["name"] for t in body["tools"]]
    system = body["messages"][0]["content"]
    assert "can't look up live sources" in system and "no digits at all" in system
    for heading in chat.DECISION_BRIEF_HEADINGS:
        assert f"**{heading}:**" in system
    assert "Never refuse these" in system


def test_prompt_with_web_search_asks_for_sourced_evidence(web_env):
    system = chat.system_prompt(web_search=True)
    assert "Call web_search first" in system and "published_date" in system
    assert "MODEL-WRITTEN judgment, not advice" in system
    assert "no differences, sums, ratios" in system  # no arithmetic of its own


# --------------------------------------------------------------------------- daily caps


def test_web_take_caps_per_ip_and_globally_per_utc_day_admin_unlimited():
    now = [datetime(2026, 11, 14, 12, tzinfo=UTC)]
    state = chat_routes.ChatState(wall=lambda: now[0])
    assert state.web_take("a", per_ip=2, daily=3) is None
    assert state.web_take("a", per_ip=2, daily=3) is None
    assert "this visitor" in state.web_take("a", per_ip=2, daily=3)
    assert state.web_take("b", per_ip=2, daily=3) is None
    assert "this server" in state.web_take("b", per_ip=2, daily=3)  # global cap: 3 used
    for _ in range(10):
        assert state.web_take(None, per_ip=2, daily=3) is None  # admin: unlimited and not counted
    assert state.web_total == 3
    now[0] += timedelta(days=1)  # a new UTC day resets both counters
    assert state.web_take("a", per_ip=2, daily=3) is None and state.web_total == 1


def test_zero_caps_mean_no_web_search_for_visitors():
    state = chat_routes.ChatState()
    assert state.web_take("a", per_ip=0, daily=100) is not None
    assert state.web_take("a", per_ip=5, daily=0) is not None


def test_daily_cap_is_enforced_through_the_chat_route_and_admin_bypasses_it(web_env):
    web_env.setenv("FAULTLINE_CHAT_WEB_PER_IP_DAY", "1")
    web_env.setenv("FAULTLINE_ADMIN_TOKEN", ADMIN)
    search = ("web_search", {"query": "Meta CEO governance"})
    h = web_harness(oa_tool_calls(search), oa_text("Done."), oa_tool_calls(search), oa_text("Done."),
                    oa_tool_calls(search), oa_text("Done."))
    first = h.turn("Should Meta keep Mark Zuckerberg as CEO?").json()
    assert first["tool_calls"][0]["result_status"] == "ok"
    second = h.turn("And Nvidia?").json()
    call = second["tool_calls"][0]
    assert call["result_status"] == "error" and "daily limit for this visitor" in call["result_summary"]["error"]
    admin = h.turn("And Nvidia?", headers={"Authorization": f"Bearer {ADMIN}"}).json()
    assert admin["tool_calls"][0]["result_status"] == "ok"


# --------------------------------------------------------------------------- the figure check on web figures


def _brief(figure: str) -> str:
    return (f"**Evidence:** Nvidia reported revenue of {figure} (Nvidia results, News.Example.com, 2026-02-26, "
            "https://News.Example.com/nvidia-results).")


@pytest.mark.parametrize("figure", ["$130.5 billion", "$130.5B", "130.5 billion dollars"])
def test_figures_cited_from_a_web_snippet_pass(web_env, figure):
    h = web_harness(oa_tool_calls(("web_search", {"query": "Nvidia revenue"})), oa_text(_brief(figure)))
    out = h.turn("Should Nvidia keep Jensen Huang as CEO?").json()
    assert out["status"] == "ok", out["notes"]
    assert figure in out["reply"]
    assert not any("Links in this reply" in n for n in out["notes"])  # the cited url came from the tool


@pytest.mark.parametrize("figure", ["$145 billion", "$131.9B", "$1.3 trillion"])
def test_figures_not_in_any_web_result_are_withheld(web_env, figure):
    h = web_harness(oa_tool_calls(("web_search", {"query": "Nvidia revenue"})), oa_text(_brief(figure)))
    out = h.turn("Should Nvidia keep Jensen Huang as CEO?").json()
    assert out["status"] == "error" and out["reply"] == ""
    assert any("withheld" in n for n in out["notes"])


def test_scaled_figures_in_tool_text_are_matched_both_ways():
    results: list[dict[str, Any]] = [{"result": {"snippet": "Revenue was $60.9 billion; capex 2.1 trillion yen."}}]
    assert chat.unverified_numbers("Revenue was $60.9 billion.", results) == []
    assert chat.unverified_numbers("Revenue was $60.9B.", results) == []
    assert chat.unverified_numbers("Revenue was $61B.", results) == []  # 3-significant-figure rounding of 60.9
    assert chat.unverified_numbers("Revenue was $63B.", results) == ["$63B"]  # "B" is now parsed, and checked
    assert chat.unverified_numbers("Capex was 2.1 trillion yen.", results) == []
