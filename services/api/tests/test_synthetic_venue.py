"""Synthetic venue for SYNTHETIC fallback quotes (issue #102).

A synthetic quote (venue "synthetic") lets a SYNTHETIC case carry a hand-written benchmark price. It must be
labelled SYNTHETIC everywhere, load only on a ``synthetic: true`` case, obey the gate's 24h staleness rule and
``venue:market_id`` reference unchanged, never reach data/raw, and never make a scorecard OFFICIAL or pool with
real cases. Reveals of committed synthetic cases do not count for the cross-event ``late`` check, and nothing
else is exempted. Every fixture here is SYNTHETIC.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError
from test_replay_seal import Clock, sealed_dict, write_sealed
from test_scoring import _pred, scored_world
from test_temporal_gate import COLLECTED, make_case, make_quote, quote_dict, sha, write_case_file

from core.evaluator import (
    LABEL_ILLUSTRATIVE,
    OutcomeVault,
    _synthetic_exempt_events,
    build_scorecard,
)
from core.store import PredictionStore
from core.temporal_gate import CaseRecord, EvidenceStore, SyntheticQuoteOnRealCase
from markets.base import (
    MarketDataError,
    MarketMeta,
    NormalizedQuote,
    QuoteProvenance,
    RawQuote,
)
from markets.normalize import select_quote
from markets.raw_store import RawResponse, store_raw
from models import Provenance

AS_OF = datetime(2025, 3, 1, 12, 0, tzinfo=UTC)
MARKET = "FAULTLINE-SYN-001"
REF = f"synthetic:{MARKET}"


def syn_quote_dict(ts: datetime, raw_price: str = "0.35", *, market_id: str = MARKET, **overrides) -> dict:
    data = {
        "venue": "synthetic",
        "market_id": market_id,
        "url": f"https://synthetic.invalid/faultline/markets/{market_id}",
        "source_url": f"https://synthetic.invalid/faultline/markets/{market_id}/quote",
        "outcome": "YES",
        "p_yes": float(raw_price),
        "quote_kind": "synthetic",
        "ts": ts.isoformat(),
        "raw_price": raw_price,
        "raw_scale": "decimal",
        "collected_at": COLLECTED.isoformat(),
        "raw_sha256": sha(f"{market_id}{ts.isoformat()}{raw_price}"),
        "provenance": "SYNTHETIC",
    }
    data.update(overrides)
    return data


def syn_quote(ts: datetime, raw_price: str = "0.35", **kw) -> NormalizedQuote:
    return NormalizedQuote.model_validate(syn_quote_dict(ts, raw_price, **kw))


def real_case(event_id: str, as_of: datetime = AS_OF, **kw):
    return make_case(event_id, as_of=as_of, synthetic=False, provenance=Provenance.REAL_HISTORICAL, **kw)


# ---------------------------------------------------------------- the quote type


def test_synthetic_quote_carries_synthetic_provenance_everywhere():
    q = syn_quote(AS_OF - timedelta(hours=1))
    assert (q.venue, q.provenance, q.quote_kind, q.raw_scale, q.p_yes) == (
        "synthetic",
        "SYNTHETIC",
        "synthetic",
        "decimal",
        0.35,
    )
    assert q.model_dump(mode="json")["provenance"] == "SYNTHETIC"  # part of the case content hash


def test_real_quotes_default_to_real_historical_and_cannot_claim_synthetic():
    q = make_quote(AS_OF, "0.40")
    assert q.provenance == "REAL_HISTORICAL"
    with pytest.raises(ValidationError, match="provenance"):
        NormalizedQuote.model_validate({**quote_dict(AS_OF, "0.40"), "provenance": "SYNTHETIC"})
    with pytest.raises(ValidationError, match="quote_kind"):
        NormalizedQuote.model_validate({**quote_dict(AS_OF, "0.40"), "quote_kind": "synthetic"})


@pytest.mark.parametrize(
    ("override", "match"),
    [
        ({"provenance": "REAL_HISTORICAL"}, "provenance"),
        ({"quote_kind": "candle_close"}, "quote_kind"),
        ({"raw_scale": "dollars"}, "decimal"),
        ({"url": "https://kalshi.com/markets/FAULTLINE-SYN-001"}, "invalid"),
        ({"source_url": "https://api.elections.kalshi.com/trade-api/v2/markets"}, "invalid"),
    ],
)
def test_synthetic_quote_missing_any_marker_is_rejected(override, match):
    with pytest.raises(ValidationError, match=match):
        NormalizedQuote.model_validate(syn_quote_dict(AS_OF, **override))


def test_synthetic_quote_without_explicit_provenance_is_rejected():
    data = syn_quote_dict(AS_OF)
    del data["provenance"]
    with pytest.raises(ValidationError, match="provenance"):
        NormalizedQuote.model_validate(data)


def test_synthetic_price_is_normalized_exactly_once_like_any_quote():
    with pytest.raises(ValidationError, match="exactly once"):
        NormalizedQuote.model_validate(syn_quote_dict(AS_OF, "0.35", p_yes=0.0035))
    with pytest.raises(ValidationError):
        NormalizedQuote.model_validate(syn_quote_dict(AS_OF, "35", p_yes=35.0))  # out of [0, 1]


def test_quote_provenance_values_are_models_provenance_wire_values():
    assert set(QuoteProvenance.__args__) <= {p.value for p in Provenance}


def test_collection_path_cannot_carry_the_synthetic_venue(tmp_path):
    raw = dict(
        market_id=MARKET,
        url="https://synthetic.invalid/x",
        source_url="https://synthetic.invalid/x",
        ts=AS_OF,
        raw_scale="decimal",
        point="0.35",
        collected_at=COLLECTED,
        raw_sha256="0" * 64,
    )
    with pytest.raises(ValidationError):
        RawQuote(venue="synthetic", **raw)
    with pytest.raises(ValidationError):
        MarketMeta(
            venue="synthetic", market_id=MARKET, url="u", title="t", is_binary=True, source_url="https://x.invalid"
        )
    resp = RawResponse(
        url="https://synthetic.invalid/x", params={}, status_code=200, body=b"{}", collected_at=COLLECTED
    )
    with pytest.raises(MarketDataError, match="only real venues"):
        store_raw(tmp_path / "raw", "synthetic", MARKET, resp)  # type: ignore[arg-type]
    assert not (tmp_path / "raw").exists()


# ---------------------------------------------------------------- the temporal gate


def _syn_case_file(event_id: str, quotes: list[dict], *, real: bool = False, market_quote_id: str | None = REF):
    case = (real_case(event_id) if real else make_case(event_id, as_of=AS_OF)).model_copy(
        update={"market_quote_id": market_quote_id}
    )
    return {"case": case.model_dump(mode="json"), "evidence": [], "market_quotes": quotes}


def test_synthetic_quote_loads_on_a_synthetic_case_file(tmp_path):
    write_case_file(tmp_path / "cases", _syn_case_file("synthetic_x", [syn_quote_dict(AS_OF - timedelta(hours=2))]))
    store = EvidenceStore.from_dir(tmp_path / "cases")
    snap = store.get_as_of("synthetic_x", AS_OF)
    assert snap.market_baseline() == (0.35, REF)
    mi = snap.model_input("agent_plus_market")
    assert (mi.market_baseline_p_yes, mi.market_baseline_ref, mi.synthetic) == (0.35, REF, True)
    assert '"venue": "synthetic"' in mi.prompt


def test_synthetic_quote_is_refused_on_a_real_case_file(tmp_path):
    write_case_file(
        tmp_path / "cases", _syn_case_file("real_x", [syn_quote_dict(AS_OF - timedelta(hours=2))], real=True)
    )
    with pytest.raises(SyntheticQuoteOnRealCase, match="real_x.json"):
        EvidenceStore.from_dir(tmp_path / "cases")


@pytest.mark.parametrize(
    "case",
    [
        real_case("real_y", market_quote_id=REF),
        # synthetic: true is not enough on its own; the case provenance must agree.
        make_case("half_y", as_of=AS_OF, market_quote_id=REF, provenance=Provenance.REAL_HISTORICAL),
        make_case("half_z", as_of=AS_OF, market_quote_id=REF, synthetic=False),
    ],
)
def test_a_real_case_can_never_load_a_synthetic_quote_in_memory(case):
    with pytest.raises(SyntheticQuoteOnRealCase):
        EvidenceStore([CaseRecord(case=case, market_quotes=(syn_quote(AS_OF - timedelta(hours=1)),))])


def test_staleness_rule_applies_unchanged_to_synthetic_quotes():
    edge, stale = AS_OF - timedelta(hours=24), AS_OF - timedelta(hours=24, seconds=1)
    assert select_quote([syn_quote(edge)], AS_OF) is not None
    assert select_quote([syn_quote(stale)], AS_OF) is None
    store = EvidenceStore(
        [CaseRecord(case=make_case("synthetic_s", as_of=AS_OF, market_quote_id=REF), market_quotes=(syn_quote(stale),))]
    )
    snap = store.get_as_of("synthetic_s", AS_OF)
    assert snap.market_baseline() == (None, None)
    assert [(x.item_id, x.reason) for x in snap.exclusions] == [(REF, "no_quote_within_24h_before_as_of")]
    # A future synthetic quote is never seen either.
    later = EvidenceStore(
        [
            CaseRecord(
                case=make_case("synthetic_f", as_of=AS_OF, market_quote_id=REF),
                market_quotes=(syn_quote(AS_OF + timedelta(minutes=1)),),
            )
        ]
    )
    assert later.get_as_of("synthetic_f", AS_OF).market_baseline() == (None, None)


def test_market_quote_id_format_applies_unchanged(tmp_path):
    wrong = _syn_case_file("synthetic_w", [syn_quote_dict(AS_OF)], market_quote_id="synthetic:OTHER")
    write_case_file(tmp_path / "cases", wrong)
    with pytest.raises(ValueError, match="names no market"):
        EvidenceStore.from_dir(tmp_path / "cases")


# ---------------------------------------------------------------- scorecards


def synthetic_world(tmp_path, n: int, *, real_rows: int = 0):
    """n SYNTHETIC cases benchmarked on a synthetic 0.35 quote (+ real_rows real cases on a kalshi fixture quote),
    one persisted agent_only forecast each, sealed outcomes alternating NO/YES."""
    sealed = tmp_path / "data" / "sealed_outcomes"
    store = PredictionStore(tmp_path / "var" / "p.sqlite3", clock=Clock(AS_OF + timedelta(days=60)))
    vault = OutcomeVault(store, sealed_dir=sealed, clock=Clock(AS_OF + timedelta(days=90)))
    records = []
    for i in range(n + real_rows):
        as_of = AS_OF + timedelta(days=i)
        if i < n:
            event_id = f"synthetic_sv_{i:03d}"
            case = make_case(event_id, as_of=as_of, market_quote_id=REF)
            quote = syn_quote(as_of - timedelta(hours=1))
        else:
            event_id = f"real_sv_{i:03d}"
            case = real_case(event_id, as_of=as_of)
            quote = make_quote(as_of - timedelta(hours=1), "0.40")
        records.append(CaseRecord(case=case, market_quotes=(quote,)))
    gate = EvidenceStore(records)
    for i, rec in enumerate(records):
        data = sealed_dict(rec.case.event_id, outcome="YES" if i % 2 else "NO")
        data["provenance"] = "SYNTHETIC" if rec.case.synthetic else "REAL_HISTORICAL"
        write_sealed(sealed, data)
        mi = gate.get_as_of(rec.case.event_id, rec.case.as_of).model_input("agent_only")
        store.save(_pred(mi, f"pred_sv_{i:03d}", 0.35), mi)
    return vault, gate


def test_synthetic_case_with_synthetic_quote_gets_a_scorecard_row_never_official(tmp_path):
    vault, gate = synthetic_world(tmp_path, 1)
    card = build_scorecard(vault, cases=gate)
    assert card.exclusions_by_reason == {}  # no longer dropped as market_not_available
    assert [e.market_refs for e in card.per_event] == [[REF]]
    assert card.per_event[0].brier["market"] == pytest.approx(0.35**2)
    assert card.provenance == Provenance.SYNTHETIC
    assert not card.label.startswith("OFFICIAL")


def test_five_synthetic_cases_are_illustrative_never_official(tmp_path):
    vault, gate = synthetic_world(tmp_path, 5)
    card = build_scorecard(vault, cases=gate)
    assert card.n_events == 5
    assert card.label == LABEL_ILLUSTRATIVE and not card.label.startswith("OFFICIAL")
    assert card.provenance == Provenance.SYNTHETIC


def test_synthetic_cases_never_pool_with_real_ones(tmp_path):
    vault, gate = synthetic_world(tmp_path, 3, real_rows=3)
    with pytest.raises(ValueError, match="separately"):
        build_scorecard(vault, cases=gate)


# ---------------------------------------------------------------- the late check (optional item of #102)


SYN = "synthetic_fixture"


def _official_world_with_synthetic_reveal(tmp_path, monkeypatch):
    """10 committed real cases (forecasts saved for 9) plus a committed SYNTHETIC case whose forecast is saved
    and then revealed (as on stage). Returns (vault, cases, rows)."""
    from test_scoring import rows_for

    rows = rows_for(10)
    vault, cases = scored_world(
        tmp_path, rows, synthetic=False, official=monkeypatch, extra_cases=(SYN,), save=set(range(9))
    )
    mi = cases.get_as_of(SYN, cases.public_case(SYN).as_of).model_input("agent_only")
    vault.store.save(_pred(mi, "syn_pred", 0.35), mi)
    write_sealed(tmp_path / "data" / "sealed_outcomes", sealed_dict(SYN, outcome="NO"))
    vault.reveal("syn_pred")
    return vault, cases, rows


def _save_late_real(vault, cases, rows):
    e, t, *_ = rows[9]
    mi = cases.get_as_of(e, t).model_input("agent_only")
    vault.store.save(_pred(mi, "after_syn_reveal", 0.9), mi)


def test_revealing_the_synthetic_fallback_does_not_block_official(tmp_path, monkeypatch):
    vault, cases, rows = _official_world_with_synthetic_reveal(tmp_path, monkeypatch)
    _save_late_real(vault, cases, rows)
    card = build_scorecard(vault, cases=cases)
    assert card.n_events == 10
    assert card.exclusions_by_reason == {"market_not_available": 1}  # the synthetic case, not pooled
    assert card.official_blockers == []
    assert card.label == "OFFICIAL: Computed from 10 historical cases"


def test_a_real_reveal_still_blocks_official_alongside_a_synthetic_one(tmp_path, monkeypatch):
    vault, cases, rows = _official_world_with_synthetic_reveal(tmp_path, monkeypatch)
    vault.reveal("pred_000")  # a real event's outcome is now known
    _save_late_real(vault, cases, rows)
    card = build_scorecard(vault, cases=cases)
    assert card.label != "OFFICIAL: Computed from 10 historical cases"
    assert any("cross-event leakage" in b for b in card.official_blockers)


def test_a_real_reveal_before_the_synthetic_one_still_blocks_official(tmp_path, monkeypatch):
    from test_scoring import rows_for

    rows = rows_for(10)
    vault, cases = scored_world(
        tmp_path, rows, synthetic=False, official=monkeypatch, extra_cases=(SYN,), save=set(range(9))
    )
    vault.reveal("pred_000")
    mi = cases.get_as_of(SYN, cases.public_case(SYN).as_of).model_input("agent_only")
    vault.store.save(_pred(mi, "syn_pred", 0.35), mi)
    write_sealed(tmp_path / "data" / "sealed_outcomes", sealed_dict(SYN, outcome="NO"))
    vault.reveal("syn_pred")
    _save_late_real(vault, cases, rows)
    card = build_scorecard(vault, cases=cases)
    assert any("cross-event leakage" in b for b in card.official_blockers)


def test_relabelling_a_revealed_real_event_as_synthetic_does_not_hide_the_reveal(tmp_path, monkeypatch):
    """The committed file says SYN is synthetic, but its forecast froze synthetic=False (made from a real case):
    that reveal still counts."""
    from test_scoring import rows_for

    rows = rows_for(10)
    vault, cases = scored_world(
        tmp_path, rows, synthetic=False, official=monkeypatch, extra_cases=(SYN,), save=set(range(9))
    )
    other = EvidenceStore([CaseRecord(case=real_case(SYN, as_of=cases.public_case(SYN).as_of))])
    mi = other.get_as_of(SYN, cases.public_case(SYN).as_of).model_input("agent_only")
    assert mi.synthetic is False
    vault.store.save(_pred(mi, "real_ctx_pred", 0.35), mi)
    write_sealed(tmp_path / "data" / "sealed_outcomes", {**sealed_dict(SYN), "provenance": "REAL_HISTORICAL"})
    vault.reveal("real_ctx_pred")
    _save_late_real(vault, cases, rows)
    assert _synthetic_exempt_events(cases, vault.store.all_records()) == set()
    card = build_scorecard(vault, cases=cases)
    assert any("cross-event leakage" in b for b in card.official_blockers)


def test_no_exemption_without_the_committed_case_list(tmp_path, monkeypatch):
    vault, cases, _rows = _official_world_with_synthetic_reveal(tmp_path, monkeypatch)
    recs = vault.store.all_records()
    assert _synthetic_exempt_events(cases, recs) == {SYN}
    assert _synthetic_exempt_events(None, recs) == set()
    in_memory = EvidenceStore([CaseRecord(case=make_case(SYN, as_of=cases.public_case(SYN).as_of))])
    assert _synthetic_exempt_events(in_memory, recs) == set()
