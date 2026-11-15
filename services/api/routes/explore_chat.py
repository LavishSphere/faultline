"""LIVE EXPLORE chat (#187): a hosted model answers with numbers only from FAULTLINE engine tool calls.

Routes:
- ``GET  /api/explore/chat/models``: the runtime model catalogue (cached 10 minutes): OpenRouter tool-capable
  models (never its ``openai/*`` / ``anthropic/*`` copies), OpenAI's vetted chat models confirmed by its model list,
  and the Claude models. ``available`` = the provider key is configured (never a key or prefix). Public visitors see
  models whose published output price is at most FAULTLINE_CHAT_MAX_PRICE_PER_MTOK; a valid admin token sees all.
  FAULTLINE_CHAT_MODELS (``provider:model`` list) pins the list instead.
- ``POST /api/explore/chat``: one turn. The model may call the engine tools below for at most
  ``MAX_TOOL_ROUNDS`` rounds; each tool runs the existing route function in-process (never HTTP to itself), and
  ``tool_calls[].input`` is the exact validated request body the engine ran, so POSTing it to /api/simulate or
  /api/optimize reproduces ``result_summary``.
- ``POST /api/explore/chat/stream`` (#222): the same turn (same body, gates, limits and honesty pipeline) as
  server-sent events: ``start``, then live ``round`` / ``tool_call`` / ``tool_result`` steps with server-built
  previews, then ``final`` (the exact POST /api/explore/chat body) or ``error``. Reply text is never streamed: it
  arrives only inside ``final``, after the figure check, so a withheld reply is never shown.
- ``GET  /api/explore/chat/status`` / ``POST /api/explore/chat/pause`` (admin): the presenter pause switch.

Tools: simulate, optimize, decision, list_scenarios, list_judge_challenges, list_decision_frames, vc_lenses, and
web_search (run on this backend for every chat model: Tavily, Anthropic or OpenAI web search per
FAULTLINE_WEB_SEARCH_PROVIDER, see agents/explore_web_search.py; offered only when one is configured; per-IP and
global daily caps for non-admin callers, FAULTLINE_CHAT_WEB_PER_IP_DAY / FAULTLINE_CHAT_WEB_DAILY; results
labelled "REAL (web, retrieved <UTC>)"). Every tool result reaches the model labeled with its
provenance. Nothing here reads replay cases, sealed outcomes, the prediction store or benchmark data, and nothing is
saved: tests/test_explore_separation.py enforces both walls.

Guards for POST /api/explore/chat, in order: access (public mode: admin token unless FAULTLINE_PUBLIC_CHAT=1) ->
body validation (<= 20 messages, <= 4,000 characters each, no extra fields) -> pause (non-admin: 503 PAUSED) ->
per-IP limit FAULTLINE_CHAT_PER_IP turns per 10 minutes (admin bypasses; 429 RATE_LIMITED) -> model in the
catalogue (422) -> provider key configured (503 LIVE_EXPLORE_UNAVAILABLE) -> global concurrency
FAULTLINE_CHAT_CONCURRENCY (503 BUSY) -> the tool loop. Provider failures: 429 RATE_LIMITED (upstream limit),
502 UPSTREAM_ERROR; a rejected key or unknown model is ``status: "unavailable"``; a refusal, a model that misuses the
tools, or a reply with figures and no tool call is ``status: "error"`` with an empty reply and a note. Never a
stand-in answer.

State (limiter, pause, catalogue cache, concurrency) is in process memory on ``app.state`` (the deploy runs one
worker); a restart clears it, including a pause.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from collections import OrderedDict, deque
from collections.abc import AsyncIterator, Callable, Coroutine
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from starlette.requests import Request as StarletteRequest

from agents import explore_chat as chat
from agents import explore_chat_steps as steps
from agents import explore_web_search as web_llm
from agents import tavily
from config import CHAT_WINDOW_S, Settings, admin_token_matches, get_settings, public_chat_enabled
from core.financials import ScenarioShock
from models import ErrorCode
from routes import CodedRoute, RouteError, RouteErrorBody, issues_from, rate_limit_key
from routes import chat_montecarlo as mc
from routes import decision as decision_routes
from routes import internal_data as internal_routes
from routes import judge_challenges as challenge_routes
from routes import optimize as optimize_routes
from routes import research as research_routes
from routes import scenarios as scenario_routes
from routes import simulate as simulate_routes

logger = logging.getLogger(__name__)

MAX_MESSAGES = 20
MAX_MESSAGE_CHARS = 4000
# Body cap for POST /api/explore/chat at the edge (main.py): 20 x 4,000 characters, even if every one is a
# JSON-escaped non-ASCII character (6 bytes), plus envelope.
CHAT_MAX_BODY_BYTES = MAX_MESSAGES * MAX_MESSAGE_CHARS * 6 + 16 * 1024
TURN_TIMEOUT_S = 150.0
DEFAULT_PAUSE_MINUTES = 30
MAX_PAUSE_MINUTES = 120
WEB_RESULTS = 5
MAX_WEB_SEARCHES_PER_TURN = 3  # paid searches (Tavily credits; Anthropic: up to 3 searches each)
TAVILY_TIMEOUT_S = 10.0
BUSY_RETRY_AFTER_S = 5

STANDARD_NOTE = ("MODEL-WRITTEN text. Numbers should come only from the engine tool calls listed with it; the demo "
                 "business is SYNTHETIC. Nothing here is saved, scored, or given to the Blind Replay.")
ADMIN_MESSAGE = ("Admin only on the public demo: the live chat spends paid model credits and needs the admin token "
                 "(Authorization: Bearer <FAULTLINE_ADMIN_TOKEN>), unless the server sets FAULTLINE_PUBLIC_CHAT=1.")
BUDGET_MESSAGE = ("The live chat has used today's model budget on this server, so it is resting until tomorrow "
                  "(UTC). Everything else in FAULTLINE still works.")
PAUSED_MESSAGE = ("The live chat is paused by the presenter for a moment. Everything else in FAULTLINE still works; "
                  "please try the chat again shortly.")


# --------------------------------------------------------------------------- access


def public_mode() -> bool:
    """Fail closed, as routes.replay.public_mode: anything but unset/empty or ``local`` is public."""
    return os.environ.get("FAULTLINE_MODE", "").strip().lower() not in ("", "local")


def _bearer(request: Request) -> str:
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    return token.strip() if scheme.lower() == "bearer" else ""


def is_admin(request: Request) -> bool:
    """A valid admin token (the same token and, in public mode, the same 64-hex format as the replay admin gate)."""
    return admin_token_matches(_bearer(request))


def _admin_error(request: Request) -> RouteError | None:
    if not public_mode():
        return None
    if not _bearer(request):
        return RouteError(ErrorCode.ADMIN_TOKEN_REQUIRED, ADMIN_MESSAGE, status_code=401)
    if not is_admin(request):
        return RouteError(ErrorCode.ADMIN_TOKEN_REQUIRED, ADMIN_MESSAGE, status_code=403)
    return None


def require_chat_access(request: Request) -> None:
    """Public mode: the chat is public only with FAULTLINE_PUBLIC_CHAT=1; otherwise it is admin-only (401/403)."""
    if public_mode() and public_chat_enabled():
        return
    err = _admin_error(request)
    if err is not None:
        raise err


class AdminGatedRoute(CodedRoute):
    """Route-level admin gate (public mode), the defence-in-depth twin of main.AdminGateMiddleware."""

    def get_route_handler(self):  # noqa: ANN201 - same signature as APIRoute
        handler = super().get_route_handler()

        async def gated(request: Request) -> Response:
            err = _admin_error(request)
            if err is not None:
                return err.response()
            return await handler(request)

        return gated


# --------------------------------------------------------------------------- per-app state


class WindowLimiter:
    """At most `limit` events per `window_s` per key (sliding window). LRU-bounded memory."""

    def __init__(self, clock: Callable[[], float], window_s: float = CHAT_WINDOW_S, max_keys: int = 10_000) -> None:
        self.clock = clock
        self.window_s = window_s
        self.max_keys = max_keys
        self._events: OrderedDict[str, deque[float]] = OrderedDict()

    def take(self, key: str, limit: int) -> int | None:
        """None when allowed (and recorded), else seconds until the oldest event leaves the window."""
        now = self.clock()
        events = self._events.pop(key, deque())
        while events and now - events[0] >= self.window_s:
            events.popleft()
        allowed = len(events) < limit
        if allowed:
            events.append(now)
        self._events[key] = events
        while len(self._events) > self.max_keys:
            self._events.popitem(last=False)
        if allowed:
            return None
        return max(1, int(self.window_s - (now - events[0]) + 0.999))


class ChatState:
    def __init__(self, clock: Callable[[], float] = time.monotonic,
                 wall: Callable[[], datetime] = lambda: datetime.now(UTC)) -> None:
        self.clock = clock
        self.wall = wall
        self.limiter = WindowLimiter(clock)
        self.active = 0  # turns running now (single event loop: no lock needed)
        self.paused_until: datetime | None = None
        self.catalog: chat.Catalog | None = None
        self.spend_day: str | None = None  # UTC date the running total belongs to
        self.spent_usd = 0.0  # estimated provider spend today (usage x catalogue price), in process memory
        self.web_day: str | None = None  # UTC date the web_search counters belong to
        self.web_total = 0
        self.web_by_ip: dict[str, int] = {}
        self.stream_tasks: set[asyncio.Task[None]] = set()  # streamed turns still running (#222)

    def spent_today(self) -> float:
        today = self.wall().date().isoformat()
        if self.spend_day != today:
            self.spend_day, self.spent_usd = today, 0.0
        return self.spent_usd

    def record_spend(self, m: chat.CatalogModel, input_tokens: int, output_tokens: int,
                     fallback_per_mtok: float) -> None:
        """Usage x published price; a model with no published price is charged at the public price cap (a
        deliberately high estimate)."""
        self.spent_today()
        pin = m.input_per_mtok if m.input_per_mtok is not None else fallback_per_mtok
        pout = m.output_per_mtok if m.output_per_mtok is not None else fallback_per_mtok
        self.spent_usd += (input_tokens * pin + output_tokens * pout) / 1_000_000

    def web_take(self, ip: str | None, per_ip: int, daily: int) -> str | None:
        """Count one web_search for a non-admin caller (`ip`), or None for an admin (unlimited, not counted).
        Returns why it is refused (per-IP or global daily cap, per UTC day) or None when allowed and counted."""
        if ip is None:
            return None
        today = self.wall().date().isoformat()
        if self.web_day != today:
            self.web_day, self.web_total, self.web_by_ip = today, 0, {}
        if self.web_by_ip.get(ip, 0) >= per_ip:
            return (f"web_search daily limit for this visitor reached ({per_ip} per day); answer from the results "
                    "you already have, or say live sources are unavailable")
        if self.web_total >= daily:
            return ("web_search daily limit for this server reached; answer from the results you already have, or "
                    "say live sources are unavailable")
        self.web_by_ip[ip] = self.web_by_ip.get(ip, 0) + 1
        self.web_total += 1
        return None

    def paused(self) -> datetime | None:
        if self.paused_until is not None and self.wall() >= self.paused_until:
            self.paused_until = None  # auto-expired
        return self.paused_until

    async def get_catalog(self, settings: Settings, factory: chat.ClientFactory) -> chat.Catalog:
        cached = self.catalog
        if cached is not None:
            ttl = chat.CATALOG_FAILURE_TTL_S if cached.failed else chat.CATALOG_TTL_S
            if self.clock() - cached.fetched_at < ttl and cached.pinned == (settings.chat_models_pinned is not None):
                return cached
        self.catalog = await chat.build_catalog(settings, factory)
        self.catalog.fetched_at = self.clock()
        return self.catalog


def get_chat_state(request: Request) -> ChatState:
    state = getattr(request.app.state, "faultline_chat", None)
    if state is None:
        state = ChatState()
        request.app.state.faultline_chat = state
    return state


def get_chat_clients() -> chat.ClientFactory:
    """Dependency hook: the real network. Tests override it with httpx2.MockTransport per provider."""
    return chat.ClientFactory()


def get_chat_tavily_transport() -> httpx.AsyncBaseTransport | None:
    """Dependency hook for web_search: None = the real Tavily API. Tests override it."""
    return None


# --------------------------------------------------------------------------- engine tools

_NULLABLE_INT = {"type": ["integer", "null"]}
SHOCK_SCHEMA: dict[str, Any] = {
    "type": ["object", "null"],
    "description": "A custom shock (null = use scenario_id, or no shock). Omitted blocks = no shock of that kind.",
    "properties": {
        "name": {"type": ["string", "null"], "description": "Optional label for the result."},
        "demand": {
            "type": ["object", "null"],
            "description": "Demand multiplier 1-delta on weeks start_week..end_week, then linear recovery.",
            "properties": {
                "delta": {"type": "number", "description": "Fraction of demand lost, 0..1 (0.2 = -20%)."},
                "start_week": {"type": "integer", "description": "First shocked week, 1..26 (week 1 is the first)."},
                "end_week": {"type": "integer", "description": "Last shocked week, start_week..26."},
                "recovery_weeks": {**_NULLABLE_INT, "description": "Weeks of linear recovery after end_week."},
            },
            "required": ["delta", "start_week", "end_week", "recovery_weeks"],
            "additionalProperties": False,
        },
        "rate": {
            "type": ["object", "null"],
            "description": "Annual interest-rate rise from start_week (0.02 = +200bp).",
            "properties": {"delta_rate": {"type": "number"},
                           "start_week": {"type": "integer", "description": "1..26 (week 1 is the first)."}},
            "required": ["delta_rate", "start_week"],
            "additionalProperties": False,
        },
        "supplier": {
            "type": ["object", "null"],
            "description": "Primary-supplier outage.",
            "properties": {
                "availability": {
                    "type": "array", "items": {"type": "number"},
                    "description": "Supplier availability per week, 0..1, exactly one entry per week of the 26-week "
                                   "horizon (entry 1 = week 1); 1 = normal, 0 = nothing delivered.",
                },
                "dependent_share": {"type": "number", "description": "Share of sales that depend on it, 0..1."},
            },
            "required": ["availability", "dependent_share"],
            "additionalProperties": False,
        },
    },
    "required": ["name", "demand", "rate", "supplier"],
    "additionalProperties": False,
}
_SCENARIO_ID = {"type": ["string", "null"],
                "description": "Id from list_scenarios or list_judge_challenges; its exact shock is used."}


def _schema(properties: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


ENGINE_TOOLS: tuple[chat.ToolSpec, ...] = (
    chat.ToolSpec("simulate", "Run the deterministic weekly cash simulation of the SYNTHETIC demo business under a "
                  "shock (no recovery actions). Give scenario_id OR shock. Returns SIMULATED cash numbers.",
                  _schema({"scenario_id": _SCENARIO_ID, "shock": SHOCK_SCHEMA})),
    chat.ToolSpec("optimize", "Find the least-harmful recovery plan (MILP) for a shock. Payroll protection is a hard "
                  "rule: pass protect_payroll=true. Returns OPTIMAL plan or NO FEASIBLE PLAN, SIMULATED.",
                  _schema({"scenario_id": _SCENARIO_ID, "shock": SHOCK_SCHEMA,
                           "protect_payroll": {"type": "boolean"}})),
    chat.ToolSpec("decision", "Evaluate ACT / WAIT / HEDGE for a decision frame at a probability of YES. Returns "
                  "SIMULATED payoffs (lowest cash) and the engine's recommendation.",
                  _schema({"frame_id": {"type": "string", "description": "Id from list_decision_frames."},
                           "p_yes": {"type": "number", "description": "Probability of YES, 0..1: the user's own "
                                     "number, or 0.5 as a neutral placeholder (say so) when they give none."}})),
    chat.ToolSpec("list_scenarios", "List the named stress scenarios (SYNTHETIC) with their exact shocks.",
                  _schema({})),
    chat.ToolSpec("list_judge_challenges", "List the ILLUSTRATIVE judge challenges with their exact shocks.",
                  _schema({})),
    chat.ToolSpec("list_decision_frames", "List the ILLUSTRATIVE ACT / WAIT / HEDGE decision frames.", _schema({})),
    chat.ToolSpec("vc_lenses", "Curated public VC research lenses (REAL HISTORICAL writing; never scored). as_of "
                  "(ISO-8601 instant) keeps only lenses provably public by then; null = all.",
                  _schema({"as_of": {"type": ["string", "null"]}})),
)


@dataclass(frozen=True)
class NamedShock:
    id: str
    name: str
    kind: Literal["scenario", "challenge"]
    shock: ScenarioShock


def normalize_scenario_key(text: str) -> str:
    """Lenient key for a model-typed id or name: case-folded, quotes dropped, runs of spaces/underscores/dashes
    -> one dash. "Bad_Quarter", "bad quarter" and "BAD-QUARTER" all give "bad-quarter"."""
    key = text.strip().strip("'\"`").casefold()
    return re.sub(r"[\s_\-]+", "-", key).strip("-")


# scenario_id strings that mean null (seen from deepseek-v3.2 in the #195 baseline: "null", "None", "none", "").
NULL_SCENARIO_KEYS = frozenset({"", "null", "none", "nil"})


def match_named(text: str, named: list[NamedShock]) -> list[NamedShock]:
    """Every named shock whose id, full name, or name before a colon ("Bad quarter: ...") matches `text`
    leniently; a challenge also matches without its "judge-" prefix. More than one hit = ambiguous."""
    key = normalize_scenario_key(text)
    if not key:
        return []
    hits = []
    for n in named:
        keys = {normalize_scenario_key(n.id), normalize_scenario_key(n.name),
                normalize_scenario_key(n.name.split(":", 1)[0])}
        if n.id.startswith("judge-"):
            keys.add(normalize_scenario_key(n.id.removeprefix("judge-")))
        if key in keys:
            hits.append(n)
    return hits


def _scenario_id_schema(named: list[NamedShock]) -> dict[str, Any]:
    scenarios = "; ".join(f"{n.id} ({n.name})" for n in named if n.kind == "scenario")
    challenges = "; ".join(f"{n.id} ({n.name})" for n in named if n.kind == "challenge")
    # anyOf, not {"type": ["string", "null"], "enum": [..., null]}: Anthropic's strict tool schemas reject the
    # latter with a 400 (seen live 2026-11-14), while every provider here accepts this form.
    return {
        "anyOf": [{"type": "string", "enum": [n.id for n in named]}, {"type": "null"}],
        "description":("A named shock: its exact engine shock is used, so there is no need to call list_scenarios "
                        "or list_judge_challenges first. null = use `shock` instead. Named scenarios (SYNTHETIC): "
                        f"{scenarios or 'none'}. Judge's Challenges (ILLUSTRATIVE): {challenges or 'none'}."),
    }


def _engine_tools(named: list[NamedShock]) -> tuple[chat.ToolSpec, ...]:
    """ENGINE_TOOLS with scenario_id an enum of the loaded ids, each listed with its name in the description."""
    sid = _scenario_id_schema(named)
    hint = (" For a named scenario or Judge's Challenge (e.g. 'the bad quarter'), pass its scenario_id from the "
            "list in that parameter and shock=null.")
    out = []
    for spec in ENGINE_TOOLS:
        if spec.name in ("simulate", "optimize"):
            props = {**spec.parameters["properties"], "scenario_id": sid}
            spec = chat.ToolSpec(spec.name, spec.description + hint, {**spec.parameters, "properties": props})
        out.append(spec)
    return tuple(out)


def _with_frame_ids(tools: tuple[chat.ToolSpec, ...], frames: list[tuple[str, str]]) -> tuple[chat.ToolSpec, ...]:
    """decision's frame_id as an enum of the loaded frames, each listed with its question (#195: models skipped
    the decision tool or listed frames first). A plain string enum: no null, so Anthropic strict tools accept it."""
    listed = "; ".join(f"{fid} ({question})" for fid, question in frames)
    frame_id = {"type": "string", "enum": [fid for fid, _ in frames],
                "description": f"The decision frame; no need to call list_decision_frames first. Frames: {listed}."}
    out = []
    for spec in tools:
        if spec.name == "decision":
            props = {**spec.parameters["properties"], "frame_id": frame_id}
            spec = chat.ToolSpec(spec.name, spec.description, {**spec.parameters, "properties": props})
        out.append(spec)
    return tuple(out)


WEB_SEARCH_TOOL = chat.ToolSpec(
    "web_search", "Search the current public web for facts about real companies, people, markets and "
    "events. Results are REAL web pages retrieved now (current, not point-in-time). Cite each fact with its source "
    "name, date and url from the results, and quote figures exactly as the snippet gives them. A `summary` field, "
    "when present, is MODEL-WRITTEN: never take a figure from it.",
    _schema({"query": {"type": "string", "description": "Search text, up to 200 characters."}}),
)

MC_DECISION_TOOL = chat.ToolSpec(mc.MONTE_CARLO_DECISION_TOOL["name"], mc.MONTE_CARLO_DECISION_TOOL["description"],
                                  mc.MONTE_CARLO_DECISION_TOOL["parameters"])


def _mc_cash_tool(scenario_schema: dict[str, Any]) -> chat.ToolSpec:
    raw = mc.cash_tool(scenario_schema, SHOCK_SCHEMA)
    return chat.ToolSpec(raw["name"], raw["description"], raw["parameters"])


_FILTER_SCHEMA = {
    "type": "object",
    "properties": {
        "field": {"type": "string", "description": "A column of the table."},
        "op": {"type": "string", "enum": ["eq", "ne", "gt", "gte", "lt", "lte", "contains"]},
        "value": {"type": ["string", "number", "boolean"]},
    },
    "required": ["field", "op", "value"],
    "additionalProperties": False,
}
INTERNAL_DATA_TOOL = chat.ToolSpec(
    "query_internal_data",
    "Query the demo business's mock internal data room (SYNTHETIC (mock internal data), fictional company): "
    "general_ledger (52 weeks of history: week_index, week_ending, store, account revenue|cogs|payroll|opex|"
    "interest, amount), ar_aging (open invoices: customer, amount, days_outstanding, bucket), ap_schedule (open "
    "supplier bills: supplier, amount, terms_days, due, days_until_due), payroll (store, department, headcount, "
    "weekly_cost), inventory (group, supplier, on_hand_value, weekly_usage_value, weeks_of_cover, perishable), "
    "customers (name, segment, weekly_revenue, annual_revenue, share_of_total_sales, churn_risk, contract_end), "
    "debt (facilities and covenants: limit, balance, annual_rate, threshold), contracts (counterparty, type, "
    "weekly_minimum, renewal_date, notice_days). Filters, group_by and the aggregate are computed in Python; "
    "grouped sums and counts carry share_of_total.",
    _schema({
        "table": {"type": "string", "enum": list(internal_routes.TABLES)},
        "filters": {"type": ["array", "null"], "items": _FILTER_SCHEMA,
                    "description": "All must hold (AND). Text compares case-insensitively; dates as ISO strings."},
        "group_by": {"type": ["string", "null"], "description": "A column to group by, or null."},
        "aggregate": {"anyOf": [{"type": "string", "enum": ["sum", "mean", "count", "min", "max"]},
                                {"type": "null"}],
                      "description": "null = return matching rows."},
        "field": {"type": ["string", "null"], "description": "Numeric column to aggregate (null for count)."},
        "limit": {"type": ["integer", "null"],
                  "description": f"Rows or groups returned, 1..{internal_routes.MAX_QUERY_ROWS}; null = "
                                 f"{internal_routes.MAX_QUERY_ROWS}."},
    }),
)


def _drop_nulls(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _drop_nulls(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [_drop_nulls(v) for v in value]
    return value


def _r(x: float | None) -> float | None:
    return None if x is None else round(float(x), 2)


class _ToolInputError(Exception):
    def __init__(self, message: str, errors: list[dict[str, Any]] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.errors = errors or []


def _route_error_summary(err: RouteError) -> dict[str, Any]:
    return {"error": err.message, "code": err.code.value,
            "errors": [{"loc": e.loc, "msg": e.msg} for e in err.errors][:10]}


def _action_totals(actions: list[Any]) -> dict[str, dict[str, Any]]:
    """{action kind: {"total_amount", "weeks"}} for an optimize plan; amounts summed in Python, rounded to cents."""
    totals: dict[str, dict[str, Any]] = {}
    for a in actions:
        t = totals.setdefault(a.action, {"total_amount": 0.0, "weeks": []})
        if a.amount is not None:
            t["total_amount"] += float(a.amount)
        t["weeks"].append(a.week)
    for t in totals.values():
        t["total_amount"] = _r(t["total_amount"])
    return totals


def web_label(retrieved_at: datetime) -> str:
    """Provenance shown with a web_search result: REAL web content, stamped with when FAULTLINE fetched it."""
    return f"REAL (web, retrieved {retrieved_at.astimezone(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')})"


class EngineToolBox:
    """Runs each tool through the same route function the HTTP API uses, in-process."""

    def __init__(self, settings: Settings, tavily_transport: httpx.AsyncBaseTransport | None,
                 web_quota: Callable[[], str | None] | None = None,
                 web_clients: chat.ClientFactory | None = None) -> None:
        self.settings = settings
        self.tavily_transport = tavily_transport
        self.web_provider = web_llm.provider_from_env()  # tavily | anthropic | openai | None (#214)
        self.web = self.web_provider is not None
        self.web_clients = web_clients or chat.ClientFactory()  # the SDK clients for Anthropic / OpenAI search
        self.web_calls = 0  # one toolbox per turn
        # Daily web_search caps for this caller (ChatState.web_take): a refusal message, or None. None = unlimited.
        self.web_quota = web_quota

    def specs(self) -> list[chat.ToolSpec]:
        try:
            named = self._named()
        except RouteError:  # a fixture that fails its schema: plain string ids, the lookup reports the error
            named = None
        tools = _engine_tools(named) if named else ENGINE_TOOLS
        try:
            frames = [(f.id, f.question_template) for f in decision_routes.list_frames(self.settings).frames]
        except RouteError:
            frames = []
        if frames:
            tools = _with_frame_ids(tools, frames)
        cash = _mc_cash_tool(_scenario_id_schema(named) if named else _SCENARIO_ID)
        return [*tools, MC_DECISION_TOOL, cash, INTERNAL_DATA_TOOL, *([WEB_SEARCH_TOOL] if self.web else [])]

    # ---- shock resolution: the canonical, validated ScenarioShock JSON the engine runs

    def _named(self) -> list[NamedShock]:
        """Named scenarios, then Judge's Challenges, from the same fixtures /api/scenarios and
        /api/judge-challenges serve."""
        scenarios = [NamedShock(s.id, s.name, "scenario", s.shock)
                     for s in scenario_routes.load_scenarios(self.settings) or []]
        challenges = challenge_routes.load_challenges(self.settings)
        return scenarios + [NamedShock(c.id, c.name, "challenge", c.shock)
                            for c in (challenges.challenges if challenges else [])]

    def _resolve(self, scenario_id: str) -> NamedShock:
        named = self._named()
        hits = [n for n in named if n.id == scenario_id] or match_named(scenario_id, named)
        if len(hits) == 1:
            return hits[0]
        valid = ", ".join(n.id for n in named) or "none loaded"
        if hits:
            raise _ToolInputError(f"scenario_id {scenario_id[:80]!r} is ambiguous ("
                                  f"{', '.join(n.id for n in hits)}); pass one exact id. Valid ids: {valid}.")
        raise _ToolInputError(f"Unknown scenario_id {scenario_id[:80]!r}. Valid ids: {valid}.")

    def _shock_body(self, args: dict[str, Any]) -> dict[str, Any]:
        sid, raw = args.get("scenario_id"), args.get("shock")
        if isinstance(sid, str) and normalize_scenario_key(sid) in NULL_SCENARIO_KEYS:
            sid = None  # a model writing null as text ("null", "None", "") means "use shock", not an unknown id
        if sid:
            if not isinstance(sid, str):
                raise _ToolInputError("scenario_id must be a string")
            hit = self._resolve(sid)
            shock = hit.shock
            body: dict[str, Any] = {"scenario_id": hit.id}  # the canonical id, so the input re-POSTs as is
        elif isinstance(raw, dict):
            try:
                shock = ScenarioShock.model_validate(_drop_nulls(raw))
            except ValidationError as exc:
                raise _ToolInputError("shock failed validation", [
                    {"loc": i.loc, "msg": i.msg} for i in issues_from(exc.errors(), prefix=("shock",))][:10]) from None
            body = {}
        elif raw is None:
            shock = ScenarioShock()
            body = {}
        else:
            raise _ToolInputError("shock must be an object or null")
        body["shock"] = shock.model_dump(mode="json")
        return body

    # ---- tools

    async def run(self, name: str, arguments: dict[str, Any]) -> chat.ToolOutcome:
        handler = getattr(self, f"_tool_{name}", None)
        provenance = _PROVENANCE.get(name, chat.CHAT_PROVENANCE)
        if handler is None:
            return chat.ToolOutcome("error", provenance, {}, {"error": f"Unknown tool {name[:60]!r}."})
        try:
            return await handler(arguments)
        except _ToolInputError as err:
            return chat.ToolOutcome("error", provenance, _safe_args(arguments),
                                    {"error": err.message, "errors": err.errors})
        except RouteError as err:
            return chat.ToolOutcome("error", provenance, _safe_args(arguments), _route_error_summary(err))
        except ValidationError as exc:
            return chat.ToolOutcome("error", provenance, _safe_args(arguments), {
                "error": "arguments failed validation",
                "errors": [{"loc": i.loc, "msg": i.msg} for i in issues_from(exc.errors())][:10]})

    async def _tool_simulate(self, args: dict[str, Any]) -> chat.ToolOutcome:
        body = self._shock_body(args)
        request = simulate_routes.SimulateRequest.model_validate(body)
        resp = simulate_routes.simulate_route(request, self.settings)
        res = resp.result
        week_of_min = res.cash.index(min(res.cash)) + 1
        summary = {
            "business_provenance": resp.business_provenance,
            "scenario": res.scenario_name,
            "horizon_weeks": res.horizon_weeks,
            "starting_cash": _r(res.cash_0),
            "min_cash": _r(res.min_cash),
            "min_cash_week": week_of_min,
            "ending_cash": _r(res.cash[-1]),
            "baseline_min_cash": _r(resp.baseline.min_cash),
            "baseline_ending_cash": _r(resp.baseline.cash[-1]),
            "min_cash_change_vs_baseline": _r(resp.deltas.min_cash_delta),
            "ending_cash_change_vs_baseline": _r(resp.deltas.ending_cash_delta),
            "min_cash_floor": _r(resp.min_cash_floor),
            # Computed here, not by the model (#195: models subtracted the floor themselves and were withheld).
            # Positive = headroom above the floor at the low point; negative = how far below it.
            "min_cash_vs_floor": (None if resp.min_cash_floor is None
                                  else _r(res.min_cash - resp.min_cash_floor)),
            # The same falls as positive amounts ("the shock cuts the low point by ..."), so a model never has to
            # flip a sign or subtract (#195: the commonest reason for a withheld reply after the first tuning).
            "min_cash_drop_vs_baseline": _r(-resp.deltas.min_cash_delta),
            "ending_cash_drop_vs_baseline": _r(-resp.deltas.ending_cash_delta),
            "min_cash_drop_from_start": _r(res.cash_0 - res.min_cash),
            "first_week_below_floor": resp.first_week_below_floor,
            "weeks_below_floor": resp.weeks_below_floor,
            "weekly_cash": [_r(c) for c in res.cash],
            "rounding": "dollar amounts rounded to cents",
        }
        return chat.ToolOutcome("ok", "SIMULATED", body, summary)

    async def _tool_optimize(self, args: dict[str, Any]) -> chat.ToolOutcome:
        body = self._shock_body(args)
        protect = args.get("protect_payroll")
        if not isinstance(protect, bool):
            raise _ToolInputError("protect_payroll must be true or false")
        body["protect_payroll"] = protect
        request = optimize_routes.OptimizeRequest.model_validate(body)
        resp = await optimize_routes.optimize_route(request, self.settings)
        summary: dict[str, Any] = {
            "business_provenance": resp.business_provenance,
            "status": resp.status,
            "scenario": resp.scenario_name,
            "protect_payroll": resp.protect_payroll,
            "min_cash": _r(resp.min_cash),
            "min_cash_week": resp.min_cash_week,
            "actions": [{"action": a.action, "week": a.week, "amount": _r(a.amount), "share": a.share}
                        for a in (resp.actions or [])],
            # Totals per action kind over the horizon, summed here (#195: models added the weekly amounts up
            # themselves, e.g. "total purchase cuts", and were withheld).
            "action_totals": _action_totals(resp.actions or []),
            "binding_constraints": resp.binding_constraints,
            "disruption_cost": _r(resp.disruption_cost),
            "payroll_cut_cap": resp.payroll_cut_cap,
            "weekly_cash": [_r(c) for c in resp.cash] if resp.cash else None,
            "rounding": "dollar amounts rounded to cents",
        }
        if resp.status != "OPTIMAL":
            summary["max_feasible_cash_floor"] = _r(resp.max_feasible_cash_floor)
            summary["diagnostic"] = resp.diagnostic
            if resp.status == "SOLVER ERROR":
                summary["solver_message"] = resp.solver_message
        return chat.ToolOutcome("ok", "SIMULATED", body, summary)

    async def _tool_decision(self, args: dict[str, Any]) -> chat.ToolOutcome:
        body = {"frame_id": args.get("frame_id"), "p_yes": args.get("p_yes")}
        request = decision_routes.DecisionRequest.model_validate(body)
        body = request.model_dump(mode="json", exclude_none=True)
        resp = decision_routes.decision_route(request, self.settings)
        summary = {
            "business_provenance": resp.business_provenance,
            "frame_provenance": resp.frame_provenance,
            "frame_id": resp.frame_id,
            "p_yes": resp.p_yes,
            "protect_payroll": resp.protect_payroll,
            "payoff": resp.payoff,
            "recommendation": resp.recommendation,
            "policies": [{"name": p.name, "expected_value": _r(p.expected_value), "value_if_yes": _r(p.value_if_yes),
                          "value_if_no": _r(p.value_if_no), "feasible_in_both": p.feasible_in_both}
                         for p in resp.policies],
            "break_even": {"status": resp.break_even.status, "policies": resp.break_even.policies,
                           "p_star": resp.break_even.p_star},
            "forecast_sensitive": resp.forecast_sensitive,
            "caveat": resp.caveat,
            "rounding": "dollar amounts rounded to cents",
        }
        return chat.ToolOutcome("ok", "SIMULATED", body, summary)

    async def _tool_list_scenarios(self, _args: dict[str, Any]) -> chat.ToolOutcome:
        resp = scenario_routes.list_scenarios(self.settings)
        summary = {"status": resp.status, "notes": resp.notes, "items": [
            {"id": s.id, "name": s.name, "rationale": s.rationale, "provenance": s.provenance,
             "shock": s.shock.model_dump(mode="json")} for s in resp.items]}
        return chat.ToolOutcome("ok", "SYNTHETIC", {}, summary)

    async def _tool_list_judge_challenges(self, _args: dict[str, Any]) -> chat.ToolOutcome:
        resp = challenge_routes.list_judge_challenges(self.settings)
        summary = {"status": resp.status, "label": resp.label, "notes": resp.notes, "items": [
            {"id": c.id, "name": c.name, "description": c.description, "shock": c.shock.model_dump(mode="json")}
            for c in resp.items]}
        return chat.ToolOutcome("ok", "ILLUSTRATIVE", {}, summary)

    async def _tool_list_decision_frames(self, _args: dict[str, Any]) -> chat.ToolOutcome:
        resp = decision_routes.list_frames(self.settings)
        summary = {"status": resp.status, "payoff": resp.payoff, "frames": [
            {"id": f.id, "question": f.question_template, "yes_means": f.yes_means, "no_means": f.no_means,
             "forecast_sensitive": f.forecast_sensitive, "caveat": f.caveat,
             "policies": [{"name": p.name, "summary": p.summary} for p in f.policies]} for f in resp.frames]}
        return chat.ToolOutcome("ok", "ILLUSTRATIVE", {}, summary)

    async def _tool_vc_lenses(self, args: dict[str, Any]) -> chat.ToolOutcome:
        as_of = args.get("as_of")
        if as_of is not None and not isinstance(as_of, str):
            raise _ToolInputError("as_of must be an ISO-8601 string or null")
        stub = StarletteRequest({"type": "http", "method": "GET", "path": "/api/vc-lenses", "query_string": b"",
                                 "headers": []})
        resp = research_routes.vc_lenses(stub, self.settings, as_of)
        summary = {"status": resp.status, "mode": resp.mode, "mode_label": resp.mode_label, "notes": resp.notes,
                   "as_of": resp.as_of.isoformat() if resp.as_of else None, "items": [
                       {"firm": i.firm, "title": i.title, "url": i.url, "published_at": i.published_at,
                        "thesis": i.thesis} for i in resp.items]}
        return chat.ToolOutcome("ok", "REAL HISTORICAL", {"as_of": as_of} if as_of else {}, summary)

    async def _tool_monte_carlo_decision(self, args: dict[str, Any]) -> chat.ToolOutcome:
        args = dict(args)
        premise = mc.premise_note(args.pop("premise", None))  # a label for the UI and the model; never an engine input
        request = mc.DecisionRequest.model_validate(_mc_args(args))
        body = mc.decision_body(request)
        out = await _run_engine(mc.run_decision(body))
        summary = {**mc.decision_summary(out), **({"premise": premise} if premise else {}), "monte_carlo": out}
        return chat.ToolOutcome("ok", "SIMULATED", body, summary)

    async def _tool_monte_carlo_cash(self, args: dict[str, Any]) -> chat.ToolOutcome:
        # The resolved shock always travels (it wins over scenario_id in the engine), so Judge's Challenges work too;
        # scenario_id is kept as the label.
        shock = self._shock_body({"scenario_id": args.get("scenario_id"), "shock": args.get("shock")})
        request = mc.CashRequest.model_validate({
            "scenario_id": shock.get("scenario_id"), "shock": shock["shock"],
            **{k: args.get(k) for k in ("protect_payroll", "with_plan", "n_paths", "seed") if k in args}})
        body = request.model_dump(mode="json")
        out = await _run_engine(mc.run_cash(body, self.settings))
        return chat.ToolOutcome("ok", "SIMULATED", body, {**mc.cash_summary(out), "monte_carlo": out})

    async def _tool_query_internal_data(self, args: dict[str, Any]) -> chat.ToolOutcome:
        table = args.get("table")
        if not isinstance(table, str) or table not in internal_routes.TABLES:
            raise _ToolInputError(f"table must be one of {list(internal_routes.TABLES)}")
        filters = args.get("filters")
        if filters is not None and not (isinstance(filters, list) and all(isinstance(f, dict) for f in filters)):
            raise _ToolInputError("filters must be a list of {field, op, value} or null")
        query = {k: args.get(k) for k in ("group_by", "aggregate", "field", "limit")}
        for k in ("group_by", "aggregate", "field"):
            if query[k] is not None and not isinstance(query[k], str):
                raise _ToolInputError(f"{k} must be a string or null")
        if query["limit"] is not None and (isinstance(query["limit"], bool) or not isinstance(query["limit"], int)):
            raise _ToolInputError("limit must be an integer or null")
        data = internal_routes.load_table(self.settings, table)
        if data is None:
            raise _ToolInputError(f"internal data table {table!r} is NOT AVAILABLE on this server")
        try:
            result = internal_routes.query_rows(data, filters=filters, **query)
        except internal_routes.QueryError as err:
            raise _ToolInputError(str(err)) from None
        body = {"table": table, "filters": filters, **query}
        summary = {"label": internal_routes.LABEL, "description": data.get("description"), **result}
        return chat.ToolOutcome("ok", internal_routes.LABEL, body, summary)

    async def _tool_web_search(self, args: dict[str, Any]) -> chat.ToolOutcome:
        if not self.web:
            raise _ToolInputError("web_search is not available on this server")
        if self.web_calls >= MAX_WEB_SEARCHES_PER_TURN:
            raise _ToolInputError(f"web_search limit reached ({MAX_WEB_SEARCHES_PER_TURN} per turn); answer from "
                                  "the results you have")
        query = tavily.normalize_query(str(args.get("query") or ""))
        if not query or len(query) > 200:
            raise _ToolInputError("query must be 1-200 characters")
        refusal = self.web_quota() if self.web_quota is not None else None
        if refusal:
            raise _ToolInputError(refusal)
        self.web_calls += 1
        if self.web_provider in ("anthropic", "openai"):
            try:
                found = await web_llm.search(self.web_provider, query, self.web_clients)
            except web_llm.WebSearchError as err:
                logger.warning("chat web_search (%s) failed: %s", self.web_provider, err.kind)
                # #221: an Anthropic search that fails gets ONE try on OpenAI's web search when its key is set. The
                # result carries the attribution of the provider that actually answered (WebSearchResult.provider).
                kind, recovered = err.kind, None
                if self.web_provider == "anthropic" and self.web_clients.key("openai"):
                    try:
                        recovered = await web_llm.search("openai", query, self.web_clients)
                    except web_llm.WebSearchError as again:
                        logger.warning("chat web_search fallback (openai) failed: %s", again.kind)
                        kind = again.kind
                if recovered is None:
                    return chat.ToolOutcome("error", "LIVE EXPLORE", {"query": query},
                                            {"error": f"Web search unavailable ({kind}). No results were made up."})
                found = recovered
            return chat.ToolOutcome("ok", "LIVE EXPLORE", {"query": query},
                                    found.as_summary(web_label(found.retrieved_at)))
        try:
            client = tavily.client_from_env(transport=self.tavily_transport, timeout_s=TAVILY_TIMEOUT_S)
            result = await client.search(query, max_results=WEB_RESULTS)
        except tavily.TavilyError as err:
            logger.warning("chat web_search failed: %s", err.kind.value)
            return chat.ToolOutcome("error", "LIVE EXPLORE", {"query": query},
                                    {"error": f"Web search unavailable ({err.kind.value})."})
        summary = {
            "provenance": web_label(result.retrieved_at),  # what the model and the tool step show
            "retrieved_at": result.retrieved_at.isoformat(),
            "query": query,
            "results": [{"title": h.title, "url": h.url, "domain": (urlsplit(h.url).hostname or "").lower(),
                         "published_date": h.published_at.isoformat() if h.published_at else None,
                         "snippet": h.snippet} for h in result.items],
            "attribution": "Search powered by Tavily",
            "note": "Current web pages, not point-in-time evidence. published_date is Tavily's estimate.",
        }
        return chat.ToolOutcome("ok", "LIVE EXPLORE", {"query": query}, summary)


_PROVENANCE = {"simulate": "SIMULATED", "optimize": "SIMULATED", "decision": "SIMULATED",
               "list_scenarios": "SYNTHETIC", "list_judge_challenges": "ILLUSTRATIVE",
               "list_decision_frames": "ILLUSTRATIVE", "vc_lenses": "REAL HISTORICAL", "web_search": "LIVE EXPLORE",
               "monte_carlo_decision": "SIMULATED", "monte_carlo_cash": "SIMULATED",
               "query_internal_data": internal_routes.LABEL}


def _mc_args(args: dict[str, Any]) -> dict[str, Any]:
    """The model's arguments with null n_paths / seed dropped (the contract defaults apply)."""
    return {k: v for k, v in args.items() if not (k in ("n_paths", "seed") and v is None)}


async def _run_engine(call: Coroutine[Any, Any, dict[str, Any]]) -> dict[str, Any]:
    """Await a Monte Carlo engine call. Engine failures become tool errors (a RouteError passes through to run()),
    never numbers."""
    try:
        return await call
    except mc.EngineUnavailable:
        raise _ToolInputError("The Monte Carlo engine is NOT AVAILABLE on this server; give the answer without "
                              "probabilities and say so.") from None
    except mc.EngineContractError as err:
        logger.warning("chat monte carlo: %s", err)
        raise _ToolInputError("The Monte Carlo engine returned an unexpected result; nothing was computed.") from None
    except (ValueError, TypeError) as err:  # the engine's own validation
        raise _ToolInputError(f"The Monte Carlo engine refused the input: {str(err)[:300]}") from None


def _safe_args(arguments: dict[str, Any]) -> dict[str, Any]:
    """Arguments as received, for a failed call (so the UI can show what the model tried). Bounded size."""
    text = str(arguments)
    return arguments if len(text) <= 4000 else {"truncated": True}


# --------------------------------------------------------------------------- request / response models


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS)


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_id: str = Field(min_length=1, max_length=200, description="An `id` from GET /api/explore/chat/models.")
    messages: list[ChatMessage] = Field(min_length=1, max_length=MAX_MESSAGES)

    @model_validator(mode="after")
    def _last_is_user(self) -> ChatRequest:
        if self.messages[-1].role != "user":
            raise ValueError("the last message must have role 'user'")
        return self


class ChatToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    input: dict[str, Any] = Field(description="The exact validated request the engine ran. For simulate / optimize "
                                  "it is a body POST /api/simulate or /api/optimize accepts and reproduces.")
    result_status: Literal["ok", "error"]
    result_summary: dict[str, Any] = Field(description="What the model was shown: numbers straight from the engine.")
    provenance: str


class ChatUsage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input_tokens: int
    output_tokens: int


class ChatResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_serialization_defaults_required=True)

    status: Literal["ok", "unavailable", "error"]
    provenance: Literal["LIVE EXPLORE"] = "LIVE EXPLORE"
    label: Literal["MODEL-WRITTEN, numbers from engine tools"] = "MODEL-WRITTEN, numbers from engine tools"
    model_id: str
    provider: Literal["openrouter", "openai", "anthropic"]
    reply: str = Field(description="Model-written text; empty unless status is ok.")
    tool_calls: list[ChatToolCall]
    usage: ChatUsage | None = Field(description="Summed over the turn; null when the provider did not report it.")
    notes: list[str]


class ChatStreamEvent(BaseModel):
    """One `data:` line of POST /api/explore/chat/stream (documentation of the SSE contract, #222). Previews are
    built on the server from the tool arguments and results; reply text only ever arrives inside `final`."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["start", "round", "tool_call", "tool_result", "repair", "final", "error"]
    model_id: str | None = Field(default=None, description="start")
    provider: Literal["openrouter", "openai", "anthropic"] | None = Field(default=None, description="start")
    started_at: datetime | None = Field(default=None, description="start (UTC)")
    n: int | None = Field(default=None, description="round: 1..MAX_TOOL_ROUNDS; repair: how many figures failed")
    id: str | None = Field(default=None, description="tool_call / tool_result: '<round>.<index>', shared by both")
    name: str | None = Field(default=None, description="tool_call / tool_result: the tool")
    input_preview: str | None = Field(default=None, description="tool_call: what the model asked for, in words")
    result_status: Literal["ok", "error"] | None = Field(default=None, description="tool_result")
    provenance: str | None = Field(default=None, description="tool_result: the tool result's provenance label")
    preview: str | None = Field(default=None,
                                description="tool_result: one line from the engine summary; repair: a note")
    response: ChatResponse | None = Field(default=None, description="final: the POST /api/explore/chat body")
    code: str | None = Field(default=None, description="error: the machine-readable code")
    message: str | None = Field(default=None, description="error: plain-language, safe to show")
    status: int | None = Field(default=None, description="error: the HTTP status the JSON route would have sent")


class ChatPricing(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input_per_mtok: float | None = Field(description="USD per million input tokens; null = not provided.")
    output_per_mtok: float | None = Field(description="USD per million output tokens; null = not provided.")


class ChatModelOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    label: str
    provider: Literal["openrouter", "openai", "anthropic"]
    available: bool = Field(description="The provider's key is configured on this server (never the key itself).")
    open_weights: bool = Field(description="On FAULTLINE's explicit allow-list of open-weight model ids (#221); "
                               "false for closed or uncertain models.")
    note: str | None
    context_length: int | None
    pricing: ChatPricing | None = Field(description="As the provider publishes it; null when not provided.")


class ChatModelsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_serialization_defaults_required=True)

    models: list[ChatModelOut]
    default: str | None = Field(description="The preselected model: the first of DEFAULT_MODEL_PREFERENCE that is "
                                "featured, else the first featured model, else the first available; null if none.")
    featured: list[str] = Field(description="Up to 12 suggested ids in two groups: open-weight models first "
                                "(open_weights true), then closed ones.")
    max_output_price_per_mtok: float | None = Field(
        description="Public catalogue price cap (USD per million output tokens); null for an admin caller.")
    notes: list[str]


class ChatPauseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    paused: bool
    minutes: int | None = Field(default=None, ge=1, le=MAX_PAUSE_MINUTES,
                                description=f"Auto-resume after this many minutes (default {DEFAULT_PAUSE_MINUTES}).")


class ChatStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    paused: bool
    until: datetime | None
    note: str = "Held in this API process's memory: a restart clears a pause."


# --------------------------------------------------------------------------- routes

router = APIRouter(tags=["explore-chat"], route_class=CodedRoute)
admin_router = APIRouter(tags=["explore-chat"], route_class=AdminGatedRoute)

_ERRORS: dict[int | str, dict[str, Any]] = {
    code: {"model": RouteErrorBody, "description": desc} for code, desc in {
        401: "ADMIN_TOKEN_REQUIRED (public mode, chat not public): no bearer token",
        403: "ADMIN_TOKEN_REQUIRED (public mode, chat not public): wrong token",
        422: "VALIDATION_ERROR",
        429: "RATE_LIMITED (Retry-After): per-IP chat limit, or the provider is rate-limiting this server",
        502: "UPSTREAM_ERROR: the model provider failed",
        503: "PAUSED (presenter pause), BUDGET (daily spend ceiling), LIVE_EXPLORE_UNAVAILABLE (no key), or BUSY",
    }.items()
}


def _model_out(m: chat.CatalogModel, catalog: chat.Catalog, settings: Settings) -> ChatModelOut:
    available = catalog.available(m, settings)
    priced = m.input_per_mtok is not None or m.output_per_mtok is not None
    return ChatModelOut(
        id=m.id, label=m.label, provider=m.provider, available=available, open_weights=m.open_weights, note=m.note,
        context_length=m.context_length,
        pricing=ChatPricing(input_per_mtok=m.input_per_mtok, output_per_mtok=m.output_per_mtok) if priced else None,
    )


def _visible(catalog: chat.Catalog, settings: Settings, admin: bool) -> list[chat.CatalogModel]:
    if admin:
        return list(catalog.models)
    return [m for m in catalog.models if chat.affordable(m, settings.chat_max_price_per_mtok)]


@router.get("/explore/chat/models", response_model=ChatModelsResponse, summary="LIVE EXPLORE chat: model catalogue")
async def chat_models(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    state: Annotated[ChatState, Depends(get_chat_state)],
    clients: Annotated[chat.ClientFactory, Depends(get_chat_clients)],
) -> ChatModelsResponse:
    admin = is_admin(request)
    catalog = await state.get_catalog(settings, clients)
    visible = _visible(catalog, settings, admin)
    featured = chat.featured_ids(visible, catalog, settings)
    notes = list(catalog.notes)
    if not admin:
        hidden = len(catalog.models) - len(visible)
        if hidden:
            notes.append(f"{hidden} model(s) hidden: published output price above "
                         f"${settings.chat_max_price_per_mtok:g} per million tokens, or no price published.")
    return ChatModelsResponse(
        models=[_model_out(m, catalog, settings) for m in visible],
        default=chat.default_model_id(featured)
        or next((m.id for m in visible if catalog.available(m, settings)), None),
        featured=featured,
        max_output_price_per_mtok=None if admin else settings.chat_max_price_per_mtok,
        notes=notes,
    )


@router.get("/explore/chat/status", response_model=ChatStatus, summary="LIVE EXPLORE chat: presenter pause state")
def chat_status(state: Annotated[ChatState, Depends(get_chat_state)]) -> ChatStatus:
    until = state.paused()
    return ChatStatus(paused=until is not None, until=until)


@admin_router.post("/explore/chat/pause", response_model=ChatStatus, responses=_ERRORS,
                   summary="LIVE EXPLORE chat: pause or resume public chat (admin)")
def chat_pause(body: ChatPauseRequest, state: Annotated[ChatState, Depends(get_chat_state)]) -> ChatStatus:
    # TODO(ash/public-inference): once that PR lands, the same pause should also gate public POST /api/replay/run.
    # The replay route must read it through a neutral module, never by importing this one (separation test).
    if body.paused:
        state.paused_until = state.wall() + timedelta(minutes=body.minutes or DEFAULT_PAUSE_MINUTES)
    else:
        state.paused_until = None
    until = state.paused()
    return ChatStatus(paused=until is not None, until=until)


def _upstream(err: chat.ChatUpstreamError, provider: str) -> RouteError:
    name = chat.PROVIDER_NAMES.get(provider, provider)
    if err.kind == "rate_limited":
        headers = {"Retry-After": str(err.retry_after)} if err.retry_after else {}
        return RouteError(ErrorCode.RATE_LIMITED, f"{name} is rate-limiting this server; try again shortly.", 429,
                          headers=headers)
    if err.kind == "timeout":
        return RouteError(ErrorCode.UPSTREAM_ERROR, f"{name} did not answer in time. No reply was made up.", 502)
    return RouteError(ErrorCode.UPSTREAM_ERROR, f"{name} returned an error. No reply was made up.", 502)


async def _admit(body: ChatRequest, request: Request, settings: Settings, state: ChatState,
                 clients: chat.ClientFactory) -> tuple[chat.CatalogModel, bool]:
    """Every gate before the tool loop, in order (pause, budget, per-IP, catalogue, key, concurrency). Shared by
    POST /api/explore/chat and its stream twin, so both refuse the same requests with the same codes."""
    admin = is_admin(request)
    if not admin and state.paused() is not None:
        raise RouteError(ErrorCode.PAUSED, PAUSED_MESSAGE, 503)
    if not admin and state.spent_today() >= settings.chat_daily_budget_usd:
        raise RouteError(ErrorCode.BUDGET, BUDGET_MESSAGE, 503)
    if not admin and settings.chat_per_ip > 0:
        host = request.client.host if request.client else "unknown"
        wait = state.limiter.take(rate_limit_key(host), settings.chat_per_ip)
        if wait is not None:
            raise RouteError(ErrorCode.RATE_LIMITED, f"Chat limit reached for this address ({settings.chat_per_ip} "
                             "turns per 10 minutes). Try again later.", 429, headers={"Retry-After": str(wait)})

    catalog = await state.get_catalog(settings, clients)
    model = next((m for m in _visible(catalog, settings, admin) if m.id == body.model_id), None)
    if model is None:
        raise RouteError(ErrorCode.VALIDATION_ERROR, "model_id is not in the current model catalogue "
                         "(GET /api/explore/chat/models).", 422)
    if not catalog.available(model, settings):
        why = "was refused by the provider" if model.provider in catalog.rejected else "is not set on this server"
        raise RouteError(ErrorCode.LIVE_EXPLORE_UNAVAILABLE,
                         f"Live chat with {chat.PROVIDER_NAMES[model.provider]} models is unavailable: its API key "
                         f"{why}.", 503)
    _check_busy(state, settings)
    return model, admin


def _check_busy(state: ChatState, settings: Settings) -> None:
    if state.active >= settings.chat_concurrency:
        raise RouteError(ErrorCode.BUSY, "The live chat is busy with other conversations. Nothing was sent; try "
                         "again in a moment.", 503, headers={"Retry-After": str(BUSY_RETRY_AFTER_S)})


async def _run_turn(body: ChatRequest, request: Request, model: chat.CatalogModel, admin: bool, settings: Settings,
                    state: ChatState, clients: chat.ClientFactory,
                    tavily_transport: httpx.AsyncBaseTransport | None,
                    on_event: chat.EventSink | None = None) -> ChatResponse:
    """The tool loop and the honesty pipeline (figure check, withholding, notes) for one admitted turn."""
    _check_busy(state, settings)  # again, with no await before the increment: the stream admits, then runs later
    state.active += 1
    caller = None if admin else rate_limit_key(request.client.host if request.client else "unknown")
    toolbox = EngineToolBox(settings, tavily_transport, web_quota=lambda: state.web_take(
        caller, settings.chat_web_per_ip_day, settings.chat_web_daily), web_clients=clients)
    history = [{"role": m.role, "content": m.content} for m in body.messages]
    try:
        adapter = chat.adapter_for(model, clients)
        async with asyncio.timeout(TURN_TIMEOUT_S):
            outcome = await chat.run_chat(adapter, toolbox, history, web_search=toolbox.web, on_event=on_event)
    except chat.ChatUpstreamError as err:
        logger.warning("chat: provider %s failed (%s)", model.provider, err.kind)
        if err.kind in ("auth", "not_found"):
            outcome = chat.ChatOutcome("unavailable", "", [], None, None, [
                f"{chat.PROVIDER_NAMES[model.provider]} rejected this server's key or does not serve this model "
                "right now; try another model."])
        elif err.kind == "bad_request":
            outcome = chat.ChatOutcome("error", "", [], None, None, [
                f"{chat.PROVIDER_NAMES[model.provider]} refused the request for this model (it may not support "
                "tool calling). " + chat.TOOLS_FAILED_NOTE])
        else:
            raise _upstream(err, model.provider) from None
    except TimeoutError:
        logger.warning("chat: turn timed out (%s)", model.provider)
        raise RouteError(ErrorCode.UPSTREAM_ERROR, "The model did not finish in time. No reply was made up.",
                         502) from None
    finally:
        state.active -= 1
    state.record_spend(model, outcome.counted_input_tokens, outcome.counted_output_tokens,
                       settings.chat_max_price_per_mtok)

    usage = (ChatUsage(input_tokens=outcome.input_tokens, output_tokens=outcome.output_tokens)
             if outcome.input_tokens is not None and outcome.output_tokens is not None else None)
    return ChatResponse(
        status=outcome.status, model_id=model.id, provider=model.provider,
        reply=outcome.reply if outcome.status == "ok" else "",
        tool_calls=[ChatToolCall(name=r.name, input=r.input, result_status=r.result_status,
                                 result_summary=r.result_summary, provenance=r.provenance)
                    for r in outcome.tool_calls],
        usage=usage, notes=[*outcome.notes, STANDARD_NOTE],
    )


@router.post("/explore/chat", response_model=ChatResponse, responses=_ERRORS,
             dependencies=[Depends(require_chat_access)],
             summary="LIVE EXPLORE chat turn: MODEL-WRITTEN, numbers from engine tools")
async def chat_turn(
    body: ChatRequest,
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    state: Annotated[ChatState, Depends(get_chat_state)],
    clients: Annotated[chat.ClientFactory, Depends(get_chat_clients)],
    tavily_transport: Annotated[httpx.AsyncBaseTransport | None, Depends(get_chat_tavily_transport)],
) -> ChatResponse | JSONResponse:
    model, admin = await _admit(body, request, settings, state, clients)
    return await _run_turn(body, request, model, admin, settings, state, clients, tavily_transport)


# --------------------------------------------------------------------------- the stream twin (#222)

HEARTBEAT_S = 10.0
SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
_STREAM_RESPONSES: dict[int | str, dict[str, Any]] = {
    **_ERRORS,
    200: {"content": {"text/event-stream": {}},
          "description": "Server-sent events, one JSON `data:` line each: start, round, tool_call, tool_result, then "
                         "exactly one of final ({response: the POST /api/explore/chat body}) or error "
                         "{code, message, status}. `: heartbeat` comment lines every 10 s."},
}


def _sse(payload: dict[str, Any]) -> str:
    return "data: " + json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str) + "\n\n"


async def _stream_turn(body: ChatRequest, request: Request, model: chat.CatalogModel, admin: bool,
                       settings: Settings, state: ChatState, clients: chat.ClientFactory,
                       tavily_transport: httpx.AsyncBaseTransport | None,
                       heartbeat_s: float | None = None) -> AsyncIterator[str]:
    """start, then live tool steps, then the final response (after the figure check) or an error. Reply text only
    ever travels inside `final`: a withheld reply has an empty `reply` there and is never streamed."""
    queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

    async def sink(ev: chat.ChatEvent) -> None:
        await queue.put(steps.event_payload(ev))

    async def work() -> None:
        try:
            resp = await _run_turn(body, request, model, admin, settings, state, clients, tavily_transport, sink)
            await queue.put({"type": "final", "response": resp.model_dump(mode="json")})
        except RouteError as err:
            await queue.put({"type": "error", "code": str(err.code), "message": err.message,
                             "status": err.status_code})
        except Exception:  # never a stack trace or a stand-in answer on the wire
            logger.exception("chat stream: turn failed")
            await queue.put({"type": "error", "code": str(ErrorCode.UPSTREAM_ERROR),
                             "message": "The turn failed on the server. No reply was made up.", "status": 500})
        finally:
            await queue.put(None)

    yield _sse({"type": "start", "model_id": model.id, "provider": model.provider,
                "started_at": state.wall().isoformat()})
    # The turn runs to completion even if the browser goes away (as POST /api/explore/chat does), so its spend is
    # recorded; the task is held on the state so it is not garbage-collected mid-turn.
    task = asyncio.create_task(work())
    state.stream_tasks.add(task)
    task.add_done_callback(state.stream_tasks.discard)
    while True:
        try:
            item = await asyncio.wait_for(queue.get(), heartbeat_s or HEARTBEAT_S)
        except TimeoutError:
            yield ": heartbeat\n\n"
            continue
        if item is None:
            return
        yield _sse(item)


@router.post("/explore/chat/stream", response_model=ChatStreamEvent, response_class=StreamingResponse,
             responses=_STREAM_RESPONSES, dependencies=[Depends(require_chat_access)],
             summary="LIVE EXPLORE chat turn, streamed: live tool steps, then the same final body")
async def chat_stream(
    body: ChatRequest,
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    state: Annotated[ChatState, Depends(get_chat_state)],
    clients: Annotated[chat.ClientFactory, Depends(get_chat_clients)],
    tavily_transport: Annotated[httpx.AsyncBaseTransport | None, Depends(get_chat_tavily_transport)],
) -> StreamingResponse:
    """Same body, gates and limits as POST /api/explore/chat; a refused request gets the same JSON error before
    any event is sent."""
    model, admin = await _admit(body, request, settings, state, clients)
    return StreamingResponse(
        _stream_turn(body, request, model, admin, settings, state, clients, tavily_transport),
        media_type="text/event-stream", headers=SSE_HEADERS)


router.include_router(admin_router)

__all__ = ["CHAT_MAX_BODY_BYTES", "ChatState", "EngineToolBox", "get_chat_clients", "get_chat_state",
           "get_chat_tavily_transport", "require_chat_access", "router"]
