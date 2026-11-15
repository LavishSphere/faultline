"""Shared API contracts (SPEC §5, §8). Pydantic v2.

Scope: replay / evidence / market-reference / prediction contracts, provenance, error codes, health.
Finance-engine types (scenarios, cash paths, optimizer plans) live in core/financials.py and
core/optimizer.py, not here.

Information isolation: every model that can be returned before a reveal (`ReplayCasePublic`,
`EvidenceItem`, `MarketQuoteRef`, `Prediction`) has `extra="forbid"` and no outcome-like field.
There is deliberately no sealed-outcome model in this module; it belongs to the evaluator boundary.
tests/test_contracts.py enforces both properties.
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

# Field names that must never reach a prompt or a pre-reveal response (replay-integrity skill).
# core/temporal_gate.py should strip evidence fields matching this pattern.
OUTCOME_FIELD_PATTERN = re.compile(r"outcome|resolution|resolved|settle|result|winner|final_price", re.IGNORECASE)

Sha256Hex = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
PrefixedSha256 = Annotated[str, StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$")]
Probability = Annotated[float, Field(ge=0.0, le=1.0, allow_inf_nan=False)]
Identifier = Annotated[str, StringConstraints(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9_.:\-]+$")]

ContaminationFlag = Literal["unknown", "likely", "unlikely"]
"""Pretraining-contamination risk for a replay case (SPEC §5). "likely" when the event precedes the model's
training cutoff; never claim "none"."""

ForecastVariant = Literal["agent_only", "agent_plus_market", "hosted_comparator"]
"""agent_only: no market price in the prompt. agent_plus_market: same evidence + as-of market quote.
hosted_comparator: optional hosted model on the same frozen evidence, labeled "hosted-model comparison,
not air-gapped" (SPEC §6)."""

Decision = Literal["act", "wait", "hedge"]
Venue = Literal["kalshi", "polymarket"]
QuoteKind = Literal["midpoint", "candle_close", "last_trade"]

MARKET_PROBABILITY_LABEL = "market-implied probability (price-derived; affected by fees, spread, liquidity)"


class Provenance(StrEnum):
    """Provenance label carried by every displayed datum (AGENTS.md §4).

    Wire format: the enum VALUE (`REAL_HISTORICAL`, `SYNTHETIC`, `RECORDED_RUN`, `SIMULATED`,
    `ILLUSTRATIVE`) is the canonical form in JSON, fixtures, SQLite and API responses. Every workstream
    (backend, markets, finance, research, web) uses exactly these strings.
    `.label` gives the spaced display text (e.g. "REAL HISTORICAL") for UI badges only; it is never
    accepted as input.
    """

    REAL_HISTORICAL = "REAL_HISTORICAL"
    SYNTHETIC = "SYNTHETIC"
    RECORDED_RUN = "RECORDED_RUN"
    SIMULATED = "SIMULATED"
    ILLUSTRATIVE = "ILLUSTRATIVE"

    @property
    def label(self) -> str:
        """Human-facing badge text, e.g. "REAL HISTORICAL"."""
        return self.value.replace("_", " ")


class ErrorCode(StrEnum):
    """Every machine-readable API error code. The single source: routes, errors.py and agents/ import it.

    HTTP status is chosen by the raiser, not encoded here. New codes are appended (existing order kept).
    """

    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"  # model server down, timeout, model not installed
    NO_FEASIBLE_PLAN = "NO_FEASIBLE_PLAN"
    NOT_REVEALABLE = "NOT_REVEALABLE"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    NOT_FOUND = "NOT_FOUND"
    # routes (routes/__init__.py RouteError)
    VALIDATION_ERROR = "VALIDATION_ERROR"  # request body / query failed validation (422)
    INFEASIBLE_INPUT = "INFEASIBLE_INPUT"  # valid shape, but financing that cannot happen (422)
    DATA_UNAVAILABLE = "DATA_UNAVAILABLE"  # a required data file is missing (503)
    DATA_INVALID = "DATA_INVALID"  # a data file exists but fails its schema (500)
    # model provider (agents/provider.py exceptions): each means there is NO forecast for the call
    MODEL_OUTPUT_INVALID = "MODEL_OUTPUT_INVALID"  # answer failed output validation on every attempt
    PROMPT_TOO_LONG = "PROMPT_TOO_LONG"  # prompt + answer budget exceeds the context window; refused, not truncated
    PROMPT_NOT_VERIFIED = "PROMPT_NOT_VERIFIED"  # cannot confirm the model saw the whole prompt; answer discarded
    # public mode: admin-only routes (replay run / reveal; Live Explore search, #60) need FAULTLINE_ADMIN_TOKEN
    ADMIN_TOKEN_REQUIRED = "ADMIN_TOKEN_REQUIRED"
    PREDICTION_EXISTS = "PREDICTION_EXISTS"  # a forecast with this id is already persisted (append-only store)
    # Live Explore (routes/explore.py, #60)
    RATE_LIMITED = "RATE_LIMITED"  # too many requests from this address, or from us upstream (429, Retry-After)
    LIVE_EXPLORE_UNAVAILABLE = "LIVE_EXPLORE_UNAVAILABLE"  # TAVILY_API_KEY unset, rejected, or over quota (503)
    LIVE_EXPLORE_UPSTREAM_ERROR = "LIVE_EXPLORE_UPSTREAM_ERROR"  # Tavily unreachable or unexpected answer (502)
    LIVE_EXPLORE_TIMEOUT = "LIVE_EXPLORE_TIMEOUT"  # Tavily did not answer within the timeout (504)
    # POST /api/optimize: every solver slot is busy (routes/optimize.py MAX_CONCURRENT_SOLVES); 503 with Retry-After
    BUSY = "BUSY"
    # LIVE EXPLORE chat (routes/explore_chat.py, #187)
    UPSTREAM_ERROR = "UPSTREAM_ERROR"  # the hosted model provider failed or answered unexpectedly (502)
    PAUSED = "PAUSED"  # the presenter paused the public chat (503); admin calls still work
    BUDGET = "BUDGET"  # the chat's daily spend ceiling is reached (503); admin calls still work


class ApiError(BaseModel):
    """Body of every non-2xx response raised through errors.FaultlineError."""

    model_config = ConfigDict(extra="forbid")

    code: ErrorCode
    message: str


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# ---------------------------------------------------------------- evidence & market references


class EvidenceItem(_Strict):
    """One dated source document for a replay case.

    Only `core.temporal_gate.EvidenceStore.get_as_of` may hand these to a prompt, and only when
    `available_at <= as_of` and `retrospective_unverified is False`.
    """

    evidence_id: Identifier
    event_id: Identifier
    title: str
    source_url: str
    archive_url: str | None = Field(
        default=None, description="Archived snapshot proving the text existed at that date."
    )
    published_at: AwareDatetime
    observed_at: AwareDatetime = Field(description="When we collected it.")
    available_at: AwareDatetime = Field(description="First known public availability.")
    content_sha256: Sha256Hex
    content: str
    retrospective_unverified: bool = Field(
        default=False,
        description="True if we cannot prove this text existed at available_at; such items are never given to a model.",
    )
    provenance: Provenance

    @field_validator("source_url", "archive_url")
    @classmethod
    def _http_url(cls, v: str | None) -> str | None:
        if v is None:
            return v
        parts = urlsplit(v)
        if parts.scheme not in ("http", "https") or not parts.netloc:
            raise ValueError("must be an absolute http(s) URL")
        return v

    @model_validator(mode="after")
    def _available_not_before_published(self) -> EvidenceItem:
        if self.published_at is not None and self.available_at is not None and self.available_at < self.published_at:
            raise ValueError("available_at must be >= published_at")
        return self


class MarketQuoteRef(_Strict):
    """Reference to one normalized, as-of market quote (normalization lives in markets/normalize.py).

    `p_yes` is already normalized to [0, 1] at ingestion (MATH_MODEL §7).
    """

    quote_id: Identifier
    venue: Venue
    market_id: str = Field(min_length=1, description="Kalshi ticker or Polymarket market/condition id.")
    ts: AwareDatetime = Field(description="Quote timestamp; must satisfy as_of - 24h <= ts <= as_of to be used.")
    p_yes: Probability
    quote_kind: QuoteKind
    raw_payload_sha256: Sha256Hex
    provenance: Provenance
    label: Literal["market-implied probability (price-derived; affected by fees, spread, liquidity)"] = (
        MARKET_PROBABILITY_LABEL
    )


# ---------------------------------------------------------------- replay cases


class ReplayCase(_Strict):
    """Internal case definition (SPEC §5). Never returned directly by an endpoint: use ReplayCasePublic.

    The realized outcome is NOT part of this model; it is stored under data/sealed_outcomes/ and read
    only by core/evaluator.py after a prediction is persisted.
    """

    event_id: Identifier
    title: str
    as_of: AwareDatetime
    horizon_days: int = Field(gt=0)
    resolution_rule: str = Field(description="Exact quoted settlement criteria (the rule text, never the result).")
    evidence_ids: list[Identifier]
    market_quote_id: Identifier | None = None
    snapshot_hash: PrefixedSha256
    synthetic: bool
    contamination_flag: ContaminationFlag = "unknown"
    provenance: Provenance


class ReplayCasePublic(_Strict):
    """Pre-reveal view of a replay case for /api/cases. Has no outcome-like field names at all.

    The settlement rule is exposed as `question_criteria` so that no public key matches
    OUTCOME_FIELD_PATTERN, which keeps the "walk the JSON for outcome keys" tests strict.
    """

    event_id: Identifier
    title: str
    as_of: AwareDatetime
    horizon_days: int = Field(gt=0)
    question_criteria: str
    evidence_ids: list[Identifier]
    market_quote_id: Identifier | None = None
    snapshot_hash: PrefixedSha256
    synthetic: bool
    contamination_flag: ContaminationFlag
    provenance: Provenance

    @classmethod
    def from_case(cls, case: ReplayCase) -> ReplayCasePublic:
        return cls(
            event_id=case.event_id,
            title=case.title,
            as_of=case.as_of,
            horizon_days=case.horizon_days,
            question_criteria=case.resolution_rule,
            evidence_ids=list(case.evidence_ids),
            market_quote_id=case.market_quote_id,
            snapshot_hash=case.snapshot_hash,
            synthetic=case.synthetic,
            contamination_flag=case.contamination_flag,
            provenance=case.provenance,
        )


# ---------------------------------------------------------------- predictions


class Prediction(_Strict):
    """A model forecast, persisted (with hashes) BEFORE any outcome is revealed (SPEC §5).

    prompt_sha256 = SHA256 of the exact prompt string the model saw on the attempt that validated (#44):
    the gated prompt itself when ``attempts == 1``, the gated prompt followed by exactly the provider's repair
    instruction (fixed header and footer, only ``- ...`` problem lines between) when ``attempts == 2``. No other
    value of ``attempts`` and no other suffix is accepted by ``core.store``.
    gated_prompt_sha256 = SHA256 of the prompt rendered by the temporal gate (``ModelInput.prompt``).
    snapshot_sha256 = SHA256 of canonical JSON (sorted keys, UTF-8, no whitespace) of the exact evidence
    + quote list given to the model.

    The model-run audit fields (``gated_prompt_sha256``, ``attempts``, ``transcript_sha256``, ``num_ctx``,
    ``num_predict``) are set by ``POST /api/replay/run`` on every new forecast. ``None`` only on records made
    without a model provider (core tests), for which the stored prompt is the gated prompt.
    """

    prediction_id: Identifier
    event_id: Identifier
    as_of: AwareDatetime
    agent_model: str = Field(min_length=1, description='e.g. "ollama/<installed-model-id>"')
    model_digest: str | None = Field(default=None, description="Ollama model digest when available.")
    variant: ForecastVariant
    p_yes: Probability
    decision: Decision
    rationale: str
    evidence_ids: list[Identifier]
    prompt_sha256: Sha256Hex
    snapshot_sha256: Sha256Hex
    temperature: float = Field(ge=0.0, allow_inf_nan=False)
    seed: int | None = None
    recorded_at: AwareDatetime
    provenance: Provenance
    gated_prompt_sha256: Sha256Hex | None = Field(
        default=None, description="SHA256 of the temporal gate's rendered prompt (before any repair turn)."
    )
    attempts: int | None = Field(
        default=None,
        ge=1,
        le=2,
        description="1 = first answer validated; 2 = validated after the one schema repair (no other value).",
    )
    transcript_sha256: Sha256Hex | None = Field(
        default=None, description="SHA256 of canonical JSON of the chat messages sent on the validated attempt."
    )
    num_ctx: int | None = Field(default=None, gt=0, description="Context window the model ran with (tokens).")
    num_predict: int | None = Field(default=None, gt=0, description="Answer token budget the model ran with.")


# ---------------------------------------------------------------- health


class OllamaStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reachable: bool
    models: list[str] = Field(description="Installed model tags reported by Ollama; empty when unreachable.")
    required_model: str = Field(description="Model tag the replay pipeline is configured to use.")
    required_model_present: bool
    error: str | None = None


class OptionalKeys(BaseModel):
    """Whether optional keys are configured. Booleans only; values are never read into the response."""

    model_config = ConfigDict(extra="forbid")

    anthropic_api_key: bool
    tavily_api_key: bool


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"] = Field(description="The API process is up. Model readiness is reported separately.")
    ollama: bool = Field(description="Ollama reachable at OLLAMA_BASE_URL.")
    model_ready: bool = Field(description="Ollama reachable AND the configured replay model is installed.")
    ollama_status: OllamaStatus
    optional_keys: OptionalKeys
    data_dir_present: bool
    data_manifest_sha256: Sha256Hex | None = Field(
        description="SHA256 of <FAULTLINE_DATA_DIR>/manifest.json bytes; null when NOT AVAILABLE."
    )
    notices: list[str] = Field(description="Plain-language notes on disabled features / missing setup.")
