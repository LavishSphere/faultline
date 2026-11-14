"""Temporal gate: the only path from replay data to a prompt (SPEC §3.1, §5, §10; MATH_MODEL §7).

Written before core/temporal_gate.py. Every fixture here is SYNTHETIC (hand-written for tests), and every
date is in 2025 so that post-cutoff curation metadata (dated 2026-11) is easy to detect in a prompt.
"""

from __future__ import annotations

import ast
import dataclasses
import hashlib
import json
import os
import re
import sys
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from core import provenance
from core.temporal_gate import (
    CaseRecord,
    EvidenceStore,
    GatedSnapshot,
    MarketNotAvailable,
    SealedDataError,
    UnknownCase,
    render_prompt,
    strip_outcome_keys,
)
from markets.base import MARKET_LABEL, NormalizedQuote
from models import EvidenceItem, Provenance, ReplayCase

API_DIR = Path(__file__).resolve().parents[1]

# Duplicated on purpose (see tests/test_contracts.py): weakening models.py must not weaken this test.
OUTCOME_LIKE = re.compile(r"outcome|resolution|resolved|settle|result|winner|final_price", re.IGNORECASE)

AS_OF = datetime(2025, 1, 15, 12, 0, tzinfo=UTC)
COLLECTED = datetime(2026, 11, 13, 3, 41, tzinfo=UTC)  # post-cutoff curation time; must never reach a prompt
EVENT = "synthetic_fed_001"


# ---------------------------------------------------------------- fixture builders (shared with other test files)


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def make_case(event_id: str = EVENT, as_of: datetime = AS_OF, **overrides) -> ReplayCase:
    data = dict(
        event_id=event_id,
        title=f"SYNTHETIC: will the committee raise the target rate ({event_id})?",
        as_of=as_of,
        horizon_days=7,
        resolution_rule="Resolves YES if the published target range upper bound is higher than before the meeting.",
        evidence_ids=[],
        market_quote_id=None,
        snapshot_hash="sha256:" + "0" * 64,
        synthetic=True,
        contamination_flag="unlikely",
        provenance=Provenance.SYNTHETIC,
    )
    data.update(overrides)
    return ReplayCase(**data)


def evidence_dict(
    evidence_id: str,
    available_at: datetime,
    content: str,
    *,
    event_id: str = EVENT,
    published_at: datetime | None = None,
    retrospective_unverified: bool = False,
    archive_url: str | None = None,
) -> dict:
    published = published_at or available_at
    return {
        "evidence_id": evidence_id,
        "event_id": event_id,
        "title": f"SYNTHETIC source {evidence_id}",
        "source_url": f"https://example.org/{evidence_id}",
        "archive_url": archive_url,
        "published_at": published.isoformat(),
        "observed_at": COLLECTED.isoformat(),
        "available_at": available_at.isoformat(),
        "content_sha256": sha(content),
        "content": content,
        "retrospective_unverified": retrospective_unverified,
        "provenance": "SYNTHETIC",
    }


def make_evidence(*args, **kwargs) -> EvidenceItem:
    return EvidenceItem.model_validate(evidence_dict(*args, **kwargs))


def quote_dict(
    ts: datetime,
    raw_price: str,
    *,
    market_id: str = "SYNTH-FED-H25",
    venue: str = "kalshi",
    volume: str | None = "1200.00",
    source_url: str = "https://example.org/api/candlesticks",
) -> dict:
    return {
        "venue": venue,
        "market_id": market_id,
        "url": f"https://example.org/markets/{market_id}",
        "source_url": source_url,
        "outcome": "YES",
        "p_yes": float(raw_price),
        "quote_kind": "candle_close",
        "ts": ts.isoformat(),
        "raw_price": raw_price,
        "raw_scale": "dollars",
        "volume": volume,
        "collected_at": COLLECTED.isoformat(),
        "raw_sha256": sha(f"{market_id}{ts.isoformat()}{raw_price}"),
    }


def make_quote(*args, **kwargs) -> NormalizedQuote:
    return NormalizedQuote.model_validate(quote_dict(*args, **kwargs))


def standard_record() -> CaseRecord:
    """One case with an included item, a boundary item, and one item per exclusion reason."""
    return CaseRecord(
        case=make_case(),
        evidence=(
            make_evidence("evid_ok", AS_OF - timedelta(days=5), "Minutes signal patience on rates."),
            make_evidence("evid_edge", AS_OF, "Statement released exactly at the cutoff."),
            make_evidence("evid_future", AS_OF + timedelta(minutes=1), "FUTURE: decision announced."),
            make_evidence(
                "evid_unverified",
                AS_OF - timedelta(days=2),
                "Undated page; cannot prove this text existed then.",
                retrospective_unverified=True,
            ),
            make_evidence("evid_other", AS_OF - timedelta(days=3), "Other event.", event_id="other_event"),
        ),
        market_quotes=(
            make_quote(AS_OF - timedelta(hours=30), "0.4000"),
            make_quote(AS_OF - timedelta(hours=2), "0.5600"),
            make_quote(AS_OF + timedelta(hours=1), "0.9000"),
        ),
    )


def write_case_file(cases_dir: Path, record_dict: dict) -> Path:
    cases_dir.mkdir(parents=True, exist_ok=True)
    path = cases_dir / f"{record_dict['case']['event_id']}.json"
    path.write_text(json.dumps(record_dict, indent=2), encoding="utf-8")
    return path


def case_file_dict(event_id: str = EVENT, evidence: list[dict] | None = None, quotes: list[dict] | None = None) -> dict:
    return {
        "case": make_case(event_id).model_dump(mode="json"),
        "evidence": evidence if evidence is not None else [],
        "market_quotes": quotes if quotes is not None else [],
    }


def walk_keys(obj, path: str = "$"):
    """Yield (json_path, key, value) for every dict key in a JSON-like object."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield f"{path}.{k}", k, v
            yield from walk_keys(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from walk_keys(v, f"{path}[{i}]")


def outcome_keys_in_snapshot(snapshot_obj: dict) -> list[str]:
    """Outcome-like keys anywhere, except the market side marker `outcome == "YES"` at quote top level."""
    bad = []
    for json_path, key, value in walk_keys(snapshot_obj):
        if not OUTCOME_LIKE.search(key):
            continue
        if re.fullmatch(r"\$\.market_quotes\[\d+\]\.outcome", json_path) and value == "YES":
            continue
        bad.append(json_path)
    return bad


# ---------------------------------------------------------------- evidence filtering


def test_evidence_after_as_of_is_rejected_and_boundary_is_included():
    snap = EvidenceStore([standard_record()]).get_as_of(EVENT, AS_OF)
    ids = [e["evidence_id"] for e in snap.evidence]
    assert ids == ["evid_ok", "evid_edge"]  # available_at <= as_of, inclusive at the boundary
    reasons = {x.item_id: x.reason for x in snap.exclusions}
    assert reasons["evid_future"] == "available_after_as_of"
    assert reasons["evid_unverified"] == "retrospective_unverified"
    assert reasons["evid_other"] == "wrong_event"


def test_every_included_item_satisfies_available_at_le_as_of():
    snap = EvidenceStore([standard_record()]).get_as_of(EVENT, AS_OF)
    for item in snap.evidence:
        assert datetime.fromisoformat(item["available_at"]) <= AS_OF
        assert datetime.fromisoformat(item["published_at"]) <= AS_OF


def test_earlier_as_of_is_stricter():
    snap = EvidenceStore([standard_record()]).get_as_of(EVENT, AS_OF - timedelta(days=1))
    assert [e["evidence_id"] for e in snap.evidence] == ["evid_ok"]
    assert {x.item_id: x.reason for x in snap.exclusions}["evid_edge"] == "available_after_as_of"


def test_as_of_after_case_cutoff_is_refused():
    store = EvidenceStore([standard_record()])
    with pytest.raises(ValueError, match="after the case cutoff"):
        store.get_as_of(EVENT, AS_OF + timedelta(seconds=1))


@pytest.mark.parametrize(
    "bad",
    [
        datetime(2025, 1, 15, 12, 0),
        "2025-01-15",
        "2025-01-15Z",
        "2025-01-15+00:00",
        "2025-01-15T12:00:00",
        # Longer than a date but not an instant to the minute: refused by the format rule itself (an
        # earlier length-based check let these through).
        "2025-01-15T12+00:00",
        "2025-01-15T12Z",
    ],
)
def test_naive_or_date_only_as_of_is_refused(bad):
    with pytest.raises((TypeError, ValueError)):
        EvidenceStore([standard_record()]).get_as_of(EVENT, bad)


def test_as_of_with_offset_is_normalized_to_utc():
    est = timezone(timedelta(hours=-5))
    snap = EvidenceStore([standard_record()]).get_as_of(EVENT, AS_OF.astimezone(est))
    assert snap.as_of == AS_OF
    assert [e["evidence_id"] for e in snap.evidence] == ["evid_ok", "evid_edge"]


def test_unknown_case_raises():
    with pytest.raises(UnknownCase):
        EvidenceStore([standard_record()]).get_as_of("nope", AS_OF)


def test_duplicate_case_ids_refused():
    with pytest.raises(ValueError, match="duplicate"):
        EvidenceStore([standard_record(), standard_record()])


# ---------------------------------------------------------------- market quotes (MATH_MODEL §7)


def test_quote_selection_uses_last_quote_at_or_before_as_of():
    snap = EvidenceStore([standard_record()]).get_as_of(EVENT, AS_OF)
    assert len(snap.market_quotes) == 1
    q = snap.market_quotes[0]
    assert q["p_yes"] == 0.56
    assert datetime.fromisoformat(q["ts"]) <= AS_OF
    assert q["label"] == MARKET_LABEL


def test_stale_quote_means_market_not_available():
    record = CaseRecord(
        case=make_case(),
        evidence=(make_evidence("evid_ok", AS_OF - timedelta(days=1), "x"),),
        market_quotes=(make_quote(AS_OF - timedelta(hours=24, seconds=1), "0.4000"),),
    )
    snap = EvidenceStore([record]).get_as_of(EVENT, AS_OF)
    assert snap.market_quotes == ()
    assert snap.market_available is False
    assert [x.reason for x in snap.exclusions if x.kind == "market"] == ["no_quote_within_24h_before_as_of"]
    with pytest.raises(MarketNotAvailable):
        snap.model_input("agent_plus_market")
    # agent_only still works, and carries no market input.
    assert json.loads(snap.model_input("agent_only").snapshot_json)["market_quotes"] == []


def test_quote_exactly_24h_old_is_still_usable():
    record = CaseRecord(case=make_case(), evidence=(), market_quotes=(make_quote(AS_OF - timedelta(hours=24), "0.4"),))
    assert EvidenceStore([record]).get_as_of(EVENT, AS_OF).market_quotes[0]["p_yes"] == 0.4


def test_only_future_quotes_means_market_not_available():
    record = CaseRecord(case=make_case(), evidence=(), market_quotes=(make_quote(AS_OF + timedelta(minutes=1), "0.9"),))
    snap = EvidenceStore([record]).get_as_of(EVENT, AS_OF)
    assert snap.market_quotes == () and not snap.market_available


def test_quotes_for_two_venues_are_selected_independently():
    record = CaseRecord(
        case=make_case(),
        evidence=(),
        market_quotes=(
            make_quote(AS_OF - timedelta(hours=1), "0.5600"),
            make_quote(AS_OF - timedelta(hours=3), "0.53", venue="polymarket", market_id="123456"),
            make_quote(AS_OF - timedelta(hours=40), "0.10", venue="polymarket", market_id="999"),
        ),
    )
    snap = EvidenceStore([record]).get_as_of(EVENT, AS_OF)
    assert [(q["venue"], q["market_id"], q["p_yes"]) for q in snap.market_quotes] == [
        ("kalshi", "SYNTH-FED-H25", 0.56),
        ("polymarket", "123456", 0.53),
    ]
    assert [x.item_id for x in snap.exclusions if x.kind == "market"] == ["polymarket:999"]


def _two_market_record(market_quote_id: str | None, *, stale_named: bool = False) -> CaseRecord:
    return CaseRecord(
        case=make_case(market_quote_id=market_quote_id),
        evidence=(),
        market_quotes=(
            make_quote(AS_OF - timedelta(hours=1), "0.5600"),
            make_quote(
                AS_OF - (timedelta(hours=30) if stale_named else timedelta(hours=3)),
                "0.53",
                venue="polymarket",
                market_id="123456",
            ),
        ),
    )


@pytest.mark.parametrize(
    ("market_quote_id", "stale_named", "expected"),
    [
        (None, False, (None, None)),  # two markets, none named: no silent choice
        ("kalshi:SYNTH-FED-H25", False, (0.56, "kalshi:SYNTH-FED-H25")),
        ("polymarket:123456", False, (0.53, "polymarket:123456")),
        ("polymarket:123456", True, (None, None)),  # the named market is stale: NOT AVAILABLE, no fallback
        ("quote_001", False, (None, None)),  # not a venue:market_id reference
    ],
)
def test_market_baseline_follows_the_fixed_rule(market_quote_id, stale_named, expected):
    snap = EvidenceStore([_two_market_record(market_quote_id, stale_named=stale_named)]).get_as_of(EVENT, AS_OF)
    assert snap.market_baseline() == expected
    mi = snap.model_input("agent_only")
    assert (mi.market_baseline_p_yes, mi.market_baseline_ref) == expected


def test_single_market_is_the_baseline_and_context_comes_from_the_case():
    record = CaseRecord(
        case=make_case(contamination_flag="likely", synthetic=True),
        evidence=(),
        market_quotes=(make_quote(AS_OF - timedelta(hours=2), "0.5600"),),
    )
    mi = EvidenceStore([record]).get_as_of(EVENT, AS_OF).model_input("agent_only")
    assert (mi.market_baseline_p_yes, mi.market_baseline_ref) == (0.56, "kalshi:SYNTH-FED-H25")
    assert (mi.contamination_flag, mi.synthetic) == ("likely", True)
    # The scoring context is audit data, never model input.
    assert "0.56" not in mi.prompt and "0.56" not in mi.snapshot_json and "likely" not in mi.prompt


@pytest.mark.parametrize(
    ("market_quote_id", "markets", "match"),
    [
        ("kalshi:NOT-IN-FILE", 1, "names no market"),
        (None, 2, "no market_quote_id"),
    ],
)
def test_committed_case_files_must_name_an_existing_benchmark_market(tmp_path, market_quote_id, markets, match):
    quotes = [quote_dict(AS_OF - timedelta(hours=1), "0.56")]
    if markets == 2:
        quotes.append(quote_dict(AS_OF - timedelta(hours=2), "0.53", venue="polymarket", market_id="123456"))
    data = case_file_dict(quotes=quotes)
    data["case"]["market_quote_id"] = market_quote_id
    cases = tmp_path / "data" / "demo_cases"
    write_case_file(cases, data)
    with pytest.raises(ValueError, match=match):
        EvidenceStore.from_dir(cases)
    data["case"]["market_quote_id"] = "kalshi:SYNTH-FED-H25"
    write_case_file(cases, data)
    assert EvidenceStore.from_dir(cases).get_as_of(EVENT, AS_OF).market_baseline() == (0.56, "kalshi:SYNTH-FED-H25")


def test_case_content_hash_is_frozen_into_the_model_input(tmp_path):
    base = EvidenceStore([standard_record()])
    mi = base.get_as_of(EVENT, AS_OF).model_input("agent_only")
    assert mi.case_sha256 == base.case_sha256(EVENT) and len(mi.case_sha256) == 64
    relabeled = CaseRecord(
        case=make_case(contamination_flag="likely"),
        evidence=standard_record().evidence,
        market_quotes=standard_record().market_quotes,
    )
    other = EvidenceStore([relabeled]).get_as_of(EVENT, AS_OF).model_input("agent_only")
    assert other.case_sha256 != mi.case_sha256
    # Loading the same content from a committed file gives the same hash (formatting does not matter).
    cases = tmp_path / "demo_cases"
    rec = standard_record()
    write_case_file(
        cases,
        {
            "case": rec.case.model_dump(mode="json"),
            "evidence": [e.model_dump(mode="json") for e in rec.evidence],
            "market_quotes": [q.model_dump(mode="json") for q in rec.market_quotes],
        },
    )
    loaded = EvidenceStore.from_dir(cases)
    assert loaded.case_sha256(EVENT) == base.case_sha256(EVENT)
    assert loaded.source_dir == cases.resolve() and base.source_dir is None


# ---------------------------------------------------------------- outcome-key stripping


def test_strip_outcome_keys_recursive():
    obj = {
        "a": 1,
        "resolution_note": "x",
        "nested": {"Settlement_Value": "y", "ok": [{"winner": 1, "k": 2}], "final_price": 1},
        "Result": 0,
        "resolved": True,
    }
    assert strip_outcome_keys(obj) == {"a": 1, "nested": {"ok": [{"k": 2}]}}


def test_market_outcome_yes_is_allowlisted_only_for_quotes():
    assert strip_outcome_keys({"outcome": "YES", "p": 1}) == {"p": 1}
    assert strip_outcome_keys({"outcome": "YES", "p": 1}, allow_market_side=True) == {"outcome": "YES", "p": 1}
    # Any other value is not a side marker, so it is stripped even for quotes.
    assert strip_outcome_keys({"outcome": "NO", "p": 1}, allow_market_side=True) == {"p": 1}
    # Only at the top level of a quote, never nested.
    assert strip_outcome_keys({"x": {"outcome": "YES"}}, allow_market_side=True) == {"x": {}}


def test_snapshot_keeps_market_outcome_and_has_no_other_outcome_keys():
    snap = EvidenceStore([standard_record()]).get_as_of(EVENT, AS_OF)
    mi = snap.model_input("agent_plus_market")
    obj = json.loads(mi.snapshot_json)
    assert obj["market_quotes"][0]["outcome"] == "YES"
    assert outcome_keys_in_snapshot(obj) == []


def test_outcome_like_keys_in_evidence_file_are_stripped(tmp_path):
    ev = evidence_dict("evid_ok", AS_OF - timedelta(days=1), "Visible text.")
    ev["resolved_value"] = "YES"
    ev["outcome"] = "YES"  # in evidence, `outcome` is never a market side marker
    cases = tmp_path / "data" / "demo_cases"
    write_case_file(cases, case_file_dict(evidence=[ev]))
    snap = EvidenceStore.from_dir(cases).get_as_of(EVENT, AS_OF)
    assert [e["evidence_id"] for e in snap.evidence] == ["evid_ok"]
    obj = json.loads(snap.model_input("agent_only").snapshot_json)
    assert outcome_keys_in_snapshot(obj) == []


@pytest.mark.parametrize(
    ("key", "value"),
    [("outcome", "NO"), ("outcome", "yes"), ("Outcome", "NO"), ("OUTCOME", "YES"), ("outcome", 1)],
)
def test_quote_file_with_non_yes_outcome_is_refused(tmp_path, key, value):
    q = quote_dict(AS_OF - timedelta(hours=1), "0.5")
    q[key] = value
    cases = tmp_path / "data" / "demo_cases"
    write_case_file(cases, case_file_dict(quotes=[q]))
    with pytest.raises(SealedDataError):
        EvidenceStore.from_dir(cases)


@pytest.mark.parametrize("key", ["outcome", "resolved_yes", "result", "settlement_value", "winner"])
def test_case_file_with_outcome_section_is_refused(tmp_path, key):
    data = case_file_dict()
    data[key] = 1
    cases = tmp_path / "data" / "demo_cases"
    write_case_file(cases, data)
    with pytest.raises(SealedDataError):
        EvidenceStore.from_dir(cases)


def test_case_definition_with_outcome_field_is_refused(tmp_path):
    data = case_file_dict()
    data["case"]["resolved_outcome"] = "YES"
    cases = tmp_path / "data" / "demo_cases"
    write_case_file(cases, data)
    with pytest.raises(SealedDataError):
        EvidenceStore.from_dir(cases)


def test_case_file_name_must_match_event_id(tmp_path):
    cases = tmp_path / "data" / "demo_cases"
    path = write_case_file(cases, case_file_dict())
    path.rename(cases / "different.json")
    with pytest.raises(ValueError, match="file name"):
        EvidenceStore.from_dir(cases)


def test_missing_cases_dir_gives_an_empty_store(tmp_path):
    assert EvidenceStore.from_dir(tmp_path / "absent").case_ids() == []


# ---------------------------------------------------------------- prompt projection and rendering


def test_prompt_projection_drops_post_cutoff_curation_metadata():
    record = CaseRecord(
        case=make_case(),
        evidence=(
            make_evidence(
                "evid_ok",
                AS_OF - timedelta(days=1),
                "Visible.",
                archive_url="https://web.archive.org/web/20261113000000/https://example.org/evid_ok",
            ),
        ),
        market_quotes=(make_quote(AS_OF - timedelta(hours=1), "0.5600"),),
    )
    snap = EvidenceStore([record]).get_as_of(EVENT, AS_OF)
    mi = snap.model_input("agent_plus_market")
    for text in (mi.prompt, mi.snapshot_json):
        assert "2026" not in text  # observed_at, collected_at, archive capture time
        assert "observed_at" not in text and "collected_at" not in text
        assert "web.archive.org" not in text
        assert "api/candlesticks" not in text  # API endpoint (venue tier) is not question content
    assert set(snap.evidence[0]) == {
        "evidence_id",
        "title",
        "published_at",
        "available_at",
        "source_url",
        "content",
        "provenance",
    }


def test_prompt_has_as_of_but_no_current_date():
    mi = EvidenceStore([standard_record()]).get_as_of(EVENT, AS_OF).model_input("agent_only")
    assert "2025-01-15T12:00:00Z" in mi.prompt
    assert datetime.now(UTC).date().isoformat() not in mi.prompt


def test_variants_are_distinct_and_labeled():
    snap = EvidenceStore([standard_record()]).get_as_of(EVENT, AS_OF)
    only = snap.model_input("agent_only")
    plus = snap.model_input("agent_plus_market")
    assert only.variant == "agent_only" and plus.variant == "agent_plus_market"
    assert "variant: agent_only" in only.prompt and "variant: agent_plus_market" in plus.prompt
    assert only.prompt_sha256 != plus.prompt_sha256
    assert only.snapshot_sha256 != plus.snapshot_sha256
    # agent_only gets no market price at all.
    assert json.loads(only.snapshot_json)["market_quotes"] == []
    assert "0.56" not in only.prompt and "SYNTH-FED-H25" not in only.prompt and MARKET_LABEL not in only.prompt
    assert "0.56" in plus.prompt and MARKET_LABEL in plus.prompt
    # Same evidence in both.
    assert json.loads(only.snapshot_json)["evidence"] == json.loads(plus.snapshot_json)["evidence"]


def test_unsupported_variant_is_refused():
    snap = EvidenceStore([standard_record()]).get_as_of(EVENT, AS_OF)
    with pytest.raises(ValueError):
        snap.model_input("hosted_comparator")


def test_hashes_match_the_exact_prompt_and_snapshot():
    mi = EvidenceStore([standard_record()]).get_as_of(EVENT, AS_OF).model_input("agent_plus_market")
    assert mi.prompt_sha256 == hashlib.sha256(mi.prompt.encode("utf-8")).hexdigest()
    assert mi.snapshot_sha256 == hashlib.sha256(mi.snapshot_json.encode("utf-8")).hexdigest()
    assert mi.snapshot_json == provenance.canonical_json(json.loads(mi.snapshot_json))
    assert mi.evidence_ids == ("evid_ok", "evid_edge")
    assert render_prompt(EvidenceStore([standard_record()]).get_as_of(EVENT, AS_OF), "agent_plus_market") == mi.prompt


def test_rendering_is_deterministic():
    a = EvidenceStore([standard_record()]).get_as_of(EVENT, AS_OF).model_input("agent_plus_market")
    b = EvidenceStore([standard_record()]).get_as_of(EVENT, AS_OF).model_input("agent_plus_market")
    assert a == b


def test_prompt_contains_case_question_and_criteria():
    mi = EvidenceStore([standard_record()]).get_as_of(EVENT, AS_OF).model_input("agent_only")
    case = make_case()
    assert case.title in mi.prompt and case.resolution_rule in mi.prompt
    assert "Minutes signal patience on rates." in mi.prompt
    assert "FUTURE: decision announced." not in mi.prompt


# ---------------------------------------------------------------- structure: the gate cannot be bypassed


def test_gated_snapshot_cannot_be_built_outside_the_store():
    with pytest.raises(TypeError):
        GatedSnapshot(case=None, as_of=AS_OF, evidence=(), market_quotes=(), exclusions=())  # type: ignore[arg-type]


def test_gated_snapshot_cannot_be_forged_with_dataclasses_replace():
    snap = EvidenceStore([standard_record()]).get_as_of(EVENT, AS_OF)
    future = dict(snap.evidence[0], evidence_id="future", available_at="2030-01-01T00:00:00Z", content="CANARY")
    with pytest.raises(TypeError):
        dataclasses.replace(snap, evidence=(*snap.evidence, future))
    with pytest.raises(TypeError):
        dataclasses.replace(snap.model_input("agent_only"), prompt="forged")


def test_public_case_lists_only_admissible_evidence_ids():
    rec = standard_record()
    rec = CaseRecord(
        case=make_case(evidence_ids=["evid_ok", "evid_edge", "evid_future", "evid_unverified", "evid_other"]),
        evidence=rec.evidence,
        market_quotes=rec.market_quotes,
    )
    store = EvidenceStore([rec])
    assert store.public_case(EVENT).evidence_ids == ["evid_ok", "evid_edge"]
    assert store.get_as_of(EVENT, AS_OF - timedelta(days=1)).case.evidence_ids == ["evid_ok"]


def _allowed_line(prompt: str) -> list[str]:
    (line,) = [ln for ln in prompt.splitlines() if ln.startswith("Allowed evidence ids")]
    return json.loads(line.split(": ", 1)[1])


def test_prompt_lists_exactly_the_gated_evidence_ids_replay_v2():
    # Pre-run format fix (2026-11-14): an explicit allowed-id list. It must name ONLY gated items: a late or
    # unverified item's id is withheld exactly like its content.
    for as_of, expected in ((AS_OF, ["evid_ok", "evid_edge"]), (AS_OF - timedelta(days=1), ["evid_ok"])):
        for variant in ("agent_only", "agent_plus_market"):
            try:
                mi = EvidenceStore([standard_record()]).get_as_of(EVENT, as_of).model_input(variant)
            except MarketNotAvailable:
                continue
            assert "template: replay-v2" in mi.prompt
            assert _allowed_line(mi.prompt) == list(mi.evidence_ids) == expected
            for withheld in ("evid_future", "evid_unverified", "evid_other"):
                assert withheld not in mi.prompt
            assert f"e.g. ({expected[0]})" in mi.prompt
            assert ("never put a market_id in evidence_ids" in mi.prompt) == (variant == "agent_plus_market")


def test_every_committed_prompt_lists_its_offered_ids():
    cases = EvidenceStore.from_dir()
    for cid in cases.case_ids():
        snap = cases.get_as_of(cid, cases.public_case(cid).as_of)
        for variant in ("agent_only", "agent_plus_market"):
            try:
                mi = snap.model_input(variant)
            except MarketNotAvailable:
                continue
            assert _allowed_line(mi.prompt) == list(mi.evidence_ids), (cid, variant)


def test_render_prompt_only_accepts_gated_snapshots():
    with pytest.raises(TypeError):
        render_prompt({"evidence": [], "market_quotes": []}, "agent_only")  # type: ignore[arg-type]


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            out.add(mod)
            out |= {f"{mod}.{a.name}" for a in node.names}
    return out


PROMPT_PATH_MODULES = [
    API_DIR / "core" / "temporal_gate.py",
    API_DIR / "core" / "provenance.py",
    API_DIR / "core" / "store.py",
    *sorted((API_DIR / "agents").glob("*.py")),
]


@pytest.mark.parametrize("path", PROMPT_PATH_MODULES, ids=lambda p: str(p.relative_to(API_DIR)))
def test_prompt_path_modules_never_import_the_evaluator(path):
    bad = {m for m in _imported_modules(path) if "evaluator" in m}
    assert bad == set(), f"{path.name} imports the outcome vault: {bad}"


@pytest.mark.parametrize("path", PROMPT_PATH_MODULES, ids=lambda p: str(p.relative_to(API_DIR)))
def test_prompt_path_modules_do_not_name_sealed_outcomes_except_as_a_refusal(path):
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if "sealed_outcomes" in ln]
    # The only allowed mention is the gate's forbidden-directory constant (used to refuse reads).
    assert all("_FORBIDDEN_DIR" in ln for ln in lines), lines


class _OpenRecorder:
    """sys.audit hook recording every file open and directory listing while active (catches C-level opens)."""

    def __init__(self) -> None:
        self.active = False
        self.paths: list[str] = []

    def __call__(self, event: str, args: tuple) -> None:
        if not self.active:
            return
        if event == "open" and args and args[0] is not None:
            self.paths.append(self._slashed(args[0]))
        elif event in ("os.listdir", "os.scandir") and args:
            self.paths.append(self._slashed(args[0]))

    @staticmethod
    def _slashed(path) -> str:
        # Windows paths use "\", so checks like "/out/runs/" in p would never match there (#122). No-op elsewhere.
        return str(path).replace("\\", "/") if os.sep == "\\" else str(path)


_RECORDER = _OpenRecorder()
sys.addaudithook(_RECORDER)


@pytest.fixture
def file_access():
    _RECORDER.paths = []
    _RECORDER.active = True
    try:
        yield _RECORDER.paths
    finally:
        _RECORDER.active = False


def test_gate_never_reads_sealed_outcomes(tmp_path, file_access):
    data = tmp_path / "data"
    cases = data / "demo_cases"
    write_case_file(
        cases,
        case_file_dict(
            evidence=[evidence_dict("evid_ok", AS_OF - timedelta(days=1), "Visible.")],
            quotes=[quote_dict(AS_OF - timedelta(hours=1), "0.5600")],
        ),
    )
    sealed = data / "sealed_outcomes"
    sealed.mkdir()
    (sealed / f"{EVENT}.json").write_text(json.dumps({"event_id": EVENT, "outcome": "YES"}), encoding="utf-8")
    file_access.clear()  # record only what the gate does, not the fixture setup above

    store = EvidenceStore.from_dir(cases)
    snap = store.get_as_of(EVENT, AS_OF)
    snap.model_input("agent_only")
    snap.model_input("agent_plus_market")
    store.public_case(EVENT)

    assert any(p.endswith(f"{EVENT}.json") and "demo_cases" in p for p in file_access), "recorder saw nothing"
    assert [p for p in file_access if "sealed_outcomes" in p] == []


def test_from_dir_refuses_the_sealed_outcomes_directory(tmp_path):
    sealed = tmp_path / "data" / "sealed_outcomes"
    sealed.mkdir(parents=True)
    with pytest.raises(SealedDataError):
        EvidenceStore.from_dir(sealed)
    with pytest.raises(SealedDataError):
        EvidenceStore.from_dir(sealed / "nested")


def test_from_dir_refuses_a_symlink_into_sealed_outcomes(tmp_path, make_symlink):
    data = tmp_path / "data"
    sealed = data / "sealed_outcomes"
    sealed.mkdir(parents=True)
    target = sealed / f"{EVENT}.json"
    target.write_text(json.dumps(case_file_dict()), encoding="utf-8")
    cases = data / "demo_cases"
    cases.mkdir()
    make_symlink(cases / f"{EVENT}.json", target)
    with pytest.raises(SealedDataError):
        EvidenceStore.from_dir(cases)


@pytest.mark.parametrize("name", ["SEALED_OUTCOMES", "Sealed_Outcomes", "sealed_outcomeS"])
def test_from_dir_refuses_sealed_dir_in_any_letter_case(tmp_path, name):
    (tmp_path / "data" / "sealed_outcomes").mkdir(parents=True)
    with pytest.raises(SealedDataError):
        EvidenceStore.from_dir(tmp_path / "data" / name)


def test_from_dir_refuses_the_configured_sealed_dir_by_inode(tmp_path, monkeypatch, make_symlink):
    """Name checks alone are not enough: the configured sealed directory is also matched by (st_dev, st_ino)."""
    from core import temporal_gate

    vault_dir = tmp_path / "innocent_name"  # stands in for the configured sealed directory
    (vault_dir / "nested").mkdir(parents=True)
    monkeypatch.setattr(temporal_gate, "_configured_sealed_dir", lambda: vault_dir)
    with pytest.raises(SealedDataError):
        EvidenceStore.from_dir(vault_dir)
    with pytest.raises(SealedDataError):
        EvidenceStore.from_dir(vault_dir / "nested")
    alias = tmp_path / "alias"
    make_symlink(alias, vault_dir, target_is_directory=True)
    with pytest.raises(SealedDataError):
        EvidenceStore.from_dir(alias)
    assert EvidenceStore.from_dir(tmp_path / "elsewhere").case_ids() == []


# The `make_symlink` helper (tests/conftest.py, #122) skips only when the OS refuses to create the link.
# Path.symlink_to is replaced, so these run the same way on every OS.


def _privilege_not_held() -> OSError:
    exc = OSError(22, "A required privilege is not held by the client")
    exc.winerror = 1314  # set by hand: the constructor ignores winerror outside Windows
    return exc


def _raise(exc):
    def fake(self, target, target_is_directory=False):
        raise exc

    return fake


def test_make_symlink_skips_with_a_clear_reason_on_winerror_1314(tmp_path, monkeypatch, make_symlink):
    monkeypatch.setattr(Path, "symlink_to", _raise(_privilege_not_held()))
    with pytest.raises(pytest.skip.Exception) as skipped:
        make_symlink(tmp_path / "link", tmp_path / "target")
    assert str(skipped.value) == (
        "OS refused to create a symlink (Windows without Developer Mode/admin): WinError 1314"
    )


@pytest.mark.parametrize("exc", [NotImplementedError("symlinks unsupported")])
def test_make_symlink_skips_when_symlinks_are_unsupported(tmp_path, monkeypatch, make_symlink, exc):
    monkeypatch.setattr(Path, "symlink_to", _raise(exc))
    with pytest.raises(pytest.skip.Exception) as skipped:
        make_symlink(tmp_path / "link", tmp_path / "target")
    assert str(skipped.value).startswith("OS refused to create a symlink: ")


def test_make_symlink_does_not_skip_when_creation_succeeds(tmp_path, monkeypatch, make_symlink):
    calls = []

    def fake(self, target, target_is_directory=False):
        calls.append((self, target, target_is_directory))

    monkeypatch.setattr(Path, "symlink_to", fake)
    try:
        make_symlink(tmp_path / "link", tmp_path / "target", target_is_directory=True)
    except pytest.skip.Exception as skipped:  # a skip here would hide the bug, so turn it into a failure
        pytest.fail(f"skipped although the symlink was created: {skipped}")
    assert calls == [(tmp_path / "link", tmp_path / "target", True)]


@pytest.mark.parametrize(
    "exc",
    [
        FileExistsError(17, "File exists"),
        OSError(28, "No space left on device"),
        FileNotFoundError(2, "missing"),
        # A plain PermissionError (no winerror 1314) is a real failure: on macOS/Linux skipping it would silently
        # skip the sealed-folder protection tests (review of PR #139).
        PermissionError(1, "not permitted"),
    ],
)
def test_make_symlink_fails_instead_of_skipping_on_other_errors(tmp_path, monkeypatch, make_symlink, exc):
    monkeypatch.setattr(Path, "symlink_to", _raise(exc))
    try:
        with pytest.raises(type(exc)):
            make_symlink(tmp_path / "link", tmp_path / "target")
    except pytest.skip.Exception as skipped:  # a skip here would hide the bug, so turn it into a failure
        pytest.fail(f"skipped on an error that is not a symlink refusal: {skipped}")


def test_from_dir_refuses_hard_linked_case_files(tmp_path):
    data = tmp_path / "data"
    sealed = data / "sealed_outcomes"
    sealed.mkdir(parents=True)
    target = sealed / f"{EVENT}.json"
    target.write_text(json.dumps(case_file_dict()), encoding="utf-8")
    cases = data / "demo_cases"
    cases.mkdir()
    os.link(target, cases / f"{EVENT}.json")
    with pytest.raises(SealedDataError, match="hard link"):
        EvidenceStore.from_dir(cases)


def test_public_case_has_no_outcome_like_keys():
    public = EvidenceStore([standard_record()]).public_case(EVENT).model_dump(mode="json")
    assert [p for p, k, _ in walk_keys(public) if OUTCOME_LIKE.search(k)] == []
