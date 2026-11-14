"""GET /api/decision/frames and POST /api/decision (issue #55; MATH_MODEL §8).

core.decision.evaluate_policies is the oracle: the route must return exactly its V(a,1), V(a,0), E[V | a],
feasibility and recommendation, plus the break-even p* between the top two policies, and pass the frame's
forecast_sensitive / caveat / not_modelled_note through verbatim. The business is SYNTHETIC, the frames ILLUSTRATIVE.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from core.decision import NO_SAFE_POLICY, Policy, evaluate_policies
from core.financials import ActionPlan, BusinessParams, ScenarioShock
from main import create_app

REAL_DATA = Path(__file__).resolve().parent.parent / "data"
FRAMES_DOC = json.loads((REAL_DATA / "decision_frames.json").read_text(encoding="utf-8"))
FRAMES = {f["id"]: f for f in FRAMES_DOC["frames"]}
BUSINESS = BusinessParams.model_validate(
    json.loads((REAL_DATA / "demo_business.json").read_text(encoding="utf-8"))["business"]
)
# Hand-derived in test_decision_frames.py: ACT (backup supplier) vs WAIT, 2,000 / 16,320.
SUPPLY_P_STAR = 2_000 / 16_320


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    d = tmp_path / "data"
    d.mkdir()
    for name in ("demo_business.json", "decision_frames.json"):
        shutil.copy(REAL_DATA / name, d / name)
    monkeypatch.setenv("FAULTLINE_DATA_DIR", str(d))
    return d


@pytest.fixture
def client(data_dir):
    return TestClient(create_app())


def _engine(frame: dict, p: float, protect: bool | None = None):
    pols = [Policy(name=x["name"], description=x["summary"], plan=ActionPlan.model_validate(x["plan"]))
            for x in frame["policies"]]
    return evaluate_policies(
        BUSINESS,
        ScenarioShock.model_validate(frame["shock_if_yes"]),
        ScenarioShock.model_validate(frame["shock_if_no"]),
        pols, p, protect_payroll=frame["protect_payroll"] if protect is None else protect,
    )


def test_frames_lists_every_frame_with_verbatim_fields(client):
    r = client.get("/api/decision/frames")
    assert r.status_code == 200
    body = r.json()
    assert body["provenance"] == "ILLUSTRATIVE" and body["business_provenance"] == "SYNTHETIC"
    assert [f["id"] for f in body["frames"]] == list(FRAMES)
    for f in body["frames"]:
        src = FRAMES[f["id"]]
        for key in ("forecast_sensitive", "question_template", "yes_means", "no_means", "protect_payroll"):
            assert f[key] == src[key]
        for key in ("caveat", "not_modelled_note", "no_state_models"):
            assert f[key] == src.get(key)
        assert [p["name"] for p in f["policies"]] == ["ACT", "WAIT", "HEDGE"]
        assert all(p["fees"] for p in f["policies"])
        assert "plan" not in f["policies"][0]


@pytest.mark.parametrize("frame_id", list(FRAMES))
@pytest.mark.parametrize("p", [0.0, 0.3, 0.5, 1.0])
def test_decision_matches_the_engine_exactly(client, frame_id, p):
    r = client.post("/api/decision", json={"frame_id": frame_id, "p_yes": p})
    assert r.status_code == 200, r.text
    body = r.json()
    expect = _engine(FRAMES[frame_id], p)
    assert body["provenance"] == "SIMULATED"
    assert body["business_provenance"] == "SYNTHETIC" and body["frame_provenance"] == "ILLUSTRATIVE"
    assert body["p_yes"] == p and body["protect_payroll"] is FRAMES[frame_id]["protect_payroll"]
    assert body["recommendation"] == expect.recommendation
    for got, ev in zip(body["policies"], expect.policies, strict=True):
        assert got["name"] == ev.policy.name
        assert got["value_if_yes"] == ev.value_if_yes
        assert got["value_if_no"] == ev.value_if_no
        assert got["expected_value"] == ev.expected_value
        assert got["feasible_in_both"] is ev.feasible_in_both
        assert got["breaches_if_yes"] == ev.if_yes.violations and got["breaches_if_no"] == ev.if_no.violations
    frame = FRAMES[frame_id]
    assert body["forecast_sensitive"] is frame["forecast_sensitive"]
    assert body["caveat"] == frame.get("caveat")
    assert body["not_modelled_note"] == frame.get("not_modelled_note")


def test_supply_disruption_break_even_is_the_hand_checked_p_star(client):
    body = client.post("/api/decision", json={"frame_id": "supply-disruption", "p_yes": 0.5}).json()
    be = body["break_even"]
    assert be["status"] == "AVAILABLE" and be["policies"] == ["ACT", "WAIT"]
    assert be["p_star"] == pytest.approx(SUPPLY_P_STAR, abs=1e-9)
    assert body["recommendation"] == "ACT"


def test_break_even_flips_the_recommendation(client):
    """Either side of p* the top policy changes: the frame really is forecast-sensitive."""
    below = client.post("/api/decision", json={"frame_id": "supply-disruption", "p_yes": SUPPLY_P_STAR - 0.01}).json()
    above = client.post("/api/decision", json={"frame_id": "supply-disruption", "p_yes": SUPPLY_P_STAR + 0.01}).json()
    assert below["recommendation"] == "WAIT" and above["recommendation"] == "ACT"


@pytest.mark.parametrize("frame_id", [f for f, v in FRAMES.items() if not v["forecast_sensitive"]])
def test_forecast_insensitive_frames_have_no_break_even(client, frame_id):
    body = client.post("/api/decision", json={"frame_id": frame_id, "p_yes": 0.5}).json()
    assert body["break_even"]["status"] == "NOT AVAILABLE" and body["break_even"]["p_star"] is None
    assert body["break_even"]["note"].startswith("NOT AVAILABLE")
    assert body["caveat"] == FRAMES[frame_id]["caveat"]


def test_no_safe_policy_when_nothing_is_feasible_in_both(client, data_dir):
    doc = json.loads((data_dir / "decision_frames.json").read_text(encoding="utf-8"))
    frame = doc["frames"][0]
    for pol in frame["policies"]:  # cut payroll in every policy while protect-payroll is on
        pol["plan"] = {"payroll_cut": 0.1}
    (data_dir / "decision_frames.json").write_text(json.dumps(doc), encoding="utf-8")
    body = client.post("/api/decision", json={"frame_id": frame["id"], "p_yes": 0.5, "protect_payroll": True}).json()
    assert body["recommendation"] == NO_SAFE_POLICY
    assert all(not p["feasible_in_both"] and p["breaches_if_yes"] for p in body["policies"])
    assert body["break_even"]["status"] == "NOT AVAILABLE"


def test_protect_payroll_override_is_passed_to_the_engine(client):
    body = client.post("/api/decision", json={"frame_id": "fomc-rate-decision", "p_yes": 0.5,
                                              "protect_payroll": False}).json()
    assert body["protect_payroll"] is False
    assert not any("protect payroll" in c for c in body["constraints_checked"])


@pytest.mark.parametrize("payload", [
    {"frame_id": "fomc-rate-decision", "p_yes": 1.5},
    {"frame_id": "fomc-rate-decision", "p_yes": -0.1},
    {"frame_id": "fomc-rate-decision"},
    {"frame_id": "fomc-rate-decision", "p_yes": 0.5, "extra": 1},
    {"frame_id": "no-such-frame", "p_yes": 0.5},
])
def test_bad_requests_are_coded_422(client, payload):
    r = client.post("/api/decision", json=payload)
    assert r.status_code == 422
    assert r.json()["code"] == "VALIDATION_ERROR"


def test_missing_frames_file_is_503(client, data_dir):
    (data_dir / "decision_frames.json").unlink()
    for r in (client.get("/api/decision/frames"),
              client.post("/api/decision", json={"frame_id": "fomc-rate-decision", "p_yes": 0.5})):
        assert r.status_code == 503 and r.json()["code"] == "DATA_UNAVAILABLE"
