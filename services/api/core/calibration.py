"""Calibration: reliability bins with Wilson intervals and the binned Brier decomposition (issue #86; MATH_MODEL §6).

Post-reveal and descriptive only. This module never reads sealed outcomes, the prediction store or any file: it
works on per-event (forecast, outcome) pairs that a ``Scorecard`` already contains, so it can only describe what
``core.evaluator.build_scorecard`` has scored. It does not compare forecasters and makes no "better" claim.

Bins (default K = 5, equal width on [0, 1]): bin k = [k/K, (k+1)/K) for k < K - 1 and the last bin [(K-1)/K, 1]
(so p = 1 is in the last bin and p = 0.2 in the second). Per forecaster and bin: count n_k, mean forecast p̄_k,
observed frequency ō_k, and the Wilson 95% interval (z = 1.96) on ō_k. Bins with n_k < 3 are flagged
"too few to read" (still listed); empty bins have count 0 and None values.

Brier decomposition over the same bins (Murphy 1973, with the two within-bin terms of Stephenson et al. 2008):
  BS  = (1/N) Σ_i (p_i - y_i)^2
  REL = (1/N) Σ_k n_k (p̄_k - ō_k)^2        RES = (1/N) Σ_k n_k (ō_k - ō)^2        UNC = ō (1 - ō)
  WBV = (1/N) Σ_k Σ_{i∈k} (p_i - p̄_k)^2     WBC = (1/N) Σ_k Σ_{i∈k} (p_i - p̄_k)(y_i - ō_k)
  BS  = REL - RES + UNC + (WBV - 2 WBC)      exactly; WBV - 2 WBC = 0 when forecasts within each bin are equal.

Display rules follow the evaluator: n < 5 events -> INSUFFICIENT DATA with no table; 5 <= n < 30 -> small-sample
caveat. Real-historical and synthetic events are never pooled (mixed input raises, as in ``build_scorecard``).

A ``Scorecard`` stores per-event Brier scores, not forecasts. For an event with ONE snapshot the forecast is
recovered exactly from b = (p - y)^2: p = sqrt(b) if y = 0, p = 1 - sqrt(b) if y = 1, rounded to 12 decimals so
float noise cannot move a forecast that sits on a bin edge (e.g. a market price of 0.60) into the wrong bin.
An event averaged over several snapshots has no single recoverable forecast; it is excluded and listed.
"""

from __future__ import annotations

import math
from bisect import bisect_right
from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict, StrictInt, field_validator

from core.evaluator import (
    CONFIDENCE,
    INSUFFICIENT_DATA,
    LABEL_INSUFFICIENT,
    MIN_EVENTS,
    SMALL_SAMPLE_EVENTS,
    CaseSet,
    Scorecard,
)
from models import Provenance

DEFAULT_BINS = 5
WILSON_Z = 1.96  # two-sided 95%; matches CONFIDENCE
MIN_BIN_COUNT = 3  # bins with fewer forecasts are flagged "too few to read"
RECOVERY_DECIMALS = 12
SOURCE = "Computed from the scorecard's per-event scores"
DESCRIPTIVE = "Descriptive only: calibration does not compare forecasters"
NOTE_TOO_FEW = "too few to read"
NOTE_EMPTY = "empty"
EDGE_RULE = "bin k = [k/K, (k+1)/K) for k < K-1; last bin [(K-1)/K, 1] includes p = 1"
SCORED_PROVENANCES = (Provenance.REAL_HISTORICAL, Provenance.SYNTHETIC)

ExclusionReason = Literal["multiple_snapshots_forecast_not_recoverable"]


class EventForecast(BaseModel):
    """One scored event: its outcome and each forecaster's probability of YES."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str
    y: StrictInt
    p: dict[str, float]
    provenance: Provenance

    @field_validator("y")
    @classmethod
    def _y01(cls, y: int) -> int:
        if y not in (0, 1):
            raise ValueError(f"outcome {y!r} not in {{0, 1}}")
        return y

    @field_validator("p")
    @classmethod
    def _probs(cls, p: dict[str, float]) -> dict[str, float]:
        if not p:
            raise ValueError("at least one forecaster is required")
        for name, v in p.items():
            if not math.isfinite(v) or v < 0.0 or v > 1.0:
                raise ValueError(f"forecast {name}={v!r} outside [0, 1]")
        return p


class ReliabilityBin(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    index: int
    lower: float
    upper: float
    upper_inclusive: bool
    count: int
    n_yes: int
    mean_forecast: float | None
    observed_frequency: float | None
    wilson_low: float | None
    wilson_high: float | None
    too_few_to_read: bool  # count < MIN_BIN_COUNT (empty bins included)
    note: str | None  # "too few to read", "empty", or None


class BrierDecomposition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    brier_score: float
    reliability: float
    resolution: float
    uncertainty: float
    base_rate: float
    within_bin_variance: float  # WBV
    within_bin_covariance: float  # WBC
    within_bin: float  # WBV - 2 WBC = BS - (REL - RES + UNC)


class ForecasterCalibration(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    forecaster: str
    n_events: int
    bins: list[ReliabilityBin]
    decomposition: BrierDecomposition


class CalibrationExclusion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str
    reason: ExclusionReason


class CalibrationReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    label: str
    verdict: str  # INSUFFICIENT_DATA or DESCRIPTIVE
    caveat: str | None
    source: str = SOURCE
    provenance: Provenance | None  # of the outcomes; None when there are no events
    scorecard_label: str | None = None
    market_label: str | None = None
    case_set: CaseSet | None = None
    n_events: int  # events used
    n_scored_events: int  # events in the input (used + excluded)
    n_bins: int
    bin_edge_rule: str = EDGE_RULE
    confidence: float = CONFIDENCE
    z: float = WILSON_Z
    min_bin_count: int = MIN_BIN_COUNT
    forecasters: list[str]
    calibration: dict[str, ForecasterCalibration] | None  # None when INSUFFICIENT DATA
    excluded: list[CalibrationExclusion] = []


# ---------------------------------------------------------------- primitives


def wilson_interval(k: int, n: int, z: float = WILSON_Z) -> tuple[float, float]:
    """Wilson score interval for k successes in n trials, clamped to [0, 1]."""
    if isinstance(k, bool) or isinstance(n, bool) or not isinstance(k, int) or not isinstance(n, int):
        raise TypeError("k and n must be ints")
    if n < 1 or k < 0 or k > n:
        raise ValueError(f"need 0 <= k <= n and n >= 1, got k={k}, n={n}")
    ph = k / n
    z2 = z * z
    denom = 1.0 + z2 / n
    centre = (ph + z2 / (2 * n)) / denom
    half = (z / denom) * math.sqrt(ph * (1.0 - ph) / n + z2 / (4 * n * n))
    lo = 0.0 if k == 0 else max(0.0, centre - half)
    hi = 1.0 if k == n else min(1.0, centre + half)
    return lo, hi


def bin_index(p: float, n_bins: int) -> int:
    """Left-closed equal-width bins on [0, 1]; p = 1 goes to the last bin."""
    edges = [i / n_bins for i in range(n_bins + 1)]
    return min(bisect_right(edges, p) - 1, n_bins - 1)


def forecast_from_brier(b: float, y: int) -> float:
    """Invert b = (p - y)^2 for one snapshot: p = sqrt(b) if y = 0, else 1 - sqrt(b) (rounded to 12 decimals)."""
    if isinstance(y, bool) or y not in (0, 1):
        raise ValueError(f"outcome {y!r} not in {{0, 1}}")
    if not math.isfinite(b) or b < 0.0 or b > 1.0:
        raise ValueError(f"Brier score {b!r} outside [0, 1]")
    r = math.sqrt(b)
    p = r if y == 0 else 1.0 - r
    return min(1.0, max(0.0, round(p, RECOVERY_DECIMALS)))


def _forecaster(name: str, pairs: list[tuple[float, int]], n_bins: int) -> ForecasterCalibration:
    n = len(pairs)
    members: list[list[tuple[float, int]]] = [[] for _ in range(n_bins)]
    for p, y in pairs:
        members[bin_index(p, n_bins)].append((p, y))
    base = sum(y for _, y in pairs) / n
    bins: list[ReliabilityBin] = []
    rel_terms: list[float] = []
    res_terms: list[float] = []
    wbv_terms: list[float] = []
    wbc_terms: list[float] = []
    for k, rows in enumerate(members):
        nk = len(rows)
        lower, upper = k / n_bins, (k + 1) / n_bins
        if nk == 0:
            bins.append(
                ReliabilityBin(
                    index=k, lower=lower, upper=upper, upper_inclusive=k == n_bins - 1, count=0, n_yes=0,
                    mean_forecast=None, observed_frequency=None, wilson_low=None, wilson_high=None,
                    too_few_to_read=True, note=NOTE_EMPTY,
                )
            )
            continue
        yes = sum(y for _, y in rows)
        pbar = math.fsum(p for p, _ in rows) / nk
        obar = yes / nk
        lo, hi = wilson_interval(yes, nk)
        few = nk < MIN_BIN_COUNT
        bins.append(
            ReliabilityBin(
                index=k, lower=lower, upper=upper, upper_inclusive=k == n_bins - 1, count=nk, n_yes=yes,
                mean_forecast=pbar, observed_frequency=obar, wilson_low=lo, wilson_high=hi,
                too_few_to_read=few, note=NOTE_TOO_FEW if few else None,
            )
        )
        rel_terms.append(nk * (pbar - obar) ** 2)
        res_terms.append(nk * (obar - base) ** 2)
        wbv_terms.extend((p - pbar) ** 2 for p, _ in rows)
        wbc_terms.extend((p - pbar) * (y - obar) for p, y in rows)
    wbv = math.fsum(wbv_terms) / n
    wbc = math.fsum(wbc_terms) / n
    return ForecasterCalibration(
        forecaster=name,
        n_events=n,
        bins=bins,
        decomposition=BrierDecomposition(
            brier_score=math.fsum((p - y) ** 2 for p, y in pairs) / n,
            reliability=math.fsum(rel_terms) / n,
            resolution=math.fsum(res_terms) / n,
            uncertainty=base * (1.0 - base),
            base_rate=base,
            within_bin_variance=wbv,
            within_bin_covariance=wbc,
            within_bin=wbv - 2.0 * wbc,
        ),
    )


# ---------------------------------------------------------------- reports


def _report(
    events: Sequence[EventForecast],
    *,
    n_bins: int,
    excluded: Sequence[CalibrationExclusion] = (),
    provenance: Provenance | None = None,
    forecasters: Sequence[str] | None = None,
    **meta,
) -> CalibrationReport:
    if isinstance(n_bins, bool) or not isinstance(n_bins, int) or n_bins < 1:
        raise ValueError(f"n_bins must be a positive int, got {n_bins!r}")
    provs = {e.provenance for e in events}
    if len(provs) > 1:
        raise ValueError("synthetic and real historical events must be calibrated separately; got a mixed set")
    if provs:
        provenance = provs.pop()
    if provenance is not None and provenance not in SCORED_PROVENANCES:
        raise ValueError(f"calibration needs scored outcomes (REAL_HISTORICAL or SYNTHETIC), got {provenance.value}")
    ids = [e.event_id for e in events]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate event_id in calibration input")
    names = sorted(events[0].p) if events else sorted(forecasters or [])
    if any(sorted(e.p) != names for e in events):
        raise ValueError("every event must carry the same forecasters (paired comparison)")

    n = len(events)
    n_scored = n + len(excluded)
    common = dict(
        provenance=provenance,
        n_events=n,
        n_scored_events=n_scored,
        n_bins=n_bins,
        forecasters=names,
        excluded=sorted(excluded, key=lambda x: x.event_id),
        **meta,
    )
    if n < MIN_EVENTS:
        return CalibrationReport(
            label=LABEL_INSUFFICIENT, verdict=INSUFFICIENT_DATA, caveat=None, calibration=None, **common
        )
    count = f"n = {n} events" if not excluded else f"n = {n} of {n_scored} scored events"
    return CalibrationReport(
        label=f"{provenance.label}: {SOURCE} ({count})",  # type: ignore[union-attr]
        verdict=DESCRIPTIVE,
        caveat=None
        if n >= SMALL_SAMPLE_EVENTS
        else f"small sample: n = {n} events (< {SMALL_SAMPLE_EVENTS}); read each bin with its Wilson interval",
        calibration={f: _forecaster(f, [(e.p[f], e.y) for e in events], n_bins) for f in names},
        **common,
    )


def calibrate(events: Sequence[EventForecast], *, n_bins: int = DEFAULT_BINS) -> CalibrationReport:
    """Reliability bins and Brier decomposition per forecaster for one set of scored events (not pooled)."""
    return _report(list(events), n_bins=n_bins)


def calibration_from_scorecard(card: Scorecard, *, n_bins: int = DEFAULT_BINS) -> CalibrationReport:
    """Calibration of every forecaster in ``card.forecasters`` from the card's per-event scores.

    Single-snapshot events: forecast recovered exactly from the per-event Brier score. Multi-snapshot events are
    excluded (reason ``multiple_snapshots_forecast_not_recoverable``) and counted in the label.
    """
    if card.per_event and card.provenance is None:
        raise ValueError("scorecard has scored events but no provenance")
    if card.provenance is not None and card.case_set is not None:
        expected = Provenance.REAL_HISTORICAL if card.case_set == "real" else Provenance.SYNTHETIC
        if card.provenance != expected:
            raise ValueError(f"scorecard case_set {card.case_set!r} disagrees with provenance {card.provenance.value}")
    events: list[EventForecast] = []
    excluded: list[CalibrationExclusion] = []
    for e in card.per_event:
        if e.n_snapshots != 1:
            reason: ExclusionReason = "multiple_snapshots_forecast_not_recoverable"
            excluded.append(CalibrationExclusion(event_id=e.event_id, reason=reason))
            continue
        if set(e.brier) != set(card.forecasters):
            raise ValueError(f"{e.event_id}: per-event scores do not match the card's forecasters")
        events.append(
            EventForecast(
                event_id=e.event_id,
                y=e.y,
                p={f: forecast_from_brier(e.brier[f], e.y) for f in card.forecasters},
                provenance=card.provenance,  # type: ignore[arg-type]
            )
        )
    return _report(
        events,
        n_bins=n_bins,
        excluded=excluded,
        provenance=card.provenance,
        forecasters=card.forecasters,
        scorecard_label=card.label,
        market_label=card.market_label,
        case_set=card.case_set,
    )
