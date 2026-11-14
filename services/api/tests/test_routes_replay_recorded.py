"""GET /api/replay/recorded: committed RECORDED RUN forecasts for one case, pre-reveal safe (issue #116).

Written before routes/recorded.py. The route serves rows of committed, non-dry runs from
<data>/recorded_runs/runs/<run_id>/ after ``routes.benchmark.load_run`` / ``verify_row`` recompute every hash; a
row that fails is skipped with a note. It never opens the sealed folder or the prediction store and returns no
outcome-like key. Every case is a SYNTHETIC fixture; the model is a mocked Ollama transport.
"""

from __future__ import annotations

import builtins
import json
import os
import pathlib
import sqlite3
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from test_record_runs import Clock, FakeModel, rr
from test_routes_replay import OUTCOME_LIKE, outcome_keys
from test_scoring import AS_OF, rows_for, scored_world

from core import store as store_module
from core.store import PredictionStore
from main import create_app
from routes.benchmark import canon_sha

CANARY = f"CANARY-{uuid.uuid4()}"
CASE = "synthetic_evt_000"
TOKEN = "t" * 40


def _world(tmp_path, monkeypatch, *, dry_run: bool = False, score: bool = True):
    """An official-procedure run (mocked model) on 6 SYNTHETIC committed cases, written to
    <data>/recorded_runs/ exactly where the route looks. Every sealed file carries the canary."""
    monkeypatch.delenv("FAULTLINE_MODE", raising=False)
    monkeypatch.delenv("FAULTLINE_ADMIN_TOKEN", raising=False)
    _vault, cases = scored_world(tmp_path, rows_for(6), official=monkeypatch, save=set())
    sealed = tmp_path / "data" / "sealed_outcomes"
    for path in sealed.glob("*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        path.write_text(json.dumps(data | {"notes": CANARY}), encoding="utf-8")
    store = PredictionStore(store_module.configured_db_path(), clock=Clock(AS_OF + timedelta(days=60)))
    out = tmp_path / "data" / "recorded_runs"
    outcome = rr.run_forecasts(
        FakeModel(store.path).provider(),
        cases=cases,
        store=store,
        out_root=out,
        dry_run=dry_run,
        clock=Clock(datetime(2026, 11, 13, 12, 0, tzinfo=UTC)),
    )
    if score and not dry_run:
        rr.score_run(outcome.run_dir, store=store, cases=cases, out_root=out)
    return SimpleNamespace(tmp=tmp_path, store=store, out=out, run_dir=outcome.run_dir, sealed=sealed)


@pytest.fixture
def committed(tmp_path, monkeypatch):
    return _world(tmp_path, monkeypatch)


def get(params: dict | None = None, headers: dict | None = None):
    return TestClient(create_app()).get("/api/replay/recorded", params=params or {}, headers=headers or {})


def manifest(c) -> dict:
    return json.loads((c.run_dir / "manifest.json").read_text(encoding="utf-8"))


def row_path(c, variant: str, case: str = CASE) -> pathlib.Path:
    (meta,) = [m for m in manifest(c)["rows"] if (m["event_id"], m["variant"]) == (case, variant)]
    return c.run_dir / meta["file"]


def read_row(c, variant: str, case: str = CASE) -> dict:
    return json.loads(row_path(c, variant, case).read_text(encoding="utf-8"))


def assert_clean(resp) -> None:
    assert CANARY not in resp.text
    assert outcome_keys(resp.json()) == [], resp.text


# ---------------------------------------------------------------- served rows are the committed rows, verbatim


def test_serves_both_variants_of_the_case_verbatim(committed):
    resp = get({"case_id": CASE})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "AVAILABLE" and body["provenance"] == "RECORDED_RUN"
    assert [i["agent_variant"] for i in body["items"]] == ["agent_only", "agent_plus_market"]
    for item in body["items"]:
        row = read_row(committed, item["agent_variant"])
        pred = row["prediction"]
        assert item["provenance"] == "RECORDED_RUN"
        assert item["run_id"] == committed.run_dir.name == row["run_id"]
        assert item["case_id"] == CASE == pred["event_id"]
        for key in (
            "prediction_id",
            "p_yes",
            "decision",
            "rationale",
            "evidence_ids",
            "agent_model",
            "prompt_sha256",
            "snapshot_sha256",
            "gated_prompt_sha256",
            "model_digest",
        ):
            assert item[key] == pred[key], key
        assert datetime.fromisoformat(item["recorded_at"]) == datetime.fromisoformat(pred["recorded_at"])
        assert datetime.fromisoformat(item["as_of"]) == datetime.fromisoformat(pred["as_of"])
        assert item["row_sha256"] == row["row_sha256"] and item["record_sha256"] == row["record_sha256"]
        assert item["model_tag"] == row["model_call"]["model_tag"]
        assert item["case_synthetic"] is True
        assert item["cited_evidence"] == []  # the fixture cases offer no evidence, so the model cites none
    assert_clean(resp)


def test_variant_filter(committed):
    body = get({"case_id": CASE, "agent_variant": "agent_plus_market"}).json()
    assert [i["agent_variant"] for i in body["items"]] == ["agent_plus_market"]
    assert body["items"][0]["prediction_id"] == read_row(committed, "agent_plus_market")["prediction"]["prediction_id"]


def test_unscored_run_is_served_too(tmp_path, monkeypatch):
    """Forecast rows are saved before any reveal; a non-dry run need not be scored to be shown."""
    c = _world(tmp_path, monkeypatch, score=False)
    assert manifest(c)["phase"] == "forecasts_saved"
    body = get({"case_id": CASE}).json()
    assert body["status"] == "AVAILABLE" and len(body["items"]) == 2


# ---------------------------------------------------------------- refusals


def test_tampered_row_is_skipped_with_a_note(committed):
    path = row_path(committed, "agent_only")
    row = json.loads(path.read_text(encoding="utf-8"))
    row["prediction"]["p_yes"] = 0.99
    path.write_text(json.dumps(row), encoding="utf-8")
    body = get({"case_id": CASE}).json()
    assert body["status"] == "AVAILABLE"
    assert [i["agent_variant"] for i in body["items"]] == ["agent_plus_market"]
    note = next(n for n in body["notes"] if path.name in n)
    assert "skipped" in note and "failed verification" in note
    assert 0.99 not in [i["p_yes"] for i in body["items"]]


def test_resealed_tampered_row_is_still_skipped(committed):
    """A forger who re-hashes the row cannot also make the raw model output and record hash agree."""
    path = row_path(committed, "agent_only")
    row = json.loads(path.read_text(encoding="utf-8"))
    row["prediction"]["p_yes"] = 0.99
    row["row_sha256"] = canon_sha({k: v for k, v in row.items() if k != "row_sha256"})
    path.write_text(json.dumps(row), encoding="utf-8")
    body = get({"case_id": CASE, "agent_variant": "agent_only"}).json()
    assert body["status"] == "NOT AVAILABLE" and body["items"] == []
    assert any(path.name in n for n in body["notes"]), body["notes"]


def test_broken_manifest_index_skips_the_whole_run(committed):
    m = manifest(committed)
    m["rows_sha256"] = "0" * 64
    (committed.run_dir / "manifest.json").write_text(json.dumps(m), encoding="utf-8")
    body = get({"case_id": CASE}).json()
    assert body["status"] == "NOT AVAILABLE" and body["items"] == []
    assert any(committed.run_dir.name in n and "rows_sha256" in n for n in body["notes"]), body["notes"]


def test_manifest_flagged_dry_run_is_not_served(committed):
    m = manifest(committed)
    m["dry_run"] = True
    (committed.run_dir / "manifest.json").write_text(json.dumps(m), encoding="utf-8")
    body = get({"case_id": CASE}).json()
    assert body["status"] == "NOT AVAILABLE" and body["items"] == []
    assert any("dry" in n for n in body["notes"]), body["notes"]


def test_real_dry_run_is_not_served(tmp_path, monkeypatch):
    c = _world(tmp_path, monkeypatch, dry_run=True)
    assert manifest(c)["dry_run"] is True and rr.verify_run(c.run_dir) == []  # intact, just not official
    body = get({"case_id": CASE}).json()
    assert body["status"] == "NOT AVAILABLE" and body["items"] == []
    assert "ollama/dry-run-mock" not in json.dumps(body)


def test_unknown_case_is_not_available(committed):
    body = get({"case_id": "no_such_case"}).json()
    assert body["status"] == "NOT AVAILABLE" and body["items"] == []
    assert any("no_such_case" in n for n in body["notes"]), body["notes"]


def test_nothing_committed_is_not_available(tmp_path, monkeypatch):
    monkeypatch.setenv("FAULTLINE_DATA_DIR", str(tmp_path / "data"))
    body = get({"case_id": CASE}).json()
    assert body == {
        "status": "NOT AVAILABLE",
        "provenance": "RECORDED_RUN",
        "case_id": CASE,
        "items": [],
        "notes": [body["notes"][0]],
    }
    assert "No committed recorded run" in body["notes"][0]


@pytest.mark.parametrize(
    "params",
    [{}, {"case_id": "../etc"}, {"case_id": CASE, "agent_variant": "hosted_comparator"}],
)
def test_bad_queries_are_422(committed, params):
    resp = get(params)
    assert resp.status_code == 422 and resp.json()["code"] == "VALIDATION_ERROR"


# ---------------------------------------------------------------- isolation


def test_no_outcome_key_and_no_canary_after_every_event_was_revealed(committed):
    # score_run revealed every event (the canary is in every sealed file); nothing may surface here.
    for case in [f"synthetic_evt_{i:03d}" for i in range(6)] + ["no_such_case"]:
        for params in ({"case_id": case}, {"case_id": case, "agent_variant": "agent_only"}):
            resp = get(params)
            assert resp.status_code == 200
            assert_clean(resp)


def test_response_schema_has_no_outcome_field():
    from test_routes_replay import _schema_property_names

    doc = TestClient(create_app()).get("/openapi.json").json()
    op = doc["paths"]["/api/replay/recorded"]["get"]
    for status, response in op["responses"].items():
        names = _schema_property_names(response, doc["components"]["schemas"])
        assert names and not [n for n in names if OUTCOME_LIKE.search(n)], (status, names)


def test_never_opens_the_sealed_folder_or_the_prediction_store(committed, monkeypatch):
    opened: list[str] = []
    real_open, real_path_open = builtins.open, pathlib.Path.open

    def spy_open(file, *args, **kwargs):
        opened.append(os.fspath(file) if isinstance(file, (str, os.PathLike)) else repr(file))
        return real_open(file, *args, **kwargs)

    def spy_path_open(self, *args, **kwargs):
        opened.append(os.fspath(self))
        return real_path_open(self, *args, **kwargs)

    def no_sqlite(*_a, **_k):
        raise AssertionError("the recorded route must not open the prediction store")

    client = TestClient(create_app())
    monkeypatch.setattr(builtins, "open", spy_open)
    monkeypatch.setattr(pathlib.Path, "open", spy_path_open)
    monkeypatch.setattr(sqlite3, "connect", no_sqlite)
    assert client.get("/api/replay/recorded", params={"case_id": CASE}).json()["status"] == "AVAILABLE"
    assert any("recorded_runs" in p for p in opened)  # the probe sees the row reads
    assert not [p for p in opened if "sealed_outcomes" in p.casefold()]
    assert not [p for p in opened if p.endswith(".sqlite3")]


def test_public_mode_serves_it_without_a_token(committed, monkeypatch):
    monkeypatch.setenv("FAULTLINE_MODE", "public")
    monkeypatch.setenv("FAULTLINE_ADMIN_TOKEN", TOKEN)
    resp = get({"case_id": CASE})
    assert resp.status_code == 200 and resp.json()["status"] == "AVAILABLE"
    run = TestClient(create_app()).post("/api/replay/run", json={"case_id": CASE, "variant": "agent_only"})
    assert run.status_code == 401  # the live run stays admin-only


@pytest.mark.parametrize(
    ("path", "gated"),
    [
        ("/api/replay/recorded", False),
        ("/api/replay/recorded/", False),
        ("/api/replay/recorded/reveal", True),
        ("/api/replay/recordedx", True),
        ("/api/replay/run", True),
        ("/api/replay/x/reveal", True),
    ],
)
def test_edge_gate_exempts_exactly_the_recorded_path(path, gated):
    from main import is_admin_gated

    assert is_admin_gated(path) is gated
