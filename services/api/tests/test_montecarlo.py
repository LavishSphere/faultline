"""Monte Carlo engines (docs/MATH_MODEL.md §11, issue #208).

Analytic checks first (known means, quantiles and Wilson intervals worked out by hand), then the exact-agreement test
of the cash engine with core.financials.simulate() at zero uncertainty, then the HTTP contract.

Every decision input below is a MADE-UP EXAMPLE for testing only: not an estimate, forecast or view of any company.
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from core.financials import ActionPlan, BusinessParams, ScenarioShock, simulate
from core.montecarlo import (
    HIST_BINS,
    CashUncertainty,
    DecisionRequest,
    canonical_sha256,
    cash_paths,
    expected_shortfall,
    run_cash,
    run_decision,
    sample_cash_draws,
    wilson,
)
from core.optimizer import OPTIMAL, OptimizerSettings, optimize
from main import create_app

DATA = Path(__file__).resolve().parent.parent / "data"
DOC = json.loads((DATA / "demo_business.json").read_text(encoding="utf-8"))
BUSINESS = BusinessParams.model_validate(DOC["business"])
OPT_SETTINGS = OptimizerSettings.from_dict(DOC["optimizer_parameters"])
SCENARIOS = {s["id"]: ScenarioShock.model_validate(s["shock"])
             for s in json.loads((DATA / "scenarios.json").read_text(encoding="utf-8"))["scenarios"]}
ZERO = CashUncertainty(demand_drop_spread=0, demand_duration_spread=0, rate_move_spread=0, outage_weeks_spread=0,
                       weekly_demand_noise_sd=0)

# MADE-UP EXAMPLE INPUTS (test only): the shape a chat tool would send for a CEO-succession question. The numbers are
# invented to exercise the engine; they are not an estimate of anything about any real company or person.
NVIDIA_CEO_EXAMPLE = {
    "question": "Should Nvidia keep Jensen Huang as CEO?",
    "metric": {"name": "change in 3-year shareholder value (MADE-UP EXAMPLE)", "unit": "USD bn",
               "higher_is_better": True},
    "options": [
        {"id": "keep", "label": "Keep the current CEO", "drivers": [
            {"name": "product execution", "kind": "value", "distribution": "triangular",
             "params": {"low": -300.0, "mode": 200.0, "high": 800.0},
             "source": {"url": None, "title": None, "note": "MADE-UP EXAMPLE range for a test"}},
            {"name": "key-person health event", "kind": "event", "distribution": "triangular",
             "params": {"low": -600.0, "mode": -300.0, "high": -100.0}, "probability": 0.15},
        ]},
        {"id": "replace", "label": "Appoint an outside CEO", "drivers": [
            {"name": "product execution", "kind": "value", "distribution": "triangular",
             "params": {"low": -500.0, "mode": 50.0, "high": 700.0}},
            {"name": "transition disruption", "kind": "value", "distribution": "normal",
             "params": {"mean": -150.0, "sd": 80.0}},
            {"name": "new-strategy upside", "kind": "event", "distribution": "lognormal",
             "params": {"median": 50.0, "p90": 200.0}, "probability": 0.4},
        ]},
    ],
}


def _req(options, higher=True, **kw) -> DecisionRequest:
    return DecisionRequest.model_validate(
        {"question": "test", "metric": {"name": "m", "unit": "u", "higher_is_better": higher}, "options": options, **kw}
    )


def _opt(oid, *drivers):
    return {"id": oid, "label": oid.upper(), "drivers": list(drivers)}


def _drv(name, dist, params, kind="value", probability=None):
    return {"name": name, "kind": kind, "distribution": dist, "params": params, "probability": probability}


def _no_runtime(d: dict) -> dict:
    return {k: v for k, v in d.items() if k != "runtime_ms"}


@pytest.fixture
def client():
    return TestClient(create_app())


# --------------------------------------------------------------------------- Wilson interval (hand-worked)


def test_wilson_hand_values():
    # p = 0.5, n = 100: centre 0.5, half = 1.96/(1 + 0.038415) * sqrt(0.0025 + 0.0000960) = 0.096170
    lo, hi = wilson(0.5, 100)
    assert lo == pytest.approx(0.403830, abs=1e-5) and hi == pytest.approx(0.596170, abs=1e-5)
    # p = 0, n = 20,000: [0, z^2/n / (1 + z^2/n)] = [0, 3.841459/20000 / 1.000192] = [0, 0.00019204]
    assert wilson(0.0, 20_000) == (0.0, pytest.approx(0.000192036, rel=1e-4))
    assert wilson(1.0, 20_000) == (pytest.approx(1 - 0.000192036, rel=1e-6), 1.0)
    for p in (0.0, 0.01, 0.3, 0.97, 1.0):
        lo, hi = wilson(p, 1000)
        assert 0.0 <= lo <= p <= hi <= 1.0


# --------------------------------------------------------------------------- decision engine: analytic sanity


@pytest.mark.parametrize("dist,params,mean,sd", [
    ("normal", {"mean": 10.0, "sd": 2.0}, 10.0, 2.0),
    ("uniform", {"low": -4.0, "high": 8.0}, 2.0, 12.0 / math.sqrt(12.0)),
    # triangular mean (a+b+c)/3; var (a²+b²+c²-ab-ac-bc)/18 with a=0, b=10, c=4: (100+16-40)/18 = 4.2222
    ("triangular", {"low": 0.0, "mode": 4.0, "high": 10.0}, 14.0 / 3.0, math.sqrt(76.0 / 18.0)),
])
def test_value_driver_moments(dist, params, mean, sd):
    res = run_decision(_req([_opt("a", _drv("x", dist, params)), _opt("b", _drv("y", "normal",
                                                                                {"mean": 0, "sd": 1}))],
                            n_paths=100_000))
    a = res.options[0]
    assert a.mean == pytest.approx(mean, abs=0.02 * sd + 1e-9)
    assert a.sd == pytest.approx(sd, rel=0.02)


def test_lognormal_fit_hits_median_and_p90():
    # mu = ln 100, sigma = ln(300/100) / 1.28155 = 0.85725; P90 = 300 by construction
    res = run_decision(_req([_opt("a", _drv("x", "lognormal", {"median": 100.0, "p90": 300.0})),
                             _opt("b", _drv("y", "normal", {"mean": 0, "sd": 1}))], n_paths=100_000))
    a = res.options[0]
    assert a.p50 == pytest.approx(100.0, rel=0.02)
    assert a.mean == pytest.approx(100.0 * math.exp(0.85725**2 / 2), rel=0.02)  # E = e^(mu + sigma²/2) = 144.3


def test_event_driver_mean_is_probability_times_mean():
    # E = p * E[Y] = 0.3 * (-100 + -50 + 0)/3 = -15; P(metric < 0) = p = 0.3
    res = run_decision(_req([_opt("a", _drv("e", "triangular", {"low": -100.0, "mode": -50.0, "high": 0.0},
                                            kind="event", probability=0.3)),
                             _opt("b", _drv("y", "normal", {"mean": 0, "sd": 1}))], n_paths=100_000))
    a = res.options[0]
    assert a.mean == pytest.approx(-15.0, abs=0.3)
    assert a.prob_below_zero == pytest.approx(0.3, abs=0.01)


def test_identical_options_are_an_exact_coin_flip_under_common_random_numbers():
    d = _drv("shared", "normal", {"mean": 5.0, "sd": 3.0})
    res = run_decision(_req([_opt("a", d), _opt("b", d)]))
    # same draws -> every path ties -> 1/2 credit each (§11.1)
    assert res.pairwise[0].prob_a_better == 0.5
    assert res.best.prob_best == 0.5
    assert res.options[0].model_dump() | {"id": "b", "label": "B"} == res.options[1].model_dump()


def test_independent_identical_distributions_are_near_one_half():
    res = run_decision(_req([_opt("a", _drv("x", "normal", {"mean": 0, "sd": 1})),
                             _opt("b", _drv("y", "normal", {"mean": 0, "sd": 1}))], n_paths=50_000))
    pw = res.pairwise[0]
    assert pw.prob_a_better == pytest.approx(0.5, abs=0.015)
    assert pw.ci95[0] <= pw.prob_a_better <= pw.ci95[1]


def test_dominant_option_wins_and_direction_respects_higher_is_better():
    opts = [_opt("low", _drv("x", "uniform", {"low": 0.0, "high": 1.0})),
            _opt("high", _drv("x", "uniform", {"low": 10.0, "high": 11.0})),
            _opt("mid", _drv("x", "uniform", {"low": 5.0, "high": 6.0}))]
    up = run_decision(_req(opts, higher=True))
    assert up.best.id == "high" and up.best.prob_best == 1.0 and up.best.ci95[1] == 1.0
    assert {(p.a, p.b): p.prob_a_better for p in up.pairwise} == {("low", "high"): 0.0, ("low", "mid"): 0.0,
                                                                ("high", "mid"): 1.0}
    down = run_decision(_req(opts, higher=False))  # e.g. a cost metric
    assert down.best.id == "low" and down.best.prob_best == 1.0


def test_histogram_quantiles_and_sensitivity_shape():
    res = run_decision(_req([
        _opt("a", _drv("big", "uniform", {"low": 0.0, "high": 100.0}), _drv("small", "uniform",
                                                                            {"low": 0.0, "high": 1.0})),
        _opt("b", _drv("solo", "triangular", {"low": 0.0, "mode": 5.0, "high": 10.0})),
    ]))
    edges = res.options[0].histogram.bin_edges
    assert len(edges) == HIST_BINS + 1 == 41 and edges == res.options[1].histogram.bin_edges
    for o in res.options:
        assert len(o.histogram.counts) == 40 and sum(o.histogram.counts) == res.n_paths
        assert o.p5 <= o.p25 <= o.p50 <= o.p75 <= o.p95
    swings = [s.swing for s in res.sensitivity]
    assert swings == sorted(swings, reverse=True)
    assert (res.sensitivity[0].option_id, res.sensitivity[0].driver) == ("a", "big")
    # one-driver option: fixing the driver at its P10 / P90 makes the option p50 exactly that quantile.
    # Tri(0,5,10) P10 = sqrt(0.1 * 10 * 5) = 2.2361, P90 = 10 - 2.2361 = 7.7639
    solo = next(s for s in res.sensitivity if s.driver == "solo")
    assert solo.low_p50 == pytest.approx(2.2361, abs=0.05) and solo.high_p50 == pytest.approx(7.7639, abs=0.05)
    # 'big' swing ~ P90 - P10 of U(0,100) = 80
    assert res.sensitivity[0].swing == pytest.approx(80.0, abs=1.0)


# --------------------------------------------------------------------------- per-option prob_best and CVaR (#240)


def _assert_prob_best_contract(res):
    assert sum(o.prob_best for o in res.options) == pytest.approx(1.0, abs=1e-9)
    for o in res.options:
        assert o.prob_best_ci95 == wilson(o.prob_best, res.n_paths)
        assert o.prob_best_ci95[0] <= o.prob_best <= o.prob_best_ci95[1]
    winner = next(o for o in res.options if o.id == res.best.id)
    assert res.best.prob_best == winner.prob_best and res.best.ci95 == winner.prob_best_ci95
    assert winner.prob_best == max(o.prob_best for o in res.options)


def test_prob_best_per_option_sums_to_one_and_matches_best():
    res = run_decision(DecisionRequest.model_validate(NVIDIA_CEO_EXAMPLE))
    _assert_prob_best_contract(res)
    assert 0.0 < res.options[0].prob_best < 1.0 and 0.0 < res.options[1].prob_best < 1.0
    # two options: prob_best of a is exactly the pairwise share P(a better) (ties split the same way)
    assert res.options[0].prob_best == pytest.approx(res.pairwise[0].prob_a_better, abs=1e-12)


def test_prob_best_dominant_option_gets_one_and_the_others_zero():
    opts = [_opt("low", _drv("x", "uniform", {"low": 0.0, "high": 1.0})),
            _opt("high", _drv("x", "uniform", {"low": 10.0, "high": 11.0})),
            _opt("mid", _drv("x", "uniform", {"low": 5.0, "high": 6.0}))]
    up = run_decision(_req(opts, higher=True))
    assert [o.prob_best for o in up.options] == [0.0, 1.0, 0.0]
    down = run_decision(_req(opts, higher=False))
    assert [o.prob_best for o in down.options] == [1.0, 0.0, 0.0]
    _assert_prob_best_contract(up)
    _assert_prob_best_contract(down)


@pytest.mark.parametrize("k", [2, 3, 4])
def test_prob_best_identical_options_split_evenly(k):
    d = _drv("shared", "normal", {"mean": 5.0, "sd": 3.0})  # same name -> same draws -> every path a k-way tie
    res = run_decision(_req([_opt(f"o{i}", d) for i in range(k)]))
    assert all(o.prob_best == pytest.approx(1.0 / k, abs=1e-12) for o in res.options)
    _assert_prob_best_contract(res)
    # independent identical options: about 1/k each
    ind = run_decision(_req([_opt(f"o{i}", _drv(f"x{i}", "normal", {"mean": 0, "sd": 1})) for i in range(k)],
                            n_paths=50_000))
    assert all(o.prob_best == pytest.approx(1.0 / k, abs=0.015) for o in ind.options)
    _assert_prob_best_contract(ind)


def test_expected_shortfall_hand_examples():
    x = np.arange(100, dtype=float)  # 0..99; k = ceil(0.05 * 100) = 5
    assert expected_shortfall(x, True) == pytest.approx((0 + 1 + 2 + 3 + 4) / 5)  # = 2.0
    assert expected_shortfall(x, False) == pytest.approx((95 + 96 + 97 + 98 + 99) / 5)  # = 97.0
    y = np.array([7.0, -3.0, 12.0, 0.0, -10.0, 5.0, 1.0, 2.0, 3.0, 4.0] * 3)  # N = 30; k = ceil(1.5) = 2
    assert expected_shortfall(y, True) == pytest.approx((-10.0 + -10.0) / 2)
    assert expected_shortfall(y, False) == pytest.approx((12.0 + 12.0) / 2)
    z = np.array([-10.0, -3.0, 0.0, 1.0] + [2.0] * 17)  # N = 21; k = ceil(1.05) = 2 -> (-10 + -3) / 2 = -6.5
    assert expected_shortfall(z, True) == pytest.approx(-6.5)
    both = expected_shortfall(np.vstack([x, x + 1.0]), True)  # row-wise on an (options, paths) array
    assert both.tolist() == pytest.approx([2.0, 3.0])


def test_expected_shortfall_in_the_engine_is_the_worst_tail_mean():
    # U(0, 100): the worst 5% (higher is better) is U(0, 5), mean 2.5; lower is better: U(95, 100), mean 97.5
    opts = [_opt("a", _drv("x", "uniform", {"low": 0.0, "high": 100.0})),
            _opt("b", _drv("y", "normal", {"mean": 0.0, "sd": 1.0}))]
    up = run_decision(_req(opts, higher=True, n_paths=100_000))
    down = run_decision(_req(opts, higher=False, n_paths=100_000))
    assert up.options[0].expected_shortfall_5 == pytest.approx(2.5, abs=0.1)
    assert down.options[0].expected_shortfall_5 == pytest.approx(97.5, abs=0.1)
    # N(0, 1): CVaR_5 = -phi(z_0.05) / 0.05 = -0.10314 / 0.05 = -2.0627 (lower tail)
    assert up.options[1].expected_shortfall_5 == pytest.approx(-2.0627, abs=0.03)
    assert down.options[1].expected_shortfall_5 == pytest.approx(2.0627, abs=0.03)
    for res in (up, run_decision(DecisionRequest.model_validate(NVIDIA_CEO_EXAMPLE))):
        for o in res.options:
            assert o.expected_shortfall_5 <= o.p5 <= o.mean  # higher is better: the tail mean sits below P5
    for o in down.options:
        assert o.expected_shortfall_5 >= o.p95  # lower is better: the worst tail is the top 5%


def test_prob_best_and_cvar_are_reproducible_with_the_seed():
    req = DecisionRequest.model_validate(NVIDIA_CEO_EXAMPLE)
    a, b = run_decision(req), run_decision(req)
    pick = [(o.prob_best, o.prob_best_ci95, o.expected_shortfall_5) for o in a.options]
    assert pick == [(o.prob_best, o.prob_best_ci95, o.expected_shortfall_5) for o in b.options]
    c = run_decision(req.model_copy(update={"seed": 7}))
    assert [o.expected_shortfall_5 for o in c.options] != [o.expected_shortfall_5 for o in a.options]


# --------------------------------------------------------------------------- reproducibility and hashing


def test_decision_is_reproducible_and_seed_sensitive():
    req = DecisionRequest.model_validate(NVIDIA_CEO_EXAMPLE)
    a, b = run_decision(req), run_decision(req)
    assert _no_runtime(a.model_dump()) == _no_runtime(b.model_dump())
    c = run_decision(req.model_copy(update={"seed": 7}))
    assert c.options[0].mean != a.options[0].mean and c.input_sha256 != a.input_sha256
    expected = hashlib.sha256(json.dumps(req.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
                              .encode()).hexdigest()
    assert a.input_sha256 == expected == canonical_sha256(req.model_dump(mode="json"))
    assert a.seed == 20261115 and a.n_paths == 20_000


def test_adding_an_option_does_not_change_existing_draws():
    """Each driver name has its own stream (§11.1), so a third option leaves A and B's numbers unchanged."""
    two = _req([_opt("a", _drv("x", "normal", {"mean": 0, "sd": 1})), _opt("b", _drv("y", "normal",
                                                                                  {"mean": 1, "sd": 1}))])
    three = _req([*two.model_dump()["options"], _opt("c", _drv("z", "normal", {"mean": 2, "sd": 1}))])
    r2, r3 = run_decision(two), run_decision(three)
    assert r2.options[0].mean == r3.options[0].mean and r2.options[1].p95 == r3.options[1].p95


def test_cash_is_reproducible(client):
    body = {"scenario_id": "bad-quarter", "n_paths": 2000}
    a, b = client.post("/api/montecarlo/cash", json=body).json(), client.post("/api/montecarlo/cash", json=body).json()
    assert _no_runtime(a) == _no_runtime(b)
    c = client.post("/api/montecarlo/cash", json={**body, "seed": 1}).json()
    assert c["no_plan"]["bands"]["p50"] != a["no_plan"]["bands"]["p50"] and c["input_sha256"] != a["input_sha256"]


# --------------------------------------------------------------------------- cash engine: exact agreement


@pytest.mark.parametrize("sid", [None, *SCENARIOS])
def test_zero_uncertainty_cash_matches_simulate_exactly(sid):
    shock = SCENARIOS[sid] if sid else ScenarioShock()
    draws = sample_cash_draws(BUSINESS, shock, 1000, 20261115, ZERO)
    C, capped = cash_paths(BUSINESS, draws, ActionPlan())
    ref = np.array(simulate(BUSINESS, shock, ActionPlan()).cash)
    assert capped == 0
    assert np.max(np.abs(C - ref)) < 1e-6
    # and with the optimizer's plan on the central scenario
    opt = optimize(BUSINESS, shock, True, OPT_SETTINGS)
    assert opt.status == OPTIMAL
    C1, _ = cash_paths(BUSINESS, draws, opt.plan)
    assert np.max(np.abs(C1 - np.array(simulate(BUSINESS, shock, opt.plan).cash))) < 1e-6
    assert np.max(np.abs(C1 - np.array(opt.cash))) < 1e-6


def test_zero_uncertainty_summary_is_the_deterministic_answer():
    shock = SCENARIOS["bad-quarter"]
    sim = simulate(BUSINESS, shock, ActionPlan())
    res = run_cash(BUSINESS, shock, scenario_id="bad-quarter", n_paths=1000, seed=1, input_sha256="x",
                   plan_result=None, unc=ZERO)
    below = any(c < BUSINESS.min_cash - 1e-6 for c in sim.cash)
    assert res.no_plan.prob_below_floor_any == float(below)
    assert res.no_plan.min_cash.p5 == pytest.approx(sim.min_cash, abs=1e-6)
    assert res.no_plan.bands.p50 == pytest.approx(sim.cash, abs=1e-6)


def test_outage_window_resampling_keeps_the_central_shape():
    shock = SCENARIOS["supplier-outage-3wk"]  # κ = 0 in weeks 5-7
    unc = ZERO.model_copy(update={"outage_weeks_spread": 0.5})  # L' in round Tri(1.5, 3, 4.5) -> 2..4 (min 1)
    k = sample_cash_draws(BUSINESS, shock, 5000, 3, unc).kappa
    lengths = (k < 1.0).sum(axis=1)
    assert set(np.unique(lengths)) <= {2, 3, 4} and (k[:, :4] == 1.0).all()  # always starts in week 5
    assert set(np.unique(k)) == {0.0, 1.0}


def test_bigger_spread_widens_the_bands():
    shock = SCENARIOS["demand-drop-20pct-6wk"]
    narrow = run_cash(BUSINESS, shock, scenario_id=None, n_paths=5000, seed=2, input_sha256="x", plan_result=None,
                      unc=CashUncertainty(demand_drop_spread=0.1, weekly_demand_noise_sd=0.0))
    wide = run_cash(BUSINESS, shock, scenario_id=None, n_paths=5000, seed=2, input_sha256="x", plan_result=None,
                    unc=CashUncertainty(demand_drop_spread=0.9, weekly_demand_noise_sd=0.0))
    spread = lambda r: r.no_plan.bands.p95[-1] - r.no_plan.bands.p5[-1]  # noqa: E731
    assert spread(wide) > spread(narrow)


# --------------------------------------------------------------------------- HTTP: decision


def test_decision_route_example_response(client):
    r = client.post("/api/montecarlo/decision", json=NVIDIA_CEO_EXAMPLE)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["provenance"] == "SIMULATED" and j["label"].startswith("Monte Carlo computed by FAULTLINE")
    assert set(j) == {"provenance", "label", "question", "metric", "n_paths", "seed", "input_sha256", "runtime_ms",
                      "options", "pairwise", "best", "sensitivity", "assumptions"}
    assert set(j["options"][0]) == {"id", "label", "mean", "sd", "p5", "p25", "p50", "p75", "p95",
                                    "prob_below_zero", "prob_best", "prob_best_ci95", "expected_shortfall_5",
                                    "histogram"}
    assert sum(o["prob_best"] for o in j["options"]) == pytest.approx(1.0, abs=1e-9)
    assert [(p["a"], p["b"]) for p in j["pairwise"]] == [("keep", "replace")]
    assert j["best"]["id"] in {"keep", "replace"} and 0 <= j["best"]["ci95"][0] <= j["best"]["ci95"][1] <= 1
    assert len(j["sensitivity"]) == 5 and len(j["assumptions"]) == 5
    assert j["assumptions"][0]["source"]["note"] == "MADE-UP EXAMPLE range for a test"
    assert j["runtime_ms"] >= 0


@pytest.mark.parametrize("mutate,needle", [
    (lambda b: b["options"][0]["drivers"][0]["params"].update(mode=900.0), "low <= mode <= high"),
    (lambda b: b["options"][1]["drivers"][1]["params"].update(sd=0.0), "sd > 0"),
    (lambda b: b["options"][1]["drivers"][2]["params"].update(p90=10.0), "0 < median < p90"),
    (lambda b: b["options"][0]["drivers"][1].update(probability=None), "needs a probability"),
    (lambda b: b["options"][0]["drivers"][0].update(probability=0.5), "probability null"),
    (lambda b: b["options"][0]["drivers"][1].update(probability=1.5), "less than or equal to 1"),
    (lambda b: b["options"][0]["drivers"][0]["params"].update(sd=1.0), "needs params exactly"),
    (lambda b: b["options"][0]["drivers"][0].update(distribution="beta"), "triangular"),
    (lambda b: b.update(options=b["options"][:1]), "at least 2"),
    (lambda b: b.update(options=b["options"] * 3), "at most 4"),
    (lambda b: b["options"][1].update(id="keep"), "option ids must be unique"),
    (lambda b: b["options"][0]["drivers"].append(b["options"][0]["drivers"][0]), "unique within an option"),
    (lambda b: b.update(n_paths=999), "greater than or equal to 1000"),
    (lambda b: b.update(n_paths=100_001), "less than or equal to 100000"),
    (lambda b: b.update(question="x" * 501), "at most 500"),
    (lambda b: b.update(extra=1), "Extra inputs"),
    (lambda b: b["options"][0]["drivers"][0]["params"].update(high=1e13), "<= 1e+12"),
    (lambda b: b["options"][0]["drivers"][0].update(source={"url": "javascript:alert(1)"}), "pattern"),
])
def test_decision_validation_errors(client, mutate, needle):
    body = json.loads(json.dumps(NVIDIA_CEO_EXAMPLE))
    mutate(body)
    r = client.post("/api/montecarlo/decision", json=body)
    assert r.status_code == 422, r.text
    j = r.json()
    assert j["code"] == "VALIDATION_ERROR"
    assert any(needle in e["msg"] for e in j["errors"]), j["errors"]


def test_decision_rejects_non_finite_numbers(client):
    text = json.dumps(NVIDIA_CEO_EXAMPLE).replace("800.0", "NaN")
    r = client.post("/api/montecarlo/decision", content=text, headers={"content-type": "application/json"})
    assert r.status_code == 422 and r.json()["code"] == "VALIDATION_ERROR"


# --------------------------------------------------------------------------- HTTP: cash


def test_cash_route_contract(client):
    r = client.post("/api/montecarlo/cash", json={"scenario_id": "bad-quarter"})
    assert r.status_code == 200, r.text
    j = r.json()
    assert (j["provenance"], j["synthetic"], j["weeks"], j["floor"]) == ("SIMULATED", True, 26, 25_000.0)
    assert j["label"].startswith("Monte Carlo on the SYNTHETIC demo business")
    assert j["n_paths"] == 10_000 and j["seed"] == 20261115
    for key in ("no_plan", "with_plan"):
        s = j[key]
        bands = s["bands"]
        assert all(len(bands[q]) == 26 for q in ("p5", "p25", "p50", "p75", "p95"))
        assert all(a <= b + 1e-9 for q1, q2 in [("p5", "p25"), ("p25", "p50"), ("p50", "p75"), ("p75", "p95")]
                   for a, b in zip(bands[q1], bands[q2], strict=True))
        assert len(s["prob_below_floor_by_week"]) == 26
        lo, hi = s["prob_below_floor_ci95"]
        assert 0 <= lo <= s["prob_below_floor_any"] <= hi <= 1
        assert max(s["prob_below_floor_by_week"]) <= s["prob_below_floor_any"]
        assert s["min_cash"]["p5"] <= s["min_cash"]["p50"] <= s["min_cash"]["p95"]
    assert j["plan"]["status"] == "OPTIMAL" and j["plan"]["actions"]
    # The plan was built to hold the floor on the central path, so it should help on most paths, not all.
    assert j["with_plan"]["prob_below_floor_any"] < j["no_plan"]["prob_below_floor_any"]
    assert {a["provenance"] for a in j["assumptions"]} == {"ILLUSTRATIVE"}
    assert {a["name"] for a in j["assumptions"]} == {
        "demand_drop_size", "demand_drop_duration_weeks", "weekly_demand_noise", "rate_move_annual",
        "supplier_outage_weeks"}


def test_cash_without_plan_and_explicit_shock(client):
    shock = {"name": "my shock", "rate": {"delta_rate": 0.03, "start_week": 2}}
    j = client.post("/api/montecarlo/cash", json={"shock": shock, "with_plan": False, "n_paths": 1000}).json()
    assert j["with_plan"] is None and j["plan"] is None
    assert {a["name"] for a in j["assumptions"]} == {"weekly_demand_noise", "rate_move_annual"}


def test_cash_errors(client):
    r = client.post("/api/montecarlo/cash", json={"scenario_id": "no-such-scenario"})
    assert r.status_code == 404 and r.json()["code"] == "NOT_FOUND"
    for bad in ({"n_paths": 999}, {"n_paths": 50_001}, {"foo": 1},
                {"shock": {"supplier": {"availability": [1.0, 0.0], "dependent_share": 0.4}}}):
        r = client.post("/api/montecarlo/cash", json=bad)
        assert r.status_code == 422 and r.json()["code"] == "VALIDATION_ERROR", (bad, r.text)


def test_cash_no_feasible_plan_is_reported_not_hidden(client):
    severe = {"name": "severe", "demand": {"delta": 0.5, "start_week": 5, "end_week": 10, "recovery_weeks": 4}}
    j = client.post("/api/montecarlo/cash", json={"shock": severe, "n_paths": 1000}).json()
    assert j["plan"]["status"] == "NO FEASIBLE PLAN" and j["with_plan"] is None and j["plan"]["actions"] is None


# --------------------------------------------------------------------------- public mode and speed


def test_routes_are_public_in_public_mode(monkeypatch):
    monkeypatch.setenv("FAULTLINE_MODE", "public")
    monkeypatch.setenv("FAULTLINE_ADMIN_TOKEN", "f6" * 32)
    monkeypatch.setenv("FAULTLINE_PUBLIC_ORIGIN", "https://faultline.khayrul.com")
    c = TestClient(create_app())
    assert c.post("/api/montecarlo/decision", json=NVIDIA_CEO_EXAMPLE).status_code == 200
    assert c.post("/api/montecarlo/cash", json={"n_paths": 1000}).status_code == 200


def test_defaults_run_well_under_two_seconds(client):
    t = time.perf_counter()
    assert client.post("/api/montecarlo/decision", json=NVIDIA_CEO_EXAMPLE).status_code == 200
    assert client.post("/api/montecarlo/cash", json={"scenario_id": "bad-quarter"}).status_code == 200
    assert time.perf_counter() - t < 2.0
