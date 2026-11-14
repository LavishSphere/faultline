"""LIVE EXPLORE shock-size guidance in data/explore_shock_guidance.json (issue #79).

The file is ILLUSTRATIVE modelling guidance: per news category, the plausible {min, default, max} for each
ScenarioShock parameter. #61's analyst clamps model suggestions to these ranges. These tests check that every range
is a valid ScenarioShock input on the demo business's 26-week horizon, that every category simulates at min, default
and max, and that a more severe setting never leaves more cash (MATH_MODEL §1-§3).
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from config import get_settings
from core.financials import ActionPlan, DemandShock, RateShock, ScenarioShock, SupplierOutage, simulate
from routes.simulate import load_business

DATA = Path(__file__).resolve().parent.parent / "data"
SETTINGS = dataclasses.replace(get_settings(), data_dir=DATA)

DOC = json.loads((DATA / "explore_shock_guidance.json").read_text(encoding="utf-8"))
BUSINESS_DOC = json.loads((DATA / "demo_business.json").read_text(encoding="utf-8"))
BUSINESS = load_business(SETTINGS)  # the same loader POST /api/simulate uses
T = BUSINESS.horizon_weeks
BASELINE_MIN_CASH = simulate(BUSINESS, ScenarioShock(), ActionPlan()).min_cash
CATEGORIES = {c["id"]: c for c in DOC["categories"]}

# Guidance parameters per shock block, and how each must be bounded. "week" = integer in 1..T.
PARAMS = {
    "rate": {"delta_rate": "rate", "start_week": "week"},
    "demand": {"delta": "fraction", "start_week": "week", "duration_weeks": "count", "recovery_weeks": "count0"},
    "supplier": {
        "availability_during_outage": "fraction",
        "start_week": "week",
        "duration_weeks": "count",
        "dependent_share": "fraction",
    },
}
INTEGER_KINDS = {"week", "count", "count0"}


def build_shock(category_id: str, values: dict[str, dict[str, float]]) -> ScenarioShock:
    """Map guidance parameters to a ScenarioShock exactly as the file's mapping_to_scenario_shock says."""
    rate = demand = supplier = None
    if "rate" in values:
        v = values["rate"]
        rate = RateShock(delta_rate=v["delta_rate"], start_week=v["start_week"])
    if "demand" in values:
        v = values["demand"]
        demand = DemandShock(
            delta=v["delta"],
            start_week=v["start_week"],
            end_week=v["start_week"] + v["duration_weeks"] - 1,
            recovery_weeks=v["recovery_weeks"],
        )
    if "supplier" in values:
        v = values["supplier"]
        first, last = v["start_week"], v["start_week"] + v["duration_weeks"] - 1
        kappa = [v["availability_during_outage"] if first <= t <= last else 1.0 for t in range(1, T + 1)]
        supplier = SupplierOutage(availability=kappa, dependent_share=v["dependent_share"])
    return ScenarioShock(name=category_id, rate=rate, demand=demand, supplier=supplier)


def _point(category: dict, which: str) -> dict[str, dict[str, float]]:
    """All parameters at 'min', 'default' or 'max'."""
    return {block: {p: r[which] for p, r in params.items()} for block, params in category["shocks"].items()}


def _severity(category: dict, level: str) -> dict[str, dict[str, float]]:
    """'mild' or 'severe': each directional parameter at its least / most severe end; timing (null) at default."""
    out: dict[str, dict[str, float]] = {}
    for block, params in category["shocks"].items():
        out[block] = {}
        for p, r in params.items():
            worse = r["worse_when"]
            if worse is None:
                out[block][p] = r["default"]
            elif (worse == "higher") == (level == "severe"):
                out[block][p] = r["max"]
            else:
                out[block][p] = r["min"]
    return out


def _min_cash(category_id: str, values: dict[str, dict[str, float]]) -> float:
    return simulate(BUSINESS, build_shock(category_id, values), ActionPlan()).min_cash


# --------------------------------------------------------------------------- file shape and labels


def test_file_is_labeled_illustrative_and_well_formed():
    assert DOC["provenance"] == "ILLUSTRATIVE"
    assert "ILLUSTRATIVE" in DOC["label"] and "not forecasts" in DOC["label"]
    assert DOC["horizon_weeks"] == T
    assert set(DOC["mapping_to_scenario_shock"]) == set(PARAMS)
    assert 6 <= len(DOC["categories"]) <= 10
    assert len(CATEGORIES) == len(DOC["categories"])  # ids are unique
    for c in DOC["categories"]:
        assert c["provenance"] == "ILLUSTRATIVE", c["id"]
        for key in ("name", "news_trigger", "timing_guidance", "rationale", "basis"):
            assert isinstance(c[key], str) and c[key].strip(), (c["id"], key)
        assert "\n" not in c["rationale"], c["id"]  # one line
        assert c["shocks"] and set(c["shocks"]) <= set(PARAMS), c["id"]


@pytest.mark.parametrize("category_id", list(CATEGORIES))
def test_sources_are_real_links_or_marked_modelling_judgment(category_id):
    c = CATEGORIES[category_id]
    assert "modelling judgment" in c["basis"]  # every exact range is a modelling choice
    if not c["sources"]:
        assert c["basis"] == "modelling judgment"
    for s in c["sources"]:
        assert s["url"].startswith("https://"), s
        assert s["supports"].strip() and s["retrieved_on"] and s["publisher"] and s["title"], s


def test_excluded_news_types_say_why():
    assert DOC["excluded"]
    for e in DOC["excluded"]:
        assert e["news_type"].strip() and e["reason"].strip()


# --------------------------------------------------------------------------- ranges are valid ScenarioShock inputs


@pytest.mark.parametrize("category_id", list(CATEGORIES))
def test_every_range_is_ordered_and_inside_model_bounds(category_id):
    for block, params in CATEGORIES[category_id]["shocks"].items():
        assert set(params) == set(PARAMS[block]), (category_id, block)  # every parameter of the block, nothing else
        for p, r in params.items():
            kind = PARAMS[block][p]
            assert set(r) == {"min", "default", "max", "worse_when"}, (category_id, block, p)
            assert r["min"] <= r["default"] <= r["max"], (category_id, block, p)
            assert r["worse_when"] in ("higher", "lower", None), (category_id, block, p)
            for which in ("min", "default", "max"):
                x = r[which]
                if kind in INTEGER_KINDS:
                    assert isinstance(x, int) and not isinstance(x, bool), (category_id, block, p, which)
                if kind == "fraction":
                    assert 0.0 <= x <= 1.0, (category_id, block, p, which)  # δ, κ, φ
                elif kind == "rate":
                    # Adverse stress only: a positive Δr, and the shocked rate stays a plausible annual rate.
                    assert 0.0 < x <= 0.05, (category_id, block, p, which)
                elif kind == "week":
                    assert 1 <= x <= T, (category_id, block, p, which)
                elif kind == "count":
                    assert 1 <= x <= T, (category_id, block, p, which)
                elif kind == "count0":
                    assert 0 <= x <= T, (category_id, block, p, which)


@pytest.mark.parametrize("category_id", list(CATEGORIES))
def test_every_window_including_recovery_ends_inside_the_horizon(category_id):
    # Worst case: latest start, longest window, longest recovery. Then any clamped suggestion fits in t = 1..T.
    for block, params in CATEGORIES[category_id]["shocks"].items():
        if "duration_weeks" not in params:
            continue
        last = params["start_week"]["max"] + params["duration_weeks"]["max"] - 1
        last += params.get("recovery_weeks", {"max": 0})["max"]
        assert last <= T, (category_id, block, last)


def test_distributor_categories_default_to_the_business_outage_share():
    # φ is carried by SupplierOutage, but the demo business records its own share in scenario_parameters (0.40).
    phi = BUSINESS_DOC["scenario_parameters"]["supplier_outage_dependent_share"]
    assert phi == 0.40
    for cid in ("distributor-strike", "supplier-insolvency", "local-disruption"):
        assert CATEGORIES[cid]["shocks"]["supplier"]["dependent_share"]["default"] == phi, cid
    # A recall hits one product line, so its φ is a much smaller share of sales.
    assert CATEGORIES["product-recall"]["shocks"]["supplier"]["dependent_share"]["max"] < phi


# --------------------------------------------------------------------------- every category simulates


@pytest.mark.parametrize("which", ["min", "default", "max", "mild", "severe"])
@pytest.mark.parametrize("category_id", list(CATEGORIES))
def test_every_category_simulates_without_error(category_id, which):
    c = CATEGORIES[category_id]
    values = _severity(c, which) if which in ("mild", "severe") else _point(c, which)
    shock = build_shock(category_id, values)
    assert {b for b in ("rate", "demand", "supplier") if getattr(shock, b) is not None} == set(c["shocks"])
    res = simulate(BUSINESS, shock, ActionPlan())
    assert len(res.cash) == T
    assert res.min_cash < BASELINE_MIN_CASH  # every setting is an adverse stress


@pytest.mark.parametrize("category_id", list(CATEGORIES))
def test_each_parameter_alone_at_min_and_max_simulates(category_id):
    c = CATEGORIES[category_id]
    for block, params in c["shocks"].items():
        for p in params:
            for which in ("min", "max"):
                values = _point(c, "default")
                values[block][p] = params[p][which]
                simulate(BUSINESS, build_shock(category_id, values), ActionPlan())


# --------------------------------------------------------------------------- more severe never leaves more cash


@pytest.mark.parametrize("category_id", list(CATEGORIES))
def test_severity_ordering_of_min_cash(category_id):
    # Lost sales and extra interest are pointwise larger at the severe end, so the cash path is pointwise lower.
    c = CATEGORIES[category_id]
    mild = _min_cash(category_id, _severity(c, "mild"))
    default = _min_cash(category_id, _point(c, "default"))
    severe = _min_cash(category_id, _severity(c, "severe"))
    assert severe <= default <= mild < BASELINE_MIN_CASH, (severe, default, mild)
    assert severe < mild


@pytest.mark.parametrize("category_id", list(CATEGORIES))
def test_each_directional_parameter_is_monotone(category_id):
    # Exception, by design: start_week of a demand or supplier window has worse_when = null and is not tested here,
    # because moving a window changes how much of it (and of the 2-week payables lag) falls inside the horizon.
    c = CATEGORIES[category_id]
    for block, params in c["shocks"].items():
        for p, r in params.items():
            if r["worse_when"] is None:
                assert p == "start_week" and block in ("demand", "supplier"), (category_id, block, p)
                continue
            cash = {}
            for which in ("min", "default", "max"):
                values = _point(c, "default")
                values[block][p] = r[which]
                cash[which] = _min_cash(category_id, values)
            if r["worse_when"] == "higher":
                assert cash["max"] <= cash["default"] <= cash["min"], (category_id, block, p, cash)
            else:
                assert cash["min"] <= cash["default"] <= cash["max"], (category_id, block, p, cash)


def test_rate_only_category_min_cash_matches_hand_arithmetic():
    # Δr from week t_r on the 600k floating term loan costs 600,000 Δr / 52 a week for (T - t_r + 1) weeks, and the
    # baseline ends at 63,000 (MATH_MODEL §10). Default: +50bp from week 1 → 26 x 57.69 = 1,500 → 61,500.
    r = CATEGORIES["central-bank-rate-surprise"]["shocks"]["rate"]
    for which in ("min", "default", "max"):
        dr, tr = r["delta_rate"][which], r["start_week"][which]
        expected = 63_000.0 - 600_000.0 * dr / 52.0 * (T - tr + 1)
        got = _min_cash("central-bank-rate-surprise", {"rate": {"delta_rate": dr, "start_week": tr}})
        assert got == pytest.approx(expected, abs=1e-6), which
    assert _min_cash(
        "central-bank-rate-surprise", {"rate": {"delta_rate": 0.005, "start_week": 1}}
    ) == pytest.approx(61_500.0, abs=1e-6)
