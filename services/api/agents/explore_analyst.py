"""LIVE EXPLORE analyst (issue #61): Tavily results -> local model -> cited evidence + a SUGGESTED stress scenario.

Live Explore only. Like ``agents/tavily.py``, this module is reachable only from ``routes/explore.py``;
``tests/test_explore_separation.py`` fails if a Blind Replay module references it. It reads nothing from the replay
side: no ``EvidenceItem``, temporal gate, prediction store, outcome vault, demo cases or sealed outcome files.
Its only data file is the finance owner's ILLUSTRATIVE guidance, ``data/explore_shock_guidance.json`` (#79).

What the model sees (``render_prompt``), as ONE user message with no system prompt, no tools and no date:
fixed instructions; the decision text the human typed; the guidance category menu with each parameter's range
(modelling choices, not facts about the world); and the Tavily results of this request (id, url, title,
Tavily's published-date string, snippet). Nothing else: the Tavily results are its only evidence.

What comes back is a PROPOSAL, checked here before anyone sees it:

- ``AnalystOutput`` is the required JSON shape (strict, no extra keys). Bad JSON or shape gets one schema-repair
  turn (same prompt plus a fixed instruction), then ``ModelOutputInvalid``. A down / missing model raises
  ``ModelUnavailable``. No path invents an answer.
- ``review_claims`` is the skeptic for evidence: a claim is kept only if it has visible text within
  ``CLAIM_MAX_CHARS``, its ``source_url`` is EXACTLY one of the URLs Tavily returned for this request, and any
  URL written inside the claim is also one of them. Everything else is rejected with a reason (never repaired).
  Cards carry Tavily's snippet, title and ``retrieved_at``, never model text in their place.
- ``build_suggestion`` turns the model's numbers into ``ScenarioShock`` INPUTS: only the blocks the chosen
  category lists; each value clamped to that category's ``[min, max]`` (weeks rounded to integers), a missing or
  non-numeric value replaced by the guidance default, and every window, recovery included, ended by week T.
  Each parameter says where its value came from (``model`` / ``model_clamped`` / ``guidance_default``). The
  numbers are labeled MODEL-SUGGESTED, HUMAN TO CONFIRM: the human edits and confirms them, and only then does the
  deterministic engine (``/api/simulate``) compute anything. The model never computes a result.

Prompt injection: a snippet can contain instructions. The guards above bound what that can do: the model can only
cite URLs Tavily returned, its numbers are clamped to guidance ranges, and a human confirms before the engine runs.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import time
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from agents.local_ollama import LocalOllamaProvider
from agents.provider import ModelOutputInvalid, ModelUnavailable, has_visible_text, summarize_validation_error
from core.financials import DemandShock, RateShock, ScenarioShock, SupplierOutage

GUIDANCE_FILE = "explore_shock_guidance.json"
SUGGESTION_LABEL = "MODEL-SUGGESTED, HUMAN TO CONFIRM"
# Used instead when the model gave no usable number at all: every value is the ILLUSTRATIVE guidance default.
DEFAULTS_LABEL = "GUIDANCE DEFAULTS, HUMAN TO CONFIRM"
DEFAULTS_NOTE = "The model gave no usable numbers; these are guidance defaults."

MAX_CLAIMS = 6
CLAIM_MAX_CHARS = 300
PARAM_RATIONALE_MAX_CHARS = 240
MAX_MODEL_ITEMS = 20  # evidence list length the schema accepts at all (extra claims beyond MAX_CLAIMS are rejected)
REJECTED_TEXT_MAX_CHARS = 300  # how much of a rejected claim / url is echoed back for display
ANALYST_NUM_PREDICT = 1024  # answer budget: up to six claims plus a rationale per parameter
# Context window for Live Explore. The installed llama3.1:8b supports 131072; 16384 fits five 1200-character
# snippets, the category menu and a repair turn (the replay provider keeps its own 8192 default).
ANALYST_NUM_CTX = 16384
MAX_ATTEMPTS = 2

Block = Literal["rate", "demand", "supplier"]
ParamKind = Literal["rate", "fraction", "week", "count", "count0"]
ValueSource = Literal["model", "model_clamped", "guidance_default"]
RejectReason = Literal[
    "uncited", "unknown_url", "unknown_url_in_text", "number_not_in_source", "hidden_characters", "provenance_label",
    "empty_claim",
    "claim_too_long", "duplicate", "over_limit"
]

# Parameters per shock block and their kind (MATH_MODEL §1; the guidance file's `units`).
PARAM_KINDS: dict[str, dict[str, ParamKind]] = {
    "rate": {"delta_rate": "rate", "start_week": "week"},
    "demand": {"delta": "fraction", "start_week": "week", "duration_weeks": "count", "recovery_weeks": "count0"},
    "supplier": {
        "availability_during_outage": "fraction",
        "start_week": "week",
        "duration_weeks": "count",
        "dependent_share": "fraction",
    },
}
INTEGER_KINDS = frozenset({"week", "count", "count0"})
RATE_HARD_BOUND = 0.1  # |Δr| a guidance file may name at all (±1000bp); the categories use far less

_URL_IN_TEXT = re.compile(r"https?://[^\s<>\"')\]]+", re.IGNORECASE)
# After NFKC folding: any scheme (javascript:, data:, ftp://, hxxps://), and any host-like token (evil.com,
# www.evil.com). A host-like token is allowed only if it is (a suffix of) a host Tavily returned.
_SCHEME = re.compile(r"(?<![a-z0-9])(?:[a-z][a-z0-9+.-]*://|(?:javascript|data|vbscript|file|blob):)", re.IGNORECASE)
_HOST_LIKE = re.compile(r"(?<![\w@.-])(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,24}(?![\w-])", re.IGNORECASE)
# Numeric tokens: 50, 0.25, 1,200, 3.5. Every one in a claim must appear in the cited result's snippet or title.
_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
# Live Explore is never REAL HISTORICAL or RECORDED RUN; model text that names those labels could spoof one.
_PROVENANCE_LABEL = re.compile(r"real[\s_-]*historical|recorded[\s_-]*run", re.IGNORECASE)


# --------------------------------------------------------------------------- guidance (ILLUSTRATIVE, #79)


class ParamRange(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    min: float
    default: float
    max: float
    worse_when: Literal["higher", "lower"] | None

    @model_validator(mode="after")
    def _ordered(self) -> ParamRange:
        values = (self.min, self.default, self.max)
        if not all(math.isfinite(v) for v in values) or not self.min <= self.default <= self.max:
            raise ValueError("expected finite min <= default <= max")
        return self


class GuidanceCategory(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    id: str
    name: str
    news_trigger: str
    timing_guidance: str
    rationale: str
    basis: str
    provenance: Literal["ILLUSTRATIVE"]
    shocks: dict[Block, dict[str, ParamRange]]


class Guidance(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    provenance: Literal["ILLUSTRATIVE"]
    label: str
    horizon_weeks: int = Field(ge=1)
    units: dict[str, str]
    categories: list[GuidanceCategory]

    @model_validator(mode="after")
    def _params_valid(self) -> Guidance:
        T = self.horizon_weeks
        ids = [c.id for c in self.categories]
        if not ids or len(set(ids)) != len(ids):
            raise ValueError("category ids must be present and unique")
        for c in self.categories:
            if not c.shocks:
                raise ValueError(f"{c.id}: no shock blocks")
            for block, params in c.shocks.items():
                if set(params) != set(PARAM_KINDS[block]):
                    raise ValueError(f"{c.id}.{block}: parameters must be exactly {sorted(PARAM_KINDS[block])}")
                for name, r in params.items():
                    lo, hi = _hard_bounds(PARAM_KINDS[block][name], T)
                    if r.min < lo or r.max > hi:
                        raise ValueError(f"{c.id}.{block}.{name}: range outside [{lo}, {hi}]")
        return self

    def category(self, category_id: str) -> GuidanceCategory | None:
        return next((c for c in self.categories if c.id == category_id), None)


class GuidanceInvalid(Exception):
    """The guidance file is missing or fails its schema. The route reports DATA_UNAVAILABLE / DATA_INVALID."""

    def __init__(self, message: str, *, missing: bool = False) -> None:
        super().__init__(message)
        self.missing = missing


def _hard_bounds(kind: ParamKind, horizon: int) -> tuple[float, float]:
    return {
        "rate": (-RATE_HARD_BOUND, RATE_HARD_BOUND),
        "fraction": (0.0, 1.0),
        "week": (1.0, float(horizon)),
        "count": (1.0, float(horizon)),
        "count0": (0.0, float(horizon)),
    }[kind]


def load_guidance(data_dir: Path) -> Guidance:
    path = Path(data_dir) / GUIDANCE_FILE
    if not path.is_file():
        raise GuidanceInvalid(f"{GUIDANCE_FILE} is missing from the data directory.", missing=True)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GuidanceInvalid(f"{GUIDANCE_FILE} could not be read as JSON ({type(exc).__name__}).") from None
    try:
        return Guidance.model_validate(raw)
    except ValidationError as exc:
        problems = "; ".join(summarize_validation_error(exc)[:3])
        raise GuidanceInvalid(f"{GUIDANCE_FILE} failed its schema: {problems}") from None


# --------------------------------------------------------------------------- the prompt


@dataclass(frozen=True)
class PromptSource:
    """One Tavily result exactly as it is shown to the model."""

    source_id: str
    url: str
    title: str
    snippet: str
    published_at_raw: str | None

    def as_dict(self) -> dict[str, Any]:
        return {"source_id": self.source_id, "url": self.url, "title": self.title, "snippet": self.snippet,
                "published_at_raw": self.published_at_raw}


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sources_sha256(sources: Sequence[PromptSource]) -> str:
    """SHA256 of canonical JSON of the exact source list given to the model."""
    return sha256_text(_canonical([s.as_dict() for s in sources]))


def _one_line(text: str) -> str:
    return " ".join(text.split())


def _fmt(v: float) -> str:
    return f"{v:g}"


def _category_menu(guidance: Guidance) -> str:
    lines = []
    for c in guidance.categories:
        lines.append(f'- "{c.id}": {_one_line(c.news_trigger)}')
        for block, params in c.shocks.items():
            lines.append(f'    block "{block}":')
            for name, r in params.items():
                kind = PARAM_KINDS[block][name]
                integer = ", whole weeks" if kind in INTEGER_KINDS else ""
                lines.append(
                    f'        parameter "{name}": from {_fmt(r.min)} to {_fmt(r.max)} (typical {_fmt(r.default)}'
                    f"{integer})"
                )
    return "\n".join(lines)


def _units(guidance: Guidance) -> str:
    names = sorted({n for params in PARAM_KINDS.values() for n in params})
    return "\n".join(f"- {n}: {_one_line(guidance.units[n])}" for n in names if n in guidance.units)


PROMPT_TEMPLATE = """\
LIVE EXPLORE. A person is stress-testing a business decision against today's news.
Use ONLY the SOURCES below. Do not use any other knowledge. If the sources do not support a claim, do not make it.

DECISION (written by the person):
{decision}

SOURCES (web search results, numbered S1, S2, ...):
{sources}

TASK
1. Evidence: write up to {max_claims} short factual claims that the SOURCES state directly. Each claim is one \
sentence of at most {claim_chars} characters. Put the exact url of the ONE source that states it in \
"source_url", copied character for character from the SOURCES. Never cite anything else.
2. Category: choose the ONE category id below that best matches the news in the SOURCES, or null if none fits.
3. Parameters: for the chosen category only, suggest a value for each parameter listed under it, inside its range, \
each with a one-line rationale of at most {rationale_chars} characters. These are stress-test inputs that a human \
will review and edit; they are not forecasts.

CATEGORIES (id: when it applies; then its blocks, and each parameter's allowed range)
{menu}

PARAMETER UNITS
{units}

Answer with exactly one JSON object and nothing else, with exactly these keys:
{{"evidence": [{{"claim": "...", "source_url": "..."}}], "category_id": "<id>" or null, "parameters": {{...}}}}

"parameters" is nested: block name, then parameter name, then an object with "value" (a number) and "rationale". \
Use the block names (rate, demand, supplier) as the keys of "parameters". Do not put the category id inside \
"parameters", and do not join names with dots. The shape, with placeholders in angle brackets:
"parameters": {{
  "<block>": {{
    "<parameter>": {{"value": <number>, "rationale": "<one line>"}},
    "<parameter>": {{"value": <number>, "rationale": "<one line>"}}
  }}
}}"""


def render_prompt(decision_text: str, sources: Sequence[PromptSource], guidance: Guidance) -> str:
    """The complete and only model input. Deterministic for the same decision, sources and guidance."""
    blocks = []
    for s in sources:
        published = s.published_at_raw if s.published_at_raw else "not given"
        snippet = s.snippet if s.snippet else "(no snippet)"
        blocks.append(f"[{s.source_id}] url: {s.url}\ntitle: {s.title}\npublished (as given by the search "
                      f"provider): {published}\nsnippet: {snippet}")
    return PROMPT_TEMPLATE.format(
        decision=decision_text,
        sources="\n\n".join(blocks),
        max_claims=MAX_CLAIMS,
        claim_chars=CLAIM_MAX_CHARS,
        rationale_chars=PARAM_RATIONALE_MAX_CHARS,
        menu=_category_menu(guidance),
        units=_units(guidance),
    )


REPAIR_INSTRUCTION = (
    "\n\n---\nA previous answer to the request above was not valid. Problems:\n{problems}\n"
    'Answer again with exactly one JSON object and nothing else, with exactly the keys "evidence" (a list of '
    '{{"claim", "source_url"}} objects), "category_id" (a category id or null) and "parameters" (an object).'
)


def repair_instruction(problems: Sequence[str]) -> str:
    lines = [" ".join(str(p).splitlines()) for p in problems] or ["the answer was not one JSON object"]
    return REPAIR_INSTRUCTION.format(problems="\n".join(f"- {line}" for line in lines))


# --------------------------------------------------------------------------- the model's answer (shape only)


class ModelClaim(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    claim: str
    source_url: str | None = None


class ModelParam(BaseModel):
    """`value` is kept as sent (any JSON); build_suggestion decides whether it is a usable number."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    value: Any = None
    rationale: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _bare_value(cls, data: Any) -> Any:
        # A bare number (`"delta_rate": 0.005`) is read as {"value": 0.005} with no rationale.
        return data if isinstance(data, dict) else {"value": data}


class AnalystOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence: list[ModelClaim] = Field(max_length=MAX_MODEL_ITEMS)
    category_id: str | None = None
    # Any JSON object: the model's nesting varies (block -> param, "block.param", or wrapped in the category id).
    # normalize_parameters reads it; values are never trusted until clamped by build_suggestion.
    parameters: dict[str, Any] = Field(default_factory=dict)


@dataclass(frozen=True)
class AnalystRun:
    output: AnalystOutput
    agent_model: str
    model_tag: str
    model_digest: str | None
    temperature: float
    seed: int | None
    attempts: int
    final_prompt: str
    raw_output_sha256: str
    latency_ms: int


class ExploreAnalyst(LocalOllamaProvider):
    """The local Ollama model (#40's provider: same request shape, no-truncation checks and error mapping), asked
    for an ``AnalystOutput`` instead of a replay forecast. Stateless between calls."""

    @classmethod
    def for_explore(cls, settings: Any, *, transport: httpx.AsyncBaseTransport | None = None) -> ExploreAnalyst:
        return cls(settings.ollama_base_url, settings.ollama_model, transport=transport,
                   num_ctx=ANALYST_NUM_CTX, num_predict=ANALYST_NUM_PREDICT)

    async def analyze(self, prompt: str) -> AnalystRun:
        """Raises ModelUnavailable, ModelOutputInvalid, PromptTooLong or PromptNotVerified; never a stand-in."""
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("prompt must be a non-empty string")
        self.precheck(prompt)
        failure: str | None = None
        try:
            return await self._analyze(prompt)
        except (httpx.HTTPError, httpx.InvalidURL) as exc:
            failure = _describe(exc)
        # Outside the except block: no chained httpx exception (its text can echo the configured URL).
        raise ModelUnavailable(failure)

    async def _analyze(self, prompt: str) -> AnalystRun:
        started = time.perf_counter()
        raw_outputs: list[str] = []
        problems: list[str] = []
        user_message = prompt
        floor = 0
        client_args = {"base_url": self.base_url, "timeout": self._timeout, "transport": self._transport}
        async with httpx.AsyncClient(**client_args) as client:
            digest = await self._installed_digest_checked(client)
            for attempt in range(1, MAX_ATTEMPTS + 1):
                body = await self._chat_checked(client, user_message)
                count = self._verify_prompt_seen(body, user_message, floor)
                message = body.get("message")
                content = message.get("content") if isinstance(message, dict) else None
                raw = content if isinstance(content, str) else ""
                raw_outputs.append(raw)
                output: AnalystOutput | None = None
                try:
                    output = AnalystOutput.model_validate_json(raw)
                except ValidationError as exc:
                    problems = summarize_validation_error(exc)
                if output is None:
                    if attempt < MAX_ATTEMPTS:
                        instruction = repair_instruction(problems)
                        user_message = prompt + instruction
                        self.precheck(user_message)
                        floor = count + len(instruction.encode("utf-8")) // 8
                    continue
                return AnalystRun(
                    output=output,
                    agent_model=f"{self.provider_id}/{self.model}",
                    model_tag=self.model,
                    model_digest=digest,
                    temperature=self.temperature,
                    seed=self.seed,
                    attempts=attempt,
                    final_prompt=user_message,
                    raw_output_sha256=sha256_text(raw),
                    latency_ms=round((time.perf_counter() - started) * 1000),
                )
        raise ModelOutputInvalid(
            f"The local model's answer failed validation after {MAX_ATTEMPTS} attempts (one schema repair).",
            raw_outputs=raw_outputs,
            problems=problems,
        )

    async def _installed_digest_checked(self, client: httpx.AsyncClient) -> str | None:
        try:
            return await self._installed_digest(client)
        except ValueError:  # /api/tags body is not JSON
            failure = "Ollama /api/tags returned a response that is not valid JSON."
        raise ModelUnavailable(failure)

    async def _chat_checked(self, client: httpx.AsyncClient, user_message: str) -> dict[str, Any]:
        try:
            return await self._chat(client, user_message)
        except ValueError:  # /api/chat body is not JSON
            failure = "Ollama /api/chat returned a response that is not valid JSON."
        raise ModelUnavailable(failure)


def _describe(exc: Exception) -> str:
    if isinstance(exc, httpx.TimeoutException):
        return f"Ollama at OLLAMA_BASE_URL timed out ({type(exc).__name__})."
    if isinstance(exc, httpx.HTTPStatusError):
        return f"Ollama returned HTTP {exc.response.status_code} for {exc.request.url.path}."
    if isinstance(exc, httpx.InvalidURL):
        return "OLLAMA_BASE_URL is not a valid URL (InvalidURL)."
    if isinstance(exc, httpx.TransportError):
        return f"Ollama not reachable at OLLAMA_BASE_URL ({type(exc).__name__})."
    return f"Ollama request failed ({type(exc).__name__})."


# --------------------------------------------------------------------------- skeptic: evidence claims


@dataclass(frozen=True)
class AcceptedClaim:
    claim: str
    source: PromptSource


@dataclass(frozen=True)
class RejectedClaim:
    claim: str
    source_url: str | None
    reason: RejectReason
    message: str


_REJECT_MESSAGES: dict[str, str] = {
    "uncited": "No source_url: every claim must cite one Tavily result returned for this request.",
    "unknown_url": "source_url is not exactly one of the URLs Tavily returned for this request.",
    "unknown_url_in_text": "The claim names a URL, link scheme or web domain that Tavily did not return.",
    "number_not_in_source": "The claim states a number that the cited result's snippet and title do not contain.",
    "hidden_characters": "The claim contains invisible formatting characters (zero-width or bidirectional controls).",
    "provenance_label": "The claim names a FAULTLINE provenance label (REAL HISTORICAL / RECORDED RUN).",
    "empty_claim": "The claim has no visible text.",
    "claim_too_long": f"The claim is longer than {CLAIM_MAX_CHARS} characters.",
    "duplicate": "The same claim and source were already accepted.",
    "over_limit": f"More than {MAX_CLAIMS} cited claims; only the first {MAX_CLAIMS} are kept.",
}


def _shorten(text: str | None) -> str | None:
    if text is None:
        return None
    return text if len(text) <= REJECTED_TEXT_MAX_CHARS else text[: REJECTED_TEXT_MAX_CHARS - 1] + "…"


def _has_format_chars(text: str) -> bool:
    return any(unicodedata.category(ch) == "Cf" for ch in text)


def _fold(text: str) -> str:
    """NFKC (full-width letters, ligatures -> ASCII forms) with invisible format characters (Cf) removed."""
    return "".join(ch for ch in unicodedata.normalize("NFKC", text) if unicodedata.category(ch) != "Cf")


def _host(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def _mask_offered_urls(text: str, offered: Iterable[str]) -> tuple[str, list[str]]:
    """(text with every offered URL blanked out, URLs in the text that were NOT offered)."""
    offered_set = set(offered)
    unknown: list[str] = []
    masked = text
    for m in _URL_IN_TEXT.finditer(text):
        raw = m.group(0).rstrip(".,;:")
        candidates = (raw, raw + ")")  # a url ending in ")" (e.g. wiki/Foo_(bar)) is cut by the pattern
        hit = next((u for u in candidates if u in offered_set and text.find(u, m.start()) == m.start()), None)
        if hit is None:
            unknown.append(raw)
        else:
            masked = masked[: m.start()] + " " * len(hit) + masked[m.start() + len(hit):]
    return masked, unknown


def _unknown_urls_in(text: str, offered: Iterable[str]) -> list[str]:
    """URLs, link schemes and host-like tokens in ``text`` (NFKC-folded, Cf removed) that Tavily did not return.

    An offered URL written in full is fine; a host-like token (``reuters.com``) is fine only when it is the host of
    a returned URL (``www.`` ignored)."""
    offered = list(offered)
    folded = _fold(text)
    masked, unknown = _mask_offered_urls(folded, offered)
    hosts = {_host(u) for u in offered}
    unknown += [m.group(0) for m in _SCHEME.finditer(masked)]
    for m in _HOST_LIKE.finditer(masked):
        token = m.group(0).lower()
        token = token[4:] if token.startswith("www.") else token
        if token not in hosts:
            unknown.append(m.group(0))
    return unknown


_SOURCE_ID_TOKEN = re.compile(r"(?<![\w])[Ss]\d{1,2}(?![\w])")


def _numbers(text: str) -> set[str]:
    return {t.replace(",", "") for t in _NUMBER.findall(text)}


def numbers_not_in_source(claim: str, source: PromptSource, offered: Iterable[str]) -> list[str]:
    """Numeric tokens of the claim that the cited result's snippet and title do not contain (B2: a valid citation
    must not carry an invented figure). Offered URLs, host names and source ids (S1) in the claim are not figures."""
    masked, _ = _mask_offered_urls(_fold(claim), offered)
    # Host names (news0.example) are not figures either; an unreturned one is refused by the URL check first.
    masked = _HOST_LIKE.sub(" ", _SOURCE_ID_TOKEN.sub(" ", masked))
    in_source = _numbers(_fold(source.snippet)) | _numbers(_fold(source.title))
    return sorted({t.replace(",", "") for t in _NUMBER.findall(masked)} - in_source)


def review_claims(claims: Sequence[ModelClaim], sources: Sequence[PromptSource]) -> tuple[
    list[AcceptedClaim], list[RejectedClaim]
]:
    """Keep each claim that cites, exactly, a URL Tavily returned; reject everything else with a reason.

    Never edits a claim. A URL match is exact after trimming surrounding whitespace (no trailing-slash, scheme or
    case normalization: a near miss is not the source that was returned). After NFKC folding, the claim may name no
    other URL, link scheme or web domain, and every number in it must appear in the cited result's snippet or
    title (a real citation must not carry an invented figure). Invisible format characters are refused outright.
    Limits: numbers written as words ("fifty") and paraphrase are not checked; a human reads the snippet.
    """
    by_url = {s.url: s for s in sources}
    offered = set(by_url)
    accepted: list[AcceptedClaim] = []
    rejected: list[RejectedClaim] = []
    seen: set[tuple[str, str]] = set()

    def reject(c: ModelClaim, reason: RejectReason) -> None:
        rejected.append(RejectedClaim(claim=_shorten(c.claim) or "", source_url=_shorten(c.source_url),
                                      reason=reason, message=_REJECT_MESSAGES[reason]))

    for c in claims:
        text = c.claim.strip()
        url = c.source_url.strip() if isinstance(c.source_url, str) else ""
        if not has_visible_text(text):
            reject(c, "empty_claim")
        elif _has_format_chars(text):
            reject(c, "hidden_characters")
        elif _PROVENANCE_LABEL.search(_fold(text)):
            reject(c, "provenance_label")
        elif len(text) > CLAIM_MAX_CHARS:
            reject(c, "claim_too_long")
        elif not url:
            reject(c, "uncited")
        elif url not in offered:
            reject(c, "unknown_url")
        elif _unknown_urls_in(text, offered):
            reject(c, "unknown_url_in_text")
        elif numbers_not_in_source(text, by_url[url], offered):
            reject(c, "number_not_in_source")
        elif (text, url) in seen:
            reject(c, "duplicate")
        elif len(accepted) >= MAX_CLAIMS:
            reject(c, "over_limit")
        else:
            seen.add((text, url))
            accepted.append(AcceptedClaim(claim=text, source=by_url[url]))
    return accepted, rejected


# --------------------------------------------------------------------------- suggestion: clamp + map to ScenarioShock


class SuggestedParameter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    block: Block
    param: str
    unit: str = Field(description="Units, from the guidance file.")
    integer: bool = Field(description="Whole weeks.")
    value: float = Field(description="The INPUT value after clamping to [min, max]; edited by the human.")
    min: float
    default: float
    max: float
    worse_when: Literal["higher", "lower"] | None
    source: ValueSource = Field(
        description="model = the model's number, inside the range; model_clamped = the model's number moved into "
        "the range (or rounded to a whole week); guidance_default = the model gave no usable number."
    )
    model_value: float | None = Field(description="The finite number the model sent, before clamping; else null.")
    rationale: str | None = Field(description="The model's one-line rationale (MODEL-WRITTEN), or null.")
    note: str | None = None


class Suggestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: Literal["MODEL-SUGGESTED, HUMAN TO CONFIRM", "GUIDANCE DEFAULTS, HUMAN TO CONFIRM"] = Field(
        description="MODEL-SUGGESTED only when at least one value came from the model (source model or "
        "model_clamped); otherwise GUIDANCE DEFAULTS: every value is the ILLUSTRATIVE guidance default."
    )
    values_from_model: int = Field(description="How many parameters took the model's number (source model or "
                                   "model_clamped). 0 = none: the numbers are guidance defaults, not the model's.")
    category_id: str
    category_name: str
    parameters: list[SuggestedParameter]
    shock: ScenarioShock = Field(
        description="The parameters mapped exactly as the guidance file's mapping_to_scenario_shock. An INPUT for "
        "POST /api/simulate after the human confirms; nothing has been simulated."
    )
    notes: list[str]


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    try:
        v = float(value)
    except OverflowError:  # a JSON integer too large for a float (e.g. 10**400) is not a usable number
        return None
    return v if math.isfinite(v) else None


_PARAM_SHAPE_KEYS = frozenset({"value", "rationale"})


def _is_param_object(v: Any) -> bool:
    return isinstance(v, dict) and bool(v) and set(v) <= _PARAM_SHAPE_KEYS


def normalize_parameters(raw: Any, category: GuidanceCategory) -> tuple[dict[str, dict[str, ModelParam]], int]:
    """The model's ``parameters`` object -> {block: {param: ModelParam}} for this category, and how many entries
    were ignored (not a parameter of the category, a duplicate, or not a value/rationale object).

    Accepted shapes, as small models actually answer: nested ``{"rate": {"delta_rate": {...}}}``; dotted
    ``{"rate.delta_rate": {...}}``; either one wrapped in a single key equal to the category id
    (``{"credit-tightening": {...}}``, seen from llama3.1:8b); and a bare parameter name when exactly one block of
    the category has it. Only the shape is normalized: every value is still clamped by ``_clamp_param``.
    Model-written keys are counted, never echoed.
    """
    if not isinstance(raw, dict):
        return {}, 0
    if len(raw) == 1 and category.id in raw and isinstance(raw[category.id], dict):
        raw = raw[category.id]
    out: dict[str, dict[str, ModelParam]] = {}
    ignored = 0

    def put(block: str, name: str, value: Any) -> None:
        nonlocal ignored
        if block not in category.shocks or name not in category.shocks[block] or name in out.get(block, {}):
            ignored += 1
            return
        try:
            out.setdefault(block, {})[name] = ModelParam.model_validate(value)
        except ValidationError:
            ignored += 1

    owners: dict[str, list[str]] = {}
    for block, ranges in category.shocks.items():
        for name in ranges:
            owners.setdefault(name, []).append(block)

    for key, value in raw.items():
        if not isinstance(key, str):
            ignored += 1
        elif "." in key:
            block, _, name = key.partition(".")
            put(block, name, value)
        elif key in category.shocks and isinstance(value, dict) and not _is_param_object(value):
            for inner, inner_value in value.items():
                name = inner if isinstance(inner, str) else ""
                if "." in name:
                    b2, _, n2 = name.partition(".")
                    name = n2 if b2 == key else ""
                put(key, name, inner_value)
        elif len(owners.get(key, [])) == 1:
            put(owners[key][0], key, value)
        else:
            ignored += 1
    return out, ignored


def _clamp_param(block: str, name: str, r: ParamRange, sent: ModelParam | None, unit: str,
                 offered: set[str]) -> SuggestedParameter:
    kind = PARAM_KINDS[block][name]
    integer = kind in INTEGER_KINDS
    model_value = _number(sent.value) if sent is not None else None
    notes: list[str] = []
    if model_value is None:
        value, source = r.default, "guidance_default"
        notes.append("No usable number from the model: guidance default used.")
    else:
        value, source = model_value, "model"
        if integer and value != round(value):
            value = float(round(value))
            source = "model_clamped"
            notes.append(f"Model value {_fmt(model_value)} rounded to whole week {_fmt(value)}.")
        if value < r.min or value > r.max:
            clamped = min(max(value, r.min), r.max)
            notes.append(f"Model value {_fmt(model_value)} clamped to {_fmt(clamped)} (guidance range "
                         f"{_fmt(r.min)} to {_fmt(r.max)}).")
            value, source = clamped, "model_clamped"
    rationale = sent.rationale.strip() if sent is not None and isinstance(sent.rationale, str) else None
    if rationale is not None:
        if not has_visible_text(rationale):
            rationale = None
        elif len(rationale) > PARAM_RATIONALE_MAX_CHARS:
            rationale = None
            notes.append(f"Model rationale dropped: longer than {PARAM_RATIONALE_MAX_CHARS} characters.")
        elif _has_format_chars(rationale) or _PROVENANCE_LABEL.search(_fold(rationale)):
            rationale = None
            notes.append("Model rationale dropped: invisible characters or a provenance label in it.")
        elif _unknown_urls_in(rationale, offered):
            rationale = None
            notes.append("Model rationale dropped: it names a URL that Tavily did not return for this request.")
    if integer:
        value = float(int(value))
    return SuggestedParameter(
        block=block, param=name, unit=unit, integer=integer, value=value, min=r.min, default=r.default, max=r.max,
        worse_when=r.worse_when, source=source, model_value=model_value, rationale=rationale,
        note=" ".join(notes) or None,
    )


def _fit_windows(values: dict[str, dict[str, float]], horizon: int, params: dict[tuple[str, str], SuggestedParameter],
                 notes: list[str]) -> None:
    """End every window, recovery included, by week T (guidance how_to_use). Shortens duration, then recovery."""
    for block in ("demand", "supplier"):
        v = values.get(block)
        if not v:
            continue
        last = v["start_week"] + v["duration_weeks"] - 1
        if last > horizon:
            v["duration_weeks"] = float(horizon - v["start_week"] + 1)
            _retarget(params[(block, "duration_weeks")], v["duration_weeks"], horizon, notes)
        if block == "demand":
            end = v["start_week"] + v["duration_weeks"] - 1 + v["recovery_weeks"]
            if end > horizon:
                v["recovery_weeks"] = float(horizon - (v["start_week"] + v["duration_weeks"] - 1))
                _retarget(params[(block, "recovery_weeks")], v["recovery_weeks"], horizon, notes)


def _retarget(p: SuggestedParameter, value: float, horizon: int, notes: list[str]) -> None:
    msg = f"{p.block}.{p.param} shortened to {_fmt(value)} so the window ends by week {horizon}."
    p.value = value
    p.source = "model_clamped" if p.source != "guidance_default" else p.source
    p.note = f"{p.note} {msg}" if p.note else msg
    notes.append(msg)


def shock_from_values(name: str, values: Mapping[str, Mapping[str, float]], horizon: int) -> ScenarioShock:
    """Guidance ``mapping_to_scenario_shock``: parameter values -> a ScenarioShock (validated by the engine model)."""
    rate = demand = supplier = None
    if "rate" in values:
        v = values["rate"]
        rate = RateShock(delta_rate=v["delta_rate"], start_week=int(v["start_week"]))
    if "demand" in values:
        v = values["demand"]
        start = int(v["start_week"])
        demand = DemandShock(delta=v["delta"], start_week=start, end_week=start + int(v["duration_weeks"]) - 1,
                             recovery_weeks=int(v["recovery_weeks"]))
    if "supplier" in values:
        v = values["supplier"]
        first = int(v["start_week"])
        last = first + int(v["duration_weeks"]) - 1
        kappa = [v["availability_during_outage"] if first <= t <= last else 1.0 for t in range(1, horizon + 1)]
        supplier = SupplierOutage(availability=kappa, dependent_share=v["dependent_share"])
    return ScenarioShock(name=name, rate=rate, demand=demand, supplier=supplier)


def build_suggestion(output: AnalystOutput, guidance: Guidance, sources: Sequence[PromptSource]) -> tuple[
    Suggestion | None, list[str]
]:
    """(suggestion, notes). None when the model chose no category or one that is not in the guidance."""
    if output.category_id is None:
        return None, ["The model matched no guidance category, so there is no suggested scenario. Choose a "
                      "category to start from its guidance defaults."]
    category = guidance.category(output.category_id)
    if category is None:
        return None, ["The model named a category that is not in the guidance file, so there is no suggested "
                      "scenario. Choose a category to start from its guidance defaults."]
    offered = {s.url for s in sources}
    notes: list[str] = []
    sent, ignored = normalize_parameters(output.parameters, category)
    if ignored:
        notes.append(f"Ignored {ignored} parameter(s) not listed for this category.")
    params: dict[tuple[str, str], SuggestedParameter] = {}
    for block, ranges in category.shocks.items():
        for name, r in ranges.items():
            sent_param = sent.get(block, {}).get(name)
            params[(block, name)] = _clamp_param(block, name, r, sent_param, guidance.units.get(name, ""), offered)
    values = {block: {name: params[(block, name)].value for name in ranges}
              for block, ranges in category.shocks.items()}
    _fit_windows(values, guidance.horizon_weeks, params, notes)
    from_model = sum(p.source in ("model", "model_clamped") for p in params.values())
    if not from_model:
        notes.insert(0, DEFAULTS_NOTE)
    kind = "model-suggested" if from_model else "guidance defaults"
    shock = shock_from_values(f"live explore: {category.id} ({kind})", values, guidance.horizon_weeks)
    return Suggestion(label=SUGGESTION_LABEL if from_model else DEFAULTS_LABEL, values_from_model=from_model,
                      category_id=category.id, category_name=category.name, parameters=list(params.values()),
                      shock=shock, notes=notes), []
