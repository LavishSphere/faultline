"""Model-provider contract for the Blind Replay decision agent (SPEC §3.3, §5).

A provider receives one already-rendered, already-gated prompt string (``core.temporal_gate.ModelInput.prompt``)
plus the evidence ids that prompt offered, and returns a ``ForecastResult``: a validated ``ForecastOutput``
and the audit metadata needed to persist a ``models.Prediction`` before any reveal.

Honesty rules enforced here:

* LLM output is *proposed*. ``ForecastOutput`` is a strict Pydantic model: ``p_yes`` must be a finite JSON
  number in [0, 1] (no strings, no booleans, no NaN), ``decision`` one of act / wait / hedge, ``rationale`` at
  most 600 characters, ``evidence_ids`` a subset of the ids offered in the prompt, and no extra keys.
* A provider never fabricates an answer. Unreachable model -> ``ModelUnavailable``; output that still fails
  validation after the single repair attempt -> ``ModelOutputInvalid``. Neither carries a forecast.
* A provider adds nothing to the prompt: no system prompt, no tools, no retrieval, no current date.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Annotated, Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, ValidationError, ValidationInfo, field_validator

from models import Decision, ErrorCode, Identifier, Probability

RATIONALE_MAX_CHARS = 600

# Pydantic validation context key holding the evidence ids offered in the prompt.
OFFERED_IDS_CONTEXT_KEY = "offered_evidence_ids"


# ---------------------------------------------------------------- errors


class ProviderError(Exception):
    """Base class. Every provider error means: there is NO forecast for this call."""

    code: ErrorCode | None = None


class ModelUnavailable(ProviderError):
    """The model could not be called (server down, timeout, model not installed, HTTP error).

    Maps to API error code MODEL_UNAVAILABLE. The UI must show this state; nothing may stand in for the answer.
    """

    code = ErrorCode.MODEL_UNAVAILABLE


class ModelOutputInvalid(ProviderError):
    """The model answered, but its output failed ForecastOutput validation on every attempt.

    ``raw_outputs`` keeps each attempt's raw text for the audit log; it is never shown as a forecast.
    """

    def __init__(self, message: str, *, raw_outputs: Sequence[str], problems: Sequence[str]) -> None:
        super().__init__(message)
        self.raw_outputs: tuple[str, ...] = tuple(raw_outputs)
        self.problems: tuple[str, ...] = tuple(problems)


class PromptTooLong(ProviderError):
    """The prompt (plus the answer budget) does not fit the configured context window.

    Raised before sending (conservative size estimate) or when the runtime refuses the request as over-long.
    By default Ollama silently drops the start of an over-long prompt, which would cut the instructions and
    evidence, so the provider refuses instead of forecasting on a truncated input.
    """


class PromptNotVerified(ProviderError):
    """The model answered, but the provider cannot confirm it saw the whole prompt.

    E.g. the runtime reported no prompt token count, or a count too small for the prompt's length (a sign of
    silent truncation). Fail closed: the answer is discarded, never shown as a forecast.
    """


# ---------------------------------------------------------------- forecast output


def has_visible_text(text: str) -> bool:
    """True if ``text`` has a character that is neither whitespace nor an invisible format character
    (Unicode category Cf: zero-width space/joiners, BOM, word joiner, bidi marks)."""
    return any(not ch.isspace() and unicodedata.category(ch) != "Cf" for ch in text)


class ForecastOutput(BaseModel):
    """The structured answer the model must return (validated, never edited).

    Validate model text with ``ForecastOutput.parse_model_json(raw, offered_evidence_ids)``. Validation
    without the offered-ids context fails, so the subset rule cannot be skipped by accident.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    p_yes: Probability
    decision: Decision
    rationale: Annotated[str, Field(min_length=1, max_length=RATIONALE_MAX_CHARS)]

    @field_validator("rationale")
    @classmethod
    def _visible(cls, v: str) -> str:
        if not has_visible_text(v):
            raise ValueError("rationale has no visible text")
        return v
    evidence_ids: list[Identifier]

    @field_validator("evidence_ids")
    @classmethod
    def _subset_of_offered(cls, v: list[str], info: ValidationInfo) -> list[str]:
        ctx = info.context
        if not isinstance(ctx, dict) or OFFERED_IDS_CONTEXT_KEY not in ctx:
            raise ValueError("offered evidence ids are required to validate evidence_ids")
        offered = set(ctx[OFFERED_IDS_CONTEXT_KEY])
        unknown = [e for e in v if e not in offered]
        if unknown:
            raise ValueError(f"evidence_ids not offered in the prompt: {sorted(set(unknown))}")
        return v

    @classmethod
    def parse_model_json(cls, raw: str, offered_evidence_ids: Sequence[str]) -> ForecastOutput:
        """Parse raw model text as one JSON object. Raises pydantic.ValidationError."""
        return cls.model_validate_json(raw, context={OFFERED_IDS_CONTEXT_KEY: tuple(offered_evidence_ids)})

    @classmethod
    def validate_obj(cls, obj: Any, offered_evidence_ids: Sequence[str]) -> ForecastOutput:
        return cls.model_validate(obj, context={OFFERED_IDS_CONTEXT_KEY: tuple(offered_evidence_ids)})


def summarize_validation_error(exc: ValidationError) -> list[str]:
    """Short, deterministic problem strings (location + message, without echoing input values)."""
    out = []
    for err in exc.errors(include_url=False, include_input=False):
        loc = ".".join(str(p) for p in err.get("loc", ())) or "<root>"
        out.append(f"{loc}: {err.get('msg', 'invalid')}")
    return out


# ---------------------------------------------------------------- result + protocol


@dataclass(frozen=True)
class ForecastResult:
    """One validated forecast plus the audit metadata a ``models.Prediction`` needs.

    The caller (replay-run route) supplies prediction_id, event_id, as_of, variant, prompt_sha256,
    snapshot_sha256, recorded_at and provenance; everything model-side comes from here.
    """

    output: ForecastOutput
    agent_model: str
    """e.g. "ollama/llama3.1:8b" -> Prediction.agent_model."""
    model_tag: str
    model_digest: str | None
    """Digest reported by the runtime for the installed weights (Ollama /api/tags), None if not reported."""
    temperature: float
    seed: int | None
    attempts: int
    """1 = first answer validated; 2 = validated after the single schema-repair turn."""
    final_prompt: str
    """The exact single user message of the attempt that validated: the gated prompt itself when
    attempts == 1; the gated prompt followed by the fixed repair instruction when attempts == 2."""
    raw_output: str
    """The exact text of the validated answer."""
    raw_output_sha256: str
    transcript_sha256: str
    """SHA256 of canonical JSON of the chat messages sent on the final attempt (always one user message)."""
    latency_ms: int
    """Wall-clock time of the whole forecast call, including any repair attempt (informational)."""
    done_reason: str | None = None
    prompt_eval_count: int | None = None
    eval_count: int | None = None


@runtime_checkable
class ModelProvider(Protocol):
    """Anything that turns one gated prompt into a validated forecast, or raises a ProviderError."""

    @property
    def provider_id(self) -> str:
        """Stable id such as "ollama"; combined with the model tag in ForecastResult.agent_model."""
        ...

    async def forecast(self, prompt: str, offered_evidence_ids: Sequence[str]) -> ForecastResult:
        """Send ``prompt`` exactly as given; validate the answer against ``offered_evidence_ids``.

        Raises ModelUnavailable, ModelOutputInvalid, PromptTooLong or PromptNotVerified. Never returns a
        substitute answer.
        """
        ...
