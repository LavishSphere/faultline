"""LocalOllamaProvider over a mocked HTTP transport (issue #36). No test here touches the network:
every request goes to an httpx.MockTransport, except one that targets a closed loopback port."""

from __future__ import annotations

import asyncio
import hashlib
import json
import traceback
from datetime import UTC, datetime

import httpx
import pytest

from agents.local_ollama import DEFAULT_SEED, LocalOllamaProvider, min_expected_tokens
from agents.provider import ModelOutputInvalid, ModelUnavailable, PromptNotVerified, PromptTooLong
from config import get_settings

DIGEST = "46e0c10c039e" + "0" * 52
OFFERED = ("evid_a", "evid_b")
PROMPT = (
    "SYNTHETIC test prompt. Cutoff: 2025-01-15T12:00:00Z.\n"
    "Evidence evid_a: orders fell 12% month over month.\nEvidence evid_b: supplier lead times doubled.\n"
    'Answer with exactly one JSON object: {"p_yes": ..., "decision": ..., "rationale": ..., "evidence_ids": [...]}'
)

VALID = {
    "p_yes": 0.62,
    "decision": "hedge",
    "rationale": "Orders fell (evid_a) and lead times doubled (evid_b).",
    "evidence_ids": ["evid_a", "evid_b"],
}


def _honest_count(body: dict) -> int:
    """A realistic prompt token count for a request: about 4 UTF-8 bytes per token, plus template tokens."""
    text = "".join(m["content"] for m in body["messages"])
    return len(text.encode()) // 4 + 10


class FakeOllama:
    """Records every request; answers /api/chat from a queue of message contents.

    ``counts`` optionally overrides prompt_eval_count per chat call (None = key absent); by default the count is
    consistent with the whole prompt having been read.
    """

    def __init__(
        self,
        chat_contents: list[str],
        tags: list[dict] | None = None,
        counts: list[int | None | str] | None = None,
    ):
        self.chat_contents = list(chat_contents)
        self.tags = tags if tags is not None else [{"name": "llama3.1:8b", "model": "llama3.1:8b", "digest": DIGEST}]
        self.counts = list(counts) if counts is not None else None
        self.requests: list[httpx.Request] = []

    def chat_bodies(self) -> list[dict]:
        return [json.loads(r.content) for r in self.requests if r.url.path == "/api/chat"]

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.method == "GET" and request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": self.tags})
        if request.method == "POST" and request.url.path == "/api/chat":
            req = json.loads(request.content)
            body = {
                "model": "llama3.1:8b",
                "created_at": "2026-11-13T00:00:00Z",
                "message": {"role": "assistant", "content": self.chat_contents.pop(0)},
                "done": True,
                "done_reason": "stop",
                "prompt_eval_count": _honest_count(req),
                "eval_count": 40,
            }
            if self.counts is not None:
                count = self.counts.pop(0)
                if count is None:
                    del body["prompt_eval_count"]
                elif count != "honest":
                    body["prompt_eval_count"] = count
            return httpx.Response(200, json=body)
        return httpx.Response(404, json={"error": "not found"})

    def provider(self, **kwargs) -> LocalOllamaProvider:
        return LocalOllamaProvider(
            "http://ollama.test", "llama3.1:8b", transport=httpx.MockTransport(self.handler), **kwargs
        )


def _run(coro):
    return asyncio.run(coro)


def _tags_ok() -> httpx.Response:
    return httpx.Response(200, json={"models": [{"name": "llama3.1:8b", "digest": DIGEST}]})


# ---------------------------------------------------------------- happy path


def test_happy_path_validates_and_records_tag_digest_and_settings():
    fake = FakeOllama([json.dumps(VALID)])
    result = _run(fake.provider().forecast(PROMPT, OFFERED))
    assert result.output.p_yes == 0.62
    assert result.output.decision == "hedge"
    assert result.output.evidence_ids == ["evid_a", "evid_b"]
    assert result.agent_model == "ollama/llama3.1:8b"
    assert result.model_tag == "llama3.1:8b"
    assert result.model_digest == DIGEST
    assert result.temperature == 0.0
    assert result.seed == DEFAULT_SEED
    assert result.attempts == 1
    assert result.final_prompt == PROMPT
    assert result.raw_output == json.dumps(VALID)
    assert result.raw_output_sha256 == hashlib.sha256(json.dumps(VALID).encode()).hexdigest()
    assert [r.url.path for r in fake.requests] == ["/api/tags", "/api/chat"]


def test_request_carries_only_the_given_prompt_no_system_no_tools_no_date():
    fake = FakeOllama([json.dumps(VALID)])
    _run(fake.provider().forecast(PROMPT, OFFERED))
    (body,) = fake.chat_bodies()
    for forbidden in ("tools", "system", "images", "context", "template", "raw"):
        assert forbidden not in body
    raw = fake.requests[-1].content.decode()
    today = datetime.now(UTC).date()
    for fmt in (today.isoformat(), today.strftime("%B %d, %Y"), today.strftime("%d %B %Y"), "Today Date"):
        assert fmt not in raw
    # The whole body, exactly: the prompt is the only text the model receives, and truncation is disabled.
    assert body == {
        "model": "llama3.1:8b",
        "messages": [{"role": "user", "content": PROMPT}],
        "format": "json",
        "stream": False,
        "think": False,
        "truncate": False,
        "shift": False,
        "options": {"temperature": 0.0, "seed": DEFAULT_SEED, "num_ctx": 8192, "num_predict": 512},
    }


def test_real_sized_prompt_fits_and_validates():
    # ~12 kB of synthetic evidence: under the conservative 2-bytes-per-token pre-check for num_ctx=8192.
    evidence = "".join(f"Evidence evid_{i}: SYNTHETIC supplier note number {i} about lead times.\n" for i in range(180))
    prompt = PROMPT + "\n" + evidence
    assert 11_000 < len(prompt.encode()) < 15_000
    fake = FakeOllama([json.dumps(VALID)])
    result = _run(fake.provider().forecast(prompt, OFFERED))
    assert result.attempts == 1
    assert fake.chat_bodies()[0]["messages"] == [{"role": "user", "content": prompt}]


def test_untagged_model_name_matches_latest():
    fake = FakeOllama([json.dumps(VALID)], tags=[{"name": "llama3.1:latest", "digest": DIGEST}])
    provider = LocalOllamaProvider("http://ollama.test", "llama3.1", transport=httpx.MockTransport(fake.handler))
    assert _run(provider.forecast(PROMPT, OFFERED)).model_digest == DIGEST


def test_missing_digest_recorded_as_none_not_invented():
    fake = FakeOllama([json.dumps(VALID)], tags=[{"name": "llama3.1:8b"}])
    assert _run(fake.provider().forecast(PROMPT, OFFERED)).model_digest is None


def test_from_settings_reads_env(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://ollama.example:1234/")
    monkeypatch.setenv("FAULTLINE_OLLAMA_MODEL", "gemma4:e2b")
    p = LocalOllamaProvider.from_settings(get_settings())
    assert p.base_url == "http://ollama.example:1234" and p.model == "gemma4:e2b"


# ---------------------------------------------------------------- repair and invalid output


def test_repair_is_one_user_message_with_the_full_prompt():
    fake = FakeOllama(["not json at all", json.dumps(VALID)])
    result = _run(fake.provider().forecast(PROMPT, OFFERED))
    assert result.attempts == 2
    first, second = fake.chat_bodies()
    assert first["messages"] == [{"role": "user", "content": PROMPT}]
    (repair,) = second["messages"]  # exactly one message: no replayed assistant turn to be dropped
    assert repair["role"] == "user"
    assert repair["content"].startswith(PROMPT)
    assert "not valid" in repair["content"][len(PROMPT) :]
    assert result.final_prompt == repair["content"]
    assert second["truncate"] is False and "tools" not in second and "system" not in second


def test_invalid_json_then_repair_fails_raises_model_output_invalid():
    fake = FakeOllama(["not json", '{"p_yes": 0.5'])
    with pytest.raises(ModelOutputInvalid) as exc:
        _run(fake.provider().forecast(PROMPT, OFFERED))
    assert exc.value.raw_outputs == ("not json", '{"p_yes": 0.5')
    assert exc.value.problems
    assert len(fake.chat_bodies()) == 2  # exactly one repair, then stop


def test_unknown_evidence_id_twice_is_invalid():
    bad = dict(VALID, evidence_ids=["evid_a", "evid_from_the_future"])
    fake = FakeOllama([json.dumps(bad), json.dumps(bad)])
    with pytest.raises(ModelOutputInvalid) as exc:
        _run(fake.provider().forecast(PROMPT, OFFERED))
    assert any("evidence_ids" in p for p in exc.value.problems)


def test_nan_p_yes_twice_is_invalid():
    nan = '{"p_yes": NaN, "decision": "wait", "rationale": "x (evid_a).", "evidence_ids": ["evid_a"]}'
    fake = FakeOllama([nan, nan])
    with pytest.raises(ModelOutputInvalid):
        _run(fake.provider().forecast(PROMPT, OFFERED))


# ---------------------------------------------------------------- the model must see the whole prompt


def test_precheck_refuses_oversized_prompt_before_any_request():
    fake = FakeOllama([json.dumps(VALID)])
    prompt = "SYNTHETIC evidence line about lead times. " * 82  # 3,444 bytes; may need ~1,722 tokens
    with pytest.raises(PromptTooLong, match="Not sent"):
        _run(fake.provider(num_ctx=512, num_predict=32).forecast(prompt, OFFERED))
    assert fake.requests == []


def test_runtime_context_refusal_is_prompt_too_long():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            return _tags_ok()
        error = "request (593 tokens) exceeds the available context size (512 tokens), try increasing it"
        return httpx.Response(400, json={"error": error})

    provider = LocalOllamaProvider(
        "http://ollama.test", "llama3.1:8b", transport=httpx.MockTransport(handler), precheck_bytes_per_token=100.0
    )
    with pytest.raises(PromptTooLong, match=r"request 593 tokens, context 512 tokens") as exc:
        _run(provider.forecast(PROMPT, OFFERED))
    assert "try increasing" not in str(exc.value)  # only the numbers are kept from Ollama's text


def test_repair_precheck_refusal_carries_no_chained_model_output():
    # First message fits the pre-check (15,000 bytes -> <= 7,532 estimated tokens of 7,616); the repair
    # message (prompt + instruction) does not.
    prompt = ("SYNTHETIC filler line about supplier lead times. " * 400)[:15_000]
    secret_raw = "INVALID-RAW-OUTPUT-MARKER not json"
    fake = FakeOllama([secret_raw])
    with pytest.raises(PromptTooLong, match="Not sent") as exc:
        _run(fake.provider().forecast(prompt, OFFERED))
    assert exc.value.__cause__ is None and exc.value.__context__ is None
    assert "INVALID-RAW-OUTPUT-MARKER" not in "".join(traceback.format_exception(exc.value))
    assert len(fake.chat_bodies()) == 1


def test_first_attempt_truncation_detected_by_low_count():
    # Real Ollama 0.40.16 without truncate=false: a 3,358-byte prompt of 593 tokens reported 258 after truncation.
    prompt = "SYNTHETIC supplier note about a two-week production line shutdown for maintenance. " * 40
    assert min_expected_tokens(prompt) > 258
    fake = FakeOllama([json.dumps(VALID)], counts=[258])
    with pytest.raises(PromptNotVerified, match="probably truncated"):
        _run(fake.provider().forecast(prompt, OFFERED))


def test_repair_turn_truncation_detected():
    # Audit repro: on the repair turn the runtime dropped the gated prompt and evaluated only ~49 tokens.
    fake = FakeOllama(["not json", json.dumps(VALID)], counts=["honest", 49])
    with pytest.raises(PromptNotVerified):
        _run(fake.provider().forecast(PROMPT, OFFERED))


def test_repair_count_must_not_drop_below_first_attempt():
    fake = FakeOllama(["not json", json.dumps(VALID)], counts=[400, 399])
    with pytest.raises(PromptNotVerified):
        _run(fake.provider().forecast(PROMPT, OFFERED))


def test_repair_count_must_cover_first_attempt_plus_instruction():
    # Same count as the first attempt (+1) means the instruction tokens are missing: something was dropped.
    fake = FakeOllama(["not json", json.dumps(VALID)], counts=[400, 401])
    with pytest.raises(PromptNotVerified):
        _run(fake.provider().forecast(PROMPT, OFFERED))


def test_missing_prompt_eval_count_fails_closed():
    fake = FakeOllama([json.dumps(VALID)], counts=[None])
    with pytest.raises(PromptNotVerified, match="did not report"):
        _run(fake.provider().forecast(PROMPT, OFFERED))


def test_count_at_context_limit_is_refused():
    fake = FakeOllama([json.dumps(VALID)], counts=[8000])
    with pytest.raises(PromptNotVerified):
        _run(fake.provider(num_ctx=8192, num_predict=512).forecast(PROMPT, OFFERED))


# ---------------------------------------------------------------- unavailable


def test_ollama_down_raises_model_unavailable_without_answer():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    provider = LocalOllamaProvider("http://ollama.test", "llama3.1:8b", transport=httpx.MockTransport(handler))
    with pytest.raises(ModelUnavailable, match="not reachable"):
        _run(provider.forecast(PROMPT, OFFERED))


def test_ollama_down_real_transport_closed_loopback_port():
    provider = LocalOllamaProvider("http://127.0.0.1:9", "llama3.1:8b", timeout_s=2.0)
    with pytest.raises(ModelUnavailable):
        _run(provider.forecast(PROMPT, OFFERED))


def test_timeout_during_chat_is_model_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            return _tags_ok()
        raise httpx.ReadTimeout("timed out", request=request)

    provider = LocalOllamaProvider("http://ollama.test", "llama3.1:8b", transport=httpx.MockTransport(handler))
    with pytest.raises(ModelUnavailable, match="timed out"):
        _run(provider.forecast(PROMPT, OFFERED))


def test_model_not_installed_is_model_unavailable_and_never_chats():
    fake = FakeOllama([json.dumps(VALID)], tags=[{"name": "gemma4:e2b", "digest": DIGEST}])
    with pytest.raises(ModelUnavailable, match="not installed"):
        _run(fake.provider().forecast(PROMPT, OFFERED))
    assert fake.chat_bodies() == []


def test_http_500_is_model_unavailable_and_says_http_status():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            return _tags_ok()
        return httpx.Response(500, json={"error": "model crashed"})

    provider = LocalOllamaProvider("http://ollama.test", "llama3.1:8b", transport=httpx.MockTransport(handler))
    with pytest.raises(ModelUnavailable, match="HTTP 500") as exc:
        _run(provider.forecast(PROMPT, OFFERED))
    assert "not reachable" not in str(exc.value)


def test_credentials_never_in_message_or_traceback():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused http://user:hunter2@ollama.test", request=request)

    provider = LocalOllamaProvider(
        "http://user:hunter2@ollama.test", "llama3.1:8b", transport=httpx.MockTransport(handler)
    )
    with pytest.raises(ModelUnavailable) as exc:
        _run(provider.forecast(PROMPT, OFFERED))
    assert exc.value.__cause__ is None and exc.value.__context__ is None
    formatted = "".join(traceback.format_exception(exc.value))
    assert "hunter2" not in formatted
    assert "ConnectError" in str(exc.value)


def test_empty_prompt_rejected_before_any_request():
    fake = FakeOllama([])
    with pytest.raises(ValueError):
        _run(fake.provider().forecast("   ", OFFERED))
    assert fake.requests == []
