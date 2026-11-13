"""Temporal gate: the ONLY path from replay data to a model prompt (SPEC §3.1, §5; MATH_MODEL §7).

``EvidenceStore.get_as_of(case_id, as_of)`` returns a ``GatedSnapshot`` holding:

* evidence items with ``available_at <= as_of`` (and ``published_at <= as_of``), for the same event, and
  ``retrospective_unverified == False``;
* per market (venue, market_id) the quote chosen by ``markets.normalize.select_quote``: the last quote with
  ``as_of - 24h <= ts <= as_of``; none in that window means the market baseline is NOT AVAILABLE;
* prompt-safe projections only: post-cutoff curation metadata (``observed_at``, ``collected_at``, archive
  capture URLs, API endpoints, raw payload hashes) is dropped, and every key matching
  ``models.OUTCOME_FIELD_PATTERN`` is stripped. The single allowlisted key is the market side marker
  ``outcome == "YES"`` at the top level of a ``NormalizedQuote`` projection;
* the exclusions, by reason, for the audit report (ids and reasons only, never excluded content).

A ``GatedSnapshot`` can only be built here, ``render_prompt`` accepts nothing else, and this module never
imports the evaluator. It refuses to load anything located in the sealed-outcome directory. The
``SealedDataError`` checks make a case file that carries an outcome fail loudly instead of silently
leaking it. Tests: tests/test_temporal_gate.py, tests/test_replay_seal.py (future-fact canary).
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from config import get_settings
from core import provenance
from markets.base import MARKET_LABEL, NormalizedQuote
from markets.normalize import DEFAULT_MAX_STALENESS, select_quote
from models import OUTCOME_FIELD_PATTERN, EvidenceItem, ReplayCase, ReplayCasePublic

PROMPT_TEMPLATE_VERSION = "replay-v1"
PROMPT_VARIANTS = ("agent_only", "agent_plus_market")
PromptVariant = Literal["agent_only", "agent_plus_market"]

# The gate refuses any path inside this directory (outcomes are read only by core/evaluator.py).
_FORBIDDEN_DIR = "sealed_outcomes"
# The one key matching OUTCOME_FIELD_PATTERN that may reach a prompt: the YES-side marker of a quote.
_MARKET_SIDE_KEY, _MARKET_SIDE_VALUE = "outcome", "YES"
# Case-definition keys that match the pattern but hold the rule text, not the result.
_CASE_RULE_KEY = "resolution_rule"

EVIDENCE_PROMPT_FIELDS = ("evidence_id", "title", "published_at", "available_at", "source_url", "content", "provenance")

ExclusionReason = Literal[
    "wrong_event",
    "retrospective_unverified",
    "available_after_as_of",
    "published_after_as_of",
    "no_quote_within_24h_before_as_of",
]


class SealedDataError(ValueError):
    """Outcome data found where the agent path could read it (or a read of the sealed directory attempted)."""


class UnknownCase(KeyError):
    pass


class MarketNotAvailable(LookupError):
    """No quote within 24h before as_of: the agent_plus_market variant cannot run (baseline NOT AVAILABLE)."""


class Exclusion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["evidence", "market"]
    item_id: str
    reason: ExclusionReason


@dataclass(frozen=True)
class CaseRecord:
    """Internal: one case definition with all of its candidate evidence and market quotes (pre-gate)."""

    case: ReplayCase
    evidence: tuple[EvidenceItem, ...] = ()
    market_quotes: tuple[NormalizedQuote, ...] = ()


@dataclass(frozen=True)
class ModelInput:
    """Exactly what one model call receives, plus its audit hashes."""

    event_id: str
    as_of: str
    variant: PromptVariant
    template_version: str
    prompt: str
    snapshot_json: str
    prompt_sha256: str
    snapshot_sha256: str
    evidence_ids: tuple[str, ...]


_GATE_TOKEN = object()


@dataclass(frozen=True)
class GatedSnapshot:
    """Point-in-time view of one case. Built only by ``EvidenceStore.get_as_of``."""

    case: ReplayCasePublic
    as_of: datetime
    evidence: tuple[Mapping[str, Any], ...]
    market_quotes: tuple[Mapping[str, Any], ...]
    exclusions: tuple[Exclusion, ...]
    _token: object = field(repr=False, compare=False, kw_only=True)

    def __post_init__(self) -> None:
        if self._token is not _GATE_TOKEN:
            raise TypeError("GatedSnapshot is created only by EvidenceStore.get_as_of")

    @property
    def market_available(self) -> bool:
        return bool(self.market_quotes)

    @property
    def evidence_ids(self) -> tuple[str, ...]:
        return tuple(e["evidence_id"] for e in self.evidence)

    def payload(self, variant: PromptVariant) -> dict[str, list[dict[str, Any]]]:
        """The exact evidence + quote list given to the model for ``variant`` (hashed as snapshot_sha256)."""
        if variant == "agent_only":
            quotes: list[dict[str, Any]] = []
        elif variant == "agent_plus_market":
            if not self.market_quotes:
                raise MarketNotAvailable(
                    f"{self.case.event_id}: no market quote within 24h before {_iso(self.as_of)}; "
                    "market baseline NOT AVAILABLE"
                )
            quotes = [dict(q) for q in self.market_quotes]
        else:
            raise ValueError(f"variant {variant!r} is not supported by the replay prompt (use {PROMPT_VARIANTS})")
        return {"evidence": [dict(e) for e in self.evidence], "market_quotes": quotes}

    def model_input(self, variant: PromptVariant) -> ModelInput:
        payload = self.payload(variant)
        snapshot_json = provenance.snapshot_payload_json(payload)
        prompt = _render(self, variant, payload)
        return ModelInput(
            event_id=self.case.event_id,
            as_of=_iso(self.as_of),
            variant=variant,
            template_version=PROMPT_TEMPLATE_VERSION,
            prompt=prompt,
            snapshot_json=snapshot_json,
            prompt_sha256=provenance.prompt_sha256(prompt),
            snapshot_sha256=provenance.sha256_hex(snapshot_json),
            evidence_ids=self.evidence_ids,
        )


def render_prompt(snapshot: GatedSnapshot, variant: PromptVariant) -> str:
    """The final prompt string for one variant. Accepts only a ``GatedSnapshot``."""
    if not isinstance(snapshot, GatedSnapshot):
        raise TypeError("render_prompt accepts only a GatedSnapshot from EvidenceStore.get_as_of")
    return snapshot.model_input(variant).prompt


# ---------------------------------------------------------------- key stripping and projections


def strip_outcome_keys(obj: Any, *, allow_market_side: bool = False) -> Any:
    """Recursively drop every dict key matching OUTCOME_FIELD_PATTERN.

    With ``allow_market_side=True`` (market-quote projections only), the top-level key ``outcome`` is kept
    when, and only when, its value is exactly ``"YES"`` (the NormalizedQuote side marker).
    """
    return _strip(obj, allow_market_side, top=True)


def _strip(obj: Any, allow: bool, top: bool) -> Any:
    if isinstance(obj, Mapping):
        out: dict[str, Any] = {}
        for k, v in obj.items():
            if OUTCOME_FIELD_PATTERN.search(str(k)):
                if allow and top and k == _MARKET_SIDE_KEY and v == _MARKET_SIDE_VALUE:
                    out[k] = v
                continue
            out[k] = _strip(v, allow, top=False)
        return out
    if isinstance(obj, (list, tuple)):
        return [_strip(v, allow, top) for v in obj]
    return obj


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _project_evidence(item: EvidenceItem) -> Mapping[str, Any]:
    full = {
        "evidence_id": item.evidence_id,
        "title": item.title,
        "published_at": _iso(item.published_at),
        "available_at": _iso(item.available_at),
        "source_url": item.source_url,
        "content": item.content,
        "provenance": item.provenance.value,
    }
    return MappingProxyType(strip_outcome_keys(full))


def _project_quote(q: NormalizedQuote) -> Mapping[str, Any]:
    full = {
        "venue": q.venue,
        "market_id": q.market_id,
        "outcome": q.outcome,
        "p_yes": q.p_yes,
        "quote_kind": q.quote_kind,
        "ts": _iso(q.ts),
        "spread": q.spread,
        "volume": q.volume,
        "open_interest": q.open_interest,
        "period_seconds": q.period_seconds,
        "label": q.label,
    }
    return MappingProxyType(strip_outcome_keys(full, allow_market_side=True))


# ---------------------------------------------------------------- prompt template


_INSTRUCTIONS = (
    "You are forecasting a yes/no question as it stood at the cutoff. Use only the evidence below: every item "
    "was publicly available at or before the cutoff. Do not use knowledge of anything that happened after the "
    "cutoff. If the evidence is insufficient, say so in the rationale."
)
_MARKET_HEADER = (
    "Market input (JSON). Each p_yes is a " + MARKET_LABEL + ", observed at `ts`, at or before the cutoff:"
)
_ANSWER_FORMAT = (
    "Answer with exactly one JSON object and nothing else:\n"
    '{"p_yes": <number from 0 to 1>, "decision": "act" | "wait" | "hedge", '
    '"rationale": "<2-4 sentences citing evidence ids>", "evidence_ids": [<ids of the evidence items used>]}\n'
    "decision: act = take the pre-declared protective action now; wait = take no action yet; "
    "hedge = take the partial, lower-cost protective action."
)


def _pretty(obj: Any) -> str:
    return json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)


def _render(snap: GatedSnapshot, variant: PromptVariant, payload: dict[str, list[dict[str, Any]]]) -> str:
    case = snap.case
    parts = [
        "FAULTLINE blind replay forecast",
        f"template: {PROMPT_TEMPLATE_VERSION}",
        f"variant: {variant}",
        f"cutoff (as_of): {_iso(snap.as_of)}",
        "",
        _INSTRUCTIONS,
        "",
        f"Question: {case.title}",
        f"Criteria for YES (quoted rule): {case.question_criteria}",
        f"Horizon: {case.horizon_days} days after the cutoff.",
        "",
        f"Evidence (JSON, {len(payload['evidence'])} items, ordered by available_at):",
        _pretty(payload["evidence"]),
    ]
    if variant == "agent_plus_market":
        parts += ["", _MARKET_HEADER, _pretty(payload["market_quotes"])]
    parts += ["", _ANSWER_FORMAT]
    return "\n".join(parts) + "\n"


# ---------------------------------------------------------------- the store


def _as_of_instant(as_of: datetime | str) -> datetime:
    if isinstance(as_of, str):
        if len(as_of.strip()) <= 10:
            raise ValueError("as_of must be an instant with a timezone, not a calendar date")
        as_of = datetime.fromisoformat(as_of.strip().replace("Z", "+00:00"))
    if not isinstance(as_of, datetime):
        raise TypeError(f"as_of must be a timezone-aware datetime, got {type(as_of).__name__}")
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    return as_of.astimezone(UTC)


def _refuse_sealed(path: Path) -> None:
    candidates = (Path(path).absolute(), Path(path).resolve())
    if any(_FORBIDDEN_DIR in p.parts for p in candidates):
        raise SealedDataError(f"refusing to read {path}: the sealed-outcome directory is read only by the evaluator")


class EvidenceStore:
    """All candidate evidence and quotes per case. ``get_as_of`` is the only way out."""

    def __init__(self, records: Iterable[CaseRecord]) -> None:
        self._records: dict[str, CaseRecord] = {}
        for rec in records:
            if not isinstance(rec, CaseRecord):
                raise TypeError("EvidenceStore takes CaseRecord values")
            if rec.case.event_id in self._records:
                raise ValueError(f"duplicate case id {rec.case.event_id!r}")
            self._records[rec.case.event_id] = rec

    @classmethod
    def from_dir(cls, cases_dir: Path | str | None = None) -> EvidenceStore:
        """Load ``<cases_dir>/<event_id>.json`` files (default ``<FAULTLINE_DATA_DIR>/demo_cases``).

        File shape: ``{"case": ReplayCase, "evidence": [EvidenceItem], "market_quotes": [NormalizedQuote]}``.
        Other top-level keys (curation notes) are ignored and never reach a prompt. A missing directory gives
        an empty store (the benchmark then reports INSUFFICIENT DATA).
        """
        root = Path(cases_dir) if cases_dir is not None else get_settings().data_dir / "demo_cases"
        _refuse_sealed(root)
        if not root.is_dir():
            return cls([])
        records = []
        for path in sorted(root.glob("*.json")):
            _refuse_sealed(path)
            records.append(_load_case_file(path))
        return cls(records)

    def case_ids(self) -> list[str]:
        return sorted(self._records)

    def public_case(self, case_id: str) -> ReplayCasePublic:
        return ReplayCasePublic.from_case(self._get(case_id).case)

    def _get(self, case_id: str) -> CaseRecord:
        try:
            return self._records[case_id]
        except KeyError:
            raise UnknownCase(case_id) from None

    def get_as_of(self, case_id: str, as_of: datetime | str) -> GatedSnapshot:
        rec = self._get(case_id)
        cutoff = _as_of_instant(as_of)
        if cutoff > rec.case.as_of:
            raise ValueError(
                f"as_of {_iso(cutoff)} is after the case cutoff {_iso(rec.case.as_of)}; a replay may only look earlier"
            )

        exclusions: list[Exclusion] = []
        kept: list[EvidenceItem] = []
        for item in sorted(rec.evidence, key=lambda e: (e.available_at, e.evidence_id)):
            reason: ExclusionReason | None = None
            if item.event_id != rec.case.event_id:
                reason = "wrong_event"
            elif item.retrospective_unverified:
                reason = "retrospective_unverified"
            elif item.available_at > cutoff:
                reason = "available_after_as_of"
            elif item.published_at > cutoff:
                reason = "published_after_as_of"
            if reason is None:
                kept.append(item)
            else:
                exclusions.append(Exclusion(kind="evidence", item_id=item.evidence_id, reason=reason))

        groups: dict[tuple[str, str], list[NormalizedQuote]] = {}
        for q in rec.market_quotes:
            groups.setdefault((q.venue, q.market_id), []).append(q)
        selected: list[Mapping[str, Any]] = []
        for (venue, market_id), quotes in sorted(groups.items()):
            chosen = select_quote(quotes, cutoff, DEFAULT_MAX_STALENESS)
            if chosen is None:
                exclusions.append(
                    Exclusion(kind="market", item_id=f"{venue}:{market_id}", reason="no_quote_within_24h_before_as_of")
                )
            else:
                selected.append(_project_quote(chosen))

        return GatedSnapshot(
            case=ReplayCasePublic.from_case(rec.case),
            as_of=cutoff,
            evidence=tuple(_project_evidence(e) for e in kept),
            market_quotes=tuple(selected),
            exclusions=tuple(exclusions),
            _token=_GATE_TOKEN,
        )


def _load_case_file(path: Path) -> CaseRecord:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not isinstance(raw.get("case"), dict):
        raise ValueError(f"{path.name}: expected an object with a 'case' object")
    leaked = sorted(k for k in raw if OUTCOME_FIELD_PATTERN.search(k))
    if leaked:
        raise SealedDataError(f"{path.name}: outcome-like top-level keys {leaked}; outcomes belong in sealed storage")
    leaked = sorted(k for k in raw["case"] if OUTCOME_FIELD_PATTERN.search(k) and k != _CASE_RULE_KEY)
    if leaked:
        raise SealedDataError(f"{path.name}: outcome-like case keys {leaked}; outcomes belong in sealed storage")
    case = ReplayCase.model_validate(raw["case"])
    if case.event_id != path.stem:
        raise ValueError(f"{path.name}: file name must be <event_id>.json (event_id is {case.event_id!r})")

    evidence = tuple(EvidenceItem.model_validate(strip_outcome_keys(e)) for e in raw.get("evidence") or [])
    quotes = []
    for q in raw.get("market_quotes") or []:
        if not isinstance(q, dict):
            raise ValueError(f"{path.name}: market_quotes entries must be objects")
        if q.get(_MARKET_SIDE_KEY, _MARKET_SIDE_VALUE) != _MARKET_SIDE_VALUE:
            # Never echo the value: it may be the result.
            raise SealedDataError(f"{path.name}: a market quote's 'outcome' must be the side marker 'YES'")
        quotes.append(NormalizedQuote.model_validate(strip_outcome_keys(q, allow_market_side=True)))
    return CaseRecord(case=case, evidence=evidence, market_quotes=tuple(quotes))
