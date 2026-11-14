"""Second SYNTHETIC business: a 12-person full-service restaurant (issue #109, docs/MATH_MODEL.md §10b).

Same engine, different shape: payroll is 36.5% of sales, there is one week of perishable stock, receipts mostly
arrive the same week, suppliers are paid the next week and the margin is thin. Everything here is SYNTHETIC: a
fictional business and invented stress paths. The hand-checked numbers below were worked out from the §3 formulas
first (see §10b) and the engine must agree with them to 0.01.

Payroll protection is checked with core.decision (the §8 rule with protect_payroll=True). The optimizer's
NO FEASIBLE PLAN is not on main yet (PR #69); its test for this business is a follow-up.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from core.decision import NO_SAFE_POLICY, Policy, evaluate_policies
from core.financials import ActionPlan, BusinessParams, ScenarioShock, SimulationResult, simulate
from routes.scenarios import NamedScenario

API = Path(__file__).resolve().parent.parent
DATA = API / "data"
MATH_MODEL = API.parent.parent / "docs" / "MATH_MODEL.md"

BUSINESS_DOC = json.loads((DATA / "restaurant_business.json").read_text(encoding="utf-8"))
SCENARIOS_DOC = json.loads((DATA / "scenarios_restaurant.json").read_text(encoding="utf-8"))
# The same validation load_business() applies to demo_business.json: the `business` block must pass BusinessParams.
BUSINESS = BusinessParams.model_validate(BUSINESS_DOC["business"])
# The same per-scenario schema load_scenarios() applies, including that the listed shock carries the catalog name.
SCENARIOS = {
    s.id: s.model_copy(update={"shock": s.shock.model_copy(update={"name": s.name})})
    for s in (NamedScenario.model_validate(entry) for entry in SCENARIOS_DOC["scenarios"])
}
BASELINE = simulate(BUSINESS, ScenarioShock(), ActionPlan())

T = 26
C_MIN = 15_000.0
TOL = 0.01  # hand checks agree with the engine to a cent

ROAD, DISTRIBUTOR, SLOW = "road-closure-9wk", "distributor-loss-4wk", "slow-season-plus-300bp"

# --------------------------------------------------------------------------- hand checks (MATH_MODEL §10b)

G, A, COGS = 0.66, 0.90, 0.34  # gross margin g, same-week collection a, food cost 1 - g
WEEKLY_PROFIT = 0.66 * 20_000 - 7_300 - 5_400 - 156_000 * 0.10 / 52  # 13,200 - 13,000 = 200
WEEKLY_PROFIT_RATE_SHOCK = 0.66 * 20_000 - 7_300 - 5_400 - 156_000 * 0.13 / 52  # 13,200 - 13,090 = 110


def _lost(weeks: dict[int, float]) -> list[float]:
    """Lost sales ΔS_t below baseline, week t at index t-1."""
    return [weeks.get(t, 0.0) for t in range(1, T + 1)]


# ΔS_t by hand. Road closure: 30% of 20,000 = 6,000 in weeks 4-12; recovery m = 1 - 0.3 (1 - k/3) loses 4,000, 2,000, 0.
# Distributor loss: phi = 0.6 of 20,000 = 12,000 in weeks 6-9. Slow season: 6,000 in weeks 2-9, no recovery tail.
LOST_SALES = {
    ROAD: _lost({**{t: 6_000.0 for t in range(4, 13)}, 13: 4_000.0, 14: 2_000.0}),
    DISTRIBUTOR: _lost({t: 12_000.0 for t in range(6, 10)}),
    SLOW: _lost({t: 6_000.0 for t in range(2, 10)}),
}
BASE_WEEKLY = {ROAD: WEEKLY_PROFIT, DISTRIBUTOR: WEEKLY_PROFIT, SLOW: WEEKLY_PROFIT_RATE_SHOCK}


def hand_cash_path(scenario_id: str) -> list[float]:
    """C_t = C_{t-1} + base weekly profit - a ΔS_t - (1-a) ΔS_{t-1} + (1-g) ΔS_{t-1}  (§10b shortcut, from §3)."""
    lost, prev, cash, out = LOST_SALES[scenario_id], 0.0, 45_000.0, []
    for d in lost:
        cash += BASE_WEEKLY[scenario_id] - A * d - (1 - A) * prev + COGS * prev
        out.append(cash)
        prev = d
    return out


# The §10b scenario table, worked out by hand: (C_T, first week below C_min, lowest cash, its week, weeks below C_min).
HAND = {
    ROAD: (50_200 - G * 60_000, 11, 7_720.0, 14, list(range(11, 27))),  # 10,600
    DISTRIBUTOR: (50_200 - G * 48_000, 9, 12_240.0, 9, [9]),  # 18,520
    SLOW: (45_000 + 26 * 110 - G * 48_000, 9, 12_870.0, 9, list(range(9, 16))),  # 16,180
}


def _run(scenario_id: str, plan: ActionPlan | None = None) -> SimulationResult:
    return simulate(BUSINESS, SCENARIOS[scenario_id].shock, plan or ActionPlan())


def _first_below_floor(res: SimulationResult) -> int | None:
    return next((t for t, c in enumerate(res.cash, start=1) if c < C_MIN), None)


# --------------------------------------------------------------------------- fixture is SYNTHETIC


def test_fixture_and_scenarios_are_synthetic():
    assert BUSINESS_DOC["provenance"] == "SYNTHETIC"
    assert BUSINESS_DOC["business"]["provenance"] == "SYNTHETIC"
    assert BUSINESS.provenance == "SYNTHETIC"
    assert "Not signed off" in BUSINESS_DOC["status"]
    assert SCENARIOS_DOC["provenance"] == "SYNTHETIC"
    assert set(SCENARIOS) == {ROAD, DISTRIBUTOR, SLOW}
    assert all(s.provenance == "SYNTHETIC" for s in SCENARIOS.values())
    assert BASELINE.provenance == "SIMULATED"


def test_scenarios_use_only_existing_shock_channels_and_match_the_horizon():
    assert BUSINESS.horizon_weeks == T
    for s in SCENARIOS.values():
        assert s.shock.name == s.name  # a listed result is never labelled "baseline"
        if s.shock.supplier is not None and isinstance(s.shock.supplier.availability, list):
            assert len(s.shock.supplier.availability) == T
    assert SCENARIOS[DISTRIBUTOR].shock.supplier.dependent_share == BUSINESS_DOC["scenario_parameters"][
        "supplier_outage_dependent_share"
    ]


def test_grocer_fixture_is_untouched():
    grocer = json.loads((DATA / "demo_business.json").read_text(encoding="utf-8"))
    assert grocer["business"]["cash_0"] == 100_000.0 and len(grocer["business"]["stores"]) == 3


# --------------------------------------------------------------------------- doc table <-> fixture


def _section_10b_rows() -> dict[str, str]:
    text = MATH_MODEL.read_text(encoding="utf-8")
    start = text.index("## 10b.")
    nxt = text.find("\n## ", start + 1)
    section = text[start:] if nxt == -1 else text[start:nxt]
    assert "Proposal for finance-owner review (issue #109). Not signed off." in section
    rows = {}
    for line in section.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 3 and re.fullmatch(r"`(business|scenario_parameters|optimizer_parameters)\.[^`]+`", cells[1]):
            rows[cells[1].strip("`")] = cells[2]
    return rows


def _resolve(path: str):
    node = BUSINESS_DOC
    for part in path.split("."):
        m = re.fullmatch(r"(\w+)\[(\d+)\]", part)
        node = node[m.group(1)][int(m.group(2))] if m else node[part]
    return node


def test_section_10b_table_matches_fixture():
    rows = _section_10b_rows()
    assert len(rows) == 34
    for field, cell in rows.items():
        assert float(cell.replace(",", "")) == pytest.approx(float(_resolve(field)), abs=1e-12), field


def test_every_fixture_parameter_is_in_section_10b():
    rows = set(_section_10b_rows())
    b = BUSINESS_DOC["business"]
    documented = {f"business.{k}" for k, v in b.items() if isinstance(v, int | float) and not isinstance(v, bool)}
    documented |= {"business.stores[0].base_sales", "business.prior_purchases[0]"}
    documented |= {f"scenario_parameters.{k}" for k in BUSINESS_DOC["scenario_parameters"]}
    opt = BUSINESS_DOC["optimizer_parameters"]
    documented |= {f"optimizer_parameters.{k}" for k, v in opt.items() if isinstance(v, int | float)}
    documented |= {f"optimizer_parameters.disruption_costs.{k}" for k in opt["disruption_costs"]}
    assert len(b["stores"]) == 1 and len(b["prior_purchases"]) == 1
    assert documented == rows


# --------------------------------------------------------------------------- baseline economics


def test_baseline_hand_check():
    assert WEEKLY_PROFIT == pytest.approx(200.0)
    assert BASELINE.interest == pytest.approx([300.0] * T)
    assert BASELINE.cash == pytest.approx([45_000 + 200 * t for t in range(1, T + 1)], abs=TOL)
    assert BASELINE.ending_cash == pytest.approx(50_200.0, abs=TOL)
    assert (BASELINE.min_cash, BASELINE.min_cash_week) == (pytest.approx(45_200.0, abs=TOL), 1)
    assert _first_below_floor(BASELINE) is None
    assert BASELINE.runway_label == "> 26 weeks"
    assert BASELINE.payroll == pytest.approx([7_300.0] * T)


# --------------------------------------------------------------------------- the three scenarios


@pytest.mark.parametrize("scenario_id", [ROAD, DISTRIBUTOR, SLOW])
def test_scenario_matches_hand_check(scenario_id):
    res = _run(scenario_id)
    c_t, first, low, low_week, below = HAND[scenario_id]
    assert res.ending_cash == pytest.approx(c_t, abs=TOL)
    assert _first_below_floor(res) == first
    assert [t for t, c in enumerate(res.cash, start=1) if c < C_MIN] == below
    assert res.min_cash == pytest.approx(low, abs=TOL) and res.min_cash_week == low_week
    assert res.runway_week is None  # cash never goes negative
    # the whole 26-week path, from the hand recursion
    assert res.cash == pytest.approx(hand_cash_path(scenario_id), abs=TOL)
    assert [b - s for b, s in zip(BASELINE.sales, res.sales, strict=True)] == pytest.approx(LOST_SALES[scenario_id])


def test_slow_season_rate_shock_costs_90_a_week():
    res = _run(SLOW)
    assert [i - b for i, b in zip(res.interest, BASELINE.interest, strict=True)] == pytest.approx([90.0] * T)


def test_backup_supplier_hand_check_in_distributor_loss():
    res = _run(DISTRIBUTOR, ActionPlan(use_backup_supplier=True))
    assert res.lost_sales == pytest.approx([0.0] * T)
    assert res.backup_premium[5:9] == pytest.approx([612.0] * 4)  # 0.15 x 0.34 x 20,000 x 0.6, weeks 6-9
    assert res.ending_cash == pytest.approx(50_200 - 500 - 4 * 612, abs=TOL)  # 47,252
    assert (res.min_cash, res.min_cash_week) == (pytest.approx(44_052.0, abs=TOL), 10)


# --------------------------------------------------------------------------- payroll protection (§4.5 via §8)


def _weeks(values: dict[int, float]) -> list[float]:
    return [values.get(t, 0.0) for t in range(1, T + 1)]


CUT = _weeks({2: 1_400.0, 3: 1_400.0})  # the full I_0 - I_min = 2,800, within v-bar = 1,400 a week
DRAW, REPAY = _weeks({8: 5_000.0}), _weeks({26: 5_000.0})  # repaid by week 26, so B_T = B_0 (§4.7)
TRIM = [0.0] * 3 + [0.10] * 23  # z_t = z-bar = 0.10 in weeks 4-26
POLICIES = [
    Policy(name="WAIT", plan=ActionPlan()),
    Policy(name="CUT PURCHASES", plan=ActionPlan(purchase_cut=CUT)),
    Policy(name="REVOLVER BRIDGE", plan=ActionPlan(revolver_draw=DRAW, revolver_repay=REPAY)),
    Policy(name="BACKUP SUPPLIER", plan=ActionPlan(use_backup_supplier=True)),
    Policy(name="ALL NON-PAYROLL LEVERS", plan=ActionPlan(
        use_backup_supplier=True, purchase_cut=CUT, revolver_draw=DRAW, revolver_repay=REPAY)),
    Policy(name="TRIM PAYROLL 10%", plan=ActionPlan(payroll_cut=TRIM)),
]


def _decide(scenario_id: str, protect_payroll: bool):
    # YES state = the scenario happens, NO state = baseline; feasible-in-both is what the §8 rule recommends from.
    return evaluate_policies(
        BUSINESS, SCENARIOS[scenario_id].shock, ScenarioShock(), POLICIES, p_yes=0.5, protect_payroll=protect_payroll
    )


def _by_name(result, name):
    return next(ev for ev in result.policies if ev.policy.name == name)


@pytest.mark.parametrize("scenario_id", [ROAD, DISTRIBUTOR, SLOW])
def test_protect_payroll_holds_in_every_scenario(scenario_id):
    res = _decide(scenario_id, protect_payroll=True)
    assert "protect payroll: z_t = 0 for all t" in res.constraints_checked
    trim = _by_name(res, "TRIM PAYROLL 10%")
    assert not trim.feasible_in_both and not trim.if_yes.feasible and not trim.if_no.feasible
    assert "protect payroll: z_4 = 0.1 > 0 while protect-payroll mode is on (week 4)" in trim.if_yes.violations
    if res.recommended is not None:  # whatever is recommended never cuts payroll
        assert res.recommended.policy.plan.payroll_cut == 0.0
        assert res.recommended.if_yes.simulation.payroll == pytest.approx([7_300.0] * T)
    # WAIT breaches the floor in the hand-checked week in every scenario
    first = HAND[scenario_id][1]
    wait = _by_name(res, "WAIT")
    assert not wait.if_yes.feasible and wait.if_no.feasible
    assert wait.if_yes.violations[0].startswith(f"liquidity floor: C_{first} = ")


def test_road_closure_has_no_safe_policy_with_payroll_protected():
    res = _decide(ROAD, protect_payroll=True)
    assert res.recommendation == NO_SAFE_POLICY and res.recommended is None
    for name in ("WAIT", "CUT PURCHASES", "REVOLVER BRIDGE", "BACKUP SUPPLIER", "ALL NON-PAYROLL LEVERS"):
        ev = _by_name(res, name)
        assert not ev.if_yes.feasible, name
        assert any(v.startswith("liquidity floor:") for v in ev.if_yes.violations), name
    # Bound over the whole §4 action space with z_t = 0 (§10b): no outage, K = E = X = 0, revolver flows net to
    # B_T - B_0 <= 0, so only purchase cuts can raise C_T, by at most I_0 - I_min. Even that stays below C_min.
    headroom = BUSINESS.inventory_0 - BUSINESS.min_inventory
    assert headroom == pytest.approx(2_800.0)
    assert _run(ROAD).ending_cash + headroom == pytest.approx(13_400.0, abs=TOL)
    assert _run(ROAD).ending_cash + headroom < BUSINESS.min_cash


def test_road_closure_payroll_trim_is_the_only_listed_way_out_when_protection_is_off():
    res = _decide(ROAD, protect_payroll=False)
    assert res.recommendation == "TRIM PAYROLL 10%"
    trim = res.recommended.if_yes.simulation
    assert trim.ending_cash == pytest.approx(10_600 + 730 * 23, abs=TOL)  # 27,390
    assert (trim.min_cash, trim.min_cash_week) == (pytest.approx(8_360 + 730 * 10, abs=TOL), 13)  # 15,660
    feasible = [ev.policy.name for ev in res.policies if ev.feasible_in_both]
    assert feasible == ["TRIM PAYROLL 10%"]


def test_distributor_loss_is_safe_without_touching_payroll():
    res = _decide(DISTRIBUTOR, protect_payroll=True)
    assert res.recommendation != NO_SAFE_POLICY
    assert _by_name(res, "BACKUP SUPPLIER").feasible_in_both
    assert _by_name(res, "BACKUP SUPPLIER").value_if_yes == pytest.approx(44_052.0, abs=TOL)
    assert _by_name(res, "CUT PURCHASES").value_if_yes == pytest.approx(12_240 + 2_800, abs=TOL)  # 15,040
    assert _by_name(res, "REVOLVER BRIDGE").feasible_in_both


def test_slow_season_is_bridged_without_touching_payroll():
    res = _decide(SLOW, protect_payroll=True)
    assert res.recommendation != NO_SAFE_POLICY
    bridge = _by_name(res, "REVOLVER BRIDGE")
    assert bridge.feasible_in_both
    assert bridge.if_yes.simulation.ending_cash == pytest.approx(16_180 - 5_000 * 0.15 / 52 * 18, abs=TOL)  # 15,920.38
    assert _by_name(res, "CUT PURCHASES").value_if_yes == pytest.approx(12_870 + 2_800, abs=TOL)  # 15,670
    backup = _by_name(res, "BACKUP SUPPLIER")  # no outage here: the 500 fee only makes the dip worse
    assert not backup.if_yes.feasible and backup.value_if_yes == pytest.approx(12_870 - 500, abs=TOL)
