"""Issue #118 (re-audit of #111): relabelling a committed case cannot hide it, recorded cards are checked against
their case set, and the official-run pre-flight applies the evaluator's logged-SYNTHETIC reveal exemption.

Written before the fix. Every event here is a SYNTHETIC test fixture from tests/test_scoring.py; the ones marked
real (``synthetic=False``) exist only to exercise the OFFICIAL label logic and are never shown anywhere.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from test_record_runs import Clock, FakeModel, rr
from test_replay_seal import sealed_dict, write_sealed
from test_scoring import AS_OF, _pred, rows_for, scored_world
from test_synthetic_venue import REF, SYN, _add_committed_synthetic_case

from core import store as store_module
from core.evaluator import (
    LABEL_NOT_OFFICIAL,
    MIXED_MARKET_LABEL,
    OutcomeVault,
    build_scorecard,
    case_sets_present,
    event_case_sets,
    first_counted_reveal,
)
from core.store import PredictionStore
from core.temporal_gate import EvidenceStore
from main import create_app
from markets.base import SYNTHETIC_QUOTE_LABEL
from models import Provenance
from routes.benchmark import canon_sha, compute_and_record, scorecard_problems, verify_snapshot

OFFICIAL_10 = "OFFICIAL: Computed from 10 historical cases"


def relabel_as_synthetic(tmp_path, event_id: str) -> EvidenceStore:
    """Edit a committed case file after the run: ``synthetic: true`` / SYNTHETIC. Returns the reloaded cases."""
    path = tmp_path / "data" / "demo_cases" / f"{event_id}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["case"].update(synthetic=True, provenance="SYNTHETIC")
    path.write_text(json.dumps(data), encoding="utf-8")
    return EvidenceStore.from_dir()


def reveal_ids(store: PredictionStore) -> list[str]:
    with sqlite3.connect(store.path) as conn:
        return [r[0] for r in conn.execute("SELECT prediction_id FROM audit_log WHERE kind='reveal' ORDER BY seq")]


# ---------------------------------------------------------------- item 1: relabelling a real case after the run


def test_relabelling_a_real_case_as_synthetic_after_the_run_blocks_official(tmp_path, monkeypatch):
    """The audit repro: 10 real cases with forecasts saved, case 0 flipped to synthetic, reload. The real card
    used to say OFFICIAL from 9 with no exclusion; the case must stay in the real set as context_mismatch."""
    rows = rows_for(10)
    vault, cases = scored_world(tmp_path, rows, synthetic=False, official=monkeypatch)
    assert build_scorecard(vault, cases=cases, case_set="real").label == OFFICIAL_10  # before the edit (no reveal)
    edited = rows[0][0]
    cases = relabel_as_synthetic(tmp_path, edited)
    recs = vault.store.all_records()
    assert cases.public_case(edited).synthetic is True
    assert event_case_sets(cases, recs)[edited] == "real"  # its forecast froze synthetic=False
    assert case_sets_present(vault.store, cases) == ["real"]

    card = build_scorecard(vault, cases=cases, case_set="real")
    assert card.exclusions_by_reason == {"context_mismatch": 1}
    assert [x.event_id for x in card.exclusions] == [edited]
    assert card.n_events == 9 and card.label == LABEL_NOT_OFFICIAL
    assert f"context_mismatch: 1 event(s) ['{edited}']" in card.official_blockers
    assert edited not in reveal_ids(vault.store)  # excluded keys are never revealed

    syn = build_scorecard(vault, cases=cases, case_set="synthetic")
    assert syn.n_events == 0 and syn.exclusions == []  # it is not in the synthetic set at all


def test_relabelled_case_blocks_official_without_a_case_set_too(tmp_path, monkeypatch):
    """Unpartitioned card: the operator-blocker filter must not exempt a case that only the edited file calls
    synthetic."""
    rows = rows_for(10)
    vault, _cases = scored_world(tmp_path, rows, synthetic=False, official=monkeypatch)
    cases = relabel_as_synthetic(tmp_path, rows[0][0])
    card = build_scorecard(vault, cases=cases)
    assert card.exclusions_by_reason == {"context_mismatch": 1}
    assert card.label == LABEL_NOT_OFFICIAL
    assert any(b.startswith("context_mismatch: 1 event(s)") for b in card.official_blockers)


@pytest.mark.parametrize("case_set", ["real", None])
def test_relabelling_a_peeked_real_case_keeps_the_peek_blocker(tmp_path, monkeypatch, case_set):
    """Peek at case 3 (reveal), re-run it, then relabel it synthetic: the ignored post-reveal forecast still
    blocks OFFICIAL (``peeked``), and so does the context_mismatch."""
    rows = rows_for(10)
    vault, cases = scored_world(tmp_path, rows, synthetic=False, official=monkeypatch)
    e, t, *_ = rows[3]
    vault.reveal("pred_003")
    mi = cases.get_as_of(e, t).model_input("agent_only")
    vault.store.save(_pred(mi, "rerun_after_peek", 0.5), mi)
    cases = relabel_as_synthetic(tmp_path, e)
    card = build_scorecard(vault, cases=cases, case_set=case_set)
    assert [p.prediction_id for p in card.ignored_predictions] == ["rerun_after_peek"]
    assert card.label == LABEL_NOT_OFFICIAL
    assert any(b.startswith("persisted_after_outcome_revealed (ignored forecasts)") for b in card.official_blockers)
    assert any(b.startswith("context_mismatch") for b in card.official_blockers)


def test_a_relabelled_case_is_not_exempt_from_the_late_check(tmp_path, monkeypatch):
    """Reveal case 0, save case 9 after it, then relabel case 0 synthetic: the reveal still counts."""
    rows = rows_for(10)
    vault, cases = scored_world(tmp_path, rows, synthetic=False, official=monkeypatch, save=set(range(9)))
    first = vault.reveal("pred_000")
    e, t, *_ = rows[9]
    mi = cases.get_as_of(e, t).model_input("agent_only")
    vault.store.save(_pred(mi, "late", 0.9), mi)
    cases = relabel_as_synthetic(tmp_path, rows[0][0])
    assert first_counted_reveal(vault.store, cases).seq == first.reveal_seq
    card = build_scorecard(vault, cases=cases, case_set="real")
    assert any("cross-event leakage" in b for b in card.official_blockers)


def test_relabelled_case_in_a_benchmark_compute_stays_in_the_real_snapshot(tmp_path, monkeypatch):
    monkeypatch.delenv("FAULTLINE_MODE", raising=False)
    monkeypatch.delenv("FAULTLINE_ADMIN_TOKEN", raising=False)
    rows = rows_for(10)
    scored_world(tmp_path, rows, synthetic=False, official=monkeypatch)
    relabel_as_synthetic(tmp_path, rows[0][0])
    body = TestClient(create_app()).post("/api/benchmark/compute", json={"agent_variant": "agent_only"}).json()
    assert [r["case_set"] for r in body["records"]] == ["real"]
    assert body["items"][0]["label"] == LABEL_NOT_OFFICIAL
    assert body["items"][0]["exclusions_by_reason"] == {"context_mismatch": 1}
    (path,) = sorted((tmp_path / "var" / "scorecards").glob("*.json"))
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert sorted(raw["cases_sha256"]) == sorted(e for e, *_ in rows)
    assert verify_snapshot(raw)[1] == []


# ---------------------------------------------------------------- item 2: real cards never carry synthetic refs


def _real_card(tmp_path, monkeypatch):
    vault, cases = scored_world(tmp_path, rows_for(6), synthetic=False, official=monkeypatch)
    card = build_scorecard(vault, cases=cases, case_set="real")
    assert card.label == "OFFICIAL: Computed from 6 historical cases" and scorecard_problems(card) == []
    return card


def _with_refs(card, refs_by_index: dict[int, list[str]], **update):
    per_event = [
        e.model_copy(update={"market_refs": refs_by_index[i]}) if i in refs_by_index else e
        for i, e in enumerate(card.per_event)
    ]
    return card.model_copy(update={"per_event": per_event, **update})


@pytest.mark.parametrize("case_set", ["real", None])
@pytest.mark.parametrize("all_synthetic", [True, False])
def test_real_card_with_synthetic_market_refs_is_refused(tmp_path, monkeypatch, case_set, all_synthetic):
    card = _real_card(tmp_path, monkeypatch)
    refs = {i: [REF] for i in range(len(card.per_event))} if all_synthetic else {0: [REF]}
    label = SYNTHETIC_QUOTE_LABEL if all_synthetic else MIXED_MARKET_LABEL
    forged = _with_refs(card, refs, market_label=label, case_set=case_set)  # market_label agrees with the refs
    problems = scorecard_problems(forged)
    assert any("synthetic: market refs" in p for p in problems), problems
    assert any("synthetic market_label" in p for p in problems), problems


def test_real_case_set_card_cannot_carry_the_synthetic_market_label(tmp_path, monkeypatch):
    card = _real_card(tmp_path, monkeypatch)
    for label in (SYNTHETIC_QUOTE_LABEL, MIXED_MARKET_LABEL):
        problems = scorecard_problems(card.model_copy(update={"market_label": label}))
        assert any("synthetic market_label" in p for p in problems), problems


def test_synthetic_card_may_carry_synthetic_refs(tmp_path):
    from test_synthetic_venue import synthetic_world

    vault, gate = synthetic_world(tmp_path, 1)
    card = build_scorecard(vault, cases=gate, case_set="synthetic")
    assert card.per_event[0].market_refs == [REF] and card.provenance == Provenance.SYNTHETIC
    assert scorecard_problems(card) == []


# ---------------------------------------------------------------- item 3: cases_sha256 agrees with the case set


def _mixed_snapshots(tmp_path, monkeypatch):
    """6 committed real cases + the committed synthetic SYN (forecast saved); one compute -> real + synthetic."""
    scored_world(tmp_path, rows_for(6), synthetic=False, official=monkeypatch)
    cases = _add_committed_synthetic_case(tmp_path)
    store = PredictionStore(store_module.configured_db_path(), clock=Clock(AS_OF + timedelta(days=61)))
    mi = cases.get_as_of(SYN, AS_OF).model_input("agent_only")
    store.save(_pred(mi, "syn_pred", 0.35), mi)
    out = compute_and_record("agent_only", store=store, cases=cases)
    by_set = {record.scorecard.case_set: json.loads(path.read_text(encoding="utf-8")) for path, record in out}
    assert sorted(by_set) == ["real", "synthetic"]
    for raw in by_set.values():
        assert verify_snapshot(raw)[1] == []
    return by_set


def _reseal(raw: dict) -> dict:
    raw["scorecard_sha256"] = canon_sha(raw["scorecard"])
    raw["snapshot_sha256"] = canon_sha({k: v for k, v in raw.items() if k != "snapshot_sha256"})
    return raw


def test_computed_snapshot_cases_sha256_must_agree_with_its_case_set(tmp_path, monkeypatch):
    snaps = _mixed_snapshots(tmp_path, monkeypatch)
    real, syn = snaps["real"], snaps["synthetic"]
    assert SYN not in real["cases_sha256"] and sorted(syn["cases_sha256"]) == [SYN]

    real["cases_sha256"][SYN] = syn["cases_sha256"][SYN]  # a synthetic case listed on the real card
    record, problems = verify_snapshot(_reseal(real))
    assert record is None and any("cases_sha256" in p and SYN in p for p in problems), problems

    other = sorted(snaps["real"]["cases_sha256"])[0]
    syn["cases_sha256"][other] = "0" * 64  # a real case listed on the synthetic card
    record, problems = verify_snapshot(_reseal(syn))
    assert record is None and any("cases_sha256" in p and other in p for p in problems), problems


def test_mislisted_computed_snapshot_is_not_served(tmp_path, monkeypatch):
    monkeypatch.delenv("FAULTLINE_MODE", raising=False)
    monkeypatch.delenv("FAULTLINE_ADMIN_TOKEN", raising=False)
    real = _mixed_snapshots(tmp_path, monkeypatch)["real"]
    real["cases_sha256"][SYN] = "0" * 64
    real["recorded_at"] = "2999-12-31T00:00:00Z"
    name = "agent_only--29991231T000000000000Z--forged000000.json"
    (tmp_path / "var" / "scorecards" / name).write_text(json.dumps(_reseal(real)), encoding="utf-8")
    body = TestClient(create_app()).get("/api/benchmark").json()
    assert name not in {r["file"] for r in body["records"]}
    assert any(name in n and "cases_sha256" in n for n in body["notes"]), body["notes"]


# ---------------------------------------------------------------- item 4: record_runs pre-flight exemption


def _official_world_with_a_stage_reveal(tmp_path, monkeypatch, logged: str | None):
    """6 committed real cases (no forecasts) + the committed synthetic fallback SYN, forecast (agent_only) and
    revealed in the configured store as on stage. ``logged`` is the sealed provenance written to audit_log for
    that reveal (SYNTHETIC via the vault; REAL_HISTORICAL or NULL written directly)."""
    scored_world(tmp_path, rows_for(6), synthetic=False, official=monkeypatch, save=set())
    cases = _add_committed_synthetic_case(tmp_path)
    store = PredictionStore(store_module.configured_db_path(), clock=Clock(AS_OF + timedelta(days=60)))
    mi = cases.get_as_of(SYN, AS_OF).model_input("agent_only")
    pred = _pred(mi, "stage_syn", 0.35)
    store.save(pred, mi)
    if logged == "SYNTHETIC":
        OutcomeVault(store).reveal("stage_syn")
    elif logged == "REAL_HISTORICAL":
        store.record_reveal(pred, AS_OF + timedelta(days=80), sealed_provenance="REAL_HISTORICAL")
    else:
        with sqlite3.connect(store.path) as conn:  # a reveal logged before #102 (no sealed_provenance)
            conn.execute(
                "INSERT INTO audit_log (kind, prediction_id, event_id, at) VALUES ('reveal', ?, ?, ?)",
                (pred.prediction_id, pred.event_id, (AS_OF + timedelta(days=80)).isoformat()),
            )
    assert reveal_ids(store) == ["stage_syn"]
    return store, cases


def _run(tmp_path, store, cases, model=None, **kw):
    model = model or FakeModel(store.path)
    clock = Clock(datetime(2026, 11, 14, 12, 0, tzinfo=UTC))
    outcome = rr.run_forecasts(model.provider(), cases=cases, store=store, out_root=tmp_path / "out", clock=clock, **kw)
    return outcome, model


def test_logged_synthetic_fallback_reveal_does_not_refuse_the_official_run(tmp_path, monkeypatch):
    store, cases = _official_world_with_a_stage_reveal(tmp_path, monkeypatch, "SYNTHETIC")
    assert first_counted_reveal(store, cases) is None  # the evaluator's own rule, shared by the pre-flight
    # The stage forecast is SYN's one agent_only forecast, so this run takes the other variant (see the clash
    # test below).
    outcome, model = _run(tmp_path, store, cases, variants=("agent_plus_market",))
    assert outcome.complete and len(model.calls) == 7  # 6 real cases + SYN
    paths = rr.score_run(outcome.run_dir, store=store, cases=cases, out_root=tmp_path / "out")
    cards = {
        json.loads(p.read_text(encoding="utf-8"))["scorecard"]["case_set"]: json.loads(p.read_text(encoding="utf-8"))
        for p in paths
    }
    assert cards["real"]["scorecard"]["label"] == "OFFICIAL: Computed from 6 historical cases"
    assert cards["real"]["scorecard"]["official_blockers"] == []
    for p in paths:
        raw = json.loads(p.read_text(encoding="utf-8"))
        assert verify_snapshot(raw, origin="committed", file_name=p.name, runs_root=tmp_path / "out" / "runs")[1] == []


@pytest.mark.parametrize("logged", ["REAL_HISTORICAL", None])
def test_a_fallback_reveal_not_logged_as_synthetic_still_refuses(tmp_path, monkeypatch, logged):
    store, cases = _official_world_with_a_stage_reveal(tmp_path, monkeypatch, logged)
    assert first_counted_reveal(store, cases) is not None
    model = FakeModel(store.path)
    with pytest.raises(rr.Refused, match="already has a reveal"):
        _run(tmp_path, store, cases, model, variants=("agent_plus_market",))
    assert model.calls == []


def test_a_real_reveal_still_refuses_the_official_run(tmp_path, monkeypatch):
    rows = rows_for(6)
    vault, cases = scored_world(tmp_path, rows, synthetic=False, official=monkeypatch, save={0})
    vault.reveal("pred_000")
    store = PredictionStore(store_module.configured_db_path(), clock=Clock(AS_OF + timedelta(days=61)))
    model = FakeModel(store.path)
    with pytest.raises(rr.Refused, match="already has a reveal"):
        _run(tmp_path, store, cases, model, variants=("agent_plus_market",))
    assert model.calls == []


def test_a_fallback_reveal_of_a_relabelled_case_still_refuses(tmp_path, monkeypatch):
    """SYN's committed file says synthetic, but its stage forecast froze synthetic=False (it was made while the
    case was real). Even a reveal logged SYNTHETIC is then not exempt: every forecast must have frozen True."""
    rows = rows_for(6)
    rows = [*rows, (SYN, AS_OF, 0, 0.5, 0.4)]
    vault, _ = scored_world(tmp_path, rows, synthetic=False, official=monkeypatch, save={6})
    store = vault.store
    store.record_reveal(store.get("pred_006"), AS_OF + timedelta(days=80), sealed_provenance="SYNTHETIC")
    cases = relabel_as_synthetic(tmp_path, SYN)
    write_sealed(tmp_path / "data" / "sealed_outcomes", {**sealed_dict(SYN), "provenance": "SYNTHETIC"})
    assert first_counted_reveal(store, cases) is not None
    model = FakeModel(store.path)
    with pytest.raises(rr.Refused, match="already has a reveal"):
        _run(tmp_path, store, cases, model, variants=("agent_plus_market",))
    assert model.calls == []


def test_the_stage_forecast_of_the_fallback_still_clashes_with_the_same_variant(tmp_path, monkeypatch):
    """Known limit (lead policy, #118): the exemption covers the reveal only. The stage forecast is still a
    forecast for SYN x agent_only, so a run of that variant is refused by the one-forecast-per-key check."""
    store, cases = _official_world_with_a_stage_reveal(tmp_path, monkeypatch, "SYNTHETIC")
    model = FakeModel(store.path)
    with pytest.raises(rr.Refused, match=f"forecasts already exist for these case x variant keys.*{SYN}/agent_only"):
        _run(tmp_path, store, cases, model)
    assert model.calls == []
