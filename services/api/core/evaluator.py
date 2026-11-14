"""Sealed-outcome vault and forecast scoring (SPEC §5, §6; MATH_MODEL §6, §9).

This is the only module that reads ``data/sealed_outcomes/``. It does so in exactly one place,
``OutcomeVault.reveal(prediction_id)``, which raises ``NotRevealable`` unless that prediction is already
persisted in the SQLite store and its stored prompt, snapshot and forecast still match their SHA-256 hashes.
The event to reveal is taken from the persisted prediction, never from the caller.

Forecast-before-outcome is enforced per EVENT, not per prediction: ``build_scorecard(vault)`` reads every
persisted prediction from the store itself and excludes any prediction persisted after the first reveal of
any prediction for the same event (``audit_log`` order). The population and each forecast's market baseline,
contamination flag and synthetic flag were fixed by the gate before any reveal; nothing comes from the caller.
The configured sealed folder can only be revealed into the configured prediction store.

Scoring (MATH_MODEL §6), for outcome y in {0, 1} and forecast p in [0, 1]:
  Brier = (p - y)^2
  log loss = -y ln(p~) - (1 - y) ln(1 - p~),  p~ = min(max(p, 1e-6), 1 - 1e-6)
  accuracy at 0.5 (secondary): predict YES iff p > 0.5, so p = 0.5 counts as predicting NO.

Aggregation: forecasters are compared on identical (event_id, as_of) pairs; multiple horizons are averaged
within an event first, and events are the unit of resampling. Uncertainty: paired bootstrap over events,
B = 10,000, fixed seed, 95% percentile CI of mean Brier(agent) - mean Brier(market). The scorecard always
uses the pre-specified B and seed; they cannot be overridden through ``build_scorecard``.

Display: n < 5 -> INSUFFICIENT DATA (per-event scores still listed); 5 <= n < 30 -> small-sample caveat;
"agent better than market" only if the CI upper bound < 0, otherwise "No improvement measured".
"""

from __future__ import annotations

import math
import os
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import numpy as np
from pydantic import AwareDatetime, BaseModel, ConfigDict, ValidationError

from config import get_settings
from core import store as store_module
from core.store import PredictionStore, RevealMark, StoredPrediction
from core.temporal_gate import PROMPT_VARIANTS, EvidenceStore, MarketNotAvailable
from errors import FaultlineError
from markets.base import MARKET_LABEL, SYNTHETIC_QUOTE_LABEL, SYNTHETIC_VENUE
from models import ErrorCode, ForecastVariant, Identifier, Prediction, Provenance

EPS = 1e-6
DEFAULT_RESAMPLES = 10_000
# Pre-specified before any outcome was revealed; changing it after looking at results is not allowed.
BOOTSTRAP_SEED = 20261115
CONFIDENCE = 0.95
MIN_EVENTS = 5
SMALL_SAMPLE_EVENTS = 30

INSUFFICIENT_DATA = "INSUFFICIENT DATA"
NO_IMPROVEMENT = "No improvement measured"
AGENT_BETTER = "agent better than market"
LABEL_INSUFFICIENT = "INSUFFICIENT DATA: No valid comparison"
LABEL_ILLUSTRATIVE = "ILLUSTRATIVE: Synthetic demo fixtures"
LABEL_NOT_OFFICIAL = "ILLUSTRATIVE: Historical cases, not an official run (see official_blockers)"

ExclusionReason = Literal[
    "no_persisted_prediction",
    "persisted_after_outcome_revealed",
    "multiple_predictions",
    "contamination_likely",
    "market_not_available",
    "sealed_outcome_not_available",
    "context_mismatch",
]
# Real and synthetic cases are scored as separate sets (issue #102); a synthetic set is never OFFICIAL.
CaseSet = Literal["real", "synthetic"]
CASE_SETS: tuple[CaseSet, ...] = ("real", "synthetic")
# market_label of a scorecard whose market baselines mix synthetic and real-venue quotes (synthetic cases only).
MIXED_MARKET_LABEL = (
    f'"synthetic:" refs: {SYNTHETIC_QUOTE_LABEL}; other refs: {MARKET_LABEL}'
)

# Exclusions an operator could cause on purpose (skip a run, re-run, peek, use other case data). Any of them on a
# real committed case blocks the OFFICIAL label. The other reasons are fixed by committed, reviewed data.
OPERATOR_REASONS = frozenset(
    {"no_persisted_prediction", "persisted_after_outcome_revealed", "multiple_predictions", "context_mismatch"}
)


# ---------------------------------------------------------------- errors


class NotRevealable(FaultlineError):
    def __init__(self, message: str) -> None:
        super().__init__(ErrorCode.NOT_REVEALABLE, message, status_code=409)


class SealedOutcomeInvalid(ValueError):
    """The sealed outcome file exists but fails its schema or names another event. Nothing is revealed."""


class OutcomeNotAvailable(FaultlineError):
    def __init__(self, message: str) -> None:
        super().__init__(ErrorCode.NOT_FOUND, message, status_code=404)


# ---------------------------------------------------------------- the vault


class SealedOutcome(BaseModel):
    """File format of ``data/sealed_outcomes/<event_id>.json``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: Identifier
    outcome: Literal["YES", "NO"]
    resolved_at: AwareDatetime | None = None
    source_url: str
    provenance: Provenance
    notes: str | None = None


_BUILDING = threading.local()


@dataclass(frozen=True)
class RevealedOutcome:
    """A persisted prediction with its realized outcome and audit ordering. Created only by ``OutcomeVault.reveal``.

    ``persist_seq`` / ``event_first_reveal_seq`` are positions in the store's single append-only audit log;
    ``persisted_before_outcome_revealed`` compares them, so it does not depend on clock resolution.
    """

    prediction: Prediction
    y: int
    sealed: SealedOutcome
    revealed_at: datetime
    reveal_seq: int
    persisted_at: datetime
    persist_seq: int
    event_first_revealed_at: datetime
    event_first_reveal_seq: int

    def __post_init__(self) -> None:
        if not getattr(_BUILDING, "active", False):
            raise TypeError("RevealedOutcome is created only by OutcomeVault.reveal")

    @property
    def persisted_before_outcome_revealed(self) -> bool:
        return self.persist_seq < self.event_first_reveal_seq


def _utcnow() -> datetime:
    return datetime.now(UTC)


def configured_sealed_dir() -> Path:
    return get_settings().data_dir / "sealed_outcomes"


def _same_path(a: Path | str, b: Path | str) -> bool:
    a, b = Path(a), Path(b)
    try:
        if a.exists() and b.exists():
            return os.path.samefile(a, b)
    except OSError:
        pass
    return os.path.normcase(str(a.resolve())) == os.path.normcase(str(b.resolve()))


class OutcomeVault:
    def __init__(
        self,
        store: PredictionStore,
        *,
        sealed_dir: Path | str | None = None,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        if not isinstance(store, PredictionStore):
            raise TypeError("OutcomeVault needs a PredictionStore")
        self._store = store
        self._dir = Path(sealed_dir) if sealed_dir is not None else configured_sealed_dir()
        self._clock = clock
        # One reveal ledger per real sealed folder: the configured folder may only be revealed into the
        # configured prediction store, so a scratch store cannot peek at real outcomes without a trace.
        if _same_path(self._dir, configured_sealed_dir()) and not _same_path(store.path, store_module.DEFAULT_DB_PATH):
            raise ValueError(
                "the configured sealed-outcome folder can only be revealed into the configured prediction store "
                f"({store_module.DEFAULT_DB_PATH}); refusing {store.path}"
            )

    @property
    def store(self) -> PredictionStore:
        return self._store

    @property
    def sealed_dir(self) -> Path:
        return self._dir

    def _path_for(self, event_id: str) -> Path:
        if not event_id or "/" in event_id or "\\" in event_id or event_id.startswith("."):
            raise NotRevealable(f"unsafe event id {event_id!r}")
        path = self._dir / f"{event_id}.json"
        if path.resolve().parent != self._dir.resolve():
            raise NotRevealable(f"sealed outcome path for {event_id!r} escapes the sealed directory")
        return path

    def reveal(self, prediction_id: str) -> RevealedOutcome:
        """Return the realized outcome for a persisted prediction. Raises before touching the sealed directory
        unless the prediction is persisted with intact prompt, snapshot and record hashes."""
        rec = self._store.get_record(prediction_id)
        if rec is None:
            raise NotRevealable(f"prediction {prediction_id!r} is not persisted; persist the forecast before reveal")
        problems = self._store.verify(prediction_id)
        if problems:
            raise NotRevealable(f"audit hash check failed for {prediction_id!r}: " + "; ".join(problems))
        revealed_at = self._clock()
        if revealed_at < rec.persisted_at:
            raise NotRevealable(f"reveal time precedes the persisted time of {prediction_id!r}")

        event_id = rec.prediction.event_id
        path = self._path_for(event_id)
        if not path.is_file():
            raise OutcomeNotAvailable(f"no sealed outcome for {event_id!r}: NOT AVAILABLE")
        try:
            sealed = SealedOutcome.model_validate_json(path.read_text(encoding="utf-8"))
        except ValidationError:
            # pydantic's message would echo the file's values; name the problem only.
            raise SealedOutcomeInvalid(f"sealed outcome file for {event_id!r} failed its schema") from None
        if sealed.event_id != event_id:
            raise SealedOutcomeInvalid(f"sealed outcome file for {event_id!r} names a different event")
        # A forecast made on a synthetic case may only reveal a SYNTHETIC sealed file, and a forecast on a real
        # case only a REAL_HISTORICAL one (#102): the case file alone never decides what kind of answer is read.
        expected = Provenance.SYNTHETIC if rec.context.synthetic else Provenance.REAL_HISTORICAL
        if sealed.provenance != expected:
            raise SealedOutcomeInvalid(
                f"sealed outcome file for {event_id!r} has provenance {sealed.provenance.value}, but the forecast was "
                f"made on a {'synthetic' if rec.context.synthetic else 'real'} case; nothing was revealed"
            )
        mark = self._store.record_reveal(rec.prediction, revealed_at, sealed_provenance=sealed.provenance.value)
        first = self._store.first_reveal(event_id)
        assert first is not None  # the reveal just recorded
        _BUILDING.active = True
        try:
            return RevealedOutcome(
                prediction=rec.prediction,
                y=1 if sealed.outcome == "YES" else 0,
                sealed=sealed,
                revealed_at=revealed_at,
                reveal_seq=mark.seq,
                persisted_at=rec.persisted_at,
                persist_seq=rec.persist_seq,
                event_first_revealed_at=first.at,
                event_first_reveal_seq=first.seq,
            )
        finally:
            _BUILDING.active = False


# ---------------------------------------------------------------- per-forecast scores


def _check_p(p: float) -> float:
    if isinstance(p, bool) or not isinstance(p, (int, float)):
        raise TypeError(f"probability must be a number, got {type(p).__name__}")
    if not math.isfinite(p) or p < 0.0 or p > 1.0:
        raise ValueError(f"probability {p!r} outside [0, 1]")
    return float(p)


def _check_y(y: int) -> int:
    if isinstance(y, bool) or not isinstance(y, int):
        raise TypeError(f"outcome must be the int 0 or 1, got {type(y).__name__}")
    if y not in (0, 1):
        raise ValueError(f"outcome {y!r} not in {{0, 1}}")
    return y


def brier(p: float, y: int) -> float:
    p, y = _check_p(p), _check_y(y)
    return (p - y) ** 2


def log_loss(p: float, y: int, eps: float = EPS) -> float:
    p, y = _check_p(p), _check_y(y)
    pt = min(max(p, eps), 1.0 - eps)
    return -math.log(pt) if y == 1 else -math.log(1.0 - pt)


def correct_at_half(p: float, y: int) -> float:
    """1.0 if the pre-specified 0.5 threshold call is right (p > 0.5 means YES; p = 0.5 means NO), else 0.0."""
    p, y = _check_p(p), _check_y(y)
    return 1.0 if (p > 0.5) == (y == 1) else 0.0


# ---------------------------------------------------------------- paired bootstrap


@dataclass(frozen=True)
class BootstrapResult:
    n: int
    mean_delta: float
    ci_low: float
    ci_high: float
    confidence: float
    n_resamples: int
    seed: int


def paired_bootstrap(
    a: Sequence[float],
    b: Sequence[float],
    *,
    n_resamples: int = DEFAULT_RESAMPLES,
    seed: int = BOOTSTRAP_SEED,
    confidence: float = CONFIDENCE,
) -> BootstrapResult:
    """Percentile CI of mean(a) - mean(b), resampling paired units (events) with replacement.

    Algorithm: ``d = a - b``; ``idx = default_rng(seed).integers(0, n, size=(B, n))``; the B resampled means
    of ``d[idx]``; CI = their (1-c)/2 and (1+c)/2 percentiles (numpy linear interpolation).
    """
    da, db = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    if da.ndim != 1 or da.shape != db.shape:
        raise ValueError("paired_bootstrap needs two equal-length 1-D sequences")
    if da.size == 0:
        raise ValueError("paired_bootstrap needs at least one pair")
    if not (np.isfinite(da).all() and np.isfinite(db).all()):
        raise ValueError("paired_bootstrap inputs must be finite")
    if n_resamples < 1 or not 0.0 < confidence < 1.0:
        raise ValueError("n_resamples must be >= 1 and confidence in (0, 1)")
    d = da - db
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, d.size, size=(n_resamples, d.size))
    means = d[idx].mean(axis=1)
    q_lo, q_hi = round(50.0 * (1.0 - confidence), 10), round(50.0 * (1.0 + confidence), 10)
    lo, hi = np.percentile(means, [q_lo, q_hi])
    return BootstrapResult(
        n=int(d.size),
        mean_delta=float(d.mean()),
        ci_low=float(lo),
        ci_high=float(hi),
        confidence=confidence,
        n_resamples=n_resamples,
        seed=seed,
    )


# ---------------------------------------------------------------- scorecard


class ScoreExclusion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str
    as_of: AwareDatetime
    reason: ExclusionReason
    prediction_ids: list[str] = []


class IgnoredPrediction(BaseModel):
    """A persisted prediction that was not used, e.g. saved after the event's outcome was first revealed."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    prediction_id: str
    event_id: str
    as_of: AwareDatetime
    reason: Literal["persisted_after_outcome_revealed"]


class EventScore(BaseModel):
    """Per-event scores (averaged over that event's snapshots). Post-reveal only."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str
    n_snapshots: int
    y: int
    prediction_ids: list[str]
    market_refs: list[str]  # "venue:market_id" of the market baseline used
    brier: dict[str, float]
    log_loss: dict[str, float]
    accuracy_at_0_5: dict[str, float]


class ForecasterSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    mean_brier: float
    mean_log_loss: float
    accuracy_at_0_5: float


class Comparison(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    agent_variant: ForecastVariant
    baseline: Literal["market"] = "market"
    metric: Literal["brier"] = "brier"
    mean_delta_brier: float  # agent - market; negative means the agent had lower (better) Brier
    ci_low: float
    ci_high: float
    confidence: float
    n_resamples: int
    seed: int


class Scorecard(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    label: str
    verdict: str
    caveat: str | None
    provenance: Provenance | None  # None when no event could be scored
    agent_variant: ForecastVariant
    forecasters: list[str]
    market_label: str = MARKET_LABEL  # SYNTHETIC_QUOTE_LABEL when the market baselines are synthetic prices
    # Which case set was scored (``build_scorecard(case_set=...)``); None = not partitioned (all keys, legacy).
    case_set: CaseSet | None = None
    n_events: int
    n_excluded: int
    exclusions_by_reason: dict[str, int]
    exclusions: list[ScoreExclusion]
    ignored_predictions: list[IgnoredPrediction]
    per_event: list[EventScore]
    summary: dict[str, ForecasterSummary] | None
    comparison: Comparison | None
    official_blockers: list[str]  # why a real-historical scorecard is not OFFICIAL; empty when it is


def configured_cases_dir() -> Path:
    return get_settings().data_dir / "demo_cases"


def _context_mismatch(cases: EvidenceStore, event_id: str, as_of: datetime, variant: str, rec) -> bool:
    """True unless re-deriving the forecast's input from ``cases`` reproduces its hashes and frozen context."""
    try:
        mi = cases.get_as_of(event_id, as_of).model_input(variant)  # type: ignore[arg-type]
    except (LookupError, ValueError):
        return True
    ctx = rec.context
    return (
        mi.prompt_sha256,
        mi.snapshot_sha256,
        mi.market_baseline_p_yes,
        mi.market_baseline_ref,
        mi.contamination_flag,
        bool(mi.synthetic),
        mi.case_sha256,
    ) != (
        # The gate's prompt hash: prompt_sha256 is what the model answered, which includes a repair turn (#44).
        rec.prediction.gated_prompt_sha256 or rec.prediction.prompt_sha256,
        rec.prediction.snapshot_sha256,
        ctx.market_baseline_p_yes,
        ctx.market_baseline_ref,
        ctx.contamination_flag,
        ctx.synthetic,
        ctx.case_sha256,
    )


def committed_synthetic_events(cases: EvidenceStore | None, all_recs: Sequence[StoredPrediction]) -> set[str]:
    """Committed cases that count as SYNTHETIC (issues #102, #118). The one rule behind the case sets, the
    operator-blocker and ``peeked`` exemptions, and (with the configured case directory) the ``late`` exemption.

    A case in ``cases`` qualifies iff it says ``synthetic: true`` with provenance SYNTHETIC AND no forecast
    persisted for that event froze ``synthetic=False`` in its gate context (every stored forecast froze True, or
    there is none). A case file edited to say synthetic after a real-context forecast was saved therefore stays
    real, where its forecast is ``context_mismatch`` and blocks OFFICIAL.
    """
    if cases is None:
        return set()
    froze_real = {r.prediction.event_id for r in all_recs if not r.context.synthetic}
    out = set()
    for cid in cases.case_ids():
        case = cases.public_case(cid)
        if case.synthetic and case.provenance == Provenance.SYNTHETIC and cid not in froze_real:
            out.add(cid)
    return out


def _synthetic_exempt_events(cases: EvidenceStore | None, all_recs: Sequence[StoredPrediction]) -> set[str]:
    """Events whose reveals do not count for the cross-event ``late`` check (issue #102).

    Only a committed SYNTHETIC case qualifies: ``cases`` was loaded by ``EvidenceStore.from_dir()`` from the
    configured case directory, the case is in ``committed_synthetic_events`` (``synthetic: true``, provenance
    SYNTHETIC, and EVERY forecast persisted for that event froze ``synthetic=True``), and it has at least one
    stored forecast. Its sealed answer is a fictional draw, so revealing it on stage tells nothing about any real
    event. Anything else (no case list, an in-memory list, a real, relabelled or uncommitted case) is not exempt,
    so the check stays as strict as before. Even for an exempt event, only reveals LOGGED with sealed provenance
    SYNTHETIC are skipped (``first_counted_reveal``).
    """
    if cases is None or cases.source_dir is None or not _same_path(cases.source_dir, configured_cases_dir()):
        return set()
    forecast = {r.prediction.event_id for r in all_recs}
    return committed_synthetic_events(cases, all_recs) & forecast


def first_counted_reveal(
    store: PredictionStore,
    cases: EvidenceStore | None,
    all_recs: Sequence[StoredPrediction] | None = None,
) -> RevealMark | None:
    """The earliest reveal in ``store`` that counts as "an outcome is known" (``late`` check; the official-run
    pre-flight in scripts/record_runs.py uses this same function). Only reveals LOGGED with sealed provenance
    SYNTHETIC of a ``_synthetic_exempt_events`` event are skipped (``PredictionStore.first_counted_reveal``);
    reveals logged REAL_HISTORICAL, or before #102 (NULL), always count. None = no counted reveal."""
    recs = store.all_records() if all_recs is None else all_recs
    return store.first_counted_reveal(_synthetic_exempt_events(cases, recs))


def market_label_for(market_refs: Sequence[str]) -> str:
    """The label of the "market" forecaster for these baseline refs ("<venue>:<market_id>")."""
    synthetic = {ref.startswith(f"{SYNTHETIC_VENUE}:") for ref in market_refs}
    if synthetic == {True}:
        return SYNTHETIC_QUOTE_LABEL
    return MIXED_MARKET_LABEL if synthetic == {True, False} else MARKET_LABEL


def event_case_sets(cases: EvidenceStore | None, all_recs: Sequence[StoredPrediction]) -> dict[str, CaseSet]:
    """The case set of every event in ``cases`` or the store (issues #102, #118). One rule, used for every card:

    * an event in ``cases`` is ``synthetic`` iff it is in ``committed_synthetic_events``: the case says
      ``synthetic: true`` with provenance SYNTHETIC (reviewed, committed data) AND no stored forecast for it froze
      ``synthetic=False``; else ``real`` (a case relabelled synthetic after a real forecast stays real);
    * an event only in the store is ``synthetic`` iff EVERY forecast persisted for it froze ``synthetic=True``,
      else ``real`` (so an unknown or mixed event stays in the real set, where it blocks OFFICIAL as before).
    """
    out: dict[str, CaseSet] = {}
    synthetic = committed_synthetic_events(cases, all_recs)
    for cid in cases.case_ids() if cases is not None else ():
        out[cid] = "synthetic" if cid in synthetic else "real"
    frozen: dict[str, set[bool]] = {}
    for r in all_recs:
        frozen.setdefault(r.prediction.event_id, set()).add(bool(r.context.synthetic))
    for event_id, flags in frozen.items():
        out.setdefault(event_id, "synthetic" if flags == {True} else "real")
    return out


def case_sets_present(store: PredictionStore, cases: EvidenceStore | None) -> list[CaseSet]:
    """The case sets that have at least one scorecard key, in ``CASE_SETS`` order (real first)."""
    present = set(event_case_sets(cases, store.all_records()).values())
    return [c for c in CASE_SETS if c in present]


def _gate_has_no_market(cases: EvidenceStore, event_id: str, as_of: datetime, variant: str) -> bool:
    """True iff ``variant`` is agent_plus_market and the gate has no quote within 24h before ``as_of``."""
    if variant != "agent_plus_market":
        return False
    try:
        cases.get_as_of(event_id, as_of).model_input(variant)  # type: ignore[arg-type]
    except MarketNotAvailable:
        return True
    except (LookupError, ValueError):
        return False
    return False


def build_scorecard(
    vault: OutcomeVault,
    *,
    agent_variant: ForecastVariant = "agent_only",
    cases: EvidenceStore | None = None,
    case_set: CaseSet | None = None,
) -> Scorecard:
    """Score one agent variant against naive (p = 0.5) and market-only on identical (event_id, as_of) pairs.

    ``case_set`` ("real" | "synthetic") keeps only the keys of that set (``event_case_sets``); keys of the other
    set are not part of the card at all (not scored, not excluded, not revealed). A real card is therefore the
    same with or without synthetic cases present. A synthetic card is never OFFICIAL. ``None`` scores every key
    (and raises if real and synthetic outcomes would be pooled).

    Nothing about the population or the baselines comes from the caller:
      * the keys are every (event_id, as_of) with a persisted prediction of ANY variant in the vault's store,
        plus, if ``cases`` is given, every case at its own cutoff (so unpredicted cases are reported);
      * the market baseline, contamination flag and synthetic flag of each prediction are the ones the gate
        fixed in its ``ModelInput`` and the store persisted with it, before any reveal.
    Per key, for ``agent_variant``:
      * none persisted -> excluded ``no_persisted_prediction``, except, with ``cases``, an ``agent_plus_market``
        key whose gate snapshot has no quote within 24h (the variant cannot run) -> ``market_not_available``;
      * persisted after the event's first reveal (any as_of, any variant) -> ignored, and if nothing else is
        left the key is excluded ``persisted_after_outcome_revealed``;
      * more than one persisted before that reveal -> excluded ``multiple_predictions`` (no choosing);
      * then ``contamination_likely``, ``market_not_available``, ``sealed_outcome_not_available``.
    With ``cases``, a remaining prediction whose input cannot be re-derived from ``cases`` with the same prompt
    and snapshot hashes and the same frozen context (incl. the case content hash) -> ``context_mismatch``.
    The single remaining prediction is revealed through the vault (logged) and scored.

    The OFFICIAL label additionally requires (else ``official_blockers`` says why and the label is ILLUSTRATIVE):
    ``cases`` loaded by ``EvidenceStore.from_dir()`` from the configured case directory; the vault on the
    configured sealed folder (hence the configured store); no ``OPERATOR_REASONS`` exclusion on any real or
    uncommitted case (only ``committed_synthetic_events`` are exempt); and every scored forecast persisted before
    the FIRST counted reveal anywhere in the store (``first_counted_reveal``: logged-SYNTHETIC reveals of
    committed SYNTHETIC cases do not count).
    """
    if not isinstance(vault, OutcomeVault):
        raise TypeError("build_scorecard needs the OutcomeVault; predictions are read from its store")
    if agent_variant not in PROMPT_VARIANTS:
        raise ValueError(f"agent_variant must be one of {PROMPT_VARIANTS}")
    if cases is not None and not isinstance(cases, EvidenceStore):
        raise TypeError("cases must be the EvidenceStore the forecasts were made from")
    if case_set is not None and case_set not in CASE_SETS:
        raise ValueError(f"case_set must be one of {CASE_SETS}")
    store = vault.store

    all_recs = store.all_records()
    keys: set[tuple[str, datetime]] = {(r.prediction.event_id, r.prediction.as_of.astimezone(UTC)) for r in all_recs}
    if cases is not None:
        keys |= {(cid, cases.public_case(cid).as_of.astimezone(UTC)) for cid in cases.case_ids()}
    if case_set is not None:
        sets = event_case_sets(cases, all_recs)
        keys = {k for k in keys if sets[k[0]] == case_set}
    # First reveal per event and in the whole store, read once before this scorecard reveals anything.
    first_reveal = {event_id: store.first_reveal(event_id) for event_id, _ in keys}
    first_reveal_any = first_counted_reveal(store, cases, all_recs)
    # Committed SYNTHETIC cases (every stored forecast froze synthetic=True) never block OFFICIAL (#118).
    exempt_synthetic = committed_synthetic_events(cases, all_recs)

    exclusions: list[ScoreExclusion] = []
    ignored: list[IgnoredPrediction] = []
    candidates: list[tuple[str, datetime, StoredPrediction]] = []
    for event_id, as_of in sorted(keys):
        recs = store.records_for(event_id, as_of, agent_variant)
        first = first_reveal[event_id]
        before = [r for r in recs if first is None or r.persist_seq < first.seq]
        before_seqs = {r.persist_seq for r in before}
        for r in recs:
            if r.persist_seq not in before_seqs:
                ignored.append(
                    IgnoredPrediction(
                        prediction_id=r.prediction.prediction_id,
                        event_id=event_id,
                        as_of=as_of,
                        reason="persisted_after_outcome_revealed",
                    )
                )
        reason: ExclusionReason | None = None
        ids = [r.prediction.prediction_id for r in recs]
        if not recs and cases is not None and _gate_has_no_market(cases, event_id, as_of, agent_variant):
            # agent_plus_market cannot run without a quote within 24h: not an operator choice, so it is not
            # reported as a skipped forecast (which would block OFFICIAL).
            reason = "market_not_available"
        elif not recs:
            reason = "no_persisted_prediction"
        elif not before:
            reason = "persisted_after_outcome_revealed"
        elif len(before) > 1:
            reason, ids = "multiple_predictions", [r.prediction.prediction_id for r in before]
        elif case_set is not None and bool(before[0].context.synthetic) != (case_set == "synthetic"):
            # The forecast's frozen context belongs to the other population: never revealed into this card.
            reason = "context_mismatch"
        elif cases is not None and _context_mismatch(cases, event_id, as_of, agent_variant, before[0]):
            reason = "context_mismatch"
        elif before[0].context.contamination_flag == "likely":
            reason = "contamination_likely"
        elif before[0].context.market_baseline_p_yes is None:
            reason = "market_not_available"
        if reason is None:
            candidates.append((event_id, as_of, before[0]))
        else:
            exclusions.append(ScoreExclusion(event_id=event_id, as_of=as_of, reason=reason, prediction_ids=ids))

    # The population is fixed BEFORE anything is revealed: a mixed set fails here with nothing logged (#102).
    if len({bool(rec.context.synthetic) for _e, _t, rec in candidates}) > 1:
        raise ValueError(
            "synthetic and real historical cases must be scored separately (pass case_set); nothing was revealed"
        )

    agent_key = agent_variant
    forecasters = ["naive", "market", agent_key]
    snapshots: dict[str, list[tuple[int, str, dict[str, float]]]] = {}
    market_refs: dict[str, list[str | None]] = {}
    real_flags: set[bool] = set()
    scored_seqs: list[int] = []
    for event_id, as_of, rec in candidates:
        ctx = rec.context
        pid = rec.prediction.prediction_id
        try:
            rev = vault.reveal(pid)
        except OutcomeNotAvailable:
            exclusions.append(
                ScoreExclusion(
                    event_id=event_id, as_of=as_of, reason="sealed_outcome_not_available", prediction_ids=[pid]
                )
            )
            continue
        pre = first_reveal[event_id]
        if rev.persist_seq != rec.persist_seq or (pre is not None and rev.persist_seq >= pre.seq):
            raise RuntimeError(f"audit order changed while scoring {pid!r}")
        sealed_real = rev.sealed.provenance == Provenance.REAL_HISTORICAL
        if sealed_real == ctx.synthetic:  # assertion: OutcomeVault.reveal refuses this before logging
            raise RuntimeError(f"{event_id}: sealed provenance disagrees with the forecast's case after reveal")
        real_flags.add(sealed_real)
        scored_seqs.append(rec.persist_seq)
        probs = {"naive": 0.5, "market": float(ctx.market_baseline_p_yes), agent_key: rev.prediction.p_yes}  # type: ignore[arg-type]
        snapshots.setdefault(event_id, []).append((rev.y, pid, probs))
        market_refs.setdefault(event_id, []).append(ctx.market_baseline_ref)

    # Assertions only: the population was checked before the reveal loop, and reveal() checks sealed provenance.
    if len(real_flags) > 1:
        raise RuntimeError("synthetic and real historical outcomes were scored together")
    is_real = real_flags == {True}
    if case_set is not None and real_flags and is_real != (case_set == "real"):
        raise RuntimeError(f"the {case_set} case set scored {'real' if is_real else 'synthetic'} outcomes")

    per_event: list[EventScore] = []
    for event_id in sorted(snapshots):
        rows = snapshots[event_id]
        ys = {y for y, _, _ in rows}
        if len(ys) != 1:
            raise ValueError(f"{event_id}: inconsistent outcomes across snapshots")
        y = ys.pop()
        per_event.append(
            EventScore(
                event_id=event_id,
                n_snapshots=len(rows),
                y=y,
                prediction_ids=[pid for _, pid, _ in rows],
                market_refs=sorted({ref for ref in market_refs[event_id] if ref is not None}),
                brier={f: float(np.mean([brier(pr[f], y) for _, _, pr in rows])) for f in forecasters},
                log_loss={f: float(np.mean([log_loss(pr[f], y) for _, _, pr in rows])) for f in forecasters},
                accuracy_at_0_5={
                    f: float(np.mean([correct_at_half(pr[f], y) for _, _, pr in rows])) for f in forecasters
                },
            )
        )

    n = len(per_event)
    by_reason: dict[str, int] = {}
    for x in exclusions:
        by_reason[x.reason] = by_reason.get(x.reason, 0) + 1
    blockers: list[str] = []
    if cases is None:
        blockers.append("cases not given: not checked against the committed case files")
    elif cases.source_dir is None or not _same_path(cases.source_dir, configured_cases_dir()):
        blockers.append(f"cases were not loaded by EvidenceStore.from_dir() from {configured_cases_dir()}")
    if not _same_path(vault.sealed_dir, configured_sealed_dir()):
        blockers.append(f"the vault does not use the configured sealed-outcome folder {configured_sealed_dir()}")
    operator = [x for x in exclusions if x.reason in OPERATOR_REASONS and x.event_id not in exempt_synthetic]
    for reason in sorted({x.reason for x in operator}):
        hit = sorted({x.event_id for x in operator if x.reason == reason})
        blockers.append(f"{reason}: {len(hit)} event(s) {hit}")
    peeked = sorted({p.event_id for p in ignored if p.event_id not in exempt_synthetic})
    if peeked:
        blockers.append(f"persisted_after_outcome_revealed (ignored forecasts): {len(peeked)} event(s) {peeked}")
    late = [seq for seq in scored_seqs if first_reveal_any is not None and seq >= first_reveal_any.seq]
    if late:
        blockers.append(
            f"{len(late)} scored forecast(s) were saved after an outcome in this store had already been revealed "
            "(possible cross-event leakage)"
        )
    common = dict(
        official_blockers=blockers,
        agent_variant=agent_variant,
        forecasters=forecasters,
        n_events=n,
        n_excluded=len(exclusions),
        exclusions_by_reason=by_reason,
        exclusions=sorted(exclusions, key=lambda x: (x.event_id, x.as_of)),
        ignored_predictions=ignored,
        per_event=per_event,
        provenance=None if n == 0 else (Provenance.REAL_HISTORICAL if is_real else Provenance.SYNTHETIC),
        case_set=case_set,
        market_label=market_label_for([ref for e in per_event for ref in e.market_refs]),
    )
    if n < MIN_EVENTS:
        return Scorecard(
            label=LABEL_INSUFFICIENT, verdict=INSUFFICIENT_DATA, caveat=None, summary=None, comparison=None, **common
        )

    summary = {
        f: ForecasterSummary(
            mean_brier=float(np.mean([e.brier[f] for e in per_event])),
            mean_log_loss=float(np.mean([e.log_loss[f] for e in per_event])),
            accuracy_at_0_5=float(np.mean([e.accuracy_at_0_5[f] for e in per_event])),
        )
        for f in forecasters
    }
    boot = paired_bootstrap([e.brier[agent_key] for e in per_event], [e.brier["market"] for e in per_event])
    comparison = Comparison(
        agent_variant=agent_variant,
        mean_delta_brier=boot.mean_delta,
        ci_low=boot.ci_low,
        ci_high=boot.ci_high,
        confidence=boot.confidence,
        n_resamples=boot.n_resamples,
        seed=boot.seed,
    )
    return Scorecard(
        label=(
            LABEL_ILLUSTRATIVE
            if not is_real or case_set == "synthetic"
            else (LABEL_NOT_OFFICIAL if blockers else f"OFFICIAL: Computed from {n} historical cases")
        ),
        verdict=AGENT_BETTER if boot.ci_high < 0 else NO_IMPROVEMENT,
        caveat=None if n >= SMALL_SAMPLE_EVENTS else f"small sample: n = {n} events (< {SMALL_SAMPLE_EVENTS})",
        summary=summary,
        comparison=comparison,
        **common,
    )
