"""Public-mode hardening from the post-#28 security review (#172).

- GET /api/cases is cached per process; the cached answer is byte-identical to the uncached one, a changed case
  file is re-read and re-checked, and building the cache key never opens a file or lists sealed_outcomes/.
- POST /api/optimize runs at most MAX_CONCURRENT_SOLVES solves at once; over the cap a request waits briefly,
  then gets 503 BUSY with Retry-After (never a cached or partial plan).
- GET /api/health in public mode is booleans only; local mode keeps its full shape.

No test touches the network: Ollama is an httpx.MockTransport or a closed loopback port.
"""

from __future__ import annotations

import builtins
import io
import json
import os
import shutil
import threading
import time
import uuid
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from test_routes_cases import _case, _file

import routes.cases as cases_route
import routes.optimize as optimize_route
from main import create_app
from models import HealthResponse
from routes.health import PublicHealthResponse, get_ollama_transport

REAL_DATA = Path(__file__).resolve().parent.parent / "data"
CANARY = f"CANARY-{uuid.uuid4()}"
TOKEN = "a7" * 32  # `openssl rand -hex 32` shape, not key-shaped
FAKE_TAVILY = "fake-tavily-value-should-never-appear-0003"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for name in ("FAULTLINE_MODE", "FAULTLINE_ADMIN_TOKEN", "FAULTLINE_CORS_ORIGINS", "FAULTLINE_PUBLIC_ORIGIN",
                 "FAULTLINE_RATE_LIMIT_PER_MIN", "FAULTLINE_MAX_BODY_BYTES", "TAVILY_API_KEY", "ANTHROPIC_API_KEY",
                 "FAULTLINE_OLLAMA_MODEL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://127.0.0.1:9")


# ==================================================================================== GET /api/cases cache


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    d = tmp_path / "data"
    (d / "demo_cases").mkdir(parents=True)
    sealed = d / "sealed_outcomes"
    sealed.mkdir()
    (sealed / "case-a.json").write_text(
        json.dumps({"event_id": "case-a", "outcome": "YES", "note": CANARY}), encoding="utf-8"
    )
    monkeypatch.setenv("FAULTLINE_DATA_DIR", str(d))
    return d


def _write(data_dir: Path, event_id: str, **case_overrides) -> Path:
    path = data_dir / "demo_cases" / f"{event_id}.json"
    path.write_text(json.dumps(_file(_case(event_id, **case_overrides))), encoding="utf-8")
    return path


def _count_builds(monkeypatch) -> list[int]:
    calls: list[int] = []
    real = cases_route.build_cases_response

    def counting(settings):
        calls.append(1)
        return real(settings)

    monkeypatch.setattr(cases_route, "build_cases_response", counting)
    return calls


def test_cached_cases_answer_is_byte_identical_on_the_committed_cases(monkeypatch):
    monkeypatch.setenv("FAULTLINE_DATA_DIR", str(REAL_DATA))
    builds = _count_builds(monkeypatch)
    client = TestClient(create_app())
    first = client.get("/api/cases")  # miss: builds and caches
    second = client.get("/api/cases")  # hit
    assert first.status_code == second.status_code == 200
    assert first.json()["status"] == "AVAILABLE" and first.json()["items"]
    assert builds == [1] and len(cases_route.CASES_CACHE) == 1
    # Without the cache (every request rebuilds): the same bytes.
    monkeypatch.setattr(cases_route.CASES_CACHE, "get", lambda key: None)
    uncached = client.get("/api/cases")
    assert builds == [1, 1]
    assert first.content == second.content == uncached.content
    assert first.headers["content-type"] == second.headers["content-type"] == uncached.headers["content-type"]


def test_cache_refreshes_when_a_case_file_changes(data_dir, monkeypatch):
    builds = _count_builds(monkeypatch)
    client = TestClient(create_app())
    path = _write(data_dir, "case-a", title="TEST FIXTURE first title")
    assert client.get("/api/cases").json()["items"][0]["title"] == "TEST FIXTURE first title"
    assert client.get("/api/cases").json()["items"][0]["title"] == "TEST FIXTURE first title"
    assert len(builds) == 1

    _write(data_dir, "case-a", title="TEST FIXTURE a longer second title")  # size and mtime change
    assert client.get("/api/cases").json()["items"][0]["title"] == "TEST FIXTURE a longer second title"
    assert len(builds) == 2

    # Same size, mtime set explicitly: still re-read (key includes mtime_ns and ctime_ns, not only size).
    _write(data_dir, "case-a", title="TEST FIXTURE a longer second TITLE")
    st = path.stat()
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))
    assert client.get("/api/cases").json()["items"][0]["title"] == "TEST FIXTURE a longer second TITLE"
    assert len(builds) == 3


def test_cache_sees_case_files_added_and_removed(data_dir):
    client = TestClient(create_app())
    _write(data_dir, "case-a")
    assert [c["event_id"] for c in client.get("/api/cases").json()["items"]] == ["case-a"]
    b = _write(data_dir, "case-b")
    assert [c["event_id"] for c in client.get("/api/cases").json()["items"]] == ["case-a", "case-b"]
    b.unlink()
    assert [c["event_id"] for c in client.get("/api/cases").json()["items"]] == ["case-a"]


def test_a_refused_case_file_is_never_served_from_the_cache(data_dir):
    client = TestClient(create_app())
    path = _write(data_dir, "case-a")
    assert client.get("/api/cases").status_code == 200  # cached
    # The file now smuggles an outcome: its metadata changed, so it is re-checked and refused.
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["case"]["outcome"] = CANARY
    path.write_text(json.dumps(payload), encoding="utf-8")
    for _ in range(2):  # refusals are not cached either
        resp = client.get("/api/cases")
        assert resp.status_code == 500 and resp.json()["code"] == "DATA_INVALID"
        assert CANARY not in resp.text
    _write(data_dir, "case-a")
    assert client.get("/api/cases").status_code == 200


def test_cached_answer_never_contains_the_sealed_canary(data_dir):
    client = TestClient(create_app())
    _write(data_dir, "case-a")
    for _ in range(3):
        resp = client.get("/api/cases")
        assert resp.status_code == 200 and CANARY not in resp.text
        assert "outcome" not in resp.text.lower()


def test_cache_key_never_opens_a_file_or_lists_sealed_outcomes(data_dir, monkeypatch):
    """The fingerprint is metadata only (stat/lstat/readlink): no open(), no listing of sealed_outcomes/."""
    _write(data_dir, "case-a")
    from config import get_settings

    settings = get_settings()
    opened: list[str] = []
    listed: list[str] = []
    real_open, real_io_open, real_os_open, real_scandir = builtins.open, io.open, os.open, os.scandir

    def spy_open(file, *a, **k):
        opened.append(str(file))
        return real_open(file, *a, **k)

    def spy_os_open(path, *a, **k):
        opened.append(str(path))
        return real_os_open(path, *a, **k)

    def spy_scandir(path="."):
        listed.append(str(path))
        return real_scandir(path)

    monkeypatch.setattr(builtins, "open", spy_open)
    monkeypatch.setattr(io, "open", spy_open)
    monkeypatch.setattr(os, "open", spy_os_open)
    monkeypatch.setattr(os, "scandir", spy_scandir)
    key = cases_route.cases_fingerprint(settings)
    monkeypatch.setattr(builtins, "open", real_open)
    monkeypatch.setattr(io, "open", real_io_open)
    monkeypatch.setattr(os, "open", real_os_open)
    monkeypatch.setattr(os, "scandir", real_scandir)

    assert opened == []
    assert listed and all("sealed_outcomes" not in p for p in listed)
    assert CANARY not in repr(key)
    # A change inside sealed_outcomes/ does not change the key (its contents are not an input).
    (data_dir / "sealed_outcomes" / "case-b.json").write_text("{}", encoding="utf-8")
    assert cases_route.cases_fingerprint(settings) == key


def test_cache_keys_on_the_data_dir(tmp_path, monkeypatch):
    client = TestClient(create_app())
    dirs = []
    for name in ("one", "two"):
        d = tmp_path / name
        (d / "demo_cases").mkdir(parents=True)
        _write(d, f"case-{name}")
        dirs.append(d)
    for d, expected in zip(dirs, ("case-one", "case-two"), strict=True):
        monkeypatch.setenv("FAULTLINE_DATA_DIR", str(d))
        assert [c["event_id"] for c in client.get("/api/cases").json()["items"]] == [expected]
    monkeypatch.setenv("FAULTLINE_DATA_DIR", str(dirs[0]))
    assert [c["event_id"] for c in client.get("/api/cases").json()["items"]] == ["case-one"]


def test_cache_is_bounded():
    cache = cases_route._CasesCache(max_entries=2)
    for i in range(5):
        cache.put((i,), object())  # type: ignore[arg-type]
    assert len(cache) == 2 and cache.get((0,)) is None and cache.get((4,)) is not None


# ==================================================================================== POST /api/optimize cap

SHOCK = {"shock": {"name": "60% drop weeks 5-8", "demand": {"delta": 0.6, "start_week": 5, "end_week": 8}},
         "protect_payroll": True}


@pytest.fixture
def optimize_data(tmp_path, monkeypatch):
    d = tmp_path / "data"
    d.mkdir()
    shutil.copy(REAL_DATA / "demo_business.json", d / "demo_business.json")
    monkeypatch.setenv("FAULTLINE_DATA_DIR", str(d))
    return d


class _BlockingSolve:
    """Stands in for routes.optimize._solve: blocks until released, records peak concurrency."""

    def __init__(self, real):
        self.real = real
        self.release = threading.Event()
        self.lock = threading.Lock()
        self.running = 0
        self.peak = 0
        self.calls = 0

    def __call__(self, body, settings):
        with self.lock:
            self.calls += 1
            self.running += 1
            self.peak = max(self.peak, self.running)
        try:
            assert self.release.wait(10), "test never released the solver"
            return self.real(body, settings)
        finally:
            with self.lock:
                self.running -= 1


def _post_in_thread(app, results: list, index: int) -> threading.Thread:
    def run():
        results[index] = TestClient(app).post("/api/optimize", json=SHOCK)

    t = threading.Thread(target=run, daemon=True)
    t.start()
    return t


def _wait_for(predicate, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline, "condition not reached"
        time.sleep(0.01)


@pytest.fixture
def blocking_solver(optimize_data, monkeypatch):
    assert optimize_route.SOLVE_SLOTS.in_use == 0
    solver = _BlockingSolve(optimize_route._solve)
    monkeypatch.setattr(optimize_route, "_solve", solver)
    yield solver
    solver.release.set()


def test_optimize_cap_is_two_and_over_the_cap_is_a_coded_503(blocking_solver, monkeypatch):
    monkeypatch.setattr(optimize_route, "SOLVE_QUEUE_WAIT_S", 0.2)
    assert optimize_route.MAX_CONCURRENT_SOLVES == 2
    app = create_app()
    results: list = [None, None]
    threads = [_post_in_thread(app, results, i) for i in range(2)]
    _wait_for(lambda: blocking_solver.running == 2)

    started = time.monotonic()
    busy = TestClient(app).post("/api/optimize", json=SHOCK)
    waited = time.monotonic() - started
    assert busy.status_code == 503
    assert busy.json()["code"] == "BUSY"
    assert "No plan was computed" in busy.json()["message"]
    assert busy.headers["retry-after"] == str(optimize_route.BUSY_RETRY_AFTER_S)
    assert set(busy.json()) == {"code", "message", "errors"}  # no plan fields, nothing invented
    assert 0.2 <= waited < 2.0  # it queued for SOLVE_QUEUE_WAIT_S, not longer
    assert blocking_solver.calls == 2  # the refused request never reached the solver

    blocking_solver.release.set()
    for t in threads:
        t.join(10)
    assert [r.status_code for r in results] == [200, 200]
    assert results[0].json()["status"] == "OPTIMAL"
    assert blocking_solver.peak == 2
    assert optimize_route.SOLVE_SLOTS.in_use == 0


def test_optimize_queues_briefly_then_runs(blocking_solver):
    assert optimize_route.SOLVE_QUEUE_WAIT_S <= 2.0
    app = create_app()
    results: list = [None, None, None]
    threads = [_post_in_thread(app, results, i) for i in range(2)]
    _wait_for(lambda: blocking_solver.running == 2)
    threads.append(_post_in_thread(app, results, 2))  # queues: both slots are taken
    time.sleep(0.2)
    assert blocking_solver.calls == 2 and results[2] is None
    blocking_solver.release.set()
    for t in threads:
        t.join(10)
    assert [r.status_code for r in results] == [200, 200, 200]
    assert blocking_solver.peak == 2 and blocking_solver.calls == 3
    assert optimize_route.SOLVE_SLOTS.in_use == 0


def test_invalid_optimize_body_does_not_take_a_slot(blocking_solver, monkeypatch):
    monkeypatch.setattr(optimize_route, "SOLVE_QUEUE_WAIT_S", 0.1)
    app = create_app()
    results: list = [None, None]
    threads = [_post_in_thread(app, results, i) for i in range(2)]
    _wait_for(lambda: blocking_solver.running == 2)
    bad = TestClient(app).post("/api/optimize", json={"shock": {}, "protect_payroll": "maybe"})
    assert bad.status_code == 422 and bad.json()["code"] == "VALIDATION_ERROR"
    blocking_solver.release.set()
    for t in threads:
        t.join(10)


def test_optimize_releases_the_slot_when_the_solve_fails(optimize_data, monkeypatch):
    def broken(body, settings):
        raise optimize_route.RouteError(optimize_route.ErrorCode.DATA_INVALID, "broken fixture", status_code=500)

    monkeypatch.setattr(optimize_route, "_solve", broken)
    client = TestClient(create_app())
    for _ in range(4):  # more than the cap: a leaked slot would turn these into 503s
        assert client.post("/api/optimize", json=SHOCK).status_code == 500
    assert optimize_route.SOLVE_SLOTS.in_use == 0


def test_solve_slots_unit():
    slots = optimize_route.SolveSlots(1)
    assert slots.try_acquire() and not slots.try_acquire()
    import asyncio

    assert asyncio.run(slots.acquire(0.05)) is False
    slots.release()
    assert asyncio.run(slots.acquire(0.05)) is True
    slots.release()
    with pytest.raises(RuntimeError):
        slots.release()


# ==================================================================================== GET /api/health shapes


def _tags(names: list[str]) -> httpx.MockTransport:
    return httpx.MockTransport(lambda request: httpx.Response(200, json={"models": [{"name": n} for n in names]}))


def _health(transport) -> httpx.Response:
    app = create_app()
    app.dependency_overrides[get_ollama_transport] = lambda: transport
    return TestClient(app).get("/api/health")


def test_public_health_is_booleans_only(monkeypatch, tmp_path):
    monkeypatch.setenv("FAULTLINE_MODE", "public")
    monkeypatch.setenv("FAULTLINE_ADMIN_TOKEN", TOKEN)
    monkeypatch.setenv("FAULTLINE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("TAVILY_API_KEY", FAKE_TAVILY)
    monkeypatch.setenv("FAULTLINE_OLLAMA_MODEL", "llama3.1:8b")
    resp = _health(_tags(["llama3.1:8b", "gemma2:2b"]))
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"status": "ok", "model_ready": True, "ollama_reachable": True, "tavily_configured": True,
                    "web_search_provider": "tavily"}  # #214: a provider name, never a key
    assert set(body) == set(PublicHealthResponse.model_fields)
    for secret in ("llama3.1", "gemma2", FAKE_TAVILY, TOKEN, str(tmp_path), "127.0.0.1"):
        assert secret not in resp.text, secret


def test_public_health_ollama_down(monkeypatch):
    monkeypatch.setenv("FAULTLINE_MODE", "public")
    body = TestClient(create_app()).get("/api/health").json()  # closed loopback port
    assert body == {"status": "ok", "model_ready": False, "ollama_reachable": False, "tavily_configured": False,
                    "web_search_provider": None}


def test_public_health_model_missing(monkeypatch):
    monkeypatch.setenv("FAULTLINE_MODE", "public")
    monkeypatch.setenv("FAULTLINE_OLLAMA_MODEL", "llama3.1:8b")
    body = _health(_tags(["gemma2:2b"])).json()
    assert body["ollama_reachable"] is True and body["model_ready"] is False
    # booleans only, except the web_search backend name (#214): one of three fixed names, or null
    assert all(isinstance(v, bool) for k, v in body.items() if k not in ("status", "web_search_provider"))
    assert body["web_search_provider"] in (None, "tavily", "anthropic", "openai")


def test_local_health_shape_is_unchanged(monkeypatch, tmp_path):
    monkeypatch.setenv("FAULTLINE_MODE", "local")
    monkeypatch.setenv("FAULTLINE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("FAULTLINE_OLLAMA_MODEL", "llama3.1:8b")
    body = _health(_tags(["llama3.1:8b", "gemma2:2b"])).json()
    assert set(body) == set(HealthResponse.model_fields)
    assert body["model_ready"] is True
    assert body["ollama_status"]["models"] == ["gemma2:2b", "llama3.1:8b"]
    assert body["ollama_status"]["required_model"] == "llama3.1:8b"
    assert body["optional_keys"] == {"anthropic_api_key": False, "tavily_api_key": False}
