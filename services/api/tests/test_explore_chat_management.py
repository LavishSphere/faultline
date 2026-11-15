"""#221: management-first prompt, the hypothetical-premise contract, the OpenAI vetted list and open-weight flags."""

from __future__ import annotations

import re

import pytest
from test_explore_chat import OPENROUTER_MODELS, FakeProvider, Harness, env, or_model  # noqa: F401 - env fixture

from agents import explore_chat as chat

# --------------------------------------------------------------------------- system prompt


@pytest.mark.parametrize("web", [True, False])
def test_prompt_puts_management_decisions_first_and_scopes_cash_tools_to_the_demo_business(web):
    system = chat.system_prompt(web_search=web)
    a, b = system.index("A. Real-world management"), system.index("B. The SYNTHETIC (fictional) demo business")
    assert a < b
    for kind in ("CEO and executive retention and succession", "scandals and misconduct", "board actions",
                 "M&A and divestitures", "layoffs", "market entry and exit", "pricing", "big bets"):
        assert kind in system[a:b], kind
    for part in ("keep / keep with conditions / suspend / replace",
                 "the board, shareholders, employees, customers and regulators", "dual-class",
                 "legal and reputational risk"):
        assert part in system, part
    for driver in ("shareholder value", "transition disruption", "scandal fallout", "key-person risk",
                   "talent attrition"):
        assert driver in system, driver
    assert "ONLY when the user asks about the demo business" in system
    assert "do not offer to stress-test a real decision on the demo business" in system
    assert "stress-test the decision on the synthetic demo business" not in system  # the old closing offer is gone


def test_prompt_with_web_search_asks_for_precedents_and_base_rates():
    system = chat.system_prompt(web_search=True)
    assert "PRECEDENTS and base rates" in system
    assert "who was ousted and who was retained" in system
    assert "above all on the precedents' base rates" in system


@pytest.mark.parametrize("web", [True, False])
def test_prompt_contains_the_hypothetical_premise_rule(web):
    system = chat.system_prompt(web_search=web)
    assert chat.HYPOTHETICAL_LINE == ("Hypothetical: you said <premise>. I have not verified it, and I treat it as "
                                      "an assumption, not a fact.")
    assert f"the reply's very first line is exactly \"{chat.HYPOTHETICAL_LINE}\"" in system
    for rule in ("never state or imply that it is true", "Never invent allegations",
                 "never present an unverified claim about a real person as fact", "do not moralise or refuse",
                 "premise field", "model the decision conditional on the hypothetical"):
        assert rule in system, rule
    assert not re.search(r"\$\d", system)


def test_brief_headings_cover_stakeholders_governance_and_precedents():
    assert "Stakeholders, governance and risk" in chat.DECISION_BRIEF_HEADINGS
    assert "Evidence and precedents" in chat.DECISION_BRIEF_HEADINGS
    assert chat.DECISION_BRIEF_HEADINGS[-1] == "Verdict (MODEL-WRITTEN judgment, not advice)"


def test_a_small_figure_in_the_hypothetical_line_is_not_withheld():
    line = ("Hypothetical: you said Jensen Huang had 3 affairs. I have not verified it, and I treat it as an "
            "assumption, not a fact.")
    assert chat.unverified_numbers(line, []) == []


# --------------------------------------------------------------------------- OpenAI vetted list


def test_openai_vetted_list_is_the_live_checked_current_generation():
    ids = [m for m, _, _ in chat.OPENAI_VETTED]
    assert ids == ["gpt-6-sol", "gpt-5.5", "gpt-5.4-mini"]
    assert not [m for m in ids if m.startswith(("gpt-4", "gpt-5.1")) or m == "gpt-5"]


@pytest.mark.parametrize("model, effort", [("gpt-6-sol", "none"), ("gpt-5.5", "none"), ("gpt-5.4-mini", None),
                                           ("some-pinned-model", None)])
def test_openai_token_kwargs_follow_the_live_check(monkeypatch, model, effort):
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-" + "o" * 24)
    adapter = chat.OpenAICompatibleAdapter("openai", model, chat.ClientFactory())
    kwargs = adapter._token_kwargs()
    assert kwargs["max_completion_tokens"] == chat.MAX_OUTPUT_TOKENS and "max_tokens" not in kwargs
    assert kwargs.get("reasoning_effort") == effort
    assert "temperature" not in kwargs


# --------------------------------------------------------------------------- open weights


@pytest.mark.parametrize("model", [
    "z-ai/glm-4.5", "z-ai/glm-4.5-air", "z-ai/glm-4.6", "z-ai/glm-4.7", "z-ai/glm-5", "z-ai/glm-5.1",
    "meta-llama/llama-4-maverick", "meta-llama/llama-3.3-70b-instruct:free",
    "google/gemma-4-31b-it", "google/gemma-3-27b-it",
    "qwen/qwen3-235b-a22b-2507", "qwen/qwen3-30b-a3b", "qwen/qwen3-coder-480b-a35b", "qwen/qwen3.5-27b",
    "qwen/qwen3.6-35b-a3b", "qwen/qwen3-235b-a22b:free",
    "deepseek/deepseek-v3.2", "deepseek/deepseek-r1",
    "moonshotai/kimi-k2", "moonshotai/kimi-k2-thinking",
    "nvidia/nemotron-nano-9b-v2",
    "mistralai/mistral-small-3.2-24b-instruct", "mistralai/ministral-8b", "mistralai/mixtral-8x22b-instruct",
    "mistralai/mistral-nemo", "mistralai/devstral-small",
])
def test_open_weight_allow_list(model):
    assert chat.is_open_weight("openrouter", model)


@pytest.mark.parametrize("model", [
    "qwen/qwen3-max", "qwen/qwen-plus", "qwen/qwen3-coder-plus", "qwen/qwen3-coder-flash", "qwen/qwen3.5-plus",
    "qwen/qwen3-omni", "qwen/qwen-max",
    "google/gemini-3.1-flash-lite", "google/gemini-3-pro", "x-ai/grok-4.3",
    "z-ai/glm-4-32b", "z-ai/glm-4",
    "mistralai/mistral-large", "mistralai/mistral-medium-3", "moonshotai/kimi-dev", "nvidia/cosmos",
    "made/up", "deepseekish/model",
])
def test_closed_or_uncertain_models_are_not_open_weight(model):
    assert not chat.is_open_weight("openrouter", model)


@pytest.mark.parametrize("provider, model", [("openai", "gpt-6-sol"), ("anthropic", "claude-sonnet-5-5"),
                                             ("openai", "meta-llama/llama-4-maverick")])
def test_native_models_are_never_open_weight(provider, model):
    assert not chat.is_open_weight(provider, model)


def test_models_endpoint_reports_open_weights_and_features_open_models_first(env):  # noqa: F811
    h = Harness(openrouter=FakeProvider(models=[*OPENROUTER_MODELS, or_model("google/gemini-3.1-flash-lite"),
                                                or_model("x-ai/grok-4.3"), or_model("z-ai/glm-5.1"),
                                                or_model("qwen/qwen3-max")]))
    body = h.client.get("/api/explore/chat/models").json()
    flags = {m["id"]: m["open_weights"] for m in body["models"]}
    assert flags["openrouter:meta-llama/llama-4-maverick"] and flags["openrouter:z-ai/glm-5.1"]
    assert not flags["openrouter:qwen/qwen3-max"] and not flags["openrouter:google/gemini-3.1-flash-lite"]
    assert not flags["openrouter:x-ai/grok-4.3"] and not flags["anthropic:claude-sonnet-5-5"]
    featured = body["featured"]
    assert len(featured) <= chat.MAX_FEATURED == 13
    groups = [flags[i] for i in featured]
    assert groups == sorted(groups, reverse=True) and groups[0] and not groups[-1]  # open first, then closed
    assert "openrouter:google/gemini-3.1-flash-lite" not in featured and "openrouter:x-ai/grok-4.3" not in featured
    assert "openrouter:google/gemini-3.1-flash-lite" in flags  # still in the full list (Cmd-K)
    assert body["default"] == "anthropic:claude-sonnet-5-5"
    closed = [i for i in featured if not flags[i]]
    assert closed[:2] == ["anthropic:claude-sonnet-5-5", "anthropic:claude-opus-5-5"]
    assert featured[0] == "openrouter:z-ai/glm-5.1"  # glm-5.3 is not in this fixture catalogue
    llama = next(m for m in body["models"] if m["id"] == "openrouter:meta-llama/llama-4-maverick")
    assert llama["note"] == chat.OPEN_WEIGHT_NOTE and "pass" not in llama["note"]


def test_featured_preference_lists_open_weight_models_before_closed_ones():
    flags = [chat.is_open_weight(*i.split(":", 1)) for i in chat.FEATURED_PREFERENCE]
    assert flags == sorted(flags, reverse=True) and flags.count(True) == 8 and flags.count(False) == 5
    assert len(chat.FEATURED_PREFERENCE) == chat.MAX_FEATURED
    assert not [i for i in chat.FEATURED_PREFERENCE if "gemini" in i]
    assert chat.FEATURED_PREFERENCE[0] == "openrouter:z-ai/glm-5.3"
    assert chat.FEATURED_PREFERENCE[8:] == ("anthropic:claude-sonnet-5-5", "anthropic:claude-opus-5-5",
                                            "openai:gpt-6-sol", "openrouter:x-ai/grok-4.6",
                                            "anthropic:claude-haiku-5-5")


def test_prompt_makes_the_search_then_monte_carlo_then_brief_pipeline_mandatory():
    system = chat.system_prompt(web_search=True)
    assert ("(1) call web_search (one broad search, then one to three follow-up searches), (2) call "
            "monte_carlo_decision, (3) only then write the brief") in system
    assert "ONE broad search" in system and "FOLLOW-UP searches on what you learned" in system
    assert "is withheld automatically" in system and "Never skip a tool" in system
    offline = chat.system_prompt(web_search=False)
    assert "(1) call monte_carlo_decision, (2) only then write the brief" in offline
    assert "call web_search, (2)" not in offline


# --------------------------------------------------------------------------- the Hypothetical line is guaranteed


def _mc_record(premise: str | None, status: str = "ok") -> chat.ToolCallRecord:
    summary = {"premise": {"text": premise, "label": chat.HYPOTHETICAL_PREMISE_LABEL}} if premise else {}
    return chat.ToolCallRecord(name="monte_carlo_decision", input={}, result_status=status,  # type: ignore[arg-type]
                               result_summary=summary, provenance="SIMULATED")


def test_a_reply_modelled_on_a_premise_always_opens_with_the_hypothetical_line():
    reply = "**Decision:** Keep or replace."
    out = chat.with_hypothetical_line(reply, [_mc_record("Jensen Huang had 3 affairs.")])
    assert out.splitlines()[0] == ("Hypothetical: you said Jensen Huang had 3 affairs. I have not verified it, and "
                                   "I treat it as an assumption, not a fact.")
    assert out.endswith(reply)


def test_the_hypothetical_line_is_not_doubled_or_invented():
    written = "Hypothetical: you said X. I have not verified it, and I treat it as an assumption, not a fact.\nB"
    assert chat.with_hypothetical_line(written, [_mc_record("X")]) == written
    assert chat.with_hypothetical_line("A", [_mc_record(None)]) == "A"  # no premise: nothing added
    assert chat.with_hypothetical_line("A", [_mc_record("X", status="error")]) == "A"
