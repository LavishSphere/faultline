"""FAULTLINE API entry point. Run from services/api: `uvicorn main:app --reload`."""

from __future__ import annotations

import json
import math
import re
import time
from collections import OrderedDict
from collections.abc import Callable
from enum import StrEnum

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from client_ip import client_key, rate_limit_key  # noqa: F401 - rate_limit_key re-exported for tests
from config import Settings, admin_token_matches, get_settings
from errors import FaultlineError, faultline_error_handler
from routes import (
    benchmark,
    cases,
    decision,
    explore,
    health,
    integrity,
    judge_challenges,
    optimize,
    recorded,
    replay,
    research,
    scenarios,
    simulate,
)

# ==== BEGIN edge protection (#13 deploy: CORS, mode header, rate limit, body limit, admin gate) ====
# Owned by the deploy issue. Router registrations live in create_app() below, outside this block.
# CORS only constrains browsers; everything else here applies to every client (curl, scripts, bots).

MODE_HEADER = "X-Faultline-Mode"

# Public-mode route classification: the ONE table (mirrored in docs/DEPLOY.md "Public mode: every route").
# "admin": runs the model, spends paid API credits, writes the prediction store, or reveals sealed outcomes; in
#          public mode it needs `Authorization: Bearer <FAULTLINE_ADMIN_TOKEN>`, checked twice: here at the edge
#          (ADMIN_GATED_PREFIXES) and inside the route (routes.replay.require_admin_in_public_mode).
# "public": deterministic or read-only; served to anyone, behind the rate limit and the body cap.
# "inference": admin, EXCEPT when FAULTLINE_PUBLIC_INFERENCE=1: then public at both layers (edge:
#          PUBLIC_INFERENCE_PATHS; route: routes.public_inference.require_run_access / require_reveal_access), behind
#          the inference safeguards
#          (one model run at a time, bounded queue, per-IP budgets) and writing only the scratch store.
# tests/test_public_mode_routes.py walks the OpenAPI schema: a route missing from this table fails the suite.
ADMIN = "admin"
PUBLIC = "public"
INFERENCE = "inference"
PUBLIC_MODE_ROUTES: dict[tuple[str, str], str] = {
    ("POST", "/api/replay/run"): INFERENCE,  # local-model inference + writes the prediction store
    ("POST", "/api/replay/{prediction_id}/reveal"): INFERENCE,  # reveals a sealed outcome + writes the reveal ledger
    ("GET", "/api/replay/recorded"): PUBLIC,  # committed RECORDED RUN rows, verified; read-only, never reveals (#116)
    ("POST", "/api/benchmark/compute"): ADMIN,  # reveals outcomes to score + writes a scorecard file
    ("POST", "/api/explore/analyze"): ADMIN,  # Tavily credits + local-model inference
    ("GET", "/api/explore/search"): ADMIN,  # Tavily credits
    ("GET", "/api/health"): PUBLIC,
    ("POST", "/api/simulate"): PUBLIC,
    ("POST", "/api/optimize"): PUBLIC,
    ("GET", "/api/scenarios"): PUBLIC,
    ("GET", "/api/decision/frames"): PUBLIC,
    ("POST", "/api/decision"): PUBLIC,
    ("GET", "/api/judge-challenges"): PUBLIC,
    ("GET", "/api/cases"): PUBLIC,
    ("GET", "/api/cases/{case_id}/evidence"): PUBLIC,
    ("GET", "/api/vc-lenses"): PUBLIC,
    ("GET", "/api/integrity"): PUBLIC,
    ("GET", "/api/benchmark"): PUBLIC,  # recorded scorecards only; never reveals
}
# Edge gate (defence in depth, runs before routing and body parsing). Prefixes, not exact paths, so a new route
# under /api/replay or /api/explore is admin-only until someone decides otherwise (fail closed).
ADMIN_GATED_PREFIXES = ("/api/replay", "/api/explore", "/api/benchmark/compute")
# Exact paths under a gated prefix that are public (read-only). Exact match only: anything below or beside them
# (e.g. /api/replay/recorded/x, /api/replay/recordedx) stays admin-only.
PUBLIC_EXACT_PATHS = frozenset({"/api/replay/recorded"})
# FAULTLINE_PUBLIC_INFERENCE=1 only: the two "inference" rows, POST only, matched in full (anchored, one path
# segment for the id). Nothing else under /api/replay, and never /api/explore or /api/benchmark/compute.
PUBLIC_INFERENCE_PATHS = (
    re.compile(r"/api/replay/run"),
    re.compile(r"/api/replay/[a-z0-9_-]{1,128}/reveal"),
)
ADMIN_MESSAGE = (
    "Admin only on the public demo: this route runs the model, spends paid search credits or reveals sealed "
    "outcomes, and needs the admin token (Authorization: Bearer <FAULTLINE_ADMIN_TOKEN>). The public demo shows "
    "RECORDED RUN data; run FAULTLINE locally (`make demo-scratch`) for live replay and Live Explore."
)


class EdgeErrorCode(StrEnum):
    # Follow-up: move into models.ErrorCode (contract change, see PR #13 description).
    ADMIN_TOKEN_REQUIRED = "ADMIN_TOKEN_REQUIRED"
    RATE_LIMITED = "RATE_LIMITED"
    PAYLOAD_TOO_LARGE = "PAYLOAD_TOO_LARGE"


async def _send_error(
    send: Send, status: int, code: EdgeErrorCode, message: str, extra_headers: list[tuple[bytes, bytes]] | None = None
) -> None:
    body = json.dumps({"code": code.value, "message": message}).encode("utf-8")
    headers = [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]
    await send({"type": "http.response.start", "status": status, "headers": headers + (extra_headers or [])})
    await send({"type": "http.response.body", "body": body})


def _normalised_path(path: str) -> str:
    return re.sub(r"/{2,}", "/", path).lower().rstrip("/")


def is_public_inference_path(method: str, path: str) -> bool:
    """POST /api/replay/run or POST /api/replay/{id}/reveal, exactly (the edge side of FAULTLINE_PUBLIC_INFERENCE)."""
    norm = _normalised_path(path)
    return method.upper() == "POST" and any(p.fullmatch(norm) for p in PUBLIC_INFERENCE_PATHS)


def is_admin_gated(path: str, method: str = "GET", *, public_inference: bool = False) -> bool:
    norm = _normalised_path(path)
    if norm in PUBLIC_EXACT_PATHS:
        return False
    if public_inference and is_public_inference_path(method, path):
        return False  # the route-level gate (routes.public_inference) still applies the safeguards
    return any(norm == p or norm.startswith(p + "/") for p in ADMIN_GATED_PREFIXES)


class AdminGateMiddleware:
    """Public mode: refuse every ADMIN_GATED_PREFIXES path unless a valid admin bearer token is presented."""

    def __init__(self, app: ASGIApp, public_inference: bool = False) -> None:
        self.app = app
        self.public_inference = public_inference

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] == "http"
            and scope["method"] != "OPTIONS"
            and is_admin_gated(scope["path"], scope["method"], public_inference=self.public_inference)
        ):
            auth = dict(scope["headers"]).get(b"authorization", b"").decode("latin-1")
            scheme, _, token = auth.partition(" ")
            token = token.strip()
            # Same statuses as the route-level gate: 401 no bearer token presented, 403 wrong or none configured.
            if scheme.lower() != "bearer" or not token:
                await _send_error(send, 401, EdgeErrorCode.ADMIN_TOKEN_REQUIRED, ADMIN_MESSAGE)
                return
            if not admin_token_matches(token):
                await _send_error(send, 403, EdgeErrorCode.ADMIN_TOKEN_REQUIRED, ADMIN_MESSAGE)
                return
        await self.app(scope, receive, send)


class BodySizeLimitMiddleware:
    """413 when the declared Content-Length or the streamed body exceeds `max_bytes`."""

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        message = f"Request body exceeds {self.max_bytes} bytes."
        declared = dict(scope["headers"]).get(b"content-length")
        if declared is not None and declared.isdigit() and int(declared) > self.max_bytes:
            await _send_error(send, 413, EdgeErrorCode.PAYLOAD_TOO_LARGE, message)
            return

        # Streamed (chunked) bodies: once the limit is crossed, the app sees a client disconnect, whatever it
        # answers is dropped, and the client gets 413 instead. (Raising from receive() would be swallowed by
        # FastAPI's body parser and turned into a 400.)
        received = 0
        too_large = False
        started = False

        async def limited_receive() -> Message:
            nonlocal received, too_large
            if too_large:
                return {"type": "http.disconnect"}
            msg = await receive()
            if msg["type"] == "http.request":
                received += len(msg.get("body", b""))
                if received > self.max_bytes:
                    too_large = True
                    return {"type": "http.disconnect"}
            return msg

        async def guarded_send(msg: Message) -> None:
            nonlocal started
            if too_large and not started:
                return
            if msg["type"] == "http.response.start":
                started = True
            await send(msg)

        try:
            await self.app(scope, limited_receive, guarded_send)
        except Exception:
            if not too_large:
                raise
        if too_large and not started:
            await _send_error(send, 413, EdgeErrorCode.PAYLOAD_TOO_LARGE, message)


class TokenBucketLimiter:
    """Per-key token bucket: `per_minute` capacity, refilled continuously. LRU-bounded memory.

    In-process state: with N uvicorn workers the effective limit is N x per_minute (deploy runs 1 worker).
    """

    def __init__(self, per_minute: int, clock: Callable[[], float] = time.monotonic, max_clients: int = 10_000):
        self.capacity = float(per_minute)
        self.rate = per_minute / 60.0
        self.clock = clock
        self.max_clients = max_clients
        self._buckets: OrderedDict[str, tuple[float, float]] = OrderedDict()

    def __len__(self) -> int:
        return len(self._buckets)

    def check(self, key: str) -> tuple[bool, int]:
        """Returns (allowed, retry_after_seconds)."""
        now = self.clock()
        tokens, last = self._buckets.pop(key, (self.capacity, now))
        tokens = min(self.capacity, tokens + (now - last) * self.rate)
        allowed = tokens >= 1.0
        if allowed:
            tokens -= 1.0
        self._buckets[key] = (tokens, now)
        while len(self._buckets) > self.max_clients:
            self._buckets.popitem(last=False)
        retry_after = 0 if allowed else max(1, math.ceil((1.0 - tokens) / self.rate))
        return allowed, retry_after


class RateLimitMiddleware:
    """429 per client IP. Behind Caddy, uvicorn --proxy-headers sets scope["client"] from X-Forwarded-For."""

    def __init__(self, app: ASGIApp, per_minute: int) -> None:
        self.app = app
        self.limiter = TokenBucketLimiter(per_minute)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            allowed, retry_after = self.limiter.check(client_key(scope.get("client")))
            if not allowed:
                await _send_error(
                    send,
                    429,
                    EdgeErrorCode.RATE_LIMITED,
                    "Too many requests from this address. Try again shortly.",
                    [(b"retry-after", str(retry_after).encode())],
                )
                return
        await self.app(scope, receive, send)


class ModeHeaderMiddleware:
    """Every response says which mode the API runs in (`public` | `local`)."""

    def __init__(self, app: ASGIApp, mode: str) -> None:
        self.app = app
        self.header = (MODE_HEADER.lower().encode(), mode.encode())

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_mode(msg: Message) -> None:
            if msg["type"] == "http.response.start":
                msg = {**msg, "headers": [*msg.get("headers", []), self.header]}
            await send(msg)

        await self.app(scope, receive, send_with_mode)


def _disable_api_docs(app: FastAPI) -> None:
    """Public mode serves no /docs, /redoc or /openapi.json (the web app does not fetch them; generate types locally).

    FastAPI registers these routes in its constructor, so they are removed here to keep this change inside the
    edge-protection block instead of editing the FastAPI(...) call.
    """
    doc_paths = {app.openapi_url, app.docs_url, app.redoc_url, app.swagger_ui_oauth2_redirect_url} - {None}
    app.router.routes[:] = [r for r in app.router.routes if getattr(r, "path", None) not in doc_paths]
    app.openapi_url = app.docs_url = app.redoc_url = app.swagger_ui_oauth2_redirect_url = None


def install_edge_protection(app: FastAPI, settings: Settings) -> None:
    # Starlette: the last middleware added is the outermost. Request order (outer -> inner):
    # CORS -> mode header -> rate limit -> body limit -> admin gate -> routes.
    # CORS is outermost so 403/413/429 bodies stay readable by the allowed web origin.
    if settings.mode == "public":
        _disable_api_docs(app)
        app.add_middleware(AdminGateMiddleware, public_inference=settings.public_inference)
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_body_bytes)
    if settings.rate_limit_per_min > 0:
        app.add_middleware(RateLimitMiddleware, per_minute=settings.rate_limit_per_min)
    app.add_middleware(ModeHeaderMiddleware, mode=settings.mode)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_methods=["GET", "POST"],
        # Authorization only with FAULTLINE_PUBLIC_INFERENCE=1 (presenter mode: the team's admin token from the
        # allowlisted site, for queue priority and no per-IP budget). Otherwise the token is never sent from a browser.
        # Never credentials or cookies; the token is compared in constant time (config.admin_token_matches).
        allow_headers=["Content-Type", "Authorization"] if settings.public_inference else ["Content-Type"],
        allow_credentials=False,
        expose_headers=[MODE_HEADER, "Retry-After"],
        max_age=600,
    )


# ==== END edge protection ====


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="FAULTLINE API",
        version="0.1.0",
        description="Time-aware decision intelligence: Blind Replay, deterministic simulation, honest scoring.",
    )
    install_edge_protection(app, settings)  # edge protection (#13); keep router registrations below
    app.add_exception_handler(FaultlineError, faultline_error_handler)
    app.include_router(health.router, prefix="/api")
    app.include_router(simulate.router, prefix="/api")
    app.include_router(optimize.router, prefix="/api")
    app.include_router(scenarios.router, prefix="/api")
    app.include_router(decision.router, prefix="/api")
    app.include_router(judge_challenges.router, prefix="/api")
    app.include_router(research.router, prefix="/api")
    app.include_router(cases.router, prefix="/api")
    app.include_router(replay.router, prefix="/api")
    app.include_router(recorded.router, prefix="/api")
    app.include_router(integrity.router, prefix="/api")
    app.include_router(benchmark.router, prefix="/api")
    # LIVE EXPLORE (Tavily). Admin-gated inside the route in public mode; never used by the Blind Replay (#60).
    app.include_router(explore.router, prefix="/api")
    return app


app = create_app()
