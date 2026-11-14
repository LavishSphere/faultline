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
import os
import re
import threading
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
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

# The gate refuses any path inside this directory (outcomes are read only by core/evaluator.py). Compared
# case-insensitively (macOS/Windows file systems) and by inode against the configured directory.
_FORBIDDEN_DIR = "sealed_outcomes"
# An as_of string must be an instant: a calendar date plus at least hours and minutes.
_ISO_INSTANT = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}")
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


class SyntheticQuoteOnRealCase(ValueError):
    """A ``venue == "synthetic"`` quote on a case that is not ``synthetic: true`` (issue #102). Never loaded."""


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


_BUILDING = threading.local()


def _build(cls, **kwargs):
    """The only way to construct a GatedSnapshot or ModelInput (``dataclasses.replace`` and direct calls raise)."""
    _BUILDING.active = True
    try:
        return cls(**kwargs)
    finally:
        _BUILDING.active = False


def _require_building(cls_name: str, origin: str) -> None:
    if not getattr(_BUILDING, "active", False):
        raise TypeError(f"{cls_name} is created only by {origin}")


@dataclass(frozen=True)
class ModelInput:
    """Exactly what one model call receives, plus its audit hashes. Created only by GatedSnapshot.model_input.

    The last four fields are the pre-reveal SCORING CONTEXT, fixed by the gate when the forecast is made and
    persisted with it (inside ``record_sha256``). They are never put in the prompt or the snapshot:
    ``market_baseline_*`` is the market-only benchmark for this (event_id, as_of), chosen by the fixed rule in
    ``GatedSnapshot.market_baseline``; ``contamination_flag`` and ``synthetic`` come from the case definition.
    """

    event_id: str
    as_of: str
    variant: PromptVariant
    template_version: str
    prompt: str
    snapshot_json: str
    prompt_sha256: str
    snapshot_sha256: str
    evidence_ids: tuple[str, ...]
    market_baseline_p_yes: float | None
    market_baseline_ref: str | None
    contamination_flag: str
    synthetic: bool
    case_sha256: str  # content hash of the case record the gate served (frozen case data)

    def __post_init__(self) -> None:
        _require_building("ModelInput", "GatedSnapshot.model_input")


@dataclass(frozen=True)
class GatedSnapshot:
    """Point-in-time view of one case. Built only by ``EvidenceStore.get_as_of``."""

    case: ReplayCasePublic
    as_of: datetime
    evidence: tuple[Mapping[str, Any], ...]
    market_quotes: tuple[Mapping[str, Any], ...]
    exclusions: tuple[Exclusion, ...]
    case_sha256: str

    def __post_init__(self) -> None:
        _require_building("GatedSnapshot", "EvidenceStore.get_as_of")

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

    def market_baseline(self) -> tuple[float | None, str | None]:
        """Market-only benchmark ``(p_yes, "venue:market_id")`` at this as_of, or ``(None, None)``.

        Fixed rule: if the case names ``market_quote_id`` as ``"<venue>:<market_id>"``, use that market's selected
        quote (absent or stale -> NOT AVAILABLE); otherwise use the only selected quote if exactly one market has
        one; otherwise NOT AVAILABLE. Never chosen by the caller and never after looking at outcomes.
        """
        by_ref = {f"{q['venue']}:{q['market_id']}": q for q in self.market_quotes}
        named = self.case.market_quote_id
        if named is not None:
            q = by_ref.get(named)
        elif len(by_ref) == 1:
            q = next(iter(by_ref.values()))
        else:
            q = None
        if q is None:
            return None, None
        return float(q["p_yes"]), f"{q['venue']}:{q['market_id']}"

    def model_input(self, variant: PromptVariant) -> ModelInput:
        payload = self.payload(variant)
        snapshot_json = provenance.snapshot_payload_json(payload)
        prompt = _render(self, variant, payload)
        baseline_p, baseline_ref = self.market_baseline()
        return _build(
            ModelInput,
            event_id=self.case.event_id,
            as_of=_iso(self.as_of),
            variant=variant,
            template_version=PROMPT_TEMPLATE_VERSION,
            prompt=prompt,
            snapshot_json=snapshot_json,
            prompt_sha256=provenance.prompt_sha256(prompt),
            snapshot_sha256=provenance.sha256_hex(snapshot_json),
            evidence_ids=self.evidence_ids,
            market_baseline_p_yes=baseline_p,
            market_baseline_ref=baseline_ref,
            contamination_flag=self.case.contamination_flag,
            synthetic=self.case.synthetic,
            case_sha256=self.case_sha256,
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
        if not _ISO_INSTANT.match(as_of.strip()):
            raise ValueError("as_of must be an ISO-8601 instant with a timezone, not a calendar date")
        as_of = datetime.fromisoformat(as_of.strip().replace("Z", "+00:00"))
    if not isinstance(as_of, datetime):
        raise TypeError(f"as_of must be a timezone-aware datetime, got {type(as_of).__name__}")
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    return as_of.astimezone(UTC)


def _configured_sealed_dir() -> Path:
    return get_settings().data_dir / _FORBIDDEN_DIR


def _same_dir(a: Path, b: Path) -> bool:
    try:
        sa, sb = os.stat(a), os.stat(b)
    except OSError:
        return False
    return (sa.st_dev, sa.st_ino) == (sb.st_dev, sb.st_ino)


def _refuse_sealed(path: Path) -> None:
    """Refuse a path inside the sealed directory: by name (case-insensitive) and by inode of every ancestor."""
    refusal = SealedDataError(f"refusing to read {path}: the sealed-outcome directory is read only by the evaluator")
    absolute, resolved = Path(path).absolute(), Path(path).resolve()
    if any(part.casefold() == _FORBIDDEN_DIR for p in (absolute, resolved) for part in p.parts):
        raise refusal
    sealed = _configured_sealed_dir()
    if sealed.exists() and any(_same_dir(a, sealed) for a in (resolved, *resolved.parents)):
        raise refusal


def _refuse_linked_file(path: Path) -> None:
    """A hard-linked case file could be the same inode as a sealed file; the gate cannot rule that out."""
    if os.stat(path).st_nlink > 1:
        raise SealedDataError(f"refusing to read {path.name}: case files must not be hard links")


class EvidenceStore:
    """All candidate evidence and quotes per case. ``get_as_of`` is the only way out."""

    def __init__(self, records: Iterable[CaseRecord]) -> None:
        self._records: dict[str, CaseRecord] = {}
        self._case_sha: dict[str, str] = {}
        # Set only by from_dir: the directory the committed case files were read from.
        self.source_dir: Path | None = None
        for rec in records:
            if not isinstance(rec, CaseRecord):
                raise TypeError("EvidenceStore takes CaseRecord values")
            if rec.case.event_id in self._records:
                raise ValueError(f"duplicate case id {rec.case.event_id!r}")
            _check_quote_provenance(rec.case.event_id, rec.case, rec.market_quotes)
            self._records[rec.case.event_id] = rec
            self._case_sha[rec.case.event_id] = case_sha256(rec)

    def case_sha256(self, case_id: str) -> str:
        """Content hash of one case record (see ``case_sha256``)."""
        self._get(case_id)
        return self._case_sha[case_id]

    @classmethod
    def from_dir(cls, cases_dir: Path | str | None = None) -> EvidenceStore:
        """Load ``<cases_dir>/<event_id>.json`` files (default ``<FAULTLINE_DATA_DIR>/demo_cases``).

        File shape: ``{"case": ReplayCase, "evidence": [EvidenceItem], "market_quotes": [NormalizedQuote]}``.
        Other top-level keys (curation notes) are ignored and never reach a prompt. Dotfiles are skipped (same
        rule as ``GET /api/cases``). A missing directory gives
        an empty store (the benchmark then reports INSUFFICIENT DATA).
        """
        root = Path(cases_dir) if cases_dir is not None else get_settings().data_dir / "demo_cases"
        _refuse_sealed(root)
        if not root.is_dir():
            return cls([])
        records = []
        for path in sorted(root.glob("*.json")):
            if path.name.startswith("."):
                continue  # dotfiles (e.g. macOS "._x.json" resource forks) are not case files
            _refuse_sealed(path)
            _refuse_linked_file(path)
            records.append(_load_case_file(path))
        store = cls(records)
        store.source_dir = root.resolve()
        return store

    def case_ids(self) -> list[str]:
        return sorted(self._records)

    def public_case(self, case_id: str) -> ReplayCasePublic:
        """Pre-reveal view at the case cutoff: ``evidence_ids`` lists only items the gate admits."""
        return self.get_as_of(case_id, self._get(case_id).case.as_of).case

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

        public = ReplayCasePublic.from_case(rec.case).model_copy(
            update={"evidence_ids": [e.evidence_id for e in kept]}
        )
        return _build(
            GatedSnapshot,
            case=public,
            as_of=cutoff,
            evidence=tuple(_project_evidence(e) for e in kept),
            market_quotes=tuple(selected),
            exclusions=tuple(exclusions),
            case_sha256=self._case_sha[rec.case.event_id],
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
        side_keys = [k for k in q if str(k).casefold() == _MARKET_SIDE_KEY]
        if any(k != _MARKET_SIDE_KEY or q[k] != _MARKET_SIDE_VALUE for k in side_keys):
            # Never echo the value: it may be the result.
            raise SealedDataError(f"{path.name}: a market quote's 'outcome' must be exactly the side marker 'YES'")
        quotes.append(NormalizedQuote.model_validate(strip_outcome_keys(q, allow_market_side=True)))
    _check_quote_provenance(path.name, case, quotes)
    _check_market_reference(path.name, case, quotes)
    return CaseRecord(case=case, evidence=evidence, market_quotes=tuple(quotes))


def _check_quote_provenance(name: str, case: ReplayCase, quotes: Iterable[NormalizedQuote]) -> None:
    """A synthetic quote (venue "synthetic", provenance SYNTHETIC) loads only on a ``synthetic: true`` case.

    Checked on every load path (case files and ``EvidenceStore(records)``), so a real case can never be
    benchmarked against a made-up price. Staleness (24h) and the ``venue:market_id`` reference rule are
    applied to synthetic quotes exactly as to real ones.
    """
    if case.synthetic and case.provenance == "SYNTHETIC":
        return
    bad = sorted({f"{q.venue}:{q.market_id}" for q in quotes if q.venue == "synthetic" or q.provenance == "SYNTHETIC"})
    if bad:
        raise SyntheticQuoteOnRealCase(
            f"{name}: synthetic market quotes {bad} on a case that is not synthetic (synthetic: true and "
            "provenance SYNTHETIC); refused"
        )


def _check_market_reference(name: str, case: ReplayCase, quotes: list[NormalizedQuote]) -> None:
    """Committed case files must make the benchmark market unambiguous (EVALUATION_PROTOCOL §7)."""
    markets = sorted({f"{q.venue}:{q.market_id}" for q in quotes})
    if case.market_quote_id is not None and case.market_quote_id not in markets:
        raise ValueError(f"{name}: market_quote_id {case.market_quote_id!r} names no market in this file {markets}")
    if case.market_quote_id is None and len(markets) > 1:
        raise ValueError(f"{name}: quotes for several markets {markets} but no market_quote_id naming the benchmark")


def case_sha256(rec: CaseRecord) -> str:
    """SHA-256 of the canonical JSON of a validated case record (case + evidence + quotes, in file order).

    Any content change, including ``market_quote_id`` or ``contamination_flag``, changes it; whitespace and key
    order in the file do not. It is frozen into every forecast's scoring context, so scoring can prove the
    forecast was made from the committed case content.
    """
    payload = {
        "case": rec.case.model_dump(mode="json"),
        "evidence": [e.model_dump(mode="json") for e in rec.evidence],
        "market_quotes": [q.model_dump(mode="json") for q in rec.market_quotes],
    }
    return provenance.sha256_hex(provenance.canonical_json(payload))
