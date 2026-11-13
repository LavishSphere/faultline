"""GET /api/benchmark with COMMITTED snapshots (issue #44 part B, audit of PR #91).

A committed scorecard is served only if it is what the evaluator's display rules give for its own per-event rows
AND it belongs to a scored, non-dry official run (scripts/record_runs.py) whose rows verify and reproduce its
per-event agent and market scores. Each test below forges one rule, re-seals both hashes, and checks the card is
not served. Every case is a SYNTHETIC fixture; the model is a mocked Ollama transport.
"""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import numpy as np
import pytest
from fastapi.testclient import TestClient
from test_record_runs import Clock, FakeModel, rr
from test_scoring import AS_OF, rows_for, scored_world

from core import store as store_module
from core.evaluator import AGENT_BETTER, LABEL_ILLUSTRATIVE, NO_IMPROVEMENT, paired_bootstrap
from core.store import PredictionStore
from main import create_app
from routes.benchmark import canon_sha, verify_snapshot


@pytest.fixture
def committed(tmp_path, monkeypatch):
    """An official-procedure run (mocked model) on 6 SYNTHETIC committed cases, scored, written to
    <data>/recorded_runs/ exactly where GET looks for committed snapshots."""
    monkeypatch.delenv("FAULTLINE_MODE", raising=False)
    monkeypatch.delenv("FAULTLINE_ADMIN_TOKEN", raising=False)
    _vault, cases = scored_world(tmp_path, rows_for(6), official=monkeypatch, save=set())
    store = PredictionStore(store_module.DEFAULT_DB_PATH, clock=Clock(AS_OF + timedelta(days=60)))
    out = tmp_path / "data" / "recorded_runs"
    outcome = rr.run_forecasts(
        FakeModel(store.path).provider(),
        cases=cases,
        store=store,
        out_root=out,
        clock=Clock(datetime(2026, 11, 13, 12, 0, tzinfo=UTC)),
    )
    paths = rr.score_run(outcome.run_dir, store=store, cases=cases, out_root=out)
    by_variant = {json.loads(p.read_text())["agent_variant"]: p for p in paths}
    return SimpleNamespace(tmp=tmp_path, store=store, cases=cases, out=out, run_dir=outcome.run_dir, paths=by_variant)


def get():
    return TestClient(create_app()).get("/api/benchmark").json()


def reseal(raw: dict) -> dict:
    raw["scorecard_sha256"] = canon_sha(raw["scorecard"])
    raw["snapshot_sha256"] = canon_sha({k: v for k, v in raw.items() if k != "snapshot_sha256"})
    return raw


def recompute_numbers(card: dict) -> None:
    """Make summary, CI and verdict consistent with per_event (so only the rule under test can fail)."""
    v = card["agent_variant"]
    pe = card["per_event"]
    card["summary"] = {
        f: {
            "mean_brier": float(np.mean([e["brier"][f] for e in pe])),
            "mean_log_loss": float(np.mean([e["log_loss"][f] for e in pe])),
            "accuracy_at_0_5": float(np.mean([e["accuracy_at_0_5"][f] for e in pe])),
        }
        for f in card["forecasters"]
    }
    boot = paired_bootstrap([e["brier"][v] for e in pe], [e["brier"]["market"] for e in pe])
    card["comparison"].update(mean_delta_brier=boot.mean_delta, ci_low=boot.ci_low, ci_high=boot.ci_high)
    card["verdict"] = AGENT_BETTER if boot.ci_high < 0 else NO_IMPROVEMENT


def plant(c, raw: dict, name: str = "agent_only--29991231T000000000000Z--forged000000.json", listed=True) -> str:
    """Write a forged snapshot into the committed folder, newer than the real one. ``listed``: the forger also
    adds it to the run manifest's scorecards[] (the manifest carries no hash of its own), so the deeper checks
    are what must catch it."""
    raw = reseal(copy.deepcopy(raw) | {"recorded_at": "2999-12-31T00:00:00Z"})
    (c.out / "scorecards" / name).write_text(json.dumps(raw), encoding="utf-8")
    if listed:
        path = c.run_dir / "manifest.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["scorecards"].append({"file": f"scorecards/{name}", "scorecard_sha256": raw["scorecard_sha256"]})
        path.write_text(json.dumps(manifest), encoding="utf-8")
    return name


def assert_not_served(c, name: str, why: str) -> None:
    body = get()
    assert name not in {r["file"] for r in body["records"]}, body["records"]
    note = next((n for n in body["notes"] if name in n), None)
    assert note is not None, body["notes"]
    assert why in note, note


def real(c, variant="agent_only") -> dict:
    return json.loads(c.paths[variant].read_text(encoding="utf-8"))


# ---------------------------------------------------------------- the real run is served, committed first


def test_committed_run_is_served_with_its_origin(committed):
    body = get()
    assert body["status"] == "AVAILABLE"
    assert [(r["origin"], r["agent_variant"]) for r in body["records"]] == [
        ("committed", "agent_only"),
        ("committed", "agent_plus_market"),
    ]
    assert {r["run_id"] for r in body["records"]} == {committed.run_dir.name}
    assert body["items"][0]["label"] == LABEL_ILLUSTRATIVE
    for variant, path in committed.paths.items():
        record, problems = verify_snapshot(
            real(committed, variant), origin="committed", file_name=path.name, runs_root=committed.out / "runs"
        )
        assert problems == [] and record is not None


def test_admin_compute_cannot_hide_the_committed_card(committed):
    client = TestClient(create_app())
    assert client.post("/api/benchmark/compute", json={"agent_variant": "agent_only"}).status_code == 200
    body = client.get("/api/benchmark").json()
    assert [(r["origin"], r["agent_variant"]) for r in body["records"]] == [
        ("committed", "agent_only"),
        ("committed", "agent_plus_market"),
        ("computed", "agent_only"),
    ]
    assert body["records"][0]["file"] == committed.paths["agent_only"].name


# ---------------------------------------------------------------- forged snapshots (one rule each)


def test_auditor_forged_official_card_is_not_served(committed):
    raw = real(committed)
    card = raw["scorecard"]
    card.update(
        label="OFFICIAL: Computed from 40 historical cases",
        verdict=AGENT_BETTER,
        comparison=None,
        provenance="SYNTHETIC",
        n_events=2,
    )
    raw.update(run_id="forged", agent_models=["ollama/dry-run-mock"])
    name = plant(committed, raw)
    assert_not_served(committed, name, "failed checks")
    record, problems = verify_snapshot(
        reseal(raw), origin="committed", file_name=name, runs_root=committed.out / "runs"
    )
    assert record is None and len(problems) >= 3


def _set(path, value):
    def mutate(raw):
        node = raw
        for key in path[:-1]:
            node = node[key]
        node[path[-1]] = value

    return mutate


FORGERIES = {
    "synthetic_labeled_official": (
        _set(("scorecard", "label"), "OFFICIAL: Computed from 6 historical cases"),
        "label must be 'ILLUSTRATIVE: Synthetic demo fixtures'",
    ),
    "official_with_blockers": (
        lambda raw: raw["scorecard"].update(
            provenance="REAL_HISTORICAL",
            label="OFFICIAL: Computed from 6 historical cases",
            official_blockers=["no_persisted_prediction: 1 event(s) ['x']"],
        ),
        "label must be 'ILLUSTRATIVE: Historical cases, not an official run",
    ),
    "official_wrong_n": (
        lambda raw: raw["scorecard"].update(
            provenance="REAL_HISTORICAL", label="OFFICIAL: Computed from 40 historical cases", official_blockers=[]
        ),
        "label must be 'OFFICIAL: Computed from 6 historical cases'",
    ),
    "official_on_synthetic_rows": (
        lambda raw: raw["scorecard"].update(
            provenance="REAL_HISTORICAL", label="OFFICIAL: Computed from 6 historical cases", official_blockers=[]
        ),
        "differs from the run's scored rows",
    ),
    "small_n_not_insufficient": (
        lambda raw: raw["scorecard"].update(per_event=raw["scorecard"]["per_event"][:2], n_events=2),
        "label/verdict/caveat must be ('INSUFFICIENT DATA: No valid comparison'",
    ),
    "agent_better_without_ci": (
        lambda raw: raw["scorecard"].update(verdict=AGENT_BETTER, comparison=None),
        "a comparison with a CI is required",
    ),
    "agent_better_with_ci_reaching_zero": (
        _set(("scorecard", "verdict"), AGENT_BETTER),
        "verdict must be 'No improvement measured'",
    ),
    "no_improvement_with_ci_below_zero": (
        lambda raw: raw["scorecard"]["comparison"].update(ci_low=-0.3, ci_high=-0.1),
        "comparison CI does not recompute",
    ),
    "summary_edited": (
        _set(("scorecard", "summary", "agent_only", "mean_brier"), 0.01),
        "summary does not recompute",
    ),
    "naive_scores_edited": (
        _set(("scorecard", "per_event", 0, "brier", "naive"), 0.2),
        "naive scores are not those of p = 0.5",
    ),
    "dry_run_model": (
        _set(("agent_models",), ["ollama/dry-run-mock"]),
        "dry-run mock",
    ),
    "no_such_run": (
        _set(("run_id",), "forged"),
        "no manifest.json",
    ),
    "prediction_ids_outside_the_run": (
        _set(("scorecard", "per_event", 0, "prediction_ids"), ["rr-other-run"]),
        "prediction_ids are not this run's",
    ),
}


@pytest.mark.parametrize("rule", sorted(FORGERIES))
def test_forged_snapshot_is_not_served(committed, rule):
    mutate, why = FORGERIES[rule]
    raw = real(committed)
    mutate(raw)
    name = plant(committed, raw)
    assert_not_served(committed, name, why)


def test_edited_per_event_score_with_consistent_summary_is_caught_by_the_run_rows(committed):
    """Numbers edited consistently (summary, CI, verdict recomputed) still have to reproduce from the rows."""
    raw = real(committed)
    card = raw["scorecard"]
    for e in card["per_event"]:
        e["brier"]["agent_only"] = 0.0
        e["log_loss"]["agent_only"] = 0.0
        e["accuracy_at_0_5"]["agent_only"] = 1.0
    recompute_numbers(card)
    assert card["verdict"] == AGENT_BETTER  # the forgery would claim a win
    name = plant(committed, raw)
    assert_not_served(committed, name, "agent_only scores do not recompute from the run's rows")


def test_copy_of_a_real_card_under_another_name_is_not_listed(committed):
    name = plant(committed, real(committed), "agent_only--29991231T000000000000Z--copy00000000.json", listed=False)
    assert_not_served(committed, name, "does not list this snapshot")


# ---------------------------------------------------------------- the run behind a committed card


def _edit_manifest(c, **changes):
    path = c.run_dir / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest.update(changes)
    path.write_text(json.dumps(manifest), encoding="utf-8")


@pytest.mark.parametrize(
    ("changes", "why"),
    [
        ({"dry_run": True}, "must be a scored, non-dry run"),
        ({"phase": "forecasts_saved"}, "must be a scored, non-dry run"),
        ({"scorecards": []}, "does not list this snapshot"),
    ],
)
def test_card_from_an_unfit_run_is_not_served(committed, changes, why):
    _edit_manifest(committed, **changes)
    body = get()
    assert [r for r in body["records"] if r["origin"] == "committed"] == []
    assert any(why in n for n in body["notes"]), body["notes"]


def test_card_whose_run_rows_were_tampered_is_not_served(committed):
    manifest = json.loads((committed.run_dir / "manifest.json").read_text(encoding="utf-8"))
    file = committed.run_dir / manifest["rows"][0]["file"]
    row = json.loads(file.read_text(encoding="utf-8"))
    row["prediction"]["p_yes"] = 0.99
    file.write_text(json.dumps(row), encoding="utf-8")
    body = get()
    assert [r for r in body["records"] if r["origin"] == "committed"] == []
    assert any("record_sha256 does not match" in n for n in body["notes"]), body["notes"]
