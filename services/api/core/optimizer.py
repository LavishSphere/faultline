"""Recovery optimizer: the least harmful set of actions that keeps cash above the floor every week.

Implements docs/MATH_MODEL.md §4 (the MILP) on top of the §2-§3 model, solved with scipy.optimize.milp (HiGHS).
That document is the contract: if a formula here and there disagree, the document wins and this file is the bug.

Decisions (one variable vector, §4):
    x_b, x_c, x_e in {0, 1}          use backup supplier, defer non-critical capex, delay expansion
    v_t in [0, v-bar]                 purchase cut, week t
    y_t, q_t >= 0                     revolver draw and repayment, week t
    z_t in [0, z-bar]                 payroll reduction share, week t (upper bound 0 in protect-payroll mode)
    B_t, C_t, I_t                     revolver balance, cash and inventory at the end of week t
    mu                                auxiliary: minimum cash

§3 as equality rows, for t = 1..T (every term is linear in the decisions once the scenario fixes m_t, lambda_t, r_t):
    C_t - C_{t-1} - R_t + P_{t-L_p} - z_t W_t + J^R_t - y_t + q_t - K_t x_c - E_t x_e + F_b x_b 1[t=1]
        = -W_t - O_t - J_t - A_t - K_t - E_t
    B_t - B_{t-1} - y_t + q_t = 0
    I_t - I_{t-1} + v_t = 0
  with S_t = S^core_t (1 - lambda_t (1 - x_b)) + (1 - x_e) X_t, R_t = a S_t + (1 - a) S_{t-1},
  P_t = (1 - g) S_t - v_t + pi (1 - g) S^core_t lambda_t x_b, J^R_t = B_{t-1} (r_t + s_R) / 52, and
  S_0, P_{1-L_p}..P_0, C_0, B_0, I_0 the given pre-horizon constants.

§4 hard constraints:
    1. C_t >= C_min    2. 0 <= B_t <= B-bar    3. I_t >= max(I_min, 0)    4. debt service J_t + A_t is a fixed outflow
    5. protect payroll: z_t <= 0    6. mu <= C_t    7. B_T <= B_0
    8. purchases non-negative: P_t >= 0, i.e. v_t <= (1 - g) S_t + pi (1 - g) S^core_t lambda_t x_b
  (8 and the 0 in 3 are the §3 physical rules simulate() enforces: no negative purchases or stock.)

Objective (minimize disruption, tie-break toward more cash):
    J = c_b x_b + c_c x_c + c_e x_e + c_v sum_t v_t + c_y sum_t y_t + c_z sum_t z_t W_t - epsilon mu

Lexicographic tie-break (issue #104): several plans can have the same minimal J (e.g. a purchase cut in week 3 or week
5 bridges the same trough). Stage 1 solves the MILP above for J*. Stage 2 keeps J(x) <= J* as a constraint and
minimizes
    TB = sum_t [ (T + 1 - t)/T * (v_t + y_t + z_t W_t) + t/(2T) * q_t ]
over the same constraints (yes/no decisions free again): among equally cheap plans, act as late as possible and
borrow for as short a time as possible. The stage-2 plan is accepted only if its J is within max(1e-9 |J*|, 1e-7) of
J*; otherwise the stage-1 plan is reported and solver_message says so. NO FEASIBLE PLAN is decided by stage 1 alone.

Rules: pure functions only. No I/O, no randomness, no LLM calls, no clock. Dollars are plain floats and are never
rounded here (round only for display). The returned cash path is the solver's C_t; optimize() re-simulates the chosen
plan with core.financials.simulate() and refuses to report OPTIMAL if the two disagree by more than 1e-6.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field
from scipy.optimize import Bounds, LinearConstraint, milp

from core.financials import (
    ActionPlan,
    BusinessParams,
    ScenarioShock,
    demand_multipliers,
    lost_sales_fractions,
    rate_path,
    simulate,
)

OPTIMAL = "OPTIMAL"
NO_FEASIBLE_PLAN = "NO FEASIBLE PLAN"
SOLVER_ERROR = "SOLVER ERROR"

# A constraint is reported as binding when its slack is below this many dollars (or shares, for z_t).
BINDING_TOL = 1e-6
# Solver path vs simulate() path: the largest allowed gap in dollars before OPTIMAL is refused.
AGREEMENT_TOL = 1e-6
# Solver values smaller than this are treated as zero when the plan is read back (removes round-off like -1e-12).
ZERO_TOL = 1e-9
# Stage-2 tie-break acceptance (§4): the tie-broken plan's J may exceed the stage-1 optimum J* by at most
# max(COST_TIE_REL_TOL * |J*|, COST_TIE_ABS_TOL) (solver round-off); otherwise the stage-1 plan is reported.
COST_TIE_REL_TOL = 1e-9
COST_TIE_ABS_TOL = 1e-7

NonNeg = Annotated[float, Field(ge=0.0)]
Fraction = Annotated[float, Field(ge=0.0, le=1.0)]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


# --------------------------------------------------------------------------- settings


class DisruptionCosts(_Model):
    """§4 disruption weights c_y, c_v, c_c, c_b, c_e, c_z (non-cash harm, on top of the §3 cash effects).

    Defaults are the MATH_MODEL §10 "Disruption costs" table (signed off by the finance owner in issue #6).
    """

    revolver_draw_per_dollar: NonNeg = 0.01  # c_y, per $ drawn
    purchase_cut_per_dollar: NonNeg = 0.05  # c_v, per $ cut
    defer_capex_per_decision: NonNeg = 1_000.0  # c_c
    backup_supplier_per_decision: NonNeg = 2_500.0  # c_b
    delay_expansion_per_decision: NonNeg = 5_000.0  # c_e
    payroll_cut_per_dollar: NonNeg = 5.0  # c_z, per $ of payroll cut (z_t W_t)


class OptimizerSettings(_Model):
    """Optimizer inputs that are not part of BusinessParams: v-bar, z-bar, epsilon and the disruption costs.

    Field names match the ``optimizer_parameters`` section of data/demo_business.json (PR #42). The defaults are the
    MATH_MODEL §10 values and are defined only here; callers that load the fixture should pass
    ``OptimizerSettings.from_dict(doc["optimizer_parameters"])`` instead of relying on them.
    """

    purchase_cut_cap_per_week: NonNeg = 10_000.0  # v-bar (§10: 10,000/wk)
    payroll_cut_cap: Fraction = 0.1  # z-bar (§10: 0.10)
    tie_break_epsilon: NonNeg = 1e-4  # epsilon (§10: 1e-4 per $ of minimum cash)
    disruption_costs: DisruptionCosts = DisruptionCosts()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OptimizerSettings:
        """Build settings from an ``optimizer_parameters`` dict. Pure: takes a dict, reads no file.

        The fixture's documentation keys ("note", "symbols") are dropped; any other unknown key is an error.
        """
        return cls.model_validate({k: v for k, v in data.items() if k not in _SETTINGS_DOC_KEYS})


# Documentation-only keys in the ``optimizer_parameters`` section of data/demo_business.json.
_SETTINGS_DOC_KEYS = ("note", "symbols")


# --------------------------------------------------------------------------- result


ActionKind = Literal[
    "use_backup_supplier", "defer_capex", "delay_expansion", "purchase_cut", "revolver_draw", "revolver_repay",
    "payroll_cut",
]


class ChosenAction(_Model):
    """One action the optimizer chose. ``week`` is None for the three yes/no decisions."""

    action: ActionKind
    week: int | None = None
    amount: float | None = None  # dollars (None for the yes/no decisions); payroll_cut: dollars not paid (z_t W_t)
    share: float | None = None  # payroll_cut only: z_t


class OptimizationResult(_Model):
    """§4 outputs. For NO FEASIBLE PLAN and SOLVER ERROR every plan field is None (nothing is invented)."""

    provenance: Literal["SIMULATED"] = "SIMULATED"
    status: Literal["OPTIMAL", "NO FEASIBLE PLAN", "SOLVER ERROR"]
    solver_message: str
    scenario_name: str
    protect_payroll: bool

    plan: ActionPlan | None = None
    actions: list[ChosenAction] | None = None
    cash: list[float] | None = None  # C_t, t = 1..T, from the solver (agrees with simulate() to 1e-6)
    revolver_balance: list[float] | None = None  # B_t
    inventory: list[float] | None = None  # I_t
    min_cash: float | None = None  # min_t C_t
    min_cash_week: int | None = None  # first t attaining min_cash
    binding_constraints: list[str] | None = None  # e.g. "liquidity floor, week 9"
    objective: float | None = None  # the full §4 objective, including -epsilon mu
    disruption_cost: float | None = None  # the objective without the tie-break term

    # NO FEASIBLE PLAN diagnostic: the highest minimum cash any plan can reach (same actions and constraints, liquidity
    # floor removed). The floor C_min would have to be lowered to this value for a plan to exist.
    max_feasible_cash_floor: float | None = None
    diagnostic: str | None = None


# --------------------------------------------------------------------------- model building


def _series(value: float | list[float], horizon: int) -> list[float]:
    """Constant or length-T list -> length-T list (BusinessParams has already checked the lengths)."""
    return [float(v) for v in value] if isinstance(value, list) else [float(value)] * horizon


class _Affine:
    """A linear expression const + sum_j coef_j * var_j over the decision vector."""

    __slots__ = ("const", "coef")

    def __init__(self, const: float = 0.0, coef: dict[int, float] | None = None) -> None:
        self.const = const
        self.coef = dict(coef or {})

    def __add__(self, other: _Affine) -> _Affine:
        out = _Affine(self.const + other.const, self.coef)
        for j, c in other.coef.items():
            out.coef[j] = out.coef.get(j, 0.0) + c
        return out

    def __sub__(self, other: _Affine) -> _Affine:
        return self + other.scale(-1.0)

    def scale(self, k: float) -> _Affine:
        return _Affine(self.const * k, {j: c * k for j, c in self.coef.items()})


def _var(j: int, coef: float = 1.0) -> _Affine:
    return _Affine(0.0, {j: coef})


class _Index:
    """Positions in the single variable vector: x_b, x_c, x_e, then v, y, q, z, B, C, I (T each), then mu."""

    def __init__(self, T: int) -> None:
        self.T = T
        self.xb, self.xc, self.xe = 0, 1, 2
        self._base = {name: 3 + k * T for k, name in enumerate(("v", "y", "q", "z", "B", "C", "I"))}
        self.mu = 3 + 7 * T
        self.n = self.mu + 1

    def __call__(self, name: str, t: int) -> int:
        """Index of variable ``name`` in week t (t = 1..T)."""
        return self._base[name] + t - 1


class _Problem:
    """The §4 MILP for one (params, shock, protect_payroll, settings) in scipy.optimize.milp form."""

    def __init__(
        self, params: BusinessParams, shock: ScenarioShock, protect_payroll: bool, settings: OptimizerSettings
    ) -> None:
        if params.min_cash is None or params.min_inventory is None:
            raise ValueError("optimize() needs params.min_cash (C_min) and params.min_inventory (I_min)")
        T = params.horizon_weeks
        ix = _Index(T)
        self.params, self.ix, self.T = params, ix, T
        g, a, Lp = params.gross_margin, params.same_week_collection, params.supplier_lag_weeks
        costs = settings.disruption_costs

        base = [0.0] * T
        for store in params.stores:
            for i, s in enumerate(_series(store.base_sales, T)):
                base[i] += s
        m = demand_multipliers(shock.demand, T)
        r = rate_path(params, shock.rate)
        _, lam = lost_sales_fractions(shock.supplier, T)
        W = _series(params.payroll, T)
        opex = _series(params.opex, T)
        K = _series(params.capex, T)
        E = _series(params.expansion_outflow, T)
        X = _series(params.expansion_sales, T)
        A = _series(params.amortization, T)
        self.W = W

        # §2-§3 affine pieces. S[t] for t = 0..T (S[0] is the constant S_0); P[k] for k = 1..T.
        S: list[_Affine] = [_Affine(params.sales_0)]
        P: list[_Affine] = [_Affine()]  # placeholder at k = 0; pre-horizon P values come from prior_purchases
        for t in range(1, T + 1):
            core = m[t - 1] * base[t - 1]
            lost = core * lam[t - 1]
            S_t = _Affine(core - lost + X[t - 1], {ix.xb: lost, ix.xe: -X[t - 1]})
            S.append(S_t)
            premium = _var(ix.xb, params.backup_premium * (1.0 - g) * lost)
            P.append(S_t.scale(1.0 - g) - _var(ix("v", t)) + premium)
        self.P = P  # P[t] = purchases in week t as an expression of the decisions (index 0 unused)

        rows: list[dict[int, float]] = []
        lo: list[float] = []
        hi: list[float] = []

        def add_row(expr: _Affine, lower: float, upper: float) -> None:
            """Add lower <= expr <= upper as a row (the expression's constant is moved to the bounds)."""
            rows.append({j: c for j, c in expr.coef.items() if c != 0.0})
            lo.append(lower - expr.const)
            hi.append(upper - expr.const)

        D = params.term_loan_principal_1
        for t in range(1, T + 1):
            i = t - 1
            C_prev = _var(ix("C", t - 1)) if t > 1 else _Affine(params.cash_0)
            B_prev = _var(ix("B", t - 1)) if t > 1 else _Affine(params.revolver_balance_0)
            I_prev = _var(ix("I", t - 1)) if t > 1 else _Affine(params.inventory_0)
            R_t = S[t].scale(a) + S[t - 1].scale(1.0 - a)
            k = t - Lp
            paid = P[k] if k >= 1 else _Affine(params.prior_purchases[t - 1])
            J = D * r[i] / 52.0  # term-loan interest, a fixed outflow (§4.4)
            JR = B_prev.scale((r[i] + params.revolver_spread) / 52.0)
            payroll_paid = _Affine(W[i], {ix("z", t): -W[i]})  # (1 - z_t) W_t
            capex_paid = _Affine(K[i], {ix.xc: -K[i]})  # (1 - x_c) K_t
            expansion_paid = _Affine(E[i], {ix.xe: -E[i]})  # (1 - x_e) E_t
            fee = _var(ix.xb, params.backup_switch_fee) if t == 1 else _Affine()
            rhs = (
                C_prev + R_t - paid - payroll_paid - _Affine(opex[i] + J + A[i]) - JR - capex_paid - expansion_paid
                - fee + _var(ix("y", t)) - _var(ix("q", t))
            )
            add_row(_var(ix("C", t)) - rhs, 0.0, 0.0)  # §3 boxed cash recurrence
            add_row(_var(ix("B", t)) - B_prev - _var(ix("y", t)) + _var(ix("q", t)), 0.0, 0.0)  # §3 revolver
            add_row(_var(ix("I", t)) - I_prev + _var(ix("v", t)), 0.0, 0.0)  # §3 inventory I_t = I_{t-1} - v_t
            add_row(_var(ix.mu) - _var(ix("C", t)), -np.inf, 0.0)  # §4.6 mu <= C_t
            add_row(P[t], 0.0, np.inf)  # §4.8 P_t >= 0: purchases cannot be negative (MATH_MODEL §3/§4)
            D -= A[i]  # D_{t+1} = D_t - A_t

        A_mat = np.zeros((len(rows), ix.n))
        for row, coefs in enumerate(rows):
            for j, c in coefs.items():
                A_mat[row, j] = c
        self.constraints = LinearConstraint(A_mat, np.array(lo), np.array(hi))

        # Bounds: §4 decision ranges and hard constraints 1, 2, 3, 5, 7.
        # §4.3 with the §3 physical rule I_t >= 0: a negative I_min can never allow negative stock.
        self.I_floor = max(params.min_inventory, 0.0)
        lb = np.zeros(ix.n)
        ub = np.full(ix.n, np.inf)
        ub[[ix.xb, ix.xc, ix.xe]] = 1.0
        z_cap = 0.0 if protect_payroll else settings.payroll_cut_cap  # §4.5: enforced in the solver
        self.B_cap = params.revolver_limit
        for t in range(1, T + 1):
            ub[ix("v", t)] = settings.purchase_cut_cap_per_week
            ub[ix("z", t)] = z_cap if W[t - 1] > 0.0 else 0.0  # no payroll due -> nothing to cut
            ub[ix("B", t)] = params.revolver_limit  # §4.2
            lb[ix("C", t)] = params.min_cash  # §4.1
            lb[ix("I", t)] = self.I_floor  # §4.3
        ub[ix("B", T)] = min(params.revolver_limit, params.revolver_balance_0)  # §4.7 terminal revolver
        lb[ix.mu] = -np.inf
        self.lb, self.ub = lb, ub
        self.v_cap, self.z_cap = settings.purchase_cut_cap_per_week, z_cap

        c = np.zeros(ix.n)
        c[ix.xb] = costs.backup_supplier_per_decision
        c[ix.xc] = costs.defer_capex_per_decision
        c[ix.xe] = costs.delay_expansion_per_decision
        for t in range(1, T + 1):
            c[ix("v", t)] = costs.purchase_cut_per_dollar
            c[ix("y", t)] = costs.revolver_draw_per_dollar
            c[ix("z", t)] = costs.payroll_cut_per_dollar * W[t - 1]
        self.c_disruption = c.copy()  # the §4 objective without the -epsilon mu term
        self.epsilon = settings.tie_break_epsilon
        c[ix.mu] = -settings.tie_break_epsilon
        self.c = c

        # §4 stage-2 tie-break TB: a dollar of purchase cut, draw or payroll cut weighs more the earlier it happens;
        # a dollar of repayment weighs more the later it happens, at half the slope, so moving a whole draw-and-repay
        # pair one week later lowers TB (by 1/(2T) per dollar) instead of tying.
        tb = np.zeros(ix.n)
        for t in range(1, T + 1):
            late = (T + 1 - t) / T
            tb[ix("v", t)] = late
            tb[ix("y", t)] = late
            tb[ix("z", t)] = late * W[t - 1]  # per dollar of payroll cut z_t W_t
            tb[ix("q", t)] = t / (2 * T)
        self.c_tie_break = tb

        self.integrality = np.zeros(ix.n)
        self.integrality[[ix.xb, ix.xc, ix.xe]] = 1

    def solve(
        self,
        c: np.ndarray,
        lb: np.ndarray,
        ub: np.ndarray,
        integrality: np.ndarray,
        extra: tuple[LinearConstraint, ...] = (),
        options: dict[str, Any] | None = None,
    ):
        return milp(
            c, integrality=integrality, bounds=Bounds(lb, ub), constraints=[self.constraints, *extra], options=options
        )

    def objective(self, sol: np.ndarray) -> float:
        """The §4 objective J of a solution, with mu at its value for the plan, min_t C_t."""
        min_cash = min(float(sol[self.ix("C", t)]) for t in range(1, self.T + 1))
        return float(self.c_disruption @ sol) - self.epsilon * min_cash

    def fixed_binaries(self, sol: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Bounds with x_b, x_c, x_e fixed at the 0/1 values in ``sol`` (the MILP may return 0.9999999)."""
        lb, ub = self.lb.copy(), self.ub.copy()
        for j in (self.ix.xb, self.ix.xc, self.ix.xe):
            lb[j] = ub[j] = float(round(sol[j]))
        return lb, ub


# --------------------------------------------------------------------------- reading the solution


def _value(expr: _Affine, sol: np.ndarray) -> float:
    """Evaluate a linear expression at the solver's solution."""
    return expr.const + sum(c * float(sol[j]) for j, c in expr.coef.items())


def _clean(value: float) -> float:
    """Drop solver round-off: |value| < ZERO_TOL -> 0, never negative (ActionPlan requires v, y, q, z >= 0)."""
    return 0.0 if value < ZERO_TOL else float(value)


def _binding(prob: _Problem, sol: np.ndarray) -> list[str]:
    """Names of §4 constraints whose slack is below BINDING_TOL, in a fixed order, with week numbers."""
    ix, T, p = prob.ix, prob.T, prob.params
    names: list[str] = []
    checks = (
        ("liquidity floor", lambda t: sol[ix("C", t)] - p.min_cash),
        ("facility limit", lambda t: prob.B_cap - sol[ix("B", t)]),
        ("inventory floor", lambda t: sol[ix("I", t)] - prob.I_floor),
        ("purchases non-negative", lambda t: _value(prob.P[t], sol)),
    )
    for label, slack in checks:
        names += [f"{label}, week {t}" for t in range(1, T + 1) if slack(t) < BINDING_TOL]
    if prob.v_cap > 0:
        names += [f"purchase-cut cap, week {t}" for t in range(1, T + 1) if prob.v_cap - sol[ix("v", t)] < BINDING_TOL]
    if prob.z_cap > 0:
        names += [f"payroll-cut cap, week {t}" for t in range(1, T + 1) if prob.z_cap - sol[ix("z", t)] < BINDING_TOL]
    # §4.7 is listed only when the plan drew on the facility: with no draws, B_T = B_0 trivially and it restricts
    # nothing.
    drew = sum(sol[ix("y", t)] for t in range(1, T + 1)) > BINDING_TOL
    if drew and p.revolver_balance_0 - sol[ix("B", T)] < BINDING_TOL:
        names.append("terminal revolver")
    return names


def _plan_and_actions(prob: _Problem, sol: np.ndarray) -> tuple[ActionPlan, list[ChosenAction]]:
    ix, T = prob.ix, prob.T
    xb, xc, xe = (bool(round(sol[j])) for j in (ix.xb, ix.xc, ix.xe))
    weekly = {name: [_clean(sol[ix(name, t)]) for t in range(1, T + 1)] for name in ("v", "y", "q", "z")}
    plan = ActionPlan(
        use_backup_supplier=xb,
        defer_capex=xc,
        delay_expansion=xe,
        purchase_cut=weekly["v"],
        revolver_draw=weekly["y"],
        revolver_repay=weekly["q"],
        payroll_cut=weekly["z"],
    )
    actions: list[ChosenAction] = []
    for flag, kind in ((xb, "use_backup_supplier"), (xc, "defer_capex"), (xe, "delay_expansion")):
        if flag:
            actions.append(ChosenAction(action=kind))  # yes/no decision: no dollar amount
    for name, kind in (("v", "purchase_cut"), ("y", "revolver_draw"), ("q", "revolver_repay")):
        actions += [
            ChosenAction(action=kind, week=t, amount=val) for t, val in enumerate(weekly[name], start=1) if val > 0.0
        ]
    actions += [
        ChosenAction(action="payroll_cut", week=t, amount=z * prob.W[t - 1], share=z)
        for t, z in enumerate(weekly["z"], start=1)
        if z > 0.0
    ]
    return plan, actions


# --------------------------------------------------------------------------- public entry point


def optimize(
    params: BusinessParams,
    shock: ScenarioShock,
    protect_payroll: bool,
    settings: OptimizerSettings | None = None,
    *,
    tie_break: bool = True,
) -> OptimizationResult:
    """Solve the §4 MILP for this scenario.

    status OPTIMAL: the least harmful plan, its C_t / B_t / I_t paths, binding constraints and objective.
    status NO FEASIBLE PLAN: no combination of actions keeps every §4 constraint; reports the highest cash floor that
    some plan could keep (``max_feasible_cash_floor``). status SOLVER ERROR: the solver's own message, no plan.
    ``settings`` defaults to the MATH_MODEL §10 values (see OptimizerSettings).
    ``tie_break`` (default True) runs the §4 stage-2 tie-break, so equally cheap plans resolve to one fixed plan.
    False returns whichever stage-1 optimum the solver found (same cost; used by tests to check the cost is unchanged).
    """
    settings = settings if settings is not None else OptimizerSettings()
    prob = _Problem(params, shock, protect_payroll, settings)
    ix, T = prob.ix, prob.T
    common = dict(scenario_name=shock.name, protect_payroll=protect_payroll)

    res = prob.solve(prob.c, prob.lb, prob.ub, prob.integrality)
    if res.status == 2:
        return _infeasible(prob, res.message, common)
    if res.status != 0 or res.x is None:
        return OptimizationResult(status=SOLVER_ERROR, solver_message=str(res.message), **common)

    # Fix the binaries at their 0/1 values and re-solve the remaining LP, so the continuous values are exact for
    # those decisions (the MILP may return x = 0.9999999 within its integrality tolerance).
    lb, ub = prob.fixed_binaries(res.x)
    polished = prob.solve(prob.c, lb, ub, np.zeros(ix.n))
    if polished.status != 0 or polished.x is None:
        return OptimizationResult(
            status=SOLVER_ERROR,
            solver_message=f"re-solve with fixed yes/no actions failed: {polished.message}",
            **common,
        )
    sol = polished.x
    message = str(res.message)
    if tie_break:
        sol, note = _tie_break(prob, sol)
        if note:
            message = f"{message}; {note}"

    plan, actions = _plan_and_actions(prob, sol)
    cash = [float(sol[ix("C", t)]) for t in range(1, T + 1)]
    try:
        check = simulate(params, shock, plan)
    except ValueError as exc:  # simulate() rejects physically impossible plans (§3); never report one as OPTIMAL
        return OptimizationResult(
            status=SOLVER_ERROR, solver_message=f"simulate() rejected the solver's plan: {exc}; plan withheld", **common
        )
    gap = max(abs(s - c) for s, c in zip(check.cash, cash, strict=True))
    if gap > AGREEMENT_TOL:
        return OptimizationResult(
            status=SOLVER_ERROR,
            solver_message=f"solver cash path differs from simulate() by ${gap:.3g} (> {AGREEMENT_TOL}); plan withheld",
            **common,
        )

    min_cash = min(cash)
    disruption_cost = float(prob.c_disruption @ sol)
    return OptimizationResult(
        status=OPTIMAL,
        solver_message=message,
        plan=plan,
        actions=actions,
        cash=cash,
        revolver_balance=[float(sol[ix("B", t)]) for t in range(1, T + 1)],
        inventory=[float(sol[ix("I", t)]) for t in range(1, T + 1)],
        min_cash=min_cash,
        min_cash_week=cash.index(min_cash) + 1,
        binding_constraints=_binding(prob, sol),
        objective=disruption_cost - prob.epsilon * min_cash,  # J with mu = min_t C_t (its value for this plan)
        disruption_cost=disruption_cost,
        **common,
    )


def _tie_break(prob: _Problem, sol1: np.ndarray) -> tuple[np.ndarray, str | None]:
    """§4 stage 2: among plans with J <= J* (the stage-1 optimum), the one with the smallest tie-break TB.

    The row is J(x) <= J* with no allowance on purpose: any positive allowance would let TB buy sub-cent changes
    (e.g. a $0.0000001 payroll cut), which would then show up as actions. The yes/no decisions are free again in the
    MILP, then fixed at its 0/1 values for an exact LP polish (falling back to the stage-1 yes/no values if that LP
    fails). A stage-2 plan is accepted only if its own J is within max(COST_TIE_REL_TOL |J*|, COST_TIE_ABS_TOL) of J*.
    Returns (solution, None), or (stage-1 solution, note) when no stage-2 plan passes.
    """
    j_star = prob.objective(sol1)
    tol = max(COST_TIE_REL_TOL * abs(j_star), COST_TIE_ABS_TOL)
    cost_row = (LinearConstraint(prob.c.reshape(1, -1), -np.inf, j_star),)
    tb = prob.c_tie_break
    stage2 = prob.solve(tb, prob.lb, prob.ub, prob.integrality, cost_row, options={"mip_rel_gap": 0.0})
    starts = [stage2.x] if stage2.status == 0 and stage2.x is not None else []
    starts.append(sol1)  # stage-1 yes/no values as the fallback
    failure = f"stage 2 MILP: {stage2.message}"
    for start in starts:
        lb, ub = prob.fixed_binaries(start)
        polished = prob.solve(tb, lb, ub, np.zeros(prob.ix.n), cost_row)
        if polished.status != 0 or polished.x is None:
            failure = f"stage 2 LP: {polished.message}"
            continue
        excess = prob.objective(polished.x) - j_star
        if excess <= tol:
            return polished.x, None
        failure = f"stage 2 plan costs {excess:.3g} more than J* (> {tol:.3g})"
    return sol1, f"tie-break not applied ({failure}); an equally cheap stage-1 plan is reported"


def _infeasible(prob: _Problem, message: str, common: dict[str, Any]) -> OptimizationResult:
    """NO FEASIBLE PLAN, plus the diagnostic: maximize mu with the liquidity floor removed (all else unchanged)."""
    ix, T = prob.ix, prob.T
    lb = prob.lb.copy()
    for t in range(1, T + 1):
        lb[ix("C", t)] = -np.inf
    c = np.zeros(ix.n)
    c[ix.mu] = -1.0
    diag = prob.solve(c, lb, prob.ub, prob.integrality)
    if diag.status == 0 and diag.x is not None:
        best = float(diag.x[ix.mu])
        text = (
            f"No plan keeps cash at or above C_min = ${prob.params.min_cash:,.2f} in every week. The highest minimum "
            f"cash any plan can reach is ${best:,.2f}: the floor would have to be lowered to that value for a plan "
            "to exist."
        )
        return OptimizationResult(
            status=NO_FEASIBLE_PLAN,
            solver_message=str(message),
            max_feasible_cash_floor=best,
            diagnostic=text,
            **common,
        )
    text = (
        "NOT AVAILABLE: no plan is feasible even without the liquidity floor (the inventory floor, facility limit or "
        f"terminal revolver condition cannot be met). Solver: {diag.message}"
    )
    return OptimizationResult(status=NO_FEASIBLE_PLAN, solver_message=str(message), diagnostic=text, **common)
