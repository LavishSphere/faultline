"""Demo business on MATH_MODEL §10 values and the named stress scenarios in data/scenarios.json (issue #19).

Everything here is SYNTHETIC: a fictional business and invented stress paths. The engine is the oracle for the
cash paths; the hand-checked numbers below come from the §10 "baseline economics" arithmetic.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from config import get_settings
from core.financials import ActionPlan, ScenarioShock, SimulationResult, simulate
from routes.scenarios import load_scenarios
from routes.simulate import load_business

DATA = Path(__file__).resolve().parent.parent / "data"
SETTINGS = dataclasses.replace(get_settings(), data_dir=DATA)

BUSINESS_DOC = json.loads((DATA / "demo_business.json").read_text(encoding="utf-8"))
SCENARIOS_DOC = json.loads((DATA / "scenarios.json").read_text(encoding="utf-8"))
BUSINESS = load_business(SETTINGS)  # the same loader POST /api/simulate uses
SCENARIOS = {s.id: s for s in load_scenarios(SETTINGS)}  # the same loader GET /api/scenarios uses
BASELINE = simulate(BUSINESS, ScenarioShock(), ActionPlan())

COMPONENTS = ("rate-plus-200bp", "demand-drop-20pct-6wk", "supplier-outage-3wk")
COMBINED = "bad-quarter"

# Expected direction of min cash vs baseline. Every scenario is an adverse shock, so min cash must fall.
EXPECTED_DIRECTION = {
    "rate-plus-200bp": "lower",  # more interest, nothing else changes
    "demand-drop-20pct-6wk": "lower",  # lost gross margin on lost sales
    "supplier-outage-3wk": "lower",  # lost gross margin on the outage share of sales
    "bad-quarter": "lower",  # all three at once
}

WEEKLY_EXTRA_INTEREST = 600_000 * 0.02 / 52  # +200bp on the 600k floating term loan = 230.769.../wk
G = 0.35  # gross margin: each lost sales dollar costs 0.35 of cash once receipts and payables have settled

# Lost base-store sales, by hand. Demand: 20% of 50,000 = 10,000/wk for weeks 3-8 (6 weeks), then the §1 recovery
# m_t = 1 - 0.2 (1 - k/4) for k = 1..4 loses 7,500 + 5,000 + 2,500 + 0. Outage: phi = 0.40 of 50,000 = 20,000/wk for
# weeks 5-7. Combined: weeks 5-7 sit inside the demand drop, so the outage loses 0.40 x 40,000 = 16,000/wk there.
LOST_SALES_DEMAND = 6 * 10_000 + 7_500 + 5_000 + 2_500  # 75,000
LOST_SALES_OUTAGE = 3 * 20_000  # 60,000
LOST_SALES_OUTAGE_IN_DEMAND_DROP = 3 * 16_000  # 48,000

# Hand-checked min cash. Baseline loses 1,423.08/wk, so cash falls to 63,000 at week 26 (MATH_MODEL §10), and every
# shock here has fully settled by week 26 (last lost sale week 11, paid for by week 13), so min cash = C_26.
HAND_MIN_CASH = {
    "rate-plus-200bp": 63_000 - 26 * WEEKLY_EXTRA_INTEREST,  # 63,000 - 6,000 = 57,000
    "demand-drop-20pct-6wk": 63_000 - G * LOST_SALES_DEMAND,  # 63,000 - 26,250 = 36,750
    "supplier-outage-3wk": 63_000 - G * LOST_SALES_OUTAGE,  # 63,000 - 21,000 = 42,000
    "bad-quarter": 63_000 - 26 * WEEKLY_EXTRA_INTEREST
    - G * (LOST_SALES_DEMAND + LOST_SALES_OUTAGE_IN_DEMAND_DROP),  # 63,000 - 6,000 - 43,050 = 13,950
}


def _run(scenario_id: str) -> SimulationResult:
    return simulate(BUSINESS, SCENARIOS[scenario_id].shock, ActionPlan())


# --------------------------------------------------------------------------- demo business (§10)


def test_demo_business_uses_math_model_section_10_values():
    assert BUSINESS_DOC["provenance"] == "SYNTHETIC"
    b = BUSINESS
    assert b.provenance == "SYNTHETIC"
    assert b.horizon_weeks == 26
    assert [s.base_sales for s in b.stores] == [18_000.0, 17_000.0, 15_000.0]
    assert (b.gross_margin, b.same_week_collection, b.supplier_lag_weeks) == (0.35, 0.80, 2)
    assert (b.payroll, b.opex) == (12_000.0, 6_000.0)
    assert (b.term_loan_principal_1, b.base_rate, b.amortization) == (600_000.0, 0.08, 0.0)
    assert (b.revolver_limit, b.revolver_spread, b.revolver_balance_0) == (150_000.0, 0.02, 0.0)
    assert (b.cash_0, b.min_cash) == (100_000.0, 25_000.0)
    assert (b.inventory_0, b.min_inventory) == (65_000.0, 40_000.0)
    assert (b.sales_0, b.prior_purchases) == (50_000.0, [32_500.0, 32_500.0])
    assert (b.backup_premium, b.backup_switch_fee) == (0.12, 2_000.0)
    # K_t, E_t, X_t are per-case placeholders: zero in the base business.
    assert (b.capex, b.expansion_outflow, b.expansion_sales) == (0.0, 0.0, 0.0)
    assert BUSINESS_DOC["scenario_parameters"]["supplier_outage_dependent_share"] == 0.40


def test_optimizer_parameters_record_section_10_caps_and_disruption_costs():
    # BusinessParams has no fields for these, so they live in a section the business loader does not read.
    opt = BUSINESS_DOC["optimizer_parameters"]
    assert opt["purchase_cut_cap_per_week"] == 10_000.0  # v-bar
    assert opt["payroll_cut_cap"] == 0.10  # z-bar
    assert opt["tie_break_epsilon"] == 1e-4  # epsilon
    assert opt["disruption_costs"] == {
        "revolver_draw_per_dollar": 0.01,  # c_y
        "purchase_cut_per_dollar": 0.05,  # c_v
        "defer_capex_per_decision": 1_000.0,  # c_c
        "backup_supplier_per_decision": 2_500.0,  # c_b
        "delay_expansion_per_decision": 5_000.0,  # c_e
        "payroll_cut_per_dollar": 5.00,  # c_z
    }


def test_baseline_matches_section_10_hand_check():
    # §10: the business loses 1,423.08/wk before any shock, so cash goes 100,000 -> 63,000 by week 26.
    assert BASELINE.min_cash == pytest.approx(63_000.0, abs=1e-6)
    assert BASELINE.min_cash_week == 26
    assert BASELINE.min_cash > BUSINESS.min_cash  # stays above C_min with no shock


# --------------------------------------------------------------------------- scenario file


def test_scenario_file_is_synthetic_and_well_formed():
    assert SCENARIOS_DOC["provenance"] == "SYNTHETIC"
    raw = SCENARIOS_DOC["scenarios"]
    assert 4 <= len(raw) <= 6
    assert set(SCENARIOS) == set(EXPECTED_DIRECTION)
    for s in raw:
        assert s["provenance"] in ("SYNTHETIC", "ILLUSTRATIVE")
        assert s["rationale"].strip() and "\n" not in s["rationale"], s["id"]  # one line


@pytest.mark.parametrize("scenario_id", list(EXPECTED_DIRECTION))
def test_every_scenario_loads_and_simulates(scenario_id):
    res = _run(scenario_id)
    assert res.scenario_name == SCENARIOS[scenario_id].name
    assert len(res.cash) == BUSINESS.horizon_weeks
    assert EXPECTED_DIRECTION[scenario_id] == "lower"
    assert res.min_cash < BASELINE.min_cash


@pytest.mark.parametrize("scenario_id", list(HAND_MIN_CASH))
def test_min_cash_matches_hand_arithmetic(scenario_id):
    res = _run(scenario_id)
    assert res.min_cash == pytest.approx(HAND_MIN_CASH[scenario_id], abs=1e-6)
    assert res.min_cash_week == 26


def test_rate_shock_adds_230_77_interest_every_week_and_nothing_else():
    res = _run("rate-plus-200bp")
    for shocked, base in zip(res.interest, BASELINE.interest, strict=True):
        assert shocked - base == pytest.approx(WEEKLY_EXTRA_INTEREST, abs=1e-9)
    assert WEEKLY_EXTRA_INTEREST == pytest.approx(230.769231, abs=1e-6)
    assert res.sales == BASELINE.sales


def test_demand_and_outage_cut_sales_through_the_expected_channel():
    demand = _run("demand-drop-20pct-6wk")
    assert sum(BASELINE.sales) - sum(demand.sales) == pytest.approx(LOST_SALES_DEMAND, abs=1e-6)
    assert demand.interest == BASELINE.interest
    outage = _run("supplier-outage-3wk")
    assert sum(outage.lost_sales) == pytest.approx(LOST_SALES_OUTAGE, abs=1e-6)
    assert outage.interest == BASELINE.interest


# --------------------------------------------------------------------------- combined scenario


def test_combined_scenario_is_exactly_its_components():
    combined = SCENARIOS[COMBINED].shock
    assert combined.rate == SCENARIOS["rate-plus-200bp"].shock.rate
    assert combined.demand == SCENARIOS["demand-drop-20pct-6wk"].shock.demand
    assert combined.supplier == SCENARIOS["supplier-outage-3wk"].shock.supplier


def test_combined_scenario_is_worse_than_each_component_alone():
    combined = _run(COMBINED).min_cash
    for component in COMPONENTS:
        assert combined < _run(component).min_cash, component


def test_combined_scenario_breaches_the_liquidity_floor_but_components_do_not():
    # The demo point: each shock alone is survivable without action; together they push cash below C_min.
    assert _run(COMBINED).min_cash < BUSINESS.min_cash
    for component in COMPONENTS:
        assert _run(component).min_cash > BUSINESS.min_cash, component
