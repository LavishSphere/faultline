"""#221: one repair round when a reply fails the figure check, on both provider paths."""

from __future__ import annotations

import asyncio
from typing import Any

from test_explore_chat import (  # noqa: F401 - env fixture
    ANTHROPIC_LIST,
    OPENROUTER_MODELS,
    OPUS,
    FakeProvider,
    Harness,
    an_message,
    env,
    oa_text,
    oa_tool_calls,
)

from agents import explore_chat as chat

BAD = "Lowest cash is $987,654 and the plan costs $12,345,678 (SIMULATED)."
GOOD = "The bad quarter pushes cash below the floor (SIMULATED). Next step: run the recovery plan."


def _sim() -> Any:
    return oa_tool_calls(("simulate", {"scenario_id": "bad-quarter", "shock": None}))


def test_repair_message_lists_exactly_the_unsupported_figures():
    msg = chat.repair_message(["$18B", "$1,601B", "$88B"])
    assert msg == ("These figures are not in any tool result: $18B, $1,601B, $88B. Rewrite the answer using only "
                   "figures that appear in the tool results (or cited snippets), or drop those figures. Do not "
                   "compute new numbers.")


def test_a_reply_that_passes_on_the_second_try_is_shown_with_a_note(env):  # noqa: F811
    h = Harness(openrouter=FakeProvider(models=OPENROUTER_MODELS, replies=[_sim(), oa_text(BAD), oa_text(GOOD)]))
    out = h.turn().json()
    assert out["status"] == "ok" and out["reply"] == GOOD
    assert chat.REPAIRED_NOTE in out["notes"]
    third = h.openrouter.chat_requests[-1]["json"]["messages"]
    assert third[-2] == {"role": "assistant", "content": BAD}
    assert third[-1] == {"role": "user", "content": chat.repair_message(["$987,654", "$12,345,678"])}
    # both final rounds count: 3 provider calls (tool call, bad reply, repaired reply)
    assert out["usage"] == {"input_tokens": 100 + 150 + 150, "output_tokens": 20 + 30 + 30}


def test_a_reply_that_fails_twice_is_withheld(env):  # noqa: F811
    h = Harness(openrouter=FakeProvider(models=OPENROUTER_MODELS, replies=[_sim(), oa_text(BAD), oa_text(BAD)]))
    out = h.turn().json()
    assert out["status"] == "error" and out["reply"] == ""
    assert any("figures the engine didn't produce" in n and "$987,654" in n for n in out["notes"])
    assert chat.REPAIRED_NOTE not in out["notes"]
    assert len(h.openrouter.chat_requests) == 3  # exactly one repair round, never a second


def test_anthropic_repair_round_appends_one_user_note_after_the_assistant_turn(env):  # noqa: F811
    tool_use = {"type": "tool_use", "id": "toolu_01", "name": "simulate",
                "input": {"scenario_id": "bad-quarter", "shock": None}}
    h = Harness(anthropic=FakeProvider(models=ANTHROPIC_LIST, replies=[
        an_message([tool_use], "tool_use"),
        an_message([{"type": "text", "text": BAD}], "end_turn"),
        an_message([{"type": "text", "text": GOOD}], "end_turn"),
    ]))
    out = h.turn(model_id=OPUS).json()
    assert out["status"] == "ok" and out["reply"] == GOOD and chat.REPAIRED_NOTE in out["notes"]
    messages = h.anthropic.chat_requests[-1]["json"]["messages"]
    assert messages[-2]["role"] == "assistant" and messages[-2]["content"][0]["text"] == BAD
    assert messages[-1] == {"role": "user", "content": chat.repair_message(["$987,654", "$12,345,678"])}


class _ScriptedAdapter:
    provider = "openrouter"
    model = "scripted"

    def __init__(self, replies: list[str]) -> None:
        self.replies = replies
        self.notes: list[tuple[str, str]] = []

    def start(self, history, tools, system) -> None:  # noqa: ANN001
        pass

    async def step(self) -> chat.Step:
        return chat.Step(text=self.replies.pop(0), tool_requests=[], stop="end", input_tokens=1, output_tokens=1)

    def add_tool_results(self, results) -> None:  # noqa: ANN001
        pass

    def add_user_note(self, previous_reply: str, note: str) -> None:
        self.notes.append((previous_reply, note))


class _OkBox:
    def specs(self) -> list[chat.ToolSpec]:
        return []

    async def run(self, name: str, arguments: dict[str, Any]) -> chat.ToolOutcome:
        raise AssertionError("not called")


def test_repair_emits_a_repair_event_when_a_callback_is_given():
    events: list[tuple[str, dict[str, Any] | None]] = []

    async def on_event(ev: chat.ChatEvent) -> None:
        events.append((ev.type, ev.detail))

    adapter = _ScriptedAdapter(["Runway is $5,000,000.", "No figures this time."])
    # a prior ok tool record is needed for the repair path (no tool at all = withheld outright), so seed one
    out = asyncio.run(_run_with_ok_record(adapter, on_event))
    assert out.status == "ok" and out.reply == "No figures this time."
    assert events == [("round", None), ("tool_call", None), ("tool_result", None),
                      ("repair", {"unsupported": ["$5,000,000"]})]
    assert adapter.notes == [("Runway is $5,000,000.", chat.repair_message(["$5,000,000"]))]


async def _run_with_ok_record(adapter: _ScriptedAdapter, on_event: Any) -> chat.ChatOutcome:
    class Box(_OkBox):
        def specs(self) -> list[chat.ToolSpec]:
            return [chat.ToolSpec("noop", "x", {"type": "object", "properties": {}, "required": [],
                                                "additionalProperties": False})]

        async def run(self, name: str, arguments: dict[str, Any]) -> chat.ToolOutcome:
            return chat.ToolOutcome("ok", "SIMULATED", {}, {"value": 1})

    first = adapter.replies.pop(0)
    calls = iter([chat.Step(text="", tool_requests=[chat.ToolRequest(id="c1", name="noop", arguments={})],
                            stop="tool_use", input_tokens=1, output_tokens=1)])
    original = adapter.step

    async def step() -> chat.Step:
        nxt = next(calls, None)
        return nxt if nxt is not None else await original()

    adapter.replies.insert(0, first)
    adapter.step = step  # type: ignore[method-assign]
    return await chat.run_chat(adapter, Box(), [{"role": "user", "content": "q"}], web_search=False,
                               on_event=on_event)
