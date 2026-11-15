"""Deterministic weekly cash-flow simulator for the SYNTHETIC demo business.

Implements docs/MATH_MODEL.md §1 (shocks), §2 (demand and sales), §3 (cash-flow recurrence and runway)
and §5 (cascade deltas) exactly. That document is the contract: if a formula here and there disagree,
the document wins and this file is the bug.

Rules: pure functions only. No I/O, no randomness, no LLM calls, no clock. Dollars are plain floats and
are never rounded here (round only for display). Week arrays are 0-indexed lists where index ``t-1``
holds week ``t`` (t = 1..T). Pre-horizon values (S_0, P_{1-L_p}..P_0, I_0, B_0, C_0, D_1) are explicit
required inputs, never implicit zeros.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# --------------------------------------------------------------------------- input types

NonNeg = Annotated[float, Field(ge=0.0)]
Fraction = Annotated[float, Field(ge=0.0, le=1.0)]
Week = Annotated[int, Field(ge=1)]

# A per-week quantity: either one constant value for every week, or an explicit list of length T.
Series = float | list[float]
NonNegSeries = NonNeg | list[NonNeg]
FractionSeries = Fraction | list[Fraction]


def _expand(name: str, value: Series, horizon: int) -> list[float]:
    """Turn a constant or a length-T list into a length-T list (week t at index t-1)."""
    if isinstance(value, list):
        if len(value) != horizon:
            raise ValueError(f"{name}: expected {horizon} weekly values, got {len(value)}")
        return [float(v) for v in value]
    return [float(value)] * horizon


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class Store(_Model):
    """One location ℓ with its baseline weekly net sales S^base_{ℓ,t}."""

    name: str
    base_sales: NonNegSeries


class BusinessParams(_Model):
    """Business structure and initial conditions (MATH_MODEL §0, §3, §10)."""

    # The business is fictional, so only these labels are allowed (same wire values as the backend Provenance enum).
    provenance: Literal["SYNTHETIC", "ILLUSTRATIVE"] = "SYNTHETIC"
    horizon_weeks: Week = 26  # T

    # Initial conditions (explicit, required)
    cash_0: float  # C_0
    sales_0: NonNeg  # S_0, sales recognized in the week before week 1
    prior_purchases: list[float]  # [P_{1-L_p}, ..., P_0], oldest first; length L_p
    inventory_0: float  # I_0, inventory at cost before week 1
    term_loan_principal_1: NonNeg  # D_1, term-loan principal outstanding at start of week 1
    revolver_balance_0: NonNeg  # B_0

    # Operations
    stores: list[Store] = Field(min_length=1)
    gross_margin: Fraction  # g
    same_week_collection: Fraction  # a
    supplier_lag_weeks: Annotated[int, Field(ge=0)]  # L_p
    payroll: NonNegSeries  # W_t
    opex: NonNegSeries  # O_t
    capex: NonNegSeries = 0.0  # K_t (non-critical, deferrable)
    expansion_outflow: NonNegSeries = 0.0  # E_t
    expansion_sales: NonNegSeries = 0.0  # X_t

    # Financing
    base_rate: Series  # r^base_t, annual
    amortization: NonNegSeries = 0.0  # A_t
    revolver_limit: NonNeg  # B-bar (optimizer constraint §4.2; not enforced by simulate())
    revolver_spread: float  # s_R, annual

    # Backup supplier terms
    backup_premium: NonNeg  # pi
    backup_switch_fee: NonNeg  # F_b

    # Stock-out cost (§3, issue #103). Service level I^svc_t = σ I_0 m_t; each $ of inventory below it loses
    # θ $ of sales per week. Both default to 0 (no stock-out cost); the fixtures set them explicitly.
    service_level_share: NonNeg = 0.0  # σ, service-level stock as a share of I_0 at planned demand (m_t = 1)
    stockout_lost_sales_rate: NonNeg = 0.0  # θ, $ of sales lost per week per $ of inventory shortfall

    # Optimizer floors (§4.1, §4.3). Carried here for the optimizer; simulate() does not enforce them.
    min_cash: float | None = None  # C_min
    min_inventory: float | None = None  # I_min

    @model_validator(mode="after")
    def _check_shapes(self) -> BusinessParams:
        if len(self.prior_purchases) != self.supplier_lag_weeks:
            raise ValueError(
                f"prior_purchases must list P_(1-L_p)..P_0: expected {self.supplier_lag_weeks} values, "
                f"got {len(self.prior_purchases)}"
            )
        T = self.horizon_weeks
        for name in ("payroll", "opex", "capex", "expansion_outflow", "expansion_sales", "base_rate", "amortization"):
            _expand(name, getattr(self, name), T)
        for store in self.stores:
            _expand(f"stores[{store.name}].base_sales", store.base_sales, T)
        return self


class DemandShock(_Model):
    """§1: m_t = 1-δ on [t1, t2], then linear recovery to 1 over ρ weeks."""

    delta: Fraction  # δ
    start_week: Week  # t1
    end_week: Week  # t2
    recovery_weeks: Annotated[int, Field(ge=0)] = 0  # ρ (0 = back to 1 immediately after t2)

    @model_validator(mode="after")
    def _check_window(self) -> DemandShock:
        if self.end_week < self.start_week:
            raise ValueError("end_week must be >= start_week")
        return self


class RateShock(_Model):
    """§1: r_t = r^base_t + Δr · 1[t >= t_r]."""

    delta_rate: float  # Δr, annual (0.02 = +200bp)
    start_week: Week  # t_r


class SupplierOutage(_Model):
    """§1: primary-supplier availability κ_t; lost-sales fraction λ_t = φ (1 - κ_t) without backup."""

    availability: FractionSeries  # κ_t
    dependent_share: Fraction  # φ


class ScenarioShock(_Model):
    """A deterministic scenario: any combination of demand, rate and supplier shocks (none = baseline)."""

    name: str = "baseline"
    demand: DemandShock | None = None
    rate: RateShock | None = None
    supplier: SupplierOutage | None = None


class ActionPlan(_Model):
    """§4 decisions. Every default is "no action"."""

    use_backup_supplier: bool = False  # x_b
    defer_capex: bool = False  # x_c
    delay_expansion: bool = False  # x_e
    purchase_cut: NonNegSeries = 0.0  # v_t
    revolver_draw: NonNegSeries = 0.0  # y_t
    revolver_repay: NonNegSeries = 0.0  # q_t
    payroll_cut: FractionSeries = 0.0  # z_t, share of W_t not paid (bound z-bar is the optimizer's job)


# --------------------------------------------------------------------------- output types


class SimulationResult(_Model):
    """Per-week paths for every §5 cascade node plus the intermediate terms of the §3 recurrence."""

    provenance: Literal["SIMULATED"] = "SIMULATED"
    scenario_name: str
    horizon_weeks: int
    weeks: list[int]

    # Exogenous paths (§1)
    demand_multiplier: list[float]  # m_t
    supplier_availability: list[float]  # κ_t
    lost_sales_fraction: list[float]  # λ_t (before backup)
    rate: list[float]  # r_t

    # Sales and stock (§2, §3)
    core_demand: list[float]  # S^core_t = m_t Σ_ℓ S^base_{ℓ,t}, base-store demand (the outage and premium base)
    demand: list[float]  # S^dem_t = S^core_t + (1-x_e) X_t, total demand
    sales: list[float]  # S_t
    lost_sales: list[float]  # S^dem_t - S_t = S^core_t λ_t (1-x_b) + ℓ_t (outage plus stock-out lost sales)
    receipts: list[float]  # R_t
    backup_premium: list[float]  # π (1-g) S^core_t λ_t x_b
    purchases: list[float]  # P_t
    payables_paid: list[float]  # P_{t-L_p}
    inventory: list[float]  # I_t
    service_level_inventory: list[float]  # I^svc_t = σ I_0 m_t
    inventory_shortfall: list[float]  # u_t = max(0, I^svc_t - I_t)
    stockout_lost_sales: list[float]  # ℓ_t = θ u_t

    # Financing
    term_loan_principal: list[float]  # D_t (start of week)
    interest: list[float]  # J_t (term loan)
    amortization: list[float]  # A_t
    revolver_interest: list[float]  # J^R_t
    total_interest: list[float]  # J_t + J^R_t
    revolver_draw: list[float]  # y_t
    revolver_repay: list[float]  # q_t
    revolver_balance: list[float]  # B_t

    # Other outflows
    payroll: list[float]  # (1 - z_t) W_t, payroll actually paid
    opex: list[float]  # O_t
    capex: list[float]  # (1 - x_c) K_t
    expansion_outflow: list[float]  # (1 - x_e) E_t
    backup_fee: list[float]  # F_b x_b 1[t=1]

    # Cash
    cash_0: float
    cash: list[float]  # C_t
    min_cash: float  # min_t C_t, t = 1..T
    min_cash_week: int  # first t attaining min_cash
    ending_cash: float  # C_T
    runway_week: int | None  # first t with C_t < 0; None if cash never goes negative within T
    runway_label: str  # "week k" or "> T weeks"


# --------------------------------------------------------------------------- §1 shocks


def demand_multipliers(shock: DemandShock | None, horizon: int) -> list[float]:
    """m_t = 1-δ for t1<=t<=t2; 1-δ(1-(t-t2)/ρ) for t2<t<=t2+ρ; else 1."""
    if shock is None:
        return [1.0] * horizon
    d, t1, t2, rho = shock.delta, shock.start_week, shock.end_week, shock.recovery_weeks
    out = []
    for t in range(1, horizon + 1):
        if t1 <= t <= t2:
            out.append(1.0 - d)
        elif rho > 0 and t2 < t <= t2 + rho:
            out.append(1.0 - d * (1.0 - (t - t2) / rho))
        else:
            out.append(1.0)
    return out


def rate_path(params: BusinessParams, shock: RateShock | None) -> list[float]:
    """r_t = r^base_t + Δr · 1[t >= t_r]."""
    base = _expand("base_rate", params.base_rate, params.horizon_weeks)
    if shock is None:
        return base
    return [r + (shock.delta_rate if t >= shock.start_week else 0.0) for t, r in enumerate(base, start=1)]


def lost_sales_fractions(shock: SupplierOutage | None, horizon: int) -> tuple[list[float], list[float]]:
    """Returns (κ_t, λ_t) with λ_t = φ (1 - κ_t). No outage → κ_t = 1, λ_t = 0."""
    if shock is None:
        return [1.0] * horizon, [0.0] * horizon
    kappa = _expand("supplier.availability", shock.availability, horizon)
    return kappa, [shock.dependent_share * (1.0 - k) for k in kappa]


# --------------------------------------------------------------------------- §2-§3 simulator


# Dollar tolerance for the financing and physical sanity checks, so optimizer round-off (e.g. B_t = -1e-9 or
# I_t = -1e-9) is not rejected.
FINANCING_TOL = 1e-6


def simulate(params: BusinessParams, shock: ScenarioShock, plan: ActionPlan) -> SimulationResult:
    """Run the §3 boxed recurrence for t = 1..T.

    C_t = C_{t-1} + R_t - P_{t-L_p} - (1-z_t)W_t - O_t - J_t - A_t - J^R_t
          - (1-x_c)K_t - (1-x_e)E_t - F_b x_b 1[t=1] + y_t - q_t

    Stock-out cost (§3): u_t = max(0, I^svc_t - I_t) with I^svc_t = σ I_0 m_t, and ℓ_t = θ u_t is
    subtracted from sales S_t, so it flows through receipts and purchases like any other lost sale.

    Raises ValueError, naming the week, for plans that cannot happen (§3): negative sales (S_t < 0),
    negative purchases (P_t < 0),
    negative inventory (I_t < 0), a revolver repayment above the balance (B_t < 0) or amortization above the
    remaining principal (D_{t+1} < 0). Within one week, purchases are checked first, then inventory, then
    financing. I_min is an optimizer constraint (§4.3) and is not enforced here.
    """
    T = params.horizon_weeks
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

    m = demand_multipliers(shock.demand, T)
    r = rate_path(params, shock.rate)
    kappa, lam = lost_sales_fractions(shock.supplier, T)

    cols: dict[str, list[float]] = {k: [] for k in (
        "core_demand", "demand", "sales", "lost_sales", "receipts", "backup_premium", "purchases", "payables_paid",
        "inventory", "service_level_inventory", "inventory_shortfall", "stockout_lost_sales", "term_loan_principal",
        "interest", "revolver_interest", "total_interest",
        "revolver_balance", "payroll", "capex", "expansion_outflow", "backup_fee", "cash",
    )}

    S_prev, inv_prev, B_prev, C_prev = params.sales_0, params.inventory_0, params.revolver_balance_0, params.cash_0
    D = params.term_loan_principal_1
    for i in range(T):
        t = i + 1
        # §2 demand and sales: the outage hits base-store demand S^core only, never the new store's X_t
        S_core = m[i] * base_sales[i]
        S_dem = S_core + (1.0 - xe) * X[i]
        # §3 inventory: I_t = I_{t-1} + P_t - (1-g)S_t - premium = I_{t-1} - v_t (does not depend on S_t)
        inv = inv_prev - v[i]
        # §3 stock-out cost: inventory below the service level loses sales ℓ_t = θ u_t this week
        svc = params.service_level_share * params.inventory_0 * m[i]  # I^svc_t = σ I_0 m_t
        short = max(0.0, svc - inv)  # u_t
        lost_stockout = params.stockout_lost_sales_rate * short  # ℓ_t
        S = S_core * (1.0 - lam[i] * (1.0 - xb)) + (1.0 - xe) * X[i] - lost_stockout
        # §3 receipts, purchases
        R = a * S + (1.0 - a) * S_prev
        premium = params.backup_premium * (1.0 - g) * S_core * lam[i] * xb  # same base-store outage share as §2
        P = (1.0 - g) * S - v[i] + premium
        # §3 physical limits: the business cannot sell, buy or hold a negative amount.
        if S < -FINANCING_TOL:
            raise ValueError(
                f"week {t}: stock-out lost sales {lost_stockout:.2f} exceed the week's sales before them "
                f"({S + lost_stockout:.2f}), so S_t would be {S:.2f} < 0; sales cannot be negative"
            )
        if P < -FINANCING_TOL:
            raise ValueError(
                f"week {t}: purchase cut v_t = {v[i]:.2f} exceeds that week's purchases before the cut "
                f"({P + v[i]:.2f}), so P_t would be {P:.2f} < 0; purchases cannot be negative"
            )
        if inv < -FINANCING_TOL:
            raise ValueError(
                f"week {t}: inventory I_t = I_(t-1) - v_t = {inv_prev:.2f} - {v[i]:.2f} = {inv:.2f} < 0; "
                "inventory cannot be negative"
            )
        cols["purchases"].append(P)  # appended before the lag lookup so L_p = 0 pays P_t
        k = t - Lp  # pay P_{t-L_p}; pre-horizon values come from prior_purchases
        paid = cols["purchases"][k - 1] if k >= 1 else params.prior_purchases[t - 1]
        # interest and revolver
        J = D * r[i] / 52.0
        JR = B_prev * (r[i] + params.revolver_spread) / 52.0
        B = B_prev + y[i] - q[i]
        if B < -FINANCING_TOL:
            raise ValueError(
                f"week {t}: revolver repayment q_t = {q[i]:.2f} exceeds the balance B_(t-1) + y_t = "
                f"{B_prev + y[i]:.2f} (B_t would be {B:.2f} < 0)"
            )
        if D - A[i] < -FINANCING_TOL:
            raise ValueError(
                f"week {t}: amortization A_t = {A[i]:.2f} exceeds term-loan principal D_t = {D:.2f} "
                f"(D_(t+1) would be {D - A[i]:.2f} < 0)"
            )
        # outflows
        payroll_paid = (1.0 - z[i]) * W[i]
        capex_paid = (1.0 - xc) * K[i]
        expansion_paid = (1.0 - xe) * E[i]
        fee = params.backup_switch_fee * xb if t == 1 else 0.0
        C = (C_prev + R - paid - payroll_paid - opex[i] - J - A[i] - JR
             - capex_paid - expansion_paid - fee + y[i] - q[i])

        for key, val in (
            ("core_demand", S_core), ("demand", S_dem), ("sales", S), ("lost_sales", S_dem - S), ("receipts", R),
            ("backup_premium", premium), ("payables_paid", paid), ("inventory", inv),
            ("service_level_inventory", svc), ("inventory_shortfall", short), ("stockout_lost_sales", lost_stockout),
            ("term_loan_principal", D), ("interest", J), ("revolver_interest", JR),
            ("total_interest", J + JR), ("revolver_balance", B), ("payroll", payroll_paid),
            ("capex", capex_paid), ("expansion_outflow", expansion_paid), ("backup_fee", fee), ("cash", C),
        ):
            cols[key].append(val)

        S_prev, inv_prev, B_prev, C_prev = S, inv, B, C
        D = D - A[i]  # D_{t+1} = D_t - A_t

    cash = cols["cash"]
    min_cash = min(cash)
    runway_week = next((t for t, c in enumerate(cash, start=1) if c < 0.0), None)
    return SimulationResult(
        scenario_name=shock.name,
        horizon_weeks=T,
        weeks=list(range(1, T + 1)),
        demand_multiplier=m,
        supplier_availability=kappa,
        lost_sales_fraction=lam,
        rate=r,
        amortization=A,
        revolver_draw=y,
        revolver_repay=q,
        opex=opex,
        cash_0=params.cash_0,
        min_cash=min_cash,
        min_cash_week=cash.index(min_cash) + 1,
        ending_cash=cash[-1],
        runway_week=runway_week,
        runway_label=f"> {T} weeks" if runway_week is None else f"week {runway_week}",
        **cols,
    )


# --------------------------------------------------------------------------- §5 cascade deltas

# §5 node name -> SimulationResult field holding its per-week value.
CASCADE_NODES: dict[str, str] = {
    "Demand": "demand",
    "Sales": "sales",
    "Receipts": "receipts",
    "Supplier": "supplier_availability",
    "Inventory": "inventory",
    "Purchases": "purchases",
    "Payables": "payables_paid",
    "Rate": "rate",
    "Interest": "total_interest",
    "Payroll": "payroll",
    "Revolver": "revolver_balance",
    "Cash": "cash",
}

# Directed dependencies read off the §2-§3 formulas (source feeds target).
CASCADE_EDGES: tuple[tuple[str, str], ...] = (
    ("Demand", "Sales"),
    ("Supplier", "Sales"),
    ("Supplier", "Purchases"),
    ("Demand", "Purchases"),  # backup premium π(1-g) S^core_t λ_t x_b uses base-store demand directly
    ("Sales", "Receipts"),
    ("Sales", "Purchases"),
    ("Purchases", "Inventory"),
    ("Purchases", "Payables"),
    ("Rate", "Interest"),
    ("Revolver", "Interest"),
    ("Receipts", "Cash"),
    ("Payables", "Cash"),
    ("Interest", "Cash"),
    ("Payroll", "Cash"),
    ("Revolver", "Cash"),
)


class NodeDelta(_Model):
    field: str
    per_week: list[float]  # Δ_t = scenario_t - baseline_t
    max_abs: float  # max_t |Δ_t|, for edge emphasis
    at_end: float  # Δ_T


class CascadeDeltas(_Model):
    provenance: Literal["SIMULATED"] = "SIMULATED"
    baseline_name: str
    scenario_name: str
    nodes: dict[str, NodeDelta]
    edges: list[tuple[str, str]]
    min_cash_delta: float
    ending_cash_delta: float


def cascade_deltas(baseline: SimulationResult, scenario: SimulationResult) -> CascadeDeltas:
    """§5: Δ_n = value_n(scenario) - value_n(baseline), per node and per week, straight from the simulator."""
    if baseline.horizon_weeks != scenario.horizon_weeks:
        raise ValueError(
            f"horizon mismatch: baseline T={baseline.horizon_weeks}, scenario T={scenario.horizon_weeks}"
        )
    nodes = {}
    for node, field in CASCADE_NODES.items():
        diff = [s - b for s, b in zip(getattr(scenario, field), getattr(baseline, field), strict=True)]
        nodes[node] = NodeDelta(field=field, per_week=diff, max_abs=max(abs(d) for d in diff), at_end=diff[-1])
    return CascadeDeltas(
        baseline_name=baseline.scenario_name,
        scenario_name=scenario.scenario_name,
        nodes=nodes,
        edges=list(CASCADE_EDGES),
        min_cash_delta=scenario.min_cash - baseline.min_cash,
        ending_cash_delta=scenario.ending_cash - baseline.ending_cash,
    )
