"""The SYNTHETIC 0.35 market price on the fallback case (issue #105; venue added in #102; case from #48).

Everything here is SYNTHETIC. 0.35 is p_draw, the probability in the case's published draw rule, so the price is
calibrated by construction and says nothing about the drawn answer. These tests never print or assert which way
the case resolved: the market Brier is checked only to be one of the two values a 0.35 price can score.
"""

from __future__ import annotations

import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from test_replay_seal import Clock
from test_scoring import _pred

from core.evaluator import LABEL_INSUFFICIENT, OutcomeVault, build_scorecard
from core.store import PredictionStore
from core.temporal_gate import EvidenceStore
from models import Provenance

DATA = Path(__file__).resolve().parent.parent / "data"
EVENT = "synthetic_distributor-depot"
AS_OF = datetime(2026, 9, 14, 12, 0, tzinfo=UTC)
REF = "synthetic:FAULTLINE-SYN-DEPOT"


@pytest.fixture(scope="module")
def gate() -> EvidenceStore:
    return EvidenceStore.from_dir(DATA / "demo_cases")


def test_fallback_case_carries_one_synthetic_quote_at_p_draw(gate):
    snap = gate.get_as_of(EVENT, AS_OF)
    assert snap.case.synthetic is True and snap.case.market_quote_id == REF
    p, ref = snap.market_baseline()
    assert (p, ref) == (pytest.approx(0.35), REF)
    (quote,) = snap.payload("agent_plus_market")["market_quotes"]
    assert quote["venue"] == "synthetic" and quote["provenance"] == "SYNTHETIC"
    assert quote["p_yes"] == pytest.approx(0.35)
    ts = datetime.fromisoformat(quote["ts"].replace("Z", "+00:00"))
    assert AS_OF - timedelta(hours=24) <= ts <= AS_OF  # inside the gate's 24 h staleness window


def test_agent_only_input_is_unchanged_and_never_sees_the_price(gate):
    snap = gate.get_as_of(EVENT, AS_OF)
    assert snap.payload("agent_only")["market_quotes"] == []


def test_agent_plus_market_variant_now_renders(gate):
    mi = gate.get_as_of(EVENT, AS_OF).model_input("agent_plus_market")  # raised MarketNotAvailable before #105
    assert mi.synthetic is True
    assert (mi.market_baseline_p_yes, mi.market_baseline_ref) == (pytest.approx(0.35), REF)


@pytest.mark.parametrize("variant", ["agent_only", "agent_plus_market"])
def test_scorecard_for_the_fallback_case_is_synthetic_and_never_official(tmp_path, gate, variant):
    """The case now gets a scorecard row with a SYNTHETIC market baseline. With n = 1 the label is INSUFFICIENT DATA
    (MATH_MODEL §6: n < 5); 5+ synthetic cases read ILLUSTRATIVE (test_synthetic_venue.py::
    test_five_synthetic_cases_are_illustrative_never_official). Never OFFICIAL, never pooled with real cases."""
    store = PredictionStore(tmp_path / "p.sqlite3", clock=Clock(AS_OF + timedelta(days=1)))
    # The vault refuses to reveal the configured sealed folder into any other store, so use a scratch copy.
    sealed = tmp_path / "sealed_outcomes"
    sealed.mkdir()
    shutil.copy(DATA / "sealed_outcomes" / f"{EVENT}.json", sealed)
    vault = OutcomeVault(store, sealed_dir=sealed, clock=Clock(AS_OF + timedelta(days=30)))
    # Only the fallback case: the real FOMC cases are scored separately and never pooled with it.
    cases_dir = tmp_path / "demo_cases"
    cases_dir.mkdir()
    shutil.copy(DATA / "demo_cases" / f"{EVENT}.json", cases_dir)
    only = EvidenceStore.from_dir(cases_dir)
    assert only.case_sha256(EVENT) == gate.case_sha256(EVENT)
    mi = only.get_as_of(EVENT, AS_OF).model_input(variant)
    store.save(_pred(mi, "pred_fallback_105", 0.5), mi)
    card = build_scorecard(vault, cases=only, agent_variant=variant)
    assert card.exclusions_by_reason == {}  # no longer dropped as market_not_available
    assert [e.market_refs for e in card.per_event] == [[REF]]
    assert card.per_event[0].brier["market"] in (pytest.approx(0.35**2), pytest.approx(0.65**2))
    assert card.provenance == Provenance.SYNTHETIC
    assert card.label == LABEL_INSUFFICIENT and not card.label.startswith("OFFICIAL")
