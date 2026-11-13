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
"""

from __future__ import annotations

import dataclasses
import json
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

# FOMC: YES = Fed holds -> +25bp from week 2, so 25 weeks (2..26) of extra interest = 721.154.
FOMC_HIT = 25 * RATE_25BP_WEEKLY
# CPI: YES = hot print -> +25bp from week 4 (23 weeks = 663.462) and -3% demand on 50,000 in weeks 3-14
# (12 x 1,500 = 18,000) plus the 4-week recovery m_t = 1 - 0.03 (1 - k/4): 1,125 + 750 + 375 + 0 = 2,250.
# Lost sales 20,250 x 0.35 = 7,087.50. Total 7,750.962.
CPI_LOST_SALES = 12 * 1_500 + 1_125 + 750 + 375
CPI_HIT = 23 * RATE_25BP_WEEKLY + 0.35 * CPI_LOST_SALES
# Supply disruption: YES = 40% of 50,000 lost for weeks 5-7 = 60,000 of sales x 0.35 = 21,000 (as scenarios.json).
OUTAGE_HIT = 0.35 * 3 * 0.40 * 50_000
BACKUP_FEE = 2_000.0  # F_b, week 1, both states
BACKUP_PREMIUM = 0.12 * 0.65 * 0.40 * 50_000 * 3  # pi (1-g) S_core lambda x 3 weeks = 1,560 x 3 = 4,680
REVOLVER_CARRY = 21_000 * (0.08 + 0.02) / 52 * 8  # B_{t-1} = 21,000 for t = 5..12 -> 323.077

HAND_V = {  # (frame, policy) -> (V(a, 1), V(a, 0))
    ("fomc-rate-decision", "ACT"): (BASE_C26 + 1_000 - FOMC_HIT, BASE_C26 + 1_000),  # 63,278.85 / 64,000
    ("fomc-rate-decision", "WAIT"): (BASE_C26 - FOMC_HIT, BASE_C26),  # 62,278.85 / 63,000
    ("fomc-rate-decision", "HEDGE"): (BASE_C26 + 500 - FOMC_HIT, BASE_C26 + 500),  # 62,778.85 / 63,500
    ("cpi-surprise", "ACT"): (BASE_C26 + 8_000 - CPI_HIT, BASE_C26 + 8_000),  # 63,249.04 / 71,000
    ("cpi-surprise", "WAIT"): (BASE_C26 - CPI_HIT, BASE_C26),  # 55,249.04 / 63,000
    ("cpi-surprise", "HEDGE"): (BASE_C26 + 4_000 - CPI_HIT, BASE_C26 + 4_000),  # 59,249.04 / 67,000
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


@pytest.mark.parametrize("frame_id", ["fomc-rate-decision", "cpi-surprise"])
def test_rate_and_cpi_frames_have_no_break_even(frame_id):
    """Honest finding: in this model no action's cash effect depends on a rate or demand shock (the revolver is
    undrawn here, and the model has no rate hedge), and a purchase cut raises cash in both states (no stock-outs,
    MATH_MODEL §3). So ACT >= HEDGE >= WAIT in BOTH states and the forecast p cannot change the recommendation."""
    ev = by_name(evaluate(FRAMES[frame_id], 0.5))
    for value in ("value_if_yes", "value_if_no"):
        assert getattr(ev["ACT"], value) > getattr(ev["HEDGE"], value) > getattr(ev["WAIT"], value)
    for p in [k / 20 for k in range(21)]:
        assert evaluate(FRAMES[frame_id], p).recommendation == "ACT"
    # ACT is sized to the YES hit, so even if YES happens it ends at least as high as the plan's lowest balance.
    assert ev["ACT"].value_if_yes >= ev["WAIT"].value_if_no


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
