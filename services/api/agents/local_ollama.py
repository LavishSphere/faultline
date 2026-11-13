"""LocalOllamaProvider: the default, offline, open-weight replay model (SPEC §5, replay-integrity skill).

One forecast = ``GET /api/tags`` (is the model installed? record its tag + digest) and then
``POST /api/chat`` with exactly ONE user message holding the gated prompt, JSON mode, temperature 0 and a
fixed seed. The request carries no system prompt, no tools, no images, no date and no other context: the
prompt from ``core.temporal_gate`` is the model's entire input. (The installed llama3.1 chat template only
adds its "Cutting Knowledge Date" header when tools are passed, and tools never are.)

The model must see the WHOLE gated prompt, or there is no forecast (fail closed, four layers):

1. Pre-check before any request: a conservative token estimate (``ceil(utf8_bytes / precheck_bytes_per_token)``,
   default 2 bytes per token; English prose is about 4) plus the answer budget and a margin must fit ``num_ctx``,
   otherwise ``PromptTooLong``.
2. ``"truncate": false`` and ``"shift": false``: Ollama refuses an over-long request with HTTP 400 instead of
   silently dropping its start (checked against Ollama 0.40.16) -> ``PromptTooLong``.
3. Every answer must report ``prompt_eval_count`` (missing -> ``PromptNotVerified``), at least
   ``utf8_bytes / 8`` (a lower bound; real prompts measure about 4-6 bytes per token), below
   ``num_ctx - num_predict``, and, on the repair attempt, at least the first attempt's count plus the lower
   bound for the repair instruction.
4. The repair turn is ONE user message: the original prompt, unchanged, followed by a fixed instruction listing
   the validation problems. No prior assistant turn is replayed, so there is no older message for the runtime
   to drop. A second invalid answer raises ``ModelOutputInvalid``.

Transport / HTTP failures raise ``ModelUnavailable`` with a message naming what failed (unreachable, timeout,
HTTP status, bad response) and no chained exception (httpx messages can echo a URL with credentials).
No path returns a canned or default forecast.

Configuration: ``OLLAMA_BASE_URL`` and ``FAULTLINE_OLLAMA_MODEL`` via ``config.get_settings()``.
Tests inject an ``httpx.MockTransport``; nothing here needs the public network.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import time
from collections.abc import Sequence
from typing import Any

import httpx
from pydantic import ValidationError

from agents.provider import (
    ForecastOutput,
    ForecastResult,
    ModelOutputInvalid,
    ModelUnavailable,
    PromptNotVerified,
    PromptTooLong,
    summarize_validation_error,
)
from config import Settings, get_settings

PROVIDER_ID = "ollama"
DEFAULT_SEED = 20261115
DEFAULT_TEMPERATURE = 0.0
DEFAULT_NUM_CTX = 8192
DEFAULT_NUM_PREDICT = 512
DEFAULT_TIMEOUT_S = 180.0
CONNECT_TIMEOUT_S = 3.0
MAX_ATTEMPTS = 2  # first answer + one schema-repair turn

# Pre-check: assume at most this many UTF-8 bytes per token (smaller = more tokens = more conservative).
DEFAULT_PRECHECK_BYTES_PER_TOKEN = 2.0
# Chat-template tokens around one user message, plus a safety margin.
TEMPLATE_OVERHEAD_TOKENS = 32
SAFETY_MARGIN_TOKENS = 64
# Post-check: a prompt of N bytes must have been evaluated as at least N / 8 tokens.
MIN_TOKENS_BYTES_PER_TOKEN = 8.0

# Ollama 0.40.16: "request (715 tokens) exceeds the available context size (512 tokens), try increasing it"
_CONTEXT_ERROR_COUNTS = re.compile(r"\((\d+) tokens\).*?\((\d+) tokens\)")

REPAIR_INSTRUCTION = (
    "\n\n---\nA previous answer to the request above was not valid. Problems:\n{problems}\n"
    "Answer again with exactly one JSON object and nothing else, with exactly these keys: "
    '"p_yes" (a number from 0 to 1), "decision" ("act", "wait" or "hedge"), '
    '"rationale" (at most 600 characters), "evidence_ids" (only ids of evidence items given above).'
)


def repair_instruction(problems: Sequence[str]) -> str:
    """The exact suffix appended to the gated prompt for the one repair attempt: one ``- <problem>`` line each.

    Problems are flattened to one line, so ``is_repair_instruction`` can recognise every suffix produced here.
    """
    lines = [" ".join(str(p).splitlines()) for p in problems]
    return REPAIR_INSTRUCTION.format(problems="\n".join(f"- {line}" for line in lines))


def is_repair_instruction(suffix: str) -> bool:
    """True iff ``suffix`` is exactly ``repair_instruction(problems)`` for one or more non-empty problems.

    The fixed header and footer come from ``REPAIR_INSTRUCTION``; only ``- ...`` problem lines may sit between
    them. Used by ``core.store`` to refuse a "repair" prompt that appends anything else to the gated prompt.
    """
    head, sep, tail = REPAIR_INSTRUCTION.partition("{problems}")
    if not isinstance(suffix, str) or not sep or len(suffix) <= len(head) + len(tail):
        return False
    if not suffix.startswith(head) or not suffix.endswith(tail):
        return False
    lines = suffix[len(head) : len(suffix) - len(tail)].split("\n")
    if not all(line.startswith("- ") and line[2:].strip() and "\r" not in line for line in lines):
        return False
    return repair_instruction([line[2:] for line in lines]) == suffix


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _tag_candidates(model: str) -> set[str]:
    """Ollama treats an untagged name as ':latest'."""
    return {model} if ":" in model else {model, f"{model}:latest"}


def _int_or_none(v: Any) -> int | None:
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def min_expected_tokens(text: str) -> int:
    """Lower bound on the token count of ``text`` (used to detect silent truncation)."""
    return math.floor(len(text.encode("utf-8")) / MIN_TOKENS_BYTES_PER_TOKEN)


def _describe_failure(exc: Exception) -> str:
    """What failed, without the exception text (which can echo the configured URL and its credentials)."""
    if isinstance(exc, httpx.TimeoutException):
        return f"Ollama at OLLAMA_BASE_URL timed out ({type(exc).__name__})."
    if isinstance(exc, httpx.HTTPStatusError):
        return f"Ollama returned HTTP {exc.response.status_code} for {exc.request.url.path}."
    if isinstance(exc, httpx.InvalidURL):
        return "OLLAMA_BASE_URL is not a valid URL (InvalidURL)."
    if isinstance(exc, httpx.TransportError):
        return f"Ollama not reachable at OLLAMA_BASE_URL ({type(exc).__name__})."
    if isinstance(exc, ValueError):
        return f"Ollama returned a response that is not valid JSON ({type(exc).__name__})."
    return f"Ollama request failed ({type(exc).__name__})."


class LocalOllamaProvider:
    """ModelProvider backed by a local Ollama server. Stateless between calls."""

    def __init__(
        self,
        base_url: str,
        model: str,
        *,
        seed: int = DEFAULT_SEED,
        num_ctx: int = DEFAULT_NUM_CTX,
        num_predict: int = DEFAULT_NUM_PREDICT,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        precheck_bytes_per_token: float = DEFAULT_PRECHECK_BYTES_PER_TOKEN,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not model.strip():
            raise ValueError("model tag is required")
        if num_predict + TEMPLATE_OVERHEAD_TOKENS + SAFETY_MARGIN_TOKENS >= num_ctx:
            raise ValueError("num_ctx leaves no room for a prompt after num_predict and the safety margin")
        if precheck_bytes_per_token <= 0:
            raise ValueError("precheck_bytes_per_token must be positive")
        self.base_url = base_url.rstrip("/")
        self.model = model.strip()
        self.temperature = DEFAULT_TEMPERATURE
        self.seed = seed
        self.num_ctx = num_ctx
        self.num_predict = num_predict
        self.precheck_bytes_per_token = precheck_bytes_per_token
        self._timeout = httpx.Timeout(timeout_s, connect=CONNECT_TIMEOUT_S)
        self._transport = transport

    @classmethod
    def from_settings(
        cls, settings: Settings | None = None, *, transport: httpx.AsyncBaseTransport | None = None, **kwargs: Any
    ) -> LocalOllamaProvider:
        s = settings or get_settings()
        return cls(s.ollama_base_url, s.ollama_model, transport=transport, **kwargs)

    @property
    def provider_id(self) -> str:
        return PROVIDER_ID

    # ------------------------------------------------------------ request construction

    def build_chat_request(self, user_message: str) -> dict[str, Any]:
        """The complete /api/chat body: one user message, the model tag, sampling options, no-truncation flags."""
        return {
            "model": self.model,
            "messages": [{"role": "user", "content": user_message}],
            "format": "json",
            "stream": False,
            "think": False,
            "truncate": False,
            "shift": False,
            "options": {
                "temperature": self.temperature,
                "seed": self.seed,
                "num_ctx": self.num_ctx,
                "num_predict": self.num_predict,
            },
        }

    def estimated_max_tokens(self, user_message: str) -> int:
        """Conservative (high) token estimate for one user message including template overhead."""
        return math.ceil(len(user_message.encode("utf-8")) / self.precheck_bytes_per_token) + TEMPLATE_OVERHEAD_TOKENS

    def precheck(self, user_message: str) -> None:
        """Refuse before sending when the message might not fit next to the answer budget."""
        estimate = self.estimated_max_tokens(user_message)
        budget = self.num_ctx - self.num_predict - SAFETY_MARGIN_TOKENS
        if estimate > budget:
            raise PromptTooLong(
                f"Prompt may need up to {estimate} tokens; only {budget} fit in num_ctx={self.num_ctx} after "
                f"num_predict={self.num_predict} and a {SAFETY_MARGIN_TOKENS}-token margin. Not sent."
            )

    # ------------------------------------------------------------ HTTP

    async def _installed_digest(self, client: httpx.AsyncClient) -> str | None:
        """Confirm the model is installed; return its digest (None if Ollama does not report one)."""
        resp = await client.get("/api/tags")
        resp.raise_for_status()
        payload = resp.json()
        entries = payload.get("models") if isinstance(payload, dict) else None
        if not isinstance(entries, list):
            raise ModelUnavailable("Unexpected response from Ollama /api/tags.")
        wanted = _tag_candidates(self.model)
        for e in entries:
            if isinstance(e, dict) and e.get("name") in wanted:
                digest = e.get("digest")
                return digest if isinstance(digest, str) and digest else None
        raise ModelUnavailable(f"Model {self.model} is not installed in Ollama (run `ollama pull {self.model}`).")

    async def _chat(self, client: httpx.AsyncClient, user_message: str) -> dict[str, Any]:
        resp = await client.post("/api/chat", json=self.build_chat_request(user_message))
        if resp.status_code == 400:
            error = _error_text(resp)
            if "context" in error.lower():
                # Ollama (truncate=false) refused an over-long request. Only the token counts are kept.
                m = _CONTEXT_ERROR_COUNTS.search(error)
                detail = f" (request {m.group(1)} tokens, context {m.group(2)} tokens)" if m else ""
                raise PromptTooLong(f"Ollama refused the request as longer than the context window{detail}.")
        resp.raise_for_status()
        body = resp.json()
        if not isinstance(body, dict):
            raise ModelUnavailable("Ollama /api/chat returned an unexpected (non-object) response.")
        if body.get("error"):
            raise ModelUnavailable("Ollama /api/chat reported a model error.")
        return body

    def _verify_prompt_seen(self, body: dict[str, Any], user_message: str, floor: int) -> int:
        """Fail closed unless the reported prompt token count is consistent with the whole message being read."""
        count = _int_or_none(body.get("prompt_eval_count"))
        if count is None:
            raise PromptNotVerified("Ollama did not report prompt_eval_count; cannot confirm the prompt was read.")
        expected = max(min_expected_tokens(user_message), floor)
        if count < expected:
            raise PromptNotVerified(
                f"Ollama evaluated {count} prompt tokens; at least {expected} expected for this prompt. "
                "The prompt was probably truncated; answer discarded."
            )
        if count >= self.num_ctx - self.num_predict:
            raise PromptNotVerified(
                f"Prompt used {count} tokens of num_ctx={self.num_ctx} with {self.num_predict} reserved for the "
                "answer; possibly truncated. Answer discarded."
            )
        return count

    # ------------------------------------------------------------ forecast

    async def forecast(self, prompt: str, offered_evidence_ids: Sequence[str]) -> ForecastResult:
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("prompt must be a non-empty string")
        self.precheck(prompt)
        try:
            return await self._forecast(prompt, tuple(offered_evidence_ids))
        except (httpx.HTTPError, httpx.InvalidURL, ValueError) as exc:
            failure = _describe_failure(exc)
        # Raised outside the except block so no __context__/__cause__ (with httpx's URL-bearing text) is attached.
        raise ModelUnavailable(failure)

    async def _forecast(self, prompt: str, offered: tuple[str, ...]) -> ForecastResult:
        started = time.perf_counter()
        raw_outputs: list[str] = []
        problems: list[str] = []
        user_message = prompt
        floor = 0
        client_args = {"base_url": self.base_url, "timeout": self._timeout, "transport": self._transport}
        async with httpx.AsyncClient(**client_args) as client:
            digest = await self._installed_digest(client)
            for attempt in range(1, MAX_ATTEMPTS + 1):
                body = await self._chat(client, user_message)
                count = self._verify_prompt_seen(body, user_message, floor)
                message = body.get("message")
                content = message.get("content") if isinstance(message, dict) else None
                raw = content if isinstance(content, str) else ""
                raw_outputs.append(raw)
                output: ForecastOutput | None = None
                try:
                    output = ForecastOutput.parse_model_json(raw, offered)
                except ValidationError as exc:
                    problems = summarize_validation_error(exc)
                if output is None:
                    # Outside the except block: a PromptTooLong here carries no chained ValidationError
                    # (whose text would echo the model's raw output).
                    if attempt < MAX_ATTEMPTS:
                        instruction = repair_instruction(problems)
                        user_message = prompt + instruction
                        self.precheck(user_message)
                        # The repair message is the whole prompt plus the instruction, so it cannot count fewer.
                        floor = count + min_expected_tokens(instruction)
                    continue
                done_reason = body.get("done_reason")
                return ForecastResult(
                    output=output,
                    agent_model=f"{PROVIDER_ID}/{self.model}",
                    model_tag=self.model,
                    model_digest=digest,
                    temperature=self.temperature,
                    seed=self.seed,
                    attempts=attempt,
                    final_prompt=user_message,
                    raw_output=raw,
                    raw_output_sha256=_sha256(raw),
                    transcript_sha256=_sha256(_canonical([{"role": "user", "content": user_message}])),
                    latency_ms=round((time.perf_counter() - started) * 1000),
                    done_reason=done_reason if isinstance(done_reason, str) else None,
                    prompt_eval_count=count,
                    eval_count=_int_or_none(body.get("eval_count")),
                )
        raise ModelOutputInvalid(
            f"Model output failed validation after {MAX_ATTEMPTS} attempts (one schema repair).",
            raw_outputs=raw_outputs,
            problems=problems,
        )


def _error_text(resp: httpx.Response) -> str:
    try:
        body = resp.json()
    except ValueError:
        return ""
    err = body.get("error") if isinstance(body, dict) else None
    return err if isinstance(err, str) else ""
