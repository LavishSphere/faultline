"""POST /api/explore/analyze (issue #61): decision -> Tavily -> local model -> cited evidence + suggested shock.

Mocked Tavily and mocked Ollama transports only: no network, no real key, no real model.

What is pinned here:
- Isolation: the model's prompt holds the decision text, the fixed instructions (including the ILLUSTRATIVE
  guidance ranges) and the Tavily results for this request, and nothing else. A canary planted in replay data
  (demo case evidence and a sealed outcome) never reaches the prompt or the response.
- Citations: every evidence card cites a URL Tavily actually returned for this request; uncited claims, unknown
  URLs (including near misses), claims naming another URL / scheme / domain, claims with a number the cited
  snippet does not contain, and claims with invisible format characters are rejected with a reason. Card
  snippets and retrieved_at come from Tavily, never from the model.
- Suggestion: every number is clamped to the finance owner's guidance range for its category (and so to a valid
  ScenarioShock), and the resulting shock is accepted by /api/simulate. It is labeled MODEL-SUGGESTED only when
  at least one value is the model's; all-default suggestions say GUIDANCE DEFAULTS. The model's parameter nesting
  (nested, dotted, wrapped in the category id) is normalized; its keys are never echoed. The analyze route itself
  never simulates. One LOCAL-ONLY test (FAULTLINE_REAL_OLLAMA=1) calls the real model.
- Honest failure: missing key -> 503 LIVE_EXPLORE_UNAVAILABLE; model down / invalid output -> a 200 that says so,
  with the Tavily sources and no evidence cards or suggestion; never a canned answer.
- Labels: LIVE EXPLORE everywhere; never REAL HISTORICAL or RECORDED RUN.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import uuid
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from agents import explore_analyst as ea
from core.financials import ScenarioShock
from main import create_app
from routes import explore

API_DIR = Path(__file__).resolve().parent.parent
DATA = API_DIR / "data"
GUIDANCE = json.loads((DATA / ea.GUIDANCE_FILE).read_text(encoding="utf-8"))
CATEGORY_IDS = [c["id"] for c in GUIDANCE["categories"]]
T = GUIDANCE["horizon_weeks"]

KEY = "tvly-analyze-" + "z" * 40
ADMIN = "b" * 40
PATH = "/api/explore/analyze"
DECISION = "Should we open a third store this spring while our floating-rate loan resets?"
DIGEST = "46e0c10c039e" + "1" * 52
URLS = [f"https://news{i}.example/story-{i}" for i in range(3)]
SNIPPETS = [
    "The central bank raised its policy rate by 50 basis points, more than markets expected.",
    "Officials signalled that further increases are likely at the next two meetings.",
    "Local retailers reported weaker weekend footfall after the announcement.",
]
OUTCOME_LIKE = re.compile(r"outcome|resolution|resolved|settle|winner|final_price|available_at", re.IGNORECASE)


# --------------------------------------------------------------------------- fakes


def tavily_payload(n: int = 3) -> dict:
    return {
        "query": DECISION,
        "results": [
            {"title": f"Headline {i}", "url": URLS[i], "content": SNIPPETS[i], "score": 0.9 - i / 10,
             "published_date": "Tue, 10 Nov 2026 14:00:00 GMT"}
            for i in range(n)
        ],
        "response_time": 0.4,
        "request_id": "req-analyze",
    }


class FakeTavily:
    def __init__(self, response: httpx.Response | Exception | None = None) -> None:
        self.response = response if response is not None else httpx.Response(200, json=tavily_payload())
        self.calls: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def model_answer(**over) -> dict:
    """A well-formed analyst answer citing the first two Tavily URLs (a TEST FIXTURE, never shown in the UI)."""
    answer = {
        "evidence": [
            {"claim": "The central bank raised its policy rate by 50 basis points.", "source_url": URLS[0]},
            {"claim": "Officials signalled further increases at the next meetings.", "source_url": URLS[1]},
        ],
        "category_id": "central-bank-rate-surprise",
        "parameters": {
            "rate": {
                "delta_rate": {"value": 0.005, "rationale": "A 50bp surprise passes through to the floating loan."},
                "start_week": {"value": 2, "rationale": "The loan resets at the next weekly reset."},
            }
        },
    }
    answer.update(over)
    return answer


class FakeOllama:
    """Records every request; answers /api/chat from a queue of contents (dict -> JSON text, str as is)."""

    def __init__(self, contents: list[dict | str] | None = None, *, installed: bool = True,
                 down: bool = False) -> None:
        self.contents = list(contents) if contents is not None else [model_answer()]
        self.installed = installed
        self.down = down
        self.requests: list[httpx.Request] = []

    def chat_bodies(self) -> list[dict]:
        return [json.loads(r.content) for r in self.requests if r.url.path == "/api/chat"]

    def prompts(self) -> list[str]:
        return [m["content"] for b in self.chat_bodies() for m in b["messages"]]

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.down:
            raise httpx.ConnectError("connection refused", request=request)
        if request.url.path == "/api/tags":
            models = [{"name": "llama3.1:8b", "model": "llama3.1:8b", "digest": DIGEST}] if self.installed else []
            return httpx.Response(200, json={"models": models})
        if request.url.path == "/api/chat":
            body = json.loads(request.content)
            text = "".join(m["content"] for m in body["messages"])
            content = self.contents.pop(0)
            text_out = content if isinstance(content, str) else json.dumps(content)
            return httpx.Response(200, json={
                "model": "llama3.1:8b",
                "message": {"role": "assistant", "content": text_out},
                "done": True,
                "done_reason": "stop",
                "prompt_eval_count": len(text.encode()) // 4 + 10,
                "eval_count": 200,
            })
        return httpx.Response(404)


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", KEY)
    for name in ("FAULTLINE_MODE", "FAULTLINE_ADMIN_TOKEN", "FAULTLINE_DATA_DIR", "OLLAMA_BASE_URL",
                 "FAULTLINE_OLLAMA_MODEL"):
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def make_client(tav: FakeTavily | None = None, oll: FakeOllama | None = None):
    tav = tav or FakeTavily()
    oll = oll or FakeOllama()
    app = create_app()
    app.dependency_overrides[explore.get_tavily_transport] = lambda: httpx.MockTransport(tav)
    app.dependency_overrides[explore.get_ollama_transport] = lambda: httpx.MockTransport(oll)
    return TestClient(app), tav, oll


def analyze(client: TestClient, text: str = DECISION, **kw) -> httpx.Response:
    return client.post(PATH, json={"decision_text": text}, **kw)


def walk_strings(node, out=None):
    out = [] if out is None else out
    if isinstance(node, dict):
        for k, v in node.items():
            out.append(k)
            walk_strings(v, out)
    elif isinstance(node, list):
        for v in node:
            walk_strings(v, out)
    elif isinstance(node, str):
        out.append(node)
    return out


# --------------------------------------------------------------------------- happy path and labels


def test_analysis_is_labeled_live_explore_and_cites_only_returned_urls(env):
    client, tav, oll = make_client()
    resp = analyze(client)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["mode"] == "live_explore"
    assert body["label"] == "LIVE EXPLORE: current, not point-in-time"
    assert body["attribution"] == "Search powered by Tavily"
    assert body["status"] == "ok"
    assert len(tav.calls) == 1 and len(oll.chat_bodies()) == 1

    # Sources are exactly what Tavily returned, with retrieval time.
    assert [s["url"] for s in body["sources"]] == URLS
    assert {s["source_id"] for s in body["sources"]} == {"S1", "S2", "S3"}

    cards = body["evidence"]
    assert [c["source_url"] for c in cards] == URLS[:2]
    by_url = {s["url"]: s for s in body["sources"]}
    for card in cards:
        src = by_url[card["source_url"]]
        # Snippet, title and timestamps come from Tavily, never from the model.
        assert card["snippet"] == src["snippet"] and card["source_title"] == src["title"]
        assert card["retrieved_at"] == src["retrieved_at"] == body["retrieved_at"]
        assert card["source_id"] == src["source_id"]
    assert body["rejected_claims"] == []


def test_suggestion_is_model_suggested_human_to_confirm_and_never_simulated(env):
    client, _, _ = make_client()
    body = analyze(client).json()
    sug = body["suggestion"]
    assert sug["label"] == "MODEL-SUGGESTED, HUMAN TO CONFIRM" and sug["values_from_model"] == 2
    assert sug["category_id"] == "central-bank-rate-surprise"
    params = {(p["block"], p["param"]): p for p in sug["parameters"]}
    assert set(params) == {("rate", "delta_rate"), ("rate", "start_week")}
    dr = params[("rate", "delta_rate")]
    assert dr["value"] == 0.005 and dr["source"] == "model" and dr["model_value"] == 0.005
    assert (dr["min"], dr["default"], dr["max"]) == (0.0025, 0.005, 0.01)
    assert dr["rationale"].startswith("A 50bp surprise")
    assert sug["shock"]["rate"] == {"delta_rate": 0.005, "start_week": 2}
    assert sug["shock"]["demand"] is None and sug["shock"]["supplier"] is None
    # No result figures in the analysis: the engine runs only when the human confirms (web app -> /api/simulate).
    keys = set(walk_strings(body))
    assert not keys & {"min_cash", "ending_cash", "runway_week", "cash", "deltas"}


def test_suggested_shock_is_accepted_by_simulate(env):
    client, _, _ = make_client()
    shock = analyze(client).json()["suggestion"]["shock"]
    sim = client.post("/api/simulate", json={"shock": shock})
    assert sim.status_code == 200, sim.text
    assert sim.json()["provenance"] == "SIMULATED"


def test_never_labeled_real_historical_or_recorded_run_and_no_outcome_keys(env):
    client, _, _ = make_client()
    body = analyze(client).json()
    text = json.dumps(body)
    for forbidden in ("REAL HISTORICAL", "REAL_HISTORICAL", "RECORDED RUN", "RECORDED_RUN"):
        assert forbidden not in text
    keys = [k for k in walk_strings(body) if isinstance(k, str)]
    dict_keys = set()

    def collect(node):
        if isinstance(node, dict):
            for k, v in node.items():
                dict_keys.add(k)
                collect(v)
        elif isinstance(node, list):
            for v in node:
                collect(v)

    collect(body)
    assert keys and not [k for k in dict_keys if OUTCOME_LIKE.search(k)]


def test_model_run_audit_fields(env):
    client, _, oll = make_client()
    body = analyze(client).json()
    run = body["model"]
    assert run["agent_model"] == "ollama/llama3.1:8b" and run["model_digest"] == DIGEST
    assert run["temperature"] == 0.0 and run["attempts"] == 1
    prompt = oll.prompts()[0]
    import hashlib

    assert run["prompt_sha256"] == hashlib.sha256(prompt.encode()).hexdigest()
    assert len(run["sources_sha256"]) == 64 and len(run["raw_output_sha256"]) == 64


# --------------------------------------------------------------------------- isolation: the prompt


def test_prompt_is_one_user_message_with_only_decision_instructions_and_tavily_results(env):
    client, _, oll = make_client()
    analyze(client)
    (chat,) = oll.chat_bodies()
    assert [m["role"] for m in chat["messages"]] == ["user"]
    assert "tools" not in chat and "system" not in chat
    assert chat["options"]["temperature"] == 0.0
    prompt = chat["messages"][0]["content"]
    assert DECISION in prompt
    for url, snip in zip(URLS, SNIPPETS, strict=True):
        assert url in prompt and snip in prompt
    # Every URL in the prompt is a Tavily result for this request (the guidance file's own source links are
    # not given to the model).
    assert set(re.findall(r"https?://\S+", prompt)) == set(URLS)


def test_prompt_matches_render_prompt_exactly(env):
    """The prompt sent is exactly render_prompt(decision, sources, guidance): no hidden extra context."""
    client, _, oll = make_client()
    body = analyze(client).json()
    sources = [ea.PromptSource(source_id=s["source_id"], url=s["url"], title=s["title"], snippet=s["snippet"],
                               published_at_raw=s["published_at_raw"]) for s in body["sources"]]
    guidance = ea.load_guidance(DATA)
    assert oll.prompts()[0] == ea.render_prompt(DECISION, sources, guidance)


def test_prompt_has_no_retrieval_timestamp(env):
    client, _, oll = make_client()
    body = analyze(client).json()
    prompt = oll.prompts()[0]
    assert body["retrieved_at"][:19] not in prompt
    assert body["retrieved_at"][:10] not in prompt  # not even today's date


def test_replay_canary_never_reaches_prompt_or_response(env, tmp_path):
    """Plant a canary in replay-only data (a demo case's evidence and a sealed outcome); it must not appear."""
    canary = f"CANARY-{uuid.uuid4()}"
    data = tmp_path / "data"
    data.mkdir()
    for name in (ea.GUIDANCE_FILE, "demo_business.json"):
        shutil.copy(DATA / name, data / name)
    (data / "sealed_outcomes").mkdir()
    (data / "sealed_outcomes" / "canary_case.json").write_text(
        json.dumps({"event_id": "canary_case", "outcome": canary, "resolution": canary}), encoding="utf-8")
    (data / "demo_cases").mkdir()
    (data / "demo_cases" / "canary_case.json").write_text(
        json.dumps({"case": {"event_id": "canary_case", "title": canary},
                    "evidence": [{"evidence_id": "canary_ev", "content": canary}]}), encoding="utf-8")
    env.setenv("FAULTLINE_DATA_DIR", str(data))
    client, _, oll = make_client()
    resp = analyze(client)
    assert resp.status_code == 200, resp.text
    assert canary not in resp.text
    assert all(canary not in p for p in oll.prompts())
    assert oll.prompts()  # the model was called


# --------------------------------------------------------------------------- citations (skeptic)


@pytest.mark.parametrize(
    ("claim", "reason"),
    [
        ({"claim": "Rates went up a lot."}, "uncited"),
        ({"claim": "Rates went up a lot.", "source_url": None}, "uncited"),
        ({"claim": "Rates went up a lot.", "source_url": "  "}, "uncited"),
        ({"claim": "Rates went up a lot.", "source_url": "https://made-up.example/x"}, "unknown_url"),
        ({"claim": "Rates went up a lot.", "source_url": URLS[0] + "/"}, "unknown_url"),  # near miss
        ({"claim": "Rates went up a lot.", "source_url": URLS[0].replace("https", "http")}, "unknown_url"),
        ({"claim": "Rates went up a lot.", "source_url": "S1"}, "unknown_url"),  # an id, not the url
        ({"claim": "See https://elsewhere.example/a for details.", "source_url": URLS[0]}, "unknown_url_in_text"),
        ({"claim": "   ", "source_url": URLS[0]}, "empty_claim"),
        ({"claim": "x" * (ea.CLAIM_MAX_CHARS + 1), "source_url": URLS[0]}, "claim_too_long"),
    ],
)
def test_uncited_or_unknown_url_claims_are_rejected(env, claim, reason):
    good = {"claim": "The central bank raised its policy rate by 50 basis points.", "source_url": URLS[0]}
    client, _, _ = make_client(oll=FakeOllama([model_answer(evidence=[good, claim])]))
    body = analyze(client).json()
    assert body["status"] == "ok"
    assert [c["source_url"] for c in body["evidence"]] == [URLS[0]]
    (rejected,) = body["rejected_claims"]
    assert rejected["reason"] == reason
    assert rejected["message"]


def test_duplicate_claims_are_rejected_once_accepted(env):
    good = {"claim": "The central bank raised its policy rate by 50 basis points.", "source_url": URLS[0]}
    client, _, _ = make_client(oll=FakeOllama([model_answer(evidence=[good, dict(good)])]))
    body = analyze(client).json()
    assert len(body["evidence"]) == 1
    assert [r["reason"] for r in body["rejected_claims"]] == ["duplicate"]


def test_claims_over_the_limit_are_rejected(env):
    claims = [{"claim": f"Claim {'abcdefghij'[i]} about the rate move.", "source_url": URLS[i % 3]}
              for i in range(ea.MAX_CLAIMS + 2)]
    client, _, _ = make_client(oll=FakeOllama([model_answer(evidence=claims)]))
    body = analyze(client).json()
    assert len(body["evidence"]) == ea.MAX_CLAIMS
    assert [r["reason"] for r in body["rejected_claims"]] == ["over_limit", "over_limit"]


def test_no_cited_evidence_withholds_the_suggestion(env):
    bad = [{"claim": "Rates went up.", "source_url": "https://made-up.example/x"}, {"claim": "Uncited claim."}]
    client, _, _ = make_client(oll=FakeOllama([model_answer(evidence=bad)]))
    body = analyze(client).json()
    assert body["status"] == "no_cited_evidence"
    assert body["evidence"] == [] and body["suggestion"] is None
    assert len(body["rejected_claims"]) == 2
    assert body["sources"]  # the Tavily results are still shown, as search results
    assert body["guidance"]["categories"]  # so the human can still build a scenario from guidance defaults


def test_rationale_naming_an_unreturned_url_is_dropped_not_edited(env):
    params = {"rate": {"delta_rate": {"value": 0.005, "rationale": "Per https://made-up.example/r rates rise."},
                       "start_week": {"value": 1, "rationale": "Next reset."}}}
    client, _, _ = make_client(oll=FakeOllama([model_answer(parameters=params)]))
    sug = analyze(client).json()["suggestion"]
    p = {x["param"]: x for x in sug["parameters"]}
    assert p["delta_rate"]["rationale"] is None and "did not return" in p["delta_rate"]["note"]
    assert p["start_week"]["rationale"] == "Next reset."


# --------------------------------------------------------------------------- clamping to guidance + ScenarioShock


def test_out_of_range_values_are_clamped_and_say_so(env):
    params = {"rate": {"delta_rate": {"value": 0.05, "rationale": "huge"},
                       "start_week": {"value": 0, "rationale": "now"}}}
    client, _, _ = make_client(oll=FakeOllama([model_answer(parameters=params)]))
    sug = analyze(client).json()["suggestion"]
    p = {x["param"]: x for x in sug["parameters"]}
    assert p["delta_rate"]["value"] == 0.01 and p["delta_rate"]["source"] == "model_clamped"
    assert p["delta_rate"]["model_value"] == 0.05 and "clamped" in p["delta_rate"]["note"]
    assert p["start_week"]["value"] == 1 and p["start_week"]["source"] == "model_clamped"
    assert sug["shock"]["rate"] == {"delta_rate": 0.01, "start_week": 1}


@pytest.mark.parametrize("value", ["0.5%", None, True, "NaN", [1], {"x": 1}])
def test_unusable_values_fall_back_to_the_guidance_default(env, value):
    params = {"rate": {"delta_rate": {"value": value, "rationale": "r"}}}
    client, _, _ = make_client(oll=FakeOllama([model_answer(parameters=params)]))
    sug = analyze(client).json()["suggestion"]
    p = {x["param"]: x for x in sug["parameters"]}
    assert p["delta_rate"]["value"] == 0.005 and p["delta_rate"]["source"] == "guidance_default"
    assert p["delta_rate"]["model_value"] is None
    # Missing parameter -> default as well.
    assert p["start_week"]["value"] == 1 and p["start_week"]["source"] == "guidance_default"


def test_non_integer_weeks_are_rounded_with_a_note(env):
    params = {"rate": {"delta_rate": {"value": 0.005, "rationale": "r"},
                       "start_week": {"value": 2.6, "rationale": "r"}}}
    client, _, _ = make_client(oll=FakeOllama([model_answer(parameters=params)]))
    p = {x["param"]: x for x in analyze(client).json()["suggestion"]["parameters"]}
    assert p["start_week"]["value"] == 3 and p["start_week"]["source"] == "model_clamped"
    assert "rounded" in p["start_week"]["note"]


def test_parameters_outside_the_category_are_ignored_with_a_note(env):
    params = {"rate": {"delta_rate": {"value": 0.005, "rationale": "r"}, "start_week": {"value": 1, "rationale": "r"}},
              "demand": {"delta": {"value": 0.3, "rationale": "r"}}}
    client, _, _ = make_client(oll=FakeOllama([model_answer(parameters=params)]))
    sug = analyze(client).json()["suggestion"]
    assert sug["shock"]["demand"] is None
    assert "Ignored 1 parameter(s) not listed for this category." in sug["notes"]


@pytest.mark.parametrize("category_id", CATEGORY_IDS)
@pytest.mark.parametrize("extreme", [1e9, -1e9, 0.5])
def test_every_category_clamps_into_guidance_and_simulates(env, category_id, extreme):
    cat = next(c for c in GUIDANCE["categories"] if c["id"] == category_id)
    params = {block: {p: {"value": extreme, "rationale": "r"} for p in ranges}
              for block, ranges in cat["shocks"].items()}
    client, _, _ = make_client(oll=FakeOllama([model_answer(category_id=category_id, parameters=params)]))
    sug = analyze(client).json()["suggestion"]
    assert sug["category_id"] == category_id
    for p in sug["parameters"]:
        assert p["min"] <= p["value"] <= p["max"], p
        if p["integer"]:
            assert p["value"] == int(p["value"])
    shock = ScenarioShock.model_validate(sug["shock"])  # a valid engine input
    for block in ("rate", "demand", "supplier"):
        assert (getattr(shock, block) is not None) == (block in cat["shocks"])
    if shock.demand:
        assert shock.demand.end_week + shock.demand.recovery_weeks <= T
    if shock.supplier:
        assert isinstance(shock.supplier.availability, list) and len(shock.supplier.availability) == T
    assert client.post("/api/simulate", json={"shock": sug["shock"]}).status_code == 200


def test_unknown_or_null_category_gives_no_suggestion(env):
    for cat in ("not-a-category", None):
        client, _, _ = make_client(oll=FakeOllama([model_answer(category_id=cat)]))
        body = analyze(client).json()
        assert body["status"] == "ok" and body["suggestion"] is None
        assert body["evidence"]
        assert any("category" in n.lower() for n in body["notes"])


def test_build_shock_mapping_matches_guidance_file():
    """mapping_to_scenario_shock in the guidance file, for a supplier window."""
    guidance = ea.load_guidance(DATA)
    shock = ea.shock_from_values(
        "x", {"supplier": {"availability_during_outage": 0.2, "start_week": 3, "duration_weeks": 2,
                           "dependent_share": 0.4},
              "demand": {"delta": 0.1, "start_week": 2, "duration_weeks": 4, "recovery_weeks": 3}},
        guidance.horizon_weeks)
    kappa = shock.supplier.availability
    assert kappa[:2] == [1.0, 1.0] and kappa[2:4] == [0.2, 0.2] and kappa[4:] == [1.0] * (T - 4)
    assert (shock.demand.start_week, shock.demand.end_week, shock.demand.recovery_weeks) == (2, 5, 3)


# --------------------------------------------------------------------------- honest failure states


def test_missing_key_is_unavailable_and_calls_nothing(env):
    env.delenv("TAVILY_API_KEY")
    client, tav, oll = make_client()
    resp = analyze(client)
    assert resp.status_code == 503
    assert resp.json()["code"] == "LIVE_EXPLORE_UNAVAILABLE"
    assert resp.json()["errors"][0]["type"] == "not_configured"
    assert tav.calls == [] and oll.requests == []


def test_tavily_upstream_errors_are_typed_and_skip_the_model(env):
    client, _, oll = make_client(tav=FakeTavily(httpx.Response(500)))
    resp = analyze(client)
    assert resp.status_code == 502 and resp.json()["code"] == "LIVE_EXPLORE_UPSTREAM_ERROR"
    assert oll.requests == []


def test_no_tavily_results_skips_the_model(env):
    empty = {"query": "q", "results": [], "response_time": 0.1}
    client, _, oll = make_client(tav=FakeTavily(httpx.Response(200, json=empty)))
    body = analyze(client).json()
    assert body["status"] == "no_sources"
    assert body["sources"] == [] and body["evidence"] == [] and body["suggestion"] is None
    assert body["model"] is None and oll.requests == []


@pytest.mark.parametrize(
    ("oll", "status"),
    [
        (FakeOllama(down=True), "model_unavailable"),
        (FakeOllama(installed=False), "model_unavailable"),
        (FakeOllama(["not json", "still not json"]), "model_output_invalid"),
        (FakeOllama([{"evidence": "nope"}, {"evidence": "nope"}]), "model_output_invalid"),
    ],
)
def test_model_failures_are_reported_with_sources_and_nothing_invented(env, oll, status):
    client, _, _ = make_client(oll=oll)
    resp = analyze(client)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == status and body["status_message"]
    assert body["evidence"] == [] and body["suggestion"] is None and body["model"] is None
    assert [s["url"] for s in body["sources"]] == URLS
    assert body["guidance"]["categories"]


def test_one_schema_repair_then_valid_answer(env):
    oll = FakeOllama(["not json", model_answer()])
    client, _, _ = make_client(oll=oll)
    body = analyze(client).json()
    assert body["status"] == "ok" and body["model"]["attempts"] == 2
    second = oll.prompts()[1]
    assert second.startswith(oll.prompts()[0])  # the repair is the same prompt plus a fixed instruction


def test_model_text_is_never_echoed_on_invalid_output(env):
    secret_text = "MODEL-RAW-" + uuid.uuid4().hex
    client, _, _ = make_client(oll=FakeOllama([secret_text, secret_text]))
    resp = analyze(client)
    assert secret_text not in resp.text


# --------------------------------------------------------------------------- validation, gate, limits


@pytest.mark.parametrize(
    "payload",
    [{}, {"decision_text": ""}, {"decision_text": "   \n "}, {"decision_text": "x" * (explore.MAX_DECISION_CHARS + 1)},
     {"decision_text": "ok", "extra": 1}, {"decision_text": 5}],
)
def test_validation_errors_call_nothing(env, payload):
    client, tav, oll = make_client()
    resp = client.post(PATH, json=payload)
    assert resp.status_code == 422 and resp.json()["code"] == "VALIDATION_ERROR"
    assert tav.calls == [] and oll.requests == []


def test_public_mode_needs_the_admin_token_and_spends_nothing(env):
    env.setenv("FAULTLINE_MODE", "public")
    env.setenv("FAULTLINE_ADMIN_TOKEN", ADMIN)
    client, tav, oll = make_client()
    missing = analyze(client)
    assert missing.status_code == 401 and missing.json()["code"] == "ADMIN_TOKEN_REQUIRED"
    wrong = analyze(client, headers={"Authorization": "Bearer " + "c" * 40})
    assert wrong.status_code == 403 and wrong.json()["code"] == "ADMIN_TOKEN_REQUIRED"
    assert ADMIN not in missing.text + wrong.text
    # The gate runs before body validation.
    assert client.post(PATH, json={}).status_code == 401
    assert tav.calls == [] and oll.requests == []
    ok = analyze(client, headers={"Authorization": f"Bearer {ADMIN}"})
    assert ok.status_code == 200 and ok.json()["status"] == "ok"


def test_rate_limit_is_shared_with_search(env):
    client, _, _ = make_client(oll=FakeOllama([model_answer() for _ in range(3)]))
    client.app.state.faultline_explore = explore.ExploreState(rate_limit_per_min=2)
    assert analyze(client).status_code == 200
    assert client.get("/api/explore/search", params={"q": "x"}).status_code == 200
    limited = analyze(client)
    assert limited.status_code == 429 and limited.json()["code"] == "RATE_LIMITED"
    assert limited.headers.get("retry-after")


def test_repeat_analysis_reuses_the_cached_search(env):
    client, tav, _ = make_client(oll=FakeOllama([model_answer(), model_answer()]))
    first = analyze(client).json()
    second = analyze(client).json()
    assert len(tav.calls) == 1
    assert second["cached"] is True and second["retrieved_at"] == first["retrieved_at"]


def test_openapi_documents_analyze(env):
    client, _, _ = make_client()
    op = client.get("/openapi.json").json()["paths"][PATH]["post"]
    assert {"401", "403", "422", "429", "502", "503", "504"} <= set(op["responses"])


# --------------------------------------------------------------------------- audit of #121: real-model shapes, numbers


def _sources_by_param(sug: dict) -> dict[str, str]:
    return {f"{p['block']}.{p['param']}": p["source"] for p in sug["parameters"]}


REAL_SHAPES = {
    # What llama3.1:8b actually returned in 4 of 4 audit runs: wrapped in the category id, dotted names.
    "category-wrapped dotted": {"central-bank-rate-surprise": {
        "rate.delta_rate": {"value": 0.0075, "rationale": "r"}, "rate.start_week": {"value": 3, "rationale": "r"}}},
    "dotted": {"rate.delta_rate": {"value": 0.0075, "rationale": "r"}, "rate.start_week": {"value": 3}},
    "category-wrapped nested": {"central-bank-rate-surprise": {"rate": {
        "delta_rate": {"value": 0.0075, "rationale": "r"}, "start_week": {"value": 3, "rationale": "r"}}}},
    "nested with dotted inner": {"rate": {"rate.delta_rate": {"value": 0.0075}, "rate.start_week": {"value": 3}}},
    "bare parameter names": {"delta_rate": {"value": 0.0075}, "start_week": 3},
}


@pytest.mark.parametrize("shape", list(REAL_SHAPES))
def test_model_parameter_shapes_are_normalized_and_still_clamped(env, shape):
    client, _, _ = make_client(oll=FakeOllama([model_answer(parameters=REAL_SHAPES[shape])]))
    sug = analyze(client).json()["suggestion"]
    assert _sources_by_param(sug) == {"rate.delta_rate": "model", "rate.start_week": "model"}, shape
    assert sug["shock"]["rate"] == {"delta_rate": 0.0075, "start_week": 3}
    assert sug["label"] == "MODEL-SUGGESTED, HUMAN TO CONFIRM" and sug["values_from_model"] == 2


def test_normalized_values_are_clamped_like_any_other(env):
    params = {"central-bank-rate-surprise": {"rate.delta_rate": {"value": 0.5}, "rate.start_week": {"value": 99}}}
    client, _, _ = make_client(oll=FakeOllama([model_answer(parameters=params)]))
    sug = analyze(client).json()["suggestion"]
    assert sug["shock"]["rate"] == {"delta_rate": 0.01, "start_week": 7}
    assert set(_sources_by_param(sug).values()) == {"model_clamped"}


def test_no_usable_model_number_is_labeled_guidance_defaults_not_model_suggested(env):
    """B1: when every value is the guidance default, the suggestion must not claim to be the model's."""
    params = {"credit-tightening": {"some.thing": {"value": "half a point"}}}
    client, _, _ = make_client(oll=FakeOllama([model_answer(parameters=params)]))
    sug = analyze(client).json()["suggestion"]
    assert set(_sources_by_param(sug).values()) == {"guidance_default"}
    assert sug["label"] == "GUIDANCE DEFAULTS, HUMAN TO CONFIRM" and sug["values_from_model"] == 0
    assert sug["notes"][0] == "The model gave no usable numbers; these are guidance defaults."
    assert "MODEL-SUGGESTED" not in json.dumps(sug)
    assert "(model-suggested)" not in sug["shock"]["name"]


def test_one_model_number_is_enough_for_model_suggested(env):
    params = {"rate": {"delta_rate": {"value": 0.0075}}}
    client, _, _ = make_client(oll=FakeOllama([model_answer(parameters=params)]))
    sug = analyze(client).json()["suggestion"]
    assert sug["label"] == "MODEL-SUGGESTED, HUMAN TO CONFIRM" and sug["values_from_model"] == 1
    assert _sources_by_param(sug) == {"rate.delta_rate": "model", "rate.start_week": "guidance_default"}


def test_huge_integer_value_is_invalid_not_a_500(env):
    """S1: float(10**400) raises OverflowError; it must count as no usable number."""
    raw = json.dumps(model_answer()).replace('"value": 0.005', '"value": ' + "9" * 400)
    assert "9" * 400 in raw
    client, _, _ = make_client(oll=FakeOllama([raw]))
    resp = analyze(client)
    assert resp.status_code == 200, resp.text
    p = {x["param"]: x for x in resp.json()["suggestion"]["parameters"]}
    assert p["delta_rate"]["source"] == "guidance_default" and p["delta_rate"]["model_value"] is None


def test_model_written_parameter_keys_are_never_echoed(env):
    """S2: notes count ignored keys; they never repeat model text (which could carry spoofed labels)."""
    spoof = "OFFICIAL: emergency 150bp hike (REAL HISTORICAL, RECORDED RUN)"
    params = {"rate": {"delta_rate": {"value": 0.005}, spoof: 1}, spoof: {"x": 1}}
    client, _, _ = make_client(oll=FakeOllama([model_answer(parameters=params)]))
    resp = analyze(client)
    assert spoof not in resp.text and "REAL HISTORICAL" not in resp.text
    assert "Ignored 2 parameter(s) not listed for this category." in resp.json()["suggestion"]["notes"]


@pytest.mark.parametrize(
    ("claim", "ok"),
    [
        ("The central bank raised rates by 300 basis points and deposits fell 90%.", False),  # snippet says 50
        ("The central bank raised its policy rate by 50 basis points.", True),
        ("The central bank raised its policy rate by 50 basis points in 2026.", False),  # 2026 is not in the source
        ("The central bank raised its policy rate by fifty basis points.", True),  # words are not checked (limit)
        ("Per S1, the central bank raised its policy rate by 50 basis points.", True),  # a source id is no figure
    ],
)
def test_numbers_in_a_claim_must_appear_in_the_cited_source(env, claim, ok):
    """B2: a valid URL does not make an invented figure evidence."""
    client, _, _ = make_client(oll=FakeOllama([model_answer(evidence=[{"claim": claim, "source_url": URLS[0]}])]))
    body = analyze(client).json()
    if ok:
        assert [c["claim"] for c in body["evidence"]] == [claim]
    else:
        assert body["evidence"] == [] and body["status"] == "no_cited_evidence"
        assert [r["reason"] for r in body["rejected_claims"]] == ["number_not_in_source"]


def test_number_check_reads_the_cited_source_not_any_source():
    src = [ea.PromptSource("S1", "https://a.example/x", "Rates up", "Rates rose 50 basis points.", None),
           ea.PromptSource("S2", "https://b.example/y", "Footfall", "Footfall fell 4% on 1,200 stores.", None)]
    claims = [ea.ModelClaim(claim="Footfall fell 4% across 1200 stores.", source_url="https://b.example/y"),
              ea.ModelClaim(claim="Footfall fell 4%.", source_url="https://a.example/x")]
    accepted, rejected = ea.review_claims(claims, src)
    assert [a.source.source_id for a in accepted] == ["S2"]  # 1,200 == 1200
    assert [r.reason for r in rejected] == ["number_not_in_source"]


@pytest.mark.parametrize(
    ("claim", "reason"),
    [
        ("Per evil.com the central bank moved.", "unknown_url_in_text"),
        ("See www.evil.com for the central bank move.", "unknown_url_in_text"),
        ("See \uff48\uff54\uff54\uff50\uff53://evil.com/x for the move.", "unknown_url_in_text"),  # full-width
        ("See hxxps://evil.com/x for the move.", "unknown_url_in_text"),
        ("[Central bank moved](javascript:alert(1))", "unknown_url_in_text"),
        ("data:text/html,<script>alert(1)</script>", "unknown_url_in_text"),
        ("see ftp://evil.com/x", "unknown_url_in_text"),
        (f"see {URLS[0]}.evil.com/x", "unknown_url_in_text"),
        (f"see {URLS[0]}@evil.com", "unknown_url_in_text"),
        ("See https\u200b://evil.com/x", "hidden_characters"),
        ("Rates \u202eesir\u202c moved.", "hidden_characters"),
    ],
)
def test_folded_urls_domains_and_hidden_characters_are_rejected(env, claim, reason):
    """S3: NFKC folding and Cf stripping before the URL check; host-like tokens must be a returned host."""
    client, _, _ = make_client(oll=FakeOllama([model_answer(evidence=[{"claim": claim, "source_url": URLS[0]}])]))
    body = analyze(client).json()
    assert body["evidence"] == []
    assert [r["reason"] for r in body["rejected_claims"]] == [reason]


def test_a_returned_url_or_host_may_be_named_in_the_claim(env):
    host = URLS[0].split("/")[2]
    claims = [{"claim": f"As {URLS[0]} reports, the central bank raised its policy rate.", "source_url": URLS[0]},
              {"claim": f"{host} reports officials signalled further increases.", "source_url": URLS[1]}]
    client, _, _ = make_client(oll=FakeOllama([model_answer(evidence=claims)]))
    body = analyze(client).json()
    assert len(body["evidence"]) == 2, body["rejected_claims"]


def test_explore_context_window_is_16k(env):
    """S5: five 1200-character snippets plus the menu and a repair turn need more than the replay's 8192."""
    client, _, oll = make_client()
    analyze(client)
    assert oll.chat_bodies()[0]["options"]["num_ctx"] == ea.ANALYST_NUM_CTX == 16384


def test_prompt_shows_a_nested_parameter_skeleton_not_dotted_names():
    prompt = ea.render_prompt(DECISION, [ea.PromptSource("S1", URLS[0], "t", "s", None)], ea.load_guidance(DATA))
    assert "rate.delta_rate" not in prompt and "do not join names with dots" in prompt
    assert '"<block>": {' in prompt and '"<parameter>": {"value": <number>' in prompt


@pytest.mark.skipif(os.environ.get("FAULTLINE_REAL_OLLAMA") != "1", reason="LOCAL ONLY: set FAULTLINE_REAL_OLLAMA=1")
def test_local_only_real_model_numbers_are_the_models(env):
    """LOCAL ONLY, never in CI: the real configured Ollama model (no transport override) on realistic SYNTHETIC
    snippets. Its suggestion must carry at least one number that is the model's own (B1), and every card must pass
    the citation and number checks (they are re-run here against the sources)."""
    snippets = [
        ("Fed raises rates by half a point", "https://news-a.example/fed-raises-rates",
         "The Federal Reserve raised its benchmark rate by 50 basis points on Tuesday, a larger move than the 25 "
         "basis points most economists expected, citing persistent services inflation."),
        ("Small businesses brace for higher loan costs", "https://news-b.example/small-business-loans",
         "Owners of small firms with floating-rate loans said monthly payments would rise; a survey found 38% plan "
         "to delay expansion."),
    ]
    payload = {"query": "q", "results": [{"title": t, "url": u, "content": c, "score": 0.8,
                                          "published_date": "Tue, 10 Nov 2026 14:00:00 GMT"} for t, u, c in snippets],
               "response_time": 0.1}
    app = create_app()
    app.dependency_overrides[explore.get_tavily_transport] = lambda: httpx.MockTransport(
        FakeTavily(httpx.Response(200, json=payload)))
    resp = TestClient(app).post(PATH, json={"decision_text": DECISION})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "ok", body["status_message"]
    sources = {s["url"]: s for s in body["sources"]}
    for card in body["evidence"]:
        src = sources[card["source_url"]]
        assert ea.numbers_not_in_source(card["claim"], ea.PromptSource(src["source_id"], src["url"], src["title"],
                                                                       src["snippet"], None), sources) == []
    sug = body["suggestion"]
    assert sug is not None, body["notes"]
    assert any(p["source"] == "model" for p in sug["parameters"]), sug["parameters"]
    assert sug["label"] == "MODEL-SUGGESTED, HUMAN TO CONFIRM"


def test_provenance_labels_in_model_text_are_refused(env):
    """Model text may not carry REAL HISTORICAL / RECORDED RUN (a label spoof): the claim is rejected and the
    rationale dropped, never shown."""
    claims = [{"claim": "Recorded run: the central bank raised its policy rate.", "source_url": URLS[0]},
              {"claim": "Officials signalled further increases.", "source_url": URLS[1]}]
    params = {"rate": {"delta_rate": {"value": 0.005, "rationale": "REAL_HISTORICAL: rates will rise."}}}
    client, _, _ = make_client(oll=FakeOllama([model_answer(evidence=claims, parameters=params)]))
    resp = analyze(client)
    body = resp.json()
    assert [r["reason"] for r in body["rejected_claims"]] == ["provenance_label"]
    p = {x["param"]: x for x in body["suggestion"]["parameters"]}
    assert p["delta_rate"]["rationale"] is None and "provenance label" in p["delta_rate"]["note"]
    shown = json.dumps({k: v for k, v in body.items() if k != "rejected_claims"})
    assert "REAL_HISTORICAL" not in shown and "Recorded run" not in shown
