"""From a forecast probability to a business decision: ACT / WAIT / HEDGE payoffs and regret.

Implements docs/MATH_MODEL.md §8. That document is the contract: if a formula here and there disagree,
the document wins and this file is the bug.

    V(a, y)   = min_t C_t                         lowest simulated cash balance, policy a, outcome y in {0, 1}
    E[V | a]  = p V(a, 1) + (1 - p) V(a, 0)       p = forecast probability of YES
    recommend = argmax_a E[V | a] over policies feasible in BOTH states, else "NO SAFE POLICY"
    regret    = max_{a'} V(a', y) - V(a, y)       after the outcome y is revealed

Every payoff comes from core.financials.simulate(); nothing is computed any other way. Payoffs are
SIMULATED cash balances of the SYNTHETIC demo business, never trading P&L.

Rules: pure functions only. No I/O, no randomness, no LLM calls, no clock. Dollars are plain floats and are
never rounded here (round only for display).
"""

from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.financials import (
    FINANCING_TOL,
    ActionPlan,
    BusinessParams,
    ScenarioShock,
    SimulationResult,
    simulate,
)

NO_SAFE_POLICY = "NO SAFE POLICY"

# Dollar tolerance for the §4 constraint checks and for ties in E[V] (same tolerance the simulator uses).
TOL = FINANCING_TOL

Outcome = Literal[0, 1]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


# --------------------------------------------------------------------------- input type


class Policy(_Model):
    """A pre-declared policy a (MATH_MODEL §8): a name plus one fixed set of §4 actions.

    The same plan is applied in both outcome states, because the decision is made before the reveal.
    All fees and carrying costs (backup switching fee F_b, backup premium π, revolver interest J^R_t,
    the cash effect of every action) are included because the payoff is read off simulate().
    The names ACT / WAIT / HEDGE are labels chosen by the caller; any distinct names are allowed.
    """

    name: str = Field(min_length=1)
    description: str = ""
    plan: ActionPlan


# --------------------------------------------------------------------------- output types


class StateOutcome(_Model):
    """One policy in one outcome state y: the simulated path, V(a, y) and its §4 feasibility."""

    provenance: Literal["SIMULATED"] = "SIMULATED"
    outcome: Outcome  # y: 1 = the forecast event happens (YES), 0 = it does not (NO)
    scenario_name: str
    simulated: bool  # False when simulate() rejected the plan as financing that cannot happen (§3)
    value: float | None  # V(a, y) = min_t C_t; None (NOT AVAILABLE) when the plan was rejected
    value_week: int | None  # first week attaining min_t C_t
    feasible: bool
    violations: list[str]  # why it is infeasible; empty when feasible
    simulation: SimulationResult | None  # the full simulated path (None when rejected)


class PolicyEvaluation(_Model):
    """Per-policy result: V(a,1), V(a,0), E[V | a] and the feasible-in-both flag."""

    provenance: Literal["SIMULATED"] = "SIMULATED"
    policy: Policy
    if_yes: StateOutcome
    if_no: StateOutcome
    value_if_yes: float | None  # V(a, 1)
    value_if_no: float | None  # V(a, 0)
    expected_value: float | None  # E[V | a]; None if either V is NOT AVAILABLE
    feasible_in_both: bool


class DecisionResult(_Model):
    """All evaluated policies and the recommendation (a policy name or "NO SAFE POLICY")."""

    provenance: Literal["SIMULATED"] = "SIMULATED"
    payoff: Literal["lowest simulated cash balance, min_t C_t"] = "lowest simulated cash balance, min_t C_t"
    p_yes: float
    constraints_checked: list[str]
    policies: list[PolicyEvaluation]
    recommendation: str  # recommended policy name, or NO_SAFE_POLICY
    recommended: PolicyEvaluation | None

    @model_validator(mode="after")
    def _check_recommendation(self) -> DecisionResult:
        if (self.recommended is None) != (self.recommendation == NO_SAFE_POLICY):
            raise ValueError("recommendation and recommended must agree")
        return self


class PolicyRegret(_Model):
    policy_name: str
    value: float | None  # V(a, y) in the revealed state
    feasible_in_state: bool
    regret: float | None  # max_{a'} V(a', y) - V(a, y); None (NOT AVAILABLE) if a was infeasible in state y
    note: str


class RegretResult(_Model):
    """Realized regret after the reveal, for every evaluated policy."""

    provenance: Literal["SIMULATED"] = "SIMULATED"
    outcome: Outcome
    best_value: float | None  # max_{a'} V(a', y) over policies feasible in state y; None if there are none
    best_policies: list[str]  # policies attaining best_value (within TOL), in the order given
    recommendation: str  # what evaluate_policies recommended before the reveal
    recommended_regret: float | None  # regret of that recommendation; None if NO SAFE POLICY
    policies: list[PolicyRegret]


# --------------------------------------------------------------------------- §4 feasibility


def _constraints(params: BusinessParams, protect_payroll: bool) -> list[str]:
    names = [
        f"liquidity floor C_t >= C_min = {params.min_cash}",
        f"facility limit 0 <= B_t <= B-bar = {params.revolver_limit}",
        f"inventory floor I_t >= I_min = {params.min_inventory}",
        f"terminal revolver B_T <= B_0 = {params.revolver_balance_0}",
        "simulator accepts the plan (no repayment above the revolver balance, no amortization above principal)",
    ]
    if protect_payroll:
        names.append("protect payroll: z_t = 0 for all t")
    return names


def _first_breach(values: list[float], ok) -> int | None:
    """First week t (1-based) whose value fails ok(value), else None."""
    return next((t for t, v in enumerate(values, start=1) if not ok(v)), None)


def _violations(params: BusinessParams, res: SimulationResult, plan: ActionPlan, protect_payroll: bool) -> list[str]:
    """Check a simulated path against the §4 hard constraints a fixed plan can break."""
    out = []
    c_min, i_min, b_max = params.min_cash, params.min_inventory, params.revolver_limit
    t = _first_breach(res.cash, lambda c: c >= c_min - TOL)
    if t is not None:
        out.append(f"liquidity floor: C_{t} = {res.cash[t - 1]:.2f} < C_min = {c_min:.2f} (week {t})")
    t = _first_breach(res.revolver_balance, lambda b: -TOL <= b <= b_max + TOL)
    if t is not None:
        out.append(f"facility limit: B_{t} = {res.revolver_balance[t - 1]:.2f} > B-bar = {b_max:.2f} (week {t})")
    t = _first_breach(res.inventory, lambda i: i >= i_min - TOL)
    if t is not None:
        out.append(f"inventory floor: I_{t} = {res.inventory[t - 1]:.2f} < I_min = {i_min:.2f} (week {t})")
    b_end, b_0 = res.revolver_balance[-1], params.revolver_balance_0
    if b_end > b_0 + TOL:  # §4.7: borrowing that is never repaid would flatter the cash path
        out.append(f"terminal revolver: B_{res.horizon_weeks} = {b_end:.2f} > B_0 = {b_0:.2f}")
    if protect_payroll:
        z = plan.payroll_cut if isinstance(plan.payroll_cut, list) else [plan.payroll_cut] * res.horizon_weeks
        t = _first_breach(z, lambda share: share <= 0.0)
        if t is not None:
            out.append(f"protect payroll: z_{t} = {z[t - 1]} > 0 while protect-payroll mode is on (week {t})")
    # §4.4 (debt service paid in full) always holds: interest and amortization are fixed outflows in simulate().
    return out


def _evaluate_state(
    params: BusinessParams, shock: ScenarioShock, policy: Policy, outcome: Outcome, protect_payroll: bool
) -> StateOutcome:
    try:
        res = simulate(params, shock, policy.plan)
    except ValueError as exc:  # §3: financing that cannot happen is rejected, so the plan is infeasible here
        return StateOutcome(
            outcome=outcome, scenario_name=shock.name, simulated=False, value=None, value_week=None,
            feasible=False, violations=[f"rejected by the simulator: {exc}"], simulation=None,
        )
    violations = _violations(params, res, policy.plan, protect_payroll)
    return StateOutcome(
        outcome=outcome, scenario_name=shock.name, simulated=True, value=res.min_cash,
        value_week=res.min_cash_week, feasible=not violations, violations=violations, simulation=res,
    )


# --------------------------------------------------------------------------- §8 decision


def _check_probability(p_yes: float) -> float:
    if isinstance(p_yes, bool) or not isinstance(p_yes, int | float):
        raise ValueError(f"p_yes must be a number in [0, 1], got {p_yes!r}")
    p = float(p_yes)
    if not math.isfinite(p) or not 0.0 <= p <= 1.0:
        raise ValueError(f"p_yes must be a number in [0, 1], got {p_yes!r}")
    return p


def evaluate_policies(
    params: BusinessParams,
    shock_if_yes: ScenarioShock,
    shock_if_no: ScenarioShock,
    policies: list[Policy],
    p_yes: float,
    *,
    protect_payroll: bool = False,
) -> DecisionResult:
    """§8: payoffs V(a,1), V(a,0), E[V | a] for every policy, and the recommendation.

    V(a, y) = min_t C_t of simulate(params, shock_y, a.plan). E[V | a] = p V(a,1) + (1-p) V(a,0).

    Feasible in a state means the simulated path satisfies the §4 hard constraints a fixed plan can break:
    liquidity floor C_t >= C_min, facility limit 0 <= B_t <= B-bar, inventory floor I_t >= I_min (all t),
    terminal revolver B_T <= B_0 (§4.7), and, when protect_payroll is True, z_t = 0; dollar checks use a
    $1e-6 tolerance. A plan simulate() rejects is infeasible in that state and its V is NOT AVAILABLE (None).
    Not checked here: the action caps v_t <= v-bar and z_t <= z-bar (BusinessParams has no fields for them).

    The recommendation is the policy with the largest E[V] among those feasible in BOTH states, whatever p is
    (also at p = 0 or 1: a plan that breaks a hard constraint in the other state is never recommended). Ties
    within $1e-6 go to the policy listed first. If no policy is feasible in both states: "NO SAFE POLICY".

    Raises ValueError if p_yes is not in [0, 1], if there are no policies or duplicate names, or if
    params.min_cash / params.min_inventory are missing (feasibility cannot be judged without them).
    """
    p = _check_probability(p_yes)
    if not policies:
        raise ValueError("at least one policy is required")
    names = [pol.name for pol in policies]
    if len(set(names)) != len(names):
        raise ValueError(f"policy names must be distinct, got {names}")
    if params.min_cash is None or params.min_inventory is None:
        raise ValueError("params.min_cash (C_min) and params.min_inventory (I_min) are required to judge feasibility")

    evaluations = []
    for pol in policies:
        yes = _evaluate_state(params, shock_if_yes, pol, 1, protect_payroll)
        no = _evaluate_state(params, shock_if_no, pol, 0, protect_payroll)
        expected = None if yes.value is None or no.value is None else p * yes.value + (1.0 - p) * no.value
        evaluations.append(PolicyEvaluation(
            policy=pol, if_yes=yes, if_no=no, value_if_yes=yes.value, value_if_no=no.value,
            expected_value=expected, feasible_in_both=yes.feasible and no.feasible,
        ))

    best: PolicyEvaluation | None = None
    for ev in evaluations:
        if ev.feasible_in_both and (best is None or ev.expected_value > best.expected_value + TOL):
            best = ev
    return DecisionResult(
        p_yes=p,
        constraints_checked=_constraints(params, protect_payroll),
        policies=evaluations,
        recommendation=NO_SAFE_POLICY if best is None else best.policy.name,
        recommended=best,
    )


def regret(results: DecisionResult, y: int) -> RegretResult:
    """Realized regret after the reveal: max_{a'} V(a', y) - V(a, y), for every evaluated policy.

    Which policies are included: the benchmark max_{a'} V(a', y) is taken over every evaluated policy that
    is feasible in the REVEALED state y, including ones that were infeasible only in the other state. Reason:
    regret is a hindsight measure, so once y is known only the hard constraints of that state still matter,
    and an alternative that broke a hard constraint in y (floor, facility, inventory, terminal revolver, payroll
    protection, or rejected by the simulator) was never an acceptable way to end up with more cash. Hence every reported
    regret is >= 0. A policy infeasible in state y gets regret None (NOT AVAILABLE) with the breach as the note.
    If no policy is feasible in state y, every regret is None.
    """
    if isinstance(y, bool) or y not in (0, 1):
        raise ValueError(f"y must be the revealed outcome 0 or 1, got {y!r}")
    y = int(y)
    states = [(ev.policy.name, ev.if_yes if y == 1 else ev.if_no) for ev in results.policies]
    feasible_values = [s.value for _, s in states if s.feasible]
    best = max(feasible_values) if feasible_values else None

    rows = []
    for name, s in states:
        if not s.feasible:
            rows.append(PolicyRegret(
                policy_name=name, value=s.value, feasible_in_state=False, regret=None,
                note="NOT AVAILABLE: infeasible in the revealed state; " + "; ".join(s.violations),
            ))
        else:  # best is not None because this policy is feasible
            rows.append(PolicyRegret(
                policy_name=name, value=s.value, feasible_in_state=True, regret=best - s.value,
                note="max V(a', y) over policies feasible in the revealed state, minus V(a, y)",
            ))
    by_name = {r.policy_name: r for r in rows}
    return RegretResult(
        outcome=y,
        best_value=best,
        best_policies=[] if best is None else [r.policy_name for r in rows if r.feasible_in_state
                                                and r.value >= best - TOL],
        recommendation=results.recommendation,
        recommended_regret=None if results.recommended is None else by_name[results.recommendation].regret,
        policies=rows,
    )
