"""Opt-in public live inference (FAULTLINE_PUBLIC_INFERENCE=1, public mode only): route gate and safeguards.

With the flag off (the default) nothing here changes behaviour: run and reveal keep the admin gate
(``routes.replay.require_admin_in_public_mode``). With the flag on in public mode:

- ``POST /api/replay/run`` and ``POST /api/replay/{id}/reveal`` accept anonymous callers (the edge gate lets exactly
  these two through, ``main.PUBLIC_INFERENCE_PATHS``);
- per-IP budgets per ``config.INFERENCE_WINDOW_S``: ``inference_per_ip`` runs and ``reveal_per_ip`` reveals, else
  429 ``RATE_LIMITED`` with Retry-After. Same client key as the edge limiter (``client_ip.client_key``: the TCP peer,
  or X-Forwarded-For only as set by uvicorn from the trusted edge subnet);
- one global ``InferenceGate``: at most ``inference_concurrency`` model runs at once, at most ``inference_queue``
  anonymous requests waiting, each for at most ``inference_max_wait_s``; else 503 ``BUSY`` with Retry-After.
  Waiting requests poll with ``asyncio.sleep`` and hold no worker thread. (Loop-agnostic like
  ``routes.optimize.SolveSlots``: an ``asyncio.Semaphore`` would bind to one event loop.)
- a valid admin token (presenter mode) skips the per-IP budgets, jumps to the front of the queue and is never
  refused for a full queue, but still waits for the running model call (never two at once, never preempted) and
  still gets BUSY after the max wait. A presented but wrong token is 403, never a silent downgrade.

Startup refuses the flag unless FAULTLINE_DEMO_STORE marks a scratch store (config._check_public_inference_store),
so public runs never touch the official store and every scorecard computed from them is NOT OFFICIAL (#155).
"""

from __future__ import annotations

import asyncio
import itertools
import math
import threading
import time
from collections import OrderedDict, deque
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass

from fastapi import Request

from client_ip import client_key
from config import INFERENCE_WINDOW_S, Settings, admin_token_matches, get_settings
from errors import FaultlineError
from models import ErrorCode
from routes import RouteError

BUSY_RETRY_AFTER_S = 60
_POLL_S = 0.05
BUSY_MESSAGE = (
    "The live model is busy (one CPU forecast at a time, a few minutes each) and the queue is full or the wait ran "
    "out. No forecast was made for this request; try again later, or view the RECORDED RUN."
)
RUN_LIMIT_MESSAGE = "Live forecast limit reached for this address. No forecast was made; try again later."
REVEAL_LIMIT_MESSAGE = "Reveal limit reached for this address. Nothing was revealed; try again later."
_WRONG_TOKEN_MESSAGE = (
    "The presented admin token is not valid (presenter mode). Clear it to continue as a public visitor."
)


# ---------------------------------------------------------------- per-IP budget


class SlidingWindowLimiter:
    """At most `limit` hits per key in any `window_s` seconds. LRU-bounded memory; in-process (one worker)."""

    def __init__(self, window_s: float = INFERENCE_WINDOW_S, clock: Callable[[], float] = time.monotonic,
                 max_clients: int = 10_000) -> None:
        self.window_s = float(window_s)
        self.clock = clock
        self.max_clients = max_clients
        self._hits: OrderedDict[str, deque[float]] = OrderedDict()
        self._lock = threading.Lock()

    def hit(self, key: str, limit: int) -> tuple[bool, int]:
        """Records a hit if allowed. Returns (allowed, retry_after_seconds)."""
        with self._lock:
            now = self.clock()
            hits = self._hits.pop(key, deque())
            while hits and hits[0] <= now - self.window_s:
                hits.popleft()
            allowed = len(hits) < limit
            if allowed:
                hits.append(now)
            self._hits[key] = hits
            while len(self._hits) > self.max_clients:
                self._hits.popitem(last=False)
            retry = 0 if allowed else max(1, math.ceil(hits[0] + self.window_s - now))
            return allowed, retry

    def refund(self, key: str) -> None:
        """Undo the latest hit (the request was refused as BUSY before any model call)."""
        with self._lock:
            hits = self._hits.get(key)
            if hits:
                hits.pop()


# ---------------------------------------------------------------- global model-run gate


@dataclass(eq=False)
class _Ticket:
    admin: bool
    seq: int


class InferenceGate:
    """Concurrency cap + bounded priority queue for model runs (admins first, FIFO within each class)."""

    def __init__(self, clock: Callable[[], float] = time.monotonic, poll_s: float = _POLL_S) -> None:
        self.clock = clock
        self.poll_s = poll_s
        self._lock = threading.Lock()
        self._running = 0
        self._waiting: list[_Ticket] = []
        self._seq = itertools.count()

    @property
    def running(self) -> int:
        with self._lock:
            return self._running

    @property
    def waiting(self) -> int:
        with self._lock:
            return len(self._waiting)

    def _enqueue(self, admin: bool, queue_limit: int) -> _Ticket | None:
        ticket = _Ticket(admin=admin, seq=next(self._seq))
        if admin:
            # Front of the queue, behind earlier admins only.
            index = sum(1 for t in self._waiting if t.admin)
        else:
            if sum(1 for t in self._waiting if not t.admin) >= queue_limit:
                return None
            index = len(self._waiting)
        self._waiting.insert(index, ticket)
        return ticket

    async def acquire(self, *, admin: bool, concurrency: int, queue_limit: int, max_wait_s: float) -> bool:
        with self._lock:
            if not self._waiting and self._running < concurrency:
                self._running += 1
                return True
            ticket = self._enqueue(admin, queue_limit)
        if ticket is None:
            return False
        deadline = self.clock() + max_wait_s
        try:
            while True:
                with self._lock:
                    if self._running < concurrency and self._waiting and self._waiting[0] is ticket:
                        self._waiting.pop(0)
                        self._running += 1
                        return True
                if self.clock() >= deadline:
                    return False
                await asyncio.sleep(self.poll_s)
        finally:
            with self._lock:
                if ticket in self._waiting:
                    self._waiting.remove(ticket)

    def release(self) -> None:
        with self._lock:
            if self._running <= 0:
                raise RuntimeError("InferenceGate released more often than acquired")
            self._running -= 1


GATE = InferenceGate()
RUN_LIMITER = SlidingWindowLimiter()
REVEAL_LIMITER = SlidingWindowLimiter()


def reset_state() -> None:
    """Fresh gate and budgets (tests)."""
    global GATE, RUN_LIMITER, REVEAL_LIMITER
    GATE, RUN_LIMITER, REVEAL_LIMITER = InferenceGate(), SlidingWindowLimiter(), SlidingWindowLimiter()


# ---------------------------------------------------------------- route dependencies


@dataclass(frozen=True)
class InferenceAccess:
    """How this request may use run/reveal. `limited`: the public-inference safeguards apply."""

    limited: bool
    admin: bool
    client: str
    settings: Settings | None = None


def _public_mode() -> bool:
    from routes.replay import public_mode  # same fail-closed reading as the admin gate

    return public_mode()


def _access(request: Request) -> InferenceAccess:
    from routes.replay import require_admin_in_public_mode

    key = client_key(request.client)
    if not _public_mode():
        return InferenceAccess(limited=False, admin=False, client=key)  # local mode: open, unchanged
    settings = get_settings()
    if not settings.public_inference:
        require_admin_in_public_mode(request)  # flag off: admin-only, unchanged
        return InferenceAccess(limited=False, admin=True, client=key)
    auth = request.headers.get("authorization")
    if auth is None:
        return InferenceAccess(limited=True, admin=False, client=key, settings=settings)
    scheme, _, presented = auth.partition(" ")
    presented = presented.strip()
    if scheme.lower() != "bearer" or not presented:
        raise FaultlineError(ErrorCode.ADMIN_TOKEN_REQUIRED, _WRONG_TOKEN_MESSAGE, status_code=401)
    if not admin_token_matches(presented):  # constant time; fails closed without a strong configured token
        raise FaultlineError(ErrorCode.ADMIN_TOKEN_REQUIRED, _WRONG_TOKEN_MESSAGE, status_code=403)
    return InferenceAccess(limited=True, admin=True, client=key, settings=settings)


def _budget(access: InferenceAccess, limiter: SlidingWindowLimiter, limit: int, message: str) -> None:
    if not access.limited or access.admin:
        return
    allowed, retry = limiter.hit(access.client, limit)
    if not allowed:
        raise RouteError(ErrorCode.RATE_LIMITED, message, status_code=429, headers={"Retry-After": str(retry)})


def require_run_access(request: Request) -> InferenceAccess:
    """Route gate for POST /api/replay/run (admin-only unless FAULTLINE_PUBLIC_INFERENCE=1 in public mode)."""
    access = _access(request)
    if access.settings is not None:
        _budget(access, RUN_LIMITER, access.settings.inference_per_ip, RUN_LIMIT_MESSAGE)
    return access


def require_reveal_access(request: Request) -> InferenceAccess:
    """Route gate for POST /api/replay/{id}/reveal (same rule; a more generous per-IP budget, no queue)."""
    access = _access(request)
    if access.settings is not None:
        _budget(access, REVEAL_LIMITER, access.settings.reveal_per_ip, REVEAL_LIMIT_MESSAGE)
    return access


@asynccontextmanager
async def model_slot(access: InferenceAccess) -> AsyncIterator[None]:
    """Hold one global model-run slot while the body runs (no-op unless the safeguards apply)."""
    if not access.limited or access.settings is None:
        yield
        return
    s = access.settings
    gate = GATE
    ok = await gate.acquire(
        admin=access.admin, concurrency=s.inference_concurrency, queue_limit=s.inference_queue,
        max_wait_s=s.inference_max_wait_s,
    )
    if not ok:
        if not access.admin:
            RUN_LIMITER.refund(access.client)  # refused before any model call: do not spend the visitor's budget
        raise RouteError(
            ErrorCode.BUSY, BUSY_MESSAGE, status_code=503, headers={"Retry-After": str(BUSY_RETRY_AFTER_S)}
        )
    try:
        yield
    finally:
        gate.release()
