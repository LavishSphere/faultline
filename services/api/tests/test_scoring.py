"""Forecast scoring, paired bootstrap and scorecard display rules (MATH_MODEL §6, §9; SPEC §6).

Written before the scoring half of core/evaluator.py. All events here are SYNTHETIC test fixtures; the
few marked synthetic=False exist only to exercise the OFFICIAL label logic and are never shown anywhere.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest
from test_replay_seal import Clock, sealed_dict, write_sealed

from core import provenance
from core.evaluator import (
    AGENT_BETTER,
    BOOTSTRAP_SEED,
    DEFAULT_RESAMPLES,
    EPS,
    INSUFFICIENT_DATA,
    NO_IMPROVEMENT,
    EventContext,
    OutcomeVault,
    brier,
    build_scorecard,
    correct_at_half,
    log_loss,
    paired_bootstrap,
)
from core.store import PredictionStore
from models import Prediction, Provenance

AS_OF = datetime(2025, 3, 1, 12, 0, tzinfo=UTC)
EMPTY_SNAPSHOT = provenance.canonical_json({"evidence": [], "market_quotes": []})


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


def scored_world(tmp_path, rows, *, synthetic=True, variant="agent_only"):
    """rows: (event_id, as_of, y, agent_p, market_p). Persists predictions, then reveals each one."""
    sealed = tmp_path / "data" / "sealed_outcomes"
    store = PredictionStore(tmp_path / "var" / "p.sqlite3", clock=Clock(AS_OF))
    vault = OutcomeVault(store, sealed_dir=sealed, clock=Clock(AS_OF + timedelta(days=30)))
    reveals, contexts, written = [], [], set()
    for i, (event_id, as_of, y, agent_p, market_p) in enumerate(rows):
        if event_id not in written:
            data = sealed_dict(event_id, outcome="YES" if y else "NO")
            data["provenance"] = "SYNTHETIC" if synthetic else "REAL_HISTORICAL"
            write_sealed(sealed, data)
            written.add(event_id)
        prompt = f"SYNTHETIC prompt {event_id} {as_of.isoformat()}"
        snapshot = EMPTY_SNAPSHOT
        pred = Prediction(
            prediction_id=f"pred_{i:03d}",
            event_id=event_id,
            as_of=as_of,
            agent_model="ollama/test-model",
            variant=variant,
            p_yes=agent_p,
            decision="wait",
            rationale="SYNTHETIC",
            evidence_ids=[],
            prompt_sha256=provenance.prompt_sha256(prompt),
            snapshot_sha256=provenance.sha256_hex(snapshot),
            temperature=0.0,
            seed=1,
            recorded_at=as_of + timedelta(minutes=5),
            provenance=Provenance.RECORDED_RUN,
        )
        store.save(pred, prompt=prompt, snapshot_json=snapshot)
        reveals.append(vault.reveal(pred.prediction_id))
        contexts.append(EventContext(event_id=event_id, as_of=as_of, market_p_yes=market_p, synthetic=synthetic))
    return reveals, contexts


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
    card = build_scorecard(*scored_world(tmp_path, rows_for(4)))
    assert card.verdict == INSUFFICIENT_DATA == "INSUFFICIENT DATA"
    assert card.label == "INSUFFICIENT DATA: No valid comparison"
    assert card.n_events == 4 and len(card.per_event) == 4
    assert card.comparison is None and card.summary is None
    assert card.per_event[0].brier["agent_only"] == pytest.approx(0.01)
    assert card.per_event[0].brier["naive"] == pytest.approx(0.25)


def test_small_sample_agent_better_only_when_ci_excludes_zero(tmp_path):
    card = build_scorecard(*scored_world(tmp_path, rows_for(10)))
    assert card.n_events == 10
    assert card.verdict == AGENT_BETTER == "agent better than market"
    assert card.caveat is not None and "small sample" in card.caveat and "n = 10" in card.caveat
    assert card.label == "ILLUSTRATIVE: Synthetic demo fixtures"
    assert card.comparison.ci_high < 0
    assert card.comparison.mean_delta_brier == pytest.approx(-0.15)
    assert card.summary["market"].mean_brier == pytest.approx(0.16)
    assert card.summary["naive"].mean_brier == pytest.approx(0.25)
    assert card.summary["agent_only"].accuracy_at_0_5 == pytest.approx(1.0)


def test_identical_forecasts_are_no_improvement(tmp_path):
    rows = [(e, t, y, m, m) for e, t, y, _a, m in rows_for(8)]
    card = build_scorecard(*scored_world(tmp_path, rows))
    assert card.verdict == NO_IMPROVEMENT == "No improvement measured"
    assert card.comparison.ci_high == pytest.approx(0.0)


def test_lower_mean_brier_with_ci_crossing_zero_is_no_improvement(tmp_path):
    rows = rows_for(7)
    e, t, _y, _a, m = rows[1]  # y = 1
    rows[1] = (e, t, 1, 0.0, m)  # one confident miss: agent Brier 1.0 vs market 0.16
    card = build_scorecard(*scored_world(tmp_path, rows))
    assert card.comparison.mean_delta_brier == pytest.approx((6 * -0.15 + 0.84) / 7)
    assert card.comparison.mean_delta_brier < 0 < card.comparison.ci_high
    assert card.verdict == NO_IMPROVEMENT


def test_worse_agent_is_no_improvement(tmp_path):
    card = build_scorecard(*scored_world(tmp_path, rows_for(8, agent_good=False)))
    assert card.verdict == NO_IMPROVEMENT
    assert card.comparison.mean_delta_brier > 0


def test_thirty_real_events_have_official_label_and_no_caveat(tmp_path):
    card = build_scorecard(*scored_world(tmp_path, rows_for(30), synthetic=False))
    assert card.label == "OFFICIAL: Computed from 30 historical cases"
    assert card.caveat is None
    assert card.provenance == Provenance.REAL_HISTORICAL


def test_exclusions_are_reported_by_reason(tmp_path):
    rows = rows_for(7)
    reveals, contexts = scored_world(tmp_path, rows)
    contexts[0] = EventContext(event_id=contexts[0].event_id, as_of=contexts[0].as_of, market_p_yes=None)
    contexts[1] = EventContext(
        event_id=contexts[1].event_id,
        as_of=contexts[1].as_of,
        market_p_yes=0.6,
        contamination_flag="likely",
    )
    contexts.append(EventContext(event_id="synthetic_no_prediction", as_of=AS_OF, market_p_yes=0.5))
    card = build_scorecard(reveals, contexts)
    assert card.exclusions_by_reason == {
        "market_not_available": 1,
        "contamination_likely": 1,
        "no_persisted_prediction": 1,
    }
    assert card.n_excluded == 3 and card.n_events == 5
    assert card.verdict == AGENT_BETTER and "small sample" in card.caveat


def test_multiple_horizons_are_averaged_within_event(tmp_path):
    rows = rows_for(5)
    e0 = rows[0][0]
    rows.append((e0, AS_OF + timedelta(days=-3), 0, 0.3, 0.4))  # second horizon for the same event (y=0)
    card = build_scorecard(*scored_world(tmp_path, rows))
    assert card.n_events == 5  # events are the unit, not snapshots
    first = next(e for e in card.per_event if e.event_id == e0)
    assert first.n_snapshots == 2
    assert first.brier["agent_only"] == pytest.approx((0.01 + 0.09) / 2)
    assert first.brier["market"] == pytest.approx((0.16 + 0.16) / 2)


def test_duplicate_predictions_for_one_snapshot_are_refused(tmp_path):
    rows = rows_for(5)
    rows.append(rows[0])
    with pytest.raises(ValueError, match="more than one"):
        build_scorecard(*scored_world(tmp_path, rows))


def test_agent_plus_market_variant_is_scored_separately(tmp_path):
    reveals, contexts = scored_world(tmp_path, rows_for(6))
    card = build_scorecard(reveals, contexts, agent_variant="agent_plus_market")
    # No agent_plus_market predictions were persisted, so every event is excluded.
    assert card.n_events == 0 and card.exclusions_by_reason == {"no_persisted_prediction": 6}
    assert card.verdict == INSUFFICIENT_DATA


def test_mixed_synthetic_and_real_cases_are_refused(tmp_path):
    r1, c1 = scored_world(tmp_path / "a", rows_for(6))
    r2, c2 = scored_world(tmp_path / "b", rows_for(6, start=10), synthetic=False)
    with pytest.raises(ValueError, match="separately"):
        build_scorecard(r1 + r2, c1 + c2)


def test_context_and_sealed_provenance_must_agree(tmp_path):
    reveals, contexts = scored_world(tmp_path, rows_for(6))
    contexts[0] = EventContext(
        event_id=contexts[0].event_id, as_of=contexts[0].as_of, market_p_yes=0.6, synthetic=False
    )
    with pytest.raises(ValueError, match="provenance"):
        build_scorecard(reveals, contexts)


def test_scorecard_requires_vault_reveals():
    ctx = [EventContext(event_id="e", as_of=AS_OF, market_p_yes=0.5)]
    with pytest.raises(TypeError):
        build_scorecard([{"prediction_id": "x", "y": 1}], ctx)  # type: ignore[list-item]
