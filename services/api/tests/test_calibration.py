"""Calibration bins, Wilson intervals and the Brier decomposition (issue #86; MATH_MODEL §6 "Calibration").

Every expected number below is worked by hand in docs/MATH_MODEL.md §6 (the 6-forecast example) or derived in
the comment next to it; nothing is copied from the code's own output. All fixtures are SYNTHETIC.
"""

from __future__ import annotations

import ast
import math
from pathlib import Path

import pytest

from core import calibration as cal
from core.calibration import (
    EventForecast,
    calibrate,
    calibration_from_scorecard,
    wilson_interval,
)
from core.evaluator import (
    INSUFFICIENT_DATA,
    LABEL_INSUFFICIENT,
    MIN_EVENTS,
    EventScore,
    Scorecard,
    brier,
    correct_at_half,
    log_loss,
)
from models import Provenance

SYN = Provenance.SYNTHETIC
REAL = Provenance.REAL_HISTORICAL

# MATH_MODEL §6 hand example: six (p, y) pairs, N = 6.
HAND = [(0.1, 0), (0.3, 0), (0.3, 1), (0.7, 1), (0.8, 0), (0.9, 1)]


def events(pairs, provenance=SYN, forecaster="agent_only"):
    return [
        EventForecast(event_id=f"e{i}", y=y, p={forecaster: p}, provenance=provenance) for i, (p, y) in enumerate(pairs)
    ]


def card_from(rows, provenance=SYN, n_snapshots=None, case_set="synthetic"):
    """A Scorecard whose per-event scores are computed from (event_id, y, {forecaster: p}) with the evaluator's
    own scoring functions, exactly as build_scorecard does for one snapshot per event."""
    forecasters = sorted({f for _e, _y, ps in rows for f in ps})
    per_event = [
        EventScore(
            event_id=eid,
            n_snapshots=(n_snapshots or {}).get(eid, 1),
            y=y,
            prediction_ids=[f"pred-{eid}"],
            market_refs=[],
            brier={f: brier(p, y) for f, p in ps.items()},
            log_loss={f: log_loss(p, y) for f, p in ps.items()},
            accuracy_at_0_5={f: correct_at_half(p, y) for f, p in ps.items()},
        )
        for eid, y, ps in rows
    ]
    return Scorecard(
        label="ILLUSTRATIVE: Synthetic demo fixtures",
        verdict="No improvement measured",
        caveat=None,
        provenance=provenance if rows else None,
        agent_variant="agent_only",
        forecasters=forecasters,
        case_set=case_set,
        n_events=len(per_event),
        n_excluded=0,
        exclusions_by_reason={},
        exclusions=[],
        ignored_predictions=[],
        per_event=per_event,
        summary=None,
        comparison=None,
        official_blockers=[],
    )


# ---------------------------------------------------------------- isolation (written before the feature)


def test_calibration_module_never_touches_sealed_outcomes_or_files():
    """Calibration works only on an already-built Scorecard: no vault, no reveal, no store, no file I/O."""
    src = Path(cal.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported |= {f"{node.module}.{a.name}" for a in node.names}
        elif isinstance(node, ast.Import):
            imported |= {a.name for a in node.names}
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id != "open", "calibration must not open files"
    banned = ("OutcomeVault", "reveal", "PredictionStore", "core.store", "temporal_gate", "pathlib", "os", "sqlite3")
    for name in imported:
        assert not any(b == name or name.endswith(f".{b}") or name.startswith(f"{b}.") for b in banned), name
    assert "sealed_outcomes" not in src


# ---------------------------------------------------------------- Wilson interval


def test_wilson_hand_values():
    # k = 1, n = 2, z = 1.96: centre (0.5 + 0.9604) / 2.9208 = 0.5,
    # half-width (1.96 / 2.9208) * sqrt(0.125 + 0.2401) = 0.4054713452 -> [0.0945286548, 0.9054713452].
    lo, hi = wilson_interval(1, 2)
    assert lo == pytest.approx(0.0945286548, abs=1e-6)
    assert hi == pytest.approx(0.9054713452, abs=1e-6)
    # k = 0, n = 1: lower 0, upper z^2 / (1 + z^2) = 3.8416 / 4.8416 = 0.7934567085.
    assert wilson_interval(0, 1) == pytest.approx((0.0, 0.7934567085), abs=1e-6)
    # k = n = 1: lower 1 / (1 + z^2) = 0.2065432915, upper 1.
    assert wilson_interval(1, 1) == pytest.approx((0.2065432915, 1.0), abs=1e-6)
    lo0, _ = wilson_interval(0, 7)
    _, hi7 = wilson_interval(7, 7)
    assert lo0 == 0.0 and hi7 == 1.0  # clamped, never a hair outside [0, 1]


@pytest.mark.parametrize("k,n", [(-1, 2), (3, 2), (0, 0), (1.0, 2)])
def test_wilson_rejects_bad_counts(k, n):
    with pytest.raises((ValueError, TypeError)):
        wilson_interval(k, n)


# ---------------------------------------------------------------- bins on the hand example


def test_hand_example_bins():
    report = calibrate(events(HAND))
    assert report.verdict != INSUFFICIENT_DATA and report.n_events == 6 and report.n_bins == 5
    bins = report.calibration["agent_only"].bins
    assert [(b.lower, b.upper, b.upper_inclusive) for b in bins] == [
        (0.0, 0.2, False),
        (0.2, 0.4, False),
        (0.4, 0.6, False),
        (0.6, 0.8, False),
        (0.8, 1.0, True),
    ]
    assert [b.count for b in bins] == [1, 2, 0, 1, 2]  # p = 0.8 falls in the LAST bin [0.8, 1.0]
    assert [b.n_yes for b in bins] == [0, 1, 0, 1, 1]
    expected_mean = [0.1, 0.3, None, 0.7, 0.85]
    expected_freq = [0.0, 0.5, None, 1.0, 0.5]
    for b, m, o in zip(bins, expected_mean, expected_freq, strict=True):
        assert (b.mean_forecast is None) == (m is None) and (b.observed_frequency is None) == (o is None)
        if m is not None:
            assert b.mean_forecast == pytest.approx(m, abs=1e-12)
            assert b.observed_frequency == pytest.approx(o, abs=1e-12)
    assert bins[1].wilson_low == pytest.approx(0.0945286548, abs=1e-6)
    assert bins[1].wilson_high == pytest.approx(0.9054713452, abs=1e-6)
    assert bins[0].wilson_low == 0.0 and bins[0].wilson_high == pytest.approx(0.7934567085, abs=1e-6)
    empty = bins[2]
    assert (empty.mean_forecast, empty.observed_frequency, empty.wilson_low, empty.wilson_high) == (None,) * 4
    assert empty.note == "empty"
    # every bin here has n < 3: flagged, but still listed
    assert all(b.too_few_to_read for b in bins)
    assert [b.note for b in bins] == ["too few to read"] * 2 + ["empty"] + ["too few to read"] * 2


def test_hand_example_decomposition_and_identity():
    d = calibrate(events(HAND)).calibration["agent_only"].decomposition
    # MATH_MODEL §6: BS = 1.33/6, REL = 0.425/6, RES = 0.5/6, UNC = 0.25, within-bin = -0.095/6.
    assert d.brier_score == pytest.approx(1.33 / 6, abs=1e-12)
    assert d.reliability == pytest.approx(0.425 / 6, abs=1e-12)
    assert d.resolution == pytest.approx(0.5 / 6, abs=1e-12)
    assert d.uncertainty == pytest.approx(0.25, abs=1e-12)
    assert d.base_rate == pytest.approx(0.5, abs=1e-12)
    assert d.within_bin_variance == pytest.approx(0.005 / 6, abs=1e-12)
    assert d.within_bin_covariance == pytest.approx(0.05 / 6, abs=1e-12)
    assert d.within_bin == pytest.approx(-0.095 / 6, abs=1e-12)
    # The identity, with the within-bin term computed from its own components (not as a difference).
    assert abs(d.brier_score - (d.reliability - d.resolution + d.uncertainty + d.within_bin)) < 1e-12
    assert abs(d.within_bin - (d.within_bin_variance - 2 * d.within_bin_covariance)) < 1e-12


def test_identity_holds_on_awkward_forecasts():
    pairs = [(0.0, 0), (0.19999, 1), (0.2, 0), (0.41, 1), (0.59, 0), (0.6, 1), (0.61, 1), (0.99, 0), (1.0, 1)]
    for n_bins in (1, 2, 5, 10):
        d = calibrate(events(pairs), n_bins=n_bins).calibration["agent_only"].decomposition
        assert abs(d.brier_score - sum((p - y) ** 2 for p, y in pairs) / len(pairs)) < 1e-12
        assert abs(d.brier_score - (d.reliability - d.resolution + d.uncertainty + d.within_bin)) < 1e-12


def test_equal_forecasts_within_bins_give_zero_within_bin_term():
    pairs = [(0.1, 0), (0.1, 0), (0.1, 1), (0.7, 1), (0.7, 1), (0.7, 0)]
    report = calibrate(events(pairs))
    d = report.calibration["agent_only"].decomposition
    assert d.within_bin == pytest.approx(0.0, abs=1e-15)
    assert abs(d.brier_score - (d.reliability - d.resolution + d.uncertainty)) < 1e-12
    # Two bins with n = 3: readable (not flagged), the rest empty.
    assert [b.too_few_to_read for b in report.calibration["agent_only"].bins] == [False, True, True, False, True]


# ---------------------------------------------------------------- edges


def test_p_zero_and_one_land_in_the_end_bins():
    pairs = [(0.0, 0), (0.0, 0), (1.0, 1), (1.0, 1), (1.0, 0)]
    bins = calibrate(events(pairs)).calibration["agent_only"].bins
    assert [b.count for b in bins] == [2, 0, 0, 0, 3]
    assert bins[0].mean_forecast == 0.0 and bins[4].mean_forecast == 1.0


def test_bin_edges_are_left_closed():
    pairs = [(0.2, 0), (0.4, 0), (0.6, 1), (0.8, 1), (0.19999999, 0)]
    bins = calibrate(events(pairs)).calibration["agent_only"].bins
    assert [b.count for b in bins] == [1, 1, 1, 1, 1]


def test_all_same_outcome_has_zero_uncertainty_and_resolution():
    pairs = [(0.9, 1), (0.6, 1), (0.3, 1), (0.95, 1), (0.1, 1)]
    d = calibrate(events(pairs)).calibration["agent_only"].decomposition
    assert d.base_rate == 1.0 and d.uncertainty == 0.0 and d.resolution == pytest.approx(0.0, abs=1e-15)
    assert abs(d.brier_score - (d.reliability - d.resolution + d.uncertainty + d.within_bin)) < 1e-12


# ---------------------------------------------------------------- honesty rules


def test_fewer_than_min_events_is_insufficient_data_without_a_table():
    report = calibrate(events(HAND[: MIN_EVENTS - 1]))
    assert report.verdict == INSUFFICIENT_DATA and report.label == LABEL_INSUFFICIENT
    assert report.calibration is None and report.n_events == MIN_EVENTS - 1
    assert report.provenance == SYN


def test_no_events_is_insufficient_data():
    report = calibrate([])
    assert report.verdict == INSUFFICIENT_DATA and report.calibration is None and report.provenance is None


def test_labels_name_the_source_and_small_sample():
    report = calibrate(events(HAND))
    assert "Computed from the scorecard's per-event scores" in report.label
    assert report.label.startswith("SYNTHETIC") and report.provenance == SYN
    assert report.caveat is not None and "small sample" in report.caveat
    assert report.source == cal.SOURCE


def test_synthetic_and_real_are_never_pooled():
    mixed = events(HAND[:3], SYN) + [
        EventForecast(event_id=f"r{i}", y=y, p={"agent_only": p}, provenance=REAL) for i, (p, y) in enumerate(HAND[3:])
    ]
    with pytest.raises(ValueError, match="separately"):
        calibrate(mixed)


@pytest.mark.parametrize("prov", [Provenance.SIMULATED, Provenance.ILLUSTRATIVE, Provenance.RECORDED_RUN])
def test_only_scored_outcome_provenances_accepted(prov):
    with pytest.raises(ValueError):
        calibrate(events(HAND, prov))


def test_forecasters_must_be_paired_and_events_unique():
    evs = events(HAND)
    bad = evs[:-1] + [EventForecast(event_id="e5", y=1, p={"market": 0.9}, provenance=SYN)]
    with pytest.raises(ValueError, match="same forecasters"):
        calibrate(bad)
    with pytest.raises(ValueError, match="duplicate"):
        calibrate(evs + [evs[0]])


@pytest.mark.parametrize("p", [-0.01, 1.01, float("nan")])
def test_bad_probability_rejected(p):
    with pytest.raises(ValueError):
        EventForecast(event_id="x", y=1, p={"agent_only": p}, provenance=SYN)


# ---------------------------------------------------------------- from a Scorecard


def _hand_rows():
    return [
        (f"e{i}", y, {"naive": 0.5, "market": q, "agent_only": p})
        for i, ((p, y), q) in enumerate(zip(HAND, [0.2, 0.4, 0.6, 0.8, 0.6, 1.0], strict=True))
    ]


def test_from_scorecard_recovers_forecasts_exactly_and_bins_every_forecaster():
    card = card_from(_hand_rows())
    report = calibration_from_scorecard(card)
    assert report.forecasters == ["agent_only", "market", "naive"]
    assert report.scorecard_label == card.label and report.case_set == "synthetic"
    agent = report.calibration["agent_only"]
    assert [b.count for b in agent.bins] == [1, 2, 0, 1, 2]
    assert agent.decomposition.brier_score == pytest.approx(1.33 / 6, abs=1e-12)
    # market prices sit exactly on bin edges (0.2, 0.4, 0.6, 0.8, 1.0): recovered p must not slip a bin.
    assert [b.count for b in report.calibration["market"].bins] == [0, 1, 1, 2, 2]
    naive = report.calibration["naive"]
    assert [b.count for b in naive.bins] == [0, 0, 6, 0, 0] and naive.bins[2].mean_forecast == 0.5
    assert naive.decomposition.reliability == pytest.approx(0.0, abs=1e-15)


def test_from_scorecard_excludes_multi_snapshot_events_and_says_so():
    rows = _hand_rows()
    report = calibration_from_scorecard(card_from(rows, n_snapshots={"e2": 2}))
    assert [(x.event_id, x.reason) for x in report.excluded] == [("e2", "multiple_snapshots_forecast_not_recoverable")]
    # 5 of 6 events remain: still >= MIN_EVENTS, and the label says 5 of 6.
    assert report.n_events == 5 and report.verdict != INSUFFICIENT_DATA
    assert "n = 5 of 6 scored events" in report.label
    two = calibration_from_scorecard(card_from(rows, n_snapshots={"e2": 2, "e3": 3}))
    assert two.verdict == INSUFFICIENT_DATA and two.calibration is None and len(two.excluded) == 2
    assert two.n_events == 4 and two.n_scored_events == 6
    every = calibration_from_scorecard(card_from(rows, n_snapshots={f"e{i}": 2 for i in range(6)}))
    assert every.n_events == 0 and every.forecasters == ["agent_only", "market", "naive"]
    assert every.provenance == SYN and every.verdict == INSUFFICIENT_DATA


def test_from_scorecard_small_card_is_insufficient_data():
    report = calibration_from_scorecard(card_from(_hand_rows()[:4]))
    assert report.verdict == INSUFFICIENT_DATA and report.calibration is None
    empty = calibration_from_scorecard(card_from([]))
    assert empty.verdict == INSUFFICIENT_DATA and empty.provenance is None


def test_from_scorecard_real_card_is_labelled_real():
    report = calibration_from_scorecard(card_from(_hand_rows(), provenance=REAL, case_set="real"))
    assert report.provenance == REAL and report.label.startswith("REAL HISTORICAL")


def test_from_scorecard_rejects_inconsistent_provenance():
    card = card_from(_hand_rows(), provenance=REAL, case_set="synthetic")
    with pytest.raises(ValueError, match="case_set"):
        calibration_from_scorecard(card)


def test_recovery_round_trip_on_many_values():
    for k in range(0, 101):
        p = k / 100
        for y in (0, 1):
            assert cal.forecast_from_brier(brier(p, y), y) == p
    assert math.isclose(cal.forecast_from_brier(brier(0.123456789, 1), 1), 0.123456789, abs_tol=1e-12)
    with pytest.raises(ValueError):
        cal.forecast_from_brier(1.5, 0)
