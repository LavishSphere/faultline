"""POST /api/simulate: fixed response contract, numbers straight from core.financials, coded errors.

The engine itself is golden-tested in test_financials.py; here the engine is the oracle and the
route must return exactly what simulate() / cascade_deltas() produce for the demo business.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from core.financials import ActionPlan, BusinessParams, ScenarioShock, cascade_deltas, simulate
from main import create_app

REAL_DATA = Path(__file__).resolve().parent.parent / "data"
CONTRACT_KEYS = {
    "provenance", "business_provenance", "baseline", "result", "deltas",
    "min_cash_floor", "first_week_below_floor", "weeks_below_floor",
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


@pytest.fixture
def params() -> BusinessParams:
    payload = json.loads((REAL_DATA / "demo_business.json").read_text(encoding="utf-8"))
    return BusinessParams.model_validate(payload["business"])


def _engine(params: BusinessParams, shock: dict, plan: dict | None = None) -> dict:
    base = simulate(params, ScenarioShock(), ActionPlan())
    res = simulate(params, ScenarioShock.model_validate(shock), ActionPlan.model_validate(plan or {}))
    return {
        "baseline": base.model_dump(mode="json"),
        "result": res.model_dump(mode="json"),
        "deltas": cascade_deltas(base, res).model_dump(mode="json"),
    }


DEMAND_WEEK_2 = {"name": "demand -20% week 2", "demand": {"delta": 0.2, "start_week": 2, "end_week": 2}}


# --------------------------------------------------------------------------- contract


def test_baseline_request_has_exact_contract_keys_and_labels(client):
    resp = client.post("/api/simulate", json={"shock": {}})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body) == CONTRACT_KEYS
    assert body["provenance"] == "SIMULATED"
    assert body["business_provenance"] == "SYNTHETIC"
    assert body["baseline"]["provenance"] == "SIMULATED"
    assert body["result"]["provenance"] == "SIMULATED"
    assert body["deltas"]["provenance"] == "SIMULATED"
    # No shock and no plan: the result IS the baseline and every delta is exactly zero.
    assert body["result"]["cash"] == body["baseline"]["cash"]
    assert all(d == 0.0 for node in body["deltas"]["nodes"].values() for d in node["per_week"])
    assert set(body["deltas"]["nodes"]) == {
        "Demand", "Sales", "Receipts", "Supplier", "Inventory", "Purchases",
        "Payables", "Rate", "Interest", "Payroll", "Revolver", "Cash",
    }


def test_result_and_deltas_equal_the_engine_exactly(client, params):
    body = client.post("/api/simulate", json={"shock": DEMAND_WEEK_2}).json()
    expected = _engine(params, DEMAND_WEEK_2)
    assert body["baseline"] == expected["baseline"]
    assert body["result"] == expected["result"]
    assert body["deltas"] == expected["deltas"]
    # Hand check on the demo business (base sales 18k + 17k + 15k = 50,000 per week).
    assert body["result"]["sales"][1] == 40000.0
    assert body["deltas"]["nodes"]["Sales"]["per_week"][1] == -10000.0
    assert body["deltas"]["min_cash_delta"] < 0


def test_plan_is_applied(client, params):
    shock = {"name": "outage", "supplier": {"availability": 0.0, "dependent_share": 0.4}}
    without = client.post("/api/simulate", json={"shock": shock}).json()
    with_backup = client.post("/api/simulate", json={"shock": shock, "plan": {"use_backup_supplier": True}}).json()
    assert max(without["result"]["lost_sales"]) > 0
    assert max(with_backup["result"]["lost_sales"]) == 0.0
    assert with_backup["result"] == _engine(params, shock, {"use_backup_supplier": True})["result"]


def _without_names(body: dict) -> dict:
    out = json.loads(json.dumps(body))
    out["result"].pop("scenario_name")
    out["deltas"].pop("scenario_name")
    return out


def test_scenario_id_does_not_change_numbers(client):
    unnamed = {k: v for k, v in DEMAND_WEEK_2.items() if k != "name"}
    a = client.post("/api/simulate", json={"shock": unnamed}).json()
    b = client.post("/api/simulate", json={"scenario_id": "demand-dip", "shock": unnamed}).json()
    assert _without_names(a) == _without_names(b)


@pytest.mark.parametrize(
    "req, expected",
    [
        ({"shock": {"rate": {"delta_rate": 0.02, "start_week": 3}}}, "custom"),
        ({"shock": {}}, "custom"),
        ({"shock": {"name": "baseline", "rate": {"delta_rate": 0.02, "start_week": 3}}}, "custom"),
        ({"scenario_id": "rate-up", "shock": {"rate": {"delta_rate": 0.02, "start_week": 3}}}, "rate-up"),
        ({"scenario_id": "rate-up", "shock": {"name": "My rate shock"}}, "My rate shock"),
    ],
)
def test_result_is_never_labeled_baseline(client, req, expected):
    body = client.post("/api/simulate", json=req).json()
    assert body["baseline"]["scenario_name"] == "baseline"
    assert body["deltas"]["baseline_name"] == "baseline"
    assert body["result"]["scenario_name"] == expected
    assert body["deltas"]["scenario_name"] == expected


def test_deterministic(client):
    req = {"shock": {"rate": {"delta_rate": 0.02, "start_week": 3}}, "plan": {"revolver_draw": 1000.0}}
    assert client.post("/api/simulate", json=req).json() == client.post("/api/simulate", json=req).json()


# --------------------------------------------------------------------------- errors


def _assert_coded(resp, status: int, code: str) -> dict:
    assert resp.status_code == status, resp.text
    body = resp.json()
    assert body["code"] == code
    assert isinstance(body["message"], str) and body["message"]
    return body


def _locs(body: dict) -> list[list]:
    return [e["loc"] for e in body["errors"]]


def test_missing_shock_is_coded_422(client):
    body = _assert_coded(client.post("/api/simulate", json={}), 422, "VALIDATION_ERROR")
    assert ["body", "shock"] in _locs(body)


@pytest.mark.parametrize(
    "req, loc_head",
    [
        ({"shock": {"demand": {"delta": 1.5, "start_week": 1, "end_week": 2}}}, ["body", "shock", "demand"]),
        ({"shock": {"demand": {"delta": 0.1, "start_week": 4, "end_week": 2}}}, ["body", "shock", "demand"]),
        ({"shock": {"unknown_field": 1}}, ["body", "shock"]),
        ({"shock": {}, "plan": {"payroll_cut": 2.0}}, ["body", "plan"]),
        ({"shock": {}, "extra": True}, ["body"]),
        ({"shock": {}, "scenario_id": "has spaces"}, ["body", "scenario_id"]),
    ],
)
def test_schema_violations_are_coded_422(client, req, loc_head):
    body = _assert_coded(client.post("/api/simulate", json=req), 422, "VALIDATION_ERROR")
    assert any(loc[: len(loc_head)] == loc_head for loc in _locs(body)), _locs(body)


def test_nan_is_rejected(client):
    raw = '{"shock": {"rate": {"delta_rate": NaN, "start_week": 1}}}'
    resp = client.post("/api/simulate", content=raw, headers={"Content-Type": "application/json"})
    _assert_coded(resp, 422, "VALIDATION_ERROR")


@pytest.mark.parametrize(
    "req, loc",
    [
        ({"shock": {}, "plan": {"purchase_cut": [1.0, 2.0]}}, ["body", "plan", "purchase_cut"]),
        ({"shock": {"supplier": {"availability": [0.5] * 3, "dependent_share": 0.4}}},
         ["body", "shock", "supplier", "availability"]),
    ],
)
def test_weekly_series_must_match_the_horizon(client, req, loc):
    body = _assert_coded(client.post("/api/simulate", json=req), 422, "VALIDATION_ERROR")
    assert loc in _locs(body)
    assert "26" in body["errors"][0]["msg"]


def test_impossible_financing_is_infeasible_input(client):
    # Demo business starts with an undrawn revolver (B_0 = 0): repaying 1,000 in week 1 cannot happen.
    resp = client.post("/api/simulate", json={"shock": {}, "plan": {"revolver_repay": 1000.0}})
    body = _assert_coded(resp, 422, "INFEASIBLE_INPUT")
    assert "revolver" in body["message"]


@pytest.mark.parametrize(
    "req",
    [
        {"shock": {}, "plan": {"revolver_draw": 1e308}},
        {"shock": {"rate": {"delta_rate": 1e306, "start_week": 1}}},
    ],
)
def test_numeric_overflow_is_short_validation_error_without_echo(client, req):
    resp = client.post("/api/simulate", json=req)
    body = _assert_coded(resp, 422, "VALIDATION_ERROR")
    assert "numeric range" in body["message"]
    assert len(resp.content) < 500
    assert "inf" not in resp.text.lower()


def test_purchase_cut_larger_than_purchases_is_infeasible(client):
    resp = client.post("/api/simulate", json={"shock": {}, "plan": {"purchase_cut": 100000.0}})
    body = _assert_coded(resp, 422, "INFEASIBLE_INPUT")
    assert "week 1" in body["message"] and "purchases cannot be negative" in body["message"]


def test_cumulative_purchase_cuts_cannot_make_inventory_negative(client):
    # Demo business: I_0 = 65,000, I_t = I_(t-1) - v_t; purchases P_t = 0.65 S_t - v_t, where S_t = 50,000 minus the
    # stock-out lost sales 0.20 x (65,000 - I_t) (issue #103). A 20,000 cut in weeks 1-4 keeps purchases >= 0
    # (P_1..P_4 = 9,900, 7,300, 4,700, 2,100) but inventory reaches 65,000 - 4 x 20,000 = -15,000 < 0 in week 4.
    cuts = [20000.0] * 4 + [0.0] * 22
    resp = client.post("/api/simulate", json={"shock": {}, "plan": {"purchase_cut": cuts}})
    body = _assert_coded(resp, 422, "INFEASIBLE_INPUT")
    assert "week 4" in body["message"] and "inventory cannot be negative" in body["message"]


def test_feasible_purchase_cut_is_accepted(client):
    cuts = [5000.0] + [0.0] * 25
    resp = client.post("/api/simulate", json={"shock": {}, "plan": {"purchase_cut": cuts}})
    assert resp.status_code == 200, resp.text
    assert resp.json()["result"]["inventory"][0] == 60000.0


def test_missing_business_file_is_data_unavailable(client, data_dir):
    (data_dir / "demo_business.json").unlink()
    body = _assert_coded(client.post("/api/simulate", json={"shock": {}}), 503, "DATA_UNAVAILABLE")
    assert "NOT AVAILABLE" in body["message"]


@pytest.mark.parametrize(
    "content",
    [
        "{not json",
        json.dumps({"provenance": "SYNTHETIC"}),
        json.dumps({"business": {"cash_0": 1.0}}),
        json.dumps({"business": "nope"}),
    ],
)
def test_invalid_business_file_is_data_invalid(client, data_dir, content):
    (data_dir / "demo_business.json").write_text(content, encoding="utf-8")
    body = _assert_coded(client.post("/api/simulate", json={"shock": {}}), 500, "DATA_INVALID")
    assert str(data_dir) not in json.dumps(body)  # never leak absolute paths


# --------------------------------------------------------------------------- liquidity floor (MATH_MODEL §4.1, §10)


def _bad_quarter() -> dict:
    payload = json.loads((REAL_DATA / "scenarios.json").read_text(encoding="utf-8"))
    return next(s for s in payload["scenarios"] if s["id"] == "bad-quarter")


def test_baseline_reports_the_floor_and_stays_above_it(client, params):
    body = client.post("/api/simulate", json={"shock": {}}).json()
    assert params.min_cash == 25000.0  # §10 C_min, read from the fixture
    assert body["min_cash_floor"] == params.min_cash
    assert body["first_week_below_floor"] is None
    assert body["weeks_below_floor"] == []


def test_bad_quarter_is_below_the_floor_in_weeks_20_to_26(client, params):
    s = _bad_quarter()
    body = client.post("/api/simulate", json={"scenario_id": s["id"], "shock": s["shock"]}).json()
    assert body["provenance"] == "SIMULATED"
    assert body["min_cash_floor"] == 25000.0
    # Oracle: the engine's own cash path for the same shock, compared with C_min week by week.
    cash = _engine(params, s["shock"])["result"]["cash"]
    expected = [t for t, c in enumerate(cash, start=1) if c < params.min_cash]
    assert expected == list(range(20, 27))  # docs/DEMO_SCRIPT.md: "below our 25,000 floor in week 20"
    assert body["weeks_below_floor"] == expected
    assert body["first_week_below_floor"] == 20
    # Cash never goes negative, so the runway week stays null: the floor is the stricter test.
    assert body["result"]["runway_week"] is None


def test_a_plan_that_holds_the_floor_exactly_is_not_below_it(client):
    s = _bad_quarter()
    opt = client.post(
        "/api/optimize", json={"scenario_id": s["id"], "shock": s["shock"], "protect_payroll": True}
    ).json()
    assert opt["status"] == "OPTIMAL"
    assert opt["min_cash"] == pytest.approx(25000.0)  # the floor binds (weeks 20-26)
    body = client.post(
        "/api/simulate", json={"scenario_id": s["id"], "shock": s["shock"], "plan": opt["plan"]}
    ).json()
    assert body["first_week_below_floor"] is None
    assert body["weeks_below_floor"] == []


def test_no_floor_in_the_fixture_reports_null(client, data_dir):
    payload = json.loads((data_dir / "demo_business.json").read_text(encoding="utf-8"))
    payload["business"].pop("min_cash")
    (data_dir / "demo_business.json").write_text(json.dumps(payload), encoding="utf-8")
    body = client.post("/api/simulate", json={"shock": _bad_quarter()["shock"]}).json()
    assert body["min_cash_floor"] is None
    assert body["first_week_below_floor"] is None
    assert body["weeks_below_floor"] == []


def test_business_provenance_follows_the_fixture(client, data_dir):
    payload = json.loads((data_dir / "demo_business.json").read_text(encoding="utf-8"))
    payload["business"]["provenance"] = "ILLUSTRATIVE"
    (data_dir / "demo_business.json").write_text(json.dumps(payload), encoding="utf-8")
    body = client.post("/api/simulate", json={"shock": {}}).json()
    assert body["business_provenance"] == "ILLUSTRATIVE"
    assert body["provenance"] == "SIMULATED"
