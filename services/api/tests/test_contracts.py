"""Shared Pydantic contracts (SPEC §5).

The key property: pre-reveal response models have NO outcome-like field at all, so returning a
sealed outcome before reveal is a type error rather than a forgotten `if`.
"""

from __future__ import annotations

import re
import types
import typing
from datetime import UTC, datetime

import pytest
from pydantic import BaseModel, ValidationError

import models
from models import (
    ApiError,
    ErrorCode,
    EvidenceItem,
    MarketQuoteRef,
    Prediction,
    Provenance,
    ReplayCase,
    ReplayCasePublic,
)

# Deliberately duplicated here (not imported from models) so weakening the constant in models.py
# cannot silently weaken this test. Source: replay-integrity skill.
OUTCOME_LIKE = re.compile(r"outcome|resolution|resolved|settle|result|winner|final_price", re.IGNORECASE)

PRE_REVEAL_MODELS: list[type[BaseModel]] = [ReplayCasePublic, EvidenceItem, MarketQuoteRef, Prediction]

AS_OF = datetime(2025, 1, 15, 12, 0, tzinfo=UTC)
H = "a" * 64


def _nested_models(tp) -> list[type[BaseModel]]:
    """All BaseModel classes reachable from a type annotation (Optional, list, Union, ...)."""
    out: list[type[BaseModel]] = []
    if isinstance(tp, type) and issubclass(tp, BaseModel):
        out.append(tp)
    for arg in typing.get_args(tp):
        out.extend(_nested_models(arg))
    if isinstance(tp, types.UnionType):
        for arg in tp.__args__:
            out.extend(_nested_models(arg))
    return out


def _all_field_names(model: type[BaseModel], seen: set | None = None) -> set[str]:
    seen = seen if seen is not None else set()
    if model in seen:
        return set()
    seen.add(model)
    names: set[str] = set()
    for name, field in model.model_fields.items():
        names.add(name)
        if field.alias:
            names.add(field.alias)
        for sub in _nested_models(field.annotation):
            names |= _all_field_names(sub, seen)
    return names


def _walk_keys(obj) -> set[str]:
    if isinstance(obj, dict):
        keys = set(obj)
        for v in obj.values():
            keys |= _walk_keys(v)
        return keys
    if isinstance(obj, list):
        return set().union(*(_walk_keys(v) for v in obj)) if obj else set()
    return set()


def _case(**overrides) -> ReplayCase:
    data = dict(
        event_id="demo_macro_001",
        title="Will the specified event occur under the published settlement rule?",
        as_of=AS_OF,
        horizon_days=30,
        resolution_rule="Exact quoted settlement criteria",
        evidence_ids=["evid_a", "evid_b"],
        market_quote_id="quote_001",
        snapshot_hash="sha256:" + H,
        synthetic=True,
        contamination_flag="unknown",
        provenance=Provenance.SYNTHETIC,
    )
    data.update(overrides)
    return ReplayCase(**data)


# ---------------------------------------------------------------- outcome isolation


@pytest.mark.parametrize("model", PRE_REVEAL_MODELS, ids=lambda m: m.__name__)
def test_pre_reveal_models_have_no_outcome_like_fields(model):
    bad = sorted(n for n in _all_field_names(model) if OUTCOME_LIKE.search(n))
    assert bad == [], f"{model.__name__} exposes outcome-like fields: {bad}"


@pytest.mark.parametrize("model", PRE_REVEAL_MODELS, ids=lambda m: m.__name__)
def test_pre_reveal_models_forbid_extra_fields(model):
    assert model.model_config.get("extra") == "forbid"


def test_replay_case_public_rejects_smuggled_outcome():
    public = ReplayCasePublic.from_case(_case()).model_dump()
    for key in ("outcome", "resolved_yes", "result", "winner", "final_price"):
        with pytest.raises(ValidationError):
            ReplayCasePublic(**public, **{key: 1})


def test_replay_case_public_json_has_no_outcome_keys():
    payload = ReplayCasePublic.from_case(_case()).model_dump(mode="json")
    bad = sorted(k for k in _walk_keys(payload) if OUTCOME_LIKE.search(k))
    assert bad == []


def test_replay_case_public_preserves_case_fields():
    case = _case()
    public = ReplayCasePublic.from_case(case)
    assert public.event_id == case.event_id
    assert public.as_of == case.as_of
    assert public.question_criteria == case.resolution_rule
    assert public.evidence_ids == case.evidence_ids
    assert public.provenance is Provenance.SYNTHETIC


def test_models_outcome_pattern_covers_required_terms():
    for term in ("outcome", "resolution", "resolved", "settle", "result", "winner", "final_price"):
        assert models.OUTCOME_FIELD_PATTERN.search(term), term


# ---------------------------------------------------------------- provenance


def test_provenance_enum_exact_members_and_labels():
    assert {p.name for p in Provenance} == {
        "REAL_HISTORICAL",
        "SYNTHETIC",
        "RECORDED_RUN",
        "SIMULATED",
        "ILLUSTRATIVE",
    }
    assert Provenance.REAL_HISTORICAL.label == "REAL HISTORICAL"
    assert Provenance.RECORDED_RUN.label == "RECORDED RUN"
    assert Provenance("SYNTHETIC") is Provenance.SYNTHETIC


def test_provenance_wire_format_is_enum_value_not_label():
    """Canonical JSON value is the underscored name; the spaced text is display-only (.label)."""
    case = _case(provenance=Provenance.REAL_HISTORICAL)
    assert ReplayCasePublic.from_case(case).model_dump(mode="json")["provenance"] == "REAL_HISTORICAL"
    with pytest.raises(ValidationError):
        _case(provenance="REAL HISTORICAL")


# ---------------------------------------------------------------- validation


def test_replay_case_requires_timezone_aware_as_of():
    with pytest.raises(ValidationError):
        _case(as_of=datetime(2025, 1, 15, 12, 0))


def test_replay_case_snapshot_hash_format():
    with pytest.raises(ValidationError):
        _case(snapshot_hash="not-a-hash")


def test_replay_case_contamination_flag_values():
    assert _case(contamination_flag="likely").contamination_flag == "likely"
    with pytest.raises(ValidationError):
        _case(contamination_flag="definitely_clean")


def test_evidence_item_requires_all_timestamps_and_hash():
    ok = EvidenceItem(
        evidence_id="evid_a",
        event_id="demo_macro_001",
        title="Example source",
        source_url="https://example.com/a",
        published_at=AS_OF,
        observed_at=AS_OF,
        available_at=AS_OF,
        content_sha256=H,
        content="text",
        provenance=Provenance.SYNTHETIC,
    )
    assert ok.retrospective_unverified is False
    missing = ok.model_dump()
    missing.pop("available_at")
    with pytest.raises(ValidationError):
        EvidenceItem(**missing)
    with pytest.raises(ValidationError):
        EvidenceItem(**{**ok.model_dump(), "content_sha256": "XYZ"})


def _evidence(**overrides) -> EvidenceItem:
    data = dict(
        evidence_id="evid_a",
        event_id="demo_macro_001",
        title="Example source",
        source_url="https://example.com/a",
        published_at=AS_OF,
        observed_at=AS_OF,
        available_at=AS_OF,
        content_sha256=H,
        content="text",
        provenance=Provenance.SYNTHETIC,
    )
    data.update(overrides)
    return EvidenceItem(**data)


@pytest.mark.parametrize(
    "url", ["ftp://example.com/a", "file:///etc/passwd", "javascript:alert(1)", "example.com/a", "https://", ""]
)
def test_evidence_item_rejects_non_http_urls(url):
    with pytest.raises(ValidationError):
        _evidence(source_url=url)
    with pytest.raises(ValidationError):
        _evidence(archive_url=url)


def test_evidence_item_accepts_http_and_https_urls():
    assert _evidence(source_url="http://example.com/a").source_url == "http://example.com/a"
    item = _evidence(archive_url="https://web.archive.org/web/20250101000000/https://example.com/a")
    assert item.archive_url.startswith("https://web.archive.org/")


def test_evidence_item_available_at_not_before_published_at():
    later = datetime(2025, 1, 16, tzinfo=UTC)
    assert _evidence(published_at=AS_OF, available_at=later).available_at == later
    with pytest.raises(ValidationError):
        _evidence(published_at=later, available_at=AS_OF)


def test_market_quote_ref_bounds_and_label():
    q = MarketQuoteRef(
        quote_id="quote_001",
        venue="kalshi",
        market_id="EXAMPLE-TICKER",
        ts=AS_OF,
        p_yes=0.42,
        quote_kind="midpoint",
        raw_payload_sha256=H,
        provenance=Provenance.REAL_HISTORICAL,
    )
    assert "market-implied" in q.label and "price-derived" in q.label
    with pytest.raises(ValidationError):
        MarketQuoteRef(**{**q.model_dump(), "p_yes": 1.01})
    with pytest.raises(ValidationError):
        MarketQuoteRef(**{**q.model_dump(), "venue": "robinhood"})


def _prediction(**overrides) -> Prediction:
    data = dict(
        prediction_id="pred_001",
        event_id="demo_macro_001",
        as_of=AS_OF,
        agent_model="ollama/llama3.1:8b",
        variant="agent_only",
        p_yes=0.61,
        decision="wait",
        rationale="Schema example only.",
        evidence_ids=["evid_a"],
        prompt_sha256=H,
        snapshot_sha256=H,
        recorded_at=datetime(2026, 11, 12, 22, 0, tzinfo=UTC),
        temperature=0.0,
        seed=7,
        provenance=Provenance.RECORDED_RUN,
    )
    data.update(overrides)
    return Prediction(**data)


def test_prediction_valid_and_bounded():
    assert _prediction().variant == "agent_only"
    with pytest.raises(ValidationError):
        _prediction(p_yes=1.2)
    with pytest.raises(ValidationError):
        _prediction(p_yes=-0.01)
    with pytest.raises(ValidationError):
        _prediction(decision="buy")
    with pytest.raises(ValidationError):
        _prediction(variant="agent_with_answers")
    with pytest.raises(ValidationError):
        _prediction(prompt_sha256="short")


@pytest.mark.parametrize("bad", [float("inf"), float("-inf"), float("nan"), -0.1])
def test_prediction_temperature_must_be_finite_non_negative(bad):
    with pytest.raises(ValidationError):
        _prediction(temperature=bad)


@pytest.mark.parametrize("bad", [float("inf"), float("nan")])
def test_probabilities_reject_inf_and_nan(bad):
    with pytest.raises(ValidationError):
        _prediction(p_yes=bad)


def test_prediction_requires_aware_datetimes():
    with pytest.raises(ValidationError):
        _prediction(recorded_at=datetime(2026, 11, 12, 22, 0))


def test_api_error_codes():
    assert {c.value for c in ErrorCode} >= {
        "MODEL_UNAVAILABLE",
        "NO_FEASIBLE_PLAN",
        "NOT_REVEALABLE",
        "INSUFFICIENT_DATA",
    }
    assert ApiError(code=ErrorCode.NOT_REVEALABLE, message="x").model_dump(mode="json") == {
        "code": "NOT_REVEALABLE",
        "message": "x",
    }
