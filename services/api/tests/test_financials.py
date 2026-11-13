"""Golden and property tests for core/financials.py (docs/MATH_MODEL.md §1-§3, §5, §9).

Every expected number in the golden tests is hand-computed from the formulas in MATH_MODEL.md;
the derivation is written next to each assertion so a finance reviewer can check it without code.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.financials import (
    CASCADE_NODES,
    ActionPlan,
    BusinessParams,
    DemandShock,
    RateShock,
    ScenarioShock,
    SupplierOutage,
    cascade_deltas,
    demand_multipliers,
    simulate,
)

TOL = 1e-3
T = 26
# Term-loan interest J_t = D r_t / 52
J8 = 600_000 * 0.08 / 52  # 923.0769...
J10 = 600_000 * 0.10 / 52  # 1153.846...


def golden_params(**overrides) -> BusinessParams:
    """MATH_MODEL §9 'Common' parameters: no revolver, capex, expansion, outage; A = 0."""
    base = dict(
        horizon_weeks=T,
        cash_0=100_000.0,
        stores=[{"name": "all stores", "base_sales": 50_000.0}],
        sales_0=50_000.0,
        gross_margin=0.35,
        same_week_collection=0.8,
        supplier_lag_weeks=1,
        prior_purchases=[32_500.0],  # P_0
        inventory_0=60_000.0,  # not used by §9 cash numbers; explicit by rule
        payroll=12_000.0,
        opex=6_000.0,
        term_loan_principal_1=600_000.0,
        amortization=0.0,
        base_rate=0.08,
        revolver_balance_0=0.0,
        revolver_limit=150_000.0,
        revolver_spread=0.02,
        backup_premium=0.12,
        backup_switch_fee=2_000.0,
    )
    base.update(overrides)
    return BusinessParams.model_validate(base)


NO_SHOCK = ScenarioShock(name="baseline")
NO_ACTION = ActionPlan()


def approx(x):
    return pytest.approx(x, abs=TOL)


# ---------------------------------------------------------------- golden cases (§9)


def test_golden_case_a_no_shock():
    res = simulate(golden_params(), NO_SHOCK, NO_ACTION)
    # R_t = 0.8*50k + 0.2*50k = 50,000
    assert res.receipts[:3] == [approx(50_000.0)] * 3
    # outflow = P_{t-1} 32,500 + W 12,000 + O 6,000 + J 923.077 = 51,423.077
    assert res.interest[0] == approx(923.077)
    assert res.payables_paid[0] == approx(32_500.0)
    assert res.cash[0] == approx(98_576.923)
    assert res.cash[1] == approx(97_153.846)
    assert res.cash[2] == approx(95_730.769)
    # constant weekly burn of 1,423.077 -> C_26 = 100,000 - 26*1,423.077
    assert res.cash[-1] == approx(100_000.0 - 26 * (51_423.0769230769 - 50_000.0))
    assert res.min_cash == approx(res.cash[-1])
    assert res.min_cash_week == 26


def test_golden_case_b_demand_drop_week_2_only():
    shock = ScenarioShock(
        name="20% drop week 2", demand=DemandShock(delta=0.2, start_week=2, end_week=2, recovery_weeks=0)
    )
    res = simulate(golden_params(), shock, NO_ACTION)
    assert res.demand_multiplier[:4] == [1.0, 0.8, 1.0, 1.0]
    # week 1 unchanged
    assert res.receipts[0] == approx(50_000.0)
    assert res.cash[0] == approx(98_576.923)
    # week 2: S_2 = 40,000; R_2 = 0.8*40k + 0.2*50k = 42,000; pays P_1 = 32,500
    assert res.sales[1] == approx(40_000.0)
    assert res.receipts[1] == approx(42_000.0)
    assert res.payables_paid[1] == approx(32_500.0)
    assert res.cash[1] == approx(89_153.846)
    # week 3: R_3 = 0.8*50k + 0.2*40k = 48,000; pays P_2 = 0.65*40k = 26,000
    assert res.receipts[2] == approx(48_000.0)
    assert res.purchases[1] == approx(26_000.0)
    assert res.payables_paid[2] == approx(26_000.0)
    # outflow = 26,000 + 12,000 + 6,000 + 923.077 = 44,923.077
    assert res.cash[2] == approx(92_230.769)


def test_golden_case_c_rate_shock_from_week_2():
    shock = ScenarioShock(name="+200bp from week 2", rate=RateShock(delta_rate=0.02, start_week=2))
    res = simulate(golden_params(), shock, NO_ACTION)
    assert res.rate[:3] == [approx(0.08), approx(0.10), approx(0.10)]
    assert res.interest[0] == approx(923.077)
    assert res.interest[1] == approx(1_153.846)
    assert res.cash[0] == approx(98_576.923)
    assert res.cash[1] == approx(96_923.077)
    assert res.cash[2] == approx(95_269.231)


# ---------------------------------------------------------------- other hand-checked cases


def test_runway_not_reached_is_none_and_labeled():
    res = simulate(golden_params(), NO_SHOCK, NO_ACTION)
    assert all(c >= 0 for c in res.cash)
    assert res.runway_week is None
    assert res.runway_label == "> 26 weeks"


def test_runway_first_negative_week():
    # C_0 = 2,000 with a weekly burn of 1,423.077: C_1 = 576.923, C_2 = -846.154
    res = simulate(golden_params(cash_0=2_000.0), NO_SHOCK, NO_ACTION)
    assert res.cash[0] == approx(576.923)
    assert res.cash[1] == approx(-846.154)
    assert res.runway_week == 2
    assert res.runway_label == "week 2"


def _outage_weeks_2_3() -> ScenarioShock:
    kappa = [1.0] * T
    kappa[1] = kappa[2] = 0.0  # primary supplier down in weeks 2-3
    return ScenarioShock(name="outage w2-3", supplier=SupplierOutage(availability=kappa, dependent_share=0.4))


def test_supplier_outage_without_backup_loses_sales():
    res = simulate(golden_params(), _outage_weeks_2_3(), NO_ACTION)
    # lambda = phi (1 - kappa) = 0.4 ; S = 50k (1 - 0.4) = 30,000
    assert res.lost_sales_fraction[1] == approx(0.4)
    assert res.sales[1] == approx(30_000.0)
    assert res.lost_sales[1] == approx(20_000.0)
    # C_2 = 98,576.923 + (0.8*30k + 0.2*50k = 34,000) - 51,423.077 = 81,153.846
    assert res.cash[1] == approx(81_153.846)
    # C_3 = 81,153.846 + (0.8*30k + 0.2*30k = 30,000) - (0.65*30k = 19,500 + 18,923.077)
    assert res.cash[2] == approx(72_730.769)


def test_backup_supplier_removes_lost_sales():
    res = simulate(golden_params(), _outage_weeks_2_3(), ActionPlan(use_backup_supplier=True))
    assert all(ls == approx(0.0) for ls in res.lost_sales)
    assert res.sales[:4] == [approx(50_000.0)] * 4
    # premium = pi (1-g) S_dem lambda = 0.12 * 0.65 * 50k * 0.4 = 1,560 in outage weeks
    assert res.backup_premium[1] == approx(1_560.0)
    assert res.purchases[1] == approx(34_060.0)
    # week 1: switching fee F_b = 2,000 -> C_1 = 98,576.923 - 2,000
    assert res.backup_fee[0] == approx(2_000.0)
    assert res.cash[0] == approx(96_576.923)
    # week 2: pays P_1 = 32,500 -> C_2 = 96,576.923 - 1,423.077
    assert res.cash[1] == approx(95_153.846)
    # week 3: pays P_2 = 34,060 -> outflow 52,983.077 -> C_3 = 92,170.769
    assert res.cash[2] == approx(92_170.769)
    # inventory unchanged: the premium is a cost, not stock (I_t = I_{t-1} - v_t)
    assert res.inventory == [approx(60_000.0)] * T


def test_purchase_cut_lowers_inventory_and_delays_cash_effect():
    v = [0.0] * T
    v[1] = 5_000.0  # cut week-2 purchases by 5k
    res = simulate(golden_params(), NO_SHOCK, ActionPlan(purchase_cut=v))
    assert res.inventory[0] == approx(60_000.0)
    assert res.inventory[1] == approx(55_000.0)
    assert res.inventory[-1] == approx(55_000.0)
    assert res.purchases[1] == approx(27_500.0)
    # paid with lag L_p = 1, so cash improves from week 3
    assert res.cash[1] == approx(97_153.846)
    assert res.cash[2] == approx(95_730.769 + 5_000.0)


def test_revolver_draw_and_interest():
    y = [0.0] * T
    y[0] = 10_000.0
    q = [0.0] * T
    q[2] = 10_000.0
    res = simulate(golden_params(), NO_SHOCK, ActionPlan(revolver_draw=y, revolver_repay=q))
    assert res.revolver_balance[:4] == [approx(10_000.0), approx(10_000.0), approx(0.0), approx(0.0)]
    # J^R_t = B_{t-1} (r + s_R) / 52 = 10,000 * 0.10 / 52 = 19.231 in weeks 2 and 3
    jr = 10_000.0 * 0.10 / 52
    assert res.revolver_interest[0] == approx(0.0)
    assert res.revolver_interest[1] == approx(jr)
    assert res.revolver_interest[2] == approx(jr)
    assert res.revolver_interest[3] == approx(0.0)
    assert res.cash[0] == approx(98_576.923 + 10_000.0)
    assert res.cash[1] == approx(97_153.846 + 10_000.0 - jr)
    assert res.cash[2] == approx(95_730.769 - 2 * jr)


def test_payroll_cut_capex_deferral_and_expansion_delay():
    z = [0.0] * T
    z[0] = 0.5
    params = golden_params(capex=3_000.0, expansion_outflow=4_000.0, expansion_sales=1_000.0)
    res_none = simulate(params, NO_SHOCK, NO_ACTION)
    res_all = simulate(
        params, NO_SHOCK, ActionPlan(payroll_cut=z, defer_capex=True, delay_expansion=True)
    )
    # week 1 without actions: S_1 = 51,000, R_1 = 0.8*51k + 0.2*50k = 50,800;
    # outflow 51,423.077 + K 3,000 + E 4,000 -> C_1 = 100,000 + 50,800 - 58,423.077
    assert res_none.sales[0] == approx(51_000.0)
    assert res_none.cash[0] == approx(92_376.923)
    # with all three: S_1 = 50,000, R_1 = 50,000; payroll (1-0.5)*12k = 6,000; no K, no E
    assert res_all.payroll[0] == approx(6_000.0)
    assert res_all.capex[0] == approx(0.0)
    assert res_all.expansion_outflow[0] == approx(0.0)
    assert res_all.cash[0] == approx(100_000.0 + 50_000.0 - 32_500.0 - 6_000.0 - 6_000.0 - J8)


def test_amortization_reduces_principal_and_interest():
    res = simulate(golden_params(amortization=10_000.0), NO_SHOCK, NO_ACTION)
    # D_1 = 600k, D_2 = 590k; J_2 = 590k * 0.08 / 52
    assert res.term_loan_principal[:2] == [approx(600_000.0), approx(590_000.0)]
    assert res.interest[1] == approx(590_000.0 * 0.08 / 52)
    assert res.cash[0] == approx(98_576.923 - 10_000.0)


def test_two_week_supplier_lag_uses_prior_purchases():
    params = golden_params(supplier_lag_weeks=2, prior_purchases=[30_000.0, 31_000.0])
    res = simulate(params, NO_SHOCK, NO_ACTION)
    # week 1 pays P_{-1} = 30,000, week 2 pays P_0 = 31,000, week 3 pays P_1 = 32,500
    assert res.payables_paid[:3] == [approx(30_000.0), approx(31_000.0), approx(32_500.0)]


def test_demand_shock_does_not_scale_expansion_sales():
    # S_dem_t = m_t * sum S_base + (1 - x_e) X_t : the shock multiplies base sales only, not X_t
    params = golden_params(expansion_sales=1_000.0)
    shock = ScenarioShock(name="b+X", demand=DemandShock(delta=0.2, start_week=2, end_week=2, recovery_weeks=0))
    res = simulate(params, shock, NO_ACTION)
    # S_1 = 51,000 ; S_2 = 0.8 * 50,000 + 1,000 = 41,000 (not 0.8 * 51,000 = 40,800)
    assert res.sales[0] == approx(51_000.0)
    assert res.sales[1] == approx(41_000.0)
    # R_2 = 0.8 * 41,000 + 0.2 * 51,000 = 43,000
    assert res.receipts[1] == approx(43_000.0)
    # C_1 = 100,000 + 50,800 - 51,423.077 = 99,376.923
    # C_2 = 99,376.923 + 43,000 - (P_1 = 0.65 * 51,000 = 33,150) - 18,923.077 = 90,303.846
    assert res.cash[0] == approx(99_376.923)
    assert res.cash[1] == approx(90_303.846)
    # delaying the expansion removes X_t: S_2 = 40,000
    delayed = simulate(params, shock, ActionPlan(delay_expansion=True))
    assert delayed.sales[1] == approx(40_000.0)


def test_revolver_repayment_above_balance_is_rejected():
    q = [0.0] * T
    q[0] = 1_000.0  # B_0 = 0, so B_1 = -1,000
    with pytest.raises(ValueError, match="week 1: revolver repayment"):
        simulate(golden_params(), NO_SHOCK, ActionPlan(revolver_repay=q))


def test_revolver_round_off_within_tolerance_is_accepted():
    y = [0.0] * T
    y[0] = 1_000.0
    q = [0.0] * T
    q[1] = 1_000.0 + 1e-9
    res = simulate(golden_params(), NO_SHOCK, ActionPlan(revolver_draw=y, revolver_repay=q))
    assert res.revolver_balance[1] == approx(0.0)


def test_amortization_above_principal_is_rejected():
    # D_1 = 1,000, A = 600/wk: D_2 = 400, then week 2 would leave D_3 = -200
    with pytest.raises(ValueError, match="week 2: amortization"):
        simulate(golden_params(term_loan_principal_1=1_000.0, amortization=600.0), NO_SHOCK, NO_ACTION)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_nan_and_inf_inputs_are_rejected(bad):
    with pytest.raises(ValueError):
        golden_params(cash_0=bad)
    with pytest.raises(ValueError):
        golden_params(base_rate=bad)
    with pytest.raises(ValueError):
        golden_params(payroll=[bad] * T)
    with pytest.raises(ValueError):
        ActionPlan(purchase_cut=[bad] * T)
    with pytest.raises(ValueError):
        RateShock(delta_rate=bad, start_week=2)


def test_provenance_only_fictional_labels():
    assert golden_params(provenance="ILLUSTRATIVE").provenance == "ILLUSTRATIVE"
    for label in ("REAL HISTORICAL", "REAL_HISTORICAL", "SIMULATED"):
        with pytest.raises(ValueError):
            golden_params(provenance=label)


def test_demand_multiplier_linear_recovery():
    m = demand_multipliers(DemandShock(delta=0.3, start_week=3, end_week=4, recovery_weeks=3), 10)
    # 1 - 0.3 (1 - (t - 4)/3) for t = 5, 6, 7
    assert m == pytest.approx([1.0, 1.0, 0.7, 0.7, 0.8, 0.9, 1.0, 1.0, 1.0, 1.0], abs=1e-12)


# ---------------------------------------------------------------- properties


@pytest.mark.parametrize("weeks", [(2, 2, 0), (3, 10, 4), (1, 26, 0)])
def test_demand_shock_monotonicity(weeks):
    t1, t2, rho = weeks
    mins = []
    for delta in [0.0, 0.1, 0.2, 0.4, 0.6]:
        demand = DemandShock(delta=delta, start_week=t1, end_week=t2, recovery_weeks=rho)
        s = ScenarioShock(name=f"d{delta}", demand=demand)
        mins.append(simulate(golden_params(), s, NO_ACTION).min_cash)
    assert all(b <= a + 1e-9 for a, b in zip(mins, mins[1:], strict=False))


def test_rate_shock_increases_interest():
    base = simulate(golden_params(), NO_SHOCK, NO_ACTION)
    for dr in [0.005, 0.02, 0.05]:
        shocked = simulate(
            golden_params(), ScenarioShock(name="rate", rate=RateShock(delta_rate=dr, start_week=5)), NO_ACTION
        )
        assert all(s >= b - 1e-12 for s, b in zip(shocked.interest, base.interest, strict=True))
        assert sum(shocked.interest) > sum(base.interest)
        assert shocked.min_cash < base.min_cash


def test_deterministic():
    shock = ScenarioShock(name="x", demand=DemandShock(delta=0.25, start_week=4, end_week=8, recovery_weeks=5))
    a = simulate(golden_params(), shock, NO_ACTION)
    b = simulate(golden_params(), shock, NO_ACTION)
    assert a.model_dump() == b.model_dump()


def test_result_arrays_have_horizon_length():
    res = simulate(golden_params(), NO_SHOCK, NO_ACTION)
    for node in CASCADE_NODES.values():
        assert len(getattr(res, node)) == T
    assert res.weeks == list(range(1, T + 1))
    assert res.provenance == "SIMULATED"


# ---------------------------------------------------------------- cascade deltas (§5)


def test_cascade_deltas_case_b():
    base = simulate(golden_params(), NO_SHOCK, NO_ACTION)
    shock = ScenarioShock(name="b", demand=DemandShock(delta=0.2, start_week=2, end_week=2, recovery_weeks=0))
    scen = simulate(golden_params(), shock, NO_ACTION)
    d = cascade_deltas(base, scen)
    assert set(d.nodes) == set(CASCADE_NODES)
    assert d.nodes["Sales"].per_week[1] == approx(-10_000.0)
    assert d.nodes["Receipts"].per_week[1] == approx(-8_000.0)
    assert d.nodes["Receipts"].per_week[2] == approx(-2_000.0)
    assert d.nodes["Payables"].per_week[2] == approx(-6_500.0)
    # Cash: C_2 89,153.846 - 97,153.846 = -8,000 ; C_3 92,230.769 - 95,730.769 = -3,500
    assert d.nodes["Cash"].per_week[1] == approx(-8_000.0)
    assert d.nodes["Cash"].per_week[2] == approx(-3_500.0)
    assert d.nodes["Cash"].max_abs == approx(8_000.0)
    assert d.nodes["Interest"].max_abs == approx(0.0)
    assert d.min_cash_delta == approx(-3_500.0)
    assert ("Demand", "Purchases") in d.edges
    assert all(src in CASCADE_NODES and dst in CASCADE_NODES for src, dst in d.edges)


def test_cascade_deltas_rejects_mismatched_horizons():
    a = simulate(golden_params(), NO_SHOCK, NO_ACTION)
    b = simulate(golden_params(horizon_weeks=10), NO_SHOCK, NO_ACTION)
    with pytest.raises(ValueError):
        cascade_deltas(a, b)


# ---------------------------------------------------------------- input validation


def test_initial_conditions_are_required():
    with pytest.raises(ValueError):
        BusinessParams.model_validate(
            {k: v for k, v in golden_params().model_dump().items() if k != "sales_0"}
        )


def test_prior_purchases_length_must_match_lag():
    with pytest.raises(ValueError):
        golden_params(supplier_lag_weeks=2, prior_purchases=[32_500.0])


def test_series_length_must_match_horizon():
    with pytest.raises(ValueError):
        golden_params(payroll=[12_000.0] * 5)
    with pytest.raises(ValueError):
        simulate(golden_params(), NO_SHOCK, ActionPlan(purchase_cut=[0.0] * 5))


# ---------------------------------------------------------------- demo fixture


def test_demo_business_fixture_loads_and_is_synthetic():
    path = Path(__file__).resolve().parent.parent / "data" / "demo_business.json"
    doc = json.loads(path.read_text())
    assert doc["provenance"] == "SYNTHETIC"
    params = BusinessParams.model_validate(doc["business"])
    assert params.provenance == "SYNTHETIC"
    assert [s.base_sales for s in params.stores] == [18_000.0, 17_000.0, 15_000.0]
    assert params.supplier_lag_weeks == 2
    res = simulate(params, NO_SHOCK, NO_ACTION)
    assert len(res.cash) == params.horizon_weeks
