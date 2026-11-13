"""Sealed-outcome vault and forecast scoring (SPEC §5, §6; MATH_MODEL §6, §9).

This is the only module that reads ``data/sealed_outcomes/``. It does so in exactly one place,
``OutcomeVault.reveal(prediction_id)``, which raises ``NotRevealable`` unless that prediction is already
persisted in the SQLite store and its stored prompt/snapshot still match their SHA-256 hashes. The event to
reveal is taken from the persisted prediction, never from the caller.

Scoring (MATH_MODEL §6), for outcome y in {0, 1} and forecast p in [0, 1]:
  Brier = (p - y)^2
  log loss = -y ln(p~) - (1 - y) ln(1 - p~),  p~ = min(max(p, 1e-6), 1 - 1e-6)
  accuracy at 0.5 (secondary): predict YES iff p > 0.5, so p = 0.5 counts as predicting NO.

Aggregation: forecasters are compared on identical (event_id, as_of) pairs; multiple horizons are averaged
within an event first, and events are the unit of resampling. Uncertainty: paired bootstrap over events,
B = 10,000, fixed seed, 95% percentile CI of mean Brier(agent) - mean Brier(market).

Display: n < 5 -> INSUFFICIENT DATA (per-event scores still listed); 5 <= n < 30 -> small-sample caveat;
"agent better than market" only if the CI upper bound < 0, otherwise "No improvement measured".
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import numpy as np
from pydantic import AwareDatetime, BaseModel, ConfigDict

from config import get_settings
from core.store import PredictionStore, check_audit
from errors import FaultlineError
from markets.base import MARKET_LABEL
from models import ContaminationFlag, ErrorCode, ForecastVariant, Identifier, Prediction, Probability, Provenance

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

ExclusionReason = Literal["no_persisted_prediction", "contamination_likely", "market_not_available"]


# ---------------------------------------------------------------- errors


class NotRevealable(FaultlineError):
    def __init__(self, message: str) -> None:
        super().__init__(ErrorCode.NOT_REVEALABLE, message, status_code=409)


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


_REVEAL_TOKEN = object()


@dataclass(frozen=True)
class RevealedOutcome:
    """A persisted prediction together with its realized outcome. Created only by ``OutcomeVault.reveal``."""

    prediction: Prediction
    y: int
    sealed: SealedOutcome
    revealed_at: datetime
    _token: object = field(repr=False, compare=False, kw_only=True)

    def __post_init__(self) -> None:
        if self._token is not _REVEAL_TOKEN:
            raise TypeError("RevealedOutcome is created only by OutcomeVault.reveal")


def _utcnow() -> datetime:
    return datetime.now(UTC)


class OutcomeVault:
    def __init__(
        self,
        store: PredictionStore,
        *,
        sealed_dir: Path | str | None = None,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._store = store
        self._dir = Path(sealed_dir) if sealed_dir is not None else get_settings().data_dir / "sealed_outcomes"
        self._clock = clock

    def _path_for(self, event_id: str) -> Path:
        if not event_id or "/" in event_id or "\\" in event_id or event_id.startswith("."):
            raise NotRevealable(f"unsafe event id {event_id!r}")
        path = self._dir / f"{event_id}.json"
        if path.resolve().parent != self._dir.resolve():
            raise NotRevealable(f"sealed outcome path for {event_id!r} escapes the sealed directory")
        return path

    def reveal(self, prediction_id: str) -> RevealedOutcome:
        """Return the realized outcome for a persisted prediction. Raises before touching the sealed directory
        unless the prediction is persisted with intact prompt/snapshot hashes."""
        rec = self._store.get_record(prediction_id)
        if rec is None:
            raise NotRevealable(f"prediction {prediction_id!r} is not persisted; persist the forecast before reveal")
        problems = check_audit(rec.prediction, rec.prompt, rec.snapshot_json)
        if problems:
            raise NotRevealable(f"audit hash check failed for {prediction_id!r}: " + "; ".join(problems))
        revealed_at = self._clock()
        if revealed_at < rec.persisted_at:
            raise NotRevealable(f"reveal time precedes the persisted time of {prediction_id!r}")

        event_id = rec.prediction.event_id
        path = self._path_for(event_id)
        if not path.is_file():
            raise OutcomeNotAvailable(f"no sealed outcome for {event_id!r}: NOT AVAILABLE")
        sealed = SealedOutcome.model_validate_json(path.read_text(encoding="utf-8"))
        if sealed.event_id != event_id:
            raise ValueError(f"sealed outcome file for {event_id!r} names a different event")
        self._store.record_reveal(prediction_id, revealed_at)
        return RevealedOutcome(
            prediction=rec.prediction,
            y=1 if sealed.outcome == "YES" else 0,
            sealed=sealed,
            revealed_at=revealed_at,
            _token=_REVEAL_TOKEN,
        )


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


class EventContext(BaseModel):
    """Pre-reveal facts about one (event_id, as_of) snapshot needed for scoring. Holds no outcome."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: Identifier
    as_of: AwareDatetime
    market_p_yes: Probability | None  # None: no quote within 24h before as_of (NOT AVAILABLE)
    contamination_flag: ContaminationFlag = "unknown"
    synthetic: bool = True

    @classmethod
    def from_snapshot(cls, snapshot, *, venue: str | None = None) -> EventContext:
        """Build from a ``core.temporal_gate.GatedSnapshot``; ``venue`` picks one market when several exist."""
        quotes = [q for q in snapshot.market_quotes if venue is None or q["venue"] == venue]
        if len(quotes) > 1:
            raise ValueError("several market quotes available; pass venue= to choose the benchmark market")
        return cls(
            event_id=snapshot.case.event_id,
            as_of=snapshot.as_of,
            market_p_yes=quotes[0]["p_yes"] if quotes else None,
            contamination_flag=snapshot.case.contamination_flag,
            synthetic=snapshot.case.synthetic,
        )


class ScoreExclusion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str
    as_of: AwareDatetime
    reason: ExclusionReason


class EventScore(BaseModel):
    """Per-event scores (averaged over that event's snapshots). Post-reveal only."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str
    n_snapshots: int
    y: int
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
    market_label: str = MARKET_LABEL
    n_events: int
    n_excluded: int
    exclusions_by_reason: dict[str, int]
    exclusions: list[ScoreExclusion]
    per_event: list[EventScore]
    summary: dict[str, ForecasterSummary] | None
    comparison: Comparison | None


def build_scorecard(
    reveals: Iterable[RevealedOutcome],
    contexts: Iterable[EventContext],
    *,
    agent_variant: ForecastVariant = "agent_only",
    n_resamples: int = DEFAULT_RESAMPLES,
    seed: int = BOOTSTRAP_SEED,
) -> Scorecard:
    """Score one agent variant against naive (p = 0.5) and market-only on identical (event_id, as_of) pairs."""
    by_key: dict[tuple[str, datetime, str], dict[str, RevealedOutcome]] = {}
    for r in reveals:
        if not isinstance(r, RevealedOutcome):
            raise TypeError("build_scorecard needs RevealedOutcome values from OutcomeVault.reveal")
        p = r.prediction
        key = (p.event_id, p.as_of.astimezone(UTC), p.variant)
        by_key.setdefault(key, {})[p.prediction_id] = r

    ctx_list = sorted(contexts, key=lambda c: (c.event_id, c.as_of))
    seen: set[tuple[str, datetime]] = set()
    exclusions: list[ScoreExclusion] = []
    agent_key = agent_variant
    forecasters = ["naive", "market", agent_key]
    snapshots: dict[str, list[tuple[int, dict[str, float]]]] = {}
    real_flags: set[bool] = set()

    for ctx in ctx_list:
        as_of = ctx.as_of.astimezone(UTC)
        if (ctx.event_id, as_of) in seen:
            raise ValueError(f"duplicate context for ({ctx.event_id}, {as_of.isoformat()})")
        seen.add((ctx.event_id, as_of))
        found = list(by_key.get((ctx.event_id, as_of, agent_variant), {}).values())
        if len(found) > 1:
            raise ValueError(
                f"more than one persisted {agent_variant} prediction for ({ctx.event_id}, {as_of.isoformat()}); "
                "refusing to choose one (no cherry-picking)"
            )
        reason: ExclusionReason | None = None
        if not found:
            reason = "no_persisted_prediction"
        else:
            sealed_real = found[0].sealed.provenance == Provenance.REAL_HISTORICAL
            if sealed_real == ctx.synthetic:
                raise ValueError(
                    f"{ctx.event_id}: context synthetic={ctx.synthetic} disagrees with sealed provenance "
                    f"{found[0].sealed.provenance.value}"
                )
            if ctx.contamination_flag == "likely":
                reason = "contamination_likely"
            elif ctx.market_p_yes is None:
                reason = "market_not_available"
        if reason is not None:
            exclusions.append(ScoreExclusion(event_id=ctx.event_id, as_of=as_of, reason=reason))
            continue
        rev = found[0]
        real_flags.add(not ctx.synthetic)
        probs = {"naive": 0.5, "market": float(ctx.market_p_yes), agent_key: rev.prediction.p_yes}  # type: ignore[arg-type]
        snapshots.setdefault(ctx.event_id, []).append((rev.y, probs))

    if len(real_flags) > 1:
        raise ValueError("synthetic and real historical cases must be scored separately")
    is_real = real_flags == {True}

    per_event: list[EventScore] = []
    for event_id in sorted(snapshots):
        rows = snapshots[event_id]
        ys = {y for y, _ in rows}
        if len(ys) != 1:
            raise ValueError(f"{event_id}: inconsistent outcomes across snapshots")
        y = ys.pop()
        per_event.append(
            EventScore(
                event_id=event_id,
                n_snapshots=len(rows),
                y=y,
                brier={f: float(np.mean([brier(pr[f], y) for _, pr in rows])) for f in forecasters},
                log_loss={f: float(np.mean([log_loss(pr[f], y) for _, pr in rows])) for f in forecasters},
                accuracy_at_0_5={f: float(np.mean([correct_at_half(pr[f], y) for _, pr in rows])) for f in forecasters},
            )
        )

    n = len(per_event)
    by_reason: dict[str, int] = {}
    for x in exclusions:
        by_reason[x.reason] = by_reason.get(x.reason, 0) + 1
    common = dict(
        agent_variant=agent_variant,
        forecasters=forecasters,
        n_events=n,
        n_excluded=len(exclusions),
        exclusions_by_reason=by_reason,
        exclusions=exclusions,
        per_event=per_event,
        provenance=None if n == 0 else (Provenance.REAL_HISTORICAL if is_real else Provenance.SYNTHETIC),
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
    boot = paired_bootstrap(
        [e.brier[agent_key] for e in per_event],
        [e.brier["market"] for e in per_event],
        n_resamples=n_resamples,
        seed=seed,
    )
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
        label=f"OFFICIAL: Computed from {n} historical cases" if is_real else LABEL_ILLUSTRATIVE,
        verdict=AGENT_BETTER if boot.ci_high < 0 else NO_IMPROVEMENT,
        caveat=None if n >= SMALL_SAMPLE_EVENTS else f"small sample: n = {n} events (< {SMALL_SAMPLE_EVENTS})",
        summary=summary,
        comparison=comparison,
        **common,
    )
