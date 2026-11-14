"""GET /api/scenarios: lists data/scenarios.json (issue #19) or says NOT AVAILABLE; never invents scenarios."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from main import create_app

REAL_DATA = Path(__file__).resolve().parent.parent / "data"

# Test-only fixture, clearly not real data. Shape = the contract documented in routes/scenarios.py.
FIXTURE = [
    {
        "id": "test-rate-up",
        "name": "TEST FIXTURE: +200bp from week 3",
        "rationale": "Test fixture only.",
        "provenance": "ILLUSTRATIVE",
        "shock": {"name": "test-rate-up", "rate": {"delta_rate": 0.02, "start_week": 3}},
    },
    {
        "id": "test-demand-dip",
        "name": "TEST FIXTURE: demand -20% weeks 2-4",
        "rationale": "Test fixture only.",
        "provenance": "SYNTHETIC",
        "shock": {"name": "test-demand-dip", "demand": {"delta": 0.2, "start_week": 2, "end_week": 4}},
    },
]


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


def _write(data_dir: Path, payload) -> None:
    text = payload if isinstance(payload, str) else json.dumps(payload)
    (data_dir / "scenarios.json").write_text(text, encoding="utf-8")


def test_missing_file_is_empty_and_not_available(client):
    resp = client.get("/api/scenarios")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "NOT AVAILABLE"
    assert body["items"] == []
    assert any("NOT AVAILABLE" in n for n in body["notes"])


@pytest.mark.parametrize("wrap", [False, True])
def test_lists_scenarios_in_file_order(client, data_dir, wrap):
    _write(data_dir, {"provenance": "SYNTHETIC", "scenarios": FIXTURE} if wrap else FIXTURE)
    body = client.get("/api/scenarios").json()
    assert body["status"] == "AVAILABLE"
    assert [s["id"] for s in body["items"]] == ["test-rate-up", "test-demand-dip"]
    assert body["items"][0]["provenance"] == "ILLUSTRATIVE"
    assert body["items"][1]["shock"]["demand"] == {"delta": 0.2, "start_week": 2, "end_week": 4, "recovery_weeks": 0}


def test_listed_shock_round_trips_into_simulate(client, data_dir):
    _write(data_dir, FIXTURE)
    scenario = client.get("/api/scenarios").json()["items"][1]
    resp = client.post("/api/simulate", json={"scenario_id": scenario["id"], "shock": scenario["shock"]})
    assert resp.status_code == 200, resp.text
    assert resp.json()["result"]["scenario_name"] == "TEST FIXTURE: demand -20% weeks 2-4"


def test_listed_shock_carries_the_catalog_name(client, data_dir):
    unnamed = [{**s, "shock": {k: v for k, v in s["shock"].items() if k != "name"}} for s in FIXTURE]
    _write(data_dir, unnamed)
    items = client.get("/api/scenarios").json()["items"]
    assert [s["shock"]["name"] for s in items] == [s["name"] for s in FIXTURE]


def test_series_length_must_match_business_horizon(client, data_dir):
    bad = {**FIXTURE[0], "shock": {"supplier": {"availability": [0.5] * 3, "dependent_share": 0.4}}}
    _write(data_dir, [bad])
    resp = client.get("/api/scenarios")
    assert resp.status_code == 500
    body = resp.json()
    assert body["code"] == "DATA_INVALID"
    assert ["scenarios.json", 0, "shock", "supplier", "availability"] in [e["loc"] for e in body["errors"]]


def test_listing_works_without_business_file(client, data_dir):
    (data_dir / "demo_business.json").unlink()
    _write(data_dir, FIXTURE)
    assert client.get("/api/scenarios").json()["status"] == "AVAILABLE"


def test_empty_file_list_is_not_available(client, data_dir):
    _write(data_dir, [])
    body = client.get("/api/scenarios").json()
    assert body["status"] == "NOT AVAILABLE"
    assert body["items"] == []


@pytest.mark.parametrize(
    "payload",
    [
        "{broken",
        {"scenarios": "nope"},
        42,
        [{**FIXTURE[0], "provenance": "REAL_HISTORICAL"}],  # scenarios for a fictional business cannot be real
        [{**FIXTURE[0], "shock": {"demand": {"delta": 3}}}],
        [{k: v for k, v in FIXTURE[0].items() if k != "rationale"}],
        [FIXTURE[0], FIXTURE[0]],  # duplicate id
    ],
)
def test_invalid_file_is_data_invalid(client, data_dir, payload):
    _write(data_dir, payload)
    resp = client.get("/api/scenarios")
    assert resp.status_code == 500
    body = resp.json()
    assert body["code"] == "DATA_INVALID"
    assert "scenarios.json" in body["message"]
    assert str(data_dir) not in resp.text


@pytest.mark.skipif(not (REAL_DATA / "scenarios.json").exists(), reason="data/scenarios.json not merged yet (#19)")
def test_real_scenarios_file_lists_and_every_scenario_simulates(monkeypatch):
    monkeypatch.setenv("FAULTLINE_DATA_DIR", str(REAL_DATA))
    client = TestClient(create_app())
    body = client.get("/api/scenarios").json()
    assert body["status"] == "AVAILABLE"
    assert body["items"]
    for s in body["items"]:
        resp = client.post("/api/simulate", json={"scenario_id": s["id"], "shock": s["shock"]})
        assert resp.status_code == 200, (s["id"], resp.text)
