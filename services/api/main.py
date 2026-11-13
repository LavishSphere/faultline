"""FAULTLINE API entry point. Run from services/api: `uvicorn main:app --reload`."""

from __future__ import annotations

import ipaddress
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

from config import Settings, admin_token_matches, get_settings
from errors import FaultlineError, faultline_error_handler
from routes import health

# ==== BEGIN edge protection (#13 deploy: CORS, mode header, rate limit, body limit, admin gate) ====
# Owned by the deploy issue. Router registrations live in create_app() below, outside this block.
# CORS only constrains browsers; everything else here applies to every client (curl, scripts, bots).

MODE_HEADER = "X-Faultline-Mode"
# Model inference (slow on the CPU server, and the only route that runs the LLM). In public mode it needs
# `Authorization: Bearer <FAULTLINE_ADMIN_TOKEN>`; the public demo serves RECORDED RUN predictions instead.
ADMIN_GATED_PREFIXES = ("/api/replay/run",)


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


def is_admin_gated(path: str) -> bool:
    norm = _normalised_path(path)
    return any(norm == p or norm.startswith(p + "/") for p in ADMIN_GATED_PREFIXES)


class AdminGateMiddleware:
    """Public mode: refuse model-inference paths unless a valid admin bearer token is presented."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["method"] != "OPTIONS" and is_admin_gated(scope["path"]):
            auth = dict(scope["headers"]).get(b"authorization", b"").decode("latin-1")
            scheme, _, token = auth.partition(" ")
            if scheme.lower() != "bearer" or not admin_token_matches(token.strip()):
                await _send_error(
                    send,
                    403,
                    EdgeErrorCode.ADMIN_TOKEN_REQUIRED,
                    "Live model inference is disabled on the public server. The public demo shows RECORDED RUN "
                    "predictions; run `make demo` locally for live replay.",
                )
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


def rate_limit_key(host: str) -> str:
    """IPv4: the address. IPv6: its /64, since one client can rotate through a whole /64 (docs/DEPLOY.md)."""
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return host
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            return str(ip.ipv4_mapped)
        return str(ipaddress.IPv6Network((ip, 64), strict=False))
    return str(ip)


class RateLimitMiddleware:
    """429 per client IP. Behind Caddy, uvicorn --proxy-headers sets scope["client"] from X-Forwarded-For."""

    def __init__(self, app: ASGIApp, per_minute: int) -> None:
        self.app = app
        self.limiter = TokenBucketLimiter(per_minute)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            client = scope.get("client")
            allowed, retry_after = self.limiter.check(rate_limit_key(client[0] if client else "unknown"))
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
        app.add_middleware(AdminGateMiddleware)
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_body_bytes)
    if settings.rate_limit_per_min > 0:
        app.add_middleware(RateLimitMiddleware, per_minute=settings.rate_limit_per_min)
    app.add_middleware(ModeHeaderMiddleware, mode=settings.mode)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],  # no Authorization: the admin token is never sent from a browser
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
    return app


app = create_app()
