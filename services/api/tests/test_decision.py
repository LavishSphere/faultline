"""Hand-checked tests for core/decision.py (docs/MATH_MODEL.md §8: ACT / WAIT / HEDGE payoffs and regret).

Every expected number is derived by hand from the MATH_MODEL §3 recurrence; the arithmetic is written next to
the assertion so a finance reviewer can check it without code.

Worked example used throughout (MATH_MODEL §9 'Common' inputs, horizon T = 3 weeks so it fits on paper):
  C_0 = 100,000; S_base = S_0 = 50,000/wk; g = 0.35; a = 0.8; L_p = 1, P_0 = 32,500; W = 12,000; O = 6,000;
  D = 600,000 at 8% -> J = 600,000 * 0.08 / 52 = 923.077/wk; no revolver, capex or expansion.
  §10 floors: C_min = 25,000, I_min = 40,000; I_0 = 65,000; backup premium pi = 0.12, switching fee F_b = 2,000.
  Forecast event (YES, y = 1): the primary supplier is down in weeks 2-3 (kappa = 0, phi = 0.4, so lambda = 0.4).
  NO (y = 0): no shock.
  Policies: WAIT = no action; HEDGE = use the backup supplier (pay F_b up front, premium only if the outage hits).

Baseline weekly outflow with no shock = P 32,500 + W 12,000 + O 6,000 + J 923.077 = 51,423.077 against receipts
of 50,000, so cash falls 1,423.077 a week: C_1 = 98,576.923, C_2 = 97,153.846, C_3 = 95,730.769.
"""

from __future__ import annotations

import pytest

from core.decision import (
    NO_SAFE_POLICY,
    Policy,
    evaluate_policies,
    regret,
)
from core.financials import ActionPlan, BusinessParams, ScenarioShock, SupplierOutage, simulate

TOL = 1e-6
T = 3
J8 = 600_000 * 0.08 / 52  # 923.0769...
BURN = 32_500 + 12_000 + 6_000 + J8 - 50_000  # 1,423.077 per week with no shock

# Hand-computed V(a, y) = min_t C_t (in all four cells the minimum is at week 3):
#
# WAIT, NO:  C_3 = 100,000 - 3 * 1,423.077                                   = 95,730.769
# WAIT, YES: week 2 S_2 = 50k (1 - 0.4) = 30,000, R_2 = 0.8*30k + 0.2*50k = 34,000, pays P_1 = 32,500
#              C_2 = 98,576.923 + 34,000 - 51,423.077                          = 81,153.846
#            week 3 S_3 = 30,000, R_3 = 30,000, pays P_2 = 0.65*30k = 19,500
#              C_3 = 81,153.846 + 30,000 - (19,500 + 18,923.077)               = 72,730.769
#            i.e. 95,730.769 - 16,000 (R_2) - 20,000 (R_3) + 13,000 (smaller P_2) = 95,730.769 - 23,000
# HEDGE, NO: switching fee 2,000 in week 1, no premium (lambda = 0)
#              C_3 = 95,730.769 - 2,000                                        = 93,730.769
# HEDGE, YES: no lost sales; premium pi (1-g) S_dem lambda = 0.12*0.65*50k*0.4 = 1,560 in P_2 and P_3;
#             P_2 = 34,060 is paid in week 3 (P_3 falls after the horizon)
#              C_3 = 95,730.769 - 2,000 - 1,560                                = 92,170.769
V_WAIT_NO = 100_000 - 3 * BURN
V_WAIT_YES = V_WAIT_NO - 23_000
V_HEDGE_NO = V_WAIT_NO - 2_000
V_HEDGE_YES = V_WAIT_NO - 2_000 - 1_560


def params(**overrides) -> BusinessParams:
    base = dict(
        horizon_weeks=T,
        cash_0=100_000.0,
        stores=[{"name": "all stores", "base_sales": 50_000.0}],
        sales_0=50_000.0,
        gross_margin=0.35,
        same_week_collection=0.8,
        supplier_lag_weeks=1,
        prior_purchases=[32_500.0],
        inventory_0=65_000.0,
        payroll=12_000.0,
        opex=6_000.0,
        term_loan_principal_1=600_000.0,
        base_rate=0.08,
        revolver_balance_0=0.0,
        revolver_limit=150_000.0,
        revolver_spread=0.02,
        backup_premium=0.12,
        backup_switch_fee=2_000.0,
        min_cash=25_000.0,
        min_inventory=40_000.0,
    )
    base.update(overrides)
    return BusinessParams.model_validate(base)


OUTAGE = ScenarioShock(
    name="supplier outage weeks 2-3",
    supplier=SupplierOutage(availability=[1.0, 0.0, 0.0], dependent_share=0.4),
)
NO_SHOCK = ScenarioShock(name="no outage")
WAIT = Policy(name="WAIT", description="no action", plan=ActionPlan())
HEDGE = Policy(name="HEDGE", description="use the backup supplier", plan=ActionPlan(use_backup_supplier=True))


def approx(x):
    return pytest.approx(x, abs=TOL)


def by_name(result, name):
    return next(ev for ev in result.policies if ev.policy.name == name)


# ---------------------------------------------------------------- hand-checked 2-policy example


def test_hand_checked_two_policy_example():
    res = evaluate_policies(params(), OUTAGE, NO_SHOCK, [WAIT, HEDGE], p_yes=0.3)
    wait, hedge = by_name(res, "WAIT"), by_name(res, "HEDGE")

    assert wait.value_if_no == approx(95_730.769231)
    assert wait.value_if_yes == approx(72_730.769231)
    assert hedge.value_if_no == approx(93_730.769231)
    assert hedge.value_if_yes == approx(92_170.769231)
    assert (wait.value_if_no, wait.value_if_yes) == (approx(V_WAIT_NO), approx(V_WAIT_YES))
    assert (hedge.value_if_no, hedge.value_if_yes) == (approx(V_HEDGE_NO), approx(V_HEDGE_YES))
    assert all(s.value_week == 3 for ev in (wait, hedge) for s in (ev.if_yes, ev.if_no))

    # E[V | WAIT]  = 0.3 * 72,730.769 + 0.7 * 95,730.769 = 95,730.769 - 0.3 * 23,000 = 88,830.769
    # E[V | HEDGE] = 0.3 * 92,170.769 + 0.7 * 93,730.769 = 93,730.769 - 0.3 * 1,560  = 93,262.769
    assert wait.expected_value == approx(88_830.769231)
    assert hedge.expected_value == approx(93_262.769231)

    # Both stay above C_min = 25,000 and I_0 = 65,000 >= I_min in both states, so both are safe.
    assert wait.feasible_in_both and hedge.feasible_in_both
    assert res.recommendation == "HEDGE"
    assert res.recommended.policy.name == "HEDGE"
    assert res.p_yes == 0.3
    assert res.provenance == "SIMULATED"
    assert all(ev.provenance == "SIMULATED" for ev in res.policies)


def test_break_even_probability():
    # WAIT beats HEDGE when 95,730.769 - 23,000 p > 93,730.769 - 1,560 p, i.e. p < 2,000 / 21,440 = 0.093284
    p_star = 2_000 / 21_440
    assert evaluate_policies(params(), OUTAGE, NO_SHOCK, [WAIT, HEDGE], p_star - 0.001).recommendation == "WAIT"
    assert evaluate_policies(params(), OUTAGE, NO_SHOCK, [WAIT, HEDGE], p_star + 0.001).recommendation == "HEDGE"


def test_payoffs_come_from_simulate():
    res = evaluate_policies(params(), OUTAGE, NO_SHOCK, [WAIT, HEDGE], p_yes=0.5)
    for ev in res.policies:
        assert ev.value_if_yes == simulate(params(), OUTAGE, ev.policy.plan).min_cash
        assert ev.value_if_no == simulate(params(), NO_SHOCK, ev.policy.plan).min_cash
        assert ev.if_yes.simulation.cash == simulate(params(), OUTAGE, ev.policy.plan).cash
        assert ev.if_yes.simulation.provenance == "SIMULATED"


# ---------------------------------------------------------------- p = 0 and p = 1


def test_p_zero_uses_only_the_no_state():
    res = evaluate_policies(params(), OUTAGE, NO_SHOCK, [WAIT, HEDGE], p_yes=0.0)
    # E[V] = V(a, 0): WAIT 95,730.769 > HEDGE 93,730.769
    assert by_name(res, "WAIT").expected_value == approx(V_WAIT_NO)
    assert by_name(res, "HEDGE").expected_value == approx(V_HEDGE_NO)
    assert res.recommendation == "WAIT"


def test_p_one_uses_only_the_yes_state():
    res = evaluate_policies(params(), OUTAGE, NO_SHOCK, [WAIT, HEDGE], p_yes=1)
    # E[V] = V(a, 1): HEDGE 92,170.769 > WAIT 72,730.769
    assert by_name(res, "WAIT").expected_value == approx(V_WAIT_YES)
    assert by_name(res, "HEDGE").expected_value == approx(V_HEDGE_YES)
    assert res.recommendation == "HEDGE"


# ---------------------------------------------------------------- feasibility


def test_policy_infeasible_in_one_state_is_never_recommended():
    # C_min = 75,000: WAIT breaks the floor only if the outage hits (C_3 = 72,730.769 < 75,000).
    # At p = 0 WAIT has the highest E[V] (95,730.769 vs 93,730.769) but must not be recommended.
    for p in (0.0, 0.05, 0.3, 1.0):
        res = evaluate_policies(params(min_cash=75_000.0), OUTAGE, NO_SHOCK, [WAIT, HEDGE], p)
        wait = by_name(res, "WAIT")
        assert wait.if_no.feasible and not wait.if_yes.feasible and not wait.feasible_in_both
        assert "liquidity floor: C_3 = 72730.77 < C_min = 75000.00 (week 3)" in wait.if_yes.violations
        assert res.recommendation == "HEDGE"
    res0 = evaluate_policies(params(min_cash=75_000.0), OUTAGE, NO_SHOCK, [WAIT, HEDGE], 0.0)
    assert by_name(res0, "WAIT").expected_value > by_name(res0, "HEDGE").expected_value


def test_no_safe_policy():
    # C_min = 95,000: WAIT breaks it if YES (72,730.769), HEDGE breaks it if NO (93,730.769).
    res = evaluate_policies(params(min_cash=95_000.0), OUTAGE, NO_SHOCK, [WAIT, HEDGE], p_yes=0.5)
    assert not any(ev.feasible_in_both for ev in res.policies)
    assert res.recommendation == NO_SAFE_POLICY == "NO SAFE POLICY"
    assert res.recommended is None
    # payoffs are still reported so the UI can show how far each policy falls short
    assert by_name(res, "HEDGE").expected_value == approx(0.5 * V_HEDGE_YES + 0.5 * V_HEDGE_NO)


def test_facility_limit_breach_is_infeasible():
    big_draw = Policy(name="DRAW", plan=ActionPlan(revolver_draw=[160_000.0, 0.0, 0.0]))  # B_1 = 160k > 150k
    res = evaluate_policies(params(), OUTAGE, NO_SHOCK, [big_draw, WAIT], p_yes=0.5)
    draw = by_name(res, "DRAW")
    assert not draw.if_yes.feasible and not draw.if_no.feasible
    assert any(v.startswith("facility limit: B_1 = 160000.00") for v in draw.if_no.violations)
    assert res.recommendation == "WAIT"


def test_terminal_revolver_must_be_repaid():
    # §4.7 B_T <= B_0 = 0. Draw y_1 = 10,000; revolver interest J^R = 10,000 * (0.08 + 0.02) / 52 = 19.231
    # in weeks 2 and 3 (charged on B_{t-1}).
    jr = 10_000 * 0.10 / 52
    keep = Policy(name="KEEP", plan=ActionPlan(revolver_draw=[10_000.0, 0.0, 0.0]))
    repay = Policy(name="REPAY", plan=ActionPlan(revolver_draw=[10_000.0, 0.0, 0.0],
                                                 revolver_repay=[0.0, 0.0, 10_000.0]))
    res = evaluate_policies(params(), OUTAGE, NO_SHOCK, [keep, repay, WAIT], p_yes=0.0)
    k, r = by_name(res, "KEEP"), by_name(res, "REPAY")
    # KEEP, NO: C_3 = 95,730.769 + 10,000 - 2 * 19.231 = 105,692.308 (B_3 = 10,000 still owed)
    assert k.value_if_no == approx(V_WAIT_NO + 10_000 - 2 * jr)
    assert "terminal revolver: B_3 = 10000.00 > B_0 = 0.00" in k.if_no.violations
    assert not k.feasible_in_both
    # REPAY, NO: C_3 = 95,730.769 - 2 * 19.231 = 95,692.308; B_3 = 0, so it is feasible
    assert r.value_if_no == approx(V_WAIT_NO - 2 * jr)
    assert r.feasible_in_both
    # KEEP has the highest E[V] (borrowed cash it never repays), but WAIT (95,730.769) is the best safe policy
    assert res.recommendation == "WAIT"


def test_inventory_floor_breach_is_infeasible():
    # v_1 = 30,000: I_1 = 65,000 - 30,000 = 35,000 < I_min = 40,000
    cut = Policy(name="CUT", plan=ActionPlan(purchase_cut=[30_000.0, 0.0, 0.0]))
    res = evaluate_policies(params(), OUTAGE, NO_SHOCK, [cut, WAIT], p_yes=0.5)
    ev = by_name(res, "CUT")
    assert not ev.feasible_in_both
    assert "inventory floor: I_1 = 35000.00 < I_min = 40000.00 (week 1)" in ev.if_no.violations
    # the cut adds 30,000 to C_2 and C_3, so its E[V] beats WAIT, yet it is not recommended
    assert ev.expected_value > by_name(res, "WAIT").expected_value
    assert res.recommendation == "WAIT"


def test_protect_payroll_mode():
    trim = Policy(name="TRIM", plan=ActionPlan(payroll_cut=[0.0, 0.1, 0.0]))
    off = evaluate_policies(params(), OUTAGE, NO_SHOCK, [trim, WAIT], p_yes=0.5)
    assert by_name(off, "TRIM").feasible_in_both  # cutting payroll is allowed outside protect-payroll mode
    assert off.recommendation == "TRIM"  # 1,200 of payroll saved in week 2 raises min cash
    on = evaluate_policies(params(), OUTAGE, NO_SHOCK, [trim, WAIT], p_yes=0.5, protect_payroll=True)
    ev = by_name(on, "TRIM")
    assert not ev.if_yes.feasible and not ev.if_no.feasible
    assert "protect payroll: z_2 = 0.1 > 0 while protect-payroll mode is on (week 2)" in ev.if_yes.violations
    assert on.recommendation == "WAIT"
    assert "protect payroll: z_t = 0 for all t" in on.constraints_checked


def test_plan_rejected_by_simulator_is_infeasible_and_not_available():
    # repay 1,000 with B_0 = 0: simulate() raises, so V is NOT AVAILABLE in both states
    bad = Policy(name="BAD", plan=ActionPlan(revolver_repay=[1_000.0, 0.0, 0.0]))
    res = evaluate_policies(params(), OUTAGE, NO_SHOCK, [bad, WAIT], p_yes=0.5)
    ev = by_name(res, "BAD")
    assert not ev.if_yes.simulated and ev.if_yes.simulation is None
    assert ev.value_if_yes is None and ev.value_if_no is None and ev.expected_value is None
    assert ev.if_no.violations[0].startswith("rejected by the simulator: week 1: revolver repayment")
    assert res.recommendation == "WAIT"
    after = regret(res, 1)
    assert next(r for r in after.policies if r.policy_name == "BAD").regret is None


def test_ties_go_to_the_policy_listed_first():
    same = Policy(name="WAIT TOO", plan=ActionPlan())
    assert evaluate_policies(params(), OUTAGE, NO_SHOCK, [WAIT, same], 0.5).recommendation == "WAIT"
    assert evaluate_policies(params(), OUTAGE, NO_SHOCK, [same, WAIT], 0.5).recommendation == "WAIT TOO"


# ---------------------------------------------------------------- regret after reveal


def test_regret_outage_happened():
    res = evaluate_policies(params(), OUTAGE, NO_SHOCK, [WAIT, HEDGE], p_yes=0.3)
    r = regret(res, 1)
    rows = {row.policy_name: row for row in r.policies}
    # best V(a', 1) = HEDGE 92,170.769; WAIT regret = 92,170.769 - 72,730.769 = 19,440 (= 23,000 - 3,560)
    assert r.best_value == approx(V_HEDGE_YES)
    assert r.best_policies == ["HEDGE"]
    assert rows["WAIT"].regret == approx(19_440.0)
    assert rows["HEDGE"].regret == approx(0.0)
    assert r.recommendation == "HEDGE" and r.recommended_regret == approx(0.0)
    assert r.provenance == "SIMULATED"


def test_regret_outage_did_not_happen():
    res = evaluate_policies(params(), OUTAGE, NO_SHOCK, [WAIT, HEDGE], p_yes=0.3)
    r = regret(res, 0)
    rows = {row.policy_name: row for row in r.policies}
    # best V(a', 0) = WAIT 95,730.769; HEDGE regret = the 2,000 switching fee it paid for nothing
    assert r.best_value == approx(V_WAIT_NO)
    assert rows["HEDGE"].regret == approx(2_000.0)
    assert rows["WAIT"].regret == approx(0.0)
    assert r.recommended_regret == approx(2_000.0)


def test_regret_skips_policies_infeasible_in_the_revealed_state():
    res = evaluate_policies(params(min_cash=75_000.0), OUTAGE, NO_SHOCK, [WAIT, HEDGE], p_yes=0.3)
    # y = 1: WAIT broke the floor, so it is not a benchmark and its regret is NOT AVAILABLE
    r1 = regret(res, 1)
    rows1 = {row.policy_name: row for row in r1.policies}
    assert rows1["WAIT"].regret is None and not rows1["WAIT"].feasible_in_state
    assert rows1["WAIT"].note.startswith("NOT AVAILABLE")
    assert rows1["HEDGE"].regret == approx(0.0)
    # y = 0: WAIT was within the floor in this state, so it is the hindsight benchmark (HEDGE regret 2,000)
    r0 = regret(res, 0)
    assert r0.best_policies == ["WAIT"]
    assert {row.policy_name: row.regret for row in r0.policies}["HEDGE"] == approx(2_000.0)


def test_regret_when_nothing_is_feasible_in_the_revealed_state():
    # C_min = 95,000 and y = 1: both policies end below 95,000, so no benchmark exists
    res = evaluate_policies(params(min_cash=95_000.0), OUTAGE, NO_SHOCK, [WAIT, HEDGE], p_yes=0.5)
    r = regret(res, 1)
    assert r.best_value is None and r.best_policies == []
    assert all(row.regret is None for row in r.policies)
    assert r.recommended_regret is None


def test_regret_is_never_negative():
    for p in (0.0, 0.3, 1.0):
        res = evaluate_policies(params(), OUTAGE, NO_SHOCK, [WAIT, HEDGE], p)
        for y in (0, 1):
            assert all(row.regret >= 0.0 for row in regret(res, y).policies)


# ---------------------------------------------------------------- input validation


@pytest.mark.parametrize("bad", [-0.1, 1.1, float("nan"), float("inf"), float("-inf"), True, None, "0.5"])
def test_invalid_probability_is_rejected(bad):
    with pytest.raises(ValueError, match="p_yes"):
        evaluate_policies(params(), OUTAGE, NO_SHOCK, [WAIT, HEDGE], bad)


@pytest.mark.parametrize("bad", [-1, 2, 0.5, True, None])
def test_invalid_outcome_is_rejected(bad):
    res = evaluate_policies(params(), OUTAGE, NO_SHOCK, [WAIT, HEDGE], 0.5)
    with pytest.raises(ValueError, match="y must be"):
        regret(res, bad)


def test_policy_list_must_be_nonempty_with_distinct_names():
    with pytest.raises(ValueError):
        evaluate_policies(params(), OUTAGE, NO_SHOCK, [], 0.5)
    with pytest.raises(ValueError, match="distinct"):
        evaluate_policies(params(), OUTAGE, NO_SHOCK, [WAIT, Policy(name="WAIT", plan=ActionPlan())], 0.5)
    with pytest.raises(ValueError):
        Policy(name="", plan=ActionPlan())


def test_floors_are_required_to_judge_feasibility():
    with pytest.raises(ValueError, match="min_cash"):
        evaluate_policies(params(min_cash=None), OUTAGE, NO_SHOCK, [WAIT], 0.5)
    with pytest.raises(ValueError, match="min_inventory"):
        evaluate_policies(params(min_inventory=None), OUTAGE, NO_SHOCK, [WAIT], 0.5)


def test_deterministic():
    a = evaluate_policies(params(), OUTAGE, NO_SHOCK, [WAIT, HEDGE], 0.3)
    b = evaluate_policies(params(), OUTAGE, NO_SHOCK, [WAIT, HEDGE], 0.3)
    assert a.model_dump() == b.model_dump()
