"""Tests for core/sensitivity.py: the min-cash tornado of the SYNTHETIC demo business (issue #78).

The engine (core.financials.simulate) is the oracle; the expected numbers below are hand-derived from the
MATH_MODEL §3 recurrence and the §10 baseline economics, with the arithmetic written next to each assertion.

Baseline facts used throughout (MATH_MODEL §10): sales 50,000/wk, g = 0.35, a = 0.8, L_p = 2, W = 12,000,
O = 6,000, term loan 600,000 at 8%: interest 923.08/wk, so cash falls 1,423.08/wk from 100,000 to 63,000 at week 26.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from config import get_settings
from core.financials import ActionPlan, ScenarioShock, simulate
from core.sensitivity import DRIVERS, TornadoResult, tornado
from routes.scenarios import load_scenarios
from routes.simulate import load_business

DATA = Path(__file__).resolve().parent.parent / "data"
SETTINGS = dataclasses.replace(get_settings(), data_dir=DATA)
BUSINESS = load_business(SETTINGS)  # the same loader POST /api/simulate uses
BAD_QUARTER = {s.id: s for s in load_scenarios(SETTINGS)}["bad-quarter"].shock

TOL = 1e-6
WEEKLY_LOSS = 50_000 * 0.35 - 12_000 - 6_000 - 600_000 * 0.08 / 52  # -1,423.08 per week


@pytest.fixture(scope="module")
def base() -> TornadoResult:
    return tornado(BUSINESS, ScenarioShock())


@pytest.fixture(scope="module")
def bad() -> TornadoResult:
    return tornado(BUSINESS, BAD_QUARTER)


def entry(result: TornadoResult, key: str):
    return next(e for e in result.entries if e.key == key)


# --------------------------------------------------------------------------- shape and labels


def test_result_is_simulated_and_covers_every_driver_once(base):
    assert base.provenance == "SIMULATED"
    assert base.rel == 0.10
    assert base.scenario_name == "baseline"
    assert sorted(e.key for e in base.entries) == sorted(d.key for d in DRIVERS)


def test_base_min_cash_is_the_engine_value(base, bad):
    assert base.base_min_cash == simulate(BUSINESS, ScenarioShock(), ActionPlan()).min_cash
    assert base.base_min_cash == pytest.approx(63_000.0, abs=TOL)  # 100,000 - 26 x 1,423.08
    assert base.base_min_cash_week == 26
    assert bad.base_min_cash == pytest.approx(13_950.0, abs=TOL)  # test_scenarios.py hand check
    assert bad.base_min_cash_week == 26


def test_every_side_matches_a_direct_simulate_run(base):
    # Each reported point is exactly simulate() on the perturbed input, e.g. payroll 12,000 x 0.9 = 10,800.
    e = entry(base, "payroll")
    direct = simulate(BUSINESS.model_copy(update={"payroll": 10_800.0}), ScenarioShock(), ActionPlan())
    assert e.low.value == pytest.approx(10_800.0)
    assert e.low.min_cash == direct.min_cash
    assert e.low.min_cash_week == direct.min_cash_week
    assert e.low.delta_vs_base == pytest.approx(direct.min_cash - 63_000.0, abs=TOL)


# --------------------------------------------------------------------------- hand checks on the baseline


def test_rate_swing_is_600k_times_delta_r_times_half_a_year(base):
    # r = 8% -> 7.2% / 8.8%, so Δr = 0.008. Only interest changes: 600,000 x 0.008 x 26/52 = 2,400 over the horizon.
    e = entry(base, "base_rate")
    shift = 600_000 * 0.008 * 26 / 52
    assert shift == pytest.approx(2_400.0)
    assert (e.low.value, e.high.value) == (pytest.approx(0.072), pytest.approx(0.088))
    assert e.low.min_cash == pytest.approx(63_000 + shift, abs=TOL)  # 65,400
    assert e.high.min_cash == pytest.approx(63_000 - shift, abs=TOL)  # 60,600
    assert e.low.min_cash_week == e.high.min_cash_week == 26
    assert e.swing == pytest.approx(2 * shift, abs=TOL)  # 4,800


def test_margin_entries_follow_the_payables_timing(base):
    e = entry(base, "gross_margin")
    assert (e.low.value, e.high.value) == (pytest.approx(0.315), pytest.approx(0.385))
    # Receipts do not depend on g. Purchases P_t = (1-g) S_t change by 0.035 x 50,000 = 1,750/wk, but with L_p = 2
    # weeks 1-2 still pay P_-1, P_0 (bought before week 1 at the old margin) and P_25, P_26 fall due after week 26.
    # So by week 26 only P_1..P_24 have been paid: 24 x 1,750 = 42,000.
    assert e.low.min_cash == pytest.approx(63_000 - 24 * 1_750, abs=TOL)  # g = 0.315: 21,000
    assert e.low.min_cash_week == 26
    # g = 0.385: from week 3 cash rises 1,750 - 1,423.08 = 326.92/wk, so the low point is week 2:
    # C_2 = 100,000 - 2 x 1,423.08 = 97,153.85 (C_26 = 63,000 + 42,000 = 105,000 is the high point instead).
    assert e.high.min_cash == pytest.approx(100_000 + 2 * WEEKLY_LOSS, abs=TOL)
    assert e.high.min_cash_week == 2
    high_run = simulate(BUSINESS.model_copy(update={"gross_margin": 0.385}), ScenarioShock(), ActionPlan())
    assert high_run.cash[-1] == pytest.approx(63_000 + 24 * 1_750, abs=TOL)
    assert e.swing == pytest.approx(100_000 + 2 * WEEKLY_LOSS - 21_000, abs=TOL)  # 76,153.85


def test_store_sales_move_all_stores_together(base):
    e = entry(base, "store_sales")
    assert (e.base_value, e.low.value, e.high.value) == (50_000.0, pytest.approx(45_000.0), pytest.approx(55_000.0))
    # -10% (45,000/wk; S_0 = 50,000 and P_-1 = P_0 = 32,500 stay as recorded). Cash change by week:
    #   wk 1: R = 0.8 x 45,000 + 0.2 x 50,000 = 46,000, pay 32,500, fixed 18,923.08 -> -5,423.08
    #   wk 2: R = 45,000, pay 32,500 -> -6,423.08
    #   wk 3-26: R = 45,000, pay 0.65 x 45,000 = 29,250 -> -3,173.08 x 24
    # Total -88,000 -> C_26 = 12,000, the low point.
    fixed = 12_000 + 6_000 + 600_000 * 0.08 / 52
    c26 = 100_000 + (46_000 - 32_500 - fixed) + (45_000 - 32_500 - fixed) + 24 * (45_000 - 29_250 - fixed)
    assert c26 == pytest.approx(12_000.0, abs=TOL)
    assert e.low.min_cash == pytest.approx(c26, abs=TOL)
    assert e.low.min_cash_week == 26
    # +10%: wk 1 R = 0.8 x 55,000 + 0.2 x 50,000 = 54,000, so C_1 = 100,000 + 54,000 - 32,500 - 18,923.08 =
    # 102,576.92, and cash only rises after that, so the low point is week 1.
    assert e.high.min_cash == pytest.approx(100_000 + 54_000 - 32_500 - fixed, abs=TOL)
    assert e.high.min_cash_week == 1


@pytest.mark.parametrize("key,weekly", [("payroll", 12_000.0), ("opex", 6_000.0)])
def test_fixed_costs_move_min_cash_by_26_weeks_of_the_step(base, key, weekly):
    # ±10% of a weekly cost for 26 weeks; cash still falls every week on both sides, so the low point stays week 26.
    e = entry(base, key)
    step = 26 * 0.10 * weekly  # payroll 31,200; opex 15,600
    assert e.low.min_cash == pytest.approx(63_000 + step, abs=TOL)
    assert e.high.min_cash == pytest.approx(63_000 - step, abs=TOL)
    assert e.low.min_cash_week == e.high.min_cash_week == 26
    assert e.swing == pytest.approx(2 * step, abs=TOL)


def test_timing_only_drivers_have_zero_swing_on_the_flat_baseline(base):
    # Sales are flat at 50,000 = S_0, so total receipts to week 26 are 26 x 50,000 whatever a is, and every purchase
    # (pre-horizon or not) is 32,500, so paying one week sooner or later changes nothing by week 26.
    for key in ("same_week_collection", "supplier_lag_weeks"):
        e = entry(base, key)
        assert e.status == "OK"
        assert e.low.min_cash == pytest.approx(63_000.0, abs=TOL)
        assert e.high.min_cash == pytest.approx(63_000.0, abs=TOL)
        assert e.swing == pytest.approx(0.0, abs=TOL)


def test_inputs_that_act_only_through_actions_are_not_applicable_without_a_plan(base):
    """Review of #98 (issue #115): a 0.00 swing would read as "this input doesn't matter". With no revolver balance or
    draw (B_0 = 0), no backup supplier, and B-bar never read by simulate(), these four are NOT_APPLICABLE instead."""
    expected = {
        "revolver_spread": "revolver is never drawn",
        "revolver_limit": "used only by the optimizer",
        "backup_premium": "does not use the backup supplier",
        "backup_switch_fee": "does not use the backup supplier",
    }
    for key, why in expected.items():
        e = entry(base, key)
        assert e.status == "NOT_APPLICABLE", key
        assert e.low is None and e.high is None and e.swing is None and e.max_abs_delta is None
        assert why in e.note


def test_revolver_limit_is_not_applicable_even_when_the_plan_draws():
    plan = ActionPlan(revolver_draw=[0.0, 0.0, 0.0, 10_000.0] + [0.0] * 22)
    res = tornado(BUSINESS, ScenarioShock(), plan=plan)
    assert entry(res, "revolver_limit").status == "NOT_APPLICABLE"
    # s_R now acts: 10,000 outstanding from week 5 to week 26 = 22 weeks of B_{t-1} s_R / 52 interest.
    # A +-10% step on s_R = 0.02 moves it by 0.002: 10,000 x 0.002 x 22 / 52 = 8.4615 a side, so swing = 16.923.
    e = entry(res, "revolver_spread")
    assert e.status == "OK"
    assert e.swing == pytest.approx(2 * 10_000 * 0.002 * 22 / 52, abs=TOL)
    assert e.max_abs_delta == pytest.approx(10_000 * 0.002 * 22 / 52, abs=TOL)


def test_backup_terms_act_when_the_plan_uses_the_backup_supplier(bad):
    res = tornado(BUSINESS, BAD_QUARTER, plan=ActionPlan(use_backup_supplier=True))
    for key in ("backup_premium", "backup_switch_fee"):
        e = entry(res, key)
        assert e.status == "OK" and e.swing > 0.0, key
        assert e.max_abs_delta == pytest.approx(max(abs(e.low.delta_vs_base), abs(e.high.delta_vs_base)), abs=TOL)
    # F_b = 2,000 is paid once in week 1, before the low point, so +-10% moves min cash by 200 a side.
    assert entry(res, "backup_switch_fee").swing == pytest.approx(400.0, abs=TOL)


def test_max_abs_delta_reports_the_larger_side(base):
    # Payroll +-10% = +-1,200 a week for 26 weeks: min cash moves by 31,200 each way, so the swing is 62,400.
    e = entry(base, "payroll")
    assert e.swing == pytest.approx(62_400.0, abs=1e-3)
    assert e.max_abs_delta == pytest.approx(31_200.0, abs=1e-3)


def test_phi_is_not_applicable_without_an_outage(base):
    e = entry(base, "dependent_share")
    assert e.status == "NOT_APPLICABLE"
    assert e.low is None and e.high is None and e.swing is None and e.base_value is None
    assert "no supplier outage" in e.note


# --------------------------------------------------------------------------- discrete supplier lag


def test_supplier_lag_moves_by_one_week_and_reshapes_prior_purchases(base):
    e = entry(base, "supplier_lag_weeks")
    assert e.step == "-1 / +1 week"
    assert (e.base_value, e.low.value, e.high.value) == (2.0, 1.0, 3.0)
    assert BUSINESS.prior_purchases == [32_500.0, 32_500.0]  # input untouched


def test_bad_quarter_longer_lag_deepens_the_week_7_trough(bad):
    # L_p = 3 (prior purchases P_-2 = P_-1 = P_0 = 32,500). Sales: 50k, 50k, then 40k in wk 3-4 (20% drop) and
    # 24k in wk 5-7 (outage loses 0.4 x 40k). Purchases are 0.65 x sales, paid 3 weeks later. Fixed costs with
    # +200bp: 12,000 + 6,000 + 600,000 x 10%/52 = 19,153.85.
    fixed = 12_000 + 6_000 + 600_000 * 0.10 / 52
    receipts = [50_000, 50_000, 42_000, 40_000, 27_200, 24_000, 24_000]  # R_t = 0.8 S_t + 0.2 S_(t-1)
    paid = [32_500, 32_500, 32_500, 32_500, 32_500, 26_000, 26_000]  # P_-2, P_-1, P_0, P_1, P_2, P_3, P_4
    c7 = 100_000 + sum(receipts) - sum(paid) - 7 * fixed
    assert c7 == pytest.approx(8_623.076923, abs=1e-5)
    e = entry(bad, "supplier_lag_weeks")
    assert e.high.min_cash == pytest.approx(c7, abs=TOL)
    assert e.high.min_cash_week == 7
    # L_p = 1: the trough is shallower and the low point stays at week 26 with the base value 13,950.
    assert e.low.min_cash == pytest.approx(13_950.0, abs=TOL)
    assert e.swing == pytest.approx(13_950.0 - c7, abs=TOL)  # 5,326.92


# --------------------------------------------------------------------------- bad quarter hand checks


def test_bad_quarter_rate_swing_is_unchanged_by_the_other_shocks(bad):
    # The +200bp shock adds Δr on top of r^base; scaling r^base by ±10% still moves interest by 2,400 each way.
    e = entry(bad, "base_rate")
    assert e.low.min_cash == pytest.approx(13_950 + 2_400, abs=TOL)
    assert e.high.min_cash == pytest.approx(13_950 - 2_400, abs=TOL)
    assert e.swing == pytest.approx(4_800.0, abs=TOL)


def test_bad_quarter_phi_swing_is_lost_margin_on_the_outage(bad):
    # φ = 0.40 -> 0.36 / 0.44. The outage (wk 5-7) sits inside the 20% demand drop, so base-store demand is 40,000
    # and lost sales change by 0.04 x 40,000 x 3 weeks = 4,800; settled by week 26, each lost dollar costs g = 0.35.
    e = entry(bad, "dependent_share")
    move = 0.04 * 40_000 * 3 * 0.35  # 1,680
    assert (e.low.value, e.high.value) == (pytest.approx(0.36), pytest.approx(0.44))
    assert e.low.min_cash == pytest.approx(13_950 + move, abs=TOL)
    assert e.high.min_cash == pytest.approx(13_950 - move, abs=TOL)
    assert e.swing == pytest.approx(2 * move, abs=TOL)  # 3,360


# --------------------------------------------------------------------------- ordering


@pytest.mark.parametrize("which", ["base", "bad"])
def test_entries_are_sorted_by_swing_with_ties_in_driver_order(which, request):
    result = request.getfixturevalue(which)
    order = [d.key for d in DRIVERS]
    computed = [e for e in result.entries if e.swing is not None]
    rest = [e for e in result.entries if e.swing is None]
    assert result.entries == computed + rest  # every entry without a swing sorts last
    for a, b in zip(computed, computed[1:], strict=False):
        assert round(a.swing, 6) >= round(b.swing, 6)
        if round(a.swing, 6) == round(b.swing, 6):
            assert order.index(a.key) < order.index(b.key)


def test_top_five_drivers(base, bad):
    assert [e.key for e in base.entries[:5]] == ["store_sales", "gross_margin", "payroll", "opex", "base_rate"]
    assert [e.key for e in bad.entries[:5]] == ["store_sales", "gross_margin", "payroll", "opex",
                                                "supplier_lag_weeks"]


# --------------------------------------------------------------------------- purity and infeasible steps


def test_inputs_are_not_mutated_and_runs_are_deterministic():
    params_before = BUSINESS.model_dump()
    shock_before = BAD_QUARTER.model_dump()
    first = tornado(BUSINESS, BAD_QUARTER)
    assert BUSINESS.model_dump() == params_before
    assert BAD_QUARTER.model_dump() == shock_before
    assert tornado(BUSINESS, BAD_QUARTER) == first


def test_out_of_range_value_is_reported_infeasible_not_dropped():
    # rel = 0.3 pushes a = 0.8 to 1.04, which the model rejects (a share cannot exceed 1); g = 0.35 x 1.3 is fine.
    result = tornado(BUSINESS, ScenarioShock(), rel=0.3)
    e = entry(result, "same_week_collection")
    assert e.status == "INFEASIBLE" and e.swing is None
    assert e.low.status == "OK" and e.low.value == pytest.approx(0.56)
    assert e.high.status == "INFEASIBLE" and e.high.min_cash is None
    assert e.high.value == pytest.approx(1.04)
    assert "same_week_collection" in e.high.reason
    assert result.entries.index(e) > max(result.entries.index(x) for x in result.entries if x.status == "OK")


def test_run_rejected_by_simulate_is_reported_infeasible():
    # A week-1 purchase cut of 30,000 is feasible at base (P_1 = 32,500 - 30,000 = 2,500), but with sales 10% lower
    # P_1 = 0.65 x 45,000 - 30,000 = -750 < 0, which simulate() refuses.
    plan = ActionPlan(purchase_cut=[30_000.0] + [0.0] * 25)
    result = tornado(BUSINESS, ScenarioShock(), plan=plan)
    e = entry(result, "store_sales")
    assert e.status == "INFEASIBLE" and e.swing is None
    assert e.low.status == "INFEASIBLE" and "purchases cannot be negative" in e.low.reason
    assert e.high.status == "OK"


@pytest.mark.parametrize("rel", [0.0, -0.1, float("nan"), float("inf")])
def test_rel_must_be_positive_and_finite(rel):
    with pytest.raises(ValueError, match="rel must be"):
        tornado(BUSINESS, ScenarioShock(), rel=rel)
