"""GET /api/explore/search: labels, honest unavailable states, validation, cache, rate limit, public-mode gate.

Mocked Tavily transport only (no network, no real key).
"""

from __future__ import annotations

import json
import re

import httpx
import pytest
from fastapi.testclient import TestClient

from main import create_app
from routes import explore

KEY = "tvly-route-" + "r" * 40
ADMIN = "a" * 40
PATH = "/api/explore/search"
OUTCOME_LIKE = re.compile(r"outcome|resolution|resolved|settle|winner|final_price|available_at", re.IGNORECASE)


def _payload(n=2):
    return {
        "query": "q",
        "results": [
            {"title": f"Title {i}", "url": f"https://news{i}.example/a", "content": f"snippet {i}", "score": 0.5,
             "published_date": "Tue, 11 Mar 2025 17:00:00 GMT"}
            for i in range(n)
        ],
        "response_time": 0.3,
    }


class FakeTavily:
    def __init__(self, response: httpx.Response | Exception | None = None) -> None:
        self.response = response if response is not None else httpx.Response(200, json=_payload())
        self.calls: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", KEY)
    for name in ("FAULTLINE_MODE", "FAULTLINE_ADMIN_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def _app(fake: FakeTavily, clock: Clock | None = None, **state_kw):
    app = create_app()
    app.dependency_overrides[explore.get_tavily_transport] = lambda: httpx.MockTransport(fake)
    app.state.faultline_explore = explore.ExploreState(clock=clock or Clock(), **state_kw)
    return app


def _client(fake=None, **kw):
    fake = fake or FakeTavily()
    return TestClient(_app(fake, **kw)), fake


def _keys(node, out=None):
    out = set() if out is None else out
    if isinstance(node, dict):
        for k, v in node.items():
            out.add(k)
            _keys(v, out)
    elif isinstance(node, list):
        for v in node:
            _keys(v, out)
    return out


# --------------------------------------------------------------------------- happy path


def test_search_returns_labeled_live_explore_results(env):
    client, fake = _client()
    resp = client.get(PATH, params={"q": "  supplier   outage  ", "max_results": 2})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["mode"] == "live_explore"
    assert body["label"] == "LIVE EXPLORE: current, not point-in-time"
    assert body["provider"] == "tavily"
    assert body["attribution"] == "Search powered by Tavily"
    assert body["query"] == "supplier outage"
    assert body["cached"] is False
    assert len(body["items"]) == 2
    item = body["items"][0]
    assert set(item) == {"title", "url", "snippet", "score", "published_at", "published_at_raw", "retrieved_at"}
    assert item["retrieved_at"] == body["retrieved_at"]
    assert item["published_at"].startswith("2025-03-11T17:00:00")
    assert any("Not point-in-time" in n for n in body["notes"])
    assert any("Tavily's estimate" in n for n in body["notes"])
    # The request Tavily saw: max_results passed through, no LLM answer requested.
    sent = json.loads(fake.calls[0].content)
    assert sent["max_results"] == 2 and sent["include_answer"] is False
    # Nothing outcome-like or replay-like in the payload, and the key never appears.
    assert not [k for k in _keys(body) if OUTCOME_LIKE.search(k)]
    assert KEY not in resp.text


def test_default_max_results_is_five(env):
    client, fake = _client()
    assert client.get(PATH, params={"q": "x"}).status_code == 200
    assert json.loads(fake.calls[0].content)["max_results"] == explore.DEFAULT_MAX_RESULTS == 5


def test_empty_result_list_is_reported_not_filled(env):
    client, _ = _client(FakeTavily(httpx.Response(200, json=_payload(0))))
    body = client.get(PATH, params={"q": "nothing"}).json()
    assert body["items"] == []
    assert any("no usable results" in n for n in body["notes"])


# --------------------------------------------------------------------------- unavailable / errors


def test_missing_key_is_live_explore_unavailable_and_makes_no_call(env):
    env.delenv("TAVILY_API_KEY")
    client, fake = _client()
    resp = client.get(PATH, params={"q": "x"})
    assert resp.status_code == 503
    assert resp.json()["code"] == "LIVE_EXPLORE_UNAVAILABLE"
    assert "TAVILY_API_KEY" in resp.json()["message"]
    assert fake.calls == []


@pytest.mark.parametrize(
    ("upstream", "status", "code"),
    [
        (httpx.Response(401, json={"detail": {"error": "Unauthorized"}}), 503, "LIVE_EXPLORE_UNAVAILABLE"),
        (httpx.Response(432, json={"detail": {"error": "limit"}}), 503, "LIVE_EXPLORE_UNAVAILABLE"),
        (httpx.Response(429, headers={"Retry-After": "9"}), 429, "RATE_LIMITED"),
        (httpx.Response(500), 502, "LIVE_EXPLORE_UPSTREAM_ERROR"),
        (httpx.Response(200, content=b"<html>"), 502, "LIVE_EXPLORE_UPSTREAM_ERROR"),
        (httpx.ReadTimeout("slow"), 504, "LIVE_EXPLORE_TIMEOUT"),
        (httpx.ConnectError("down"), 502, "LIVE_EXPLORE_UPSTREAM_ERROR"),
    ],
)
def test_upstream_failures_are_typed(env, upstream, status, code, caplog):
    client, _ = _client(FakeTavily(upstream))
    resp = client.get(PATH, params={"q": "x"})
    assert resp.status_code == status
    body = resp.json()
    assert body["code"] == code and body["message"]
    assert set(body) == {"code", "message", "errors"}
    if code == "RATE_LIMITED":
        assert resp.headers["retry-after"] == "9"
    assert KEY not in resp.text and KEY not in caplog.text


def test_failures_are_not_cached(env):
    fake = FakeTavily(httpx.Response(500))
    client, _ = _client(fake)
    client.get(PATH, params={"q": "x"})
    fake.response = httpx.Response(200, json=_payload())
    assert client.get(PATH, params={"q": "x"}).status_code == 200
    assert len(fake.calls) == 2


# --------------------------------------------------------------------------- validation


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"q": ""},
        {"q": "   "},
        {"q": "x" * (explore.MAX_QUERY_CHARS + 1)},
        {"q": "x", "max_results": 0},
        {"q": "x", "max_results": explore.MAX_RESULTS + 1},
        {"q": "x", "max_results": "five"},
    ],
)
def test_validation_errors(env, params):
    client, fake = _client()
    resp = client.get(PATH, params=params)
    assert resp.status_code == 422
    body = resp.json()
    assert body["code"] == "VALIDATION_ERROR" and body["errors"]
    assert fake.calls == []


def test_repeated_q_rejected(env):
    client, fake = _client()
    resp = client.get(PATH + "?q=a&q=b")
    assert resp.status_code == 422 and resp.json()["errors"][0]["type"] == "q_repeated"
    assert fake.calls == []


def test_query_at_limit_accepted(env):
    client, _ = _client()
    assert client.get(PATH, params={"q": "x" * explore.MAX_QUERY_CHARS}).status_code == 200


# --------------------------------------------------------------------------- cache


def test_cache_serves_repeat_within_ttl_and_keeps_original_retrieved_at(env):
    clock = Clock()
    client, fake = _client(clock=clock)
    first = client.get(PATH, params={"q": "Rate Shock"}).json()
    clock.t += explore.CACHE_TTL_S - 1
    second = client.get(PATH, params={"q": "  rate   shock "}).json()  # same normalized, case-folded key
    assert len(fake.calls) == 1
    assert second["cached"] is True and second["retrieved_at"] == first["retrieved_at"]
    assert any("cache" in n for n in second["notes"])
    clock.t += 2  # past the TTL
    third = client.get(PATH, params={"q": "rate shock"}).json()
    assert third["cached"] is False and len(fake.calls) == 2


def test_cache_keyed_by_max_results_and_bounded(env):
    client, fake = _client(max_entries=2)
    for q in ("a", "b", "c"):
        client.get(PATH, params={"q": q})
    client.get(PATH, params={"q": "c", "max_results": 3})
    assert len(fake.calls) == 4
    client.get(PATH, params={"q": "a"})  # evicted (LRU, max 2)
    assert len(fake.calls) == 5


# --------------------------------------------------------------------------- rate limit


def test_per_ip_rate_limit(env):
    clock = Clock()
    client, fake = _client(clock=clock, rate_limit_per_min=3)
    codes = [client.get(PATH, params={"q": f"q{i}"}).status_code for i in range(4)]
    assert codes == [200, 200, 200, 429]
    resp = client.get(PATH, params={"q": "again"})
    assert resp.json()["code"] == "RATE_LIMITED" and int(resp.headers["retry-after"]) >= 1
    assert len(fake.calls) == 3
    clock.t += 60
    assert client.get(PATH, params={"q": "later"}).status_code == 200


def test_rate_limit_is_per_ip(env):
    state = explore.ExploreState(clock=Clock(), rate_limit_per_min=1)
    assert state.limiter.take("10.0.0.1") is None
    assert state.limiter.take("10.0.0.1") is not None
    assert state.limiter.take("10.0.0.2") is None


# --------------------------------------------------------------------------- public-mode admin gate


def test_public_mode_without_token_is_403_and_spends_nothing(env):
    env.setenv("FAULTLINE_MODE", "public")
    env.setenv("FAULTLINE_ADMIN_TOKEN", ADMIN)
    client, fake = _client()
    for headers in ({}, {"Authorization": "Bearer wrong"}, {"Authorization": f"Basic {ADMIN}"},
                    {"Authorization": ADMIN}):
        resp = client.get(PATH, params={"q": "x"}, headers=headers)
        assert resp.status_code == 403
        assert resp.json()["code"] == "ADMIN_TOKEN_REQUIRED"
        assert ADMIN not in resp.text
    assert fake.calls == []


def test_public_mode_gate_runs_before_validation(env):
    env.setenv("FAULTLINE_MODE", "public")
    client, _ = _client()
    assert client.get(PATH).status_code == 403


def test_public_mode_with_admin_token_searches(env):
    env.setenv("FAULTLINE_MODE", "public")
    env.setenv("FAULTLINE_ADMIN_TOKEN", ADMIN)
    client, fake = _client()
    resp = client.get(PATH, params={"q": "x"}, headers={"Authorization": f"Bearer {ADMIN}"})
    assert resp.status_code == 200 and len(fake.calls) == 1


def test_public_mode_short_token_fails_closed(env):
    env.setenv("FAULTLINE_MODE", "public")
    env.setenv("FAULTLINE_ADMIN_TOKEN", "short")
    try:
        client, fake = _client()
    except ValueError:
        return  # PR #28's config refuses to start with a short token in public mode: also closed
    resp = client.get(PATH, params={"q": "x"}, headers={"Authorization": "Bearer short"})
    assert resp.status_code == 403 and fake.calls == []


def test_unknown_mode_fails_closed(env):
    env.setenv("FAULTLINE_MODE", "staging")
    try:
        client, fake = _client()
    except ValueError:
        return  # PR #28's config rejects unknown modes at startup
    assert client.get(PATH, params={"q": "x"}).status_code == 403 and fake.calls == []


def test_local_mode_needs_no_token(env):
    env.setenv("FAULTLINE_MODE", "local")
    client, fake = _client()
    assert client.get(PATH, params={"q": "x"}).status_code == 200


# --------------------------------------------------------------------------- contract


def test_openapi_documents_route_and_error_codes(env):
    client, _ = _client()
    spec = client.get("/openapi.json").json()
    op = spec["paths"][PATH]["get"]
    assert {"403", "422", "429", "502", "503", "504"} <= set(op["responses"])
    schema = spec["components"]["schemas"]["ExploreSearchResponse"]
    assert schema["properties"]["label"]["const"] == "LIVE EXPLORE: current, not point-in-time"
    assert "available_at" not in json.dumps(spec["components"]["schemas"]["ExploreSearchItem"])


@pytest.mark.parametrize(
    ("upstream", "reason"),
    [
        (httpx.Response(401, json={"detail": {"error": "Unauthorized"}}), "auth_rejected"),
        (httpx.Response(433, json={"detail": {"error": "limit"}}), "quota_exceeded"),
    ],
)
def test_unavailable_says_why(env, upstream, reason):
    client, _ = _client(FakeTavily(upstream))
    body = client.get(PATH, params={"q": "x"}).json()
    assert body["code"] == "LIVE_EXPLORE_UNAVAILABLE"
    assert [e["type"] for e in body["errors"]] == [reason]


def test_missing_key_reason_is_not_configured(env):
    env.delenv("TAVILY_API_KEY")
    client, _ = _client()
    body = client.get(PATH, params={"q": "x"}).json()
    assert [e["type"] for e in body["errors"]] == ["not_configured"]


def test_pasted_non_ascii_key_is_a_json_503_with_cors_not_a_500(env):
    bad = "tvly-abc​def" + "z" * 30
    env.setenv("TAVILY_API_KEY", bad)
    client, fake = _client()
    resp = client.get(PATH, params={"q": "x"}, headers={"Origin": "http://localhost:3000"})
    assert resp.status_code == 503
    assert resp.headers["content-type"].startswith("application/json")
    assert resp.headers.get("access-control-allow-origin") == "http://localhost:3000"
    body = resp.json()
    assert body["code"] == "LIVE_EXPLORE_UNAVAILABLE" and body["errors"][0]["type"] == "not_configured"
    assert bad not in resp.text and fake.calls == []


def test_cache_hit_echoes_the_requesters_own_query(env):
    client, fake = _client()
    first = client.get(PATH, params={"q": "Rate Shock"}).json()
    second = client.get(PATH, params={"q": "rate   SHOCK"}).json()
    assert len(fake.calls) == 1 and second["cached"] is True
    assert first["query"] == "Rate Shock" and second["query"] == "rate SHOCK"
