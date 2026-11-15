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
from core.evaluator import (
    AGENT_BETTER,
    LABEL_ILLUSTRATIVE,
    NO_IMPROVEMENT,
    brier,
    correct_at_half,
    log_loss,
    paired_bootstrap,
)
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
    store = PredictionStore(store_module.configured_db_path(), clock=Clock(AS_OF + timedelta(days=60)))
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
            provenance="REAL_HISTORICAL",
            label="OFFICIAL: Computed from 6 historical cases",
            official_blockers=[],
            case_set="real",  # relabelled consistently, so only the run's rows can catch it
        ),
        "differs from the run's scored rows",
    ),
    "official_in_the_synthetic_case_set": (
        lambda raw: raw["scorecard"].update(
            provenance="REAL_HISTORICAL", label="OFFICIAL: Computed from 6 historical cases", official_blockers=[]
        ),
        "a synthetic case-set card is never OFFICIAL",
    ),
    "synthetic_case_set_relabelled_real_without_provenance": (
        _set(("scorecard", "case_set"), "real"),
        "a real case-set card cannot have provenance SYNTHETIC",
    ),
    "synthetic_market_label_on_real_refs": (
        _set(
            ("scorecard", "market_label"),
            "SYNTHETIC market price (invented for this fallback case; not a real venue), not a true probability",
        ),
        "market_label does not match",
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


# ---------------------------------------------------------------- per-event p_yes (#180)


def _forge_p(field, value):
    def mutate(raw):
        raw["scorecard"]["per_event"][0][field] = value

    return mutate


def _forge_p_with_matching_scores(raw):
    """A forger who changes the agent's p AND its scores consistently, then fixes summary/CI: only the run's rows
    can catch it."""
    card = raw["scorecard"]
    e, v = card["per_event"][0], card["agent_variant"]
    q = 1.0 - e["agent_p_yes"]
    e["agent_p_yes"] = q
    e["brier"][v], e["log_loss"][v], e["accuracy_at_0_5"][v] = (
        brier(q, e["y"]),
        log_loss(q, e["y"]),
        correct_at_half(q, e["y"]),
    )
    recompute_numbers(card)


P_FORGERIES = {
    "agent_p_beside_real_brier": (_forge_p("agent_p_yes", 0.5), "agent_p_yes is not the input of the row's agent_only"),
    "market_p_beside_real_brier": (_forge_p("market_p_yes", 0.99), "market_p_yes is not the input of the row's market"),
    "p_and_scores_forged_together": (_forge_p_with_matching_scores, "do not recompute from the run's rows"),
    "committed_row_without_p": (_forge_p("agent_p_yes", None), "agent_p_yes / market_p_yes differ from the run's rows"),
}


def test_committed_card_carries_the_run_rows_p_yes(committed):
    rows = {
        r["prediction"]["prediction_id"]: r
        for r in (json.loads(f.read_text()) for f in (committed.run_dir / "rows").glob("*.json"))
    }
    for variant in committed.paths:
        for e in real(committed, variant)["scorecard"]["per_event"]:
            (pid,) = e["prediction_ids"]
            assert e["agent_p_yes"] == rows[pid]["prediction"]["p_yes"]
            assert e["market_p_yes"] == rows[pid]["context"]["market_baseline_p_yes"]
            assert e["brier"][variant] == brier(e["agent_p_yes"], e["y"])
            assert e["brier"]["market"] == brier(e["market_p_yes"], e["y"])


@pytest.mark.parametrize("rule", sorted(P_FORGERIES))
def test_forged_p_yes_is_not_served(committed, rule):
    mutate, why = P_FORGERIES[rule]
    raw = real(committed)
    mutate(raw)
    name = plant(committed, raw)
    assert_not_served(committed, name, why)
    record, problems = verify_snapshot(
        reseal(raw), origin="committed", file_name=name, runs_root=committed.out / "runs"
    )
    assert record is None and any(why in x for x in problems), problems


@pytest.mark.parametrize("rule", ["agent_p_beside_real_brier", "market_p_beside_real_brier"])
def test_forged_p_yes_is_refused_without_a_run(committed, rule):
    """verify_snapshot's own consistency check (scorecard_problems), with no run rows to compare against."""
    mutate, why = P_FORGERIES[rule]
    raw = real(committed)
    mutate(raw)
    record, problems = verify_snapshot(reseal(raw), origin="computed")
    assert record is None and any(why in x for x in problems), problems
    assert verify_snapshot(reseal(real(committed)), origin="computed")[1] == []


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
        # p set to the outcome and its scores to match it (#180), so the row is self-consistent.
        e["agent_p_yes"] = float(e["y"])
        e["brier"]["agent_only"] = 0.0
        e["log_loss"]["agent_only"] = log_loss(float(e["y"]), e["y"])
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
