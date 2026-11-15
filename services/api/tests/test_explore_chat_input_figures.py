"""#230: the model's own Monte Carlo INPUT values back the figures it restates as assumptions; web_search queries
(model-written text) never do."""

from __future__ import annotations

from typing import Any

import pytest

from agents import explore_chat as chat

MC_INPUT: dict[str, Any] = {
    "question": "Should Nvidia keep its CEO?",
    "metric": {"name": "5-year shareholder value change", "unit": "$B", "higher_is_better": True},
    "options": [
        {"id": "keep", "label": "Keep", "drivers": [
            {"name": "execution", "kind": "value", "distribution": "triangular",
             "params": {"low": -40.0, "mode": 120.0, "high": 300.0}, "source": None},
            {"name": "scandal fallout", "kind": "event", "distribution": "uniform",
             "params": {"low": -250.0, "high": -80.0}, "probability": 0.6, "source": None}]},
        {"id": "replace", "label": "Replace", "drivers": [
            {"name": "transition", "kind": "value", "distribution": "normal",
             "params": {"mean": -60.0, "sd": 90.0}, "source": None}]},
    ],
    "n_paths": 20000,
    "seed": 7,
}


def _record(name: str, inp: dict[str, Any], summary: dict[str, Any] | None = None,
            status: str = "ok") -> chat.ToolCallRecord:
    return chat.ToolCallRecord(name=name, input=inp, result_status=status,  # type: ignore[arg-type]
                               result_summary=summary or {"provenance": "SIMULATED"}, provenance="SIMULATED")


@pytest.mark.parametrize("reply", [
    "I assumed a 60% chance that the scandal fallout hits.",
    "Execution ranges from -$40B to $300B, most likely $120B (my assumption).",
    "The transition is a loss of about $60B on average, with a spread of $90B.",
    "Run on 20,000 paths.",
])
def test_a_reply_quoting_its_own_monte_carlo_input_passes(reply):
    payloads = chat.figure_payloads([_record("monte_carlo_decision", MC_INPUT)])
    assert chat.unverified_numbers(reply, payloads) == []


@pytest.mark.parametrize("reply, flagged", [
    ("I assumed a 45% chance of a lawsuit.", ["45%"]),
    ("Replacing him costs $18B.", ["$18B"]),
])
def test_a_figure_in_no_input_or_output_still_fails(reply, flagged):
    payloads = chat.figure_payloads([_record("monte_carlo_decision", MC_INPUT)])
    assert chat.unverified_numbers(reply, payloads) == flagged


def test_a_web_search_query_never_backs_a_figure():
    search = _record("web_search", {"query": "Nvidia $18B buyback 37% stake 2026"},
                     {"provenance": "REAL (web, retrieved 2026-11-15T05:00:00Z)", "results": []})
    payloads = chat.figure_payloads([search])
    assert payloads == [{"input": {}, "result": search.result_summary}]
    assert chat.unverified_numbers("Nvidia announced a $18B buyback and a 37% stake.", payloads) == ["$18B", "37%"]


def test_inputs_of_failed_calls_never_count():
    payloads = chat.figure_payloads([_record("monte_carlo_decision", MC_INPUT, status="error")])
    assert payloads == []
    assert chat.unverified_numbers("I assumed a 60% chance.", payloads) == ["60%"]


def test_monte_carlo_cash_inputs_count_too():
    payloads = chat.figure_payloads([_record("monte_carlo_cash", {"scenario_id": "bad-quarter", "n_paths": 5000,
                                                                  "protect_payroll": True})])
    assert chat.unverified_numbers("I ran 5,000 paths.", payloads) == []


def test_round_and_search_caps_fit_broad_search_follow_ups_and_monte_carlo():
    from routes import explore_chat as chat_routes
    assert chat.MAX_TOOL_ROUNDS == 6 and chat_routes.MAX_WEB_SEARCHES_PER_TURN == 6
