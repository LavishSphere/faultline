"""POST /api/explore/analyze (issue #61): decision -> Tavily -> local model -> cited evidence + suggested shock.

Mocked Tavily and mocked Ollama transports only: no network, no real key, no real model.

What is pinned here:
- Isolation: the model's prompt holds the decision text, the fixed instructions (including the ILLUSTRATIVE
  guidance ranges) and the Tavily results for this request, and nothing else. A canary planted in replay data
  (demo case evidence and a sealed outcome) never reaches the prompt or the response.
- Citations: every evidence card cites a URL Tavily actually returned for this request; uncited claims, unknown
  URLs (including near misses), and claims naming a URL that was not returned are rejected with a reason. Card
  snippets and retrieved_at come from Tavily, never from the model.
- Suggestion: every number is clamped to the finance owner's guidance range for its category (and so to a valid
  ScenarioShock), is labeled MODEL-SUGGESTED, HUMAN TO CONFIRM, and the resulting shock is accepted by
  /api/simulate. The analyze route itself never simulates.
- Honest failure: missing key -> 503 LIVE_EXPLORE_UNAVAILABLE; model down / invalid output -> a 200 that says so,
  with the Tavily sources and no evidence cards or suggestion; never a canned answer.
- Labels: LIVE EXPLORE everywhere; never REAL HISTORICAL or RECORDED RUN.
"""

from __future__ import annotations

import json
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
    assert sug["label"] == "MODEL-SUGGESTED, HUMAN TO CONFIRM"
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
    claims = [{"claim": f"Claim number {i} about the rate move.", "source_url": URLS[i % 3]}
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
    assert any("demand.delta" in n for n in sug["notes"])


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
