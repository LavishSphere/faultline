"""Live step previews for POST /api/explore/chat/stream (#222): one short line per tool call and per tool result.

Built on the server from the tool's arguments and the engine's own summary, so the browser computes nothing. The
lines are formatting only: every figure in a result preview is copied (rounded for display) from the tool result the
model is shown, and the same result arrives in full in the final response. Reply text never passes through here.
"""

from __future__ import annotations

from typing import Any

from agents.explore_chat import ChatEvent, ToolOutcome

MAX_PREVIEW = 160


def _clip(text: str, limit: int = MAX_PREVIEW) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _num(v: Any) -> float | None:
    return float(v) if isinstance(v, int | float) and not isinstance(v, bool) else None


def _money(v: Any) -> str:
    x = _num(v)
    if x is None:
        return "n/a"
    return f"-${abs(x):,.0f}" if x < 0 else f"${x:,.0f}"


def _pct(v: Any) -> str:
    x = _num(v)
    return "n/a" if x is None else f"{x * 100:.0f}%"


def _paths(v: Any) -> str | None:
    x = _num(v)
    return f"{int(x):,} paths" if x is not None else None


def _scenario(args: dict[str, Any]) -> str:
    sid = args.get("scenario_id")
    if isinstance(sid, str) and sid.strip() and sid.strip().lower() not in ("null", "none"):
        return _clip(sid, 60)
    shock = args.get("shock")
    if isinstance(shock, dict):
        name = shock.get("name")
        return _clip(name, 60) if isinstance(name, str) and name.strip() else "a custom shock"
    return "no shock (baseline)"


def call_preview(name: str, args: dict[str, Any] | None) -> str:
    """What the model asked for, in words. Arguments are the model's (not yet validated)."""
    if args is None:
        return f"{name}: arguments were not a JSON object"
    if name == "web_search":
        return _clip(f"Searching the web: “{_clip(args.get('query') or '', 120)}”")
    if name == "simulate":
        return _clip(f"Simulating cash: {_scenario(args)}")
    if name == "optimize":
        payroll = " · payroll protected" if args.get("protect_payroll") is True else ""
        return _clip(f"Optimizing a recovery plan: {_scenario(args)}{payroll}")
    if name == "decision":
        frame = args.get("frame_id")
        return _clip(f"Weighing the decision frame {frame}" if isinstance(frame, str) else "Weighing a decision frame")
    if name == "monte_carlo_decision":
        opts = [o.get("label") or o.get("id") for o in args.get("options") or [] if isinstance(o, dict)]
        parts = ["Running Monte Carlo", _paths(args.get("n_paths")), " vs ".join(str(o) for o in opts[:4] if o)]
        return _clip(" · ".join(p for p in parts if p))
    if name == "monte_carlo_cash":
        parts = ["Running Monte Carlo on cash", _paths(args.get("n_paths")), _scenario(args)]
        return _clip(" · ".join(p for p in parts if p))
    if name == "query_internal_data":
        table = args.get("table")
        return _clip(f"Querying internal data: {table}" if isinstance(table, str) else "Querying internal data")
    if name == "vc_lenses":
        return "Reading the VC research lenses"
    if name in ("list_scenarios", "list_judge_challenges", "list_decision_frames"):
        return "Reading the engine: " + name.removeprefix("list_").replace("_", " ")
    return _clip(f"Calling {name}")


def _count(summary: dict[str, Any], key: str, noun: str) -> str:
    items = summary.get(key)
    return f"{len(items)} {noun}" if isinstance(items, list) else f"{noun}: NOT AVAILABLE"


def result_preview(name: str, outcome: ToolOutcome) -> str:
    """What the engine returned, in one line, from the same summary the model is shown."""
    s = outcome.summary if isinstance(outcome.summary, dict) else {}
    if outcome.status != "ok":
        return _clip(f"error: {s.get('error') or 'the tool failed'}")
    if name == "web_search":
        results = [r for r in s.get("results") or [] if isinstance(r, dict)]
        domains: list[str] = []
        for r in results:
            d = r.get("domain")
            if isinstance(d, str) and d and d not in domains:
                domains.append(d)
        more = ", …" if len(domains) > 3 else ""
        noun = "source" if len(results) == 1 else "sources"
        return _clip(f"{len(results)} {noun}" + (f": {', '.join(domains[:3])}{more}" if domains else ""))
    if name == "simulate":
        return _clip(f"low point {_money(s.get('min_cash'))} in week {s.get('min_cash_week')} · "
                     f"ends at {_money(s.get('ending_cash'))}")
    if name == "optimize":
        if s.get("status") == "OPTIMAL":
            return _clip(f"OPTIMAL · low point {_money(s.get('min_cash'))} in week {s.get('min_cash_week')}")
        return _clip(str(s.get("status") or "no status"))
    if name == "decision":
        rec = s.get("recommendation")
        return _clip(f"recommendation: {rec}" if rec else "no recommendation")
    if name == "monte_carlo_decision":
        best = s.get("best") if isinstance(s.get("best"), dict) else {}
        labels = {o.get("id"): o.get("label") for o in s.get("options") or [] if isinstance(o, dict)}
        ci = best.get("ci95")
        ci_text = (f" (CI {_pct(ci[0]).rstrip('%')}-{_pct(ci[1])})"
                   if isinstance(ci, list | tuple) and len(ci) == 2 else "")
        paths = _paths(s.get("n_paths"))
        if best.get("id") is None:
            return _clip("no single best option" + (f" · {paths}" if paths else ""))
        label = labels.get(best.get("id")) or best.get("id")
        return _clip(f"best: {label} {_pct(best.get('prob_best'))}{ci_text}" + (f" · {paths}" if paths else ""))
    if name == "monte_carlo_cash":
        no_plan = s.get("no_plan") if isinstance(s.get("no_plan"), dict) else {}
        with_plan = s.get("with_plan") if isinstance(s.get("with_plan"), dict) else None
        text = f"P(below floor) no plan {_pct(no_plan.get('prob_below_floor_any'))}"
        if with_plan:
            text += f" → with plan {_pct(with_plan.get('prob_below_floor_any'))}"
        paths = _paths(s.get("n_paths"))
        return _clip(text + (f" · {paths}" if paths else ""))
    if name == "query_internal_data":
        matched = s.get("rows_matched")
        return _clip(f"{matched} rows matched" if isinstance(matched, int) else "query ran")
    if name == "vc_lenses":
        return _count(s, "items", "research items")
    if name == "list_scenarios":
        return _count(s, "items", "scenarios")
    if name == "list_judge_challenges":
        return _count(s, "items", "challenges")
    if name == "list_decision_frames":
        return _count(s, "frames", "decision frames")
    return "done"


def event_payload(ev: ChatEvent) -> dict[str, Any]:
    """The SSE `data:` object for one ChatEvent (type round / tool_call / tool_result)."""
    if ev.type == "round":
        return {"type": "round", "n": ev.round}
    if ev.type == "tool_call":
        return {"type": "tool_call", "id": ev.id, "name": ev.name, "input_preview": call_preview(ev.name, ev.arguments)}
    outcome = ev.outcome or ToolOutcome("error", "LIVE EXPLORE", {}, {"error": "no result"})
    return {"type": "tool_result", "id": ev.id, "name": ev.name, "result_status": outcome.status,
            "provenance": outcome.provenance, "preview": result_preview(ev.name, outcome)}


__all__ = ["call_preview", "event_payload", "result_preview"]
