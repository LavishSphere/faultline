"""No OFFICIAL scorecard from a demo scratch store (issue #155, follow-up to #152).

Written before the blocker. While FAULTLINE_DEMO_STORE is set (scripts/demo_api.py and `make demo-scratch` set it),
``build_scorecard`` adds ``DEMO_SCRATCH_BLOCKER``, so the label is never OFFICIAL, and ``verify_snapshot`` refuses to
serve a COMPUTED card labelled OFFICIAL. Committed recorded runs are verified from files and are unaffected. Without
the variable nothing changes (the rest of the suite runs with it unset, see conftest.py). All cases are SYNTHETIC
fixtures; some are marked real only to exercise the label logic, as in tests/test_scoring.py.
"""

from __future__ import annotations

import json
from datetime import timedelta

from fastapi.testclient import TestClient
from test_predictions_db_setting import _demo_main, _record_runs_store
from test_record_runs import AS_OF, Clock, rr, run
from test_scoring import rows_for, scored_world

from config import get_settings
from core import store as store_module
from core.evaluator import (
    DEMO_SCRATCH_BLOCKER,
    LABEL_ILLUSTRATIVE,
    LABEL_INSUFFICIENT,
    LABEL_NOT_OFFICIAL,
    Scorecard,
    build_scorecard,
)
from core.store import PredictionStore
from main import create_app
from routes.benchmark import computed_dir, verify_snapshot

OFFICIAL_6 = "OFFICIAL: Computed from 6 historical cases"


def _local(monkeypatch):
    monkeypatch.delenv("FAULTLINE_MODE", raising=False)
    monkeypatch.delenv("FAULTLINE_ADMIN_TOKEN", raising=False)


def _demo_on(monkeypatch, tmp_path):
    monkeypatch.setenv("FAULTLINE_DEMO_STORE", str(tmp_path / "demo" / "predictions.sqlite3"))


# ---------------------------------------------------------------- build_scorecard


def test_a_world_that_earns_official_is_blocked_while_the_demo_store_is_set(tmp_path, monkeypatch):
    vault, cases = scored_world(tmp_path, rows_for(6), synthetic=False, official=monkeypatch)
    _demo_on(monkeypatch, tmp_path)
    card = build_scorecard(vault, cases=cases)
    assert card.label == LABEL_NOT_OFFICIAL and card.official_blockers == [DEMO_SCRATCH_BLOCKER]
    assert DEMO_SCRATCH_BLOCKER.startswith("demo_scratch_store: ")
    # Read at call time: the same store and cases earn OFFICIAL once the variable is gone (control).
    monkeypatch.delenv("FAULTLINE_DEMO_STORE")
    again = build_scorecard(vault, cases=cases)
    assert again.label == OFFICIAL_6 and again.official_blockers == []


def test_blank_demo_store_does_not_block(tmp_path, monkeypatch):
    vault, cases = scored_world(tmp_path, rows_for(6), synthetic=False, official=monkeypatch)
    monkeypatch.setenv("FAULTLINE_DEMO_STORE", "  ")
    assert build_scorecard(vault, cases=cases).label == OFFICIAL_6


def test_small_and_synthetic_worlds_keep_their_labels_and_list_the_blocker(tmp_path, monkeypatch):
    vault, cases = scored_world(tmp_path / "small", rows_for(4), synthetic=False, official=monkeypatch)
    _demo_on(monkeypatch, tmp_path)
    small = build_scorecard(vault, cases=cases)
    assert small.label == LABEL_INSUFFICIENT and DEMO_SCRATCH_BLOCKER in small.official_blockers
    monkeypatch.delenv("FAULTLINE_DEMO_STORE")
    vault, cases = scored_world(tmp_path / "syn", rows_for(6), official=monkeypatch)
    _demo_on(monkeypatch, tmp_path)
    syn = build_scorecard(vault, cases=cases, case_set="synthetic")
    assert syn.label == LABEL_ILLUSTRATIVE and DEMO_SCRATCH_BLOCKER in syn.official_blockers


# ---------------------------------------------------------------- compute + GET through the API


def test_compute_on_a_demo_store_records_and_serves_a_not_official_card(tmp_path, monkeypatch):
    _local(monkeypatch)
    scored_world(tmp_path, rows_for(6), synthetic=False, official=monkeypatch)
    _demo_on(monkeypatch, tmp_path)
    client = TestClient(create_app())
    resp = client.post("/api/benchmark/compute", json={"agent_variant": "agent_only"})
    assert resp.status_code == 200, resp.text
    (item,) = resp.json()["items"]
    card = Scorecard.model_validate(item)
    assert card.label == LABEL_NOT_OFFICIAL and DEMO_SCRATCH_BLOCKER in card.official_blockers
    listed = client.get("/api/benchmark").json()
    assert listed["items"] == [item]  # the honest card is served
    assert "OFFICIAL:" not in json.dumps(listed["items"])


def test_an_official_computed_card_is_not_served_while_the_demo_store_is_set(tmp_path, monkeypatch):
    _local(monkeypatch)
    scored_world(tmp_path, rows_for(6), synthetic=False, official=monkeypatch)
    client = TestClient(create_app())
    resp = client.post("/api/benchmark/compute", json={"agent_variant": "agent_only"})  # no demo store: OFFICIAL
    assert resp.json()["items"][0]["label"] == OFFICIAL_6
    (path,) = sorted(computed_dir().glob("*.json"))
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert verify_snapshot(raw, origin="computed")[1] == []

    _demo_on(monkeypatch, tmp_path)
    record, problems = verify_snapshot(raw, origin="computed")
    assert record is None and any("FAULTLINE_DEMO_STORE" in p for p in problems)
    listed = client.get("/api/benchmark").json()
    assert listed["items"] == [] and listed["status"] == "NOT AVAILABLE"
    assert any("FAULTLINE_DEMO_STORE" in n for n in listed["notes"])

    monkeypatch.delenv("FAULTLINE_DEMO_STORE")
    assert client.get("/api/benchmark").json()["items"][0]["label"] == OFFICIAL_6


# ---------------------------------------------------------------- committed recorded runs are unaffected


def test_committed_official_card_still_verifies_while_the_demo_store_is_set(tmp_path, monkeypatch):
    _vault, cases = scored_world(tmp_path, rows_for(6), synthetic=False, official=monkeypatch, save=set())
    store = PredictionStore(store_module.configured_db_path(), clock=Clock(AS_OF + timedelta(days=60)))
    outcome, _ = run((tmp_path, store, cases), variants=("agent_only",))
    (path,) = rr.score_run(outcome.run_dir, store=store, cases=cases, out_root=tmp_path / "out")
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["scorecard"]["label"] == OFFICIAL_6
    _demo_on(monkeypatch, tmp_path)
    runs_root = tmp_path / "out" / "runs"
    assert verify_snapshot(raw, origin="committed", file_name=path.name, runs_root=runs_root)[1] == []


# ---------------------------------------------------------------- launchers


def test_demo_launcher_marks_any_scratch_store_as_a_demo_store(tmp_path, monkeypatch):
    monkeypatch.setenv("FAULTLINE_PREDICTIONS_DB", str(tmp_path / "scratch.sqlite3"))  # no FAULTLINE_DEMO_STORE
    code, _served = _demo_main(monkeypatch)
    assert code == 0 and get_settings().demo_store_set


def test_demo_launcher_on_the_official_store_does_not_set_the_demo_store(monkeypatch):
    monkeypatch.delenv("FAULTLINE_PREDICTIONS_DB", raising=False)
    code, _served = _demo_main(monkeypatch)
    assert code == 0 and not get_settings().demo_store_set


def test_record_runs_warns_when_the_demo_store_is_set(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("FAULTLINE_PREDICTIONS_DB", str(tmp_path / "x.sqlite3"))
    _demo_on(monkeypatch, tmp_path)
    _record_runs_store(monkeypatch, tmp_path)
    assert "FAULTLINE_DEMO_STORE is set, so no scorecard from this run can be OFFICIAL" in capsys.readouterr().out
