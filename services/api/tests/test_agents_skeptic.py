"""Skeptic validator (issue #36, SPEC §3.3): reports problems, never edits the forecast."""

from __future__ import annotations

import json
import math

from agents.provider import ForecastOutput
from agents.skeptic import market_refs, review, split_sentences

OFFERED = ("evid_a", "evid_b", "ev.1")


def _forecast(**kw) -> ForecastOutput:
    base = {
        "p_yes": 0.55,
        "decision": "wait",
        "rationale": "Orders fell 12% (evid_a). Lead times doubled per evid_b.",
        "evidence_ids": ["evid_a", "evid_b"],
    }
    base.update(kw)
    # model_construct bypasses validation on purpose: the skeptic must not trust the type.
    return ForecastOutput.model_construct(**base)


def test_clean_forecast_has_no_problems():
    report = review(_forecast(), OFFERED)
    assert report.problems == ()
    assert not report.rejected and not report.flagged


def test_unknown_evidence_id_rejected():
    report = review(_forecast(evidence_ids=["evid_a", "evid_future"]), OFFERED)
    assert report.rejected
    (p,) = [p for p in report.problems if p.code == "UNKNOWN_EVIDENCE_ID"]
    assert p.evidence_id == "evid_future" and p.severity == "error"


def test_nan_and_out_of_range_p_yes_rejected():
    for bad in (math.nan, math.inf, -0.1, 1.5, True, "0.5", None):
        assert "P_YES_OUT_OF_RANGE" in review(_forecast(p_yes=bad), OFFERED).codes(), bad
    for ok in (0, 0.0, 1, 1.0):
        assert "P_YES_OUT_OF_RANGE" not in review(_forecast(p_yes=ok), OFFERED).codes()


def test_invalid_decision_and_overlong_rationale_rejected():
    assert "INVALID_DECISION" in review(_forecast(decision="buy"), OFFERED).codes()
    assert "RATIONALE_LENGTH" in review(_forecast(rationale="evid_a " * 120), OFFERED).codes()
    assert "RATIONALE_LENGTH" in review(_forecast(rationale=""), OFFERED).codes()


def test_uncited_claim_flagged_not_rejected():
    f = _forecast(rationale="Orders fell 12% (evid_a). The central bank will certainly cut rates next month.")
    report = review(f, OFFERED)
    assert not report.rejected and report.flagged
    (p,) = [p for p in report.problems if p.code == "UNCITED_CLAIM"]
    assert "central bank" in p.sentence


def test_insufficiency_statement_is_not_an_uncited_claim():
    f = _forecast(rationale="Orders fell 12% (evid_a). The evidence is insufficient for a confident call.")
    assert "UNCITED_CLAIM" not in review(f, OFFERED).codes()


def test_cited_in_rationale_but_not_listed_is_flagged():
    f = _forecast(evidence_ids=["evid_a"])
    report = review(f, OFFERED)
    (p,) = [p for p in report.problems if p.code == "CITATION_NOT_LISTED"]
    assert p.evidence_id == "evid_b"


def test_no_evidence_cited_and_duplicates_flagged():
    assert "NO_EVIDENCE_CITED" in review(_forecast(evidence_ids=[]), OFFERED).codes()
    assert "DUPLICATE_EVIDENCE_ID" in review(_forecast(evidence_ids=["evid_a", "evid_a", "evid_b"]), OFFERED).codes()


def test_id_matching_is_whole_token():
    # "evid_ab" must not count as a citation of "evid_a"; a sentence-final period is fine.
    f = _forecast(rationale="Demand slipped per evid_ab. Lead times doubled per evid_b.", evidence_ids=["evid_b"])
    report = review(f, OFFERED)
    (p,) = [p for p in report.problems if p.code == "UNCITED_CLAIM"]
    assert "evid_ab" in p.sentence
    # ...and "evid_ab" is shaped like an evidence id but not in a citation form: a warning, not a rejection.
    assert not report.rejected
    assert [p.evidence_id for p in report.problems if p.code == "POSSIBLE_UNKNOWN_ID"] == ["evid_ab"]
    dotted = _forecast(rationale="Shipping costs rose sharply per ev.1.", evidence_ids=["ev.1"])
    assert "UNCITED_CLAIM" not in review(dotted, OFFERED).codes()


def test_unoffered_id_in_rationale_next_to_a_real_one_rejected():
    f = _forecast(rationale="Orders fell (evid_a, evid_q) and lead times doubled per evid_b.")
    report = review(f, OFFERED)
    assert report.rejected
    assert [p.evidence_id for p in report.problems if p.code == "UNKNOWN_CITED_ID"] == ["evid_q"]


def test_ordinary_words_are_not_mistaken_for_ids():
    f = _forecast(rationale="U.S. orders fell 12% in Q3 (evid_a). Lead times doubled per evid_b.")
    assert "UNKNOWN_CITED_ID" not in review(f, OFFERED).codes()


def _slug_forecast(rationale: str, ids: list[str]) -> ForecastOutput:
    return ForecastOutput.model_construct(p_yes=0.4, decision="wait", rationale=rationale, evidence_ids=ids)


def test_slug_ids_do_not_false_reject_hyphenated_english():
    # Audit repros: the repo's evidence ids are slugs.
    f = _slug_forecast("A bad-tempered market (bad-quarter) hurts sales.", ["bad-quarter"])
    report = review(f, ["bad-quarter"])
    assert not report.rejected
    assert [p.evidence_id for p in report.problems if p.code == "POSSIBLE_UNKNOWN_ID"] == ["bad-tempered"]

    f = _slug_forecast("Prices rose for us-based firms (us-cpi).", ["us-cpi"])
    report = review(f, ["us-cpi"])
    assert not report.rejected
    assert "us-based" in [p.evidence_id for p in report.problems]

    offered = ["rate-plus-200bp", "a16z-fintech-thesis"]
    f = _slug_forecast(
        "Rate-plus scenarios and a16z-fintech themes matter (rate-plus-200bp, a16z-fintech-thesis).", offered
    )
    assert not review(f, offered).rejected


def test_unoffered_ids_in_citation_forms_rejected_any_case_or_separator():
    cases = {
        "Orders fell (evid_a, EVID_Z) per the notes.": "EVID_Z",
        "Orders fell per the notes [evid_z] and evid_a.": "evid_z",
        "Orders fell (evid_a, evid-c) per the notes.": "evid-c",
        "Rates rose (bad-quarter, rate-plus-300bp) per the notes.": "rate-plus-300bp",
    }
    offered = ["evid_a", "evid_b", "bad-quarter", "rate-plus-200bp"]
    for rationale, bad in cases.items():
        report = review(_slug_forecast(rationale, ["evid_a"]), offered)
        assert report.rejected, rationale
        assert bad in [p.evidence_id for p in report.problems if p.code == "UNKNOWN_CITED_ID"], rationale


def test_non_id_parentheticals_are_not_rejected():
    f = _forecast(rationale="Orders fell (evid_a; see the Q3 2024 report) and lead times doubled (evid_b).")
    assert "UNKNOWN_CITED_ID" not in review(f, OFFERED).codes()


def test_zero_width_only_rationale_rejected():
    assert "RATIONALE_LENGTH" in review(_forecast(rationale="​‍﻿"), OFFERED).codes()


def test_unhashable_decision_does_not_crash():
    for bad in (["act"], {"x": 1}, None, 3):
        assert "INVALID_DECISION" in review(_forecast(decision=bad), OFFERED).codes()


def test_review_never_mutates_the_forecast():
    f = ForecastOutput.parse_model_json(
        '{"p_yes": 0.3, "decision": "act", "rationale": "Unsupported claim here.", "evidence_ids": []}', OFFERED
    )
    before = f.model_dump()
    report = review(f, OFFERED)
    assert report.flagged
    assert f.model_dump() == before


def test_split_sentences_merges_short_fragments():
    assert split_sentences("U.S. GDP fell (evid_a). Rates rose per evid_b.") == [
        "U.S. GDP fell (evid_a).",
        "Rates rose per evid_b.",
    ]


# ---------------------------------------------------------------- pre-run format fixes (EVALUATION_PROTOCOL §8)
# Rehearsal finding (2026-11-14, llama3.1:8b): the model cites "(evidence_id: fomc-2026-jul.minutes)", copying the
# JSON key of the evidence items; with market input it also cites the market's id. Neither label is evidence.
FOMC = ("fomc-2026-jul.statement", "fomc-2026-jul.jobs", "fomc-2026-jul.minutes", "fomc-2026-jul.cpi")
SHOWN = ("KXFEDDECISION-26JUL-H0", "kalshi:KXFEDDECISION-26JUL-H0", "528974", "polymarket:528974")


def _fomc(rationale: str, ids: list[str] | None = None) -> ForecastOutput:
    return ForecastOutput.model_construct(
        p_yes=0.4, decision="wait", rationale=rationale, evidence_ids=ids or ["fomc-2026-jul.minutes"]
    )


def _cited_errors(report) -> list[str]:
    return [p.evidence_id for p in report.problems if p.code == "UNKNOWN_CITED_ID"]


def test_evidence_id_field_label_in_a_citation_is_not_an_unknown_id():
    for rationale in (
        "The minutes lean hawkish (evidence_id: fomc-2026-jul.minutes).",
        "The minutes lean hawkish [evidence_id: fomc-2026-jul.minutes].",
        "The minutes lean hawkish (evidence_ids: fomc-2026-jul.minutes, fomc-2026-jul.cpi).",
        'The minutes lean hawkish ("evidence_id": "fomc-2026-jul.minutes").',
        "The minutes lean hawkish (fomc-2026-jul.cpi, evidence_id: fomc-2026-jul.minutes).",
        "The minutes lean hawkish (evidence_id=fomc-2026-jul.minutes).",
    ):
        report = review(_fomc(rationale, ["fomc-2026-jul.minutes", "fomc-2026-jul.cpi"]), FOMC)
        assert not report.rejected, rationale
        assert "UNKNOWN_CITED_ID" not in report.codes(), rationale
        assert "UNCITED_CLAIM" not in report.codes(), rationale  # the id after the label still cites


def test_field_label_normalisation_never_maps_to_a_closest_id():
    # Only the label is dropped; the id after it must still match an offered id EXACTLY (no case folding either).
    for rationale, bad in {
        "Hawkish (evidence_id: fomc-2026-jul.minute).": "fomc-2026-jul.minute",
        "Hawkish (evidence_ids: fomc-2026-jul.cpi, fomc-2026-jul.gdp).": "fomc-2026-jul.gdp",
        "Hawkish (evidence_id: FOMC-2026-JUL.MINUTES).": "FOMC-2026-JUL.MINUTES",
    }.items():
        report = review(_fomc(rationale), FOMC)
        assert report.rejected, rationale
        assert _cited_errors(report) == [bad], rationale


def test_only_the_exact_schema_field_name_is_a_label():
    report = review(_forecast(rationale="Orders fell (evid_q: evid_a) per the notes."), OFFERED)
    assert _cited_errors(report) == ["evid_q"]
    report = review(_fomc("Hawkish (fomc-2026-jul.minutes, evidence_id_9: fomc-2026-jul.cpi)."), FOMC)
    assert "evidence_id_9" in _cited_errors(report)


def test_shown_market_id_cited_in_agent_plus_market_is_a_warning_not_an_error():
    for rationale, token in {
        "Markets lean to a hold (fomc-2026-jul.statement, KXFEDDECISION-26JUL-H0).": "KXFEDDECISION-26JUL-H0",
        "Markets lean to a hold (fomc-2026-jul.statement, kalshi:KXFEDDECISION-26JUL-H0).": (
            "kalshi:KXFEDDECISION-26JUL-H0"
        ),
        "Markets lean to a hold [fomc-2026-jul.cpi, 528974].": "528974",
        "Markets lean to a hold (KXFEDDECISION-26JUL-H0).": "KXFEDDECISION-26JUL-H0",
    }.items():
        report = review(_fomc(rationale, ["fomc-2026-jul.statement", "fomc-2026-jul.cpi"]), FOMC, market_refs=SHOWN)
        assert not report.rejected, rationale
        warned = [p for p in report.problems if p.code == "MARKET_ID_CITED"]
        assert [(p.evidence_id, p.severity) for p in warned] == [(token, "warning")], rationale


def test_market_id_without_market_input_is_still_rejected():
    # agent_only shows no market, so no market ref is passed and the same id stays an unknown cited id.
    rationale = "Markets lean to a hold (fomc-2026-jul.statement, KXFEDDECISION-26JUL-H0)."
    report = review(_fomc(rationale, ["fomc-2026-jul.statement"]), FOMC)
    assert report.rejected and _cited_errors(report) == ["KXFEDDECISION-26JUL-H0"]
    assert "MARKET_ID_CITED" not in report.codes()


def test_other_case_and_near_miss_market_ids_are_rejected():
    for bad in (
        "KXFEDDECISION-26JUN-H0",  # another case's market
        "KXFEDDECISION-26JUL-H1",  # near miss
        "kxfeddecision-26jul-h0",  # case changed: no case folding
        "KXFEDDECISION-26JUL",  # partial
        "polymarket:528975",  # near-miss ref
        "kalshi:528974",  # right id, wrong venue
    ):
        rationale = f"Markets lean to a hold (fomc-2026-jul.statement, {bad})."
        report = review(_fomc(rationale, ["fomc-2026-jul.statement"]), FOMC, market_refs=SHOWN)
        assert report.rejected, bad
        assert _cited_errors(report) == [bad], bad
        assert "MARKET_ID_CITED" not in report.codes(), bad


def test_market_id_in_evidence_ids_stays_an_error():
    # The evidence_ids field holds evidence only (ForecastOutput, PredictionStore.save and verify_row agree on it).
    f = _fomc("Hold likely (fomc-2026-jul.statement).", ["KXFEDDECISION-26JUL-H0"])
    report = review(f, FOMC, market_refs=SHOWN)
    assert report.rejected
    assert [p.evidence_id for p in report.problems if p.code == "UNKNOWN_EVIDENCE_ID"] == ["KXFEDDECISION-26JUL-H0"]


def test_market_refs_come_only_from_the_quotes_shown_in_the_prompt():
    from core.temporal_gate import EvidenceStore

    cases = EvidenceStore.from_dir()
    for cid in cases.case_ids():
        snap = cases.get_as_of(cid, cases.public_case(cid).as_of)
        assert market_refs(snap.model_input("agent_only").snapshot_json) == ()
        if not snap.market_available:
            continue
        mi = snap.model_input("agent_plus_market")
        quotes = json.loads(mi.snapshot_json)["market_quotes"]
        expected = {str(q["market_id"]) for q in quotes} | {f"{q['venue']}:{q['market_id']}" for q in quotes}
        assert set(market_refs(mi.snapshot_json)) == expected, cid
        assert all(ref in mi.prompt for ref in expected if ":" not in ref), cid


def test_normalisation_does_not_edit_the_rationale():
    raw = (
        '{"p_yes": 0.4, "decision": "wait", "rationale": "Hawkish (evidence_id: fomc-2026-jul.minutes, '
        'KXFEDDECISION-26JUL-H0).", "evidence_ids": ["fomc-2026-jul.minutes"]}'
    )
    f = ForecastOutput.parse_model_json(raw, FOMC)
    before = f.model_dump()
    assert not review(f, FOMC, market_refs=SHOWN).rejected
    assert f.model_dump() == before
