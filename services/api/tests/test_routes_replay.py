"""POST /api/replay/run and POST /api/replay/{prediction_id}/reveal (issue #44), plus the pre-reveal leakage walk.

Written before routes/replay.py. All fixtures are SYNTHETIC. The model is a mocked Ollama HTTP transport
(tests/test_agents_local_ollama.FakeOllama); no test here calls a real model, except the one LOCAL-ONLY test at
the bottom, which is skipped unless FAULTLINE_REAL_OLLAMA=1.

Leakage is checked four ways:
- every route under /api/cases and /api/replay must be classified pre- or post-reveal (a tripwire for new routes);
- the OpenAPI schemas of every pre-reveal response (success and error) have no outcome-like property names;
- the JSON of every pre-reveal endpoint, before and after a reveal, has no outcome-like key, no canary and no
  sealed value;
- no pre-reveal request opens a file under sealed_outcomes/ (the probe is shown to work on the reveal route).
"""

from __future__ import annotations

import builtins
import json
import math
import os
import pathlib
import re
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from test_agents_local_ollama import DIGEST, FakeOllama
from test_temporal_gate import AS_OF, EVENT, evidence_dict, make_case, quote_dict

from agents.local_ollama import DEFAULT_NUM_CTX, DEFAULT_NUM_PREDICT, DEFAULT_SEED, LocalOllamaProvider
from core import provenance
from core import store as store_module
from core.evaluator import OutcomeVault, build_scorecard
from core.store import PredictionStore, record_sha256
from core.temporal_gate import EvidenceStore
from main import create_app
from markets.base import MARKET_LABEL
from routes import replay

OUTCOME_LIKE = re.compile(r"outcome|resolution|resolved|settle|result|winner|final_price", re.IGNORECASE)
CANARY = f"CANARY-{uuid.uuid4()}"
SEALED_RESOLVED_AT = "2025-01-22T19:07:00+00:00"  # exists only in the sealed file
MARKET_REF = "kalshi:SYNTH-FED-H25"

ANSWER = {
    "p_yes": 0.7,
    "decision": "hedge",
    "rationale": "Minutes signal patience on rates (evid_ok). The statement at the cutoff is cautious (evid_edge).",
    "evidence_ids": ["evid_ok", "evid_edge"],
}

# /api/integrity (#81) is pre-reveal too: it reports checks about a case and run, never the outcome.
PRE_REVEAL = {
    ("get", "/api/cases"),
    ("get", "/api/cases/{case_id}/evidence"),
    ("post", "/api/replay/run"),
    ("get", "/api/integrity"),
}
POST_REVEAL = {("post", "/api/replay/{prediction_id}/reveal")}
# /api/explore/search and /api/explore/analyze are LIVE EXPLORE (#60, #61): current web search and a local-model
# reading of it, walled off from the replay by tests/test_explore_separation.py (no replay module may reference
# them, and they serve no case or outcome data).
# /api/judge-challenges (#123) serves ILLUSTRATIVE shocks for the demo business; no case or outcome data.
NOT_REPLAY = {
    "/api/health",
    "/api/simulate",
    "/api/optimize",
    "/api/scenarios",
    "/api/vc-lenses",
    # routes/decision.py (#55): SYNTHETIC business payoffs from decision_frames.json; never reads cases or outcomes.
    "/api/decision",
    "/api/decision/frames",
    "/api/explore/search",
    "/api/explore/analyze",
    "/api/judge-challenges",
}
# routes/benchmark.py (tests/test_routes_benchmark*.py): GET serves recorded post-reveal scorecards, read-only (it
# never reveals and never opens the store or sealed folder); compute reveals and is admin-only in public mode.
BENCHMARK_POST_REVEAL_READ_ONLY = {("get", "/api/benchmark")}
BENCHMARK_ADMIN_REVEALS = {("post", "/api/benchmark/compute")}

RUN_KEYS = {
    "prediction", "skeptic", "market_at_cutoff", "persisted_at", "persist_seq", "record_sha256",
    "event_first_reveal_seq", "persisted_after_event_reveal", "store_first_reveal_seq", "persisted_after_any_reveal",
    "audit_note",
}
REVEAL_KEYS = {
    "prediction", "y", "sealed", "revealed_at", "persisted_at", "persist_seq", "reveal_seq",
    "event_first_revealed_at", "event_first_reveal_seq", "persisted_before_outcome_revealed", "scores", "baselines",
}


# ---------------------------------------------------------------- fixtures (also used by test_routes_replay_*.py)


def gate_case_file(event_id: str = EVENT, *, quotes: bool = True, **case_overrides) -> dict:
    """A SYNTHETIC case file in the temporal gate's format. The canary sits ONLY in items the gate must exclude."""
    case = make_case(event_id, **case_overrides).model_dump(mode="json")
    evidence = [
        evidence_dict("evid_ok", AS_OF - timedelta(days=5), "Minutes signal patience on rates.", event_id=event_id),
        evidence_dict("evid_edge", AS_OF, "Statement released exactly at the cutoff.", event_id=event_id),
        evidence_dict("evid_future", AS_OF + timedelta(minutes=1), f"FUTURE: decided. {CANARY}", event_id=event_id),
        evidence_dict(
            "evid_unverified",
            AS_OF - timedelta(days=2),
            f"Undated page. {CANARY}",
            event_id=event_id,
            retrospective_unverified=True,
        ),
    ]
    market = (
        [
            quote_dict(AS_OF - timedelta(hours=30), "0.4000"),
            quote_dict(AS_OF - timedelta(hours=2), "0.5600"),
            quote_dict(AS_OF + timedelta(hours=1), "0.9000"),
        ]
        if quotes
        else []
    )
    return {"case": case, "evidence": evidence, "market_quotes": market}


def sealed_file(event_id: str = EVENT, outcome: str = "YES") -> dict:
    return {
        "event_id": event_id,
        "outcome": outcome,
        "resolved_at": SEALED_RESOLVED_AT,
        "source_url": "https://example.org/settlement",
        "provenance": "SYNTHETIC",
        "notes": CANARY,
    }


@dataclass
class World:
    data: Path
    db: Path
    fake: FakeOllama
    provider_kwargs: dict = field(default_factory=dict)
    provider: object | None = None

    def client(self) -> TestClient:
        app = create_app()
        app.dependency_overrides[replay.get_provider] = lambda: (
            self.provider if self.provider is not None else self.fake.provider(**self.provider_kwargs)
        )
        return TestClient(app)

    def write_case(self, payload: dict) -> Path:
        path = self.data / "demo_cases" / f"{payload['case']['event_id']}.json"
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return path

    def records(self) -> list:
        return PredictionStore(self.db).all_records() if self.db.exists() else []

    def model_input(self, variant: str, event_id: str = EVENT):
        cases = EvidenceStore.from_dir(self.data / "demo_cases")
        return cases.get_as_of(event_id, cases.public_case(event_id).as_of).model_input(variant)


def make_world(tmp_path: Path, monkeypatch, answers: list[str] | None = None, **case_kwargs) -> World:
    data = tmp_path / "data"
    (data / "demo_cases").mkdir(parents=True)
    (data / "sealed_outcomes").mkdir()
    (data / "sealed_outcomes" / f"{EVENT}.json").write_text(json.dumps(sealed_file()), encoding="utf-8")
    db = tmp_path / "var" / "predictions.sqlite3"
    monkeypatch.setenv("FAULTLINE_DATA_DIR", str(data))
    monkeypatch.setenv("FAULTLINE_PREDICTIONS_DB", str(db))
    world = World(data=data, db=db, fake=FakeOllama(answers if answers is not None else [json.dumps(ANSWER)] * 8))
    world.write_case(gate_case_file(**case_kwargs))
    return world


@pytest.fixture
def world(tmp_path, monkeypatch) -> World:
    return make_world(tmp_path, monkeypatch)


def outcome_keys(node, path: str = "$") -> list[str]:
    found = []
    if isinstance(node, dict):
        for k, v in node.items():
            if OUTCOME_LIKE.search(str(k)):
                found.append(f"{path}.{k}")
            found += outcome_keys(v, f"{path}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            found += outcome_keys(v, f"{path}[{i}]")
    return found


def assert_pre_reveal_clean(resp) -> None:
    assert CANARY not in resp.text
    assert SEALED_RESOLVED_AT not in resp.text and "2025-01-22T19:07" not in resp.text
    assert outcome_keys(resp.json()) == [], resp.text


def run(client: TestClient, variant: str = "agent_only", case_id: str = EVENT):
    return client.post("/api/replay/run", json={"case_id": case_id, "variant": variant})


def sha(text: str) -> str:
    return provenance.sha256_hex(text)


# ---------------------------------------------------------------- run: happy path


def test_run_persists_before_reveal_and_returns_no_outcome(world):
    resp = run(world.client())
    assert resp.status_code == 200, resp.text
    assert_pre_reveal_clean(resp)
    body = resp.json()
    assert set(body) == RUN_KEYS
    p = body["prediction"]
    assert p["event_id"] == EVENT and p["variant"] == "agent_only"
    assert p["p_yes"] == 0.7 and p["decision"] == "hedge"
    assert p["evidence_ids"] == ["evid_ok", "evid_edge"]
    assert p["provenance"] == "RECORDED_RUN"
    assert p["agent_model"] == "ollama/llama3.1:8b" and p["model_digest"] == DIGEST
    assert p["temperature"] == 0.0 and p["seed"] == DEFAULT_SEED
    assert (p["attempts"], p["num_ctx"], p["num_predict"]) == (1, DEFAULT_NUM_CTX, DEFAULT_NUM_PREDICT)

    # Persisted, with intact hashes, before anything was revealed.
    [rec] = world.records()
    assert rec.prediction.prediction_id == p["prediction_id"]
    assert PredictionStore(world.db).verify(p["prediction_id"]) == []
    assert PredictionStore(world.db).first_reveal(EVENT) is None
    assert body["persist_seq"] == rec.persist_seq and body["record_sha256"] == rec.record_sha256
    assert body["event_first_reveal_seq"] is None and body["store_first_reveal_seq"] is None
    assert body["persisted_after_event_reveal"] is False and body["persisted_after_any_reveal"] is False
    assert body["audit_note"] is None

    # The model got exactly the gated prompt: one user message, no canary, no market for agent_only.
    [chat] = world.fake.chat_bodies()
    assert [m["role"] for m in chat["messages"]] == ["user"]
    sent = chat["messages"][0]["content"]
    mi = world.model_input("agent_only")
    assert sent == mi.prompt
    assert CANARY not in sent and "Market input" not in sent
    assert p["prompt_sha256"] == sha(sent) == p["gated_prompt_sha256"] == mi.prompt_sha256
    assert p["snapshot_sha256"] == mi.snapshot_sha256
    assert p["transcript_sha256"] == sha(provenance.canonical_json(chat["messages"]))

    # Market-implied probability at the cutoff, from the gate (the 2h-old quote; never the post-cutoff one).
    m = body["market_at_cutoff"]
    assert m["status"] == "AVAILABLE" and m["ref"] == MARKET_REF and m["p_yes"] == 0.56
    assert m["venue"] == "kalshi" and m["quote_kind"] == "candle_close" and m["provenance"] == "SYNTHETIC"
    assert "price-derived" in m["label"] and "market-implied" in m["label"]
    assert m["ts"].replace("Z", "+00:00") == (AS_OF - timedelta(hours=2)).isoformat()


def test_agent_plus_market_sees_only_the_as_of_quote_and_is_distinct(world):
    client = world.client()
    only, plus = run(client, "agent_only").json(), run(client, "agent_plus_market")
    assert plus.status_code == 200, plus.text
    assert_pre_reveal_clean(plus)
    plus = plus.json()
    assert plus["prediction"]["variant"] == "agent_plus_market"
    assert plus["prediction"]["snapshot_sha256"] != only["prediction"]["snapshot_sha256"]
    assert plus["prediction"]["prediction_id"] != only["prediction"]["prediction_id"]
    sent = world.fake.chat_bodies()[-1]["messages"][0]["content"]
    assert "Market input" in sent and '"p_yes": 0.56' in sent
    assert "0.9" not in sent and "0.4" not in sent  # post-cutoff and stale quotes never reach the prompt
    assert plus["market_at_cutoff"]["p_yes"] == only["market_at_cutoff"]["p_yes"] == 0.56


def test_skeptic_warnings_are_returned_with_the_forecast(world):
    uncited = {**ANSWER, "rationale": "Rates look steady overall. Minutes signal patience (evid_ok, evid_edge)."}
    world.fake.chat_contents = [json.dumps(uncited)]
    resp = run(world.client())
    assert resp.status_code == 200, resp.text
    problems = resp.json()["skeptic"]["problems"]
    assert {p["code"] for p in problems} == {"UNCITED_CLAIM"}
    assert all(p["severity"] == "warning" for p in problems)


# ---------------------------------------------------------------- what the model saw is what gets hashed


def test_repair_attempt_recomputes_every_hash(world):
    world.fake.chat_contents = ["RAW-NOT-JSON", json.dumps(ANSWER)]
    resp = run(world.client(), "agent_plus_market")
    assert resp.status_code == 200, resp.text
    assert "RAW-NOT-JSON" not in resp.text
    p = resp.json()["prediction"]
    assert p["attempts"] == 2

    first, second = world.fake.chat_bodies()
    gated, final = first["messages"][0]["content"], second["messages"][0]["content"]
    mi = world.model_input("agent_plus_market")
    assert gated == mi.prompt
    assert final.startswith(gated) and final != gated
    # prompt_sha256 is what the model answered; the gate's prompt hash is kept separately.
    assert p["prompt_sha256"] == sha(final) != p["gated_prompt_sha256"]
    assert p["gated_prompt_sha256"] == sha(gated) == mi.prompt_sha256
    assert p["transcript_sha256"] == sha(provenance.canonical_json(second["messages"]))
    assert p["transcript_sha256"] == provenance.transcript_sha256(final)
    assert p["snapshot_sha256"] == sha(mi.snapshot_json) == mi.snapshot_sha256
    assert p["model_digest"] == DIGEST

    store = PredictionStore(world.db)
    rec = store.get_record(p["prediction_id"])
    assert rec.prompt == gated and rec.model_prompt == final and rec.snapshot_json == mi.snapshot_json
    assert record_sha256(rec.prediction, rec.context, rec.persisted_at, rec.persist_seq) == rec.record_sha256
    assert resp.json()["record_sha256"] == rec.record_sha256
    assert store.verify(p["prediction_id"]) == []


def test_repaired_forecast_is_scored_not_context_mismatch(world):
    """Re-deriving the input from the case files compares the GATED prompt hash, not the repaired one."""
    world.fake.chat_contents = ["RAW-NOT-JSON", json.dumps(ANSWER)]
    pid = run(world.client()).json()["prediction"]["prediction_id"]
    cards = build_scorecard(
        OutcomeVault(PredictionStore(world.db)), agent_variant="agent_only", cases=EvidenceStore.from_dir()
    )
    assert [x.reason for x in cards.exclusions] == []
    assert [e.prediction_ids for e in cards.per_event] == [[pid]]


# ---------------------------------------------------------------- run: errors (never persisted, never a forecast)


def _down(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("connection refused", request=request)


@pytest.mark.parametrize(
    ("setup", "status", "code"),
    [
        ("down", 503, "MODEL_UNAVAILABLE"),
        ("not_installed", 503, "MODEL_UNAVAILABLE"),
        ("invalid_twice", 422, "MODEL_OUTPUT_INVALID"),
        ("no_prompt_count", 422, "PROMPT_NOT_VERIFIED"),
        ("too_long", 422, "PROMPT_TOO_LONG"),
    ],
)
def test_provider_errors_are_coded_and_never_persisted(world, setup, status, code):
    if setup == "down":
        world.provider = LocalOllamaProvider("http://ollama.test", "llama3.1:8b", transport=httpx.MockTransport(_down))
    elif setup == "not_installed":
        world.fake.tags = []
    elif setup == "invalid_twice":
        world.fake.chat_contents = ["RAW-OUTPUT-1", "RAW-OUTPUT-2"]
    elif setup == "no_prompt_count":
        world.fake.counts = [None]
    elif setup == "too_long":
        world.provider_kwargs = {"num_ctx": 700, "num_predict": 100}
    resp = run(world.client())
    assert resp.status_code == status, resp.text
    body = resp.json()
    assert body["code"] == code and set(body) == {"code", "message", "errors"}
    assert "RAW-OUTPUT" not in resp.text and "p_yes" not in resp.text
    assert_pre_reveal_clean(resp)
    assert world.records() == []


def test_skeptic_rejection_is_422_and_not_persisted(world):
    invented = {**ANSWER, "rationale": "Minutes signal patience (evid_ok). A leaked memo says so (evid_zzz)."}
    world.fake.chat_contents = [json.dumps(invented)]
    resp = run(world.client())
    assert resp.status_code == 422, resp.text
    body = resp.json()
    assert body["code"] == "MODEL_OUTPUT_INVALID"
    assert [e["type"] for e in body["errors"]] == ["UNKNOWN_CITED_ID"]
    assert "evid_zzz" not in resp.text and "leaked memo" not in resp.text  # the rejected answer is not echoed
    assert_pre_reveal_clean(resp)
    assert world.records() == []


@pytest.mark.parametrize(
    ("payload", "status", "code"),
    [
        ({"case_id": "no_such_case", "variant": "agent_only"}, 404, "NOT_FOUND"),
        ({"case_id": EVENT, "variant": "hosted_comparator"}, 422, "VALIDATION_ERROR"),
        ({"case_id": EVENT, "variant": "agent_with_answers"}, 422, "VALIDATION_ERROR"),
        ({"case_id": EVENT}, 422, "VALIDATION_ERROR"),
        ({"case_id": EVENT, "variant": "agent_only", "as_of": "2030-01-01T00:00:00Z"}, 422, "VALIDATION_ERROR"),
    ],
)
def test_bad_run_requests_never_call_the_model(world, payload, status, code):
    resp = world.client().post("/api/replay/run", json=payload)
    assert resp.status_code == status, resp.text
    assert resp.json()["code"] == code
    assert world.fake.requests == []
    assert world.records() == []


def test_no_cases_directory_is_not_found(world):
    (world.data / "demo_cases" / f"{EVENT}.json").unlink()
    (world.data / "demo_cases").rmdir()
    resp = run(world.client())
    assert resp.status_code == 404 and resp.json()["code"] == "NOT_FOUND"
    assert world.fake.requests == []


def test_agent_plus_market_without_fresh_quote_is_insufficient_data(tmp_path, monkeypatch):
    world = make_world(tmp_path, monkeypatch, quotes=False)
    client = world.client()
    resp = run(client, "agent_plus_market")
    assert resp.status_code == 422 and resp.json()["code"] == "INSUFFICIENT_DATA"
    assert world.fake.requests == [] and world.records() == []
    only = run(client, "agent_only")
    assert only.status_code == 200, only.text
    m = only.json()["market_at_cutoff"]
    assert m["status"] == "NOT AVAILABLE" and m["p_yes"] is None and m["ts"] is None and m["note"]


# ---------------------------------------------------------------- run after a reveal: flagged, still persisted


def test_run_after_this_events_reveal_is_flagged_not_refused(world):
    client = world.client()
    first = run(client).json()["prediction"]["prediction_id"]
    reveal_seq = client.post(f"/api/replay/{first}/reveal").json()["reveal_seq"]
    resp = run(client, "agent_plus_market")
    assert resp.status_code == 200, resp.text
    assert_pre_reveal_clean(resp)
    body = resp.json()
    assert body["event_first_reveal_seq"] == body["store_first_reveal_seq"] == reveal_seq < body["persist_seq"]
    assert body["persisted_after_event_reveal"] is True and body["persisted_after_any_reveal"] is True
    assert "not a blind forecast" in body["audit_note"]
    store = PredictionStore(world.db)
    assert store.verify(body["prediction"]["prediction_id"]) == []  # persisted as usual
    cards = build_scorecard(OutcomeVault(store), agent_variant="agent_plus_market", cases=EvidenceStore.from_dir())
    assert [x.reason for x in cards.exclusions] == ["persisted_after_outcome_revealed"]


def test_run_after_another_events_reveal_is_flagged(world):
    other = "synthetic_fed_002"
    world.write_case(gate_case_file(other))
    (world.data / "sealed_outcomes" / f"{other}.json").write_text(json.dumps(sealed_file(other)), encoding="utf-8")
    client = world.client()
    pid = run(client, case_id=other).json()["prediction"]["prediction_id"]
    reveal_seq = client.post(f"/api/replay/{pid}/reveal").json()["reveal_seq"]
    body = run(client).json()
    assert body["event_first_reveal_seq"] is None and body["persisted_after_event_reveal"] is False
    assert body["store_first_reveal_seq"] == reveal_seq and body["persisted_after_any_reveal"] is True
    assert "cannot be OFFICIAL" in body["audit_note"]


# ---------------------------------------------------------------- run: store refusals are coded, never echoed


def test_prediction_id_collision_is_409_prediction_exists(world, monkeypatch):
    class Fixed:
        hex = "0" * 32

    monkeypatch.setattr(replay, "uuid4", lambda: Fixed())
    client = world.client()
    assert run(client).status_code == 200
    resp = run(client)
    assert resp.status_code == 409 and resp.json()["code"] == "PREDICTION_EXISTS"
    assert "already persisted" in resp.json()["message"] and "pred_" not in resp.json()["message"]
    assert len(world.records()) == 1


def test_hash_mismatch_on_save_is_500_data_invalid_without_echo(world, monkeypatch):
    def refuse(self, *args, **kwargs):
        raise store_module.HashMismatch("prompt_sha256 SECRET-DETAIL-XYZ")

    monkeypatch.setattr(PredictionStore, "save", refuse)
    resp = run(world.client())
    assert resp.status_code == 500 and resp.json()["code"] == "DATA_INVALID"
    assert "SECRET-DETAIL-XYZ" not in resp.text and "p_yes" not in resp.text


def test_reveal_does_not_call_other_value_errors_a_sealed_file_problem(world, monkeypatch):
    client = world.client()
    pid = run(client).json()["prediction"]["prediction_id"]

    def broken(self, prediction_id):
        raise ValueError("unrelated failure")

    monkeypatch.setattr(OutcomeVault, "reveal", broken)
    app = create_app()
    resp = TestClient(app, raise_server_exceptions=False).post(f"/api/replay/{pid}/reveal")
    assert resp.status_code == 500
    assert "sealed outcome" not in resp.text


# ---------------------------------------------------------------- reveal


def test_reveal_contract_and_scores(world):
    client = world.client()
    pred = run(client, "agent_plus_market").json()["prediction"]
    resp = client.post(f"/api/replay/{pred['prediction_id']}/reveal")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body) == REVEAL_KEYS
    assert body["prediction"] == pred
    assert body["y"] == 1 and body["sealed"]["outcome"] == "YES" and body["sealed"]["provenance"] == "SYNTHETIC"
    assert body["persisted_before_outcome_revealed"] is True
    assert body["persist_seq"] < body["reveal_seq"] == body["event_first_reveal_seq"]

    assert set(body["scores"]) == {"brier", "log_loss", "accuracy_at_0_5"}
    assert body["scores"]["brier"] == pytest.approx((0.7 - 1) ** 2)
    assert body["scores"]["log_loss"] == pytest.approx(-math.log(0.7))
    assert body["scores"]["accuracy_at_0_5"] == 1.0
    assert set(body["baselines"]) == {"market", "naive"}
    market, naive = body["baselines"]["market"], body["baselines"]["naive"]
    assert set(market) == {"p_yes", "brier", "log_loss", "label", "ref"} and set(naive) == {"brier", "log_loss"}
    assert market["p_yes"] == 0.56  # the gate's pre-reveal baseline, not anything chosen now
    # The ref frozen in the prediction context before reveal, and the label that ref implies (#117).
    frozen = PredictionStore(world.db).get_record(pred["prediction_id"]).context.market_baseline_ref
    assert market["ref"] == frozen == MARKET_REF
    assert market["label"] == MARKET_LABEL
    assert market["brier"] == pytest.approx((0.56 - 1) ** 2) and market["log_loss"] == pytest.approx(-math.log(0.56))
    assert naive["brier"] == pytest.approx(0.25) and naive["log_loss"] == pytest.approx(math.log(2))
    assert len(PredictionStore(world.db).reveal_times(pred["prediction_id"])) == 1


def test_reveal_without_market_baseline_reports_null(tmp_path, monkeypatch):
    world = make_world(tmp_path, monkeypatch, quotes=False)
    client = world.client()
    pid = run(client).json()["prediction"]["prediction_id"]
    body = client.post(f"/api/replay/{pid}/reveal").json()
    assert body["baselines"]["market"] is None
    assert body["baselines"]["naive"]["brier"] == pytest.approx(0.25)


def test_prediction_saved_after_the_first_reveal_is_flagged(world):
    client = world.client()
    first = run(client).json()["prediction"]["prediction_id"]
    client.post(f"/api/replay/{first}/reveal")
    late = run(client, "agent_plus_market").json()["prediction"]["prediction_id"]
    body = client.post(f"/api/replay/{late}/reveal").json()
    assert body["persisted_before_outcome_revealed"] is False
    assert body["event_first_reveal_seq"] < body["persist_seq"]


def test_reveal_of_unknown_prediction_is_409_not_revealable(world):
    resp = world.client().post("/api/replay/pred_never_saved/reveal")
    assert resp.status_code == 409
    assert resp.json()["code"] == "NOT_REVEALABLE"
    assert CANARY not in resp.text


def test_reveal_of_tampered_record_is_409(world):
    client = world.client()
    pid = run(client).json()["prediction"]["prediction_id"]
    with sqlite3.connect(world.db) as conn:
        for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'trigger'").fetchall():
            conn.execute(f"DROP TRIGGER {name}")
        conn.execute("UPDATE predictions SET final_prompt_text = final_prompt_text || ' edited'")
    resp = client.post(f"/api/replay/{pid}/reveal")
    assert resp.status_code == 409 and resp.json()["code"] == "NOT_REVEALABLE"
    assert CANARY not in resp.text


def test_reveal_without_sealed_outcome_is_404_not_found(world):
    client = world.client()
    pid = run(client).json()["prediction"]["prediction_id"]
    (world.data / "sealed_outcomes" / f"{EVENT}.json").unlink()
    resp = client.post(f"/api/replay/{pid}/reveal")
    assert resp.status_code == 404
    assert resp.json()["code"] == "NOT_FOUND"


def test_malformed_sealed_file_is_500_without_echo(world):
    client = world.client()
    pid = run(client).json()["prediction"]["prediction_id"]
    (world.data / "sealed_outcomes" / f"{EVENT}.json").write_text(
        json.dumps({**sealed_file(), "outcome": f"MAYBE-{CANARY}"}), encoding="utf-8"
    )
    resp = client.post(f"/api/replay/{pid}/reveal")
    assert resp.status_code == 500 and resp.json()["code"] == "DATA_INVALID"
    assert CANARY not in resp.text


def test_missing_route_has_no_code(world):
    resp = world.client().post("/api/replay/nothing/here")
    assert resp.status_code in (404, 405)
    assert "code" not in resp.json()


# ---------------------------------------------------------------- leakage: classification, schemas, JSON, files


def _paths(client: TestClient) -> dict:
    return client.get("/openapi.json").json()["paths"]


def test_every_case_and_replay_route_is_classified(world):
    ops = {(m, path) for path, item in _paths(world.client()).items() for m in item}
    replay_ops = {op for op in ops if op[1].startswith(("/api/cases", "/api/replay", "/api/integrity"))}
    assert replay_ops == PRE_REVEAL | POST_REVEAL, "classify new case/replay routes as pre- or post-reveal"
    benchmark_ops = {op for op in ops if op[1].startswith("/api/benchmark")}
    assert benchmark_ops == BENCHMARK_POST_REVEAL_READ_ONLY | BENCHMARK_ADMIN_REVEALS, "classify new benchmark routes"
    unclassified = {op for op in ops - replay_ops - benchmark_ops if op[1] not in NOT_REPLAY}
    assert not unclassified, f"new routes must be classified in this test: {sorted(unclassified)}"


def _schema_property_names(schema: dict, components: dict, seen: set[str] | None = None) -> set[str]:
    seen = set() if seen is None else seen
    names: set[str] = set()
    if isinstance(schema, dict):
        ref = schema.get("$ref")
        if ref:
            name = ref.rsplit("/", 1)[-1]
            if name not in seen:
                seen.add(name)
                names |= _schema_property_names(components[name], components, seen)
        for key, value in schema.items():
            if key == "properties":
                names |= set(value)
            names |= _schema_property_names(value, components, seen)
    elif isinstance(schema, list):
        for value in schema:
            names |= _schema_property_names(value, components, seen)
    return names


def test_pre_reveal_response_schemas_have_no_outcome_fields(world):
    doc = world.client().get("/openapi.json").json()
    components = doc["components"]["schemas"]
    for method, path in PRE_REVEAL:
        op = doc["paths"][path][method]
        for status, response in op["responses"].items():
            names = _schema_property_names(response, components)
            assert names, (path, status)
            leaked = sorted(n for n in names if OUTCOME_LIKE.search(n))
            assert leaked == [], (method, path, status, leaked)
    # The reveal schema does carry the outcome; that is the point of the post-reveal boundary.
    reveal = doc["paths"]["/api/replay/{prediction_id}/reveal"]["post"]["responses"]["200"]
    assert "outcome" in _schema_property_names(reveal, components)


def _run_pid(responses: list) -> str:
    """prediction_id of the agent_plus_market run among the pre-reveal responses."""
    runs = [r for r in responses if r.status_code == 200 and "prediction" in r.json()]
    return next(r for r in runs if r.json()["prediction"]["variant"] == "agent_plus_market").json()["prediction"][
        "prediction_id"
    ]


def _pre_reveal_calls(world: World, client: TestClient) -> list:
    """At least one request (success and failure) per pre-reveal route."""
    calls = {
        ("get", "/api/cases"): [client.get("/api/cases")],
        ("get", "/api/cases/{case_id}/evidence"): [
            client.get(f"/api/cases/{EVENT}/evidence"),
            client.get(f"/api/cases/{EVENT}/evidence", params={"as_of": (AS_OF - timedelta(days=3)).isoformat()}),
            client.get(f"/api/cases/{EVENT}/evidence", params={"as_of": (AS_OF + timedelta(days=1)).isoformat()}),
            client.get("/api/cases/no_such_case/evidence"),
        ],
        ("post", "/api/replay/run"): [
            run(client, "agent_only"),
            run(client, "agent_plus_market"),
            run(client, "agent_only", case_id="no_such_case"),
        ],
    }
    pid = _run_pid(calls[("post", "/api/replay/run")])
    calls[("get", "/api/integrity")] = [
        client.get("/api/integrity"),
        client.get("/api/integrity", params={"case_id": EVENT}),
        client.get("/api/integrity", params={"prediction_id": pid}),
        client.get("/api/integrity", params={"case_id": "no_such_case"}),
    ]
    assert set(calls) == PRE_REVEAL
    return [resp for group in calls.values() for resp in group]


def test_pre_reveal_endpoints_never_return_sealed_values_before_or_after_a_reveal(world):
    client = world.client()
    before = _pre_reveal_calls(world, client)
    assert {r.status_code for r in before} >= {200, 404, 422}
    for resp in before:
        assert_pre_reveal_clean(resp)
    pid = _run_pid(before)
    revealed = client.post(f"/api/replay/{pid}/reveal")
    assert revealed.status_code == 200 and CANARY in revealed.text  # the canary IS in the sealed file
    for resp in _pre_reveal_calls(world, client):
        assert_pre_reveal_clean(resp)


def test_pre_reveal_routes_never_open_the_sealed_directory(world, monkeypatch):
    opened: list[str] = []
    real_open, real_path_open = builtins.open, pathlib.Path.open

    def spy_open(file, *args, **kwargs):
        opened.append(os.fspath(file) if isinstance(file, (str, os.PathLike)) else repr(file))
        return real_open(file, *args, **kwargs)

    def spy_path_open(self, *args, **kwargs):
        opened.append(os.fspath(self))
        return real_path_open(self, *args, **kwargs)

    client = world.client()
    monkeypatch.setattr(builtins, "open", spy_open)
    monkeypatch.setattr(pathlib.Path, "open", spy_path_open)
    responses = _pre_reveal_calls(world, client)
    assert any(r.status_code == 200 for r in responses)
    assert any("demo_cases" in p for p in opened)  # the probe sees the case reads
    assert not [p for p in opened if "sealed_outcomes" in p.casefold()]

    pid = _run_pid(responses)
    assert client.post(f"/api/replay/{pid}/reveal").status_code == 200
    assert [p for p in opened if "sealed_outcomes" in p]  # ... and would have caught a sealed read


# ---------------------------------------------------------------- LOCAL ONLY: one real model call


@pytest.mark.skipif(os.environ.get("FAULTLINE_REAL_OLLAMA") != "1", reason="LOCAL ONLY: set FAULTLINE_REAL_OLLAMA=1")
def test_local_only_real_ollama_run(tmp_path, monkeypatch):
    """LOCAL ONLY, never in CI: one real call to the configured Ollama model on the SYNTHETIC fixture.

    Either a real, persisted forecast or a coded error; never a substitute answer."""
    world = make_world(tmp_path, monkeypatch)
    app = create_app()  # no provider override: LocalOllamaProvider.from_settings()
    resp = run(TestClient(app))
    assert_pre_reveal_clean(resp)
    if resp.status_code == 200:
        p = resp.json()["prediction"]
        assert PredictionStore(world.db).verify(p["prediction_id"]) == []
    else:
        assert resp.json()["code"] in {"MODEL_UNAVAILABLE", "MODEL_OUTPUT_INVALID", "PROMPT_NOT_VERIFIED",
                                       "PROMPT_TOO_LONG"}
        assert world.records() == []
