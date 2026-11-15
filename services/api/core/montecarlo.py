"""Monte Carlo engines (docs/MATH_MODEL.md §11, issue #208).

Two engines, both seeded and vectorised with numpy:

1. ``run_decision``: a generic decision Monte Carlo. Each option's metric on a path is the sum of its drivers
   (§11.1). Same-named drivers share their uniform draws across options (common random numbers), so option
   comparisons are paired.
2. ``run_cash``: the §3 cash recurrence on the SYNTHETIC demo business, re-run on many paths whose shock sizes are
   drawn around a central scenario (§11.2). With zero uncertainty every path equals ``core.financials.simulate()``.

That document is the contract: if a formula here and there disagree, the document wins and this file is the bug.

Rules: the only randomness is ``numpy.random.Generator`` seeded from the request (same input + seed -> same output);
no I/O, no LLM calls. ``runtime_ms`` is measured here with ``time.perf_counter`` and is metadata only: it never
feeds a result. LLMs supply the inputs (assumptions); every number in a response is computed here.
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from typing import Annotated, Any, Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator
from scipy.special import ndtri

from core.financials import (
    FINANCING_TOL,
    ActionPlan,
    BusinessParams,
    ScenarioShock,
    _expand,
    demand_multipliers,
    lost_sales_fractions,
    rate_path,
)
from core.optimizer import OPTIMAL, ChosenAction, OptimizationResult

DEFAULT_SEED = 20261115
Z95 = 1.959963984540054  # Φ^{-1}(0.975)
Z90 = 1.2815515655446004  # Φ^{-1}(0.90), used to fit the lognormal from its P90
QUANTILES = (0.05, 0.25, 0.50, 0.75, 0.95)
HIST_BINS = 40
MAX_ABS_PARAM = 1e12  # |parameter| cap so sums of 8 drivers stay far from float overflow
_U_EPS = 1e-12  # uniforms are clipped to [eps, 1 - eps] so normal/lognormal inverse CDFs stay finite

DECISION_LABEL = (
    "Monte Carlo computed by FAULTLINE; inputs are model-estimated assumptions (cited where a source is shown)"
)
CASH_LABEL = "Monte Carlo on the SYNTHETIC demo business; uncertainty ranges are ILLUSTRATIVE assumptions"


# --------------------------------------------------------------------------- shared helpers


def canonical_sha256(payload: Any) -> str:
    """sha256 of the canonical JSON of a validated request: defaults filled in, keys sorted, no whitespace."""
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _stream(seed: int, name: str) -> np.random.Generator:
    """One independent random stream per (seed, name): the draws for a name never depend on the other names."""
    tag = int.from_bytes(hashlib.sha256(name.encode("utf-8")).digest()[:8], "big")
    return np.random.default_rng(np.random.SeedSequence([seed, tag]))


def _uniform(rng: np.random.Generator, size: int | tuple[int, ...]) -> np.ndarray:
    return np.clip(rng.random(size), _U_EPS, 1.0 - _U_EPS)


def triangular_ppf(u: np.ndarray, low: float, mode: float, high: float) -> np.ndarray:
    """Inverse CDF of Triangular(low, mode, high); a point mass when low == high."""
    if high <= low:
        return np.full_like(u, low, dtype=float)
    span = high - low
    fc = (mode - low) / span
    left = low + np.sqrt(u * span * (mode - low))
    right = high - np.sqrt((1.0 - u) * span * (high - mode))
    return np.where(u < fc, left, right)


def wilson(p_hat: float, n: int, z: float = Z95) -> tuple[float, float]:
    """Wilson score interval for a proportion p_hat observed on n trials (§11.1)."""
    if n <= 0:
        raise ValueError("wilson: n must be positive")
    z2n = z * z / n
    denom = 1.0 + z2n
    centre = (p_hat + z2n / 2.0) / denom
    half = z / denom * math.sqrt(max(p_hat * (1.0 - p_hat) / n + z2n / (4.0 * n), 0.0))
    lo = 0.0 if p_hat <= 0.0 else max(0.0, centre - half)  # exact algebraic limits at p_hat = 0 and 1
    hi = 1.0 if p_hat >= 1.0 else min(1.0, centre + half)
    return lo, hi


def _quantiles(x: np.ndarray, axis: int | None = None) -> dict[str, Any]:
    q = np.quantile(x, QUANTILES, axis=axis)
    keys = ("p5", "p25", "p50", "p75", "p95")
    if axis is None:
        return {k: float(v) for k, v in zip(keys, q, strict=True)}
    return {k: [float(v) for v in row] for k, row in zip(keys, q, strict=True)}


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


Probability = Annotated[float, Field(ge=0.0, le=1.0)]
CI = tuple[float, float]


# --------------------------------------------------------------------------- 1. decision Monte Carlo: request

_PARAM_KEYS: dict[str, tuple[str, ...]] = {
    "triangular": ("low", "mode", "high"),
    "normal": ("mean", "sd"),
    "lognormal": ("median", "p90"),
    "uniform": ("low", "high"),
}


class Source(_Model):
    url: Annotated[str, Field(max_length=2000, pattern=r"^https?://\S+$")] | None = None
    title: Annotated[str, Field(max_length=300)] | None = None
    note: Annotated[str, Field(max_length=1000)] | None = None


class Driver(_Model):
    name: Annotated[str, Field(min_length=1, max_length=100)]
    kind: Literal["value", "event"]
    distribution: Literal["triangular", "normal", "lognormal", "uniform"]
    params: dict[str, float]
    probability: Probability | None = None
    source: Source | None = None

    @model_validator(mode="after")
    def _check(self) -> Driver:
        want = _PARAM_KEYS[self.distribution]
        got = set(self.params)
        if got != set(want):
            raise ValueError(
                f"driver '{self.name}': {self.distribution} needs params exactly {{{', '.join(want)}}}, "
                f"got {{{', '.join(sorted(got))}}}"
            )
        p = self.params
        for k, v in p.items():
            if not math.isfinite(v):
                raise ValueError(f"driver '{self.name}': params.{k} must be a finite number")
            if abs(v) > MAX_ABS_PARAM:
                raise ValueError(f"driver '{self.name}': |params.{k}| must be <= {MAX_ABS_PARAM:g}")
        d = self.distribution
        if d == "triangular" and not (p["low"] <= p["mode"] <= p["high"]):
            raise ValueError(f"driver '{self.name}': triangular needs low <= mode <= high")
        if d == "normal" and not p["sd"] > 0:
            raise ValueError(f"driver '{self.name}': normal needs sd > 0")
        if d == "lognormal" and not (0 < p["median"] < p["p90"]):
            raise ValueError(f"driver '{self.name}': lognormal needs 0 < median < p90")
        if d == "uniform" and not p["low"] <= p["high"]:
            raise ValueError(f"driver '{self.name}': uniform needs low <= high")
        if self.kind == "event" and self.probability is None:
            raise ValueError(f"driver '{self.name}': an event driver needs a probability in [0, 1]")
        if self.kind == "value" and self.probability is not None:
            raise ValueError(f"driver '{self.name}': a value driver must have probability null")
        return self

    def ppf(self, u: np.ndarray) -> np.ndarray:
        """Inverse CDF of the driver's distribution (metric units)."""
        p = self.params
        if self.distribution == "triangular":
            return triangular_ppf(u, p["low"], p["mode"], p["high"])
        if self.distribution == "normal":
            return p["mean"] + p["sd"] * ndtri(u)
        if self.distribution == "lognormal":
            mu = math.log(p["median"])
            sigma = (math.log(p["p90"]) - mu) / Z90
            return np.exp(mu + sigma * ndtri(u))
        return p["low"] + (p["high"] - p["low"]) * u  # uniform


class Option(_Model):
    id: Annotated[str, Field(min_length=1, max_length=64)]
    label: Annotated[str, Field(min_length=1, max_length=200)]
    drivers: Annotated[list[Driver], Field(min_length=1, max_length=8)]

    @model_validator(mode="after")
    def _unique_drivers(self) -> Option:
        names = [d.name for d in self.drivers]
        if len(names) != len(set(names)):
            raise ValueError(f"option '{self.id}': driver names must be unique within an option")
        return self


class Metric(_Model):
    name: Annotated[str, Field(min_length=1, max_length=100)]
    unit: Annotated[str, Field(max_length=40)]
    higher_is_better: bool


class DecisionRequest(_Model):
    question: Annotated[str, Field(min_length=1, max_length=500)]
    metric: Metric
    options: Annotated[list[Option], Field(min_length=2, max_length=4)]
    n_paths: Annotated[int, Field(ge=1000, le=100_000)] = 20_000
    seed: Annotated[int, Field(ge=0, le=2**63 - 1)] = DEFAULT_SEED

    @model_validator(mode="after")
    def _unique_options(self) -> DecisionRequest:
        ids = [o.id for o in self.options]
        if len(ids) != len(set(ids)):
            raise ValueError("option ids must be unique")
        return self


# --------------------------------------------------------------------------- 1. decision Monte Carlo: response


class Histogram(_Model):
    bin_edges: list[float]  # HIST_BINS + 1 edges, shared by every option
    counts: list[int]  # HIST_BINS counts


class OptionStats(_Model):
    id: str
    label: str
    mean: float
    sd: float
    p5: float
    p25: float
    p50: float
    p75: float
    p95: float
    prob_below_zero: float
    histogram: Histogram


class Pairwise(_Model):
    a: str
    b: str
    prob_a_better: float
    ci95: CI


class Best(_Model):
    id: str
    prob_best: float
    ci95: CI


class Sensitivity(_Model):
    option_id: str
    driver: str
    low_p50: float
    high_p50: float
    swing: float


class AssumptionEcho(_Model):
    option_id: str
    name: str
    kind: str
    distribution: str
    params: dict[str, float]
    probability: float | None
    source: Source | None


class DecisionResponse(_Model):
    provenance: Literal["SIMULATED"] = "SIMULATED"
    label: str = DECISION_LABEL
    question: str
    metric: Metric
    n_paths: int
    seed: int
    input_sha256: str
    runtime_ms: float
    options: list[OptionStats]
    pairwise: list[Pairwise]
    best: Best
    sensitivity: list[Sensitivity]
    assumptions: list[AssumptionEcho]


# --------------------------------------------------------------------------- 1. decision Monte Carlo: engine


def driver_samples(req: DecisionRequest) -> list[np.ndarray]:
    """Per option, an (n_drivers, n_paths) array of each driver's contribution (§11.1).

    value driver: x = F^{-1}(U).  event driver: x = 1[V < p] · F^{-1}(U).
    U and V come from the stream named after the driver, so same-named drivers share them across options.
    """
    n = req.n_paths
    draws: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    out = []
    for opt in req.options:
        rows = []
        for d in opt.drivers:
            if d.name not in draws:
                rng = _stream(req.seed, "driver:" + d.name)
                draws[d.name] = (_uniform(rng, n), _uniform(rng, n))
            u, v = draws[d.name]
            x = d.ppf(u)
            if d.kind == "event":
                x = np.where(v < d.probability, x, 0.0)
            rows.append(x)
        out.append(np.vstack(rows))
    return out


def _better(a: np.ndarray, b: np.ndarray, higher_is_better: bool) -> np.ndarray:
    """Per path: 1 if a beats b, 0.5 on an exact tie, 0 otherwise (§11.1)."""
    win = (a > b) if higher_is_better else (a < b)
    return win + 0.5 * (a == b)


def run_decision(req: DecisionRequest) -> DecisionResponse:
    start = time.perf_counter()
    n = req.n_paths
    hib = req.metric.higher_is_better
    contrib = driver_samples(req)
    totals = np.vstack([c.sum(axis=0) for c in contrib])  # (n_options, n_paths)
    if not np.all(np.isfinite(totals)):
        raise ValueError("the drivers produced a non-finite metric value; use smaller magnitudes")

    lo, hi = float(totals.min()), float(totals.max())
    if hi <= lo:
        lo, hi = lo - 0.5, hi + 0.5
    edges = np.linspace(lo, hi, HIST_BINS + 1)

    options = []
    for opt, x in zip(req.options, totals, strict=True):
        counts, _ = np.histogram(x, bins=edges)
        options.append(OptionStats(
            id=opt.id, label=opt.label, mean=float(x.mean()), sd=float(x.std(ddof=1)), **_quantiles(x),
            prob_below_zero=float(np.mean(x < 0.0)),
            histogram=Histogram(bin_edges=[float(e) for e in edges], counts=[int(c) for c in counts]),
        ))

    pairwise = []
    k = len(req.options)
    for i in range(k):
        for j in range(i + 1, k):
            p = float(_better(totals[i], totals[j], hib).mean())
            pairwise.append(Pairwise(a=req.options[i].id, b=req.options[j].id, prob_a_better=p, ci95=wilson(p, n)))

    # Best per path; an exact tie between m options gives each 1/m of that path.
    extreme = totals.max(axis=0) if hib else totals.min(axis=0)
    is_best = totals == extreme
    share = is_best / is_best.sum(axis=0)
    prob_best = share.mean(axis=1)
    b = int(np.argmax(prob_best))  # first option wins an exact tie in prob_best
    best = Best(id=req.options[b].id, prob_best=float(prob_best[b]), ci95=wilson(float(prob_best[b]), n))

    sens = []
    for opt, c, x in zip(req.options, contrib, totals, strict=True):
        for d, xd in zip(opt.drivers, c, strict=True):
            q10, q90 = np.quantile(xd, [0.10, 0.90])
            rest = x - xd
            low_p50 = float(np.median(rest + q10))
            high_p50 = float(np.median(rest + q90))
            sens.append(Sensitivity(option_id=opt.id, driver=d.name, low_p50=low_p50, high_p50=high_p50,
                                    swing=abs(high_p50 - low_p50)))
    sens.sort(key=lambda s: -s.swing)  # stable: ties keep option, then driver order

    assumptions = [
        AssumptionEcho(option_id=opt.id, name=d.name, kind=d.kind, distribution=d.distribution, params=d.params,
                       probability=d.probability, source=d.source)
        for opt in req.options for d in opt.drivers
    ]
    return DecisionResponse(
        question=req.question, metric=req.metric, n_paths=n, seed=req.seed,
        input_sha256=canonical_sha256(req.model_dump(mode="json")),
        runtime_ms=(time.perf_counter() - start) * 1000.0,
        options=options, pairwise=pairwise, best=best, sensitivity=sens, assumptions=assumptions,
    )


# --------------------------------------------------------------------------- 2. cash Monte Carlo


class CashUncertainty(_Model):
    """§11.2 spreads (ILLUSTRATIVE, for review by the finance owner). Not part of the HTTP request."""

    demand_drop_spread: Annotated[float, Field(ge=0.0, le=1.0)] = 0.5  # δ' ~ Tri(δ(1-s), δ, min(1, δ(1+s)))
    demand_duration_spread: Annotated[float, Field(ge=0.0, le=1.0)] = 0.5  # D' ~ round Tri(D(1-s), D, D(1+s))
    rate_move_spread: Annotated[float, Field(ge=0.0, le=1.0)] = 0.5  # Δr' ~ Tri(Δr(1-s), Δr, Δr(1+s))
    outage_weeks_spread: Annotated[float, Field(ge=0.0, le=1.0)] = 0.5  # L' ~ round Tri(L(1-s), L, L(1+s))
    weekly_demand_noise_sd: Annotated[float, Field(ge=0.0, le=0.5)] = 0.05  # ε_t ~ N(1, sd), clipped at 0


class Assumption(_Model):
    name: str
    distribution: str
    params: dict[str, float]
    provenance: Literal["ILLUSTRATIVE"] = "ILLUSTRATIVE"


class Bands(_Model):
    p5: list[float]
    p25: list[float]
    p50: list[float]
    p75: list[float]
    p95: list[float]


class MinCash(_Model):
    p5: float
    p50: float
    p95: float


class CashSummary(_Model):
    bands: Bands
    prob_below_floor_any: float
    prob_below_floor_ci95: CI
    prob_negative_any: float
    prob_below_floor_by_week: list[float]
    min_cash: MinCash


class PlanSummary(_Model):
    status: str
    actions: list[ChosenAction] | None
    central_min_cash: float | None  # min_t C_t of the plan on the central scenario (the optimizer's own number)
    diagnostic: str | None


class CashResponse(_Model):
    provenance: Literal["SIMULATED"] = "SIMULATED"
    synthetic: Literal[True] = True
    label: str = CASH_LABEL
    scenario_id: str | None
    n_paths: int
    seed: int
    input_sha256: str
    runtime_ms: float
    weeks: int
    floor: float
    no_plan: CashSummary
    with_plan: CashSummary | None
    plan: PlanSummary | None
    assumptions: list[Assumption]
    notes: list[str]


class CashDraws(BaseModel):
    """Exogenous paths, shape (n_paths, T): demand multiplier m, weekly noise ε, rate r, availability κ."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    m: Any
    eps: Any
    r: Any
    kappa: Any
    dependent_share: float
    assumptions: list[Assumption]


def _tri_spread(central: float, spread: float, cap_high: float | None = None) -> tuple[float, float, float]:
    a, b = central * (1.0 - spread), central * (1.0 + spread)
    low, high = min(a, b), max(a, b)
    if cap_high is not None:
        high = min(high, cap_high)
    return low, central, high


def sample_cash_draws(
    params: BusinessParams, shock: ScenarioShock, n: int, seed: int, unc: CashUncertainty
) -> CashDraws:
    """Draw the §11.2 shock paths. With every spread and the noise at 0, each row equals the central §1 paths."""
    T = params.horizon_weeks
    t = np.arange(1, T + 1, dtype=float)
    assumptions: list[Assumption] = []

    # Demand: drop size δ' and duration D' (weeks) around the central shock; start week and recovery ρ fixed.
    if shock.demand is not None:
        dem = shock.demand
        d_lo, d_mode, d_hi = _tri_spread(dem.delta, unc.demand_drop_spread, cap_high=1.0)
        D = dem.end_week - dem.start_week + 1
        w_lo, w_mode, w_hi = _tri_spread(float(D), unc.demand_duration_spread)
        rng = _stream(seed, "cash:demand")
        delta = triangular_ppf(_uniform(rng, n), d_lo, d_mode, d_hi)[:, None]
        dur = np.maximum(1.0, np.rint(triangular_ppf(_uniform(rng, n), w_lo, w_mode, w_hi)))[:, None]
        t1, rho = float(dem.start_week), float(dem.recovery_weeks)
        t2 = t1 + dur - 1.0
        in_win = (t >= t1) & (t <= t2)
        if rho > 0:
            rec = (t > t2) & (t <= t2 + rho)
            m = np.where(in_win, 1.0 - delta, np.where(rec, 1.0 - delta * (1.0 - (t - t2) / rho), 1.0))
        else:
            m = np.where(in_win, 1.0 - delta, 1.0)
        assumptions += [
            Assumption(name="demand_drop_size", distribution="triangular",
                       params={"low": d_lo, "mode": d_mode, "high": d_hi}),
            Assumption(name="demand_drop_duration_weeks", distribution="triangular, rounded to whole weeks (min 1)",
                       params={"low": w_lo, "mode": w_mode, "high": w_hi}),
        ]
    else:
        m = np.broadcast_to(np.array(demand_multipliers(None, T)), (n, T))

    # Weekly demand noise on base-store demand (not on the service level, which follows planned demand m_t).
    rng = _stream(seed, "cash:weekly_noise")
    eps = np.maximum(0.0, 1.0 + unc.weekly_demand_noise_sd * rng.standard_normal((n, T)))
    assumptions.append(Assumption(name="weekly_demand_noise", distribution="normal (multiplier, clipped at 0)",
                                  params={"mean": 1.0, "sd": unc.weekly_demand_noise_sd}))

    # Rate: move Δr' around the central move; start week fixed.
    base_r = np.array(rate_path(params, None))
    if shock.rate is not None:
        r_lo, r_mode, r_hi = _tri_spread(shock.rate.delta_rate, unc.rate_move_spread)
        rng = _stream(seed, "cash:rate")
        dr = triangular_ppf(_uniform(rng, n), r_lo, r_mode, r_hi)[:, None]
        r = base_r + np.where(t >= shock.rate.start_week, dr, 0.0)
        assumptions.append(Assumption(name="rate_move_annual", distribution="triangular",
                                      params={"low": r_lo, "mode": r_mode, "high": r_hi}))
    else:
        r = np.broadcast_to(base_r, (n, T))

    # Supplier outage: span L = last - first outage week + 1; L' weeks from the first outage week.
    kappa_c, _ = lost_sales_fractions(shock.supplier, T)
    kc = np.array(kappa_c)
    out_weeks = np.flatnonzero(kc < 1.0)
    phi = shock.supplier.dependent_share if shock.supplier is not None else 0.0
    if out_weeks.size:
        first, last = int(out_weeks[0]), int(out_weeks[-1])  # 0-based indices
        L = last - first + 1
        o_lo, o_mode, o_hi = _tri_spread(float(L), unc.outage_weeks_spread)
        rng = _stream(seed, "cash:outage")
        Lp = np.maximum(1.0, np.rint(triangular_ppf(_uniform(rng, n), o_lo, o_mode, o_hi)))[:, None]
        idx = np.arange(T)
        # weeks first..last keep their central κ; weeks past `last` (when L' > L) take κ_last; past first+L'-1 -> 1
        extended = np.where(idx <= last, kc, kc[last])
        kappa = np.where((idx >= first) & (idx < first + Lp), extended, np.where(idx < first, kc, 1.0))
        assumptions.append(Assumption(name="supplier_outage_weeks",
                                      distribution="triangular, rounded to whole weeks (min 1)",
                                      params={"low": o_lo, "mode": o_mode, "high": o_hi}))
    else:
        kappa = np.broadcast_to(kc, (n, T))

    return CashDraws(m=np.asarray(m, float), eps=eps, r=np.asarray(r, float), kappa=np.asarray(kappa, float),
                     dependent_share=phi, assumptions=assumptions)


def cash_paths(params: BusinessParams, draws: CashDraws, plan: ActionPlan) -> tuple[np.ndarray, int]:
    """The §3 boxed recurrence for every path at once; same operations, in the same order, as simulate().

    Returns (C, capped): C has shape (n_paths, T). `capped` counts paths where a physical cap bound (§11.2):
    stock-out lost sales limited to the week's sales (S_t >= 0) or purchases floored at 0 (P_t >= 0).
    """
    T = params.horizon_weeks
    n = draws.m.shape[0]
    g, a, Lp = params.gross_margin, params.same_week_collection, params.supplier_lag_weeks
    xb, xc, xe = float(plan.use_backup_supplier), float(plan.defer_capex), float(plan.delay_expansion)

    base_sales = [0.0] * T
    for store in params.stores:
        for i, s in enumerate(_expand(f"stores[{store.name}].base_sales", store.base_sales, T)):
            base_sales[i] += s
    W = _expand("payroll", params.payroll, T)
    opex = _expand("opex", params.opex, T)
    K = _expand("capex", params.capex, T)
    E = _expand("expansion_outflow", params.expansion_outflow, T)
    X = _expand("expansion_sales", params.expansion_sales, T)
    A = _expand("amortization", params.amortization, T)
    v = _expand("purchase_cut", plan.purchase_cut, T)
    y = _expand("revolver_draw", plan.revolver_draw, T)
    q = _expand("revolver_repay", plan.revolver_repay, T)
    z = _expand("payroll_cut", plan.payroll_cut, T)
    lam = draws.dependent_share * (1.0 - draws.kappa)  # λ_t = φ (1 - κ_t)

    capped = np.zeros(n, dtype=bool)
    purchases: list[np.ndarray] = []
    S_prev = np.full(n, params.sales_0)
    C_prev = np.full(n, params.cash_0)
    inv_prev, B_prev, D = params.inventory_0, params.revolver_balance_0, params.term_loan_principal_1
    C = np.empty((n, T))
    for i in range(T):
        t = i + 1
        m_i = draws.m[:, i]
        S_core = m_i * draws.eps[:, i] * base_sales[i]
        inv = inv_prev - v[i]  # plan-only: identical on every path
        svc = params.service_level_share * params.inventory_0 * m_i
        short = np.maximum(0.0, svc - inv)
        lost_stockout = params.stockout_lost_sales_rate * short
        S = S_core * (1.0 - lam[:, i] * (1.0 - xb)) + (1.0 - xe) * X[i] - lost_stockout
        neg_s = S < 0.0
        S = np.where(neg_s, 0.0, S)
        R = a * S + (1.0 - a) * S_prev
        premium = params.backup_premium * (1.0 - g) * S_core * lam[:, i] * xb
        P = (1.0 - g) * S - v[i] + premium
        neg_p = P < 0.0
        P = np.where(neg_p, 0.0, P)
        capped |= neg_s | neg_p
        purchases.append(P)
        k = t - Lp
        paid = purchases[k - 1] if k >= 1 else params.prior_purchases[t - 1]
        r_i = draws.r[:, i]
        J = D * r_i / 52.0
        JR = B_prev * (r_i + params.revolver_spread) / 52.0
        B = B_prev + y[i] - q[i]
        payroll_paid = (1.0 - z[i]) * W[i]
        capex_paid = (1.0 - xc) * K[i]
        expansion_paid = (1.0 - xe) * E[i]
        fee = params.backup_switch_fee * xb if t == 1 else 0.0
        C_t = (C_prev + R - paid - payroll_paid - opex[i] - J - A[i] - JR
               - capex_paid - expansion_paid - fee + y[i] - q[i])
        C[:, i] = C_t
        S_prev, inv_prev, B_prev, C_prev = S, inv, B, C_t
        D = D - A[i]
    return C, int(capped.sum())


def summarize_cash(C: np.ndarray, floor: float) -> CashSummary:
    n = C.shape[0]
    below = C < floor - FINANCING_TOL  # same "below the floor" test as POST /api/simulate
    p_any = float(below.any(axis=1).mean())
    mins = C.min(axis=1)
    mq = np.quantile(mins, [0.05, 0.50, 0.95])
    return CashSummary(
        bands=Bands(**_quantiles(C, axis=0)),
        prob_below_floor_any=p_any,
        prob_below_floor_ci95=wilson(p_any, n),
        prob_negative_any=float((C < 0.0).any(axis=1).mean()),
        prob_below_floor_by_week=[float(x) for x in below.mean(axis=0)],
        min_cash=MinCash(p5=float(mq[0]), p50=float(mq[1]), p95=float(mq[2])),
    )


def run_cash(
    params: BusinessParams,
    shock: ScenarioShock,
    *,
    scenario_id: str | None,
    n_paths: int,
    seed: int,
    input_sha256: str,
    plan_result: OptimizationResult | None,
    unc: CashUncertainty | None = None,
    started_at: float | None = None,
) -> CashResponse:
    """§11.2. `plan_result` is the optimizer's answer on the central shock (None when with_plan is false).

    The same draws are used for the no-plan and the with-plan runs, so the two are paired path by path.
    """
    start = time.perf_counter() if started_at is None else started_at
    unc = unc or CashUncertainty()
    if params.min_cash is None:
        raise ValueError("the business has no liquidity floor C_min (min_cash)")
    floor = params.min_cash
    draws = sample_cash_draws(params, shock, n_paths, seed, unc)
    C0, capped0 = cash_paths(params, draws, ActionPlan())
    no_plan = summarize_cash(C0, floor)
    notes = []
    if capped0:
        notes.append(f"no plan: {capped0} of {n_paths} paths hit a physical cap (sales or purchases floored at 0).")

    with_plan = plan = None
    if plan_result is not None:
        ok = plan_result.status == OPTIMAL and plan_result.plan is not None
        plan = PlanSummary(status=plan_result.status, actions=plan_result.actions if ok else None,
                           central_min_cash=plan_result.min_cash if ok else None,
                           diagnostic=plan_result.diagnostic or (None if ok else plan_result.solver_message))
        if ok:
            C1, capped1 = cash_paths(params, draws, plan_result.plan)
            with_plan = summarize_cash(C1, floor)
            if capped1:
                notes.append(
                    f"with plan: {capped1} of {n_paths} paths hit a physical cap (sales or purchases floored at 0)."
                )
    return CashResponse(
        scenario_id=scenario_id, n_paths=n_paths, seed=seed, input_sha256=input_sha256,
        runtime_ms=(time.perf_counter() - start) * 1000.0, weeks=params.horizon_weeks, floor=floor,
        no_plan=no_plan, with_plan=with_plan, plan=plan, assumptions=draws.assumptions, notes=notes,
    )
