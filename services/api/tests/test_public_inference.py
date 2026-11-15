"""Opt-in public live inference (FAULTLINE_PUBLIC_INFERENCE=1): gate, safeguards, scratch store only.

Written before the feature. Flag off: run and reveal stay admin-only (test_routes_replay_admin.py and
test_public_mode_routes.py keep passing unchanged). Flag on, public mode: exactly POST /api/replay/run and
POST /api/replay/{id}/reveal open to anonymous callers, at both the edge and the route; everything else that was
admin stays admin. One model run at a time, a bounded queue (503 BUSY + Retry-After), per-IP budgets (429), admin
priority without bypassing the concurrency cap. Startup refuses the flag without a marked scratch store, and nothing
computed from public runs is OFFICIAL. SYNTHETIC fixtures; the model is a mocked provider; no network.
"""

from __future__ import annotations

import asyncio
import threading
import time

import pytest
from fastapi.testclient import TestClient
from test_routes_replay import EVENT, assert_pre_reveal_clean, make_world

import routes.public_inference as pi
from config import DEFAULT_PREDICTIONS_DB, ConfigError, get_settings
from core.evaluator import DEMO_SCRATCH_BLOCKER
from main import create_app, is_admin_gated
from routes import replay

TOKEN = "c3" * 32  # `openssl rand -hex 32` shape, not key-shaped
ORIGIN = "https://faultline.khayrul.com"
RUN_BODY = {"case_id": EVENT, "variant": "agent_only"}
ADMIN = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture(autouse=True)
def _fresh_state():
    pi.reset_state()
    yield
    pi.reset_state()


def _base_env(monkeypatch):
    for name in ("FAULTLINE_MODE", "FAULTLINE_ADMIN_TOKEN", "FAULTLINE_CORS_ORIGINS", "FAULTLINE_PUBLIC_ORIGIN",
                 "FAULTLINE_RATE_LIMIT_PER_MIN", "FAULTLINE_PUBLIC_INFERENCE", "FAULTLINE_INFERENCE_CONCURRENCY",
                 "FAULTLINE_INFERENCE_QUEUE", "FAULTLINE_INFERENCE_MAX_WAIT_S", "FAULTLINE_INFERENCE_PER_IP",
                 "FAULTLINE_REVEAL_PER_IP"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("FAULTLINE_MODE", "public")
    monkeypatch.setenv("FAULTLINE_ADMIN_TOKEN", TOKEN)
    monkeypatch.setenv("FAULTLINE_PUBLIC_ORIGIN", ORIGIN)


@pytest.fixture
def world_off(tmp_path, monkeypatch):
    world = make_world(tmp_path, monkeypatch)
    _base_env(monkeypatch)
    return world


@pytest.fixture
def world_on(tmp_path, monkeypatch):
    world = make_world(tmp_path, monkeypatch)
    _base_env(monkeypatch)
    monkeypatch.setenv("FAULTLINE_PUBLIC_INFERENCE", "1")
    monkeypatch.setenv("FAULTLINE_DEMO_STORE", str(world.db))  # the scratch store, as compose sets it
    return world


# ---------------------------------------------------------------- configuration


def test_flag_defaults_off(world_off):
    assert get_settings().public_inference is False


@pytest.mark.parametrize("value", ["1", "true", "YES", "on"])
def test_flag_on_values(world_on, monkeypatch, value):
    monkeypatch.setenv("FAULTLINE_PUBLIC_INFERENCE", value)
    s = get_settings()
    assert s.public_inference is True
    assert (s.inference_concurrency, s.inference_queue, s.inference_max_wait_s) == (1, 3, 240)
    assert (s.inference_per_ip, s.reveal_per_ip) == (3, 20)


def test_unclear_flag_value_is_a_config_error(world_off, monkeypatch):
    monkeypatch.setenv("FAULTLINE_PUBLIC_INFERENCE", "maybe")
    with pytest.raises(ConfigError):
        get_settings()


def test_flag_on_without_a_scratch_store_refuses_to_start(world_on, monkeypatch):
    monkeypatch.delenv("FAULTLINE_DEMO_STORE")
    with pytest.raises(ConfigError, match="FAULTLINE_DEMO_STORE"):
        create_app()


def test_flag_on_against_the_official_store_refuses_to_start(world_on, monkeypatch):
    monkeypatch.setenv("FAULTLINE_PREDICTIONS_DB", str(DEFAULT_PREDICTIONS_DB))
    with pytest.raises(ConfigError, match="official"):
        create_app()


@pytest.mark.parametrize("name", ["FAULTLINE_INFERENCE_CONCURRENCY", "FAULTLINE_INFERENCE_PER_IP",
                                  "FAULTLINE_REVEAL_PER_IP", "FAULTLINE_INFERENCE_MAX_WAIT_S"])
def test_zero_caps_are_refused(world_on, monkeypatch, name):
    monkeypatch.setenv(name, "0")
    with pytest.raises(ConfigError):
        get_settings()


# ---------------------------------------------------------------- which routes open


def test_flag_off_run_and_reveal_stay_admin(world_off):
    client = world_off.client()
    assert client.post("/api/replay/run", json=RUN_BODY).json()["code"] == "ADMIN_TOKEN_REQUIRED"
    assert client.post("/api/replay/pred_x/reveal").status_code == 401
    assert world_off.records() == []


def test_flag_on_run_and_reveal_are_public_without_a_token(world_on):
    client = world_on.client()
    run = client.post("/api/replay/run", json=RUN_BODY)
    assert run.status_code == 200, run.text
    assert_pre_reveal_clean(run)  # the leak + canary walk still holds on the public path
    pid = run.json()["prediction"]["prediction_id"]
    assert run.json()["prediction"]["provenance"] == "RECORDED_RUN"
    reveal = client.post(f"/api/replay/{pid}/reveal")
    assert reveal.status_code == 200, reveal.text  # post-reveal: the sealed record (incl. its canary) is the answer
    assert TOKEN not in run.text + reveal.text


@pytest.mark.parametrize(("method", "path"), [
    ("POST", "/api/benchmark/compute"),
    ("POST", "/api/explore/analyze"),
    ("GET", "/api/explore/search?q=x"),
])
def test_flag_on_everything_else_admin_stays_admin(world_on, method, path):
    resp = world_on.client().request(method, path, json={} if method == "POST" else None)
    assert resp.status_code == 401 and resp.json()["code"] == "ADMIN_TOKEN_REQUIRED", resp.text


@pytest.mark.parametrize("path", [
    "/api/replay/run/x", "/api/replay/runx", "/api/replay/a/b/reveal", "/api/replay/x/reveal/more",
    "/api/replay/x/revealx", "/api/replay/x", "/api/replay",
])
def test_edge_opens_only_the_exact_paths(path):
    assert is_admin_gated(path, "POST", public_inference=True), path


def test_edge_opens_post_only():
    assert not is_admin_gated("/api/replay/run", "POST", public_inference=True)
    assert not is_admin_gated("//api/replay//pred_1/reveal/", "POST", public_inference=True)
    assert is_admin_gated("/api/replay/run", "GET", public_inference=True)
    assert is_admin_gated("/api/replay/run", "POST", public_inference=False)


def test_a_wrong_token_is_refused_not_downgraded(world_on):
    client = world_on.client()
    resp = client.post("/api/replay/run", json=RUN_BODY, headers={"Authorization": "Bearer " + "0" * 64})
    assert resp.status_code == 403 and resp.json()["code"] == "ADMIN_TOKEN_REQUIRED"
    resp = client.post("/api/replay/run", json=RUN_BODY, headers={"Authorization": "Basic abc"})
    assert resp.status_code == 401
    assert world_on.records() == []


def test_public_health_reports_the_flag(world_on, monkeypatch):
    body = TestClient(create_app()).get("/api/health").json()
    assert body["public_inference"] is True and isinstance(body["model_ready"], bool)
    assert all(isinstance(v, bool) for k, v in body.items() if k != "status")
    monkeypatch.delenv("FAULTLINE_PUBLIC_INFERENCE")
    assert TestClient(create_app()).get("/api/health").json()["public_inference"] is False


# ---------------------------------------------------------------- CORS (presenter mode)


def _preflight(client, origin: str):
    return client.options("/api/replay/run", headers={
        "Origin": origin, "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "authorization,content-type"})


def test_cors_allows_authorization_only_with_the_flag_and_only_for_the_allowlist(world_on, monkeypatch):
    on = TestClient(create_app())
    ok = _preflight(on, ORIGIN)
    assert ok.status_code == 200
    assert ok.headers["access-control-allow-origin"] == ORIGIN
    assert "authorization" in ok.headers["access-control-allow-headers"].lower()
    assert "access-control-allow-credentials" not in ok.headers  # never credentials or cookies
    bad = _preflight(on, "https://evil.example")
    assert "access-control-allow-origin" not in bad.headers
    monkeypatch.delenv("FAULTLINE_PUBLIC_INFERENCE")
    off = _preflight(TestClient(create_app()), ORIGIN)
    assert off.status_code == 400 or "authorization" not in off.headers.get("access-control-allow-headers", "").lower()


# ---------------------------------------------------------------- per-IP budgets


def test_per_ip_run_limit_is_429_after_three(world_on):
    client = world_on.client()
    codes = [client.post("/api/replay/run", json=RUN_BODY).status_code for _ in range(4)]
    assert codes == [200, 200, 200, 429]
    last = client.post("/api/replay/run", json=RUN_BODY)
    assert last.json()["code"] == "RATE_LIMITED" and int(last.headers["retry-after"]) >= 1
    assert len(world_on.records()) == 3  # the refused requests never ran the model


def test_admin_bypasses_the_per_ip_limit(world_on):
    client = world_on.client()
    for _ in range(3):
        assert client.post("/api/replay/run", json=RUN_BODY).status_code == 200
    assert client.post("/api/replay/run", json=RUN_BODY).status_code == 429
    for _ in range(2):
        assert client.post("/api/replay/run", json=RUN_BODY, headers=ADMIN).status_code == 200


def test_reveal_limit_is_more_generous_and_separate(world_on, monkeypatch):
    monkeypatch.setenv("FAULTLINE_REVEAL_PER_IP", "4")
    client = world_on.client()
    pid = client.post("/api/replay/run", json=RUN_BODY).json()["prediction"]["prediction_id"]
    codes = [client.post(f"/api/replay/{pid}/reveal").status_code for _ in range(5)]
    assert codes == [200, 200, 200, 200, 429]
    monkeypatch.delenv("FAULTLINE_REVEAL_PER_IP")
    assert get_settings().reveal_per_ip == 20 > get_settings().inference_per_ip == 3


def test_sliding_window_unit():
    now = [0.0]
    lim = pi.SlidingWindowLimiter(window_s=600, clock=lambda: now[0])
    assert [lim.hit("a", 3)[0] for _ in range(3)] == [True, True, True]
    allowed, retry = lim.hit("a", 3)
    assert not allowed and retry == 600
    assert lim.hit("b", 3)[0]  # another address has its own budget
    now[0] = 600.0
    assert lim.hit("a", 3)[0]  # the window slid
    lim.refund("a")
    assert lim.hit("a", 3)[0]


# ---------------------------------------------------------------- concurrency + queue


class SlowProvider:
    """Wraps the mocked Ollama provider: blocks (asynchronously) until released; records peak concurrency."""

    def __init__(self, inner_factory):
        self.inner_factory = inner_factory
        self.release = threading.Event()
        self.lock = threading.Lock()
        self.running = 0
        self.peak = 0
        self.order: list[str] = []

    def bind(self, label: str):
        outer = self
        inner = self.inner_factory()

        class _Bound:
            def __getattr__(self, name):
                return getattr(inner, name)

            async def forecast(self, prompt, offered):
                with outer.lock:
                    outer.running += 1
                    outer.peak = max(outer.peak, outer.running)
                    outer.order.append(label)
                try:
                    while not outer.release.is_set():
                        await asyncio.sleep(0.01)
                    return await inner.forecast(prompt, offered)
                finally:
                    with outer.lock:
                        outer.running -= 1

        return _Bound()


def _client_with(world, slow: SlowProvider, label: str) -> TestClient:
    app = create_app()
    app.dependency_overrides[replay.get_provider] = lambda: slow.bind(label)
    return TestClient(app)


def _post_in_thread(world, slow, label, results, headers=None) -> threading.Thread:
    def go():
        results[label] = _client_with(world, slow, label).post("/api/replay/run", json=RUN_BODY,
                                                               headers=headers or {})

    t = threading.Thread(target=go, daemon=True)
    t.start()
    return t


def _wait_for(predicate, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline, "condition not reached"
        time.sleep(0.01)


@pytest.fixture
def slow(world_on, monkeypatch):
    monkeypatch.setenv("FAULTLINE_INFERENCE_PER_IP", "50")  # isolate the queue from the per-IP budget
    s = SlowProvider(lambda: world_on.fake.provider())
    yield s
    s.release.set()


def test_one_run_at_a_time_second_waits_fifth_is_busy(world_on, slow):
    results: dict = {}
    threads = [_post_in_thread(world_on, slow, "r1", results)]
    _wait_for(lambda: slow.running == 1)
    for i, label in enumerate(("r2", "r3", "r4"), start=1):
        threads.append(_post_in_thread(world_on, slow, label, results))
        _wait_for(lambda i=i: pi.GATE.waiting == i)  # enqueue in a known order
    assert slow.running == 1 and "r2" not in results  # the 2nd waits, it is not refused

    started = time.monotonic()
    busy = _client_with(world_on, slow, "r5").post("/api/replay/run", json=RUN_BODY)
    assert time.monotonic() - started < 2.0  # a full queue refuses at once
    assert busy.status_code == 503 and busy.json()["code"] == "BUSY"
    assert int(busy.headers["retry-after"]) > 0
    assert "No forecast was made" in busy.json()["message"]

    slow.release.set()
    for t in threads:
        t.join(15)
    assert [results[k].status_code for k in ("r1", "r2", "r3", "r4")] == [200] * 4
    assert slow.peak == 1  # never two model calls at once
    assert slow.order == ["r1", "r2", "r3", "r4"]  # FIFO
    assert "r5" not in slow.order
    assert pi.GATE.running == 0 and pi.GATE.waiting == 0
    assert len(world_on.records()) == 4


def test_waiting_past_the_max_wait_is_busy(world_on, slow, monkeypatch):
    monkeypatch.setenv("FAULTLINE_INFERENCE_MAX_WAIT_S", "1")
    results: dict = {}
    t = _post_in_thread(world_on, slow, "r1", results)
    _wait_for(lambda: slow.running == 1)
    started = time.monotonic()
    late = _client_with(world_on, slow, "r2").post("/api/replay/run", json=RUN_BODY)
    assert 1.0 <= time.monotonic() - started < 4.0
    assert late.status_code == 503 and late.json()["code"] == "BUSY"
    assert pi.GATE.waiting == 0  # the timed-out waiter left the queue
    slow.release.set()
    t.join(15)
    assert results["r1"].status_code == 200


def test_admin_jumps_the_queue_but_not_the_running_call(world_on, slow):
    results: dict = {}
    threads = [_post_in_thread(world_on, slow, "r1", results)]
    _wait_for(lambda: slow.running == 1)
    for i, label in enumerate(("r2", "r3", "r4"), start=1):  # the public queue is now full
        threads.append(_post_in_thread(world_on, slow, label, results))
        _wait_for(lambda i=i: pi.GATE.waiting == i)
    threads.append(_post_in_thread(world_on, slow, "admin", results, headers=ADMIN))
    _wait_for(lambda: pi.GATE.waiting == 4)  # admitted although the queue is full: never BUSY for a full queue
    time.sleep(0.2)
    assert slow.running == 1 and slow.order == ["r1"]  # it does not preempt or run alongside r1

    slow.release.set()
    for t in threads:
        t.join(15)
    assert all(r.status_code == 200 for r in results.values()), {k: r.text for k, r in results.items()}
    assert slow.peak == 1
    assert slow.order == ["r1", "admin", "r2", "r3", "r4"]  # front of the queue


def test_gate_releases_the_slot_when_the_model_fails(world_on, monkeypatch):
    class Down:
        async def forecast(self, prompt, offered):
            from agents.provider import ModelUnavailable

            raise ModelUnavailable("Ollama not reachable (test)")

    world_on.provider = Down()
    client = world_on.client()
    assert client.post("/api/replay/run", json=RUN_BODY).json()["code"] == "MODEL_UNAVAILABLE"
    assert pi.GATE.running == 0 and world_on.records() == []


def test_gate_unit_priority_and_cap():
    async def scenario():
        gate = pi.InferenceGate(poll_s=0.001)
        assert await gate.acquire(admin=False, concurrency=1, queue_limit=1, max_wait_s=1)
        order: list[str] = []

        async def wait(label, admin):
            ok = await gate.acquire(admin=admin, concurrency=1, queue_limit=1, max_wait_s=1)
            if ok:
                order.append(label)
                gate.release()
            return ok

        public = asyncio.create_task(wait("public", False))
        await asyncio.sleep(0.01)
        refused = await gate.acquire(admin=False, concurrency=1, queue_limit=1, max_wait_s=1)
        admin = asyncio.create_task(wait("admin", True))
        await asyncio.sleep(0.01)
        assert gate.waiting == 2 and not refused
        gate.release()
        assert await public and await admin
        assert order == ["admin", "public"]
        with pytest.raises(RuntimeError):
            gate.release()

    asyncio.run(scenario())


# ---------------------------------------------------------------- scratch store only, never OFFICIAL


def test_public_runs_write_only_the_scratch_store_and_never_make_an_official_card(world_on):
    official_before = DEFAULT_PREDICTIONS_DB.stat().st_mtime_ns if DEFAULT_PREDICTIONS_DB.exists() else None
    client = world_on.client()
    run = client.post("/api/replay/run", json=RUN_BODY)
    assert run.status_code == 200
    pid = run.json()["prediction"]["prediction_id"]
    assert client.post(f"/api/replay/{pid}/reveal").status_code == 200
    assert [r.prediction.prediction_id for r in world_on.records()] == [pid]  # in the scratch store
    official_after = DEFAULT_PREDICTIONS_DB.stat().st_mtime_ns if DEFAULT_PREDICTIONS_DB.exists() else None
    assert official_after == official_before  # the official store was not touched

    card = client.post("/api/benchmark/compute", json={"agent_variant": "agent_only"}, headers=ADMIN)
    assert card.status_code == 200, card.text
    items = card.json()["items"]
    assert items, card.text
    for item in items:
        assert not item["label"].startswith("OFFICIAL")
        assert DEMO_SCRATCH_BLOCKER in item["official_blockers"]
    assert "OFFICIAL:" not in client.get("/api/benchmark").text
