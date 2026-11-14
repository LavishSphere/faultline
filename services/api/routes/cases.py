"""GET /api/cases and GET /api/cases/{case_id}/evidence: Blind Replay cases before any reveal (SPEC §5, §8).

Both routes go through ``core.temporal_gate.EvidenceStore`` (#44): the case list is
``EvidenceStore.public_case`` (``evidence_ids`` = only the items the gate admits at the case cutoff) and the
evidence route is ``EvidenceStore.get_as_of`` (the exact projection the prompt uses). Nothing else reads case data.

Isolation is structural, in two layers:
1. A strict pre-scan here, file by file, before the gate loads anything:
   - only ``<FAULTLINE_DATA_DIR>/demo_cases/*.json`` (dotfiles skipped) is read; ``sealed_outcomes/`` is never
     opened, a ``demo_cases/`` overlapping it is refused, and a file resolving (e.g. via a symlink) outside
     ``demo_cases/`` is refused unread;
   - a file with an outcome-like key (``models.OUTCOME_FIELD_PATTERN``) ANYWHERE in it is refused, unserved.
     Exceptions: ``case.resolution_rule`` (the rule text, as a string) and the market side marker
     ``"outcome": "YES"`` directly on a ``market_quotes[i]`` object (``markets.base.NormalizedQuote``);
   - top-level keys are allow-listed; ``case`` / ``evidence[i]`` / ``market_quotes[i]`` must pass
     ``ReplayCase`` / ``EvidenceItem`` / ``NormalizedQuote``; the file name must be ``<event_id>.json``.
2. ``EvidenceStore.from_dir`` then adds its own refusals (sealed directory by name, case-insensitively, and by
   inode; hard-linked files) and is the only source of what is served.

Response models have no outcome-like field at all. Error responses carry only file names, field locations and
error types, never file contents.

Case file shape (docs/EVALUATION_PROTOCOL.md §7):
``{"case": ReplayCase, "evidence": [EvidenceItem], "market_quotes": [NormalizedQuote], "curation_notes": ...}``.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError

from config import Settings, get_settings
from core.temporal_gate import EvidenceStore, GatedSnapshot, SealedDataError, UnknownCase

# Quote types come from the normalizer (markets.base), which the gate projects from; its QuoteKind also has
# "price_history_point" (Polymarket CLOB history), unlike models.QuoteKind.
from markets.base import MARKET_LABEL, MarketLabel, NormalizedQuote, QuoteKind, Venue
from models import (
    OUTCOME_FIELD_PATTERN,
    ErrorCode,
    EvidenceItem,
    Probability,
    Provenance,
    ReplayCase,
    ReplayCasePublic,
)
from routes import NOT_AVAILABLE, CodedRoute, RouteError, RouteErrorBody, issues_from, read_json

router = APIRouter(tags=["cases"], route_class=CodedRoute)

CASES_DIR = "demo_cases"
SEALED_DIR = "sealed_outcomes"  # never opened here; only used to refuse an overlapping cases directory
ALLOWED_TOP_LEVEL = frozenset({"case", "evidence", "market_quotes", "curation_notes"})
_MARKET_SIDE_KEY, _MARKET_SIDE_VALUE = "outcome", "YES"
# ReplayCase.resolution_rule is the settlement RULE text (served as question_criteria), never the result.
_RULE_PATH = "case.resolution_rule"
# An as_of must be an instant: a calendar date plus at least hours and minutes (same rule as the gate).
_ISO_INSTANT = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}")


def coded_responses(**by_status: str) -> dict[int | str, dict[str, Any]]:
    """OpenAPI ``responses=`` entries with the RouteErrorBody shape, e.g. ``coded_responses(_404="NOT_FOUND")``."""
    return {int(k.lstrip("_")): {"model": RouteErrorBody, "description": v} for k, v in by_status.items()}


def _allowed(path: str, key: str, value: object, in_quote: bool) -> bool:
    if path == _RULE_PATH:
        return isinstance(value, str)
    return in_quote and key == _MARKET_SIDE_KEY and value == _MARKET_SIDE_VALUE


def outcome_key_paths(payload: object) -> list[str]:
    """JSON paths of every outcome-like key in a case file, except the two allow-listed keys:
    ``case.resolution_rule`` (rule text) and ``market_quotes[i].outcome == "YES"`` (quote side marker)."""
    found: list[str] = []

    def walk(node: object, path: str, in_quote: bool) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                key = str(k)
                here = f"{path}.{key}" if path else key
                if OUTCOME_FIELD_PATTERN.search(key) and not _allowed(here, key, v, in_quote):
                    found.append(here)
                walk(v, here, False)
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{path}[{i}]", in_quote=(path == "market_quotes"))

    walk(payload, "", False)
    return found


def _invalid(message: str, errors=None) -> RouteError:
    return RouteError(ErrorCode.DATA_INVALID, message, status_code=500, errors=errors)


def _validate(model: type[BaseModel], raw: object, name: str, loc: tuple[str | int, ...], what: str) -> BaseModel:
    try:
        return model.model_validate(raw)
    except ValidationError as exc:
        raise _invalid(f"{name} failed the {what} schema.", issues_from(exc.errors(), prefix=(name, *loc))) from None


def _prescan(path: Path, root: Path) -> str:
    """Strict checks on one case file before the gate reads it. Returns its event_id."""
    name = f"{CASES_DIR}/{path.name}"
    resolved = path.resolve()
    if not resolved.is_relative_to(root) or not resolved.is_file():
        raise _invalid(f"{name} is not a regular file inside {CASES_DIR}/; refusing to read it.")
    payload = read_json(resolved, name)
    if not isinstance(payload, dict) or not isinstance(payload.get("case"), dict):
        raise _invalid(f"{name} must be an object with a `case` (ReplayCase) object.")
    leaked = outcome_key_paths(payload)
    if leaked:
        # Paths (key names) only, never values: the values are exactly what must not leak.
        raise _invalid(f"{name} contains outcome-like keys and is refused: {', '.join(leaked)}.")
    unknown = sorted(set(payload) - ALLOWED_TOP_LEVEL)
    if unknown:
        raise _invalid(f"{name} has unexpected top-level keys {unknown}; allowed: {sorted(ALLOWED_TOP_LEVEL)}.")
    case = _validate(ReplayCase, payload["case"], name, ("case",), "ReplayCase")
    for key, model, what in (("evidence", EvidenceItem, "EvidenceItem"), ("market_quotes", NormalizedQuote, "quote")):
        items = payload.get(key) or []
        if not isinstance(items, list):
            raise _invalid(f"{name} `{key}` must be a list.")
        for i, item in enumerate(items):
            _validate(model, item, name, (key, i), what)
    if case.event_id != path.stem:
        raise _invalid(f"{name}: the file name must be <event_id>.json (event_id is {case.event_id!r}).")
    return case.event_id


def load_evidence_store(settings: Settings) -> EvidenceStore | None:
    """The temporal gate's store over ``demo_cases/``, after the strict pre-scan. None when the directory is absent."""
    directory = settings.data_dir / CASES_DIR
    if not directory.is_dir():
        return None
    root = directory.resolve()
    sealed = (settings.data_dir / SEALED_DIR).resolve()
    if root.is_relative_to(sealed) or sealed.is_relative_to(root):
        raise _invalid(f"{CASES_DIR}/ overlaps {SEALED_DIR}/; refusing to read it.")
    files = sorted((p for p in directory.glob("*.json") if not p.name.startswith(".")), key=lambda p: p.name)
    ids = [_prescan(p, root) for p in files]
    if len(ids) != len(set(ids)):
        raise _invalid(f"{CASES_DIR}/ has duplicate event_id values.")
    try:
        store = EvidenceStore.from_dir(directory)
    except SealedDataError:
        # The gate's message names absolute paths; say what happened without them.
        raise _invalid(
            f"The temporal gate is refusing to read {CASES_DIR}/: a file is a hard link, lies in the sealed-outcome "
            "directory, or carries sealed-outcome data."
        ) from None
    except (ValueError, OSError) as exc:
        # The gate's own ValueError messages name the file and market ids only (e.g. a market_quote_id naming no
        # market in the file). Subclasses (pydantic, JSON) can echo values, so they get the type name only.
        detail = str(exc) if type(exc) is ValueError else type(exc).__name__
        raise _invalid(f"The temporal gate could not load {CASES_DIR}/: {detail}") from None
    if store.case_ids() != sorted(ids):
        raise _invalid(f"The temporal gate loaded different cases from {CASES_DIR}/ than were checked.")
    return store


def require_case_store(settings: Settings, case_id: str) -> EvidenceStore:
    """The store, or 404 NOT_FOUND when there are no cases or ``case_id`` is not one of them."""
    store = load_evidence_store(settings)
    if store is None or case_id not in store.case_ids():
        reason = f"{CASES_DIR}/ has not been added yet" if store is None else f"no case {case_id!r}"
        raise RouteError(ErrorCode.NOT_FOUND, f"Replay case {NOT_AVAILABLE}: {reason}.", status_code=404)
    return store


# ---------------------------------------------------------------- market-implied probability at the cutoff


class MarketAtCutoff(BaseModel):
    """The market-only benchmark at the cutoff, from the gate (``GatedSnapshot.market_baseline``'s fixed rule).

    ``status == "NOT AVAILABLE"`` (and every quote field null) when no quote lies within 24h before the cutoff or
    the rule picks no single market. ``p_yes`` is price-derived, never a "true probability"; for venue
    ``"synthetic"`` (SYNTHETIC cases only) it is an invented price and ``label`` says so (SYNTHETIC_QUOTE_LABEL).
    """

    model_config = ConfigDict(extra="forbid", json_schema_serialization_defaults_required=True)

    status: Literal["AVAILABLE", "NOT AVAILABLE"]
    label: MarketLabel = MARKET_LABEL
    ref: str | None = Field(description='"<venue>:<market_id>" of the quote, null when NOT AVAILABLE.')
    venue: Venue | None
    market_id: str | None
    quote_kind: QuoteKind | None
    ts: AwareDatetime | None = Field(description="Quote timestamp; as_of - 24h <= ts <= as_of.")
    p_yes: Probability | None
    provenance: Provenance | None = Field(
        description="Provenance of the case file the quote comes from (REAL_HISTORICAL or SYNTHETIC)."
    )
    note: str | None


def market_at_cutoff(snap: GatedSnapshot, ref: str | None, p_yes: float | None) -> MarketAtCutoff:
    """``ref`` / ``p_yes`` are the gate's baseline (``ModelInput.market_baseline_*`` or ``snap.market_baseline()``)."""
    quote = next((q for q in snap.market_quotes if f"{q['venue']}:{q['market_id']}" == ref), None)
    if ref is None or p_yes is None or quote is None:
        if snap.market_quotes:
            note = (
                f"Market baseline {NOT_AVAILABLE}: no single market is selected by the fixed rule "
                "(the case names none, or names one without a quote within 24h before the cutoff)."
            )
        else:
            note = f"Market baseline {NOT_AVAILABLE}: no market quote within 24h before the cutoff."
        return MarketAtCutoff(
            status=NOT_AVAILABLE,
            ref=None,
            venue=None,
            market_id=None,
            quote_kind=None,
            ts=None,
            p_yes=None,
            provenance=None,
            note=note,
        )
    return MarketAtCutoff(
        status="AVAILABLE",
        # The selected quote's own label: SYNTHETIC_QUOTE_LABEL for venue "synthetic", else MARKET_LABEL.
        label=quote["label"],
        ref=ref,
        venue=quote["venue"],
        market_id=quote["market_id"],
        quote_kind=quote["quote_kind"],
        ts=quote["ts"],
        p_yes=p_yes,
        # The gate's projected quote provenance: SYNTHETIC for any quote on a SYNTHETIC case (#102).
        provenance=quote["provenance"],
        note=None,
    )


# ---------------------------------------------------------------- GET /api/cases


class CasesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_serialization_defaults_required=True)

    status: Literal["AVAILABLE", "NOT AVAILABLE"]
    items: list[ReplayCasePublic]
    notes: list[str]


def load_public_cases(settings: Settings) -> list[ReplayCasePublic] | None:
    """None when the cases directory does not exist yet. Sorted by event_id (= file name)."""
    store = load_evidence_store(settings)
    if store is None:
        return None
    return [store.public_case(cid) for cid in store.case_ids()]


@router.get(
    "/cases",
    response_model=CasesResponse,
    responses=coded_responses(_500="DATA_INVALID: a case file failed a check"),
    summary="Blind Replay demo cases (public view, no outcomes)",
)
def list_cases(settings: Annotated[Settings, Depends(get_settings)]) -> CasesResponse:
    cases = load_public_cases(settings)
    if not cases:
        reason = "has not been added yet (issue #20)" if cases is None else "contains no case files yet"
        note = f"Replay cases {NOT_AVAILABLE}: {CASES_DIR}/ {reason}."
        return CasesResponse(status=NOT_AVAILABLE, items=[], notes=[note])
    return CasesResponse(status="AVAILABLE", items=cases, notes=[])


# ---------------------------------------------------------------- GET /api/cases/{case_id}/evidence


class GatedEvidence(BaseModel):
    """One admitted evidence item exactly as the prompt shows it (``temporal_gate._project_evidence``).

    Post-cutoff curation metadata (``observed_at``, archive capture URL, content hash) is not part of it.
    """

    model_config = ConfigDict(extra="forbid")

    evidence_id: str
    title: str
    published_at: AwareDatetime
    available_at: AwareDatetime
    source_url: str
    content: str
    provenance: Provenance


class GatedQuote(BaseModel):
    """One selected as-of market quote (``temporal_gate._project_quote``, without the YES-side marker)."""

    model_config = ConfigDict(extra="forbid")

    venue: Venue
    market_id: str
    p_yes: Probability
    quote_kind: QuoteKind
    ts: AwareDatetime
    spread: float | None
    volume: str | None
    open_interest: str | None
    period_seconds: int | None
    label: MarketLabel
    provenance: Provenance = Field(
        description="SYNTHETIC for every quote on a SYNTHETIC case (and for venue synthetic), else REAL_HISTORICAL."
    )


class CaseEvidenceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_serialization_defaults_required=True)

    status: Literal["AVAILABLE", "NOT AVAILABLE"] = Field(description="NOT AVAILABLE when no evidence is admitted.")
    event_id: str
    as_of: AwareDatetime = Field(description="The cutoff applied (the case cutoff unless an earlier one was asked).")
    case_as_of: AwareDatetime = Field(description="The case's own cutoff.")
    items: list[GatedEvidence] = Field(description="Admitted evidence, ordered by available_at.")
    market_quotes: list[GatedQuote] = Field(description="Per market, the last quote within 24h before as_of.")
    market_at_cutoff: MarketAtCutoff
    excluded_by_reason: dict[str, int] = Field(
        description="How many items the gate excluded, by reason. Ids and content of excluded items are not served."
    )
    notes: list[str]


def parse_as_of(raw: str) -> datetime:
    """A timezone-aware ISO-8601 instant, or 422. Messages never echo the input."""
    text = raw.strip()
    hint = (
        "as_of must be a timezone-aware ISO-8601 instant, YYYY-MM-DDTHH:MM:SSZ or with an offset "
        "(percent-encode '+' as %2B)."
    )
    if not _ISO_INSTANT.match(text):
        raise RouteError(ErrorCode.VALIDATION_ERROR, hint)
    try:
        value = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        raise RouteError(ErrorCode.VALIDATION_ERROR, hint) from None
    if value.tzinfo is None or value.utcoffset() is None:
        raise RouteError(ErrorCode.VALIDATION_ERROR, hint)
    try:
        return value.astimezone(UTC)
    except OverflowError:  # e.g. 0001-01-01T00:00:00+23:59 has no UTC representation
        raise RouteError(ErrorCode.VALIDATION_ERROR, "as_of is out of range once converted to UTC.") from None


def _quote_view(q: Mapping[str, Any]) -> GatedQuote:
    return GatedQuote.model_validate({k: v for k, v in q.items() if k != _MARKET_SIDE_KEY})


@router.get(
    "/cases/{case_id}/evidence",
    response_model=CaseEvidenceResponse,
    responses=coded_responses(
        _404="NOT_FOUND: unknown case",
        _422="VALIDATION_ERROR: as_of malformed or after the case cutoff",
        _500="DATA_INVALID: a case file failed a check",
    ),
    summary="Evidence admitted by the temporal gate at as_of (what the model may see), plus the as-of market quote",
)
def case_evidence(
    case_id: str,
    settings: Annotated[Settings, Depends(get_settings)],
    as_of: Annotated[
        str | None, Query(description="Timezone-aware ISO-8601 instant; default and maximum: the case cutoff.")
    ] = None,
) -> CaseEvidenceResponse:
    store = require_case_store(settings, case_id)
    case_as_of = store.public_case(case_id).as_of.astimezone(UTC)
    cutoff = case_as_of if as_of is None else parse_as_of(as_of)
    if cutoff > case_as_of:
        raise RouteError(
            ErrorCode.VALIDATION_ERROR,
            f"as_of is after the case cutoff {case_as_of.isoformat()}; a replay may only look earlier.",
        )
    try:
        snap = store.get_as_of(case_id, cutoff)
    except UnknownCase:
        raise RouteError(ErrorCode.NOT_FOUND, f"Replay case {NOT_AVAILABLE}: no case {case_id!r}.", 404) from None
    ref_p, ref = snap.market_baseline()
    excluded: dict[str, int] = {}
    for x in snap.exclusions:
        excluded[x.reason] = excluded.get(x.reason, 0) + 1
    notes = [] if snap.evidence else [f"Evidence {NOT_AVAILABLE}: no item was public at or before this as_of."]
    return CaseEvidenceResponse(
        status="AVAILABLE" if snap.evidence else NOT_AVAILABLE,
        event_id=case_id,
        as_of=snap.as_of,
        case_as_of=case_as_of,
        items=[GatedEvidence.model_validate(dict(e)) for e in snap.evidence],
        market_quotes=[_quote_view(q) for q in snap.market_quotes],
        market_at_cutoff=market_at_cutoff(snap, ref, ref_p),
        excluded_by_reason=excluded,
        notes=notes,
    )
