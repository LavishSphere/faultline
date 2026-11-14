"""Forecast scoring, paired bootstrap and scorecard display rules (MATH_MODEL §6, §9; SPEC §6).

Written before the scoring half of core/evaluator.py. All events here are SYNTHETIC test fixtures; the
few marked synthetic=False exist only to exercise the OFFICIAL label logic and are never shown anywhere.
"""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest
from test_replay_seal import Clock, sealed_dict, write_sealed
from test_temporal_gate import evidence_dict, make_case, make_quote, write_case_file

from core.evaluator import (
    AGENT_BETTER,
    BOOTSTRAP_SEED,
    DEFAULT_RESAMPLES,
    EPS,
    INSUFFICIENT_DATA,
    LABEL_NOT_OFFICIAL,
    NO_IMPROVEMENT,
    OutcomeVault,
    brier,
    build_scorecard,
    correct_at_half,
    log_loss,
    paired_bootstrap,
)
from core.store import PredictionStore
from core.temporal_gate import CaseRecord, EvidenceStore
from models import Prediction, Provenance

AS_OF = datetime(2025, 3, 1, 12, 0, tzinfo=UTC)


# ---------------------------------------------------------------- MATH_MODEL §9 scoring fixtures (exact)


@pytest.mark.parametrize(
    ("p", "y", "b", "ll"),
    [
        (0.7, 1, 0.09, 0.356675),
        (0.7, 0, 0.49, 1.203973),
        (0.5, 1, 0.25, 0.693147),
        (0.5, 0, 0.25, 0.693147),
    ],
)
def test_math_model_section_9_fixtures(p, y, b, ll):
    assert brier(p, y) == pytest.approx(b, abs=1e-12)
    assert log_loss(p, y) == pytest.approx(ll, abs=5e-7)


def test_log_loss_clamps_with_epsilon_1e_6():
    assert EPS == 1e-6
    assert log_loss(0.0, 1) == pytest.approx(13.815511, abs=5e-7)
    assert log_loss(0.0, 1) == pytest.approx(-math.log(1e-6), abs=1e-12)
    assert log_loss(1.0, 0) == pytest.approx(-math.log(1e-6), abs=1e-9)
    assert log_loss(1.0, 1) == pytest.approx(-math.log(1 - 1e-6), abs=1e-15)


@pytest.mark.parametrize(
    ("p", "y", "expected"),
    [(0.5, 0, 1.0), (0.5, 1, 0.0), (0.51, 1, 1.0), (0.49, 1, 0.0), (0.2, 0, 1.0), (1.0, 1, 1.0)],
)
def test_accuracy_at_half_counts_exactly_half_as_no(p, y, expected):
    assert correct_at_half(p, y) == expected


@pytest.mark.parametrize("p", [-0.01, 1.01, float("nan"), float("inf")])
def test_invalid_probability_raises(p):
    for fn in (brier, log_loss, correct_at_half):
        with pytest.raises(ValueError):
            fn(p, 1)


@pytest.mark.parametrize("y", [2, -1, 0.5, True])
def test_invalid_outcome_raises(y):
    with pytest.raises((TypeError, ValueError)):
        brier(0.5, y)


# ---------------------------------------------------------------- paired bootstrap


def test_bootstrap_defaults_are_pre_specified():
    assert DEFAULT_RESAMPLES == 10_000
    assert isinstance(BOOTSTRAP_SEED, int)
    r = paired_bootstrap([0.1, 0.2, 0.3], [0.2, 0.2, 0.2])
    assert (r.n_resamples, r.seed, r.confidence) == (10_000, BOOTSTRAP_SEED, 0.95)


def test_bootstrap_is_deterministic_with_seed():
    rng = np.random.default_rng(0)  # test data only
    a, b = rng.uniform(0, 1, 20).tolist(), rng.uniform(0, 1, 20).tolist()
    r1, r2 = paired_bootstrap(a, b, seed=123), paired_bootstrap(a, b, seed=123)
    assert r1 == r2
    r3 = paired_bootstrap(a, b, seed=124)
    assert (r3.ci_low, r3.ci_high) != (r1.ci_low, r1.ci_high)
    assert r1.mean_delta == pytest.approx(float(np.mean(a) - np.mean(b)), abs=1e-15)
    assert r1.ci_low <= r1.mean_delta <= r1.ci_high


def test_bootstrap_follows_the_documented_algorithm():
    """Resample event indices with replacement (B x n), mean paired difference, 2.5/97.5 percentiles."""
    a = [0.09, 0.49, 0.25, 0.01, 0.36, 0.16, 0.04]
    b = [0.16, 0.36, 0.25, 0.09, 0.25, 0.25, 0.16]
    d = np.asarray(a) - np.asarray(b)
    idx = np.random.default_rng(7).integers(0, len(d), size=(10_000, len(d)))
    lo, hi = np.percentile(d[idx].mean(axis=1), [2.5, 97.5])
    r = paired_bootstrap(a, b, seed=7)
    assert (r.ci_low, r.ci_high) == (float(lo), float(hi))


def test_bootstrap_constant_difference_has_degenerate_ci():
    r = paired_bootstrap([0.01] * 6, [0.16] * 6)
    assert r.ci_low == pytest.approx(-0.15) and r.ci_high == pytest.approx(-0.15)


def test_bootstrap_two_point_extremes():
    r = paired_bootstrap([0.0, 1.0], [0.0, 0.0], seed=1)
    assert (r.ci_low, r.ci_high, r.mean_delta) == (0.0, 1.0, 0.5)


def test_bootstrap_input_validation():
    with pytest.raises(ValueError):
        paired_bootstrap([0.1], [0.1, 0.2])
    with pytest.raises(ValueError):
        paired_bootstrap([], [])
    with pytest.raises(ValueError):
        paired_bootstrap([0.1, float("nan")], [0.1, 0.2])


# ---------------------------------------------------------------- scorecard (display rules)


def scored_world(
    tmp_path,
    rows,
    *,
    synthetic=True,
    real_events=frozenset(),
    likely_events=frozenset(),
    extra_cases=(),
    sealed_provenance=None,
    official=None,
    save=None,
):
    """rows: (event_id, as_of, y, agent_p, market_p or None).

    Builds SYNTHETIC gate cases whose market quote (1h before each as_of) encodes market_p, persists one
    agent_only prediction per row from the gate's ModelInput (which fixes the market baseline, contamination
    flag and synthetic flag before any reveal), and seals each event's outcome. Nothing is revealed here.
    Events in ``real_events`` (or all, if synthetic=False) are marked real only to exercise the label logic.

    ``official=monkeypatch`` writes the cases as committed files under ``tmp/data/demo_cases``, points
    FAULTLINE_DATA_DIR and the default store path at tmp, and uses ``EvidenceStore.from_dir()`` plus the
    configured sealed folder and store: the only setup that can earn the OFFICIAL label.
    ``save`` (indices) limits which rows get a persisted prediction. Returns (vault, cases)."""
    sealed = tmp_path / "data" / "sealed_outcomes"
    if official is not None:
        from core import store as store_module

        official.setenv("FAULTLINE_DATA_DIR", str(tmp_path / "data"))
        official.setenv("FAULTLINE_PREDICTIONS_DB", str(tmp_path / "var" / "predictions.sqlite3"))
        store = PredictionStore(store_module.configured_db_path(), clock=Clock(AS_OF + timedelta(days=60)))
        sealed.mkdir(parents=True, exist_ok=True)
        vault = OutcomeVault(store, clock=Clock(AS_OF + timedelta(days=90)))
    else:
        store = PredictionStore(tmp_path / "var" / "p.sqlite3", clock=Clock(AS_OF + timedelta(days=60)))
        vault = OutcomeVault(store, sealed_dir=sealed, clock=Clock(AS_OF + timedelta(days=90)))

    cutoffs: dict[str, datetime] = {}
    quotes: dict[str, list] = {}
    for event_id, as_of, _y, _a, market_p in rows:
        cutoffs[event_id] = max(as_of, cutoffs.get(event_id, as_of))
        quotes.setdefault(event_id, [])
        if market_p is not None:
            quotes[event_id].append(make_quote(as_of - timedelta(hours=1), repr(float(market_p))))
    records = []
    for event_id, cutoff in cutoffs.items():
        is_real = (not synthetic) or event_id in real_events
        case = make_case(
            event_id,
            as_of=cutoff,
            synthetic=not is_real,
            provenance=Provenance.REAL_HISTORICAL if is_real else Provenance.SYNTHETIC,
            contamination_flag="likely" if event_id in likely_events else "unlikely",
        )
        records.append(CaseRecord(case=case, market_quotes=tuple(quotes[event_id])))
    records += [CaseRecord(case=make_case(e, as_of=AS_OF)) for e in extra_cases]
    gate = EvidenceStore(records)
    if official is not None:
        write_committed_cases(tmp_path / "data" / "demo_cases", records)
        gate = EvidenceStore.from_dir()

    for i, (event_id, as_of, y, agent_p, _m) in enumerate(rows):
        is_real = (not synthetic) or event_id in real_events
        data = sealed_dict(event_id, outcome="YES" if y else "NO")
        data["provenance"] = (sealed_provenance or {}).get(event_id, "REAL_HISTORICAL" if is_real else "SYNTHETIC")
        write_sealed(sealed, data)
        if save is not None and i not in save:
            continue
        snap = gate.get_as_of(event_id, as_of)
        mi = snap.model_input("agent_only")
        pred = Prediction(
            prediction_id=f"pred_{i:03d}",
            event_id=event_id,
            as_of=as_of,
            agent_model="ollama/test-model",
            variant="agent_only",
            p_yes=agent_p,
            decision="wait",
            rationale="SYNTHETIC",
            evidence_ids=[],
            prompt_sha256=mi.prompt_sha256,
            snapshot_sha256=mi.snapshot_sha256,
            temperature=0.0,
            seed=1,
            recorded_at=as_of + timedelta(minutes=5),
            provenance=Provenance.RECORDED_RUN,
        )
        store.save(pred, mi)
    return vault, gate


def write_committed_cases(cases_dir, records):
    for rec in records:
        write_case_file(
            cases_dir,
            {
                "case": rec.case.model_dump(mode="json"),
                "evidence": [e.model_dump(mode="json") for e in rec.evidence],
                "market_quotes": [q.model_dump(mode="json") for q in rec.market_quotes],
            },
        )


def card_for(tmp_path, rows, **kwargs):
    vault, _gate = scored_world(tmp_path, rows, **kwargs)
    return build_scorecard(vault)


def rows_for(n, agent_good=True, start=0):
    """Alternating outcomes; agent 0.9/0.1 (good) and market 0.6/0.4. Per-event delta Brier = -0.15."""
    rows = []
    for i in range(start, start + n):
        y = i % 2
        agent = (0.9 if y else 0.1) if agent_good else 0.5
        market = 0.6 if y else 0.4
        rows.append((f"synthetic_evt_{i:03d}", AS_OF + timedelta(days=i), y, agent, market))
    return rows


def test_fewer_than_five_events_is_insufficient_data_but_lists_per_event(tmp_path):
    card = card_for(tmp_path, rows_for(4))
    assert card.verdict == INSUFFICIENT_DATA == "INSUFFICIENT DATA"
    assert card.label == "INSUFFICIENT DATA: No valid comparison"
    assert card.n_events == 4 and len(card.per_event) == 4
    assert card.comparison is None and card.summary is None
    assert card.per_event[0].brier["agent_only"] == pytest.approx(0.01)
    assert card.per_event[0].brier["naive"] == pytest.approx(0.25)


def test_small_sample_agent_better_only_when_ci_excludes_zero(tmp_path):
    card = card_for(tmp_path, rows_for(10))
    assert card.n_events == 10
    assert card.verdict == AGENT_BETTER == "agent better than market"
    assert card.caveat is not None and "small sample" in card.caveat and "n = 10" in card.caveat
    assert card.label == "ILLUSTRATIVE: Synthetic demo fixtures"
    assert card.comparison.ci_high < 0
    assert card.comparison.mean_delta_brier == pytest.approx(-0.15)
    assert (card.comparison.n_resamples, card.comparison.seed) == (DEFAULT_RESAMPLES, BOOTSTRAP_SEED)
    assert card.summary["market"].mean_brier == pytest.approx(0.16)
    assert card.summary["naive"].mean_brier == pytest.approx(0.25)
    assert card.summary["agent_only"].accuracy_at_0_5 == pytest.approx(1.0)


def test_identical_forecasts_are_no_improvement(tmp_path):
    rows = [(e, t, y, m, m) for e, t, y, _a, m in rows_for(8)]
    card = card_for(tmp_path, rows)
    assert card.verdict == NO_IMPROVEMENT == "No improvement measured"
    assert card.comparison.ci_high == pytest.approx(0.0)


def test_lower_mean_brier_with_ci_crossing_zero_is_no_improvement(tmp_path):
    rows = rows_for(7)
    e, t, _y, _a, m = rows[1]  # y = 1
    rows[1] = (e, t, 1, 0.0, m)  # one confident miss: agent Brier 1.0 vs market 0.16
    card = card_for(tmp_path, rows)
    assert card.comparison.mean_delta_brier == pytest.approx((6 * -0.15 + 0.84) / 7)
    assert card.comparison.mean_delta_brier < 0 < card.comparison.ci_high
    assert card.verdict == NO_IMPROVEMENT


def test_worse_agent_is_no_improvement(tmp_path):
    card = card_for(tmp_path, rows_for(8, agent_good=False))
    assert card.verdict == NO_IMPROVEMENT
    assert card.comparison.mean_delta_brier > 0


def official_card(tmp_path, monkeypatch, rows, **kwargs):
    vault, cases = scored_world(tmp_path, rows, synthetic=False, official=monkeypatch, **kwargs)
    return build_scorecard(vault, cases=cases), vault, cases


def test_twenty_nine_events_still_carry_the_small_sample_caveat(tmp_path, monkeypatch):
    card, *_ = official_card(tmp_path, monkeypatch, rows_for(29))
    assert card.caveat == "small sample: n = 29 events (< 30)"
    assert card.label == "OFFICIAL: Computed from 29 historical cases" and card.official_blockers == []


def test_thirty_real_events_have_official_label_and_no_caveat(tmp_path, monkeypatch):
    card, *_ = official_card(tmp_path, monkeypatch, rows_for(30))
    assert card.label == "OFFICIAL: Computed from 30 historical cases"
    assert card.caveat is None and card.official_blockers == []
    assert card.provenance == Provenance.REAL_HISTORICAL


# ---------------------------------------------------------------- OFFICIAL needs the committed cases (round 3)


def test_real_cases_without_committed_cases_are_not_official(tmp_path, monkeypatch):
    vault, cases = scored_world(tmp_path, rows_for(10), synthetic=False, official=monkeypatch)
    card = build_scorecard(vault)
    assert card.label == LABEL_NOT_OFFICIAL and card.verdict == AGENT_BETTER
    assert any("not checked against the committed case files" in b for b in card.official_blockers)
    assert build_scorecard(vault, cases=cases).label == "OFFICIAL: Computed from 10 historical cases"


def test_in_memory_case_store_is_not_official(tmp_path):
    vault, cases = scored_world(tmp_path, rows_for(10), synthetic=False)  # gate built from records, tmp vault
    card = build_scorecard(vault, cases=cases)
    assert card.label == LABEL_NOT_OFFICIAL
    assert any("EvidenceStore.from_dir()" in b for b in card.official_blockers)
    assert any("sealed-outcome folder" in b for b in card.official_blockers)


def test_saving_only_winners_is_not_official(tmp_path, monkeypatch):
    """round3_d: 10 committed real cases, the operator saves forecasts for the 6 winners only."""
    rows = [(f"ev{i}", AS_OF, 1 if i < 6 else 0, 0.9, 0.6) for i in range(10)]
    card, *_ = official_card(tmp_path, monkeypatch, rows, save=set(range(6)))
    assert card.n_events == 6 and card.verdict == AGENT_BETTER
    assert card.exclusions_by_reason == {"no_persisted_prediction": 4}
    assert card.label == LABEL_NOT_OFFICIAL
    assert any(b.startswith("no_persisted_prediction: 4 event(s)") for b in card.official_blockers)


@pytest.mark.parametrize("reason", ["multiple_predictions", "persisted_after_outcome_revealed"])
def test_dropping_a_loser_by_rerun_or_peek_is_not_official(tmp_path, monkeypatch, reason):
    rows = rows_for(10)
    vault, cases = scored_world(tmp_path, rows, synthetic=False, official=monkeypatch)
    e, t, *_ = rows[3]
    snap = cases.get_as_of(e, t)
    mi = snap.model_input("agent_only")
    if reason == "persisted_after_outcome_revealed":
        vault.reveal("pred_003")
    vault.store.save(_pred(mi, "rerun", 0.5), mi)
    card = build_scorecard(vault, cases=cases)
    assert card.label == LABEL_NOT_OFFICIAL
    assert any(b.startswith(reason) for b in card.official_blockers)


def test_forecast_made_from_other_case_data_is_context_mismatch(tmp_path, monkeypatch):
    """round3_c a: a script-built gate with a fabricated quote freezes a fake baseline."""
    rows = rows_for(10)
    vault, cases = scored_world(tmp_path, rows, synthetic=False, official=monkeypatch, save=set(range(1, 10)))
    e, t, *_ = rows[0]
    fake = EvidenceStore(
        [
            CaseRecord(
                case=make_case(e, as_of=t, synthetic=False, provenance=Provenance.REAL_HISTORICAL),
                market_quotes=(make_quote(t - timedelta(hours=1), "0.99"),),
            )
        ]
    )
    snap = fake.get_as_of(e, t)
    mi = snap.model_input("agent_only")
    vault.store.save(_pred(mi, "fake_ctx", 0.1), mi)
    card = build_scorecard(vault, cases=cases)
    assert card.exclusions_by_reason == {"context_mismatch": 1}
    assert card.exclusions[0].prediction_ids == ["fake_ctx"]
    assert card.label == LABEL_NOT_OFFICIAL
    assert vault.store.reveal_times("fake_ctx") == []  # mismatched forecasts are not revealed


def test_editing_a_committed_case_after_the_run_is_context_mismatch(tmp_path, monkeypatch):
    rows = rows_for(10)
    vault, _ = scored_world(tmp_path, rows, synthetic=False, official=monkeypatch)
    path = tmp_path / "data" / "demo_cases" / f"{rows[2][0]}.json"
    data = json.loads(path.read_text())
    data["case"]["contamination_flag"] = "likely"  # relabel a case after the forecasts were made
    path.write_text(json.dumps(data))
    card = build_scorecard(vault, cases=EvidenceStore.from_dir())
    assert card.exclusions_by_reason == {"context_mismatch": 1}
    assert card.label == LABEL_NOT_OFFICIAL


def test_any_change_to_a_committed_case_file_after_the_run_is_context_mismatch(tmp_path, monkeypatch):
    """Even content the model never saw (an item excluded at as_of) is frozen: the case hash must match."""
    rows = rows_for(10)
    vault, _ = scored_world(tmp_path, rows, synthetic=False, official=monkeypatch)
    e, t0, *_ = rows[4]
    path = tmp_path / "data" / "demo_cases" / f"{e}.json"
    data = json.loads(path.read_text())
    data["evidence"].append(evidence_dict("evid_later", t0 + timedelta(days=2), "Added after the run.", event_id=e))
    path.write_text(json.dumps(data))
    cases = EvidenceStore.from_dir()
    # The prompt and snapshot at as_of are unchanged (the new item is after the cutoff) ...
    rec = vault.store.records_for(e, t0, "agent_only")[0]
    assert cases.get_as_of(e, t0).model_input("agent_only").snapshot_sha256 == rec.prediction.snapshot_sha256
    # ... but the case content changed, so the forecast is no longer tied to the committed case.
    card = build_scorecard(vault, cases=cases)
    assert card.exclusions_by_reason == {"context_mismatch": 1}
    assert card.label == LABEL_NOT_OFFICIAL


def test_forecast_saved_after_another_events_reveal_is_not_official(tmp_path, monkeypatch):
    """round3_c d: reveal one event, then forecast a correlated event."""
    rows = rows_for(10)
    vault, cases = scored_world(tmp_path, rows, synthetic=False, official=monkeypatch, save=set(range(9)))
    vault.reveal("pred_000")
    e, t, *_ = rows[9]
    snap = cases.get_as_of(e, t)
    mi = snap.model_input("agent_only")
    vault.store.save(_pred(mi, "late", 0.9), mi)
    card = build_scorecard(vault, cases=cases)
    assert card.n_events == 10 and card.exclusions == []
    assert card.label == LABEL_NOT_OFFICIAL
    assert any("cross-event leakage" in b for b in card.official_blockers)


def test_synthetic_committed_cases_without_forecasts_do_not_block_official(tmp_path, monkeypatch):
    rows = rows_for(10)
    vault, cases = scored_world(
        tmp_path, rows, synthetic=False, official=monkeypatch, extra_cases=("synthetic_fixture",)
    )
    card = build_scorecard(vault, cases=cases)
    assert card.exclusions_by_reason == {"no_persisted_prediction": 1}
    assert card.label == "OFFICIAL: Computed from 10 historical cases"


def _pred(mi, pid, p_yes):
    return Prediction(
        prediction_id=pid,
        event_id=mi.event_id,
        as_of=datetime.fromisoformat(mi.as_of),
        agent_model="ollama/test-model",
        variant=mi.variant,
        p_yes=p_yes,
        decision="wait",
        rationale="SYNTHETIC",
        evidence_ids=[],
        prompt_sha256=mi.prompt_sha256,
        snapshot_sha256=mi.snapshot_sha256,
        temperature=0.0,
        seed=1,
        recorded_at=datetime.fromisoformat(mi.as_of) + timedelta(minutes=5),
        provenance=Provenance.RECORDED_RUN,
    )


def test_exclusions_are_reported_by_reason(tmp_path):
    rows = rows_for(7)
    e0, t0, y0, a0, _m = rows[0]
    rows[0] = (e0, t0, y0, a0, None)  # no market quote at that as_of
    vault, gate = scored_world(
        tmp_path, rows, likely_events={rows[1][0]}, extra_cases=("synthetic_no_prediction",)
    )
    card = build_scorecard(vault, cases=gate)
    assert card.exclusions_by_reason == {
        "market_not_available": 1,
        "contamination_likely": 1,
        "no_persisted_prediction": 1,
    }
    assert card.n_excluded == 3 and card.n_events == 5
    assert card.verdict == AGENT_BETTER and "small sample" in card.caveat
    # Excluded predictions are not revealed by scoring.
    assert vault.store.reveal_times("pred_000") == [] and vault.store.reveal_times("pred_001") == []
    # Without the case list, unpredicted cases are simply not part of the population.
    assert build_scorecard(vault).exclusions_by_reason == {"market_not_available": 1, "contamination_likely": 1}


def test_missing_sealed_outcome_is_an_exclusion(tmp_path):
    rows = rows_for(6)
    vault, _ = scored_world(tmp_path, rows)
    (tmp_path / "data" / "sealed_outcomes" / f"{rows[0][0]}.json").unlink()
    card = build_scorecard(vault)
    assert card.exclusions_by_reason == {"sealed_outcome_not_available": 1} and card.n_events == 5


def test_multiple_horizons_are_averaged_within_event(tmp_path):
    rows = rows_for(5)
    e0 = rows[0][0]
    rows.append((e0, AS_OF + timedelta(days=-3), 0, 0.3, 0.4))  # second horizon for the same event (y=0)
    card = card_for(tmp_path, rows)
    assert card.n_events == 5  # events are the unit, not snapshots
    first = next(e for e in card.per_event if e.event_id == e0)
    assert first.n_snapshots == 2
    assert first.brier["agent_only"] == pytest.approx((0.01 + 0.09) / 2)
    assert first.brier["market"] == pytest.approx((0.16 + 0.16) / 2)


def test_duplicate_predictions_for_one_snapshot_are_excluded_not_chosen(tmp_path):
    rows = rows_for(6)
    rows.append(rows[0])
    card = card_for(tmp_path, rows)
    assert card.exclusions_by_reason == {"multiple_predictions": 1}
    assert card.exclusions[0].prediction_ids == ["pred_000", "pred_006"]
    assert card.n_events == 5


def test_agent_plus_market_variant_is_scored_separately(tmp_path):
    vault, _ = scored_world(tmp_path, rows_for(6))
    card = build_scorecard(vault, agent_variant="agent_plus_market")
    # No agent_plus_market predictions were persisted, so every event is excluded.
    assert card.n_events == 0 and card.exclusions_by_reason == {"no_persisted_prediction": 6}
    assert card.verdict == INSUFFICIENT_DATA


def test_hosted_comparator_is_not_scored_yet(tmp_path):
    vault, _ = scored_world(tmp_path, rows_for(5))
    with pytest.raises(ValueError, match="agent_variant"):
        build_scorecard(vault, agent_variant="hosted_comparator")


def test_mixed_synthetic_and_real_cases_are_refused(tmp_path):
    rows = rows_for(12)
    real = frozenset(e for e, *_ in rows[6:])
    with pytest.raises(ValueError, match="separately"):
        card_for(tmp_path, rows, real_events=real)


def test_case_and_sealed_provenance_must_agree(tmp_path):
    rows = rows_for(6)
    with pytest.raises(ValueError, match="provenance"):
        card_for(tmp_path, rows, sealed_provenance={rows[0][0]: "REAL_HISTORICAL"})


def test_scorecard_takes_the_vault_not_caller_supplied_reveals():
    with pytest.raises(TypeError):
        build_scorecard([{"prediction_id": "x", "y": 1}])  # type: ignore[arg-type]


def test_scorecard_cannot_override_bootstrap_settings(tmp_path):
    vault, _ = scored_world(tmp_path, rows_for(5))
    with pytest.raises(TypeError):
        build_scorecard(vault, seed=1)  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        build_scorecard(vault, n_resamples=10)  # type: ignore[call-arg]


def test_post_hoc_context_manipulation_has_no_effect(tmp_path):
    """Audit round 2 (reaudit2.py): after outcomes are known, a caller must not be able to drop losing events,
    invent a market price, or flag losers as contaminated."""
    rows = [(f"ev{i}", AS_OF, 1 if i < 6 else 0, 0.7, 0.7) for i in range(8)]
    vault, gate = scored_world(tmp_path, rows)
    honest = build_scorecard(vault)
    assert (honest.n_events, honest.verdict) == (8, NO_IMPROVEMENT)
    assert honest.comparison.mean_delta_brier == pytest.approx(0.0)

    losers = {e.event_id for e in honest.per_event if e.y == 0}
    # A case list with the losers dropped and a fabricated 0.3 market price, built after the reveal.
    forged = EvidenceStore(
        [
            CaseRecord(
                case=make_case(e, as_of=AS_OF, contamination_flag="likely" if e in losers else "unlikely"),
                market_quotes=(make_quote(AS_OF - timedelta(hours=1), "0.3"),),
            )
            for e, *_ in rows
            if e not in losers
        ]
    )
    again = build_scorecard(vault, cases=forged)
    # The forged list cannot reproduce the frozen inputs, so every forecast is a context_mismatch: the
    # manipulation can only remove events (visibly, and never earning OFFICIAL), never improve the verdict.
    assert again.exclusions_by_reason == {"context_mismatch": 8}
    assert again.n_events == 0 and again.verdict == INSUFFICIENT_DATA
    # Without a case list the result is the honest one, and the stored baselines were never touched.
    assert build_scorecard(vault).per_event == honest.per_event
