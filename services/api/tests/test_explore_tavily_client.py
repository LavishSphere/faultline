"""agents/tavily.py: request shape (as documented by Tavily), parsing, typed errors, and key secrecy.

Every test uses httpx.MockTransport: no network, no real key.
"""

from __future__ import annotations

import asyncio
import json
import logging
import pickle
import traceback
from datetime import UTC, date, datetime

import httpx
import pytest

from agents import tavily

KEY = "tvly-secret-" + "s" * 40
FIXED_NOW = datetime(2026, 11, 13, 15, 0, tzinfo=UTC)


def _payload(results=None, **extra):
    body = {
        "query": "q",
        "results": results if results is not None else [
            {"title": "A", "url": "https://a.example/1", "content": "alpha", "score": 0.9,
             "published_date": "Tue, 11 Mar 2025 17:00:00 GMT"},
            {"title": "B", "url": "https://b.example/2", "content": "beta", "score": 0.5, "published_date": None},
        ],
        "response_time": 1.67,
        "request_id": "123e4567-e89b-12d3-a456-426614174111",
    }
    body.update(extra)
    return body


class Recorder:
    def __init__(self, response: httpx.Response | Exception) -> None:
        self.response = response
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def _client(rec: Recorder, **kw) -> tavily.TavilyClient:
    return tavily.TavilyClient(KEY, transport=httpx.MockTransport(rec), clock=lambda: FIXED_NOW, **kw)


def _run(coro):
    return asyncio.run(coro)


# --------------------------------------------------------------------------- request shape


def test_request_matches_documented_api():
    rec = Recorder(httpx.Response(200, json=_payload()))
    _run(_client(rec).search("  regional   banks\tdeposits ", max_results=2, topic="news",
                             start_date=date(2025, 1, 1), end_date="2025-03-01"))
    (req,) = rec.requests
    assert req.method == "POST"
    assert str(req.url) == "https://api.tavily.com/search"
    assert req.headers["authorization"] == f"Bearer {KEY}"
    assert KEY not in str(req.url)
    body = json.loads(req.content)
    assert KEY not in json.dumps(body)  # key only in the header, never the body
    assert body == {
        "query": "regional banks deposits",
        "max_results": 2,
        "topic": "news",
        "search_depth": "basic",
        "include_answer": False,
        "include_raw_content": False,
        "include_images": False,
        "include_published_date": True,
        "start_date": "2025-01-01",
        "end_date": "2025-03-01",
    }


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_results": 0},
        {"max_results": 21},
        {"max_results": True},
        {"topic": "sports"},
        {"search_depth": "ultra-fast"},
        {"time_range": "decade"},
        {"start_date": "2025-13-01"},
        {"end_date": datetime(2025, 1, 1, tzinfo=UTC)},
        {"start_date": "2025-03-02", "end_date": "2025-03-01"},
        {"include_domains": "example.com"},
    ],
)
def test_bad_arguments_raise_before_any_request(kwargs):
    rec = Recorder(httpx.Response(200, json=_payload()))
    with pytest.raises(ValueError):
        _run(_client(rec).search("q", **kwargs))
    assert rec.requests == []


@pytest.mark.parametrize("query", ["", "   ", "\x00\x01", "x" * (tavily.MAX_QUERY_CHARS + 1)])
def test_bad_query_raises(query):
    rec = Recorder(httpx.Response(200, json=_payload()))
    with pytest.raises(ValueError):
        _run(_client(rec).search(query))
    assert rec.requests == []


# --------------------------------------------------------------------------- parsing


def test_parses_results_with_retrieved_at_and_published_estimate():
    rec = Recorder(httpx.Response(200, json=_payload()))
    resp = _run(_client(rec).search("q", max_results=5))
    assert resp.retrieved_at == FIXED_NOW
    assert resp.request_id == "123e4567-e89b-12d3-a456-426614174111"
    assert resp.response_time_s == pytest.approx(1.67)
    a, b = resp.items
    assert (a.title, a.url, a.snippet, a.score) == ("A", "https://a.example/1", "alpha", 0.9)
    assert a.published_at == datetime(2025, 3, 11, 17, 0, tzinfo=UTC)
    assert a.published_at_raw == "Tue, 11 Mar 2025 17:00:00 GMT"
    assert a.retrieved_at == FIXED_NOW
    assert b.published_at is None and b.published_at_raw is None
    assert "available_at" not in a.as_dict()


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Tue, 11 Mar 2025 17:00:00 GMT", datetime(2025, 3, 11, 17, 0, tzinfo=UTC)),
        ("2025-03-11T17:00:00Z", datetime(2025, 3, 11, 17, 0, tzinfo=UTC)),
        ("2025-03-11T12:00:00-05:00", datetime(2025, 3, 11, 17, 0, tzinfo=UTC)),
        ("2025-03-11", None),  # date only: time zone unknown, keep raw only
        ("2025-03-11T17:00:00", None),  # naive
        ("last week", None),
        (None, None),
        (12345, None),
    ],
)
def test_published_date_parsing(raw, expected):
    assert tavily.parse_published_date(raw) == expected


def test_malformed_and_duplicate_results_are_dropped_not_patched():
    results = [
        {"title": "ok", "url": "https://ok.example/", "content": "c"},
        {"title": "", "url": "https://notitle.example/"},
        {"title": "no url"},
        {"title": "ftp", "url": "ftp://x.example/file"},
        {"title": "js", "url": "javascript:alert(1)"},
        {"title": "dup", "url": "https://ok.example/"},
        "not an object",
        {"title": "bad score", "url": "https://s.example/", "score": "high", "content": None},
    ]
    resp = _run(_client(Recorder(httpx.Response(200, json=_payload(results)))).search("q", max_results=10))
    assert [h.url for h in resp.items] == ["https://ok.example/", "https://s.example/"]
    assert resp.items[1].score is None and resp.items[1].snippet == ""
    assert resp.dropped == 6


def test_result_count_capped_at_max_results_and_text_cleaned():
    results = [{"title": f"t{i}\n\x07x", "url": f"https://e.example/{i}", "content": "y" * 5000} for i in range(8)]
    resp = _run(_client(Recorder(httpx.Response(200, json=_payload(results)))).search("q", max_results=3))
    assert len(resp.items) == 3
    assert resp.items[0].title == "t0 x"
    assert len(resp.items[0].snippet) <= tavily.SNIPPET_MAX_CHARS


@pytest.mark.parametrize("body", [b"not json", b"[]", b'{"answer": "x"}', b'{"results": {}}'])
def test_bad_body_is_typed_error(body):
    rec = Recorder(httpx.Response(200, content=body))
    with pytest.raises(tavily.TavilyUpstreamError) as exc:
        _run(_client(rec).search("q"))
    assert exc.value.kind is tavily.TavilyErrorKind.BAD_RESPONSE


# --------------------------------------------------------------------------- errors


@pytest.mark.parametrize(
    ("status", "cls", "kind"),
    [
        (401, tavily.TavilyUnavailable, tavily.TavilyErrorKind.AUTH_REJECTED),
        (403, tavily.TavilyUnavailable, tavily.TavilyErrorKind.AUTH_REJECTED),
        (432, tavily.TavilyUnavailable, tavily.TavilyErrorKind.QUOTA_EXCEEDED),
        (433, tavily.TavilyUnavailable, tavily.TavilyErrorKind.QUOTA_EXCEEDED),
        (429, tavily.TavilyRateLimited, tavily.TavilyErrorKind.RATE_LIMITED),
        (400, tavily.TavilyUpstreamError, tavily.TavilyErrorKind.BAD_REQUEST),
        (422, tavily.TavilyUpstreamError, tavily.TavilyErrorKind.BAD_REQUEST),
        (434, tavily.TavilyUpstreamError, tavily.TavilyErrorKind.UPSTREAM),
        (500, tavily.TavilyUpstreamError, tavily.TavilyErrorKind.UPSTREAM),
        (302, tavily.TavilyUpstreamError, tavily.TavilyErrorKind.UPSTREAM),
    ],
)
def test_status_codes_map_to_typed_errors(status, cls, kind):
    rec = Recorder(httpx.Response(status, json={"detail": {"error": f"echo {KEY}"}},
                                  headers={"Retry-After": "7", "Location": "https://elsewhere.example/"}))
    with pytest.raises(cls) as exc:
        _run(_client(rec).search("q"))
    err = exc.value
    assert err.kind is kind and err.status == status
    assert KEY not in str(err) and KEY not in repr(err)
    if status == 429:
        assert err.retry_after_s == 7
    assert len(rec.requests) == 1  # redirects are not followed


def test_bad_request_includes_redacted_upstream_detail():
    rec = Recorder(httpx.Response(400, json={"detail": {"error": f"Invalid topic {KEY}"}}))
    with pytest.raises(tavily.TavilyUpstreamError) as exc:
        _run(_client(rec).search("q"))
    assert "Invalid topic [redacted]" in str(exc.value)


@pytest.mark.parametrize(
    ("raised", "cls", "kind"),
    [
        (httpx.ReadTimeout("slow"), tavily.TavilyTimeout, tavily.TavilyErrorKind.TIMEOUT),
        (httpx.ConnectTimeout("slow"), tavily.TavilyTimeout, tavily.TavilyErrorKind.TIMEOUT),
        (httpx.ConnectError("refused"), tavily.TavilyUpstreamError, tavily.TavilyErrorKind.NETWORK),
    ],
)
def test_transport_failures_are_typed_and_carry_no_exception_chain(raised, cls, kind):
    rec = Recorder(raised)
    with pytest.raises(cls) as exc:
        _run(_client(rec).search("q"))
    err = exc.value
    assert err.kind is kind
    # No link back to the httpx exception / request (whose headers hold the key).
    assert err.__cause__ is None and err.__context__ is None
    formatted = "".join(traceback.format_exception(err))
    assert KEY not in formatted and "Authorization" not in formatted


def test_missing_key_is_not_configured(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    assert tavily.key_configured() is False
    with pytest.raises(tavily.TavilyUnavailable) as exc:
        tavily.client_from_env()
    assert exc.value.kind is tavily.TavilyErrorKind.NOT_CONFIGURED
    monkeypatch.setenv("TAVILY_API_KEY", "   ")
    with pytest.raises(tavily.TavilyUnavailable):
        tavily.client_from_env()


def test_key_never_in_repr_logs_or_pickle(monkeypatch, caplog):
    monkeypatch.setenv("TAVILY_API_KEY", KEY)
    caplog.set_level(logging.DEBUG)
    rec = Recorder(httpx.Response(401, json={"detail": {"error": "Unauthorized: missing or invalid API key."}}))
    client = tavily.client_from_env(transport=httpx.MockTransport(rec))
    assert KEY not in repr(client) and KEY not in str(client)
    assert KEY not in repr(vars(client))  # held in a closure, not an attribute
    with pytest.raises(TypeError):
        pickle.dumps(client)
    with pytest.raises(tavily.TavilyUnavailable):
        _run(client.search("q"))
    assert KEY not in caplog.text


def test_invalid_timeout_rejected():
    with pytest.raises(ValueError):
        tavily.TavilyClient(KEY, timeout_s=0)


@pytest.mark.parametrize(
    "bad_key",
    [
        "tvly-abc​def" + "x" * 30,  # zero-width space pasted inside
        "“tvly-" + "q" * 30 + "”",  # smart quotes around it
        "tvly-abc def" + "x" * 30,  # inner space
        "tvly-abc\tdef" + "x" * 30,
    ],
)
def test_key_with_unsendable_characters_is_not_configured(bad_key, monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", bad_key)
    with pytest.raises(tavily.TavilyUnavailable) as exc:
        tavily.client_from_env()
    assert exc.value.kind is tavily.TavilyErrorKind.NOT_CONFIGURED
    assert bad_key.strip() not in str(exc.value) and bad_key.strip() not in repr(exc.value)
    assert exc.value.__context__ is None and exc.value.__cause__ is None


@pytest.mark.parametrize(
    "raised",
    [
        RuntimeError(f"boom Bearer {KEY}"),
        UnicodeEncodeError("ascii", f"Bearer {KEY}", 7, 8, "ordinal not in range(128)"),
        KeyError(KEY),
    ],
)
def test_non_httpx_failure_is_typed_with_no_chain(raised):
    rec = Recorder(raised)
    with pytest.raises(tavily.TavilyUpstreamError) as exc:
        _run(_client(rec).search("q"))
    err = exc.value
    assert err.kind is tavily.TavilyErrorKind.UPSTREAM
    assert type(raised).__name__ in str(err)
    assert err.__cause__ is None and err.__context__ is None
    formatted = "".join(traceback.format_exception(err))
    assert KEY not in formatted and "Bearer" not in formatted


def test_key_is_not_kept_as_a_local_in_search():
    """The key is read into the Authorization header inside _headers() only (audit nit on PR #73)."""
    import inspect

    source = inspect.getsource(tavily.TavilyClient.search)
    assert "_secret()" not in source and "secret =" not in source
