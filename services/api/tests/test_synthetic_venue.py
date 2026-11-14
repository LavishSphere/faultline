"""Synthetic venue for SYNTHETIC fallback quotes (issue #102).

A synthetic quote (venue "synthetic") lets a SYNTHETIC case carry a hand-written benchmark price. It must be
labelled SYNTHETIC everywhere, load only on a ``synthetic: true`` case, obey the gate's 24h staleness rule and
``venue:market_id`` reference unchanged, never reach data/raw, and never make a scorecard OFFICIAL or pool with
real cases. Reveals of committed synthetic cases do not count for the cross-event ``late`` check, and nothing
else is exempted. Every fixture here is SYNTHETIC.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from test_replay_seal import Clock, sealed_dict, write_sealed
from test_scoring import _pred, rows_for, scored_world
from test_temporal_gate import COLLECTED, make_case, make_quote, quote_dict, write_case_file

from core import store as store_module
from core.evaluator import (
    LABEL_ILLUSTRATIVE,
    OutcomeVault,
    Scorecard,
    SealedOutcomeInvalid,
    _synthetic_exempt_events,
    build_scorecard,
    event_case_sets,
)
from core.store import PredictionStore
from core.temporal_gate import CaseRecord, EvidenceStore, SyntheticQuoteOnRealCase
from main import create_app
from markets.base import (
    MARKET_LABEL,
    SYNTHETIC_QUOTE_LABEL,
    MarketDataError,
    MarketLabel,
    MarketMeta,
    NormalizedQuote,
    QuoteProvenance,
    RawQuote,
    synthetic_quote_sha256,
)
from markets.normalize import select_quote
from markets.raw_store import RawResponse, store_raw
from models import Provenance
from routes.benchmark import case_set_of, verify_snapshot

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
        "raw_sha256": synthetic_quote_sha256(market_id, ts, raw_price),
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


# ---------------------------------------------------------------- SYNTHETIC wording (prompt, API, scorecard)


def test_label_values_match_their_constants():
    assert set(MarketLabel.__args__) == {MARKET_LABEL, SYNTHETIC_QUOTE_LABEL}
    assert SYNTHETIC_QUOTE_LABEL.startswith("SYNTHETIC benchmark price written by the case author")
    assert "price-derived" not in SYNTHETIC_QUOTE_LABEL and "not from any market" in SYNTHETIC_QUOTE_LABEL


def test_synthetic_quote_hash_and_collection_time_have_a_fixed_meaning():
    q = syn_quote(AS_OF)
    assert q.raw_sha256 == synthetic_quote_sha256(MARKET, AS_OF, "0.35")
    with pytest.raises(ValidationError, match="raw_sha256"):
        NormalizedQuote.model_validate(syn_quote_dict(AS_OF, raw_sha256="0" * 64))
    with pytest.raises(ValidationError, match="raw_sha256"):  # the hash is tied to the price it states
        NormalizedQuote.model_validate(syn_quote_dict(AS_OF, "0.36", raw_sha256=q.raw_sha256))


@pytest.mark.parametrize(
    "override",
    [
        {"url": "https://kalshi.invalid/markets/X"},
        {"source_url": "https://api.synthetic.invalid/quote"},
    ],
)
def test_real_case_refuses_a_real_venue_quote_with_an_invalid_host(override):
    quote = NormalizedQuote.model_validate({**quote_dict(AS_OF - timedelta(hours=1), "0.40"), **override})
    with pytest.raises(SyntheticQuoteOnRealCase):
        EvidenceStore([CaseRecord(case=real_case("real_inv"), market_quotes=(quote,))])


def test_synthetic_quote_label_is_fixed_by_its_venue():
    assert syn_quote(AS_OF).label == SYNTHETIC_QUOTE_LABEL  # filled in when absent
    with pytest.raises(ValidationError, match="label"):
        NormalizedQuote.model_validate(syn_quote_dict(AS_OF, label=MARKET_LABEL))
    with pytest.raises(ValidationError, match="label"):
        NormalizedQuote.model_validate({**quote_dict(AS_OF, "0.40"), "label": SYNTHETIC_QUOTE_LABEL})


def test_prompt_says_synthetic_whenever_a_synthetic_quote_is_shown():
    store = EvidenceStore(
        [
            CaseRecord(
                case=make_case("synthetic_p", as_of=AS_OF, market_quote_id=REF),
                market_quotes=(syn_quote(AS_OF - timedelta(hours=1)),),
            ),
            CaseRecord(case=real_case("real_p"), market_quotes=(make_quote(AS_OF - timedelta(hours=1), "0.40"),)),
        ]
    )
    plus = store.get_as_of("synthetic_p", AS_OF).model_input("agent_plus_market").prompt
    assert "Market input (JSON). SYNTHETIC: this is a fictional case" in plus
    assert 'A quote with venue "synthetic" is a ' + SYNTHETIC_QUOTE_LABEL in plus
    assert f'"label": "{SYNTHETIC_QUOTE_LABEL}"' in plus and '"venue": "synthetic"' in plus
    assert '"provenance": "SYNTHETIC"' in plus and "REAL_HISTORICAL" not in plus
    assert "Each p_yes is a " + MARKET_LABEL not in plus  # the real-venue header is not used
    # A real case's prompt keeps the real-venue header and never mentions a synthetic price.
    real = store.get_as_of("real_p", AS_OF).model_input("agent_plus_market").prompt
    assert "Each p_yes is a " + MARKET_LABEL in real and "SYNTHETIC" not in real.split("Market input")[1]
    assert '"provenance": "REAL_HISTORICAL"' in real


def test_real_venue_quote_on_a_synthetic_case_never_displays_as_real_historical(tmp_path, monkeypatch):
    """A synthetic case may carry a hand-written kalshi/polymarket quote (test fixtures do). Its quote defaults to
    provenance REAL_HISTORICAL in the file, but the prompt and the API label it from the case: SYNTHETIC."""
    data = _syn_case_file(
        "synthetic_k", [quote_dict(AS_OF - timedelta(hours=1), "0.40")], market_quote_id="kalshi:SYNTH-FED-H25"
    )
    write_case_file(tmp_path / "data" / "demo_cases", data)
    cases = EvidenceStore.from_dir(tmp_path / "data" / "demo_cases")
    assert cases._get("synthetic_k").market_quotes[0].provenance == "REAL_HISTORICAL"  # as written in the file
    plus = cases.get_as_of("synthetic_k", AS_OF).model_input("agent_plus_market").prompt
    assert '"provenance": "SYNTHETIC"' in plus and "REAL_HISTORICAL" not in plus
    assert "Market input (JSON). SYNTHETIC: this is a fictional case" in plus
    monkeypatch.delenv("FAULTLINE_MODE", raising=False)
    monkeypatch.setenv("FAULTLINE_DATA_DIR", str(tmp_path / "data"))
    body = TestClient(create_app()).get("/api/cases/synthetic_k/evidence").json()
    assert [q["provenance"] for q in body["market_quotes"]] == ["SYNTHETIC"]
    assert body["market_at_cutoff"]["provenance"] == "SYNTHETIC"
    assert "REAL_HISTORICAL" not in json.dumps(body)


def test_cases_evidence_api_says_synthetic_for_a_synthetic_quote(tmp_path, monkeypatch):
    monkeypatch.delenv("FAULTLINE_MODE", raising=False)
    monkeypatch.setenv("FAULTLINE_DATA_DIR", str(tmp_path / "data"))
    write_case_file(
        tmp_path / "data" / "demo_cases",
        _syn_case_file("synthetic_api", [syn_quote_dict(AS_OF - timedelta(hours=2))]),
    )
    body = TestClient(create_app()).get("/api/cases/synthetic_api/evidence").json()
    [quote] = body["market_quotes"]
    assert quote["venue"] == "synthetic" and quote["label"] == SYNTHETIC_QUOTE_LABEL
    assert quote["provenance"] == "SYNTHETIC"
    m = body["market_at_cutoff"]
    assert (m["status"], m["venue"], m["ref"], m["p_yes"]) == ("AVAILABLE", "synthetic", REF, 0.35)
    assert m["label"] == SYNTHETIC_QUOTE_LABEL and m["provenance"] == "SYNTHETIC"
    assert "price-derived" not in json.dumps(m)


def test_synthetic_scorecard_market_label_says_synthetic(tmp_path):
    vault, gate = synthetic_world(tmp_path, 5)
    assert build_scorecard(vault, cases=gate).market_label == SYNTHETIC_QUOTE_LABEL
    real_vault, _ = scored_world(tmp_path / "real", rows_for(5), synthetic=False)
    assert build_scorecard(real_vault).market_label == MARKET_LABEL


# ---------------------------------------------------------------- real and synthetic case sets (never pooled)


def _add_committed_synthetic_case(tmp_path) -> EvidenceStore:
    """Commit SYN with a synthetic 0.35 quote and seal its SYNTHETIC outcome. Returns the reloaded case list."""
    write_case_file(
        tmp_path / "data" / "demo_cases",
        {
            "case": make_case(SYN, as_of=AS_OF, market_quote_id=REF).model_dump(mode="json"),
            "evidence": [],
            "market_quotes": [syn_quote_dict(AS_OF - timedelta(hours=1))],
        },
    )
    write_sealed(tmp_path / "data" / "sealed_outcomes", sealed_dict(SYN, outcome="NO"))
    return EvidenceStore.from_dir()


def _real_card_world(tmp_path, monkeypatch, *, with_synthetic: bool):
    """10 committed real cases; with_synthetic adds SYN (synthetic quote), forecast and revealed (as on stage)
    before the last real forecast is saved."""
    rows = rows_for(10)
    vault, cases = scored_world(tmp_path, rows, synthetic=False, official=monkeypatch, save=set(range(9)))
    if with_synthetic:
        cases = _add_committed_synthetic_case(tmp_path)
        mi = cases.get_as_of(SYN, AS_OF).model_input("agent_only")
        vault.store.save(_pred(mi, "syn_pred", 0.35), mi)
        vault.reveal("syn_pred")
    e, t, y, agent_p, _m = rows[9]
    mi = cases.get_as_of(e, t).model_input("agent_only")
    vault.store.save(_pred(mi, "pred_009", agent_p), mi)
    return vault, cases


def test_mixed_case_dir_does_not_raise_and_scores_each_set_separately(tmp_path, monkeypatch):
    vault, cases = _real_card_world(tmp_path, monkeypatch, with_synthetic=True)
    with pytest.raises(ValueError, match="separately"):
        build_scorecard(vault, cases=cases)  # unpartitioned: still refuses to pool
    real = build_scorecard(vault, cases=cases, case_set="real")
    syn = build_scorecard(vault, cases=cases, case_set="synthetic")
    assert (real.case_set, real.provenance, real.n_events) == ("real", Provenance.REAL_HISTORICAL, 10)
    assert real.label == "OFFICIAL: Computed from 10 historical cases" and real.official_blockers == []
    assert SYN not in {e.event_id for e in real.per_event} | {x.event_id for x in real.exclusions}
    assert (syn.case_set, syn.provenance, syn.n_events) == ("synthetic", Provenance.SYNTHETIC, 1)
    assert [e.market_refs for e in syn.per_event] == [[REF]] and syn.market_label == SYNTHETIC_QUOTE_LABEL
    assert not syn.label.startswith("OFFICIAL")


def test_real_card_is_identical_with_and_without_the_synthetic_case(tmp_path, monkeypatch):
    without, cases_a = _real_card_world(tmp_path / "a", monkeypatch, with_synthetic=False)
    card_a = build_scorecard(without, cases=cases_a, case_set="real").model_dump(mode="json")
    with_syn, cases_b = _real_card_world(tmp_path / "b", monkeypatch, with_synthetic=True)
    card_b = build_scorecard(with_syn, cases=cases_b, case_set="real").model_dump(mode="json")
    assert card_a == card_b
    assert card_a["label"] == "OFFICIAL: Computed from 10 historical cases"


def test_five_synthetic_cases_in_the_synthetic_set_are_illustrative(tmp_path):
    vault, gate = synthetic_world(tmp_path, 5, real_rows=3)
    card = build_scorecard(vault, cases=gate, case_set="synthetic")
    assert (card.label, card.case_set, card.n_events) == (LABEL_ILLUSTRATIVE, "synthetic", 5)
    real = build_scorecard(vault, cases=gate, case_set="real")
    assert (real.case_set, real.n_events, real.provenance) == ("real", 3, Provenance.REAL_HISTORICAL)


def test_case_set_rule_for_store_only_events(tmp_path):
    vault, gate = synthetic_world(tmp_path, 2, real_rows=2)
    recs = vault.store.all_records()
    # Without the case list the frozen gate context decides; with it, the committed case does (same here).
    assert event_case_sets(None, recs) == event_case_sets(gate, recs)
    assert sorted(event_case_sets(None, recs).items()) == [
        ("real_sv_002", "real"),
        ("real_sv_003", "real"),
        ("synthetic_sv_000", "synthetic"),
        ("synthetic_sv_001", "synthetic"),
    ]
    with pytest.raises(ValueError, match="case_set"):
        build_scorecard(vault, case_set="fictional")  # type: ignore[arg-type]


# ---------------------------------------------------------------- benchmark route and the official-run script


def test_benchmark_compute_and_get_serve_real_cards_before_synthetic_ones(tmp_path, monkeypatch):
    monkeypatch.delenv("FAULTLINE_MODE", raising=False)
    monkeypatch.delenv("FAULTLINE_ADMIN_TOKEN", raising=False)
    _real_card_world(tmp_path, monkeypatch, with_synthetic=True)
    c = TestClient(create_app())
    for variant in ("agent_only", "agent_plus_market"):
        resp = c.post("/api/benchmark/compute", json={"agent_variant": variant})
        assert resp.status_code == 200, resp.text
        assert [r["case_set"] for r in resp.json()["records"]] == ["real", "synthetic"]
    body = c.get("/api/benchmark").json()
    assert [(r["case_set"], r["agent_variant"]) for r in body["records"]] == [
        ("real", "agent_only"),
        ("real", "agent_plus_market"),
        ("synthetic", "agent_only"),
        ("synthetic", "agent_plus_market"),
    ]
    assert [i["case_set"] for i in body["items"]] == ["real", "real", "synthetic", "synthetic"]
    assert body["items"][0]["label"] == "OFFICIAL: Computed from 10 historical cases"
    for item in body["items"][2:]:
        assert item["provenance"] in ("SYNTHETIC", None) and not item["label"].startswith("OFFICIAL")
    # Each snapshot lists only its own set's case hashes.
    for path in sorted((tmp_path / "var" / "scorecards").glob("*.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        assert (SYN in raw["cases_sha256"]) == (raw["scorecard"]["case_set"] == "synthetic")


def test_snapshot_without_case_set_is_grouped_by_its_provenance():
    base = dict(
        label="INSUFFICIENT DATA: No valid comparison",
        verdict="INSUFFICIENT DATA",
        caveat=None,
        agent_variant="agent_only",
        forecasters=["naive", "market", "agent_only"],
        n_events=0,
        n_excluded=0,
        exclusions_by_reason={},
        exclusions=[],
        ignored_predictions=[],
        per_event=[],
        summary=None,
        comparison=None,
        official_blockers=[],
    )
    assert case_set_of(Scorecard(provenance=None, **base)) == "real"
    assert case_set_of(Scorecard(provenance=Provenance.SYNTHETIC, **base)) == "synthetic"
    assert case_set_of(Scorecard(provenance=None, case_set="synthetic", **base)) == "synthetic"


def test_record_runs_scores_a_mixed_case_dir_as_two_sets(tmp_path, monkeypatch):
    from test_record_runs import FakeModel, rr

    scored_world(tmp_path, rows_for(6), synthetic=False, official=monkeypatch, save=set())
    cases = _add_committed_synthetic_case(tmp_path)
    store = PredictionStore(store_module.DEFAULT_DB_PATH, clock=Clock(AS_OF + timedelta(days=60)))
    clock = Clock(datetime(2026, 11, 13, 12, 0, tzinfo=UTC))
    outcome = rr.run_forecasts(
        FakeModel(store.path).provider(), cases=cases, store=store, out_root=tmp_path / "out", clock=clock
    )
    assert outcome.complete
    paths = rr.score_run(outcome.run_dir, store=store, cases=cases, out_root=tmp_path / "out")
    manifest = json.loads((outcome.run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert [(s["agent_variant"], s["case_set"]) for s in manifest["scorecards"]] == [
        ("agent_only", "real"),
        ("agent_only", "synthetic"),
        ("agent_plus_market", "real"),
        ("agent_plus_market", "synthetic"),
    ]
    for path in paths:
        record, problems = verify_snapshot(
            json.loads(path.read_text(encoding="utf-8")),
            origin="committed",
            file_name=path.name,
            runs_root=tmp_path / "out" / "runs",
        )
        assert problems == [], problems
        card = record.scorecard
        if card.case_set == "synthetic":
            assert card.provenance == Provenance.SYNTHETIC and [e.event_id for e in card.per_event] == [SYN]
            assert not card.label.startswith("OFFICIAL")
        else:
            assert card.provenance == Provenance.REAL_HISTORICAL and card.n_events == 6


# ---------------------------------------------------------------- audit of #111: sealed provenance and pooling


def _reveal_rows(store: PredictionStore) -> list[tuple]:
    with sqlite3.connect(store.path) as conn:
        return conn.execute(
            "SELECT prediction_id, sealed_provenance FROM audit_log WHERE kind = 'reveal' ORDER BY seq"
        ).fetchall()


def _world_with_syn_forecast(tmp_path, monkeypatch, sealed_provenance: str):
    rows = rows_for(10)
    vault, cases = scored_world(
        tmp_path, rows, synthetic=False, official=monkeypatch, extra_cases=(SYN,), save=set(range(9))
    )
    mi = cases.get_as_of(SYN, cases.public_case(SYN).as_of).model_input("agent_only")
    vault.store.save(_pred(mi, "syn_pred", 0.35), mi)
    write_sealed(tmp_path / "data" / "sealed_outcomes", {**sealed_dict(SYN), "provenance": sealed_provenance})
    return vault, cases, rows


def test_synthetic_case_with_a_real_sealed_file_is_never_revealed(tmp_path, monkeypatch):
    """Audit repro: the case says SYNTHETIC but the sealed file says REAL_HISTORICAL. reveal() refuses before
    logging anything, so it cannot be exempted from the late check (and the message does not echo the outcome)."""
    vault, cases, rows = _world_with_syn_forecast(tmp_path, monkeypatch, "REAL_HISTORICAL")
    with pytest.raises(SealedOutcomeInvalid, match="provenance REAL_HISTORICAL") as err:
        vault.reveal("syn_pred")
    assert "YES" not in str(err.value) and "NO" not in str(err.value).replace("NOT", "")
    assert _reveal_rows(vault.store) == []
    _save_late_real(vault, cases, rows)
    card = build_scorecard(vault, cases=cases, case_set="real")
    # Nothing was revealed, so the later real forecast is not late: OFFICIAL is honest here.
    assert card.label == "OFFICIAL: Computed from 10 historical cases" and card.official_blockers == []


def test_real_case_with_a_synthetic_sealed_file_is_never_revealed(tmp_path, monkeypatch):
    vault, cases = scored_world(tmp_path, rows_for(5), synthetic=False, official=monkeypatch)
    write_sealed(tmp_path / "data" / "sealed_outcomes", {**sealed_dict(rows_for(5)[0][0]), "provenance": "SYNTHETIC"})
    with pytest.raises(SealedOutcomeInvalid, match="real case"):
        vault.reveal("pred_000")
    assert _reveal_rows(vault.store) == []


def test_reveals_are_logged_with_their_sealed_provenance(tmp_path, monkeypatch):
    vault, _cases, _rows = _official_world_with_synthetic_reveal(tmp_path, monkeypatch)
    vault.reveal("pred_000")
    assert _reveal_rows(vault.store) == [("syn_pred", "SYNTHETIC"), ("pred_000", "REAL_HISTORICAL")]


@pytest.mark.parametrize("logged", ["REAL_HISTORICAL", None])
def test_only_reveals_logged_as_synthetic_are_exempt(tmp_path, monkeypatch, logged):
    """A reveal of the committed synthetic case that was logged as REAL_HISTORICAL, or before #102 (NULL), still
    counts for the late check, even though the case and every stored context say synthetic."""
    vault, cases, rows = _world_with_syn_forecast(tmp_path, monkeypatch, "SYNTHETIC")
    pred = vault.store.get("syn_pred")
    if logged is None:
        with sqlite3.connect(vault.store.path) as conn:
            conn.execute(
                "INSERT INTO audit_log (kind, prediction_id, event_id, at) VALUES ('reveal', ?, ?, ?)",
                (pred.prediction_id, pred.event_id, (AS_OF + timedelta(days=80)).isoformat()),
            )
    else:
        vault.store.record_reveal(pred, AS_OF + timedelta(days=80), sealed_provenance=logged)
    assert _synthetic_exempt_events(cases, vault.store.all_records()) == {SYN}
    _save_late_real(vault, cases, rows)
    card = build_scorecard(vault, cases=cases, case_set="real")
    assert any("cross-event leakage" in b for b in card.official_blockers)


def test_record_reveal_needs_a_known_sealed_provenance(tmp_path):
    vault, _gate = synthetic_world(tmp_path, 1)
    with pytest.raises(ValueError, match="sealed_provenance"):
        vault.store.record_reveal(vault.store.get("pred_sv_000"), AS_OF, sealed_provenance="ILLUSTRATIVE")  # type: ignore[arg-type]


def test_sealed_provenance_column_is_added_once_to_an_older_store(tmp_path):
    from core import store as store_mod

    path = tmp_path / "old.sqlite3"
    with sqlite3.connect(path) as conn:  # the schema as created before #102 (no sealed_provenance column)
        conn.executescript(store_mod._SCHEMA)
    for _ in range(2):
        PredictionStore(path)
    with sqlite3.connect(path) as conn:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(audit_log)")]
    assert cols.count("sealed_provenance") == 1


def test_mixed_populations_fail_before_any_reveal(tmp_path):
    """Audit: the pooling error used to fire after real outcomes were revealed into the store."""
    vault, gate = synthetic_world(tmp_path, 3, real_rows=3)
    with pytest.raises(ValueError, match="nothing was revealed"):
        build_scorecard(vault, cases=gate)
    with pytest.raises(ValueError, match="nothing was revealed"):
        build_scorecard(vault)  # without the case list too
    assert _reveal_rows(vault.store) == []
    real = build_scorecard(vault, cases=gate, case_set="real")
    syn = build_scorecard(vault, cases=gate, case_set="synthetic")
    assert (real.n_events, syn.n_events) == (3, 3)
    assert {p for p, _prov in _reveal_rows(vault.store)} == {f"pred_sv_{i:03d}" for i in range(6)}


def test_a_forecast_whose_context_is_in_the_other_population_is_never_revealed(tmp_path):
    """An event only in the store with mixed frozen flags is in the real set; its synthetic-context forecast is
    excluded as context_mismatch before the reveal loop, never revealed into the real card."""
    vault, gate = synthetic_world(tmp_path, 1, real_rows=0)
    other = EvidenceStore(
        [
            CaseRecord(
                case=real_case("synthetic_sv_000", as_of=AS_OF),
                market_quotes=(make_quote(AS_OF - timedelta(hours=1), "0.40"),),
            )
        ]
    )
    mi = other.get_as_of("synthetic_sv_000", AS_OF).model_input("agent_plus_market")
    vault.store.save(_pred(mi, "real_ctx", 0.5), mi)  # same event, real context, other variant
    assert event_case_sets(None, vault.store.all_records()) == {"synthetic_sv_000": "real"}
    card = build_scorecard(vault, case_set="real")
    assert card.exclusions_by_reason == {"context_mismatch": 1} and _reveal_rows(vault.store) == []
