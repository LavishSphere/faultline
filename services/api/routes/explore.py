"""GET /api/explore/search: LIVE EXPLORE web search via Tavily (SPEC §3.3; issue #60).

Live Explore answers "what does current public news say?", next to (never inside) the Blind Replay:

- Results are current web content labeled ``LIVE EXPLORE: current, not point-in-time``. Each carries
  ``retrieved_at`` (when this API fetched it) and Tavily's ``published_at`` estimate. There is no
  ``available_at``, and nothing here creates an ``EvidenceItem``, writes a case file or touches a prompt.
  ``tests/test_explore_separation.py`` fails if a replay module imports this module or the Tavily client.
- Missing ``TAVILY_API_KEY`` -> 503 ``LIVE_EXPLORE_UNAVAILABLE``. Never placeholder results.
- Guards (in this order): public-mode admin token -> query validation -> key configured -> per-IP rate
  limit -> 5-minute in-memory cache -> Tavily.

Public mode (``FAULTLINE_MODE=public``, PR #28): requires ``Authorization: Bearer <FAULTLINE_ADMIN_TOKEN>``,
as for ``/api/replay/run``, so public visitors cannot spend API credits. The check lives in this route so it
works before and after PR #28: it uses ``config.admin_token_matches`` and ``Settings.mode`` when they exist,
otherwise the same rules read from the environment (token >= 32 characters, constant-time compare; any
mode other than ``local`` fails closed). The web app never sends the token, so the public demo shows
"admin only". Error code ``ADMIN_TOKEN_REQUIRED`` matches PR #28's edge gate.

Errors use ``routes.RouteErrorBody`` ``{"code", "message", "errors": [{loc, msg, type}]}`` with codes from
``models.ErrorCode``: VALIDATION_ERROR 422, ADMIN_TOKEN_REQUIRED 403, RATE_LIMITED 429 (Retry-After),
LIVE_EXPLORE_UNAVAILABLE 503, LIVE_EXPLORE_UPSTREAM_ERROR 502, LIVE_EXPLORE_TIMEOUT 504.
"""

from __future__ import annotations

import hmac
import logging
import os
import time
from collections import OrderedDict
from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Any, Literal

import httpx
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

import config
from agents import tavily
from config import Settings, get_settings
from models import ErrorCode
from routes import CodedRoute, FieldIssue, RouteError, RouteErrorBody

logger = logging.getLogger(__name__)

LIVE_EXPLORE_LABEL = "LIVE EXPLORE: current, not point-in-time"
ATTRIBUTION = "Search powered by Tavily"
MAX_QUERY_CHARS = 200
DEFAULT_MAX_RESULTS = 5
MAX_RESULTS = 10
CACHE_TTL_S = 300.0
CACHE_MAX_ENTRIES = 256
RATE_LIMIT_PER_MIN = 10
TAVILY_TIMEOUT_S = 10.0
MIN_ADMIN_TOKEN_LEN = 32  # same rule as PR #28's config.MIN_ADMIN_TOKEN_LEN

NOT_POINT_IN_TIME_NOTE = (
    "Current web results, retrieved at retrieved_at. Not point-in-time: never given to the Blind Replay, "
    "its prompts, or the scorecard."
)
PUBLISHED_AT_NOTE = (
    "published_at is Tavily's estimate of when a page was published or last updated. It can be later than the "
    "original date and is not proof of when the text became public."
)
SNIPPET_NOTE = (
    "Snippets are excerpts selected by Tavily search, not FAULTLINE claims. No AI-written answer is requested."
)
CACHED_NOTE = "Served from this API's 5-minute cache; retrieved_at is the original retrieval time."


# --------------------------------------------------------------------------- errors


class ExploreError(RouteError):
    """RouteError that can also carry response headers (Retry-After on 429). Rendered by CodedRoute."""

    def __init__(self, code: ErrorCode, message: str, status_code: int,
                 errors: list[FieldIssue] | None = None, headers: dict[str, str] | None = None) -> None:
        super().__init__(code, message, status_code=status_code, errors=errors)
        self.headers = headers or {}

    def response(self) -> JSONResponse:
        resp = super().response()
        resp.headers.update(self.headers)
        return resp


_ERROR_DESCRIPTIONS = {
    403: "ADMIN_TOKEN_REQUIRED: public mode, admin token missing or wrong",
    422: "VALIDATION_ERROR",
    429: "RATE_LIMITED (Retry-After header)",
    502: "LIVE_EXPLORE_UPSTREAM_ERROR",
    503: "LIVE_EXPLORE_UNAVAILABLE: TAVILY_API_KEY not set, rejected, or over quota",
    504: "LIVE_EXPLORE_TIMEOUT",
}
_RESPONSES: dict[int | str, dict[str, Any]] = {
    code: {"model": RouteErrorBody, "description": desc} for code, desc in _ERROR_DESCRIPTIONS.items()
}


# --------------------------------------------------------------------------- response models


class ExploreSearchItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    url: str
    snippet: str = Field(description="Excerpt chosen by Tavily search (may be empty).")
    score: float | None = Field(description="Tavily relevance score, as sent; null when absent.")
    published_at: datetime | None = Field(
        description="Tavily's estimate of publish/last-update time (UTC); null when absent or not an instant."
    )
    published_at_raw: str | None = Field(description="published_date exactly as Tavily sent it.")
    retrieved_at: datetime = Field(description="When this API fetched the result from Tavily (UTC).")


class ExploreSearchResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_serialization_defaults_required=True)

    mode: Literal["live_explore"] = "live_explore"
    label: Literal["LIVE EXPLORE: current, not point-in-time"] = LIVE_EXPLORE_LABEL
    provider: Literal["tavily"] = "tavily"
    attribution: Literal["Search powered by Tavily"] = ATTRIBUTION
    query: str = Field(description="The normalized query sent to Tavily.")
    retrieved_at: datetime
    cached: bool
    items: list[ExploreSearchItem]
    notes: list[str]


# --------------------------------------------------------------------------- per-app state: cache + rate limit


class _TokenBucket:
    """Per-key token bucket: `per_minute` capacity, continuous refill, LRU-bounded memory."""

    def __init__(self, per_minute: int, clock: Callable[[], float], max_keys: int = 10_000) -> None:
        self.capacity = float(per_minute)
        self.rate = per_minute / 60.0
        self.clock = clock
        self.max_keys = max_keys
        self._buckets: OrderedDict[str, tuple[float, float]] = OrderedDict()

    def take(self, key: str) -> int | None:
        """None when allowed, else seconds until a token is available."""
        now = self.clock()
        tokens, last = self._buckets.pop(key, (self.capacity, now))
        tokens = min(self.capacity, tokens + (now - last) * self.rate)
        allowed = tokens >= 1.0
        if allowed:
            tokens -= 1.0
        self._buckets[key] = (tokens, now)
        while len(self._buckets) > self.max_keys:
            self._buckets.popitem(last=False)
        return None if allowed else max(1, int((1.0 - tokens) / self.rate + 0.999))


class ExploreState:
    """Cache and limiter for one app instance (kept on ``app.state``; nothing persists to disk)."""

    def __init__(self, clock: Callable[[], float] = time.monotonic, rate_limit_per_min: int = RATE_LIMIT_PER_MIN,
                 ttl_s: float = CACHE_TTL_S, max_entries: int = CACHE_MAX_ENTRIES) -> None:
        self.clock = clock
        self.ttl_s = ttl_s
        self.max_entries = max_entries
        self.limiter = _TokenBucket(rate_limit_per_min, clock)
        self._cache: OrderedDict[tuple[str, int], tuple[float, tavily.TavilySearchResponse]] = OrderedDict()

    def cached(self, key: tuple[str, int]) -> tavily.TavilySearchResponse | None:
        hit = self._cache.get(key)
        if hit is None:
            return None
        stored_at, value = hit
        if self.clock() - stored_at >= self.ttl_s:
            del self._cache[key]
            return None
        self._cache.move_to_end(key)
        return value

    def store(self, key: tuple[str, int], value: tavily.TavilySearchResponse) -> None:
        self._cache[key] = (self.clock(), value)
        self._cache.move_to_end(key)
        while len(self._cache) > self.max_entries:
            self._cache.popitem(last=False)


def get_explore_state(request: Request) -> ExploreState:
    state = getattr(request.app.state, "faultline_explore", None)
    if state is None:
        state = ExploreState()
        request.app.state.faultline_explore = state
    return state


def get_tavily_transport() -> httpx.AsyncBaseTransport | None:
    """Dependency hook: None = real network. Tests override it with httpx.MockTransport."""
    return None


# --------------------------------------------------------------------------- public-mode admin gate


def _public_mode(settings: Settings) -> bool:
    mode = getattr(settings, "mode", None)  # Settings.mode exists once PR #28 lands
    if mode is None:
        mode = os.environ.get("FAULTLINE_MODE", "").strip().lower() or "local"
    return mode != "local"  # fail closed on anything unexpected


def _token_matches(presented: str) -> bool:
    matcher = getattr(config, "admin_token_matches", None)  # PR #28's constant-time check
    if callable(matcher):
        return bool(matcher(presented))
    expected = os.environ.get("FAULTLINE_ADMIN_TOKEN", "").strip()
    if len(expected) < MIN_ADMIN_TOKEN_LEN or not presented:
        return False
    return hmac.compare_digest(presented.encode("utf-8"), expected.encode("utf-8"))


def require_admin_in_public_mode(request: Request, settings: Annotated[Settings, Depends(get_settings)]) -> None:
    if not _public_mode(settings):
        return
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not _token_matches(token.strip()):
        raise ExploreError(
            ErrorCode.ADMIN_TOKEN_REQUIRED,
            "Live Explore search is admin only on the public demo (it spends Tavily API credits). "
            "Run FAULTLINE locally with TAVILY_API_KEY set to use it.",
            403,
        )


# --------------------------------------------------------------------------- route

router = APIRouter(tags=["explore"], route_class=CodedRoute)


def _validation(loc: list[str | int], msg: str, kind: str) -> ExploreError:
    return ExploreError(ErrorCode.VALIDATION_ERROR, "Request failed validation; see `errors` for each field.",
                        422, errors=[FieldIssue(loc=loc, msg=msg, type=kind)])


def _unavailable(kind: tavily.TavilyErrorKind, message: str) -> ExploreError:
    """503 whose `errors[0].type` says why: not_configured | auth_rejected | quota_exceeded (the web app's note)."""
    reason = FieldIssue(loc=["server", "tavily"], msg=message, type=kind.value)
    return ExploreError(ErrorCode.LIVE_EXPLORE_UNAVAILABLE, message, 503, errors=[reason])


def _from_tavily(err: tavily.TavilyError) -> ExploreError:
    if isinstance(err, tavily.TavilyUnavailable):
        return _unavailable(err.kind, f"Live Explore unavailable: {err.message}")
    if isinstance(err, tavily.TavilyRateLimited):
        headers = {"Retry-After": str(err.retry_after_s)} if err.retry_after_s else {}
        return ExploreError(ErrorCode.RATE_LIMITED, err.message, 429, headers=headers)
    if isinstance(err, tavily.TavilyTimeout):
        return ExploreError(ErrorCode.LIVE_EXPLORE_TIMEOUT, err.message, 504)
    return ExploreError(ErrorCode.LIVE_EXPLORE_UPSTREAM_ERROR, err.message, 502)


def _response(result: tavily.TavilySearchResponse, cached: bool, query: str) -> ExploreSearchResponse:
    notes = [NOT_POINT_IN_TIME_NOTE, PUBLISHED_AT_NOTE, SNIPPET_NOTE]
    if result.dropped:
        notes.append(f"{result.dropped} result(s) dropped: missing title, invalid http(s) url, or duplicate url.")
    if not result.items:
        notes.append("Tavily returned no usable results for this query.")
    if cached:
        notes.append(CACHED_NOTE)
    return ExploreSearchResponse(
        query=query,  # this requester's normalized text (a cache hit may come from a differently-cased query)
        retrieved_at=result.retrieved_at,
        cached=cached,
        items=[ExploreSearchItem(**hit.as_dict()) for hit in result.items],
        notes=notes,
    )


@router.get(
    "/explore/search",
    response_model=ExploreSearchResponse,
    responses=_RESPONSES,
    dependencies=[Depends(require_admin_in_public_mode)],
    summary="LIVE EXPLORE web search (Tavily): current, not point-in-time; never used by the Blind Replay",
)
async def explore_search(
    request: Request,
    state: Annotated[ExploreState, Depends(get_explore_state)],
    transport: Annotated[httpx.AsyncBaseTransport | None, Depends(get_tavily_transport)],
    q: Annotated[str, Query(description=f"Search text, 1-{MAX_QUERY_CHARS} characters after trimming.")],
    max_results: Annotated[int, Query(ge=1, le=MAX_RESULTS)] = DEFAULT_MAX_RESULTS,
) -> ExploreSearchResponse:
    if len(request.query_params.getlist("q")) > 1:
        raise _validation(["query", "q"], "q must be given once", "q_repeated")
    query = tavily.normalize_query(q)
    if not query:
        raise _validation(["query", "q"], "q is empty", "q_empty")
    if len(query) > MAX_QUERY_CHARS:
        raise _validation(["query", "q"], f"q is longer than {MAX_QUERY_CHARS} characters", "q_too_long")

    if not tavily.key_configured():
        raise _unavailable(tavily.TavilyErrorKind.NOT_CONFIGURED,
                           "Live Explore unavailable: TAVILY_API_KEY is not set on this API server.")

    client_host = request.client.host if request.client else "unknown"
    wait = state.limiter.take(client_host)
    if wait is not None:
        raise ExploreError(ErrorCode.RATE_LIMITED,
                           f"Too many Live Explore searches from this address (limit {RATE_LIMIT_PER_MIN}/minute).",
                           429, headers={"Retry-After": str(wait)})

    key = (query.casefold(), max_results)
    hit = state.cached(key)
    if hit is not None:
        return _response(hit, cached=True, query=query)

    try:
        client = tavily.client_from_env(transport=transport, timeout_s=TAVILY_TIMEOUT_S)
        result = await client.search(query, max_results=max_results)
    except tavily.TavilyError as err:
        logger.warning("Live Explore search failed: %s (status %s)", err.kind.value, err.status)
        mapped = _from_tavily(err)
    else:
        state.store(key, result)
        return _response(result, cached=False, query=query)
    raise mapped  # outside the except block: no exception chain
