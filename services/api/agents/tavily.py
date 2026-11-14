"""Read-only Tavily web-search client for LIVE EXPLORE MODE ONLY (SPEC §3.3; issue #60).

SPEC §5: no retrieval tool, Tavily or web search is available to the replay model. This module is therefore
imported only by the Live Explore surface (``routes/explore.py``, ``agents/explore_*.py``,
``scripts/tavily_curate.py``); ``tests/test_explore_separation.py`` fails if any other module imports it.
It imports nothing from the replay side either (no ``EvidenceItem``, gate, store or vault), and its results
carry ``retrieved_at`` (when we fetched them), never an ``available_at``: they are current web content,
not point-in-time evidence.

Tavily Search API, as verified against the official docs on 2026-11-13
(https://docs.tavily.com/documentation/api-reference/endpoint/search):

- ``POST https://api.tavily.com/search``, JSON body, header ``Authorization: Bearer tvly-...``.
- Body used here: ``query`` (required), ``max_results`` (0-20, default 10), ``topic`` (general|news|finance),
  ``search_depth`` (basic = 1 credit, advanced = 2; ``fast``/``ultra-fast`` not used), optional
  ``time_range``, ``start_date``/``end_date`` (YYYY-MM-DD), ``include_domains``/``exclude_domains``, and
  ``include_published_date: true``. ``include_answer``, ``include_raw_content`` and ``include_images`` are
  sent as ``false``: we never request Tavily's LLM-written answer, only ranked sources.
- 200 body: ``{query, results: [{title, url, content, score, published_date?, ...}], response_time,
  request_id, ...}``. ``content`` is a snippet. ``published_date`` is "Tavily's best estimate of when the
  source was published or last updated", can be later than the original publish date, is null when no date
  is detected, and the docs' example is RFC 2822 (``"Tue, 11 Mar 2025 17:00:00 GMT"``).
- Errors: 400 invalid request, 401 missing/invalid key, 422 validation, 429 rate limited (may send
  ``Retry-After``), 432 plan usage limit, 433 pay-as-you-go limit, 434 live fetch unavailable (only with
  ``max_age_hours``, which is not sent), 500. Error bodies are ``{"detail": {"error": "..."}}``.

Secrets: the key is read from ``TAVILY_API_KEY`` by ``client_from_env`` only, kept in a private attribute,
sent only in the Authorization header (never the URL or body), and never logged, echoed or put in an
exception. ``TavilyError`` is raised outside of ``except`` blocks, so it carries no ``__context__`` /
``__cause__`` chain back to an httpx request object (which holds the headers).
"""

from __future__ import annotations

import math
import os
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from email.utils import parsedate_to_datetime
from enum import StrEnum
from typing import Any, Literal
from urllib.parse import urlsplit

import httpx

TAVILY_SEARCH_URL = "https://api.tavily.com/search"
TAVILY_DOCS_URL = "https://docs.tavily.com/documentation/api-reference/endpoint/search"
API_KEY_ENV = "TAVILY_API_KEY"

DEFAULT_TIMEOUT_S = 10.0
MAX_QUERY_CHARS = 400
TAVILY_MAX_RESULTS = 20  # documented upper bound of `max_results`
SNIPPET_MAX_CHARS = 1200
TITLE_MAX_CHARS = 300
UPSTREAM_MESSAGE_MAX_CHARS = 200

Topic = Literal["general", "news", "finance"]
SearchDepth = Literal["basic", "advanced"]
TimeRange = Literal["day", "week", "month", "year"]
_TOPICS = ("general", "news", "finance")
_DEPTHS = ("basic", "advanced")
_TIME_RANGES = ("day", "week", "month", "year")
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
_WS = re.compile(r"\s+")
# Printable ASCII, no spaces: anything else cannot be sent in an HTTP header as-is.
_KEY_CHARS = re.compile(r"[\x21-\x7e]+")


class TavilyErrorKind(StrEnum):
    NOT_CONFIGURED = "not_configured"  # TAVILY_API_KEY unset: Live Explore is disabled
    AUTH_REJECTED = "auth_rejected"  # 401/403: Tavily refused the configured key
    QUOTA_EXCEEDED = "quota_exceeded"  # 432/433: plan or pay-as-you-go limit reached
    RATE_LIMITED = "rate_limited"  # 429
    TIMEOUT = "timeout"  # no answer within the timeout
    NETWORK = "network"  # connection failed (DNS, TLS, refused, offline)
    BAD_REQUEST = "bad_request"  # 400/422: Tavily rejected the request parameters
    UPSTREAM = "upstream"  # 5xx, 434, redirects or any other unexpected status
    BAD_RESPONSE = "bad_response"  # 2xx whose body is not the documented shape


class TavilyError(Exception):
    """Every failure of a search. ``str()`` is a plain-language message that never contains the key."""

    def __init__(self, kind: TavilyErrorKind, message: str, *, status: int | None = None,
                 retry_after_s: int | None = None) -> None:
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.status = status
        self.retry_after_s = retry_after_s

    def __repr__(self) -> str:
        return f"{type(self).__name__}(kind={self.kind.value!r}, status={self.status!r})"


class TavilyUnavailable(TavilyError):
    """No usable key: NOT_CONFIGURED, AUTH_REJECTED or QUOTA_EXCEEDED. Show "Live Explore unavailable"."""


class TavilyRateLimited(TavilyError):
    """429 from Tavily. ``retry_after_s`` is Tavily's ``Retry-After`` when it sent one."""


class TavilyTimeout(TavilyError):
    """Tavily did not answer within the timeout."""


class TavilyUpstreamError(TavilyError):
    """NETWORK, BAD_REQUEST, UPSTREAM or BAD_RESPONSE."""


_KIND_CLASS: dict[TavilyErrorKind, type[TavilyError]] = {
    TavilyErrorKind.NOT_CONFIGURED: TavilyUnavailable,
    TavilyErrorKind.AUTH_REJECTED: TavilyUnavailable,
    TavilyErrorKind.QUOTA_EXCEEDED: TavilyUnavailable,
    TavilyErrorKind.RATE_LIMITED: TavilyRateLimited,
    TavilyErrorKind.TIMEOUT: TavilyTimeout,
}


def _error(kind: TavilyErrorKind, message: str, **kw: Any) -> TavilyError:
    return _KIND_CLASS.get(kind, TavilyUpstreamError)(kind, message, **kw)


@dataclass(frozen=True)
class TavilyHit:
    """One search result. ``retrieved_at`` is when FAULTLINE fetched it; there is deliberately no ``available_at``.

    ``published_at`` is Tavily's estimate (tz-aware, UTC) when it could be parsed as an instant;
    ``published_at_raw`` is the string Tavily sent (``None`` when it sent none). Neither proves when the page
    first became public.
    """

    title: str
    url: str
    snippet: str
    score: float | None
    published_at: datetime | None
    published_at_raw: str | None
    retrieved_at: datetime

    def as_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "url": self.url,
            "snippet": self.snippet,
            "score": self.score,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "published_at_raw": self.published_at_raw,
            "retrieved_at": self.retrieved_at.isoformat(),
        }


@dataclass(frozen=True)
class TavilySearchResponse:
    query: str
    items: tuple[TavilyHit, ...]
    retrieved_at: datetime
    dropped: int = 0  # results skipped: missing title, invalid url, or duplicate url
    request_id: str | None = None
    response_time_s: float | None = None
    params: dict[str, Any] = field(default_factory=dict)  # request body actually sent (no key)


def _clean(value: Any, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    text = _WS.sub(" ", _CONTROL.sub(" ", value)).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def normalize_query(query: str) -> str:
    """Collapse whitespace and drop control characters. The route and the curation script use the same rule."""
    return _WS.sub(" ", _CONTROL.sub(" ", query)).strip()


def _http_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    url = value.strip()
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not parts.netloc or _CONTROL.search(url) or " " in url:
        return None
    return url


def parse_published_date(raw: Any) -> datetime | None:
    """Tavily ``published_date`` -> tz-aware UTC instant, or None (also for date-only / naive values,
    whose time zone is unknown: the raw string is kept for display instead of guessing)."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    text = raw.strip()
    parsed: datetime | None = None
    try:
        parsed = parsedate_to_datetime(text)  # RFC 2822, the documented example format
    except (TypeError, ValueError, IndexError):
        parsed = None
    if parsed is None:
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00") if text.endswith("Z") else text)
        except ValueError:
            return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


def _retry_after(headers: httpx.Headers) -> int | None:
    raw = headers.get("retry-after", "").strip()
    return int(raw) if raw.isdigit() else None


def _redact(text: str, secret: Callable[[], str]) -> str:
    key = secret()
    return text.replace(key, "[redacted]") if key else text


def _upstream_detail(resp: httpx.Response, secret: Callable[[], str]) -> str | None:
    """Tavily's own error text for 400/422 (useful: e.g. 'Invalid topic'), redacted and truncated."""
    try:
        body = resp.json()
    except ValueError:
        return None
    detail = body.get("detail") if isinstance(body, dict) else None
    if isinstance(detail, dict) and isinstance(detail.get("error"), str):
        text = detail["error"]
    elif isinstance(detail, list):
        text = "; ".join(str(d.get("msg", "")) for d in detail if isinstance(d, dict)) or ""
    else:
        return None
    text = _clean(_redact(text, secret), UPSTREAM_MESSAGE_MAX_CHARS)
    return text or None


def _status_error(resp: httpx.Response, secret: Callable[[], str]) -> TavilyError:
    status = resp.status_code
    if status in (401, 403):
        return _error(TavilyErrorKind.AUTH_REJECTED,
                      "Tavily rejected the configured TAVILY_API_KEY (missing, invalid or revoked).", status=status)
    if status in (432, 433):
        return _error(TavilyErrorKind.QUOTA_EXCEEDED,
                      "Tavily usage limit reached for the configured key (plan or pay-as-you-go limit).",
                      status=status)
    if status == 429:
        return _error(TavilyErrorKind.RATE_LIMITED, "Tavily rate limit reached; retry shortly.", status=status,
                      retry_after_s=_retry_after(resp.headers))
    if status in (400, 422):
        detail = _upstream_detail(resp, secret)
        msg = "Tavily rejected the search parameters" + (f": {detail}" if detail else ".")
        return _error(TavilyErrorKind.BAD_REQUEST, msg, status=status)
    return _error(TavilyErrorKind.UPSTREAM, f"Tavily returned HTTP {status}.", status=status)


def _check_date(value: date | str | None, name: str) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        raise ValueError(f"{name} must be a calendar date (YYYY-MM-DD), not a datetime")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        date.fromisoformat(value)  # raises ValueError on an impossible date
        return value
    raise ValueError(f"{name} must be YYYY-MM-DD")


def _domains(values: Sequence[str] | None, name: str, limit: int) -> list[str] | None:
    if values is None:
        return None
    if isinstance(values, str):
        raise ValueError(f"{name} must be a list of domains")
    cleaned = [v.strip() for v in values if isinstance(v, str) and v.strip()]
    if len(cleaned) > limit:
        raise ValueError(f"{name} accepts at most {limit} domains")
    return cleaned or None


class TavilyClient:
    """Async, read-only Tavily search. One method: ``search``. Pass ``transport`` (e.g. ``httpx.MockTransport``)
    in tests; ``None`` uses the real network."""

    def __init__(
        self,
        api_key: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        clock: Callable[[], datetime] | None = None,
        base_url: str = TAVILY_SEARCH_URL,
    ) -> None:
        key = api_key.strip() if isinstance(api_key, str) else ""
        if not key:
            raise _error(TavilyErrorKind.NOT_CONFIGURED,
                         f"{API_KEY_ENV} is not set: Live Explore web search is unavailable.")
        if not _KEY_CHARS.fullmatch(key):
            # e.g. a pasted zero-width space or smart quote. httpx would fail to encode the header with a
            # UnicodeEncodeError whose `.object` holds "Bearer <key>"; refuse here instead (message names no chars).
            raise _error(TavilyErrorKind.NOT_CONFIGURED,
                         f"{API_KEY_ENV} contains whitespace or non-ASCII characters (often from copy and paste); "
                         "re-copy the key from the Tavily dashboard.")
        if not (timeout_s > 0 and math.isfinite(timeout_s)):
            raise ValueError("timeout_s must be a positive number")
        # Held in a closure, not an attribute, so vars()/repr()/debug dumps of the client never show it.
        def _secret() -> str:
            return key

        self._secret = _secret
        self._transport = transport
        self._timeout_s = float(timeout_s)
        self._clock = clock or (lambda: datetime.now(UTC))
        self._url = base_url

    def _headers(self) -> dict[str, str]:
        """Request headers; the key is read into the Authorization value here and nowhere else."""
        return {"Authorization": "Bearer " + self._secret(), "Accept": "application/json"}

    def __repr__(self) -> str:  # never shows the key
        return f"TavilyClient(url={self._url!r}, timeout_s={self._timeout_s}, key=<set>)"

    __str__ = __repr__

    def __reduce__(self):  # refuse pickling (which would serialize the key)
        raise TypeError("TavilyClient cannot be pickled")

    @staticmethod
    def build_params(
        query: str,
        *,
        max_results: int = 5,
        topic: Topic = "general",
        search_depth: SearchDepth = "basic",
        time_range: TimeRange | None = None,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
        include_domains: Sequence[str] | None = None,
        exclude_domains: Sequence[str] | None = None,
    ) -> dict[str, Any]:
        """Validated request body (without the key). Raises ValueError on bad arguments, before any network."""
        q = normalize_query(query) if isinstance(query, str) else ""
        if not q:
            raise ValueError("query must be a non-empty string")
        if len(q) > MAX_QUERY_CHARS:
            raise ValueError(f"query is longer than {MAX_QUERY_CHARS} characters")
        valid_int = isinstance(max_results, int) and not isinstance(max_results, bool)
        if not valid_int or not 1 <= max_results <= TAVILY_MAX_RESULTS:
            raise ValueError(f"max_results must be an integer from 1 to {TAVILY_MAX_RESULTS}")
        if topic not in _TOPICS:
            raise ValueError(f"topic must be one of {_TOPICS}")
        if search_depth not in _DEPTHS:
            raise ValueError(f"search_depth must be one of {_DEPTHS}")
        if time_range is not None and time_range not in _TIME_RANGES:
            raise ValueError(f"time_range must be one of {_TIME_RANGES}")
        params: dict[str, Any] = {
            "query": q,
            "max_results": max_results,
            "topic": topic,
            "search_depth": search_depth,
            "include_answer": False,
            "include_raw_content": False,
            "include_images": False,
            "include_published_date": True,
        }
        optional = {
            "time_range": time_range,
            "start_date": _check_date(start_date, "start_date"),
            "end_date": _check_date(end_date, "end_date"),
            "include_domains": _domains(include_domains, "include_domains", 300),
            "exclude_domains": _domains(exclude_domains, "exclude_domains", 150),
        }
        params.update({k: v for k, v in optional.items() if v is not None})
        if "start_date" in params and "end_date" in params and params["start_date"] > params["end_date"]:
            raise ValueError("start_date must not be after end_date")
        return params

    async def search(self, query: str, **options: Any) -> TavilySearchResponse:
        """Run one search. Raises ``ValueError`` for bad arguments and a ``TavilyError`` subclass for every
        failure (never returns placeholder results). ``options`` are the keyword arguments of ``build_params``."""
        params = self.build_params(query, **options)
        failure: TavilyError | None = None
        resp: httpx.Response | None = None
        try:
            async with httpx.AsyncClient(timeout=self._timeout_s, transport=self._transport,
                                         follow_redirects=False) as client:
                resp = await client.post(self._url, json=params, headers=self._headers())
        except httpx.TimeoutException:
            failure = _error(TavilyErrorKind.TIMEOUT, f"Tavily did not answer within {self._timeout_s:g} s.")
        except (httpx.HTTPError, httpx.InvalidURL) as exc:
            failure = _error(TavilyErrorKind.NETWORK, f"Could not reach Tavily ({type(exc).__name__}).")
        except Exception as exc:  # noqa: BLE001 - anything else (e.g. header encoding) must not escape untyped
            failure = _error(TavilyErrorKind.UPSTREAM, f"Tavily request failed ({type(exc).__name__}).")
        # Raised here, outside the except blocks, so no exception chain links back to the request headers.
        if failure is not None:
            raise failure
        assert resp is not None
        retrieved_at = self._clock()
        if resp.status_code != 200:
            raise _status_error(resp, self._secret)
        payload: Any = None
        try:
            payload = resp.json()
        except ValueError:
            payload = None
        if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
            raise _error(TavilyErrorKind.BAD_RESPONSE, "Tavily answered with a body that is not a search result list.",
                         status=resp.status_code)
        return _parse(payload, params, retrieved_at)


def _parse(payload: dict[str, Any], params: dict[str, Any], retrieved_at: datetime) -> TavilySearchResponse:
    items: list[TavilyHit] = []
    seen: set[str] = set()
    dropped = 0
    for raw in payload["results"]:
        if not isinstance(raw, dict):
            dropped += 1
            continue
        url = _http_url(raw.get("url"))
        title = _clean(raw.get("title"), TITLE_MAX_CHARS)
        if url is None or not title or url in seen:
            dropped += 1
            continue
        seen.add(url)
        score = raw.get("score")
        score_ok = isinstance(score, int | float) and not isinstance(score, bool) and math.isfinite(score)
        pub_raw = raw.get("published_date")
        items.append(
            TavilyHit(
                title=title,
                url=url,
                snippet=_clean(raw.get("content"), SNIPPET_MAX_CHARS),
                score=float(score) if score_ok else None,
                published_at=parse_published_date(pub_raw),
                published_at_raw=_clean(pub_raw, 80) or None,
                retrieved_at=retrieved_at,
            )
        )
        if len(items) >= params["max_results"]:
            break
    rt = payload.get("response_time")
    try:
        response_time = float(rt) if rt is not None and not isinstance(rt, bool) else None
    except (TypeError, ValueError):
        response_time = None
    if response_time is not None and not math.isfinite(response_time):
        response_time = None
    request_id = payload.get("request_id")
    return TavilySearchResponse(
        query=params["query"],
        items=tuple(items),
        retrieved_at=retrieved_at,
        dropped=dropped,
        request_id=request_id if isinstance(request_id, str) else None,
        response_time_s=response_time,
        params=dict(params),
    )


def key_configured() -> bool:
    return bool(os.environ.get(API_KEY_ENV, "").strip())


def client_from_env(**kwargs: Any) -> TavilyClient:
    """Build a client from ``TAVILY_API_KEY``. Raises ``TavilyUnavailable`` (NOT_CONFIGURED) when it is unset.
    ``kwargs`` go to ``TavilyClient`` (``transport``, ``timeout_s``, ``clock``)."""
    return TavilyClient(os.environ.get(API_KEY_ENV, ""), **kwargs)
