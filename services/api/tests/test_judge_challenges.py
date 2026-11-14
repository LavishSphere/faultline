"""Judge's Challenge shocks in data/judge_challenges.json and GET /api/judge-challenges (issue #123).

Every challenge must be a valid ScenarioShock, sized inside the explore_shock_guidance.json ranges of the category it
cites, built from those parameters exactly as the guidance file's mapping_to_scenario_shock says, and runnable by
POST /api/simulate on the demo business. "Surprise me" must be a fixed, complete order (no hidden randomness).
No expected cash figure is written here: the only numbers checked are the guidance ranges themselves.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from core.financials import ScenarioShock
from main import create_app
from tests.test_explore_guidance import BUSINESS, CATEGORIES, PARAMS, T, build_shock

DATA = Path(__file__).resolve().parent.parent / "data"
DOC = json.loads((DATA / "judge_challenges.json").read_text(encoding="utf-8"))
CHALLENGES = {c["id"]: c for c in DOC["challenges"]}


def test_file_is_labeled_illustrative_and_well_formed():
    assert DOC["provenance"] == "ILLUSTRATIVE"
    assert "ILLUSTRATIVE" in DOC["label"] and "not forecasts" in DOC["label"]
    assert DOC["guidance_file"] == "explore_shock_guidance.json"
    assert 6 <= len(DOC["challenges"]) <= 10
    assert len(CHALLENGES) == len(DOC["challenges"])  # unique ids
    assert T == BUSINESS.horizon_weeks
    for c in DOC["challenges"]:
        assert c["provenance"] == "ILLUSTRATIVE", c["id"]
        for key in ("name", "description", "range_citation"):
            assert isinstance(c[key], str) and c[key].strip() and "\n" not in c[key], (c["id"], key)


def test_surprise_order_is_a_fixed_permutation_of_every_challenge():
    order = DOC["surprise_order"]
    assert sorted(order) == sorted(CHALLENGES)
    assert len(order) == len(set(order))
    assert "random" not in json.dumps(DOC).lower().replace("no hidden randomness", "")


@pytest.mark.parametrize("challenge_id", list(CHALLENGES))
def test_shock_validates_and_matches_the_guidance_mapping(challenge_id):
    c = CHALLENGES[challenge_id]
    shock = ScenarioShock.model_validate(c["shock"])  # raises on any invalid field
    assert shock.name == c["name"]
    expected = build_shock(c["guidance"]["category"], c["guidance"]["values"])
    assert shock.model_dump(exclude={"name"}) == expected.model_dump(exclude={"name"})


@pytest.mark.parametrize("challenge_id", list(CHALLENGES))
def test_every_parameter_is_inside_the_cited_guidance_range(challenge_id):
    c = CHALLENGES[challenge_id]
    cat_id = c["guidance"]["category"]
    assert cat_id in CATEGORIES, cat_id
    ranges = CATEGORIES[cat_id]["shocks"]
    values = c["guidance"]["values"]
    assert values and set(values) <= set(ranges), (challenge_id, set(values))
    assert c["range_citation"].startswith(f"explore_shock_guidance.json · {cat_id}:")
    for block, params in values.items():
        assert set(params) == set(PARAMS[block]), (challenge_id, block)  # every parameter of the block
        for p, v in params.items():
            r = ranges[block][p]
            assert r["min"] <= v <= r["max"], (challenge_id, block, p, v, r)
            assert f"{block}.{p} " in c["range_citation"], (challenge_id, block, p)
            if PARAMS[block][p] in {"week", "count", "count0"}:
                assert float(v).is_integer(), (challenge_id, block, p)


@pytest.mark.parametrize("challenge_id", list(CHALLENGES))
def test_every_window_including_recovery_ends_by_week_T(challenge_id):
    shock = ScenarioShock.model_validate(CHALLENGES[challenge_id]["shock"])
    if shock.demand:
        assert shock.demand.end_week + shock.demand.recovery_weeks <= T
    if shock.supplier:
        assert isinstance(shock.supplier.availability, list) and len(shock.supplier.availability) == T


# --------------------------------------------------------------------------- route


@pytest.fixture
def client():
    return TestClient(create_app())


def test_route_serves_every_challenge_and_each_one_simulates(client):
    body = client.get("/api/judge-challenges").json()
    assert body["status"] == "AVAILABLE" and body["provenance"] == "ILLUSTRATIVE"
    assert [c["id"] for c in body["items"]] == [c["id"] for c in DOC["challenges"]]
    assert body["surprise_order"] == DOC["surprise_order"]
    for item in body["items"]:
        assert item["shock"]["name"] == item["name"]
        resp = client.post("/api/simulate", json={"scenario_id": item["id"], "shock": item["shock"]})
        assert resp.status_code == 200, (item["id"], resp.text)
        assert resp.json()["provenance"] == "SIMULATED"
        assert resp.json()["result"]["scenario_name"] == item["name"]


def test_missing_file_is_not_available(tmp_path, monkeypatch):
    d = tmp_path / "data"
    d.mkdir()
    shutil.copy(DATA / "demo_business.json", d / "demo_business.json")
    monkeypatch.setenv("FAULTLINE_DATA_DIR", str(d))
    body = TestClient(create_app()).get("/api/judge-challenges").json()
    assert body["status"] == "NOT AVAILABLE" and body["items"] == [] and body["surprise_order"] == []
    assert any("NOT AVAILABLE" in n for n in body["notes"])


def test_incomplete_surprise_order_is_rejected(tmp_path, monkeypatch):
    d = tmp_path / "data"
    d.mkdir()
    shutil.copy(DATA / "demo_business.json", d / "demo_business.json")
    bad = {**DOC, "surprise_order": DOC["surprise_order"][:-1]}
    (d / "judge_challenges.json").write_text(json.dumps(bad), encoding="utf-8")
    monkeypatch.setenv("FAULTLINE_DATA_DIR", str(d))
    resp = TestClient(create_app()).get("/api/judge-challenges")
    assert resp.status_code == 500 and resp.json()["code"] == "DATA_INVALID"
