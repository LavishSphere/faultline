"""LIVE EXPLORE chat web_search through an LLM provider's server-side web search (#214). LIVE EXPLORE ONLY.

The chat's ``web_search`` tool runs on FAULTLINE's backend whatever chat model asked for it (OpenRouter models too):
the route calls ``search()`` here, which makes one search request to the configured provider and returns the same
result shape as the Tavily path, so the chat UI's source cards work unchanged.

- **Anthropic** (``claude-sonnet-5-5`` with the ``web_search_20250305`` server tool, ``max_uses`` 3). Results are the
  ``web_search_tool_result`` blocks (url, title, page_age). A result's ``snippet`` is ONLY the ``cited_text`` of the
  citations Claude attached to its text blocks for that url: Anthropic documents ``cited_text`` as text quoted from the
  page, so snippets are verbatim page quotes. Claude's own prose is MODEL-WRITTEN and is returned separately as
  ``summary`` (``summary_label`` says so); ``agents/explore_chat.py`` drops it before the figure check, so a figure
  found only in the summary withholds the reply. ``pause_turn`` is resumed at most twice.
- **OpenAI** (Responses API, ``web_search`` tool). Results are the ``url_citation`` annotations (url, title). OpenAI
  gives no verbatim page text, so a result's snippet is the span of OpenAI's answer that cites it, labelled
  MODEL-WRITTEN (``snippet_label``); the figure check drops those snippets and only titles count.

Every failure raises ``WebSearchError`` with a kind (never a provider error body, which can quote the key); no
placeholder results are ever returned. Walls: imports nothing from the Blind Replay (no gate, store, evaluator,
provenance hashing or replay data), and only ``agents/explore_*`` / ``routes/explore_chat.py`` may import it
(tests/test_explore_separation.py matches ``agents.explore_``).
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal
from urllib.parse import urlsplit

import anthropic
import openai

from agents.explore_chat import ClientFactory

logger = logging.getLogger(__name__)

ANTHROPIC_SEARCH_MODEL = "claude-sonnet-5-5"
# web_search_20250305, not _20260209: live on 2026-11-14 the _20260209 version ran its dynamic filtering through code
# execution and returned text with NO citations (so no verbatim snippets) in ~20 s; _20250305 returned cited_text
# for 5 of 8 results in ~9 s. Billed per search, so max_uses stays at 3.
ANTHROPIC_SEARCH_TOOL = {"type": "web_search_20250305", "name": "web_search", "max_uses": 3}
OPENAI_SEARCH_MODEL = "gpt-4.1-mini"
OPENAI_SEARCH_TOOL = {"type": "web_search"}
SEARCH_MAX_TOKENS = 1500
SEARCH_TIMEOUT_S = 30.0  # the whole search, pause_turn resumes included
MAX_PAUSE_RESUMES = 2
DEFAULT_MAX_RESULTS = 8
SNIPPET_MAX_CHARS = 1200
TITLE_MAX_CHARS = 300
SUMMARY_MAX_CHARS = 2500

SEARCH_SYSTEM = ("Search the web for the user's query and quote the most relevant facts with citations. Prefer "
                 "recent, primary and reputable sources. Keep it short: a few sentences, every fact cited. Do not "
                 "add facts or figures that are not in the pages you found.")
SUMMARY_LABEL = "MODEL-WRITTEN search summary"
OPENAI_SNIPPET_LABEL = "MODEL-WRITTEN (OpenAI's answer text citing this page; not a page quote)"
ATTRIBUTION = {"anthropic": "Search by Anthropic Claude web search", "openai": "Search by OpenAI web search"}
NOTE = {"anthropic": "Current web pages, not point-in-time evidence; snippets are verbatim page quotes (Anthropic "
                     "cited_text). published_date is the page age Anthropic reports, when it has one.",
        "openai": "Current web pages, not point-in-time evidence; snippets are model-written (OpenAI), not page "
                  "quotes, so only titles count as sources for figures."}

# Which backend the chat's web_search uses: FAULTLINE_WEB_SEARCH_PROVIDER = auto|anthropic|openai|tavily. auto (the
# default, and any unknown value) = tavily if TAVILY_API_KEY is set, else anthropic, else openai. A forced provider
# whose key is unset means no web_search at all (never a silent switch to another provider). Kept here, not in
# config.py, because the replay side imports config.py and must not name Tavily (routes/integrity.py scan).
PROVIDER_ENV = "FAULTLINE_WEB_SEARCH_PROVIDER"
PROVIDER_ORDER = ("tavily", "anthropic", "openai")
PROVIDER_KEY_ENV = {"tavily": "TAVILY_API_KEY", "anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY"}


def provider_from_env() -> str | None:
    """The web_search backend this process would use now (environment read per call): a name, or None."""
    def has_key(name: str) -> bool:
        return bool(os.environ.get(PROVIDER_KEY_ENV[name], "").strip())

    choice = os.environ.get(PROVIDER_ENV, "").strip().lower()
    if choice in PROVIDER_ORDER:
        return choice if has_key(choice) else None
    return next((p for p in PROVIDER_ORDER if has_key(p)), None)


Provider = Literal["anthropic", "openai"]
ErrorKind = Literal["timeout", "auth", "rate_limited", "bad_request", "network", "upstream", "no_results"]

_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
_WS = re.compile(r"\s+")


class WebSearchError(Exception):
    """A failed search. Only the kind is kept (``str()`` is a plain message), never the provider's error body."""

    def __init__(self, kind: ErrorKind, message: str) -> None:
        super().__init__(message)
        self.kind = kind


@dataclass(frozen=True)
class WebSearchResult:
    provider: Provider
    query: str
    retrieved_at: datetime
    results: tuple[dict[str, Any], ...]  # {title, url, domain, published_date, snippet[, snippet_label]}
    summary: str

    def as_summary(self, provenance: str) -> dict[str, Any]:
        """The tool-result shape the chat UI and the model see (the Tavily path's keys plus summary/summary_label)."""
        return {"provenance": provenance, "retrieved_at": self.retrieved_at.isoformat(), "query": self.query,
                "results": [dict(r) for r in self.results], "attribution": ATTRIBUTION[self.provider],
                "note": NOTE[self.provider], "summary": self.summary, "summary_label": SUMMARY_LABEL}


def _clean(value: Any, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    text = _WS.sub(" ", _CONTROL.sub(" ", value)).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _http_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    url = value.strip()
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not parts.netloc or " " in url or _CONTROL.search(url):
        return None
    return url


def _domain(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


def _get(obj: Any, name: str) -> Any:
    return obj.get(name) if isinstance(obj, dict) else getattr(obj, name, None)


class _Results:
    """Ordered, de-duplicated results; cited ones first in the output."""

    def __init__(self) -> None:
        self.by_url: dict[str, dict[str, Any]] = {}
        self.cited: list[str] = []
        self.quotes: dict[str, list[str]] = {}

    def add(self, url: Any, title: Any, published: Any = None) -> str | None:
        clean = _http_url(url)
        if clean is None:
            return None
        if clean not in self.by_url:
            self.by_url[clean] = {"title": _clean(title, TITLE_MAX_CHARS) or _domain(clean), "url": clean,
                                  "domain": _domain(clean), "published_date": _clean(published, 80) or None}
        elif published and not self.by_url[clean]["published_date"]:
            self.by_url[clean]["published_date"] = _clean(published, 80) or None
        return clean

    def cite(self, url: str, quote: str) -> None:
        if url not in self.cited:
            self.cited.append(url)
        quote = _clean(quote, SNIPPET_MAX_CHARS)
        if quote and quote not in self.quotes.setdefault(url, []):
            self.quotes[url].append(quote)

    def build(self, max_results: int, snippet_label: str | None) -> tuple[dict[str, Any], ...]:
        order = [*self.cited, *(u for u in self.by_url if u not in self.cited)]
        out = []
        for url in order[:max_results]:
            item = {**self.by_url[url], "snippet": _clean(" … ".join(self.quotes.get(url, [])), SNIPPET_MAX_CHARS)}
            if snippet_label is not None:
                item["snippet_label"] = snippet_label
            out.append(item)
        return tuple(out)


# --------------------------------------------------------------------------- Anthropic


def parse_anthropic(contents: list[Any], max_results: int = DEFAULT_MAX_RESULTS) -> tuple[tuple[dict, ...], str]:
    """Results (from web_search_tool_result blocks and web citations) and the MODEL-WRITTEN prose, from the content
    blocks of every response of one search (a paused turn's blocks, then the resumed ones)."""
    results = _Results()
    prose: list[str] = []
    for block in contents:
        kind = _get(block, "type")
        if kind == "web_search_tool_result":
            content = _get(block, "content")
            if isinstance(content, list):  # else a WebSearchToolResultError (error_code): no results from it
                for hit in content:
                    if _get(hit, "type") == "web_search_result":
                        results.add(_get(hit, "url"), _get(hit, "title"), _get(hit, "page_age"))
            else:
                logger.warning("chat web_search: Anthropic search error %s", _get(content, "error_code"))
        elif kind == "text":
            prose.append(_get(block, "text") or "")
            for cite in _get(block, "citations") or []:
                if _get(cite, "type") != "web_search_result_location":
                    continue
                url = results.add(_get(cite, "url"), _get(cite, "title"))
                if url is not None:
                    results.cite(url, _get(cite, "cited_text") or "")
    return results.build(max_results, None), _clean("".join(prose), SUMMARY_MAX_CHARS)


async def _anthropic_search(query: str, factory: ClientFactory, max_results: int) -> tuple[tuple[dict, ...], str]:
    client = factory.anthropic().with_options(timeout=SEARCH_TIMEOUT_S, max_retries=0)
    messages: list[dict[str, Any]] = [{"role": "user", "content": f"Search query: {query}"}]
    contents: list[Any] = []
    for attempt in range(MAX_PAUSE_RESUMES + 1):
        resp = await client.messages.create(model=ANTHROPIC_SEARCH_MODEL, max_tokens=SEARCH_MAX_TOKENS,
                                            system=SEARCH_SYSTEM, tools=[ANTHROPIC_SEARCH_TOOL], messages=messages)
        contents.extend(resp.content)
        if resp.stop_reason != "pause_turn":
            break
        if attempt == MAX_PAUSE_RESUMES:
            logger.warning("chat web_search: Anthropic still paused after %d resumes; using what it returned",
                           MAX_PAUSE_RESUMES)
            break
        # Resume as documented: send the paused assistant turn back, no extra "continue" user message.
        messages.append({"role": "assistant", "content": resp.content})
    return parse_anthropic(contents, max_results)


# --------------------------------------------------------------------------- OpenAI


def _cited_span(text: str, start: Any, end: Any) -> str:
    """The text an annotation supports. OpenAI's annotated range is usually the inline link itself, so the sentence
    in front of it is taken; the range is used when nothing precedes it."""
    if not (isinstance(start, int) and isinstance(end, int) and 0 <= start <= end <= len(text)):
        return ""
    dot = text.rfind(". ", 0, start)
    lead = text[dot + 2 if dot >= 0 else 0:start].strip()
    return lead or text[start:end]


def parse_openai(output: list[Any], max_results: int = DEFAULT_MAX_RESULTS) -> tuple[tuple[dict, ...], str]:
    """Results from the url_citation annotations of the Responses API output; each snippet is the cited span of
    OpenAI's own text (MODEL-WRITTEN)."""
    results = _Results()
    prose: list[str] = []
    for item in output:
        if _get(item, "type") != "message":
            continue
        for part in _get(item, "content") or []:
            if _get(part, "type") != "output_text":
                continue
            text = _get(part, "text") or ""
            prose.append(text)
            for ann in _get(part, "annotations") or []:
                if _get(ann, "type") != "url_citation":
                    continue
                url = results.add(_get(ann, "url"), _get(ann, "title"))
                if url is None:
                    continue
                results.cite(url, _cited_span(text, _get(ann, "start_index"), _get(ann, "end_index")))
    return results.build(max_results, OPENAI_SNIPPET_LABEL), _clean("".join(prose), SUMMARY_MAX_CHARS)


async def _openai_search(query: str, factory: ClientFactory, max_results: int) -> tuple[tuple[dict, ...], str]:
    client = factory.openai_compatible("openai").with_options(timeout=SEARCH_TIMEOUT_S, max_retries=0)
    resp = await client.responses.create(model=OPENAI_SEARCH_MODEL, instructions=SEARCH_SYSTEM,
                                         input=f"Search query: {query}", tools=[OPENAI_SEARCH_TOOL],
                                         max_output_tokens=SEARCH_MAX_TOKENS)
    return parse_openai(list(resp.output or []), max_results)


# --------------------------------------------------------------------------- entry point


def _kind(err: Exception) -> ErrorKind:
    if isinstance(err, anthropic.APITimeoutError | openai.APITimeoutError | TimeoutError):
        return "timeout"
    if isinstance(err, anthropic.APIConnectionError | openai.APIConnectionError):
        return "network"
    status = getattr(err, "status_code", None)
    if status in (401, 403):
        return "auth"
    if status == 429:
        return "rate_limited"
    if status in (400, 404, 422):
        return "bad_request"
    return "upstream"


async def search(provider: Provider, query: str, factory: ClientFactory, *, max_results: int = DEFAULT_MAX_RESULTS,
                 clock: Callable[[], datetime] | None = None) -> WebSearchResult:
    """One web search through ``provider``. Raises WebSearchError on any failure or when nothing was found."""
    run = _anthropic_search if provider == "anthropic" else _openai_search
    failure: WebSearchError | None = None
    found: tuple[tuple[dict, ...], str] = ((), "")
    try:
        async with asyncio.timeout(SEARCH_TIMEOUT_S):
            found = await run(query, factory, max_results)
    except Exception as err:  # noqa: BLE001 - every failure becomes a kind; the provider body is never kept
        failure = WebSearchError(_kind(err), f"Web search failed ({_kind(err)}).")
    # Raised outside the except block, so no exception chain links back to the request (which holds the key).
    if failure is not None:
        raise failure
    results, summary = found
    if not results:
        raise WebSearchError("no_results", "The web search returned no sources.")
    return WebSearchResult(provider=provider, query=query, retrieved_at=(clock or (lambda: datetime.now(UTC)))(),
                           results=results, summary=summary)


__all__ = ["ANTHROPIC_SEARCH_MODEL", "ANTHROPIC_SEARCH_TOOL", "MAX_PAUSE_RESUMES", "OPENAI_SEARCH_MODEL",
           "OPENAI_SNIPPET_LABEL", "SUMMARY_LABEL", "WebSearchError", "WebSearchResult", "parse_anthropic",
           "parse_openai", "provider_from_env", "search"]
