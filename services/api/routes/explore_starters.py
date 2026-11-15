"""LIVE EXPLORE chat starter questions from current business news (#223). LIVE EXPLORE ONLY.

``GET /api/explore/chat/starters`` returns up to 4 decision questions a board or executive team faces now, each
written by a Claude model from a real news story it found with Anthropic's server-side web search in one call.

Honesty:
- Every starter's ``source_url`` must be one of the urls in that call's ``web_search_tool_result`` blocks (exact
  match after trimming a trailing slash), or the starter is dropped. ``source_title`` and ``published_date`` come
  from the search result (title, and the page age Anthropic reports, as YYYY-MM-DD when it parses; a relative
  age is counted from the search day), never from the model. ``headline`` is the
  model's copy of the title only when it overlaps the search result's title; otherwise the search title is used.
- Questions are validated (Pydantic): a "Should ...?" decision of at most 90 characters, a known tag, and no
  accusatory word ("fraud", "illegal", ...) unless the headline itself uses it. Bad items are dropped; fewer than 2
  survivors is 503 STARTERS_UNAVAILABLE (the UI falls back to static questions). Never a placeholder starter.

Caching: in process memory on ``app.state``; a good result is served for FAULTLINE_STARTERS_TTL_S (default 6 h).
One refresh at a time (single-flight): visitors during a refresh get the stale result. With no result yet, the visitor
whose request starts a refresh waits for it; anyone who arrives while it runs gets 503 STARTERS_UNAVAILABLE at once
with ``Retry-After: 15`` (the UI shows its standard questions and asks again). A failed refresh keeps the last good
result and is not retried for 15 minutes.

Warm-up (#234): at API startup a background task runs the same single-flight refresh, so the first visitor after a
restart does not wait ~10 s for the web search. It never blocks startup or /api/health, needs ANTHROPIC_API_KEY, obeys
the same daily cap and budget, and is on by default in public mode only. FAULTLINE_STARTERS_WARM=1 / 0 forces it on /
off; it is always off under pytest.
Cost: at most 4 refresh attempts per UTC day, and each refresh's estimated spend (tokens x Anthropic list price,
plus searches) is added to the chat's daily budget; no refresh starts once that budget is spent.

Walls: imports nothing from the Blind Replay; tests/test_explore_separation.py lists this module as a Live Explore
importer.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, FastAPI, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from agents import explore_chat as chat
from agents import explore_web_search as web
from config import Settings, get_settings
from models import ErrorCode
from routes import CodedRoute, RouteError, RouteErrorBody
from routes import explore_chat as chat_routes

logger = logging.getLogger(__name__)

STARTERS_MODEL = web.ANTHROPIC_SEARCH_MODEL
STARTERS_TOOL = {"type": "web_search_20250305", "name": "web_search", "max_uses": 4}
STARTERS_MAX_TOKENS = 3000
REFRESH_TIMEOUT_S = 120.0
MAX_PAUSE_RESUMES = 2
MAX_STARTERS = 4
MIN_STARTERS = 2
QUESTION_MAX_CHARS = 90
DEFAULT_TTL_S = 6 * 3600
TTL_ENV = "FAULTLINE_STARTERS_TTL_S"
FAILURE_RETRY_S = 15 * 60
WARM_ENV = "FAULTLINE_STARTERS_WARM"
WARMING_RETRY_AFTER_S = 15
MAX_REFRESHES_PER_DAY = 4
MAX_AGE_DAYS = 45  # a dated search result older than this is not "current" news
WEB_SEARCH_USD = 0.01  # Anthropic web search list price: $10 per 1,000 searches

LABEL = "Questions written by a model from current news; check the source"
WARMING_MESSAGE = ("Current-news starter questions are being prepared. Nothing was made up; use the standard "
                   "questions for now.")
UNAVAILABLE_MESSAGE = ("Current-news starter questions are not available right now. Nothing was made up; use the "
                       "standard questions instead.")
Tag = Literal["Leadership", "M&A", "Strategy", "Governance", "Workforce"]

# Accusatory words a question may use only when the headline itself does (no allegation beyond the headline).
_ACCUSATORY = re.compile(r"\b(fraud\w*|illegal\w*|crim\w*|guilty|lie[ds]?|lying|scam\w*|cover-?up\w*|corrupt\w*|"
                         r"embezzl\w*|brib\w*|launder\w*|steal\w*|stole\w*|cheat\w*|misconduct|harass\w*|abus\w*)\b",
                         re.IGNORECASE)
_WORD = re.compile(r"[a-z0-9]+")

SYSTEM = ("You find current business news and turn it into neutral decision questions for an executive-decision "
          "tool. You only use facts from pages you found with web search. Your final answer is a single JSON "
          "object and nothing else.")


def build_prompt(today: date) -> str:
    since = today - timedelta(days=30)
    return (
        f"Today is {today.isoformat()}. Use web search to find 4 different real news stories published since "
        f"{since.isoformat()} about business leadership and strategy at named companies: CEO or leadership changes, "
        "governance disputes or scandals, mergers and acquisitions, layoffs or restructuring, entering or exiting a "
        "market, activist investor campaigns. Use 4 different companies and mix the topics.\n\n"
        "For each story write one decision question the company's board or executive team faces right now.\n"
        "Rules:\n"
        f"- question: at most {QUESTION_MAX_CHARS} characters, starts with \"Should\", ends with \"?\", names the "
        "company, and is a neutral decision (for example \"Should Acme's board accept the activist's two seats?\").\n"
        "- Do not state any allegation or wrongdoing as fact; say only what the headline says. Never name private "
        "individuals; refer to executives by role.\n"
        "- headline: the article's title exactly as the search result shows it.\n"
        "- source_url: the exact URL of a search result you retrieved for that story. Never invent or edit a URL.\n"
        "- published_date: YYYY-MM-DD if the page shows it, else null.\n"
        "- tag: one of Leadership, M&A, Strategy, Governance, Workforce.\n\n"
        "Reply with ONLY this JSON, no prose and no markdown:\n"
        '{"starters": [{"question": "...", "headline": "...", "source_url": "https://...", '
        '"published_date": "YYYY-MM-DD", "tag": "Leadership"}]}'
    )


# --------------------------------------------------------------------------- validation


class ModelStarter(BaseModel):
    """One item as the model wrote it. Anything that fails is dropped, never repaired into something plausible."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    question: str = Field(min_length=12, max_length=QUESTION_MAX_CHARS)
    headline: str = Field(default="", max_length=400)
    source_url: str = Field(min_length=8, max_length=2000)
    tag: Tag

    @field_validator("question")
    @classmethod
    def _decision(cls, value: str) -> str:
        if not value.startswith("Should ") or not value.endswith("?") or "\n" in value:
            raise ValueError("question must be a 'Should ...?' decision on one line")
        return value


class Starter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(description="A decision question (at most 90 characters), MODEL-WRITTEN from the story.")
    headline: str = Field(description="The article's title (from the web search result).")
    source_title: str = Field(description="The search result's title, as Anthropic web search returned it.")
    source_url: str = Field(description="A url that appeared in this refresh's web search results.")
    domain: str
    published_date: str | None = Field(description=(
        "From the page age Anthropic web search reports: YYYY-MM-DD when it is a date or 'N days ago' (counted from "
        "the search day), else its text as given; null if none. Never from the model."))
    tag: Tag


class StartersResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provenance: str = Field(description='"REAL (web, retrieved <UTC>)": when FAULTLINE ran the search.')
    generated_at: datetime
    label: str
    starters: list[Starter]


def _norm_url(url: str) -> str:
    return url.strip().rstrip("/")


def _words(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if len(w) > 2}


def _headline(model_headline: str, search_title: str) -> str:
    """The model's headline only if most of its words are in the search result's title; else the search title."""
    mine, theirs = _words(model_headline), _words(search_title)
    if mine and theirs and len(mine & theirs) / len(mine) >= 0.6:
        return model_headline
    return search_title


_RELATIVE = re.compile(r"^(\d{1,4}) (hour|day|week|month)s? ago$", re.IGNORECASE)
_RELATIVE_DAYS = {"hour": 0, "day": 1, "week": 7, "month": 30}


def _parse_page_age(value: str | None, today: date) -> date | None:
    """A page age as a date: absolute ("November 3, 2026", ISO) or relative to the search day ("5 days ago")."""
    if not value:
        return None
    text = value.strip()
    rel = _RELATIVE.match(text)
    if rel:
        return today - timedelta(days=int(rel.group(1)) * _RELATIVE_DAYS[rel.group(2).lower()])
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%Y-%m-%d", "%d %B %Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _final_text(contents: list[Any]) -> str:
    """The model's text after its last web search (earlier text is narration between searches)."""
    last_search = max((i for i, b in enumerate(contents)
                       if web._get(b, "type") in ("server_tool_use", "web_search_tool_result")), default=-1)
    return "".join(web._get(b, "text") or "" for b in contents[last_search + 1:] if web._get(b, "type") == "text")


def _json_object(text: str) -> dict[str, Any] | None:
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        value = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def build_starters(contents: list[Any], today: date) -> list[Starter]:
    """Validated starters from the content blocks of one search call (paused turns included)."""
    found, _ = web.parse_anthropic(
        [b for b in contents if web._get(b, "type") == "web_search_tool_result"], max_results=10_000)
    by_url = {_norm_url(r["url"]): r for r in found}
    raw = _json_object(_final_text(contents))
    items = raw.get("starters") if raw else None
    if not isinstance(items, list):
        logger.warning("starters: the model did not return a starters list")
        return []
    out: list[Starter] = []
    seen: set[str] = set()
    for item in items:
        try:
            ms = ModelStarter.model_validate(item)
        except ValidationError:
            logger.info("starters: dropped an item that failed validation")
            continue
        hit = by_url.get(_norm_url(ms.source_url))
        if hit is None:
            logger.info("starters: dropped an item whose source_url was not in the search results")
            continue
        if hit["url"] in seen:
            continue
        headline = _headline(ms.headline, hit["title"])
        accused = {w.lower() for w in _ACCUSATORY.findall(ms.question)}
        if accused - {w.lower() for w in _ACCUSATORY.findall(f"{headline} {hit['title']}")}:
            logger.info("starters: dropped a question with an accusation the headline does not make")
            continue
        published = _parse_page_age(hit["published_date"], today)
        if published is not None and (published > today + timedelta(days=1)
                                      or (today - published).days > MAX_AGE_DAYS):
            logger.info("starters: dropped a story outside the current-news window")
            continue
        seen.add(hit["url"])
        out.append(Starter(question=ms.question, headline=headline, source_title=hit["title"], source_url=hit["url"],
                           domain=hit["domain"], tag=ms.tag,
                           published_date=published.isoformat() if published else hit["published_date"]))
        if len(out) == MAX_STARTERS:
            break
    return out


# --------------------------------------------------------------------------- the provider call


@dataclass(frozen=True)
class Fetched:
    contents: list[Any]
    input_tokens: int
    output_tokens: int
    searches: int


async def fetch_news(factory: chat.ClientFactory, today: date) -> Fetched:
    """One Anthropic call with web_search (pause_turn resumed at most twice). Raises on any provider failure."""
    client = factory.anthropic().with_options(timeout=REFRESH_TIMEOUT_S, max_retries=0)
    messages: list[dict[str, Any]] = [{"role": "user", "content": build_prompt(today)}]
    contents: list[Any] = []
    tokens_in = tokens_out = searches = 0
    for attempt in range(MAX_PAUSE_RESUMES + 1):
        resp = await client.messages.create(model=STARTERS_MODEL, max_tokens=STARTERS_MAX_TOKENS, system=SYSTEM,
                                            tools=[STARTERS_TOOL], messages=messages)
        contents.extend(resp.content)
        usage = resp.usage
        tokens_in += getattr(usage, "input_tokens", 0) or 0
        tokens_out += getattr(usage, "output_tokens", 0) or 0
        stu = getattr(usage, "server_tool_use", None)
        searches += getattr(stu, "web_search_requests", 0) or 0
        if resp.stop_reason != "pause_turn" or attempt == MAX_PAUSE_RESUMES:
            break
        messages.append({"role": "assistant", "content": resp.content})
    return Fetched(contents, tokens_in, tokens_out, searches)


def estimated_cost_usd(f: Fetched) -> float:
    prices = {m[0]: (m[2], m[3]) for m in chat.ANTHROPIC_MODELS}
    pin, pout = prices.get(STARTERS_MODEL, (20.0, 100.0))  # unknown model: a deliberately high estimate
    return (f.input_tokens * pin + f.output_tokens * pout) / 1_000_000 + f.searches * WEB_SEARCH_USD


# --------------------------------------------------------------------------- cache + single flight


@dataclass(frozen=True)
class Snapshot:
    response: StartersResponse
    fetched_at: float  # monotonic


Fetcher = Callable[[date], Awaitable[Fetched]]


def ttl_from_env() -> float:
    try:
        value = float(os.environ.get(TTL_ENV, "").strip() or DEFAULT_TTL_S)
    except ValueError:
        return DEFAULT_TTL_S
    return max(60.0, value)


class StartersState:
    def __init__(self, clock: Callable[[], float] = time.monotonic,
                 wall: Callable[[], datetime] = lambda: datetime.now(UTC), ttl_s: float | None = None) -> None:
        self.clock = clock
        self.wall = wall
        self.ttl_s = ttl_from_env() if ttl_s is None else ttl_s
        self.good: Snapshot | None = None
        self.last_failure_at: float | None = None
        self.task: asyncio.Task[None] | None = None
        self.refresh_day: str | None = None
        self.refreshes_today = 0
        self.provider_calls = 0  # total, for tests and logs

    @property
    def warming(self) -> bool:
        """True while a refresh runs and there is no result to serve yet."""
        return self.good is None and self.task is not None and not self.task.done()

    def _fresh(self) -> bool:
        return self.good is not None and self.clock() - self.good.fetched_at < self.ttl_s

    def _may_start(self, budget_left: bool) -> bool:
        if not budget_left:
            return False
        if self.last_failure_at is not None and self.clock() - self.last_failure_at < FAILURE_RETRY_S:
            return False
        today = self.wall().date().isoformat()
        if self.refresh_day != today:
            self.refresh_day, self.refreshes_today = today, 0
        return self.refreshes_today < MAX_REFRESHES_PER_DAY

    async def _refresh(self, fetch: Fetcher, on_cost: Callable[[float], None]) -> None:
        self.refreshes_today += 1
        self.provider_calls += 1
        now = self.wall()
        try:
            async with asyncio.timeout(REFRESH_TIMEOUT_S + 10):
                fetched = await fetch(now.date())
        except Exception as err:  # noqa: BLE001 - logged by kind only; a provider error body can quote the key
            logger.warning("starters: refresh failed (%s)", type(err).__name__)
            self.last_failure_at = self.clock()
            return
        try:
            on_cost(estimated_cost_usd(fetched))
        except Exception:  # noqa: BLE001 - accounting must never break the refresh
            logger.warning("starters: could not record spend")
        starters = build_starters(fetched.contents, now.date())
        if len(starters) < MIN_STARTERS:
            logger.warning("starters: refresh produced %d valid starters; keeping the last good result",
                           len(starters))
            self.last_failure_at = self.clock()
            return
        self.last_failure_at = None
        self.good = Snapshot(StartersResponse(provenance=chat_routes.web_label(now), generated_at=now, label=LABEL,
                                              starters=starters), self.clock())

    async def get(self, fetch: Fetcher, *, budget_left: bool = True,
                  on_cost: Callable[[float], None] = lambda _usd: None) -> StartersResponse | None:
        """The cached response (refreshing it when stale, one refresh at a time), or None when there is none."""
        if self._fresh():
            return self.good.response  # type: ignore[union-attr]
        task = self.task
        if task is not None and (task.done() or task.get_loop() is not asyncio.get_running_loop()):
            task = self.task = None  # finished, or orphaned on a loop that is gone
        started = False
        if task is None and self._may_start(budget_left):
            task = self.task = asyncio.create_task(self._refresh(fetch, on_cost))
            started = True
        if self.good is not None:
            return self.good.response  # stale while the refresh runs (or while refreshes are capped)
        if task is not None and started:
            await asyncio.shield(task)  # this request started it; later arrivals get None at once (self.warming)
        return self.good.response if self.good is not None else None

    def warm(self, fetch: Fetcher, *, budget_left: bool = True,
             on_cost: Callable[[float], None] = lambda _usd: None) -> asyncio.Task[None] | None:
        """Start the single-flight refresh in the background (startup warm-up); never waits. None if not started."""
        if self._fresh() or (self.task is not None and not self.task.done()):
            return None
        if not self._may_start(budget_left):
            return None
        self.task = asyncio.create_task(self._refresh(fetch, on_cost))
        return self.task


def _state_of(app: Any) -> StartersState:
    state = getattr(app.state, "faultline_starters", None)
    if state is None:
        state = StartersState()
        app.state.faultline_starters = state
    return state


def get_starters_state(request: Request) -> StartersState:
    return _state_of(request.app)


def get_starters_clients() -> chat.ClientFactory:
    """Dependency hook: the real network. Tests override it with an httpx2.MockTransport for anthropic."""
    return chat.ClientFactory()


def _chat_state_of(app: Any) -> chat_routes.ChatState:
    state = getattr(app.state, "faultline_chat", None)
    if state is None:
        state = chat_routes.ChatState()
        app.state.faultline_chat = state
    return state


def _budget(app: Any, settings: Settings) -> tuple[bool, Callable[[float], None]]:
    """(budget left?, spend recorder): the chat's daily budget pays for starter refreshes too."""
    chat_state = _chat_state_of(app)

    def on_cost(usd: float) -> None:
        chat_state.spent_today()
        chat_state.spent_usd += usd

    return chat_state.spent_today() < settings.chat_daily_budget_usd, on_cost


def warm_enabled(mode: str, environ: Mapping[str, str]) -> bool:
    """Startup warm-up switch: never under pytest; FAULTLINE_STARTERS_WARM=1/0 forces it; default on in public mode."""
    if "PYTEST_CURRENT_TEST" in environ:
        return False
    flag = environ.get(WARM_ENV, "").strip()
    if flag in ("0", "1"):
        return flag == "1"
    return mode == "public"


def schedule_warm(app: FastAPI, settings: Settings) -> asyncio.Task[None] | None:
    """Schedule the startup refresh as a background task (needs ANTHROPIC_API_KEY). Returns it, or None."""
    if not chat.ClientFactory.key("anthropic"):
        logger.info("starters: warm-up skipped (no ANTHROPIC_API_KEY)")
        return None
    factory = app.dependency_overrides.get(get_starters_clients, get_starters_clients)()
    budget_left, on_cost = _budget(app, settings)
    task = _state_of(app).warm(lambda today: fetch_news(factory, today), budget_left=budget_left, on_cost=on_cost)
    if task is not None:
        logger.info("starters: warm-up refresh scheduled")
    return task


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """FastAPI lifespan: warm the starters cache in the background; cancel an unfinished refresh on shutdown."""
    settings = get_settings()
    if warm_enabled(settings.mode, os.environ):
        schedule_warm(app, settings)
    yield
    task = getattr(getattr(app.state, "faultline_starters", None), "task", None)
    if task is not None and not task.done():
        task.cancel()


router = APIRouter(route_class=CodedRoute, tags=["live-explore"])


@router.get("/explore/chat/starters", response_model=StartersResponse,
            responses={503: {"model": RouteErrorBody, "description": "STARTERS_UNAVAILABLE"}},
            summary="LIVE EXPLORE chat: starter questions written by a model from current news")
async def chat_starters(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    state: Annotated[StartersState, Depends(get_starters_state)],
    clients: Annotated[chat.ClientFactory, Depends(get_starters_clients)],
) -> StartersResponse:
    if not chat.ClientFactory.key("anthropic"):
        raise RouteError(ErrorCode.STARTERS_UNAVAILABLE, "Current-news starter questions need ANTHROPIC_API_KEY on "
                         "this server. Nothing was made up; use the standard questions instead.", 503)
    budget_left, on_cost = _budget(request.app, settings)
    result = await state.get(lambda today: fetch_news(clients, today), budget_left=budget_left, on_cost=on_cost)
    if result is None and state.warming:
        raise RouteError(ErrorCode.STARTERS_UNAVAILABLE, WARMING_MESSAGE, 503,
                         headers={"Retry-After": str(WARMING_RETRY_AFTER_S)})
    if result is None:
        raise RouteError(ErrorCode.STARTERS_UNAVAILABLE, UNAVAILABLE_MESSAGE, 503)
    return result


__all__ = ["LABEL", "Starter", "StartersResponse", "StartersState", "build_prompt", "build_starters", "fetch_news",
           "get_starters_clients", "get_starters_state", "lifespan", "router", "schedule_warm", "warm_enabled"]
