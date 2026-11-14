"""ACT / WAIT / HEDGE decision frames in data/decision_frames.json (issue #45; MATH_MODEL §8; SPEC §2 Screen B, §6).

The business is SYNTHETIC (data/demo_business.json, MATH_MODEL §10). The shocks and policies are ILLUSTRATIVE.
core.decision.evaluate_policies and core.financials.simulate are the oracle for every payoff; the hand-checked
numbers below come from the MATH_MODEL §10 "baseline economics" arithmetic and are written out so a finance
reviewer can check them without code.

Hand arithmetic shared by all frames. With no shock and no action the business loses 1,423.08 a week, so cash falls
monotonically from 100,000 to 63,000 at week 26 (MATH_MODEL §10). No shock or action here adds cash after week 10, so
the lowest balance is at week 26 in every cell and V(a, y) = C_26 = 63,000 + (cash effect of a) - (cash cost of y):
  * a purchase cut v_t is paid for L_p = 2 weeks later, so cuts in weeks 1-8 raise C_26 by exactly sum_t v_t;
  * +25bp on the 600,000 floating term loan costs 600,000 x 0.0025 / 52 = 28.846 a week;
  * a lost sales dollar costs the 35% gross margin once receipts and payables have settled.

Stock-out cost (issue #103, MATH_MODEL §3, §10): the service level is I^svc_t = sigma I_0 m_t = 65,000 x m_t
(sigma = 1: the opening stock, 2 weeks of cost of goods, scaled by the demand multiplier), so WAIT never runs short,
and each $ of stock below it loses 0.20 of sales a week. Effect of lost sales l_t on C_26 (receipts a l_t in week t
and (1-a) l_t in t+1; the purchase (1-g) l_t not made is a payment saved in t+2):
  * weeks 1-24: 0.35 per $ (settled: the gross margin);
  * week 25: 1.00 per $ (the saved payment would fall in week 27);
  * week 26: 0.80 per $ (only the same-week 80% of receipts falls inside the horizon).
So a shortfall of u held from week w to week 26 costs 0.20 u x (0.35 (25 - w) + 1.0 + 0.8) of C_26.
"""

from __future__ import annotations

import dataclasses
import json
import re
from pathlib import Path

import pytest

from config import get_settings
from core.decision import NO_SAFE_POLICY, Policy, evaluate_policies, regret
from core.financials import ActionPlan, ScenarioShock, simulate
from routes.simulate import load_business

TOL = 1e-6
DATA = Path(__file__).resolve().parent.parent / "data"
SETTINGS = dataclasses.replace(get_settings(), data_dir=DATA)

FRAMES_DOC = json.loads((DATA / "decision_frames.json").read_text(encoding="utf-8"))
BUSINESS_DOC = json.loads((DATA / "demo_business.json").read_text(encoding="utf-8"))
BUSINESS = load_business(SETTINGS)  # the same loader POST /api/simulate uses
FRAMES = {f["id"]: f for f in FRAMES_DOC["frames"]}
POLICY_NAMES = ("ACT", "WAIT", "HEDGE")
PROBABILITIES = (0.0, 0.5, 1.0)

# ---------------------------------------------------------------- hand-checked payoffs V(a, y) = C_26

BASE_C26 = 63_000.0  # planning path: 100,000 - 26 x 1,423.077 (MATH_MODEL §10)
RATE_25BP_WEEKLY = 600_000 * 0.0025 / 52  # 28.846...
THETA = 0.20  # stock-out lost sales per $ of shortfall per week (MATH_MODEL §10, issue #103)


def stockout_cost(shortfall_by_week: dict[int, float]) -> float:
    """C_26 cost of stock-out lost sales 0.20 u_t, with the week weights in the module docstring."""
    weight = {**{t: 0.35 for t in range(1, 25)}, 25: 1.0, 26: 0.8}
    return sum(THETA * u * weight[t] for t, u in shortfall_by_week.items())


# FOMC: YES = Fed holds -> +25bp from week 2, so 25 weeks (2..26) of extra interest = 721.154, and (issue #103 proposal)
# demand 1% lower from week 2: 500 of sales lost a week in weeks 2-26. By week 26 receipts lose 500 x 25 - 0.2 x 500
# = 12,400 and payables fall 0.65 x 500 x 23 (weeks 2-24) = 7,475: 4,925. Total 5,646.154.
FOMC_RATE = 25 * RATE_25BP_WEEKLY
FOMC_DEMAND = 500 * 25 - 0.2 * 500 - 0.65 * 500 * 23
FOMC_HIT = FOMC_RATE + FOMC_DEMAND
# A hold lowers the service level to 65,000 x 0.99 = 64,350 from week 2, so ACT's 650 cut (HEDGE: 325) in week 2 is
# surplus stock if YES (no shortfall) and a shortfall in weeks 2-26 if NO:
#   ACT  NO: 0.20 x 650 x (0.35 x 23 + 1.0 + 0.8) = 130 x 9.85 = 1,280.50;  HEDGE NO: 65 x 9.85 = 640.25.
FOMC_SO_ACT = stockout_cost({t: 650.0 for t in range(2, 27)})  # 1,280.50
FOMC_SO_HEDGE = stockout_cost({t: 325.0 for t in range(2, 27)})  # 640.25
# Break-even, ACT vs WAIT (MATH_MODEL §8), from the payoffs below:
#   ACT - WAIT = +650 if YES, 650 - 1,280.50 = -630.50 if NO
#   p* = 630.50 / (630.50 + 650) = 630.50 / 1,280.50 = 1,261 / 2,561 = 0.492386...
# HEDGE is exactly halfway between ACT and WAIT in both states, so all three lines cross at the same p*.
FOMC_P_STAR = 630.50 / 1_280.50
# CPI: YES = hot print -> +25bp from week 4 (23 weeks = 663.462) and -3% demand on 50,000 in weeks 3-14
# (12 x 1,500 = 18,000) plus the 4-week recovery m_t = 1 - 0.03 (1 - k/4): 1,125 + 750 + 375 + 0 = 2,250.
# Lost sales 20,250 x 0.35 = 7,087.50. Total 7,750.962.
CPI_LOST_SALES = 12 * 1_500 + 1_125 + 750 + 375
CPI_HIT = 23 * RATE_25BP_WEEKLY + 0.35 * CPI_LOST_SALES
# CPI stock-out (issue #103). A hot print lowers the service level by 3% x 65,000 = 1,950 in weeks 3-14, then by
# 1,462.50, 975 and 487.50 in weeks 15-17, and by 0 from week 18. ACT cuts 975 in week 3 (inventory 64,025), HEDGE
# 487.50 (inventory 64,512.50).
#   ACT  YES: short 487.50 in week 17 and 975 in weeks 18-26 -> 0.35 x (97.50 + 7 x 195) + 195 x 1.8 = 862.875
#   ACT  NO : short 975 in weeks 3-26 -> 195 x (0.35 x 22 + 1.8) = 1,852.50
#   HEDGE YES: short 487.50 in weeks 18-26 -> 0.35 x 7 x 97.50 + 97.50 x 1.8 = 414.375
#   HEDGE NO : short 487.50 in weeks 3-26 -> 97.50 x 9.5 = 926.25
CPI_SO = {
    ("ACT", 1): stockout_cost({17: 487.5, **{t: 975.0 for t in range(18, 27)}}),
    ("ACT", 0): stockout_cost({t: 975.0 for t in range(3, 27)}),
    ("HEDGE", 1): stockout_cost({t: 487.5 for t in range(18, 27)}),
    ("HEDGE", 0): stockout_cost({t: 487.5 for t in range(3, 27)}),
}
# Net effect against WAIT: HEDGE +73.125 if YES, -438.75 if NO; ACT +112.125 if YES, -877.50 if NO. Break-evens:
#   WAIT -> HEDGE: 438.75 / (438.75 + 73.125) = 6/7 = 0.857143
#   HEDGE -> ACT : ACT - HEDGE = +39 if YES, -438.75 if NO -> 438.75 / (438.75 + 39) = 45/49 = 0.918367
CPI_P_STAR_WAIT_HEDGE = 6 / 7
CPI_P_STAR_HEDGE_ACT = 45 / 49
# Supply disruption: YES = 40% of 50,000 lost for weeks 5-7 = 60,000 of sales x 0.35 = 21,000 (as scenarios.json).
OUTAGE_HIT = 0.35 * 3 * 0.40 * 50_000
BACKUP_FEE = 2_000.0  # F_b, week 1, both states
BACKUP_PREMIUM = 0.12 * 0.65 * 0.40 * 50_000 * 3  # pi (1-g) S_core lambda x 3 weeks = 1,560 x 3 = 4,680
REVOLVER_CARRY = 21_000 * (0.08 + 0.02) / 52 * 8  # B_{t-1} = 21,000 for t = 5..12 -> 323.077

HAND_V = {  # (frame, policy) -> (V(a, 1), V(a, 0))
    ("fomc-rate-decision", "ACT"): (BASE_C26 + 650 - FOMC_HIT, BASE_C26 + 650 - FOMC_SO_ACT),  # 58,003.85 / 62,369.50
    ("fomc-rate-decision", "WAIT"): (BASE_C26 - FOMC_HIT, BASE_C26),  # 57,353.85 / 63,000
    ("fomc-rate-decision", "HEDGE"): (BASE_C26 + 325 - FOMC_HIT,
                                      BASE_C26 + 325 - FOMC_SO_HEDGE),  # 57,678.85 / 62,684.75
    ("cpi-surprise", "ACT"): (BASE_C26 + 975 - CPI_HIT - CPI_SO[("ACT", 1)],
                              BASE_C26 + 975 - CPI_SO[("ACT", 0)]),  # 55,361.16 / 62,122.50
    ("cpi-surprise", "WAIT"): (BASE_C26 - CPI_HIT, BASE_C26),  # 55,249.04 / 63,000
    ("cpi-surprise", "HEDGE"): (BASE_C26 + 487.5 - CPI_HIT - CPI_SO[("HEDGE", 1)],
                                BASE_C26 + 487.5 - CPI_SO[("HEDGE", 0)]),  # 55,322.16 / 62,561.25
    ("supply-disruption", "ACT"): (BASE_C26 - BACKUP_FEE - BACKUP_PREMIUM, BASE_C26 - BACKUP_FEE),  # 56,320 / 61,000
    ("supply-disruption", "WAIT"): (BASE_C26 - OUTAGE_HIT, BASE_C26),  # 42,000 / 63,000
    ("supply-disruption", "HEDGE"): (BASE_C26 - OUTAGE_HIT - REVOLVER_CARRY, BASE_C26 - REVOLVER_CARRY),
    # HEDGE: 41,676.92 / 62,676.92
}

# Break-even p* for the supply-disruption frame, ACT (backup supplier) vs WAIT, from the engine values above:
#   E[V | ACT]  = p x 56,320 + (1 - p) x 61,000 = 61,000 - 4,680 p
#   E[V | WAIT] = p x 42,000 + (1 - p) x 63,000 = 63,000 - 21,000 p
#   equal when 16,320 p = 2,000  ->  p* = 2,000 / 16,320 = 25 / 204 = 0.122549...
# Read as insurance: pay the 2,000 fee for sure to save 21,000 - 4,680 = 16,320 if the disruption happens, so the
# fee is worth paying once P(YES) x 16,320 > (1 - P(YES)) x 2,000.
SUPPLY_P_STAR = 2_000 / 16_320


def shocks(frame: dict) -> tuple[ScenarioShock, ScenarioShock]:
    return ScenarioShock.model_validate(frame["shock_if_yes"]), ScenarioShock.model_validate(frame["shock_if_no"])


def policies(frame: dict) -> list[Policy]:
    return [Policy(name=p["name"], description=p["summary"], plan=ActionPlan.model_validate(p["plan"]))
            for p in frame["policies"]]


def evaluate(frame: dict, p: float):
    yes, no = shocks(frame)
    return evaluate_policies(BUSINESS, yes, no, policies(frame), p, protect_payroll=frame["protect_payroll"])


def by_name(result) -> dict:
    return {ev.policy.name: ev for ev in result.policies}


# ---------------------------------------------------------------- file shape and labels


def test_file_is_labelled_synthetic_business_and_illustrative_policies():
    assert FRAMES_DOC["provenance"] == "ILLUSTRATIVE"
    assert FRAMES_DOC["business_provenance"] == "SYNTHETIC"
    assert FRAMES_DOC["business_file"] == "demo_business.json"
    assert BUSINESS_DOC["provenance"] == "SYNTHETIC" and BUSINESS.provenance == "SYNTHETIC"
    assert "not a real company" in FRAMES_DOC["description"]
    for frame in FRAMES_DOC["frames"]:
        assert frame["provenance"] == "ILLUSTRATIVE"
        assert frame["assumptions"] and any(a.startswith("ILLUSTRATIVE:") for a in frame["assumptions"])
        for pol in frame["policies"]:
            assert pol["provenance"] == "ILLUSTRATIVE"


def test_required_question_types_are_present():
    assert {f["question_type"] for f in FRAMES_DOC["frames"]} >= {"fomc_rate_decision", "cpi_surprise"}
    assert len(FRAMES) == len(FRAMES_DOC["frames"])  # ids are unique
    assert len({f["question_type"] for f in FRAMES_DOC["frames"]}) == len(FRAMES)  # one frame per question type


def test_fomc_frame_yes_means_the_fed_holds():
    """The replay cases from issue #20 ask 'Will the FOMC leave the federal funds target range unchanged?'."""
    fomc = FRAMES["fomc-rate-decision"]
    assert "leave the federal funds target range unchanged" in fomc["question_template"]
    assert "holds" in fomc["yes_means"]
    yes, no = shocks(fomc)
    assert yes.rate is not None and yes.rate.delta_rate == pytest.approx(0.0025)  # hold = 25bp above the plan
    assert (no.demand, no.rate, no.supplier) == (None, None, None)  # the planned cut = the planning path


@pytest.mark.parametrize("frame_id", list(FRAMES))
def test_every_frame_loads(frame_id):
    frame = FRAMES[frame_id]
    for key in ("question_template", "yes_means", "no_means"):
        assert frame[key].strip()
    assert frame["shock_rationale"]["if_yes"].strip() and frame["shock_rationale"]["if_no"].strip()
    shocks(frame)  # both validate as ScenarioShock
    assert tuple(p["name"] for p in frame["policies"]) == POLICY_NAMES
    for pol in frame["policies"]:
        ActionPlan.model_validate(pol["plan"])
        assert pol["summary"].strip() and pol["rationale"].strip()
        assert pol["fees"], f"{frame_id}/{pol['name']}: every policy states its fees, even when the only cost is risk"
        for fee in pol["fees"]:
            assert set(fee) == {"item", "amount", "when", "in_payoff"}
            assert isinstance(fee["in_payoff"], bool)
    assert frame["protect_payroll"] is True


@pytest.mark.parametrize("frame_id", list(FRAMES))
def test_policies_use_only_actions_with_an_effect_and_respect_caps(frame_id):
    """Proposal: no payroll cuts; no capex/expansion levers (K_t = E_t = 0 in the demo business, so they do nothing);
    purchase cuts within v-bar per week and within I_0 - I_min = 25,000 in total (MATH_MODEL §10)."""
    assert BUSINESS.capex == 0.0 and BUSINESS.expansion_outflow == 0.0
    v_bar = BUSINESS_DOC["optimizer_parameters"]["purchase_cut_cap_per_week"]
    headroom = BUSINESS.inventory_0 - BUSINESS.min_inventory  # 25,000
    T = BUSINESS.horizon_weeks
    for pol in policies(FRAMES[frame_id]):
        plan = pol.plan
        assert not plan.defer_capex and not plan.delay_expansion
        z = plan.payroll_cut if isinstance(plan.payroll_cut, list) else [plan.payroll_cut] * T
        assert all(share == 0.0 for share in z)
        v = plan.purchase_cut if isinstance(plan.purchase_cut, list) else [plan.purchase_cut] * T
        assert max(v) <= v_bar and sum(v) <= headroom


# ---------------------------------------------------------------- every policy simulates under both shocks


@pytest.mark.parametrize("frame_id", list(FRAMES))
def test_every_policy_simulates_under_both_shocks(frame_id):
    frame = FRAMES[frame_id]
    for shock in shocks(frame):
        for pol in policies(frame):
            res = simulate(BUSINESS, shock, pol.plan)
            assert len(res.cash) == BUSINESS.horizon_weeks
            assert min(res.purchases) > 0.0  # cuts stay far below normal purchases of 32,500 a week
            assert min(res.inventory) >= BUSINESS.min_inventory
            assert max(res.revolver_balance) <= BUSINESS.revolver_limit
            assert res.revolver_balance[-1] <= BUSINESS.revolver_balance_0 + TOL
            assert res.runway_week is None


@pytest.mark.parametrize("frame_id", list(FRAMES))
@pytest.mark.parametrize("p", PROBABILITIES)
def test_evaluate_policies_runs_at_0_half_and_1(frame_id, p):
    result = evaluate(FRAMES[frame_id], p)
    assert result.p_yes == p and result.provenance == "SIMULATED"
    assert result.recommendation != NO_SAFE_POLICY
    assert result.recommended.feasible_in_both  # never a policy that breaks a §4 constraint in either state
    for ev in result.policies:
        assert ev.expected_value == pytest.approx(p * ev.value_if_yes + (1 - p) * ev.value_if_no, abs=TOL)
        assert ev.expected_value <= result.recommended.expected_value + TOL or not ev.feasible_in_both
    for y in (0, 1):
        assert regret(result, y).recommended_regret >= 0.0


@pytest.mark.parametrize(("frame_id", "name"), list(HAND_V))
def test_payoffs_match_hand_arithmetic(frame_id, name):
    ev = by_name(evaluate(FRAMES[frame_id], 0.5))[name]
    v_yes, v_no = HAND_V[(frame_id, name)]
    assert ev.value_if_yes == pytest.approx(v_yes, abs=1e-3)
    assert ev.value_if_no == pytest.approx(v_no, abs=1e-3)
    assert ev.if_yes.value_week == ev.if_no.value_week == BUSINESS.horizon_weeks  # lowest balance at week 26
    assert ev.feasible_in_both  # every policy here clears C_min = 25,000 and the other §4 constraints


# ---------------------------------------------------------------- what the frames say about the decision


def p_star(a, b) -> float:
    """MATH_MODEL §8: E[V | a] = E[V | b] at p* = (V(b,0) - V(a,0)) / ((V(a,1) - V(a,0)) - (V(b,1) - V(b,0)))."""
    return (b.value_if_no - a.value_if_no) / ((a.value_if_yes - a.value_if_no) - (b.value_if_yes - b.value_if_no))


def test_fomc_break_even_probability():
    """Issue #103: ACT (cut 650 of stock in week 2) vs WAIT cross at p* = 630.50 / 1,280.50 = 0.4924 (hand arithmetic
    at the top). ACT releases 650 of surplus stock if the Fed holds and demand softens, and loses 1,280.50 of margin to
    stock-outs if it cuts as planned. Below p* WAIT is recommended, above it ACT."""
    ev = by_name(evaluate(FRAMES["fomc-rate-decision"], 0.5))
    act, wait, hedge = ev["ACT"], ev["WAIT"], ev["HEDGE"]
    assert act.value_if_yes - wait.value_if_yes == pytest.approx(650.0, abs=1e-6)  # no stock-out if the Fed holds
    assert act.value_if_no - wait.value_if_no == pytest.approx(650.0 - 1_280.50, abs=1e-6)
    star = p_star(act, wait)
    assert star == pytest.approx(FOMC_P_STAR, abs=0.01)  # the issue #103 acceptance test, to 0.01
    assert star == pytest.approx(0.49238579, abs=1e-6)
    assert 0.0 < star < 1.0
    assert p_star(act, hedge) == pytest.approx(star, abs=1e-9)  # HEDGE is halfway: all three lines meet at p*
    assert evaluate(FRAMES["fomc-rate-decision"], star - 1e-3).recommendation == "WAIT"
    assert evaluate(FRAMES["fomc-rate-decision"], star + 1e-3).recommendation == "ACT"
    assert [evaluate(FRAMES["fomc-rate-decision"], p).recommendation for p in PROBABILITIES] == ["WAIT", "ACT", "ACT"]


def test_cpi_break_even_probabilities():
    """Issue #103: WAIT up to 6/7 = 0.857, HEDGE between 6/7 and 45/49 = 0.918, ACT above (hand arithmetic at the top).
    A hot print lowers demand for a quarter, but a cut is permanent, so the stock is short again once demand recovers:
    a cut only pays if a hot print is very likely."""
    ev = by_name(evaluate(FRAMES["cpi-surprise"], 0.5))
    act, wait, hedge = ev["ACT"], ev["WAIT"], ev["HEDGE"]
    assert p_star(hedge, wait) == pytest.approx(CPI_P_STAR_WAIT_HEDGE, abs=1e-6)
    assert p_star(act, hedge) == pytest.approx(CPI_P_STAR_HEDGE_ACT, abs=1e-6)
    assert 0.0 < CPI_P_STAR_WAIT_HEDGE < CPI_P_STAR_HEDGE_ACT < 1.0
    recs = {p: evaluate(FRAMES["cpi-surprise"], p).recommendation for p in P_GRID}
    assert {p for p, r in recs.items() if r == "WAIT"} == {p for p in P_GRID if p < CPI_P_STAR_WAIT_HEDGE}
    assert recs[0.9] == "HEDGE" and recs[0.95] == recs[1.0] == "ACT"


def test_fomc_purchase_cuts_cost_nothing_if_the_fed_holds_and_rate_alone_gives_no_break_even():
    """MATH_MODEL §8 (issue #103): the break-even comes from the demand channel. With the demand effect removed from
    the YES state (rate only), every policy differs from WAIT by the same amount in both states, so p* cannot exist even
    with the stock-out cost: the rate changes only term-loan interest, which no policy here touches."""
    frame = FRAMES["fomc-rate-decision"]
    yes = ScenarioShock.model_validate(frame["shock_if_yes"])
    for pol in policies(frame):
        assert max(simulate(BUSINESS, yes, pol.plan).inventory_shortfall) == pytest.approx(0.0, abs=1e-9)
    rate_only = yes.model_copy(update={"demand": None})
    no = ScenarioShock.model_validate(frame["shock_if_no"])
    res = evaluate_policies(BUSINESS, rate_only, no, policies(frame), 0.5, protect_payroll=True)
    ev = by_name(res)
    for name in ("ACT", "HEDGE"):
        gap_yes = ev[name].value_if_yes - ev["WAIT"].value_if_yes
        gap_no = ev[name].value_if_no - ev["WAIT"].value_if_no
        assert gap_yes == pytest.approx(gap_no, abs=1e-6)


def test_supply_disruption_break_even_probability():
    """ACT (backup supplier) vs WAIT cross at p* = 2,000 / 16,320 = 0.122549 (hand arithmetic at the top)."""
    ev = by_name(evaluate(FRAMES["supply-disruption"], 0.5))
    act, wait = ev["ACT"], ev["WAIT"]
    # Engine values: V(ACT,1) = 56,320, V(ACT,0) = 61,000, V(WAIT,1) = 42,000, V(WAIT,0) = 63,000.
    p_star = (wait.value_if_no - act.value_if_no) / (
        (wait.value_if_no - act.value_if_no) + (act.value_if_yes - wait.value_if_yes)
    )
    assert p_star == pytest.approx(SUPPLY_P_STAR, abs=1e-6)
    assert p_star == pytest.approx(0.12254902, abs=1e-6)
    assert 0.0 < p_star < 1.0
    at_star = by_name(evaluate(FRAMES["supply-disruption"], p_star))
    assert at_star["ACT"].expected_value == pytest.approx(at_star["WAIT"].expected_value, abs=1e-6)
    assert evaluate(FRAMES["supply-disruption"], p_star - 1e-3).recommendation == "WAIT"
    assert evaluate(FRAMES["supply-disruption"], p_star + 1e-3).recommendation == "ACT"
    assert [evaluate(FRAMES["supply-disruption"], p).recommendation for p in PROBABILITIES] == ["WAIT", "ACT", "ACT"]


def test_supply_disruption_liquidity_hedge_only_costs_carry():
    """HEDGE (draw 21,000 in week 4, repay in week 12) pays 323.08 of revolver interest in both states and cannot raise
    the week-26 low point, so it is below WAIT in both states and never recommended."""
    for p in [k / 20 for k in range(21)]:
        ev = by_name(evaluate(FRAMES["supply-disruption"], p))
        assert ev["WAIT"].value_if_yes - ev["HEDGE"].value_if_yes == pytest.approx(REVOLVER_CARRY, abs=1e-6)
        assert ev["WAIT"].value_if_no - ev["HEDGE"].value_if_no == pytest.approx(REVOLVER_CARRY, abs=1e-6)
        assert evaluate(FRAMES["supply-disruption"], p).recommendation != "HEDGE"


# ---------------------------------------------------------------- which NO outcome a frame models (review of PR #71)


@pytest.mark.parametrize("frame_id", list(FRAMES))
def test_every_frame_says_which_no_outcome_it_models(frame_id):
    frame = FRAMES[frame_id]
    assert frame["no_state_models"].strip()
    if "not_modelled_note" in frame:
        assert frame["not_modelled_note"].startswith("NOT AVAILABLE: ")


def test_fomc_no_is_a_cut_or_a_hike_but_only_the_cut_is_modelled():
    """The real FOMC cases (#20) resolve NO if EITHER bound changes, so a NO can be a hike. The frame models only the
    planned 25bp cut; a hike must show NOT AVAILABLE at reveal, never a regret for a cut that did not happen."""
    fomc = FRAMES["fomc-rate-decision"]
    assert "cut or a hike" in fomc["no_means"]
    assert fomc["no_state_models"] == "cut"
    assert fomc["not_modelled_note"] == "NOT AVAILABLE: this frame does not model a hike"


# ---------------------------------------------------------------- forecast_sensitive flag (review of PR #71)

P_GRID = [k / 20 for k in range(21)]


@pytest.mark.parametrize("frame_id", list(FRAMES))
def test_forecast_sensitive_flag_matches_the_engine(frame_id):
    """forecast_sensitive is true exactly when the recommended policy changes somewhere on p = 0, 0.05, ..., 1,
    i.e. when the frame has a break-even p* (test_supply_disruption_break_even_probability,
    test_fomc_break_even_probability, test_cpi_break_even_probabilities). A frame whose answer ignores the forecast
    must say so."""
    frame = FRAMES[frame_id]
    recommendations = {evaluate(frame, p).recommendation for p in P_GRID}
    assert frame["forecast_sensitive"] is (len(recommendations) > 1)
    if not frame["forecast_sensitive"]:
        assert "does not depend on the forecast" in frame["caveat"]


# ---------------------------------------------------------------- typed fee amounts match the engine (review of PR #71)

NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


def final_number(text: str) -> float:
    return float(NUMBER.findall(text)[-1].replace(",", ""))


NO_STOCKOUT = BUSINESS.model_copy(update={"stockout_lost_sales_rate": 0.0})  # theta = 0: stock-out cost switched off


def value(frame_id: str, policy: str, shock: dict, params=BUSINESS) -> float:
    """V(a, y) = min_t C_t from the engine, for one policy under one shock (MATH_MODEL §8)."""
    plan = next(p["plan"] for p in FRAMES[frame_id]["policies"] if p["name"] == policy)
    res = simulate(params, ScenarioShock.model_validate(shock), ActionPlan.model_validate(plan))
    return min(res.cash)


def yes_channels(frame_id: str, channels: tuple[str, ...]) -> dict:
    """shock_if_yes with only the named channels (rate / demand / supplier) switched on."""
    return {k: v for k, v in FRAMES[frame_id]["shock_if_yes"].items() if k == "name" or k in channels}


def engine_amount(frame_id: str, policy: str, check: tuple) -> float:
    frame = FRAMES[frame_id]
    no = frame["shock_if_no"]
    if check[0] == "yes":
        # cost that only hits in YES: V(a, NO) - V(a, YES restricted to the channel), measured with the stock-out cost
        # off so the channel's own cost is separated from the stock-out line (with theta = 0 this is the pre-#103 check)
        return (value(frame_id, policy, no, NO_STOCKOUT)
                - value(frame_id, policy, yes_channels(frame_id, check[1]), NO_STOCKOUT))
    if check[0] == "stockout":  # stock-out lost margin in state y: V(a, y) with theta = 0 minus V(a, y)
        shock = frame["shock_if_yes"] if check[1] == 1 else no
        return value(frame_id, policy, shock, NO_STOCKOUT) - value(frame_id, policy, shock)
    # cost paid in both states: V(WAIT, NO) - V(a, NO)
    return value(frame_id, "WAIT", no) - value(frame_id, policy, no)


FEE_CHECKS = {
    **{("fomc-rate-decision", a, "Extra term-loan interest if the Fed holds"): ("yes", ("rate",))
       for a in POLICY_NAMES},
    **{("fomc-rate-decision", a, "Lost gross margin on lower demand if the Fed holds"): ("yes", ("demand",))
       for a in POLICY_NAMES},
    ("fomc-rate-decision", "ACT", "Stock-out lost margin if the Fed cuts (inventory 650 below the service level)"):
        ("stockout", 0),
    ("fomc-rate-decision", "HEDGE", "Stock-out lost margin if the Fed cuts (inventory 325 below the service level)"):
        ("stockout", 0),
    **{("cpi-surprise", a, "Stock-out lost margin if the print is hot"): ("stockout", 1) for a in ("ACT", "HEDGE")},
    **{("cpi-surprise", a, "Stock-out lost margin if the print is in line"): ("stockout", 0) for a in ("ACT", "HEDGE")},
    **{("cpi-surprise", a, "Extra term-loan interest if the print is hot"): ("yes", ("rate",)) for a in POLICY_NAMES},
    **{("cpi-surprise", a, "Lost gross margin on lower demand if the print is hot"): ("yes", ("demand",))
       for a in POLICY_NAMES},
    ("supply-disruption", "ACT", "Backup-supplier switching fee F_b (MATH_MODEL §10)"): ("both",),
    ("supply-disruption", "ACT", "Backup premium pi on outage-share purchases (MATH_MODEL §10)"):
        ("yes", ("supplier",)),
    ("supply-disruption", "WAIT", "Lost gross margin on outage-share sales"): ("yes", ("supplier",)),
    ("supply-disruption", "HEDGE", "Revolver interest J^R_t at r + s_R = 10.0%"): ("both",),
    ("supply-disruption", "HEDGE", "Lost gross margin on outage-share sales"): ("yes", ("supplier",)),
}


def test_every_in_payoff_fee_has_an_engine_check():
    in_payoff = {(f["id"], p["name"], fee["item"])
                 for f in FRAMES_DOC["frames"] for p in f["policies"] for fee in p["fees"] if fee["in_payoff"]}
    assert in_payoff == set(FEE_CHECKS)


@pytest.mark.parametrize(("frame_id", "policy", "item"), list(FEE_CHECKS))
def test_typed_fee_amount_matches_engine_difference(frame_id, policy, item):
    """The last number typed in each in_payoff fee (e.g. '... = 721.15') equals the engine's cash difference to 0.01."""
    fee = next(fee for p in FRAMES[frame_id]["policies"] if p["name"] == policy for fee in p["fees"]
               if fee["item"] == item)
    expected = engine_amount(frame_id, policy, FEE_CHECKS[(frame_id, policy, item)])
    assert final_number(fee["amount"]) == pytest.approx(expected, abs=0.01)


@pytest.mark.parametrize("frame_id", list(FRAMES))
def test_typed_shock_total_matches_engine(frame_id):
    """shock_rationale.if_yes ends with the total cash hit ('... 721.15 lower cash by week 26'): it must equal
    V(WAIT, NO) - V(WAIT, YES) from the engine to 0.01."""
    text = FRAMES[frame_id]["shock_rationale"]["if_yes"]
    typed = re.search(r"([\d,]+(?:\.\d+)?) lower cash by week 26", text)
    assert typed, text
    frame = FRAMES[frame_id]
    expected = value(frame_id, "WAIT", frame["shock_if_no"]) - value(frame_id, "WAIT", frame["shock_if_yes"])
    assert float(typed.group(1).replace(",", "")) == pytest.approx(expected, abs=0.01)
