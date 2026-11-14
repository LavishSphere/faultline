"""POST /api/optimize (#47): numbers straight from core.optimizer.optimize, coded errors like /api/simulate.

The optimizer itself is hand-checked in test_optimizer.py; here it is the oracle and the route must return exactly
what optimize() produces for the demo business with the fixture's signed-off optimizer_parameters.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from core.financials import BusinessParams, ScenarioShock
from core.optimizer import OptimizerSettings, optimize
from main import create_app

REAL_DATA = Path(__file__).resolve().parent.parent / "data"
DOC = json.loads((REAL_DATA / "demo_business.json").read_text(encoding="utf-8"))
TOL = 1e-6

SHARP_DIP = {"name": "60% drop weeks 5-8", "demand": {"delta": 0.6, "start_week": 5, "end_week": 8}}
SEVERE_DROP = {
    "name": "50% drop weeks 5-10, 4-week recovery",
    "demand": {"delta": 0.5, "start_week": 5, "end_week": 10, "recovery_weeks": 4},
}


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    d = tmp_path / "data"
    d.mkdir()
    shutil.copy(REAL_DATA / "demo_business.json", d / "demo_business.json")
    monkeypatch.setenv("FAULTLINE_DATA_DIR", str(d))
    return d


@pytest.fixture
def client(data_dir):
    return TestClient(create_app())


def _engine(shock: dict, protect: bool) -> dict:
    params = BusinessParams.model_validate(DOC["business"])
    settings = OptimizerSettings.from_dict(DOC["optimizer_parameters"])
    return optimize(params, ScenarioShock.model_validate(shock), protect, settings).model_dump(mode="json")


def test_feasible_case_is_the_engine_result_labelled_simulated(client):
    resp = client.post("/api/optimize", json={"shock": SHARP_DIP, "protect_payroll": True})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["provenance"] == "SIMULATED"
    assert body["business_provenance"] == "SYNTHETIC"
    assert body["status"] == "OPTIMAL"
    expected = _engine(SHARP_DIP, True)
    served = {"business_provenance", "payroll_cut_cap", "supplier_lag_weeks"}
    assert {k: v for k, v in body.items() if k not in served} == expected
    # #157 (F15, F18): the configured z-bar and L_p from the fixture, so the screen never hardcodes them.
    assert body["payroll_cut_cap"] == DOC["optimizer_parameters"]["payroll_cut_cap"] == 0.1
    assert body["supplier_lag_weeks"] == DOC["business"]["supplier_lag_weeks"] == 2
    assert body["scenario_name"] == SHARP_DIP["name"]
    assert body["protect_payroll"] is True
    assert body["actions"] and body["binding_constraints"]
    assert body["objective"] is not None and body["min_cash"] >= DOC["business"]["min_cash"] - TOL
    assert all(z == 0.0 for z in body["plan"]["payroll_cut"])


def test_severe_drop_with_protect_payroll_is_no_feasible_plan_with_smallest_floor(client):
    protected = client.post("/api/optimize", json={"shock": SEVERE_DROP, "protect_payroll": True})
    assert protected.status_code == 200, protected.text
    body = protected.json()
    assert body["status"] == "NO FEASIBLE PLAN"
    assert body["provenance"] == "SIMULATED"
    # Hand-checked in test_optimizer.py: -2,625 + 25,000 of purchase cuts = 22,375.
    assert body["max_feasible_cash_floor"] == pytest.approx(22_375.0, abs=1e-4)
    assert "22,375" in body["diagnostic"]
    for field in ("plan", "actions", "cash", "min_cash", "binding_constraints", "objective"):
        assert body[field] is None  # nothing invented for an infeasible problem

    allowed = client.post("/api/optimize", json={"shock": SEVERE_DROP, "protect_payroll": False}).json()
    assert allowed["status"] == "OPTIMAL"
    assert sum(allowed["plan"]["payroll_cut"]) > 0.0


def test_plan_resimulated_through_simulate_gives_the_same_cash_path(client):
    for shock, protect in ((SHARP_DIP, True), (SEVERE_DROP, False)):
        opt = client.post("/api/optimize", json={"shock": shock, "protect_payroll": protect}).json()
        assert opt["status"] == "OPTIMAL"
        sim = client.post("/api/simulate", json={"shock": shock, "plan": opt["plan"]})
        assert sim.status_code == 200, sim.text
        cash = sim.json()["result"]["cash"]
        assert len(cash) == len(opt["cash"])
        assert max(abs(a - b) for a, b in zip(cash, opt["cash"], strict=True)) <= TOL


def test_scenario_id_names_the_result_when_no_explicit_name(client):
    shock = {"demand": SHARP_DIP["demand"]}
    body = client.post("/api/optimize", json={"scenario_id": "sharp-dip", "shock": shock,
                                              "protect_payroll": False}).json()
    assert body["scenario_name"] == "sharp-dip"


@pytest.mark.parametrize(
    "payload",
    [
        {"shock": {}},  # protect_payroll missing
        {"shock": {"demand": {"delta": 1.5, "start_week": 1, "end_week": 2}}, "protect_payroll": True},
        {"shock": {"demand": {"delta": 0.2, "start_week": 5, "end_week": 2}}, "protect_payroll": True},
        {"shock": {}, "protect_payroll": True, "plan": {}},  # extra field
        {"shock": {"supplier": {"availability": [1.0, 0.0], "dependent_share": 0.4}}, "protect_payroll": True},
    ],
)
def test_bad_input_is_a_coded_422_like_simulate(client, payload):
    resp = client.post("/api/optimize", json=payload)
    assert resp.status_code == 422, resp.text
    body = resp.json()
    assert set(body) == {"code", "message", "errors"}
    assert body["code"] == "VALIDATION_ERROR"


def test_value_error_from_the_engine_is_a_422_with_its_message(client, monkeypatch):
    import routes.optimize as route

    def boom(*_a, **_k):
        raise ValueError("week 3: rate path is undefined")

    monkeypatch.setattr(route, "optimize", boom)
    resp = client.post("/api/optimize", json={"shock": {}, "protect_payroll": True})
    assert resp.status_code == 422
    assert resp.json() == {"code": "INFEASIBLE_INPUT", "message": "week 3: rate path is undefined", "errors": []}


def test_solver_error_is_reported_with_the_solvers_own_message(client, monkeypatch):
    import routes.optimize as route
    from core.optimizer import OptimizationResult

    def failing(params, shock, protect, settings):
        return OptimizationResult(status="SOLVER ERROR", solver_message="HiGHS: time limit reached",
                                  scenario_name=shock.name, protect_payroll=protect)

    monkeypatch.setattr(route, "optimize", failing)
    body = client.post("/api/optimize", json={"shock": {}, "protect_payroll": True}).json()
    assert body["status"] == "SOLVER ERROR"
    assert body["solver_message"] == "HiGHS: time limit reached"
    assert body["plan"] is None and body["cash"] is None


def test_missing_optimizer_parameters_is_data_invalid(client, data_dir):
    doc = dict(DOC)
    doc.pop("optimizer_parameters")
    (data_dir / "demo_business.json").write_text(json.dumps(doc), encoding="utf-8")
    resp = client.post("/api/optimize", json={"shock": {}, "protect_payroll": True})
    assert resp.status_code == 500
    assert resp.json()["code"] == "DATA_INVALID"


def test_missing_business_file_is_data_unavailable(client, data_dir):
    (data_dir / "demo_business.json").unlink()
    resp = client.post("/api/optimize", json={"shock": {}, "protect_payroll": True})
    assert resp.status_code == 503
    assert resp.json()["code"] == "DATA_UNAVAILABLE"
