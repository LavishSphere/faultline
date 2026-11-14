"""Benchmark routes (issue #44 part B): POST /api/benchmark/compute (reveals, admin-gated in public mode) and the
read-only GET /api/benchmark (serves recorded scorecards; never reveals, never opens the store or sealed folder).

Written before routes/benchmark.py. Every case here is a SYNTHETIC test fixture built by tests/test_scoring.py.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from test_scoring import AS_OF, rows_for, scored_world
from test_temporal_gate import OUTCOME_LIKE, walk_keys

from core import provenance
from core import store as store_module
from core.evaluator import LABEL_ILLUSTRATIVE, LABEL_INSUFFICIENT, OutcomeVault, Scorecard, build_scorecard
from core.store import PredictionStore
from core.temporal_gate import EvidenceStore
from main import create_app

TOKEN = "c3" * 32  # test-only admin token, `openssl rand -hex 32` shape (public mode requires it)


class _Recorder:
    """sys.audit hook: file opens, directory listings and sqlite connections while active."""

    def __init__(self) -> None:
        self.active = False
        self.events: list[tuple[str, str]] = []

    def __call__(self, event: str, args: tuple) -> None:
        if not self.active:
            return
        if event in ("open", "os.listdir", "os.scandir", "sqlite3.connect") and args and args[0] is not None:
            self.events.append((event, str(args[0])))


_REC = _Recorder()
sys.addaudithook(_REC)


@pytest.fixture
def local_mode(monkeypatch):
    monkeypatch.delenv("FAULTLINE_MODE", raising=False)
    monkeypatch.delenv("FAULTLINE_ADMIN_TOKEN", raising=False)


@pytest.fixture
def world(tmp_path, monkeypatch, local_mode):
    """6 committed SYNTHETIC cases, one persisted agent_only forecast each, outcomes sealed; nothing revealed."""
    vault, cases = scored_world(tmp_path, rows_for(6), official=monkeypatch)
    return tmp_path, vault, cases


def client() -> TestClient:
    return TestClient(create_app())


def reveal_count(db) -> int:
    if not db.exists():
        return 0
    with sqlite3.connect(db) as conn:
        return conn.execute("SELECT count(*) FROM audit_log WHERE kind = 'reveal'").fetchone()[0]


def db_path():
    return store_module.configured_db_path()


def scorecard_files(tmp_path):
    root = tmp_path / "var" / "scorecards"
    return sorted(root.glob("*.json")) if root.is_dir() else []


def compute(c: TestClient, variant: str = "agent_only", **headers):
    return c.post("/api/benchmark/compute", json={"agent_variant": variant}, headers=headers)


# ---------------------------------------------------------------- GET is read-only (written first)


def test_get_with_nothing_recorded_is_not_available_and_creates_nothing(tmp_path, monkeypatch, local_mode):
    monkeypatch.setenv("FAULTLINE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("FAULTLINE_PREDICTIONS_DB", str(tmp_path / "var" / "predictions.sqlite3"))
    resp = client().get("/api/benchmark")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "NOT AVAILABLE"
    assert body["items"] == [] and body["records"] == []
    assert body["provenance"] == "RECORDED_RUN"
    assert any("NOT AVAILABLE" in n for n in body["notes"])
    assert not (tmp_path / "var").exists(), "GET must not create the store or the scorecard folder"


def test_get_never_reveals_and_never_opens_the_store_or_sealed_folder(world):
    tmp_path, _vault, _cases = world
    assert reveal_count(db_path()) == 0
    c = client()
    _REC.events, _REC.active = [], True
    try:
        before = c.get("/api/benchmark")
    finally:
        _REC.active = False
    assert before.status_code == 200 and before.json()["status"] == "NOT AVAILABLE"
    assert reveal_count(db_path()) == 0
    touched = [p for _e, p in _REC.events]
    assert [p for p in touched if "sealed_outcomes" in p] == []
    assert [p for p in touched if "predictions.sqlite3" in p] == []
    assert [e for e, _p in _REC.events if e == "sqlite3.connect"] == []

    # The JSON served before any compute carries no outcome-like key (outcomes exist, sealed, unrevealed).
    assert [path for path, key, _v in walk_keys(before.json()) if OUTCOME_LIKE.search(key)] == []

    # After a compute, GET still never reveals again (the reveal count stays at the compute's count).
    assert compute(c).status_code == 200
    after_compute = reveal_count(db_path())
    assert after_compute == 6
    _REC.events, _REC.active = [], True
    try:
        for _ in range(3):
            assert c.get("/api/benchmark").status_code == 200
    finally:
        _REC.active = False
    assert reveal_count(db_path()) == after_compute
    assert [p for _e, p in _REC.events if "sealed_outcomes" in p or "predictions.sqlite3" in p] == []


def test_get_query_params_cannot_trigger_a_compute(world):
    c = client()
    resp = c.get("/api/benchmark", params={"agent_variant": "agent_only", "compute": "1"})
    assert resp.status_code == 200 and resp.json()["items"] == []
    assert reveal_count(db_path()) == 0


# ---------------------------------------------------------------- POST compute


def test_compute_returns_the_evaluator_scorecard_verbatim_and_records_it(world):
    tmp_path, _vault, _cases = world
    resp = compute(client())
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "AVAILABLE" and body["provenance"] == "RECORDED_RUN"
    (item,) = body["items"]
    (record,) = body["records"]
    card = Scorecard.model_validate(item)
    assert card.label == LABEL_ILLUSTRATIVE  # synthetic fixtures, verbatim from the evaluator
    assert card.n_events == 6 and card.agent_variant == "agent_only"
    assert card.official_blockers == [] and card.exclusions == []

    # Same numbers as calling the evaluator directly on a fresh copy of the world is not possible (the
    # reveal is logged), so check against a second evaluator call on the same, now revealed, store instead.
    again = build_scorecard(
        OutcomeVault(PredictionStore(db_path())), cases=EvidenceStore.from_dir(), case_set="synthetic"
    )
    assert again.model_dump(mode="json") == item

    (path,) = scorecard_files(tmp_path)
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["provenance"] == "RECORDED_RUN" and saved["source"] == "compute_route"
    assert saved["scorecard"] == item
    assert saved["scorecard_sha256"] == provenance.sha256_hex(provenance.canonical_json(item))
    assert record["scorecard_sha256"] == saved["scorecard_sha256"]
    rest = {k: v for k, v in saved.items() if k != "snapshot_sha256"}
    assert saved["snapshot_sha256"] == provenance.sha256_hex(provenance.canonical_json(rest))
    assert saved["agent_models"] == ["ollama/test-model"]
    assert sorted(saved["cases_sha256"]) == [f"synthetic_evt_{i:03d}" for i in range(6)]

    listed = client().get("/api/benchmark").json()
    assert listed["status"] == "AVAILABLE"
    assert listed["items"] == [item]
    assert listed["records"] == [record]


def test_compute_with_no_cases_records_insufficient_data(tmp_path, monkeypatch, local_mode):
    monkeypatch.setenv("FAULTLINE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("FAULTLINE_PREDICTIONS_DB", str(tmp_path / "var" / "predictions.sqlite3"))
    resp = compute(client())
    assert resp.status_code == 200, resp.text
    (item,) = resp.json()["items"]
    assert item["label"] == LABEL_INSUFFICIENT and item["verdict"] == "INSUFFICIENT DATA"
    assert item["n_events"] == 0 and item["provenance"] is None


def test_get_returns_latest_per_variant_in_fixed_order(world):
    c = client()
    first = compute(c, "agent_only").json()["records"][0]
    plus = compute(c, "agent_plus_market").json()
    second = compute(c, "agent_only").json()["records"][0]
    assert datetime.fromisoformat(second["recorded_at"]) > datetime.fromisoformat(first["recorded_at"])
    body = c.get("/api/benchmark").json()
    assert [i["agent_variant"] for i in body["items"]] == ["agent_only", "agent_plus_market"]
    assert body["records"][0] == second
    assert body["records"][1] == plus["records"][0]
    # agent_plus_market had no persisted forecasts: every case excluded, label verbatim INSUFFICIENT DATA.
    assert body["items"][1]["label"] == LABEL_INSUFFICIENT
    assert body["items"][1]["exclusions_by_reason"] == {"no_persisted_prediction": 6}


def test_hosted_comparator_and_unknown_fields_are_refused(world):
    c = client()
    for payload in ({"agent_variant": "hosted_comparator"}, {"agent_variant": "agent_only", "seed": 1}, {}):
        resp = c.post("/api/benchmark/compute", json=payload)
        assert resp.status_code == 422, payload
        assert resp.json()["code"] == "VALIDATION_ERROR"
    assert reveal_count(db_path()) == 0


def test_invalid_case_file_is_data_invalid_and_reveals_nothing(world):
    tmp_path, _vault, _cases = world
    (tmp_path / "data" / "demo_cases" / "broken.json").write_text("{not json", encoding="utf-8")
    resp = compute(client())
    assert resp.status_code == 500
    assert resp.json()["code"] == "DATA_INVALID"
    assert reveal_count(db_path()) == 0
    assert scorecard_files(tmp_path) == []


# ---------------------------------------------------------------- admin gate (public mode)


@pytest.fixture
def public(monkeypatch):
    monkeypatch.setenv("FAULTLINE_MODE", "public")
    monkeypatch.setenv("FAULTLINE_ADMIN_TOKEN", TOKEN)


def _assert_refused(resp, status, tmp_path):
    assert resp.status_code == status, resp.text
    body = resp.json()
    assert body["code"] == "ADMIN_TOKEN_REQUIRED"
    assert isinstance(body["message"], str) and body["message"]
    assert TOKEN not in resp.text
    assert reveal_count(db_path()) == 0
    assert scorecard_files(tmp_path) == []


def test_public_mode_without_credentials_is_401(world, public):
    tmp_path = world[0]
    _assert_refused(compute(client()), 401, tmp_path)


@pytest.mark.parametrize("auth", [f"Basic {TOKEN}", "Bearer ", "Bearer", TOKEN])
def test_public_mode_without_bearer_credentials_is_401(world, public, auth):
    # Same rule as routes/replay.py (shared gate): no bearer token presented -> 401.
    tmp_path = world[0]
    _assert_refused(compute(client(), Authorization=auth), 401, tmp_path)


@pytest.mark.parametrize("auth", ["Bearer wrong-token-" + "x" * 30, f"Bearer {TOKEN}x", f"Bearer {TOKEN[:-1]}"])
def test_public_mode_with_wrong_credentials_is_403(world, public, auth):
    tmp_path = world[0]
    _assert_refused(compute(client(), Authorization=auth), 403, tmp_path)


def test_compute_uses_the_replay_admin_gate():
    from routes import benchmark, replay

    assert benchmark.require_admin_in_public_mode is replay.require_admin_in_public_mode


def test_public_mode_gate_runs_before_body_validation(world, public):
    tmp_path = world[0]
    c = client()
    _assert_refused(c.post("/api/benchmark/compute", content=b"{not json"), 401, tmp_path)
    _assert_refused(c.post("/api/benchmark/compute", json={"agent_variant": "nope"}), 401, tmp_path)


@pytest.mark.parametrize("configured", [None, "", "short-token", " " * 40])
def test_public_mode_with_no_usable_token_configured_fails_closed(world, monkeypatch, configured):
    tmp_path = world[0]
    db = db_path()
    monkeypatch.setenv("FAULTLINE_MODE", "public")
    if configured is None:
        monkeypatch.delenv("FAULTLINE_ADMIN_TOKEN", raising=False)
    else:
        monkeypatch.setenv("FAULTLINE_ADMIN_TOKEN", configured)
    if configured and configured.strip():
        # A set-but-short token in public mode stops the app at startup (config.ConfigError, PR #28): closed.
        from config import ConfigError

        with pytest.raises(ConfigError):
            client()
        assert reveal_count(db) == 0 and scorecard_files(tmp_path) == []
        return
    _assert_refused(compute(client(), Authorization=f"Bearer {TOKEN}"), 403, tmp_path)


@pytest.mark.parametrize("mode", ["PUBLIC", "pubic", "prod", " public "])
def test_any_mode_other_than_local_is_gated(world, monkeypatch, mode):
    tmp_path = world[0]
    db = db_path()
    monkeypatch.setenv("FAULTLINE_MODE", mode)
    monkeypatch.setenv("FAULTLINE_ADMIN_TOKEN", TOKEN)
    if mode.strip().lower() != "public":
        # config.get_settings refuses an unknown mode at startup (PR #28): fail closed, nothing computed.
        from config import ConfigError

        with pytest.raises(ConfigError):
            client()
        assert reveal_count(db) == 0 and scorecard_files(tmp_path) == []
        return
    _assert_refused(compute(client()), 401, tmp_path)


def test_public_mode_with_the_admin_token_computes(world, public):
    resp = compute(client(), Authorization=f"Bearer {TOKEN}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["items"][0]["n_events"] == 6


def test_public_mode_get_needs_no_token_and_still_never_reveals(world, public):
    resp = client().get("/api/benchmark")
    assert resp.status_code == 200
    assert reveal_count(db_path()) == 0


# ---------------------------------------------------------------- recorded snapshots: verification and sources


def test_tampered_snapshot_is_not_served(world):
    tmp_path = world[0]
    c = client()
    good = compute(c).json()
    later = compute(c).json()
    newest = max(
        scorecard_files(tmp_path), key=lambda p: datetime.fromisoformat(json.loads(p.read_text())["recorded_at"])
    )
    data = json.loads(newest.read_text(encoding="utf-8"))
    assert data["recorded_at"] == later["records"][0]["recorded_at"]
    data["scorecard"]["verdict"] = "agent better than market (edited)"
    newest.write_text(json.dumps(data), encoding="utf-8")

    body = c.get("/api/benchmark").json()
    assert body["items"] == good["items"]
    assert body["records"] == good["records"]
    assert any("failed its hash check" in n and newest.name in n for n in body["notes"])


def test_unreadable_snapshot_is_reported_not_served(world):
    tmp_path = world[0]
    c = client()
    good = compute(c).json()
    (tmp_path / "var" / "scorecards" / "agent_only--junk.json").write_text("{", encoding="utf-8")
    body = c.get("/api/benchmark").json()
    assert body["items"] == good["items"]
    assert any("agent_only--junk.json" in n for n in body["notes"])


def test_committed_snapshot_without_its_run_is_not_served(world):
    """A computed card copied into the committed folder (no run manifest, no rows) is refused."""
    tmp_path = world[0]
    c = client()
    computed = compute(c).json()
    data = json.loads(scorecard_files(tmp_path)[0].read_text(encoding="utf-8"))

    from routes.benchmark import write_scorecard_snapshot

    path, _ = write_scorecard_snapshot(
        Scorecard.model_validate(data["scorecard"]),
        tmp_path / "data" / "recorded_runs" / "scorecards",
        source="record_runs_script",
        run_id="run-test",
        recorded_at=AS_OF + timedelta(days=3650),
        agent_models=data["agent_models"],
        cases_sha256=data["cases_sha256"],
    )
    body = c.get("/api/benchmark").json()
    assert [r["origin"] for r in body["records"]] == ["computed"]
    assert body["items"] == computed["items"]
    assert any(path.name in n and "no manifest.json" in n for n in body["notes"])


def test_benchmark_routes_are_in_openapi_with_admin_error_shape(local_mode):
    schema = client().get("/openapi.json").json()
    paths = schema["paths"]
    assert "get" in paths["/api/benchmark"]
    op = paths["/api/benchmark/compute"]["post"]
    for status in ("401", "403"):
        ref = op["responses"][status]["content"]["application/json"]["schema"]["$ref"]
        body = schema["components"]["schemas"][ref.rsplit("/", 1)[-1]]
        assert set(body["properties"]) == {"code", "message"}
    req = op["requestBody"]["content"]["application/json"]["schema"]["$ref"]
    req_schema = schema["components"]["schemas"][req.rsplit("/", 1)[-1]]
    assert set(req_schema["properties"]) == {"agent_variant"}
    get_ok = paths["/api/benchmark"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    env = schema["components"]["schemas"][get_ok.rsplit("/", 1)[-1]]
    assert {"status", "items", "notes"} <= set(env["properties"])
