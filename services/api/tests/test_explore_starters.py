"""GET /api/explore/chat/starters (#223): news starter questions, verified sources, cache and single-flight.

The Anthropic SDK is mocked at the HTTP layer (httpx2.MockTransport) with responses in the documented shape, so the
real SDK parses them; no test touches the network.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, date, datetime
from typing import Any

import httpx2
import pytest
from fastapi.testclient import TestClient

from agents import explore_chat as chat
from main import create_app
from routes import explore_chat as chat_routes
from routes import explore_starters as st

ANTHROPIC_KEY = "test-anthropic-" + "a" * 24
ADMIN = "c3" * 32
TODAY = date(2026, 11, 14)
PATH = "/api/explore/chat/starters"

RESULTS = [
    ("https://news.example.com/acme-ceo", "Acme names new CEO after board review", "November 10, 2026"),
    ("https://biz.example.org/globex-deal/", "Globex agrees to buy Initech for $4bn", "November 8, 2026"),
    ("https://wire.example.net/umbrella-layoffs", "Umbrella to cut 2,000 jobs in restructuring", None),
    ("https://daily.example.com/hooli-activist", "Activist fund takes stake in Hooli, seeks board seats",
     "November 2, 2026"),
    ("https://old.example.com/stale", "Soylent exits European market", "March 1, 2025"),
]


def item(question: str, url: str, tag: str = "Leadership", headline: str = "") -> dict[str, Any]:
    return {"question": question, "headline": headline, "source_url": url, "published_date": None, "tag": tag}


GOOD = [
    item("Should Acme's board give the new CEO a mandate to restructure?", RESULTS[0][0],
         headline="Acme names new CEO after board review"),
    item("Should Globex finance the Initech deal with debt or stock?", RESULTS[1][0].rstrip("/"), "M&A"),
    item("Should Umbrella phase its 2,000 job cuts over a year?", RESULTS[2][0], "Workforce"),
    item("Should Hooli offer the activist fund one board seat?", RESULTS[3][0], "Governance"),
]


def blocks(items: list[dict[str, Any]], prose: str = "") -> list[dict[str, Any]]:
    return [
        {"type": "text", "text": "I'll search for recent news.", "citations": None},
        {"type": "server_tool_use", "id": "srvtoolu_1", "name": "web_search", "input": {"query": "CEO news"}},
        {"type": "web_search_tool_result", "tool_use_id": "srvtoolu_1", "content": [
            {"type": "web_search_result", "url": u, "title": t, "encrypted_content": "Eq", "page_age": a}
            for u, t, a in RESULTS]},
        {"type": "text", "text": prose + json.dumps({"starters": items}), "citations": None},
    ]


class FakeAnthropic:
    def __init__(self, content: list[dict[str, Any]] | None = None, status: int = 200) -> None:
        self.content = content if content is not None else blocks(GOOD)
        self.status = status
        self.calls: list[dict[str, Any]] = []

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.content)
        self.calls.append(body)
        if self.status != 200:
            return httpx2.Response(self.status, json={"type": "error", "error": {"type": "api_error",
                                                                                 "message": "boom"}})
        return httpx2.Response(200, json={
            "id": "msg_st", "type": "message", "role": "assistant", "model": st.STARTERS_MODEL,
            "content": self.content, "stop_reason": "end_turn", "stop_sequence": None,
            "usage": {"input_tokens": 20_000, "output_tokens": 800, "server_tool_use": {"web_search_requests": 4}}})

    def factory(self) -> chat.ClientFactory:
        return chat.ClientFactory({"anthropic": httpx2.MockTransport(self.handler)})


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", ANTHROPIC_KEY)
    monkeypatch.delenv("FAULTLINE_MODE", raising=False)
    monkeypatch.delenv("FAULTLINE_STARTERS_TTL_S", raising=False)
    yield monkeypatch


def make_client(fake: FakeAnthropic) -> TestClient:
    app = create_app()
    app.dependency_overrides[st.get_starters_clients] = fake.factory
    return TestClient(app)


# --------------------------------------------------------------------------- shape + validation


def test_shape_and_provenance(env):
    fake = FakeAnthropic()
    with make_client(fake) as client:
        resp = client.get(PATH)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body) == {"provenance", "generated_at", "label", "starters"}
    assert body["provenance"].startswith("REAL (web, retrieved ") and body["provenance"].endswith("Z)")
    assert body["label"] == "Questions written by a model from current news; check the source"
    assert len(body["starters"]) == 4
    for s in body["starters"]:
        assert set(s) == {"question", "headline", "source_title", "source_url", "domain", "published_date", "tag"}
        assert len(s["question"]) <= 90 and s["question"].startswith("Should ") and s["question"].endswith("?")
        assert s["tag"] in ("Leadership", "M&A", "Strategy", "Governance", "Workforce")
    first = body["starters"][0]
    assert first["source_url"] == RESULTS[0][0]
    assert first["domain"] == "news.example.com"
    assert first["source_title"] == RESULTS[0][1]
    assert first["published_date"] == "2026-11-10"  # page age from the search result, not the model
    assert body["starters"][1]["source_url"] == RESULTS[1][0]  # the search result's url (trailing slash kept)
    assert body["starters"][2]["published_date"] is None
    # one provider call, with the web_search tool capped at 4 uses
    assert len(fake.calls) == 1
    assert fake.calls[0]["tools"] == [st.STARTERS_TOOL] and st.STARTERS_TOOL["max_uses"] == 4


def test_invented_url_is_dropped():
    invented = item("Should Initrode's board sell the cloud unit?", "https://news.example.com/made-up-story", "M&A")
    out = st.build_starters(blocks([invented, *GOOD[:2]]), TODAY)
    assert [s.source_url for s in out] == [RESULTS[0][0], RESULTS[1][0]]
    assert all("made-up" not in s.source_url for s in out)


def test_bad_items_dropped():
    bad = [
        item("Acme should restructure now.", RESULTS[0][0]),  # not a "Should ...?" question
        item("Should Acme's board " + "really " * 15 + "act?", RESULTS[0][0]),  # over 90 characters
        item("Should Acme restructure now?", RESULTS[0][0], tag="Gossip"),  # unknown tag
        item("Should Globex fire the CEO who committed fraud?", RESULTS[1][0], "Governance"),  # allegation as fact
        item("Should Soylent re-enter Europe after its exit?", RESULTS[4][0], "Strategy"),  # 2025: not current news
        {"question": "Should Hooli settle?", "tag": "Governance"},  # no url
        "not an object",
        GOOD[2],
    ]
    out = st.build_starters(blocks(bad), TODAY)
    assert [s.source_url for s in out] == [RESULTS[2][0]]


def test_headline_falls_back_to_search_title():
    rewritten = item("Should Umbrella phase its 2,000 job cuts over a year?", RESULTS[2][0], "Workforce",
                     headline="Umbrella executives accused of hiding losses")
    (out,) = st.build_starters(blocks([rewritten]), TODAY)
    assert out.headline == RESULTS[2][1]


def test_json_after_prose_and_no_json():
    assert len(st.build_starters(blocks(GOOD, prose="Here are the questions:\n```json\n"), TODAY)) == 4
    no_json = blocks(GOOD)
    no_json[-1]["text"] = "I could not find enough stories."
    assert st.build_starters(no_json, TODAY) == []


def test_relative_page_age_counted_from_search_day():
    assert st._parse_page_age("5 days ago", TODAY) == date(2026, 11, 9)
    assert st._parse_page_age("1 days ago", TODAY) == date(2026, 11, 13)
    assert st._parse_page_age("2 weeks ago", TODAY) == date(2026, 10, 31)
    assert st._parse_page_age("3 hours ago", TODAY) == TODAY
    assert st._parse_page_age("sometime", TODAY) is None


def test_duplicate_sources_collapse():
    out = st.build_starters(blocks([GOOD[0], {**GOOD[0], "question": "Should Acme split the CEO and chair roles?"}]),
                            TODAY)
    assert len(out) == 1


# --------------------------------------------------------------------------- 503 paths


def test_fewer_than_two_is_503(env):
    fake = FakeAnthropic(blocks([GOOD[0], item("Should X?", "https://invented.example/x")]))
    with make_client(fake) as client:
        resp = client.get(PATH)
    assert resp.status_code == 503
    assert resp.json()["code"] == "STARTERS_UNAVAILABLE"


def test_provider_error_is_503_without_key_or_body(env):
    fake = FakeAnthropic(status=500)
    with make_client(fake) as client:
        resp = client.get(PATH)
    assert resp.status_code == 503 and resp.json()["code"] == "STARTERS_UNAVAILABLE"
    assert ANTHROPIC_KEY not in resp.text and "boom" not in resp.text


def test_no_key_is_503_and_no_call(env):
    env.delenv("ANTHROPIC_API_KEY")
    fake = FakeAnthropic()
    with make_client(fake) as client:
        resp = client.get(PATH)
    assert resp.status_code == 503 and resp.json()["code"] == "STARTERS_UNAVAILABLE"
    assert fake.calls == []


# --------------------------------------------------------------------------- caching + single flight


def test_cached_across_visitors(env):
    fake = FakeAnthropic()
    with make_client(fake) as client:
        bodies = [client.get(PATH).json() for _ in range(5)]
    assert len(fake.calls) == 1
    assert all(b == bodies[0] for b in bodies)


def test_spend_counts_against_chat_budget(env):
    fake = FakeAnthropic()
    with make_client(fake) as client:
        client.get(PATH)
        spent = client.app.state.faultline_chat.spent_today()
    # 20,000 in x $2 + 800 out x $10 per Mtok + 4 searches x $0.01
    assert spent == pytest.approx(0.04 + 0.008 + 0.04)


def test_exhausted_chat_budget_blocks_refresh(env):
    fake = FakeAnthropic()
    with make_client(fake) as client:
        state = chat_routes.ChatState()
        state.spent_today()
        state.spent_usd = 10_000.0
        client.app.state.faultline_chat = state
        resp = client.get(PATH)
    assert resp.status_code == 503 and fake.calls == []


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def _fetched(items: list[dict[str, Any]]) -> st.Fetched:
    return st.Fetched(blocks(items), 0, 0, 0)


def test_single_flight_and_stale_while_refreshing():
    clock = Clock()
    wall = lambda: datetime(2026, 11, 14, 5, 0, tzinfo=UTC)  # noqa: E731
    state = st.StartersState(clock=clock, wall=wall, ttl_s=100)
    calls = 0

    async def scenario() -> None:
        nonlocal calls
        gate = asyncio.Event()

        async def slow_fetch(_today: date) -> st.Fetched:
            nonlocal calls
            calls += 1
            await gate.wait()
            return _fetched(GOOD)

        # 10 concurrent first visitors share one refresh: the one that started it waits, the rest get None at once
        # (the route answers them 503 + Retry-After while warming, #234)
        starter = asyncio.create_task(state.get(slow_fetch))
        for _ in range(5):
            await asyncio.sleep(0)
        others = [await state.get(slow_fetch) for _ in range(9)]
        assert calls == 1 and others == [None] * 9 and state.warming
        gate.set()
        first = await starter
        assert calls == 1 and first is not None and len(first.starters) == 4 and not state.warming
        assert await state.get(slow_fetch) is first

        # stale: visitors get the old result at once while one refresh runs
        clock.t += 101
        gate2 = asyncio.Event()

        async def slow_fetch2(_today: date) -> st.Fetched:
            nonlocal calls
            calls += 1
            await gate2.wait()
            return _fetched(GOOD[:2])

        stale = [await state.get(slow_fetch2) for _ in range(5)]
        for _ in range(5):
            await asyncio.sleep(0)
        assert calls == 2 and all(r is first for r in stale)
        gate2.set()
        await state.task
        fresh = await state.get(slow_fetch2)
        assert len(fresh.starters) == 2 and calls == 2

    asyncio.run(scenario())


def test_failed_refresh_keeps_last_good_and_daily_cap():
    clock = Clock()
    wall = lambda: datetime(2026, 11, 14, 5, 0, tzinfo=UTC)  # noqa: E731
    state = st.StartersState(clock=clock, wall=wall, ttl_s=100)

    async def scenario() -> None:
        calls = 0

        async def ok(_today: date) -> st.Fetched:
            nonlocal calls
            calls += 1
            return _fetched(GOOD)

        async def broken(_today: date) -> st.Fetched:
            nonlocal calls
            calls += 1
            raise RuntimeError("provider down")

        good = await state.get(ok)
        assert good is not None
        clock.t += 101
        assert await state.get(broken) is good  # stale served while the refresh fails
        await state.task
        assert await state.get(broken) is good and calls == 2  # failure kept the last good; no retry for 15 min
        # daily cap: 4 attempts per UTC day, whatever the TTL
        for _ in range(10):
            clock.t += st.FAILURE_RETRY_S + 1
            await state.get(broken)
            if state.task is not None:
                await state.task
        assert calls == st.MAX_REFRESHES_PER_DAY
        assert await state.get(ok) is good

    asyncio.run(scenario())


# --------------------------------------------------------------------------- startup warm-up (#234)


def test_warm_enabled_switch():
    assert st.warm_enabled("public", {}) is True
    assert st.warm_enabled("local", {}) is False
    assert st.warm_enabled("local", {st.WARM_ENV: "1"}) is True
    assert st.warm_enabled("public", {st.WARM_ENV: "0"}) is False
    assert st.warm_enabled("public", {st.WARM_ENV: "yes"}) is True  # not 0/1: the mode default
    # never under pytest, whatever the flag says
    assert st.warm_enabled("public", {"PYTEST_CURRENT_TEST": "t", st.WARM_ENV: "1"}) is False


def test_startup_does_not_warm_under_pytest(env):
    env.setenv(st.WARM_ENV, "1")
    fake = FakeAnthropic()
    with make_client(fake) as client:
        assert client.get("/api/health").status_code == 200
        assert getattr(client.app.state, "faultline_starters", None) is None
    assert fake.calls == []


def test_startup_warm_scheduled_when_enabled(env):
    env.setattr(st, "warm_enabled", lambda _mode, _environ: True)
    fake = FakeAnthropic()
    with make_client(fake) as client:
        state = client.app.state.faultline_starters
        assert state.task is not None  # scheduled by the lifespan, before any visitor
        client.portal.call(asyncio.wait_for, asyncio.shield(state.task), 5)
        assert len(fake.calls) == 1
        resp = client.get(PATH)  # served from the warm cache: no second provider call
        assert resp.status_code == 200 and len(resp.json()["starters"]) == 4
    assert len(fake.calls) == 1


def test_startup_warm_needs_key(env):
    env.delenv("ANTHROPIC_API_KEY")
    env.setattr(st, "warm_enabled", lambda _mode, _environ: True)
    fake = FakeAnthropic()
    with make_client(fake) as client:
        assert getattr(client.app.state, "faultline_starters", None) is None
    assert fake.calls == []


def test_warming_with_empty_cache_is_503_retry_after(env):
    """A refresh in flight and nothing cached: 503 at once with Retry-After, not a wait; then the result."""
    gate = asyncio.Event()

    async def slow_fetch(_today: date) -> st.Fetched:
        await gate.wait()
        return _fetched(GOOD)

    fake = FakeAnthropic()
    with make_client(fake) as client:
        state = st.StartersState()
        client.app.state.faultline_starters = state
        client.portal.call(lambda: _start(state, slow_fetch))
        assert state.warming
        resp = client.get(PATH)
        assert resp.status_code == 503 and resp.json()["code"] == "STARTERS_UNAVAILABLE"
        assert resp.headers["retry-after"] == "15"
        assert "being prepared" in resp.json()["message"]
        client.portal.call(gate.set)
        client.portal.call(asyncio.wait_for, asyncio.shield(state.task), 5)
        resp = client.get(PATH)
        assert resp.status_code == 200 and len(resp.json()["starters"]) == 4
    assert fake.calls == []  # the in-flight refresh was the only fetch


async def _start(state: st.StartersState, fetch: st.Fetcher) -> None:
    assert state.warm(fetch) is not None
    assert state.warm(fetch) is None  # single flight: a second warm-up does not start another refresh


def test_failed_refresh_503_has_no_retry_after(env):
    fake = FakeAnthropic(status=500)
    with make_client(fake) as client:
        resp = client.get(PATH)
    assert resp.status_code == 503 and "retry-after" not in resp.headers


def test_ttl_env(monkeypatch):
    monkeypatch.setenv("FAULTLINE_STARTERS_TTL_S", "3600")
    assert st.StartersState().ttl_s == 3600
    monkeypatch.setenv("FAULTLINE_STARTERS_TTL_S", "nonsense")
    assert st.StartersState().ttl_s == st.DEFAULT_TTL_S
    monkeypatch.delenv("FAULTLINE_STARTERS_TTL_S")
    assert st.StartersState().ttl_s == 6 * 3600


# --------------------------------------------------------------------------- public mode


def test_public_mode_is_public(env):
    env.setenv("FAULTLINE_MODE", "public")
    env.setenv("FAULTLINE_ADMIN_TOKEN", ADMIN)
    env.delenv("FAULTLINE_PUBLIC_CHAT", raising=False)
    fake = FakeAnthropic()
    with make_client(fake) as client:
        resp = client.get(PATH)  # no admin token
        assert resp.status_code == 200, resp.text
        assert len(resp.json()["starters"]) == 4
        # neighbours stay gated: exact-path match only
        assert client.get(PATH + "/x").status_code in (401, 403, 404)
        assert client.post("/api/explore/chat", json={}).status_code in (401, 403)


def test_prompt_has_rules():
    prompt = st.build_prompt(TODAY)
    assert "2026-11-14" in prompt and "2026-10-15" in prompt
    assert "Never invent" in prompt and "private" in prompt and '"starters"' in prompt
