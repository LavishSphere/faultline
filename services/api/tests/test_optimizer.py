"""Tests for core/optimizer.py: the MATH_MODEL §4 recovery MILP.

The 3-week cases are hand-checked: every input is stated and every expected number is derived in the comments from the
§3 recurrence, so a finance reviewer can check them without code. The demo-business cases use data/demo_business.json
(SYNTHETIC) and check what can be derived by hand (totals, min cash); the agreement test re-simulates every chosen plan
with core.financials.simulate() and requires the same cash, revolver and inventory paths to 1e-6.
"""

from __future__ import annotations

import json
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


def test_bad_quarter_is_fixed_by_purchase_cuts_in_both_modes():
    # No-action min cash is 13,950 at week 26 (tests/test_scenarios.py), 11,050 below the floor. A purchase cut is a
    # permanent saving and the cheapest permanent lever: total cut 11,050 (harm 0.05 x 11,050 = 552.50), within the
    # inventory headroom I_0 - I_min = 25,000. The revolver cannot help week 26 because B_26 <= B_0 = 0.
    for protect in (False, True):
        res = run(DEMO, SCENARIOS["bad-quarter"], protect)
        assert res.status == OPTIMAL
        assert sum(res.plan.purchase_cut) == approx(11_050.0)
        assert res.disruption_cost == approx(552.5)
        assert res.plan.payroll_cut == [approx(0.0)] * 26
        assert res.min_cash == approx(25_000.0)
        assert "liquidity floor, week 26" in res.binding_constraints


def _deep_slump() -> ScenarioShock:
    return ScenarioShock(name="70% drop weeks 5-8", demand=DemandShock(delta=0.7, start_week=5, end_week=8))


def test_deep_slump_keeps_purchases_non_negative():
    # 70% drop in weeks 5-8: S_t = 15,000, so purchases before any cut are 0.65 x 15,000 = 9,750 in those weeks,
    # below the 10,000/wk cut cap. Before the P_t >= 0 row the optimizer could choose v_5 = 10,000 (P_5 = -250), which
    # simulate() now rejects (issue #39). No-action min cash is 1,115.38 in week 8.
    # Permanent loss 0.35 x 0.7 x 50,000 x 4 = 49,000 -> C_26 = 14,000, so cuts must total 11,000 plus the revolver
    # interest; the week-7/8 trough is bridged by the revolver and repaid.
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
        assert sum(res.plan.purchase_cut) == approx(11_000.0 + interest)
        assert res.disruption_cost == approx(0.05 * sum(res.plan.purchase_cut) + 0.01 * sum(res.plan.revolver_draw))
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
    # Lead review on PR #69: both modes cost 677.34 but cut in different weeks (v_5 = 10,000 vs v_3 = 10,000), so
    # flipping "Protect payroll" moved the cuts although payroll is never cut. With the tie-break both give one plan.
    # Hand check (70% drop weeks 5-8, L_p = 2, so a week-t cut is paid out in week t+2):
    #   no-action C_7 = 14,788.462, so weeks <= 5 must cut 25,000 - 14,788.462 = 10,211.538 to keep C_7 at the floor.
    #   Latest first: v_5 = 9,750 (all of week 5's purchases, P_5 = 0), v_4 = 10,211.538 - 9,750 = 461.538.
    #   Week 8 (no-action C_8 = 1,115.385) is bridged by a week-8 draw repaid in week 9, at 10%/52 interest.
    #   The rest of the permanent cut, 11,000 + interest - 10,211.538, goes in week 6 (paid in week 8):
    #   v_6 = 788.462 + 0.10/52 x y_8 with y_8 = 25,000 - 1,115.385 - 10,211.538 - v_6 = 13,673.077 - v_6
    #   -> v_6 = (520 x 788.462 + 13,673.077) / 521 = 423,673.077 / 521 = 813.192, y_8 = q_9 = 12,859.885.
    shock = _deep_slump()
    off = run(DEMO, shock, protect=False)
    on = run(DEMO, shock, protect=True)
    assert off.status == on.status == OPTIMAL
    assert off.plan.payroll_cut == [0.0] * 26 and on.plan.payroll_cut == [0.0] * 26
    assert_same_plan(off, on)
    assert off.objective == approx(on.objective)
    cuts = off.plan.purchase_cut
    assert [t for t, v in enumerate(cuts, start=1) if v > 0] == [4, 5, 6]
    assert cuts[3:6] == [approx(461.538462), approx(9_750.0), approx(423_673.076923 / 521)]
    assert off.plan.revolver_draw[7] == approx(13_673.076923 - 423_673.076923 / 521)  # week 8: 12,859.885
    assert off.plan.revolver_repay[8] == approx(13_673.076923 - 423_673.076923 / 521)  # week 9
    assert sum(off.plan.revolver_draw) == approx(off.plan.revolver_draw[7])


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


def test_bad_quarter_cuts_just_in_time():
    # Before the tie-break, protect on put 3,307.69 in week 21 and nothing in week 22 (same total, same cost 550.00).
    # Latest-first (L_p = 2): no-action cash first dips below 25,000 in week 20 (23,873.08, short 1,126.92) and then
    # falls 1,653.85/wk (the 1,423.08/wk baseline loss plus 600,000 x 2%/52 = 230.77/wk of extra interest) to 13,950 in
    # week 26. So week 18 cuts 1,126.92 (paid in week 20) and weeks 19-24 each cut the next 1,653.85:
    # 1,126.92 + 6 x 1,653.85 = 11,050.
    for protect in (False, True):
        cuts = run(DEMO, SCENARIOS["bad-quarter"], protect).plan.purchase_cut
        assert [t for t, v in enumerate(cuts, start=1) if v > 0] == list(range(18, 25))
        assert cuts[18:24] == [approx(1_653.846154)] * 6
        assert cuts[17] == approx(11_050.0 - 6 * 1_653.846154)


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


def test_tie_break_keeps_no_feasible_plan():
    # NO FEASIBLE PLAN is decided by stage 1 alone; stage 2 never runs.
    res = run(DEMO, _severe_drop(), protect=True)
    assert res.status == NO_FEASIBLE_PLAN
    assert res.plan is None
    assert res.max_feasible_cash_floor == approx(22_375.0)


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
    interest = sum(simulate(DEMO, _sharp_dip(), res.plan).revolver_interest)
    assert sum(res.plan.purchase_cut) == approx(4_000.0 + interest)
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
    # Purchase cuts can add at most I_0 - I_min = 25,000 -> 22,375, still 2,625 short of C_min = 25,000.
    # The revolver must be repaid by week 26; there is no outage, capex or expansion. So only payroll closes it.
    allowed = run(DEMO, _severe_drop(), protect=False)
    assert allowed.status == OPTIMAL
    assert sum(allowed.plan.purchase_cut) == approx(25_000.0)
    payroll_cut = sum(z * 12_000.0 for z in allowed.plan.payroll_cut)
    assert payroll_cut >= 2_625.0 - TOL
    assert max(allowed.plan.payroll_cut) <= 0.10 + TOL  # z-bar
    assert min(allowed.inventory) >= 40_000.0 - TOL  # I_min
    assert "inventory floor, week 26" in allowed.binding_constraints

    protected = run(DEMO, _severe_drop(), protect=True)
    assert protected.status == NO_FEASIBLE_PLAN
    # Highest reachable minimum cash without payroll cuts: -2,625 + 25,000 = 22,375.
    assert protected.max_feasible_cash_floor == approx(22_375.0)


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
