"""Tests for core/optimizer.py: the MATH_MODEL §4 recovery MILP.

The 3-week cases are hand-checked: every input is stated and every expected number is derived in the comments from the
§3 recurrence, so a finance reviewer can check them without code. The demo-business cases use data/demo_business.json
(SYNTHETIC) and check what can be derived by hand (totals, min cash); the agreement test re-simulates every chosen plan
with core.financials.simulate() and requires the same cash, revolver and inventory paths to 1e-6.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from types import SimpleNamespace

import pytest

import core.optimizer as optimizer_module
from core.financials import ActionPlan, BusinessParams, DemandShock, ScenarioShock, SupplierOutage, simulate
from core.optimizer import (
    NO_FEASIBLE_PLAN,
    OPTIMAL,
    SOLVER_ERROR,
    DisruptionCosts,
    OptimizationResult,
    OptimizerSettings,
    optimize,
)

TOL = 1e-6
DATA = Path(__file__).resolve().parent.parent / "data"
DEMO_DOC = json.loads((DATA / "demo_business.json").read_text(encoding="utf-8"))
DEMO = BusinessParams.model_validate(DEMO_DOC["business"])
SCENARIOS = {
    s["id"]: ScenarioShock.model_validate(s["shock"])
    for s in json.loads((DATA / "scenarios.json").read_text(encoding="utf-8"))["scenarios"]
}

# MATH_MODEL §10 optimizer settings, written out explicitly (not taken from the defaults).
SEC10 = OptimizerSettings(
    purchase_cut_cap_per_week=10_000.0,  # v-bar
    payroll_cut_cap=0.10,  # z-bar
    tie_break_epsilon=1e-4,  # epsilon
    disruption_costs=DisruptionCosts(
        revolver_draw_per_dollar=0.01,  # c_y
        purchase_cut_per_dollar=0.05,  # c_v
        defer_capex_per_decision=1_000.0,  # c_c
        backup_supplier_per_decision=2_500.0,  # c_b
        delay_expansion_per_decision=5_000.0,  # c_e
        payroll_cut_per_dollar=5.0,  # c_z
    ),
)
BASELINE = ScenarioShock(name="baseline")


def approx(x):
    return pytest.approx(x, abs=TOL)


def run(params: BusinessParams, shock: ScenarioShock, protect: bool, settings: OptimizerSettings = SEC10):
    return optimize(params, shock, protect, settings)


# ---------------------------------------------------------------- settings


def test_settings_from_dict_with_fixture_keys():
    section = {
        "purchase_cut_cap_per_week": 10000.0,
        "payroll_cut_cap": 0.1,
        "tie_break_epsilon": 0.0001,
        "disruption_costs": {
            "revolver_draw_per_dollar": 0.01,
            "purchase_cut_per_dollar": 0.05,
            "defer_capex_per_decision": 1000.0,
            "backup_supplier_per_decision": 2500.0,
            "delay_expansion_per_decision": 5000.0,
            "payroll_cut_per_dollar": 5.0,
        },
    }
    assert OptimizerSettings.from_dict(section) == SEC10


def test_settings_from_fixture_section_ignores_only_documentation_keys():
    # data/demo_business.json carries "note" and "symbols" next to the values; those are documentation.
    assert OptimizerSettings.from_dict(DEMO_DOC["optimizer_parameters"]) == SEC10
    with pytest.raises(ValueError):  # a typo is not silently ignored
        OptimizerSettings.from_dict({"purchase_cut_cap_per_wk": 5_000.0})


def test_settings_defaults_are_section_10():
    assert OptimizerSettings() == SEC10


def test_floors_are_required():
    params = DEMO.model_copy(update={"min_cash": None})
    with pytest.raises(ValueError):
        run(params, BASELINE, False)


# ---------------------------------------------------------------- hand-checkable 3-week case
#
# Inputs (MATH_MODEL §9 "Common", horizon T = 3):
#   C_0 = 100,000; one store with S^base = 50,000/wk; S_0 = 50,000; g = 0.35; a = 0.8; L_p = 1; P_0 = 32,500;
#   W = 12,000; O = 6,000; D = 600,000 at r = 8%, A = 0; no capex, expansion or outage.
#   Revolver: B_0 = 0, B-bar = 150,000 (case-specific below), s_R = 2% so J^R_t = B_{t-1} x 10% / 52.
#   I_0 = 60,000, I_min = 40,000 (case-specific below). C_min = 90,000. Backup: pi = 0.12, F_b = 2,000.
#   Shock: §9 Case B, 20% demand drop in week 2 only.
#   Settings: §10 (c_y 0.01, c_v 0.05, c_z 5.00 per $, epsilon 1e-4, v-bar 10,000, z-bar 0.10).
#
# With no action (§9 Case B): C_1 = 98,576.923, C_2 = 89,153.846, C_3 = 92,230.769.
# So week 2 is 90,000 - 89,153.846 = 846.154 below the floor; weeks 1 and 3 are above it.
# Levers that raise C_2: a draw y_2 (harm 0.01/$; repaid in week 3 because B_3 <= B_0 = 0), a purchase cut v_1
# (harm 0.05/$; with L_p = 1 it lowers the week-2 payment P_1), or a payroll cut in week 1 or 2 (harm 5/$).
# A draw in week 1 does not help more than one in week 2 (B_2 <= B-bar either way) and adds interest in week 2.

J8 = 600_000 * 0.08 / 52  # 923.077 term-loan interest per week
NO_ACTION_C = (98_576.923077, 89_153.846154, 92_230.769231)
SHORT_WEEK_2 = 90_000 - NO_ACTION_C[1]  # 846.153846


def three_week_params(**overrides) -> BusinessParams:
    base = dict(
        horizon_weeks=3,
        cash_0=100_000.0,
        stores=[{"name": "all stores", "base_sales": 50_000.0}],
        sales_0=50_000.0,
        gross_margin=0.35,
        same_week_collection=0.8,
        supplier_lag_weeks=1,
        prior_purchases=[32_500.0],
        inventory_0=60_000.0,
        payroll=12_000.0,
        opex=6_000.0,
        term_loan_principal_1=600_000.0,
        base_rate=0.08,
        revolver_balance_0=0.0,
        revolver_limit=150_000.0,
        revolver_spread=0.02,
        backup_premium=0.12,
        backup_switch_fee=2_000.0,
        min_cash=90_000.0,
        min_inventory=40_000.0,
    )
    base.update(overrides)
    return BusinessParams.model_validate(base)


CASE_B = ScenarioShock(name="20% drop week 2", demand=DemandShock(delta=0.2, start_week=2, end_week=2))


def test_three_week_no_action_path_matches_section_9_case_b():
    res = simulate(three_week_params(), CASE_B, ActionPlan())
    assert res.cash == [approx(c) for c in NO_ACTION_C]


def test_three_week_revolver_covers_the_dip():
    res = run(three_week_params(), CASE_B, protect=False)
    assert res.status == OPTIMAL
    # The cheapest lever is the revolver: draw exactly the gap in week 2, repay it in week 3.
    assert res.plan.revolver_draw == [approx(0.0), approx(SHORT_WEEK_2), approx(0.0)]
    assert res.plan.revolver_repay == [approx(0.0), approx(0.0), approx(SHORT_WEEK_2)]
    assert res.plan.purchase_cut == [approx(0.0)] * 3
    assert res.plan.payroll_cut == [approx(0.0)] * 3
    # C_2 = 89,153.846 + 846.154 = 90,000.
    # C_3 = 92,230.769 + y_2 - q_3 - J^R_3, J^R_3 = 846.154 x 0.10 / 52 = 1.627219 -> 92,229.142012.
    assert res.cash == [approx(98_576.923077), approx(90_000.0), approx(92_229.142012)]
    assert res.revolver_balance == [approx(0.0), approx(SHORT_WEEK_2), approx(0.0)]
    assert res.min_cash == approx(90_000.0)
    assert res.min_cash_week == 2
    # Objective = c_y x 846.153846 - epsilon x mu = 8.461538 - 0.0001 x 90,000 = -0.538462.
    assert res.objective == approx(-0.538462)
    assert res.disruption_cost == approx(8.461538)
    assert res.binding_constraints == ["liquidity floor, week 2", "terminal revolver"]


def test_three_week_facility_limit_then_purchase_cut():
    # B-bar = 500: the revolver covers 500 of the 846.154 gap; the next cheapest lever is a week-1 purchase cut
    # v_1 = 346.154 (0.05/$, versus 5/$ for payroll).
    res = run(three_week_params(revolver_limit=500.0), CASE_B, protect=False)
    assert res.status == OPTIMAL
    assert res.plan.revolver_draw == [approx(0.0), approx(500.0), approx(0.0)]
    assert res.plan.revolver_repay == [approx(0.0), approx(0.0), approx(500.0)]
    assert res.plan.purchase_cut == [approx(346.153846), approx(0.0), approx(0.0)]
    assert res.plan.payroll_cut == [approx(0.0)] * 3
    # C_2 = 89,153.846 + 500 + 346.154 = 90,000.
    # C_3 = 92,230.769 + v_1 + y_2 - q_3 - J^R_3, J^R_3 = 500 x 0.10 / 52 = 0.961538 -> 92,575.961538.
    assert res.cash == [approx(98_576.923077), approx(90_000.0), approx(92_575.961538)]
    assert max(res.revolver_balance) <= 500.0 + TOL
    # I_t = I_{t-1} - v_t: 60,000 - 346.154 = 59,653.846 in weeks 1-3.
    assert res.inventory == [approx(59_653.846154)] * 3
    # Objective = 0.01 x 500 + 0.05 x 346.153846 - 9 = 5 + 17.307692 - 9 = 13.307692.
    assert res.objective == approx(13.307692)
    assert res.binding_constraints == ["liquidity floor, week 2", "facility limit, week 2", "terminal revolver"]


def test_three_week_payroll_only_case_and_protect_payroll():
    # B-bar = 500 and I_min = 59,800, so purchase cuts are capped at I_0 - I_min = 200 in total.
    # Gap left after the revolver (500) and the purchase cut (200): 846.154 - 700 = 146.154, and only a payroll cut
    # can close it (no outage, capex or expansion to act on).
    params = three_week_params(revolver_limit=500.0, min_inventory=59_800.0)

    allowed = run(params, CASE_B, protect=False)
    assert allowed.status == OPTIMAL
    assert allowed.plan.purchase_cut == [approx(200.0), approx(0.0), approx(0.0)]
    assert allowed.plan.revolver_draw == [approx(0.0), approx(500.0), approx(0.0)]
    # A payroll cut in week 1 or week 2 raises C_2 by the same amount at the same harm, so only the total is fixed:
    # z_1 W + z_2 W = 146.153846, z_3 = 0 (week 3 is not short).
    payroll_cut_dollars = [z * 12_000.0 for z in allowed.plan.payroll_cut]
    assert sum(payroll_cut_dollars[:2]) == approx(146.153846)
    assert payroll_cut_dollars[2] == approx(0.0)
    assert [a.action for a in allowed.actions].count("payroll_cut") >= 1
    # C_2 = 89,153.846 + 500 + 200 + 146.154 = 90,000; C_3 = 92,230.769 + 846.154 - 500 - 0.961538 = 92,575.961538.
    assert allowed.cash[1:] == [approx(90_000.0), approx(92_575.961538)]
    # Objective = 0.01 x 500 + 0.05 x 200 + 5 x 146.153846 - 9 = 5 + 10 + 730.769231 - 9 = 736.769231.
    assert allowed.objective == approx(736.769231)
    for name in ("liquidity floor, week 2", "facility limit, week 2", "inventory floor, week 1",
                 "inventory floor, week 3", "terminal revolver"):
        assert name in allowed.binding_constraints

    protected = run(params, CASE_B, protect=True)
    assert protected.status == NO_FEASIBLE_PLAN
    assert protected.plan is None and protected.cash is None and protected.actions is None
    # Best possible C_2 without payroll cuts: 89,153.846 + 500 + 200 = 89,853.846, and C_1, C_3 are higher.
    assert protected.max_feasible_cash_floor == approx(89_853.846154)
    assert "$89,853.85" in protected.diagnostic  # display text only; the field above is unrounded


def test_terminal_revolver_blocks_borrow_and_never_repay():
    # No shock, C_min = 96,000, purchase cuts switched off (v-bar = 0), payroll protected.
    # No action: C_3 = 100,000 - 3 x 1,423.077 = 95,730.769, short by 269.231 in week 3 only.
    # A week-3 draw of 269.231 would fix it, but §4.7 needs B_3 <= B_0 = 0, so it must be repaid in the same horizon
    # and adds nothing. No feasible plan; the best floor is the no-action C_3 (draws only add interest).
    settings = SEC10.model_copy(update={"purchase_cut_cap_per_week": 0.0})
    res = run(three_week_params(min_cash=96_000.0), BASELINE, protect=True, settings=settings)
    assert res.status == NO_FEASIBLE_PLAN
    assert res.max_feasible_cash_floor == approx(100_000 - 3 * (51_423.076923 - 50_000))  # 95,730.769231


def _three_week_slump() -> ScenarioShock:
    return ScenarioShock(name="90% drop weeks 1-2", demand=DemandShock(delta=0.9, start_week=1, end_week=2))


def test_three_week_purchases_cannot_go_negative():
    # §3 physical rule (issue #39, finance-owner decision on PR #69): P_t >= 0, so a cut v_t cannot exceed that week's
    # purchases. Same 3-week inputs as above, but a 90% drop in weeks 1-2, no revolver (B-bar = 0), C_min = 50,000.
    # S_1 = S_2 = 5,000, so purchases before any cut are P_1 = P_2 = 0.65 x 5,000 = 3,250.
    # No action:
    #   C_1 = 100,000 + (0.8 x 5,000 + 0.2 x 50,000 = 14,000) - P_0 32,500 - 18,923.077 = 62,576.923
    #   C_2 = 62,576.923 + (0.8 x 5,000 + 0.2 x 5,000 = 5,000) - P_1 3,250 - 18,923.077 = 45,403.846
    #   C_3 = 45,403.846 + (0.8 x 50,000 + 0.2 x 5,000 = 41,000) - P_2 3,250 - 18,923.077 = 64,230.769
    # Week 2 is 4,596.154 short. Only v_1 (paid in week 2) or a payroll cut in week 1 or 2 can raise C_2.
    # Without the rule the cheapest plan was v_1 = 4,596.154, i.e. P_1 = -1,346.154: impossible.
    # With it: v_1 = 3,250 (P_1 = 0) and the remaining 1,346.154 from payroll (harm 5/$).
    params = three_week_params(revolver_limit=0.0, min_cash=50_000.0)
    no_action = simulate(params, _three_week_slump(), ActionPlan())
    assert no_action.cash == [approx(62_576.923077), approx(45_403.846154), approx(64_230.769231)]
    assert no_action.purchases[:2] == [approx(3_250.0), approx(3_250.0)]

    allowed = run(params, _three_week_slump(), protect=False)
    assert allowed.status == OPTIMAL
    assert allowed.plan.purchase_cut == [approx(3_250.0), approx(0.0), approx(0.0)]
    sim = simulate(params, _three_week_slump(), allowed.plan)  # accepted: no negative purchases
    assert sim.purchases[0] == approx(0.0)
    assert min(sim.purchases) >= -TOL
    payroll_cut_dollars = [z * 12_000.0 for z in allowed.plan.payroll_cut]
    assert sum(payroll_cut_dollars[:2]) == approx(1_346.153846)  # week 1 or 2, same harm; only the total is fixed
    assert payroll_cut_dollars[2] == approx(0.0)
    # C_2 = 45,403.846 + 3,250 + 1,346.154 = 50,000; C_3 = 64,230.769 + 3,250 + 1,346.154 = 68,826.923.
    assert allowed.cash[1:] == [approx(50_000.0), approx(68_826.923077)]
    # Objective = 0.05 x 3,250 + 5 x 1,346.153846 - 0.0001 x 50,000 = 162.50 + 6,730.769231 - 5 = 6,888.269231.
    assert allowed.objective == approx(6_888.269231)
    assert "purchases non-negative, week 1" in allowed.binding_constraints
    assert "liquidity floor, week 2" in allowed.binding_constraints

    protected = run(params, _three_week_slump(), protect=True)
    assert protected.status == NO_FEASIBLE_PLAN
    # Best C_2 without payroll: 45,403.846 + 3,250 = 48,653.846.
    assert protected.max_feasible_cash_floor == approx(48_653.846154)


def test_negative_inventory_minimum_never_allows_negative_stock():
    # §4.3 bound is max(I_min, 0). Facility-limit inputs (B-bar = 500, gap after the revolver 346.154), but only
    # I_0 = 100 of stock and I_min = -10,000. A cut can remove at most the 100 in stock (I_1 = 0), so the other
    # 246.154 must come from payroll (weeks 1-2, harm 5/$); without the 0 bound the solver would cut 346.154 and leave
    # I_1 = -246.154, which simulate() rejects.
    params = three_week_params(revolver_limit=500.0, inventory_0=100.0, min_inventory=-10_000.0)
    res = run(params, CASE_B, protect=False)
    assert res.status == OPTIMAL
    assert res.plan.purchase_cut == [approx(100.0), approx(0.0), approx(0.0)]
    assert res.inventory == [approx(0.0)] * 3
    assert sum(z * 12_000.0 for z in res.plan.payroll_cut[:2]) == approx(246.153846)
    assert "inventory floor, week 1" in res.binding_constraints
    sim = simulate(params, CASE_B, res.plan)  # accepted: no negative stock
    assert min(sim.inventory) >= -TOL
    assert res.cash == [approx(c) for c in sim.cash]


def test_infeasible_without_any_floor_reports_not_available():
    # I_0 = 60,000 below I_min = 70,000: no plan exists even with the liquidity floor removed.
    res = run(three_week_params(min_inventory=70_000.0), CASE_B, protect=False)
    assert res.status == NO_FEASIBLE_PLAN
    assert res.max_feasible_cash_floor is None
    assert res.diagnostic.startswith("NOT AVAILABLE")


# ---------------------------------------------------------------- demo business (SYNTHETIC, §10 values)


def test_feasible_baseline_picks_no_costly_actions():
    for protect in (False, True):
        res = run(DEMO, BASELINE, protect)
        assert res.status == OPTIMAL
        assert res.actions == []
        assert res.plan == ActionPlan(
            purchase_cut=[0.0] * 26, revolver_draw=[0.0] * 26, revolver_repay=[0.0] * 26, payroll_cut=[0.0] * 26
        )
        assert res.disruption_cost == approx(0.0)
        # §10: with no shock, cash falls 1,423.077/wk to 63,000 at week 26, above C_min = 25,000.
        assert res.min_cash == approx(63_000.0)
        assert res.min_cash_week == 26
        assert res.objective == approx(-1e-4 * 63_000.0)
        assert res.binding_constraints == []


def test_named_scenarios_above_the_floor_need_no_action():
    # From tests/test_scenarios.py (hand-checked): no-action min cash 57,000 / 36,750 / 42,000, all above 25,000.
    for sid in ("rate-plus-200bp", "demand-drop-20pct-6wk", "supplier-outage-3wk"):
        res = run(DEMO, SCENARIOS[sid], protect=True)
        assert res.status == OPTIMAL
        assert res.actions == []


# Stock-out cost (issue #103, MATH_MODEL §3, §10): every purchase cut leaves the demo business below its service level
# I^svc = 65,000 for the rest of the horizon and loses 0.20 of sales per $ cut per week. The cut itself is paid back
# two weeks later (L_p = 2), so a cut v in week w <= 24 raises C_26 by v minus the stock-out cost
# 0.20 v (0.35 (25 - w) + 1.0 + 0.8)  (lost sales cost 0.35 once settled, 1.0 in week 25, 0.8 in week 26):
#   net per $: week 22 -> 1 - 0.57 = 0.43;  week 23 -> 1 - 0.50 = 0.50;  week 24 -> 1 - 0.43 = 0.57.
# Earlier cuts net less (week 18 -> 1 - 0.71 = 0.29), so the optimizer cuts as late as possible and bridges the earlier
# weeks with the revolver. Lost sales after week 26 are not counted (MATH_MODEL §10 "Known limits").
NET_PER_DOLLAR = {w: 1.0 - 0.2 * (0.35 * (25 - w) + 1.8) for w in range(1, 25)}


def c26_gain(plan: ActionPlan) -> float:
    """C_26 gained from the plan's purchase cuts, net of stock-out lost margin (formula above; cuts in weeks <= 24)."""
    assert all(v == 0.0 for v in plan.purchase_cut[24:])  # a week-25/26 cut would be paid back only after week 26
    return sum(NET_PER_DOLLAR[w] * v for w, v in enumerate(plan.purchase_cut[:24], start=1))


def test_bad_quarter_is_fixed_by_late_purchase_cuts_in_both_modes():
    # No-action min cash is 13,950 at week 26 (tests/test_scenarios.py), 11,050 below the floor. Before issue #103 a
    # cut of exactly 11,050 fixed it (harm 552.50). Now each $ cut nets at most 0.57 at week 26, so the plan cuts the
    # late weeks first (10,000 in each of weeks 24 and 23: 5,700 + 5,000) and the rest in week 22, and the revolver
    # bridges the earlier weeks; its interest is a cost the cuts must also cover:
    #   0.57 v_24 + 0.50 v_23 + 0.43 v_22 - revolver interest = 11,050.
    for protect in (False, True):
        res = run(DEMO, SCENARIOS["bad-quarter"], protect)
        assert res.status == OPTIMAL
        sim = simulate(DEMO, SCENARIOS["bad-quarter"], res.plan)
        assert c26_gain(res.plan) - sum(sim.revolver_interest) == approx(11_050.0)
        assert res.plan.purchase_cut[22] == approx(10_000.0) and res.plan.purchase_cut[23] == approx(10_000.0)
        assert sum(res.plan.purchase_cut[:21]) == approx(0.0)  # nothing before week 22
        assert sum(res.plan.purchase_cut) <= 25_000.0 + TOL  # I_0 - I_min
        assert res.disruption_cost == approx(
            0.05 * sum(res.plan.purchase_cut) + 0.01 * sum(res.plan.revolver_draw) + 0.01 * sum(sim.inventory_shortfall)
        )
        assert res.disruption_cost == pytest.approx(1_924.71, abs=0.01)  # engine value (was 552.50 before #103)
        assert res.plan.payroll_cut == [approx(0.0)] * 26
        assert res.min_cash == approx(25_000.0)
        assert "liquidity floor, week 26" in res.binding_constraints


def _deep_slump() -> ScenarioShock:
    return ScenarioShock(name="70% drop weeks 5-8", demand=DemandShock(delta=0.7, start_week=5, end_week=8))


def test_deep_slump_keeps_purchases_non_negative():
    # 70% drop in weeks 5-8: S_t = 15,000, so purchases before any cut are 0.65 x 15,000 = 9,750 in those weeks,
    # below the 10,000/wk cut cap. Before the P_t >= 0 row the optimizer could choose v_5 = 10,000 (P_5 = -250), which
    # simulate() now rejects (issue #39). No-action min cash is 1,115.38 in week 8.
    # Permanent loss 0.35 x 0.7 x 50,000 x 4 = 49,000 -> C_26 = 14,000, so the cuts must add 11,000 plus the revolver
    # interest to C_26, net of their stock-out cost (NET_PER_DOLLAR above); the week-7/8 trough is bridged by the
    # revolver and repaid. (Before issue #103: cuts of exactly 11,000 + interest.)
    shock = _deep_slump()
    assert simulate(DEMO, shock, ActionPlan()).min_cash == approx(1_115.384615)
    for protect in (False, True):
        res = run(DEMO, shock, protect)
        assert res.status == OPTIMAL
        sim = simulate(DEMO, shock, res.plan)  # would raise ValueError on negative purchases
        assert min(sim.purchases) >= -TOL
        assert res.cash == [approx(c) for c in sim.cash]
        assert res.min_cash == approx(25_000.0)
        interest = sum(sim.revolver_interest)
        assert c26_gain(res.plan) == approx(11_000.0 + interest)
        assert res.disruption_cost == approx(
            0.05 * sum(res.plan.purchase_cut) + 0.01 * sum(res.plan.revolver_draw) + 0.01 * sum(sim.inventory_shortfall)
        )
        assert res.plan.payroll_cut == [approx(0.0)] * 26


def test_deep_slump_protect_off_cut_capped_by_week_purchases():
    # Lead review on PR #69: 70% drop in weeks 5-8, protect payroll off. Week-5 purchases before a cut are
    # 0.65 x 15,000 = 9,750, so v_5 <= 9,750 (it used to be 10,000, i.e. P_5 = -250).
    res = run(DEMO, _deep_slump(), protect=False)
    assert res.status == OPTIMAL
    assert res.plan.purchase_cut[4] <= 9_750 + TOL  # week 5
    assert res.min_cash == approx(25_000.0)


# ---------------------------------------------------------------- §4 lexicographic tie-break (issue #104)
#
# Stage 1 finds the least harmful cost J*; stage 2 keeps J <= J* and minimizes
#   TB = sum_t [ (T+1-t)/T (v_t + y_t + z_t W_t) + t/(2T) q_t ]
# i.e. among equally cheap plans: act as late as possible, borrow for as short a time as possible.

PLAN_FIELDS = ("purchase_cut", "revolver_draw", "revolver_repay", "payroll_cut")


def assert_same_plan(a, b):
    assert (a.plan.use_backup_supplier, a.plan.defer_capex, a.plan.delay_expansion) == (
        b.plan.use_backup_supplier, b.plan.defer_capex, b.plan.delay_expansion)
    for name in PLAN_FIELDS:
        assert getattr(a.plan, name) == [approx(x) for x in getattr(b.plan, name)], name
    assert [(x.action, x.week) for x in a.actions] == [(x.action, x.week) for x in b.actions]


def test_deep_slump_same_plan_with_protect_on_and_off():
    # Lead review on PR #69: before the tie-break both modes cost the same but cut in different weeks, so flipping
    # "Protect payroll" moved the cuts although payroll is never cut. With the tie-break (#104) both give one plan.
    # With the stock-out cost (#103) a permanent purchase cut loses theta x shortfall of sales every week it stays below
    # the service level, so it is cheapest as late as possible: the plan bridges the slump with the revolver (draws in
    # weeks 7-8) and makes the permanent cuts in weeks 22-24, two of them at the v-bar = 10,000 weekly cap. Cost
    # 2,118.55 is the engine value (679.84 before #103).
    shock = _deep_slump()
    off = run(DEMO, shock, protect=False)
    on = run(DEMO, shock, protect=True)
    assert off.status == on.status == OPTIMAL
    assert off.plan.payroll_cut == [0.0] * 26 and on.plan.payroll_cut == [0.0] * 26
    assert_same_plan(off, on)
    assert off.objective == approx(on.objective)
    assert off.disruption_cost == pytest.approx(2_118.55, abs=0.01)
    cuts = off.plan.purchase_cut
    assert [t for t, v in enumerate(cuts, start=1) if v > 0] == [22, 23, 24]
    assert cuts[22] == approx(10_000.0) and cuts[23] == approx(10_000.0)  # v-bar cap
    assert [t for t, y in enumerate(off.plan.revolver_draw, start=1) if y > 0][:2] == [7, 8]  # bridge the slump


TIE_BREAK_SCENARIOS = [(sid, DEMO, SCENARIOS[sid]) for sid in SCENARIOS] + [
    ("70% drop weeks 5-8", DEMO, _deep_slump()),
]


@pytest.mark.parametrize(("label", "params", "shock"), TIE_BREAK_SCENARIOS, ids=[c[0] for c in TIE_BREAK_SCENARIOS])
def test_tie_break_never_changes_the_optimal_cost(label, params, shock):
    # Every named scenario (data/scenarios.json) plus the deep slump, both modes: the tie-break only chooses among
    # plans that are already optimal, so J is the stage-1 optimum to within 1e-6 relative.
    for protect in (False, True):
        before = optimize(params, shock, protect, SEC10, tie_break=False)
        after = run(params, shock, protect)
        assert before.status == after.status == OPTIMAL, label
        assert abs(after.objective - before.objective) <= 1e-6 * max(1.0, abs(before.objective)), label
        assert after.disruption_cost == pytest.approx(before.disruption_cost, rel=1e-6, abs=1e-6)
        assert after.min_cash == pytest.approx(before.min_cash, rel=1e-6, abs=1e-6)


def test_named_scenarios_same_plan_with_protect_on_and_off():
    # None of the named scenarios needs a payroll cut, so "Protect payroll" must not move any action.
    for sid, shock in SCENARIOS.items():
        off, on = run(DEMO, shock, protect=False), run(DEMO, shock, protect=True)
        assert off.plan.payroll_cut == [0.0] * 26, sid
        assert_same_plan(off, on)


def test_bad_quarter_same_plan_and_late_cuts():
    # Before the tie-break, protect on and off cut in different weeks at the same cost. With the tie-break (#104) and
    # the stock-out cost (#103), both modes give one plan: the revolver bridges weeks 20-24 and the permanent cuts sit
    # in weeks 22-24 (two at the 10,000 cap), as late as possible because every week a cut stays below the service
    # level costs lost sales. Cost 1,924.71 and the hand identity for the cuts are checked in
    # test_bad_quarter_is_fixed_by_late_purchase_cuts_in_both_modes.
    plans = [run(DEMO, SCENARIOS["bad-quarter"], protect) for protect in (False, True)]
    assert_same_plan(*plans)
    cuts = plans[0].plan.purchase_cut
    assert [t for t, v in enumerate(cuts, start=1) if v > 0] == [22, 23, 24]
    assert cuts[22] == approx(10_000.0) and cuts[23] == approx(10_000.0)
    assert plans[0].plan.payroll_cut == [0.0] * 26


def test_tie_break_puts_a_tied_payroll_cut_in_the_latest_week():
    # 3-week payroll case above: a payroll cut in week 1 or week 2 raises C_2 equally at the same harm (5/$).
    # Latest first: the whole 146.154 in week 2.
    res = run(three_week_params(revolver_limit=500.0, min_inventory=59_800.0), CASE_B, protect=False)
    assert [z * 12_000.0 for z in res.plan.payroll_cut] == [approx(0.0), approx(146.153846), approx(0.0)]
    # 3-week slump: 1,346.154 of payroll cuts in weeks 1-2. Week 2 takes the cap z-bar W = 1,200 first, week 1 the rest.
    res = run(three_week_params(revolver_limit=0.0, min_cash=50_000.0), _three_week_slump(), protect=False)
    assert [z * 12_000.0 for z in res.plan.payroll_cut] == [approx(146.153846), approx(1_200.0), approx(0.0)]


def test_tie_break_failure_reports_the_equally_cheap_stage_1_plan(monkeypatch):
    # If the stage-2 solve fails, the stage-1 plan (same cost) is reported and the message says the tie-break was
    # not applied; nothing is hidden and the status stays OPTIMAL.
    real_milp = optimizer_module.milp

    def failing_stage_2(*args, **kwargs):
        if len(kwargs["constraints"]) > 1:  # only stage 2 adds the J <= J* row
            return SimpleNamespace(status=1, x=None, message="Time limit reached.")
        return real_milp(*args, **kwargs)

    monkeypatch.setattr(optimizer_module, "milp", failing_stage_2)
    res = run(DEMO, _deep_slump(), protect=True)
    monkeypatch.setattr(optimizer_module, "milp", real_milp)
    stage_1 = optimize(DEMO, _deep_slump(), True, SEC10, tie_break=False)
    assert res.status == OPTIMAL
    assert "tie-break not applied" in res.solver_message
    assert_same_plan(res, stage_1)
    assert res.objective == approx(stage_1.objective)


def test_stage_2_plan_failing_the_simulate_check_falls_back_to_stage_1(monkeypatch):
    # If the tie-broken plan doesn't reproduce in simulate() (e.g. round-off just over AGREEMENT_TOL), the stage-1
    # plan is re-checked and reported, as the §4 guarantee says, instead of withholding a valid optimal plan.
    real_tie_break = optimizer_module._tie_break

    def bad_stage_2(prob, sol1):
        sol, note = real_tie_break(prob, sol1)
        sol = sol.copy()
        sol[prob.ix("C", 1)] += 1.0  # a cash path simulate() cannot reproduce
        return sol, note

    monkeypatch.setattr(optimizer_module, "_tie_break", bad_stage_2)
    res = run(DEMO, _deep_slump(), protect=True)
    monkeypatch.setattr(optimizer_module, "_tie_break", real_tie_break)
    stage_1 = optimize(DEMO, _deep_slump(), True, SEC10, tie_break=False)
    assert res.status == OPTIMAL
    assert "tie-break not applied (stage-2 plan failed the simulate() check" in res.solver_message
    assert_same_plan(res, stage_1)
    assert res.disruption_cost == approx(stage_1.disruption_cost)


def test_tie_break_keeps_no_feasible_plan():
    # NO FEASIBLE PLAN is decided by stage 1 alone; stage 2 never runs.
    res = run(DEMO, _severe_drop(), protect=True)
    assert res.status == NO_FEASIBLE_PLAN
    assert res.plan is None
    # 22,375 before #103; hand bound in test_severe_drop_feasible_only_with_payroll_cuts
    assert res.max_feasible_cash_floor == pytest.approx(10_070.50, abs=0.01)


# ---------------------------------------------------------------- reporting round-off (issue #147)
#
# After the tie-break (#104) some plans sit on C_min = 25,000 in several weeks, and the solver's cash differs between
# those weeks by ~4e-12. That must not move the reported min-cash week, and B_t = -4e-13 must not be reported.

CHALLENGES = {
    c["id"]: ScenarioShock.model_validate(c["shock"])
    for c in json.loads((DATA / "judge_challenges.json").read_text(encoding="utf-8"))["challenges"]
}
ALL_NAMED = {
    **{f"scenario {k}": v for k, v in SCENARIOS.items()},
    **{f"challenge {k}": v for k, v in CHALLENGES.items()},
}


def test_min_cash_week_ignores_round_off_between_tied_weeks():
    # Hand case: week 1 is 4e-12 above week 3, which is the exact minimum. Within tolerance -> week 1 (first tie).
    assert optimizer_module._min_cash_week([25_000.0 + 4e-12, 30_000.0, 25_000.0], 25_000.0) == 1
    # A real gap (1 cent, far above max(1e-6, 1e-9 x 25,000) = 2.5e-5) is not a tie: the strict minimum wins.
    assert optimizer_module._min_cash_week([25_000.01, 30_000.0, 25_000.0], 25_000.0) == 3


def test_distributor_strike_min_cash_week_is_the_first_week_on_the_floor():
    # Judge's Challenge "distributor strike": the plan sits on C_min in week 5 and again in week 26. #136 reported
    # week 26 (C_26 was 4e-12 below C_5); the first tied week is the one to report.
    for protect in (False, True):
        res = run(DEMO, CHALLENGES["judge-distributor-strike"], protect)
        assert res.status == OPTIMAL
        assert res.min_cash == approx(DEMO.min_cash)
        tol = max(1e-6, 1e-9 * abs(res.min_cash))
        tied = [t for t, c in enumerate(res.cash, start=1) if c - res.min_cash <= tol]
        assert len(tied) >= 2 and tied[-1] == 26  # a genuine tie: more than one week on the floor
        assert res.min_cash_week == tied[0]
        assert all(c - res.min_cash > tol for c in res.cash[: res.min_cash_week - 1])


@pytest.mark.parametrize("label", sorted(ALL_NAMED))
def test_reported_paths_have_no_round_off_around_zero(label):
    # Every named scenario and Judge's Challenge, both modes: no negative revolver balance (plant closure with
    # payroll cuts allowed used to report B_t = -4.03e-13), and no |x| < ZERO_TOL residue in any reported path.
    for protect in (False, True):
        res = run(DEMO, ALL_NAMED[label], protect)
        if res.status != OPTIMAL:
            continue
        assert all(b >= 0.0 for b in res.revolver_balance), label
        for path in (res.cash, res.revolver_balance, res.inventory):
            assert all(x == 0.0 or abs(x) >= optimizer_module.ZERO_TOL for x in path), label


def test_no_action_plans_report_a_disruption_cost_of_exactly_zero():
    # PR #161 review: with no action the stock-out term c_u u_t was priced on solver round-off, so disruption_cost came
    # out near -1e-12 (baseline: -1.09e-12) and CASCADE showed "-0.00". It is now exactly 0.0, and never negative: it is
    # a weighted sum of actions and shortfalls that are all >= 0.
    no_action = []
    for label, shock in {"baseline": BASELINE, **ALL_NAMED}.items():
        res = run(DEMO, shock, protect=True)
        if res.status != OPTIMAL:
            continue  # plant closure with payroll protected: NO FEASIBLE PLAN, no cost is reported
        assert res.disruption_cost >= 0.0, label
        if not res.actions:
            # copysign: -0.0 == 0.0 is True in Python, but a screen prints -0.0 as "-0".
            assert res.disruption_cost == 0.0 and math.copysign(1.0, res.disruption_cost) == 1.0, label
            no_action.append(label)
    # The baseline and the three named scenarios that stay above the floor (test above) take no action.
    assert {"baseline", "scenario rate-plus-200bp", "scenario demand-drop-20pct-6wk",
            "scenario supplier-outage-3wk"} <= set(no_action)


def test_plant_closure_with_payroll_cuts_reports_zero_revolver_balance():
    res = run(DEMO, CHALLENGES["judge-plant-closure"], protect=False)
    assert res.status == OPTIMAL
    assert min(res.revolver_balance) == 0.0


def _long_outage() -> ScenarioShock:
    kappa = [1.0, 1.0] + [0.0] * 12 + [1.0] * 12  # primary supplier down weeks 3-14
    return ScenarioShock(name="outage weeks 3-14", supplier=SupplierOutage(availability=kappa, dependent_share=0.4))


def test_long_outage_chooses_backup_supplier():
    # Without backup: 0.40 x 50,000 = 20,000/wk of lost sales for 12 weeks; each costs 0.35 of cash once settled ->
    # C_26 = 63,000 - 84,000 = -21,000. Purchase cuts (25,000) are not enough; payroll would be (harm 5/$).
    # With backup (harm 2,500): fee 2,000 + premium 0.12 x 0.65 x 20,000 = 1,560/wk x 12 = 18,720 ->
    # C_26 = 63,000 - 2,000 - 18,720 = 42,280, no other action needed.
    for protect in (False, True):
        res = run(DEMO, _long_outage(), protect)
        assert res.status == OPTIMAL
        assert res.plan.use_backup_supplier is True
        assert [a.action for a in res.actions] == ["use_backup_supplier"]
        assert res.actions[0].amount is None and res.actions[0].week is None  # yes/no action: no "$0" amount
        assert res.disruption_cost == approx(2_500.0)
        assert res.min_cash == approx(42_280.0)


def _sharp_dip() -> ScenarioShock:
    return ScenarioShock(name="60% drop weeks 5-8", demand=DemandShock(delta=0.6, start_week=5, end_week=8))


def test_sharp_dip_uses_revolver_and_respects_floors():
    # Lost sales 0.6 x 50,000 x 4 = 120,000 -> permanent cash loss 0.35 x 120,000 = 42,000 -> C_26 = 21,000 without
    # action. Receipts fall at once but payables only two weeks later, so the trough in week 8 is deeper than the
    # permanent loss: the revolver bridges it, purchase cuts fix the permanent part.
    res = run(DEMO, _sharp_dip(), protect=True)
    assert res.status == OPTIMAL
    assert sum(res.plan.revolver_draw) > 0.0
    # Every dollar drawn is repaid (B_26 <= B_0 = 0); its interest J^R is a permanent cost the cuts must also cover.
    assert res.revolver_balance[-1] <= DEMO.revolver_balance_0 + TOL
    assert sum(res.plan.revolver_repay) == approx(sum(res.plan.revolver_draw))
    # Issue #103: the cuts must add 4,000 + interest to C_26 net of their stock-out cost (NET_PER_DOLLAR above). The
    # cheapest place is week 24 (0.57 per $): 7,366.67 x 0.57 = 4,199.00, of which 199.00 covers the revolver interest.
    interest = sum(simulate(DEMO, _sharp_dip(), res.plan).revolver_interest)
    assert c26_gain(res.plan) == approx(4_000.0 + interest)
    assert res.plan.purchase_cut[23] == approx(sum(res.plan.purchase_cut))  # all in week 24
    assert min(res.cash) >= 25_000.0 - TOL
    assert "terminal revolver" in res.binding_constraints


def test_facility_limit_respected():
    params = DEMO.model_copy(update={"revolver_limit": 3_000.0})
    res = run(params, _sharp_dip(), protect=True)
    assert res.status == OPTIMAL
    assert max(res.revolver_balance) <= 3_000.0 + TOL
    assert any(name.startswith("facility limit, week") for name in res.binding_constraints)
    assert min(res.cash) >= 25_000.0 - TOL


def _severe_drop() -> ScenarioShock:
    return ScenarioShock(
        name="50% drop weeks 5-10, 4-week recovery",
        demand=DemandShock(delta=0.5, start_week=5, end_week=10, recovery_weeks=4),
    )


def test_severe_drop_feasible_only_with_payroll_cuts():
    # Lost sales: 25,000 x 6 weeks + recovery (m = 0.625, 0.75, 0.875, 1) 18,750 + 12,500 + 6,250 + 0 = 187,500.
    # Permanent cash loss 0.35 x 187,500 = 65,625 -> C_26 = 63,000 - 65,625 = -2,625 without action.
    # Purchase cuts total at most I_0 - I_min = 25,000. Net of stock-out cost (NET_PER_DOLLAR above), the most they can
    # add to C_26 is the late weeks first: 10,000 x 0.57 (week 24) + 10,000 x 0.50 (week 23) + 5,000 x 0.43 (week 22)
    # = 12,850, so C_26 <= -2,625 + 12,850 = 10,225 (before issue #103: -2,625 + 25,000 = 22,375).
    # The revolver must be repaid by week 26; there is no outage, capex or expansion. So only payroll closes it.
    best_c26_without_payroll = -2_625.0 + 0.57 * 10_000 + 0.50 * 10_000 + 0.43 * 5_000  # 10,225
    allowed = run(DEMO, _severe_drop(), protect=False)
    assert allowed.status == OPTIMAL
    assert sum(allowed.plan.purchase_cut) == approx(25_000.0)
    payroll_cut = sum(z * 12_000.0 for z in allowed.plan.payroll_cut)
    assert payroll_cut >= 25_000.0 - best_c26_without_payroll - TOL  # at least 14,775
    assert payroll_cut == pytest.approx(14_939.50, abs=0.01)  # engine value (2,625 before #103); the rest is interest
    assert max(allowed.plan.payroll_cut) <= 0.10 + TOL  # z-bar
    assert min(allowed.inventory) >= 40_000.0 - TOL  # I_min
    assert "inventory floor, week 26" in allowed.binding_constraints

    protected = run(DEMO, _severe_drop(), protect=True)
    assert protected.status == NO_FEASIBLE_PLAN
    # Highest reachable minimum cash without payroll cuts: at most 10,225 (above); the engine finds 10,070.50, the gap
    # being the interest on the revolver that bridges the weeks 10-24 trough.
    assert protected.max_feasible_cash_floor <= best_c26_without_payroll + TOL
    assert protected.max_feasible_cash_floor == pytest.approx(10_070.50, abs=0.01)


def test_stock_shortfall_cost_must_be_positive():
    """§4.9 (issue #103): with c_u = 0 the shortfall u_t would not be pinned to max(0, I^svc_t - I_t), and the solver's
    lost sales could differ from simulate()'s, so a zero weight is refused."""
    with pytest.raises(ValueError):
        DisruptionCosts(stock_shortfall_per_dollar_week=0.0)
    assert DisruptionCosts().stock_shortfall_per_dollar_week == 0.01  # MATH_MODEL §10 proposal


def test_optimizer_shortfall_matches_simulator_stockouts():
    """The solver's u_t equals simulate()'s inventory shortfall (§4.9), so its stock-out lost sales and cash agree."""
    res = run(DEMO, SCENARIOS["bad-quarter"], protect=True)
    sim = simulate(DEMO, SCENARIOS["bad-quarter"], res.plan)
    assert sum(sim.stockout_lost_sales) > 0.0  # the plan does run below the service level
    assert sim.inventory_shortfall == [approx(max(0.0, 65_000.0 - i)) for i in sim.inventory]  # m_t = 1 after week 12
    assert res.cash == [approx(c) for c in sim.cash]


def test_protect_payroll_sets_every_payroll_cut_to_zero():
    # Payroll is cheap enough to beat a purchase cut only if c_z < c_v; make it so, then protect it.
    cheap_payroll = SEC10.model_copy(
        update={"disruption_costs": SEC10.disruption_costs.model_copy(update={"payroll_cut_per_dollar": 0.001})}
    )
    allowed = run(DEMO, SCENARIOS["bad-quarter"], protect=False, settings=cheap_payroll)
    assert sum(allowed.plan.payroll_cut) > 0.0
    protected = run(DEMO, SCENARIOS["bad-quarter"], protect=True, settings=cheap_payroll)
    assert protected.status == OPTIMAL
    assert protected.plan.payroll_cut == [0.0] * 26
    assert "payroll_cut" not in [a.action for a in protected.actions]


# ---------------------------------------------------------------- simulator / optimizer agreement

AGREEMENT_CASES = [
    ("demo baseline", DEMO, BASELINE, False, SEC10),
    ("bad quarter", DEMO, SCENARIOS["bad-quarter"], True, SEC10),
    ("outage + backup supplier", DEMO, _long_outage(), True, SEC10),
    ("revolver bridge", DEMO, _sharp_dip(), True, SEC10),
    ("facility limit", DEMO.model_copy(update={"revolver_limit": 3_000.0}), _sharp_dip(), True, SEC10),
    ("payroll cuts", DEMO, _severe_drop(), False, SEC10),
    ("opening revolver balance", DEMO.model_copy(update={"revolver_balance_0": 20_000.0}), _sharp_dip(), True, SEC10),
    ("3-week revolver", three_week_params(), CASE_B, False, SEC10),
    ("3-week facility limit", three_week_params(revolver_limit=500.0), CASE_B, False, SEC10),
    ("3-week payroll", three_week_params(revolver_limit=500.0, min_inventory=59_800.0), CASE_B, False, SEC10),
    ("deep slump, payroll allowed", DEMO, _deep_slump(), False, SEC10),
    ("deep slump, payroll protected", DEMO, _deep_slump(), True, SEC10),
    ("3-week slump, purchases at zero", three_week_params(revolver_limit=0.0, min_cash=50_000.0), _three_week_slump(),
     False, SEC10),
]


@pytest.mark.parametrize(("label", "params", "shock", "protect", "settings"), AGREEMENT_CASES,
                         ids=[c[0] for c in AGREEMENT_CASES])
def test_simulator_agrees_with_optimizer(label, params, shock, protect, settings):
    res = run(params, shock, protect, settings)
    assert res.status == OPTIMAL, label
    sim = simulate(params, shock, res.plan)
    assert res.cash == [approx(c) for c in sim.cash]
    assert res.revolver_balance == [approx(b) for b in sim.revolver_balance]
    assert res.inventory == [approx(i) for i in sim.inventory]
    assert res.min_cash == approx(sim.min_cash)
    # Every §4 hard constraint holds on the simulated path.
    assert min(sim.cash) >= params.min_cash - TOL
    assert all(-TOL <= b <= params.revolver_limit + TOL for b in sim.revolver_balance)
    assert min(sim.inventory) >= params.min_inventory - TOL
    assert sim.revolver_balance[-1] <= params.revolver_balance_0 + TOL
    assert min(sim.purchases) >= -TOL  # §3 physical rule (issue #39)


def test_opening_revolver_balance_terminal_condition():
    # B_0 = 20,000: the plan may end with a lower balance but never a higher one (§4.7).
    params = DEMO.model_copy(update={"revolver_balance_0": 20_000.0})
    res = run(params, _sharp_dip(), protect=True)
    assert res.status == OPTIMAL
    assert res.revolver_balance[-1] <= 20_000.0 + TOL


# ---------------------------------------------------------------- status handling


def test_other_solver_status_is_surfaced_not_reported_optimal(monkeypatch):
    fake = SimpleNamespace(status=1, x=None, message="Time limit reached. (HiGHS Status 13)")
    monkeypatch.setattr(optimizer_module, "milp", lambda *args, **kwargs: fake)
    res = run(DEMO, BASELINE, protect=False)
    assert res.status == SOLVER_ERROR
    assert res.solver_message == "Time limit reached. (HiGHS Status 13)"
    assert res.plan is None and res.cash is None


def test_result_is_labeled_simulated_and_deterministic():
    first = run(DEMO, SCENARIOS["bad-quarter"], protect=True)
    second = run(DEMO, SCENARIOS["bad-quarter"], protect=True)
    assert isinstance(first, OptimizationResult)
    assert first.provenance == "SIMULATED"
    assert first == second


# ---------------------------------------------------------------- §4.9 optional DSCR covenant (issue #85)
#
# For every rolling w-week window a..b (default w = 4) with term-loan debt service:
#   sum OCF_t >= DSCR_min * sum DS_t,
#   OCF_t = R_t - P_{t-L_p} - (1 - z_t) W_t - O_t - F_b x_b 1[t=1]   DS_t = J_t + A_t + J^R_t.
# The grocer (§10) has OCF = 50,000 - 32,500 - 12,000 - 6,000 = -500 a week, so its baseline DSCR is already negative;
# the restaurant (§10b) has OCF = 20,000 - 6,800 - 7,300 - 5,400 = 500 against 300 of interest, DSCR 1.67.

REST_DOC = json.loads((DATA / "restaurant_business.json").read_text(encoding="utf-8"))
REST = BusinessParams.model_validate(REST_DOC["business"])
REST_SETTINGS = OptimizerSettings.from_dict(REST_DOC["optimizer_parameters"])
REST_SCENARIOS = {
    s["id"]: ScenarioShock.model_validate(s["shock"])
    for s in json.loads((DATA / "scenarios_restaurant.json").read_text(encoding="utf-8"))["scenarios"]
}
COVENANT = 1.20  # DSCR_min: proposal for finance-owner review (MATH_MODEL §4.9), typical bank range 1.20-1.25x


def rolling_dscr(sim, w: int = 4) -> list[float]:
    """DSCR of every w-week window, computed from simulate()'s own arrays (independent of the optimizer's rows)."""
    ocf = [r - p - wp - o - f for r, p, wp, o, f in
           zip(sim.receipts, sim.payables_paid, sim.payroll, sim.opex, sim.backup_fee, strict=True)]
    ds = [j + a + jr for j, a, jr in zip(sim.interest, sim.amortization, sim.revolver_interest, strict=True)]
    return [sum(ocf[k - w:k]) / sum(ds[k - w:k]) for k in range(w, len(ocf) + 1)]


def test_baseline_dscr_worked_numbers():
    # Grocer: 4 x (-500) / (4 x 600,000 x 8% / 52) = -2,000 / 3,692.31 = -0.5417 in every window.
    grocer = rolling_dscr(simulate(DEMO, BASELINE, ActionPlan()))
    assert grocer == [approx(-2_000 / (4 * 600_000 * 0.08 / 52))] * 23
    assert grocer[0] == pytest.approx(-0.541667, abs=1e-6)
    # Restaurant: 4 x 500 / (4 x 156,000 x 10% / 52) = 2,000 / 1,200 = 1.6667.
    assert rolling_dscr(simulate(REST, BASELINE, ActionPlan())) == [approx(2_000 / 1_200)] * 23


@pytest.mark.parametrize("protect", [False, True])
def test_covenant_off_gives_identical_results_on_every_named_scenario(protect):
    # covenant_dscr_min=None adds no row at all, so every result (status, plan, cost, paths, binding names, diagnostic)
    # is exactly equal to the result without the argument (so certainly within 1e-9).
    cases = [(DEMO, SEC10, s) for s in (*SCENARIOS.values(), BASELINE)]
    cases += [(REST, REST_SETTINGS, s) for s in (*REST_SCENARIOS.values(), BASELINE)]
    for params, settings, shock in cases:
        before = optimize(params, shock, protect, settings)
        after = optimize(params, shock, protect, settings, covenant_dscr_min=None)
        assert after == before, shock.name
        if before.status == OPTIMAL:
            assert not any(name.startswith("DSCR") for name in before.binding_constraints)


def test_restaurant_slow_season_feasible_without_covenant_infeasible_with_it():
    """slow-season-plus-300bp (restaurant): rate 13% from week 1, sales -30% (6,000) in weeks 2-9.

    Without the covenant a revolver bridge keeps cash above C_min = 15,000 (MATH_MODEL §10b).
    With DSCR_min = 1.20, look at the window weeks 4-7. Each of those weeks with no action:
      R_t = 14,000 (sales 14,000 this week and last), bill paid P_{t-1} = 0.34 x 14,000 = 4,760,
      OCF_t = 14,000 - 4,760 - 7,300 - 5,400 = -3,460, so window OCF = -13,840.
      Debt service: interest 156,000 x 13% / 52 = 390 a week, 1,560 per window (plus any revolver interest, >= 0).
      The covenant needs window OCF >= 1.20 x 1,560 = 1,872.
    The most any lever adds to that window's OCF: purchase cuts 2,800 in total (I_0 - I_min = 6,800 - 4,000);
    payroll cuts 4 x 730 = 2,920 (0 with Protect payroll); backup supplier nothing (no outage, only the week-1 fee);
    capex and expansion are 0; revolver draws are financing, not OCF, and only add interest to DS.
    So window OCF <= -13,840 + 2,800 + 2,920 = -8,120 < 1,872: NO FEASIBLE PLAN in both modes.
    """
    shock = REST_SCENARIOS["slow-season-plus-300bp"]
    for protect in (True, False):
        free = optimize(REST, shock, protect, REST_SETTINGS)
        assert free.status == OPTIMAL
        assert free.min_cash >= REST.min_cash - TOL
        bound = optimize(REST, shock, protect, REST_SETTINGS, covenant_dscr_min=COVENANT)
        assert bound.status == NO_FEASIBLE_PLAN
        assert bound.plan is None and bound.cash is None
        assert "Without the DSCR covenant (DSCR_min = 1.2) a plan would exist" in bound.diagnostic


def test_restaurant_distributor_loss_covenant_changes_the_plan():
    """distributor-loss-4wk (restaurant): primary distributor out in weeks 6-9, 60% of sales (12,000 a week) lost.

    Without the covenant (cost 27.60): draw 2,760 in week 9, repay it in week 10 (cheapest way over C_min).
    A revolver draw cannot help the covenant (financing is not OCF), and without the backup supplier week 6 alone has
    OCF = 500 - 0.9 x 12,000 = -10,300, far beyond what 2,800 of purchase cuts can offset. So the plan must switch to
    the backup supplier (x_b = 1, c_b = 2,500): no sales lost, but the premium 0.15 x 0.34 x 12,000 = 612 is bought in
    weeks 6-9 and paid in weeks 7-10 (L_p = 1), so OCF = 500 - 612 = -112 there (and the 500 fee hits week 1).
    The covenant needs 1.20 x 4 x 300 = 1,440 per window. A cut v_t raises OCF in week t+1. Windows:
      weeks 4-7:  1,500 - 112 + v_6 >= 1,440                -> v_6 >= 52
      weeks 5-8:  1,000 - 224 + v_6 + v_7 >= 1,440          -> v_6 + v_7 >= 664
      weeks 6-9:    500 - 336 + v_6 + v_7 + v_8 >= 1,440    -> ... >= 1,276
      weeks 7-10:      -448 + v_6 + ... + v_9 >= 1,440      -> ... >= 1,888
    Cutting as late as possible (the §4 tie-break) gives v_6 = 52, v_7 = v_8 = v_9 = 612, all four windows binding,
    total 1,888 <= 2,800. Cost 2,500 + 0.05 x 1,888 = 2,594.40. Payroll is never cut, in either mode.
    """
    shock = REST_SCENARIOS["distributor-loss-4wk"]
    for protect in (True, False):
        free = optimize(REST, shock, protect, REST_SETTINGS)
        assert free.status == OPTIMAL
        assert free.disruption_cost == approx(27.60)
        assert [(a.action, a.week, a.amount) for a in free.actions] == [
            ("revolver_draw", 9, approx(2_760.0)), ("revolver_repay", 10, approx(2_760.0))]

        bound = optimize(REST, shock, protect, REST_SETTINGS, covenant_dscr_min=COVENANT)
        assert bound.status == OPTIMAL
        assert bound.plan.use_backup_supplier
        assert bound.plan.purchase_cut[5:9] == [approx(52.0), approx(612.0), approx(612.0), approx(612.0)]
        assert sum(bound.plan.purchase_cut) == approx(1_888.0)
        assert sum(bound.plan.revolver_draw) == 0.0 and bound.plan.payroll_cut == [0.0] * 26
        assert bound.disruption_cost == approx(2_594.40)
        covenant_names = [n for n in bound.binding_constraints if n.startswith("DSCR")]
        assert covenant_names == [f"DSCR covenant, weeks {a}–{a + 3}" for a in (4, 5, 6, 7)]
        # Independent check on simulate()'s path: the covenant holds in every window and cash matches the solver.
        sim = simulate(REST, shock, bound.plan)
        assert bound.cash == [approx(c) for c in sim.cash]
        assert min(rolling_dscr(sim)) >= COVENANT - 1e-9
        # Stage 1 alone reaches the same cost: the covenant is in the constraints of both tie-break stages.
        stage1 = optimize(REST, shock, protect, REST_SETTINGS, tie_break=False, covenant_dscr_min=COVENANT)
        assert stage1.disruption_cost == approx(bound.disruption_cost)
        assert min(rolling_dscr(simulate(REST, shock, stage1.plan))) >= COVENANT - 1e-9


def test_grocer_baseline_breaches_a_bank_covenant_with_payroll_protected():
    """The §10 grocer loses money before any shock: OCF = -500 a week, baseline DSCR -0.54.

    With Protect payroll the only lever that raises OCF is a purchase cut. Without the stock-out cost the bound was
    6 x (2,000 + 3,692.31 DSCR_min) <= 25,000, i.e. DSCR_min <= 0.587. With it (#103) a cut raises OCF once, when
    paid, then loses theta = 0.20 of sales per $ short every later week (about 0.07 of OCF per $ per week once
    settled), so repairing the early windows deepens the later ones: no positive covenant is reachable at all.
    Any bank-style covenant (1.20) is NO FEASIBLE PLAN, even with no shock.
    """
    assert optimize(DEMO, BASELINE, True, SEC10, covenant_dscr_min=0.01).status == NO_FEASIBLE_PLAN
    res = optimize(DEMO, BASELINE, True, SEC10, covenant_dscr_min=COVENANT)
    assert res.status == NO_FEASIBLE_PLAN
    assert "the covenant is what makes this scenario infeasible" in res.diagnostic
    for shock in SCENARIOS.values():
        assert optimize(DEMO, shock, True, SEC10, covenant_dscr_min=COVENANT).status == NO_FEASIBLE_PLAN, shock.name


def test_grocer_cannot_meet_a_bank_covenant_even_cutting_payroll():
    """Protect payroll off. Before the stock-out cost (#103) the grocer reached 1.20 with 25,000 of purchase cuts plus
    13,584.62 of payroll cuts. With it, purchase cuts lose later sales: the optimizer certifies a plan at 0.73 (which
    re-simulates to a rolling DSCR >= 0.73 in every window, with payroll cut) and none at 0.90 or 1.20.

    Between 0.74 and 0.80 the covenant can make a larger stock shortfall u_t look useful (it shifts OCF between
    windows), so the solver's u_t may exceed the true shortfall. MATH_MODEL §4 documents this; the re-simulation check
    must then withhold the plan (SOLVER ERROR), never report OPTIMAL with a cash path simulate() can't reproduce."""
    res = optimize(DEMO, BASELINE, False, SEC10, covenant_dscr_min=0.73)
    assert res.status == OPTIMAL
    assert sum(res.plan.payroll_cut) > 0.0  # purchase cuts alone can't get there
    assert min(rolling_dscr(simulate(DEMO, BASELINE, res.plan))) >= 0.73 - 1e-9
    for dscr_min in (0.90, COVENANT):
        assert optimize(DEMO, BASELINE, False, SEC10, covenant_dscr_min=dscr_min).status == NO_FEASIBLE_PLAN
    for dscr_min in (0.74, 0.75, 0.80):  # the documented gray zone: never a wrong plan
        r = optimize(DEMO, BASELINE, False, SEC10, covenant_dscr_min=dscr_min)
        assert r.status in (SOLVER_ERROR, NO_FEASIBLE_PLAN) or (
            r.status == OPTIMAL and min(rolling_dscr(simulate(DEMO, BASELINE, r.plan))) >= dscr_min - 1e-9
        )


def test_weekly_covenant_window_is_stricter():
    """Same distributor loss with a 1-week window (DSCR_min = 1.20, Protect payroll): NO FEASIBLE PLAN.

    Without the backup supplier, week 6 has OCF = -10,300 and at most 1,400 of cut can be paid that week. With it,
    week 1 has OCF = 20,000 - 6,800 - 7,300 - 5,400 - 500 (fee) = 0 < 1.20 x 300 = 360, and nothing can offset it:
    the bill paid in week 1 is the pre-horizon P_0 and payroll is protected. The 4-week test above is feasible.
    """
    shock = REST_SCENARIOS["distributor-loss-4wk"]
    weekly = optimize(REST, shock, True, REST_SETTINGS, covenant_dscr_min=COVENANT, covenant_window_weeks=1)
    assert weekly.status == NO_FEASIBLE_PLAN
    # Baseline at DSCR_min = 500/300 exactly: every week's OCF (500) sits on the covenant, so week 5 binds and is
    # named with a single week.
    res = optimize(REST, BASELINE, True, REST_SETTINGS, covenant_dscr_min=500 / 300, covenant_window_weeks=1)
    assert res.status == OPTIMAL
    assert "DSCR covenant, week 5" in res.binding_constraints


def test_covenant_diagnostic_when_infeasible_anyway():
    # road-closure-9wk with Protect payroll is NO FEASIBLE PLAN even without the covenant (MATH_MODEL §10b bound:
    # C_26 <= 13,400 < 15,000); the diagnostic must not blame the covenant.
    res = optimize(REST, REST_SCENARIOS["road-closure-9wk"], True, REST_SETTINGS, covenant_dscr_min=COVENANT)
    assert res.status == NO_FEASIBLE_PLAN
    assert "infeasible even without the DSCR covenant" in res.diagnostic


@pytest.mark.parametrize("bad", [dict(covenant_dscr_min=0.0), dict(covenant_dscr_min=-1.2),
                                 dict(covenant_dscr_min=float("nan")), dict(covenant_dscr_min=float("inf")),
                                 dict(covenant_dscr_min=1.2, covenant_window_weeks=0),
                                 dict(covenant_dscr_min=1.2, covenant_window_weeks=27),
                                 dict(covenant_dscr_min=1.2, covenant_window_weeks=True),
                                 # the window is validated even with the covenant off (review of #144)
                                 dict(covenant_window_weeks=0), dict(covenant_window_weeks=-1)])
def test_covenant_rejects_bad_inputs(bad):
    with pytest.raises(ValueError):
        optimize(REST, BASELINE, True, REST_SETTINGS, **bad)
