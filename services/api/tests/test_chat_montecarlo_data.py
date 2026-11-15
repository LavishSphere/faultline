"""#209: Monte Carlo chat tools, the figure check on probabilities, and the SYNTHETIC mock internal data room.

The Monte Carlo engine (PR #208) is replaced by a contract-shaped fake through the adapter's one seam
(``chat_montecarlo._engine_routes``), so these tests run whether or not that PR is on this branch. When the real
engine is importable, ``test_real_engine_round_trip`` also runs it end to end.
"""

from __future__ import annotations

import asyncio
import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from test_explore_chat import (
    ANTHROPIC_KEY,
    OPENROUTER_KEY,
    OPENROUTER_MODELS,
    FakeProvider,
    Harness,
    oa_text,
    oa_tool_calls,
    tool_results_in,
)

from agents import explore_chat as chat
from config import get_settings
from main import create_app
from routes import chat_montecarlo as mc
from routes import explore_chat as chat_routes
from routes import internal_data

REPO = Path(__file__).resolve().parents[3]

# ----------------------------------------------------------------------------- a contract-shaped fake engine

FAKE_DECISION: dict[str, Any] = {
    "provenance": "SIMULATED", "label": "SIMULATED: Monte Carlo over model-chosen inputs", "n_paths": 20000,
    "seed": 20261115, "input_sha256": "ab" * 32, "runtime_ms": 12.5,
    "options": [
        {"id": "keep", "label": "Keep the CEO", "mean": 41.2, "sd": 30.1, "p5": -8.4, "p25": 20.0, "p50": 40.3,
         "p75": 61.0, "p95": 92.7, "prob_below_zero": 0.083, "prob_best": 0.783, "prob_best_ci95": [0.777, 0.789],
         "expected_shortfall_5": -21.6,
         "histogram": {"bin_edges": [-20.0, 0.85, 120.0], "counts": [85, 19915]}},
        {"id": "replace", "label": "Replace the CEO", "mean": 12.5, "sd": 25.0, "p5": -30.2, "p25": -3.0,
         "p50": 11.9, "p75": 28.0, "p95": 55.4, "prob_below_zero": 0.31, "prob_best": 0.217,
         "prob_best_ci95": [0.211, 0.223], "expected_shortfall_5": -412.0,
         "histogram": {"bin_edges": [-60.0, 0.85, 80.0], "counts": [85, 19915]}},
    ],
    "pairwise": [{"a": "keep", "b": "replace", "prob_a_better": 0.783, "ci95": [0.777, 0.789]}],
    "best": {"id": "keep", "prob_best": 0.783, "ci95": [0.777, 0.789]},
    "sensitivity": [
        {"option_id": "keep", "driver": "small", "low_p50": 39.0, "high_p50": 42.0, "swing": 3.0},
        {"option_id": "keep", "driver": "execution", "low_p50": 25.1, "high_p50": 55.6, "swing": 30.5},
        {"option_id": "replace", "driver": "transition", "low_p50": 1.2, "high_p50": 22.4, "swing": 21.2},
        {"option_id": "replace", "driver": "tiny", "low_p50": 11.0, "high_p50": 12.0, "swing": 1.0},
    ],
    "assumptions": [],
}
FAKE_CASH: dict[str, Any] = {
    "provenance": "SIMULATED", "synthetic": True, "label": "SIMULATED", "n_paths": 10000, "seed": 20261115,
    "input_sha256": "cd" * 32, "floor": 25000.0,
    "no_plan": {"bands": {"p5": [1.0] * 26, "p50": [2.0] * 26, "p95": [3.0] * 26},
                "prob_below_floor_any": 0.612, "prob_below_floor_ci95": [0.602, 0.621], "prob_negative_any": 0.21,
                "prob_below_floor_by_week": [0.0] * 26, "min_cash": {"p5": -4100.0, "p50": 12000.0, "p95": 30500.0}},
    "with_plan": {"bands": {"p5": [1.0] * 26, "p50": [2.0] * 26, "p95": [3.0] * 26},
                  "prob_below_floor_any": 0.044, "prob_below_floor_ci95": [0.04, 0.048], "prob_negative_any": 0.0,
                  "prob_below_floor_by_week": [0.0] * 26, "min_cash": {"p5": 24000.0, "p50": 31000.0, "p95": 40000.0}},
    "plan": {"status": "OPTIMAL", "actions": [], "central_min_cash": 25000.0, "diagnostic": None},
    "assumptions": [],
}


class _PassThrough:
    @staticmethod
    def model_validate(body: dict[str, Any]) -> dict[str, Any]:
        return body


def fake_engine(decision: dict[str, Any] | None = None, cash: dict[str, Any] | None = None, seen: list | None = None):
    seen = seen if seen is not None else []

    def decision_montecarlo(body: dict[str, Any]) -> dict[str, Any]:
        seen.append(("decision", body))
        return copy.deepcopy(decision or FAKE_DECISION)

    async def cash_montecarlo(body: dict[str, Any], _settings: Any) -> dict[str, Any]:
        seen.append(("cash", body))
        return copy.deepcopy(cash or FAKE_CASH)

    return SimpleNamespace(DecisionRequest=_PassThrough, CashRequest=_PassThrough,
                           decision_montecarlo=decision_montecarlo, cash_montecarlo=cash_montecarlo)


@pytest.fixture
def env(monkeypatch):
    for name in ("FAULTLINE_MODE", "FAULTLINE_ADMIN_TOKEN", "FAULTLINE_PUBLIC_CHAT", "FAULTLINE_CHAT_MODELS",
                 "FAULTLINE_CHAT_PER_IP", "FAULTLINE_CHAT_CONCURRENCY", "FAULTLINE_CHAT_MAX_PRICE_PER_MTOK",
                 "TAVILY_API_KEY", "OPENAI_API_KEY", "FAULTLINE_RATE_LIMIT_PER_MIN"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", OPENROUTER_KEY)
    monkeypatch.setenv("ANTHROPIC_API_KEY", ANTHROPIC_KEY)
    return monkeypatch


@pytest.fixture
def engine(monkeypatch):
    seen: list = []
    monkeypatch.setattr(mc, "_engine_routes", lambda: fake_engine(seen=seen))
    return seen


def _driver(name: str, low: float, mode: float, high: float, **extra: Any) -> dict[str, Any]:
    d = {"name": name, "kind": "value", "distribution": "triangular",
         "params": {"low": low, "mode": mode, "high": high, "mean": None, "sd": None, "median": None, "p90": None},
         "probability": None, "source": None}
    d.update(extra)
    return d


DECISION_ARGS: dict[str, Any] = {
    "question": "Should the company keep its CEO?",
    "metric": {"name": "5-year shareholder value change", "unit": "$B", "higher_is_better": True},
    "options": [
        {"id": "keep", "label": "Keep the CEO", "drivers": [
            _driver("execution", -10.0, 40.0, 90.0,
                    source={"url": "https://news.example.com/a", "title": "A story", "note": None}),
            {"name": "key-person event", "kind": "event", "distribution": "uniform",
             "params": {"low": -40.0, "high": -10.0, "mode": None, "mean": None, "sd": None, "median": None,
                        "p90": None},
             "probability": 0.05, "source": None}]},
        {"id": "replace", "label": "Replace the CEO", "drivers": [_driver("transition", -50.0, 10.0, 60.0)]},
    ],
    "n_paths": None,
    "seed": None,
}


def _box() -> chat_routes.EngineToolBox:
    return chat_routes.EngineToolBox(get_settings(), None)


# ----------------------------------------------------------------------------- tool schemas


def _walk(schema: Any, path: str = "$"):
    if isinstance(schema, dict):
        yield path, schema
        for k, v in schema.items():
            yield from _walk(v, f"{path}.{k}")
    elif isinstance(schema, list):
        for i, v in enumerate(schema):
            yield from _walk(v, f"{path}[{i}]")


@pytest.mark.parametrize("name", ["monte_carlo_decision", "monte_carlo_cash", "query_internal_data"])
def test_new_tool_schemas_are_strict_ready(name):
    spec = next(s for s in _box().specs() if s.name == name)
    for path, node in _walk(spec.parameters):
        if "properties" in node:
            assert node.get("additionalProperties") is False, path
            assert sorted(node["required"]) == sorted(node["properties"]), path
        # Anthropic strict tools do not support numeric / string-length constraints: Pydantic enforces them.
        assert not {"minimum", "maximum", "minLength", "maxLength", "minItems", "maxItems", "pattern"} & set(node), path


def test_cash_tool_lists_the_named_scenarios_and_reuses_the_shock_schema():
    spec = next(s for s in _box().specs() if s.name == "monte_carlo_cash")
    sid = spec.parameters["properties"]["scenario_id"]
    assert "bad-quarter" in sid["anyOf"][0]["enum"]
    assert spec.parameters["properties"]["shock"] == chat_routes.SHOCK_SCHEMA


# ----------------------------------------------------------------------------- strict validation (tool errors)


@pytest.mark.parametrize("mutate, needle", [
    (lambda a: a["options"].pop(), "options"),  # one option
    (lambda a: a["options"][1].update(id="keep"), "unique"),
    (lambda a: a["options"][0]["drivers"][0]["params"].update(mean=3.0), "triangular needs exactly"),
    (lambda a: a["options"][0]["drivers"][0]["params"].update(low=95.0), "low <= mode <= high"),
    (lambda a: a["options"][0]["drivers"][1].update(probability=None), "probability"),
    (lambda a: a["options"][0]["drivers"][0].update(probability=0.5), "probability null"),
    (lambda a: a.update(n_paths=10), "n_paths"),
    (lambda a: a.update(extra=1), "extra"),
    (lambda a: a["options"][0]["drivers"][0].update(source={"url": "ftp://x", "title": "t", "note": None}), "url"),
])
def test_bad_decision_input_is_a_tool_error_and_the_engine_never_runs(engine, mutate, needle):
    args = copy.deepcopy(DECISION_ARGS)
    mutate(args)
    out = asyncio.run(_box().run("monte_carlo_decision", args))
    assert out.status == "error" and engine == []
    assert needle in json.dumps(out.summary), out.summary
    assert "monte_carlo" not in out.summary


def test_decision_body_sends_only_the_chosen_distribution_params_and_contract_defaults(engine):
    out = asyncio.run(_box().run("monte_carlo_decision", copy.deepcopy(DECISION_ARGS)))
    assert out.status == "ok", out.summary
    (_, body), = engine
    assert body["n_paths"] == 20000 and body["seed"] == 20261115
    keep = body["options"][0]["drivers"]
    assert keep[0]["params"] == {"low": -10.0, "mode": 40.0, "high": 90.0} and "probability" not in keep[0]
    assert keep[1]["params"] == {"low": -40.0, "high": -10.0} and keep[1]["probability"] == 0.05
    assert out.input == body  # re-POSTable to /api/montecarlo/decision


# ----------------------------------------------------------------------------- the adapter


def test_engine_missing_is_a_not_available_tool_error(monkeypatch):
    def missing():
        raise mc.EngineUnavailable

    monkeypatch.setattr(mc, "_engine_routes", missing)
    for name, args in (("monte_carlo_decision", copy.deepcopy(DECISION_ARGS)),
                       ("monte_carlo_cash", {"scenario_id": "bad-quarter", "shock": None, "protect_payroll": True,
                                             "with_plan": True, "n_paths": None, "seed": None})):
        out = asyncio.run(_box().run(name, args))
        assert out.status == "error" and "NOT AVAILABLE" in out.summary["error"]


def test_engine_shape_drift_is_a_tool_error_not_numbers(monkeypatch):
    broken = {k: v for k, v in FAKE_DECISION.items() if k != "best"}
    monkeypatch.setattr(mc, "_engine_routes", lambda: fake_engine(decision=broken))
    out = asyncio.run(_box().run("monte_carlo_decision", copy.deepcopy(DECISION_ARGS)))
    assert out.status == "error" and "unexpected result" in out.summary["error"]
    unlabelled = {**FAKE_DECISION, "provenance": "LIVE"}
    monkeypatch.setattr(mc, "_engine_routes", lambda: fake_engine(decision=unlabelled))
    assert asyncio.run(_box().run("monte_carlo_decision", copy.deepcopy(DECISION_ARGS))).status == "error"


def test_engine_route_error_comes_back_as_a_coded_tool_error(monkeypatch):
    from models import ErrorCode
    from routes import RouteError

    def refuse(_body):
        raise RouteError(ErrorCode.VALIDATION_ERROR, "Monte Carlo inputs out of range: too big.")

    fake = fake_engine()
    fake.decision_montecarlo = refuse
    monkeypatch.setattr(mc, "_engine_routes", lambda: fake)
    out = asyncio.run(_box().run("monte_carlo_decision", copy.deepcopy(DECISION_ARGS)))
    assert out.status == "error" and out.summary["code"] == "VALIDATION_ERROR"


def test_decision_summary_is_compact_and_the_full_result_is_kept_for_the_ui(engine):
    out = asyncio.run(_box().run("monte_carlo_decision", copy.deepcopy(DECISION_ARGS)))
    s = out.summary
    assert out.provenance == "SIMULATED" and s["monte_carlo"] == FAKE_DECISION
    assert s["best"] == {"id": "keep", "prob_best": 0.783, "ci95": [0.777, 0.789]}
    assert [o["p50"] for o in s["options"]] == [40.3, 11.9] and "histogram" not in s["options"][0]
    assert [r["driver"] for r in s["top_sensitivity"]] == ["execution", "transition", "small"]  # by |swing|
    assert (s["n_paths"], s["seed"], s["input_sha256"], s["ci_level"]) == (20000, 20261115, "ab" * 32, 0.95)
    sent = json.loads(out.for_model())
    assert "monte_carlo" not in sent and sent["best"]["prob_best"] == 0.783  # the model sees the compact view


def test_cash_tool_sends_the_resolved_shock_so_judge_challenges_work(engine):
    out = asyncio.run(_box().run("monte_carlo_cash", {"scenario_id": "plant closure", "shock": None,
                                                      "protect_payroll": True, "with_plan": True, "n_paths": None,
                                                      "seed": None}))
    assert out.status == "ok", out.summary
    (_, body), = engine
    assert body["scenario_id"] == "judge-plant-closure" and body["shock"] is not None
    assert (body["n_paths"], body["seed"], body["protect_payroll"]) == (10000, 20261115, True)
    s = out.summary
    assert s["no_plan"]["prob_below_floor_any"] == 0.612 and s["with_plan"]["prob_below_floor_any"] == 0.044
    assert s["monte_carlo"] == FAKE_CASH and "bands" not in s["no_plan"]
    assert s["plan_central_headroom_over_floor"] == 0.0  # central_min_cash 25,000 on a 25,000 floor
    assert s["notes"] is None  # passed through as the engine gives it


# ----------------------------------------------------------------------------- figure check: probabilities


def _payloads(summary: dict[str, Any], inp: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    return [{"input": inp or {}, "result": summary}]


def test_percentages_are_checked_against_tool_shares():
    res = _payloads({**mc.decision_summary(FAKE_DECISION), "monte_carlo": FAKE_DECISION})
    ok = ("Keep: best in 78% of 20,000 paths (95% CI 77.7-78.9%). P50 $40.3B vs $11.9B; P5 -$8.4B. "
          "Chance of a loss 8%. Top driver: execution, swing 30.5.")
    assert chat.unverified_numbers(ok, res) == []
    assert chat.unverified_numbers("Keep wins 78.3% of the time.", res) == []
    assert chat.unverified_numbers("Keep wins 81 percent of the time.", res) == ["81%"]
    # 85 appears only in histogram counts (and 0.85 only in bin edges): not a figure the model may quote
    assert chat.unverified_numbers("Keep wins 85% of the time.", res) == ["85%"]
    assert chat.unverified_numbers("Value change P50 of $12.9B.", res) == ["$12.9B"]


def test_per_option_odds_and_downside_reach_the_model_and_pass_the_figure_check():
    """#240: every option's prob_best (+ CI) and worst-5% average are in the compact view the model sees."""
    s = mc.decision_summary(FAKE_DECISION)
    assert [(o["id"], o["prob_best"], o["prob_best_ci95"], o["expected_shortfall_5"]) for o in s["options"]] == [
        ("keep", 0.783, [0.777, 0.789], -21.6), ("replace", 0.217, [0.211, 0.223], -412.0)]
    res = _payloads({**s, "monte_carlo": FAKE_DECISION})
    ok = ("Replace: best in 22% (95% CI 21.1-22.3%), worst-5% average -$412B, chance of a loss 31%. "
          "Keep: best in 78%, worst-5% average -$21.6B.")
    assert chat.unverified_numbers(ok, res) == []
    assert chat.unverified_numbers("Replace: best in 34%.", res) == ["34%"]  # not a share of this run
    assert chat.unverified_numbers("Replace: best in 21.7%.", res) == []
    # a share of 0.344 is quotable as 34% / 34.4%
    one = _payloads(mc.decision_summary({**FAKE_DECISION, "options": [
        {**FAKE_DECISION["options"][1], "prob_best": 0.344, "prob_best_ci95": [0.337, 0.351]}]}))
    assert chat.unverified_numbers("Replace: best in 34% (34.4%), CI 33.7-35.1%.", one) == []
    assert chat.unverified_numbers("Replace: worst-5% average -$450B.", res) == ["$450B"]


def test_percentages_from_inputs_and_web_text_count():
    res = [{"input": DECISION_ARGS, "result": {"snippet": "revenue rose 23% last year"}}]
    assert chat.unverified_numbers("I assumed a 5% chance of a key-person event.", res) == []
    assert chat.unverified_numbers("Revenue rose 23%.", res) == []
    assert chat.unverified_numbers("Revenue rose 24%.", res) == ["24%"]


def test_chat_turn_with_monte_carlo_passes_the_figure_check_and_ships_the_full_result(env, engine):
    def final(body: dict[str, Any]) -> str:
        r = tool_results_in(body)[0]
        assert "monte_carlo" not in r  # compact view only
        best = r["best"]
        return (f"**Monte Carlo (SIMULATED, on my assumptions):** Keep: best in {best['prob_best']:.0%} of "
                f"{r['n_paths']:,} paths (95% CI {best['ci95'][0]:.0%}-{best['ci95'][1]:.0%}). P5 / P50 / P95: "
                f"keep -$8.4B / $40.3B / $92.7B. The inputs are my assumptions.")

    h = Harness(openrouter=FakeProvider(models=OPENROUTER_MODELS, replies=[
        oa_tool_calls(("monte_carlo_decision", copy.deepcopy(DECISION_ARGS))), oa_text(final)]))
    out = h.turn("Should Nvidia keep Jensen Huang as CEO?").json()
    assert out["status"] == "ok", out["notes"]
    assert "best in 78% of 20,000 paths (95% CI 78%-79%)" in out["reply"]
    call = out["tool_calls"][0]
    assert call["name"] == "monte_carlo_decision" and call["provenance"] == "SIMULATED"
    assert call["result_summary"]["monte_carlo"] == FAKE_DECISION  # the UI draws from this


def test_chat_turn_with_an_invented_probability_is_withheld(env, engine):
    h = Harness(openrouter=FakeProvider(models=OPENROUTER_MODELS, replies=[
        oa_tool_calls(("monte_carlo_decision", copy.deepcopy(DECISION_ARGS))),
        oa_text("Keep is best in 85% of paths (SIMULATED)."),
        oa_text("Keep is best in 85% of paths (SIMULATED).")]))  # the repair round (#221) repeats it
    out = h.turn("Should Nvidia keep Jensen Huang as CEO?").json()
    assert out["status"] == "error" and out["reply"] == ""
    assert any("85%" in n for n in out["notes"])


def test_prompt_asks_for_search_then_monte_carlo_then_numbers_first():
    for web in (True, False):
        system = chat.system_prompt(web_search=web)
        for rule in ("monte_carlo_decision", "LEADING WITH THE NUMBERS", "conditional on them, not a forecast",
                     "MODEL-WRITTEN judgment", "monte_carlo_cash", "query_internal_data",
                     "SYNTHETIC (mock internal data)", "0.783 is 78%", "use triangular or normal for any downside",
                     "plan_central_headroom_over_floor"):
            assert rule in system, (web, rule)
    assert "Step 1: Call web_search first" in chat.system_prompt(web_search=True)
    assert "set every source null" in chat.system_prompt(web_search=False)


@pytest.mark.skipif(importlib.util.find_spec("routes.montecarlo") is None, reason="engine PR #208 not on this branch")
def test_real_engine_round_trip():
    out = asyncio.run(_box().run("monte_carlo_decision", copy.deepcopy(DECISION_ARGS)))
    assert out.status == "ok", out.summary
    full = out.summary["monte_carlo"]
    assert full["provenance"] == "SIMULATED" and full["n_paths"] == 20000
    assert {o["id"] for o in full["options"]} == {"keep", "replace"}
    assert 0 <= out.summary["best"]["prob_best"] <= 1
    cash = asyncio.run(_box().run("monte_carlo_cash", {"scenario_id": "bad-quarter", "shock": None,
                                                      "protect_payroll": True, "with_plan": True, "n_paths": 2000,
                                                      "seed": None}))
    assert cash.status == "ok", cash.summary
    assert 0 <= cash.summary["no_plan"]["prob_below_floor_any"] <= 1


# ----------------------------------------------------------------------------- the data room


def _table(name: str) -> dict[str, Any]:
    data = internal_data.load_table(get_settings(), name)
    assert data is not None
    return data


def test_every_table_is_committed_synthetic_and_labelled():
    for name in internal_data.TABLES:
        t = _table(name)
        assert t["provenance"] == "SYNTHETIC" and t["label"] == "SYNTHETIC (mock internal data)"
        assert t["rows"] and set(t["rows"][0]) == set(t["schema"]), name


def test_data_room_is_consistent_with_the_demo_business():
    biz = json.loads((REPO / "services/api/data/demo_business.json").read_text())["business"]
    q = internal_data.query_rows
    assert q(_table("payroll"), filters=None, group_by=None, aggregate="sum", field="weekly_cost",
             limit=None)["value"] == biz["payroll"]
    assert q(_table("inventory"), filters=None, group_by=None, aggregate="sum", field="on_hand_value",
             limit=None)["value"] == biz["inventory_0"]
    revenue = q(_table("general_ledger"), filters=[{"field": "account", "op": "eq", "value": "revenue"}],
                group_by=None, aggregate="sum", field="amount", limit=None)["value"]
    assert abs(revenue / 52 - sum(s["base_sales"] for s in biz["stores"])) < 0.05 * 50_000
    weekly = sum(r["weekly_revenue"] for r in _table("customers")["rows"])
    assert abs(weekly - sum(s["base_sales"] for s in biz["stores"])) < 0.01
    debt = {r["item_id"]: r for r in _table("debt")["rows"]}
    assert debt["D2"]["limit"] == biz["revolver_limit"] and debt["D3"]["threshold"] == biz["min_cash"]


def test_generator_reproduces_the_committed_files():
    out = subprocess.run([sys.executable, str(REPO / "scripts/gen_internal_data.py"), "--check"],
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stdout + out.stderr


def test_query_grouped_sum_carries_share_of_total_computed_in_python():
    res = internal_data.query_rows(_table("customers"), filters=None, group_by="segment", aggregate="sum",
                                   field="share_of_total_sales", limit=None)
    assert res["groups_total"] == 2 and res["groups"][0]["group"] == "retail (paid at till)"
    assert abs(res["value"] - 1.0) < 1e-3
    top = internal_data.query_rows(_table("customers"),
                                   filters=[{"field": "segment", "op": "eq", "value": "account (invoiced)"}],
                                   group_by="name", aggregate="sum", field="weekly_revenue", limit=1)
    assert len(top["groups"]) == 1 and top["groups_total"] == 12 and 0 < top["groups"][0]["share_of_total"] < 1


def test_query_filters_aggregates_and_limits():
    q = internal_data.query_rows
    ar = _table("ar_aging")
    over = q(ar, filters=[{"field": "days_outstanding", "op": "gt", "value": 30}], group_by=None, aggregate="count",
             field=None, limit=None)
    assert over["value"] == sum(1 for r in ar["rows"] if r["days_outstanding"] > 30)
    assert q(ar, filters=None, group_by=None, aggregate="max", field="days_outstanding", limit=None)["value"] == max(
        r["days_outstanding"] for r in ar["rows"])
    rows = q(_table("general_ledger"), filters=[{"field": "store", "op": "contains", "value": "store 1"}],
             group_by=None, aggregate=None, field=None, limit=5)
    assert rows["returned"] == 5 and rows["truncated"] and all(r["store"] == "Store 1" for r in rows["rows"])
    for kwargs, needle in (({"limit": 51}, "limit"), ({"group_by": "nope", "aggregate": "count"}, "not a column"),
                           ({"aggregate": "sum"}, "needs a numeric field"), ({"field": "amount"}, "need an aggregate"),
                           ({"aggregate": "sum", "field": "customer"}, "not numeric")):
        full = {"filters": None, "group_by": None, "aggregate": None, "field": None, "limit": None, **kwargs}
        with pytest.raises(internal_data.QueryError, match=needle):
            q(ar, **full)


def test_query_tool_is_labelled_and_errors_go_back_to_the_model():
    box = _box()
    ok = asyncio.run(box.run("query_internal_data", {"table": "payroll", "filters": None, "group_by": "store",
                                                     "aggregate": "sum", "field": "weekly_cost", "limit": None}))
    assert ok.status == "ok" and ok.provenance == "SYNTHETIC (mock internal data)"
    assert ok.summary["value"] == 12000.0 and ok.summary["computed_by"].startswith("Python")
    assert ok.input == {"table": "payroll", "filters": None, "group_by": "store", "aggregate": "sum",
                        "field": "weekly_cost", "limit": None}
    # a grouped share quoted as a percentage passes the figure check
    share = ok.summary["groups"][0]["share_of_total"]
    text = f"Store payroll: the largest store is {share:.0%} of the weekly total of $12,000."
    assert chat.unverified_numbers(text, [{"input": ok.input, "result": ok.summary}]) == []
    bad = asyncio.run(box.run("query_internal_data", {"table": "secrets", "filters": None, "group_by": None,
                                                      "aggregate": None, "field": None, "limit": None}))
    assert bad.status == "error" and "table must be one of" in bad.summary["error"]


# ----------------------------------------------------------------------------- routes + public mode


def test_internal_data_routes():
    client = TestClient(create_app())
    idx = client.get("/api/internal-data").json()
    assert idx["status"] == "AVAILABLE" and idx["label"] == "SYNTHETIC (mock internal data)"
    assert [t["name"] for t in idx["tables"]] == list(internal_data.TABLES)
    assert next(t for t in idx["tables"] if t["name"] == "general_ledger")["row_count"] == 676
    one = client.get("/api/internal-data/customers", params={"limit": 3}).json()
    assert one["provenance"] == "SYNTHETIC" and one["returned"] == 3 and one["row_count"] == 13
    assert "schema" in one and len(one["rows"]) == 3
    missing = client.get("/api/internal-data/salaries")
    assert missing.status_code == 404 and missing.json()["code"] == "NOT_FOUND"
    assert client.get("/api/internal-data/payroll", params={"limit": 0}).status_code == 422


def test_missing_data_room_is_not_available(tmp_path, monkeypatch):
    monkeypatch.setenv("FAULTLINE_DATA_DIR", str(tmp_path))
    client = TestClient(create_app())
    idx = client.get("/api/internal-data").json()
    assert idx["status"] == "NOT AVAILABLE" and idx["tables"] == []
    resp = client.get("/api/internal-data/payroll")
    assert resp.status_code == 503 and resp.json()["code"] == "DATA_UNAVAILABLE"


def test_internal_data_is_public_in_public_mode(monkeypatch):
    for name in ("FAULTLINE_PUBLIC_CHAT", "FAULTLINE_CORS_ORIGINS", "FAULTLINE_RATE_LIMIT_PER_MIN"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("FAULTLINE_MODE", "public")
    monkeypatch.setenv("FAULTLINE_ADMIN_TOKEN", "f6" * 32)
    monkeypatch.setenv("FAULTLINE_PUBLIC_ORIGIN", "https://faultline.example.com")
    client = TestClient(create_app())
    assert client.get("/api/internal-data").status_code == 200  # no token, like /api/simulate
    assert client.get("/api/internal-data/debt").status_code == 200
    assert client.post("/api/explore/chat", json={}).status_code in (401, 403)  # the chat stays gated


# ----------------------------------------------------------------------------- hypothetical premise (#221)


def test_premise_labels_the_run_and_never_reaches_the_engine(engine):
    args = {**copy.deepcopy(DECISION_ARGS), "premise": "  the CEO had   3 affairs "}
    out = asyncio.run(_box().run("monte_carlo_decision", args))
    assert out.status == "ok", out.summary
    (_, body), = engine
    assert "premise" not in body and "premise" not in out.input  # the engine input is unchanged
    assert out.summary["premise"] == {"text": "the CEO had 3 affairs", "label": chat.HYPOTHETICAL_PREMISE_LABEL,
                                      "note": "Taken from the user's message as an assumption; not checked "
                                              "against any source."}
    assert "USER-SUPPLIED HYPOTHETICAL, NOT VERIFIED" in out.for_model()


@pytest.mark.parametrize("premise", ["", "   ", None])
def test_no_premise_adds_no_label(engine, premise):
    args = {**copy.deepcopy(DECISION_ARGS), "premise": premise}
    out = asyncio.run(_box().run("monte_carlo_decision", args))
    assert out.status == "ok" and "premise" not in out.summary


def test_decision_tool_asks_for_a_premise_without_spending_the_union_budget():
    spec = next(s for s in _box().specs() if s.name == "monte_carlo_decision")
    assert spec.parameters["properties"]["premise"]["type"] == "string"  # not nullable: no extra union parameter
    assert "premise" in spec.parameters["required"]
