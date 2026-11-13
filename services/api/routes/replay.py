"""Blind Replay over HTTP (SPEC §5, §8; issue #44): run a forecast, then reveal it only after it is saved.

Both routes change state, so in public mode both are admin-only, enforced HERE (``require_admin_in_public_mode``),
with or without #28's edge middleware: an early public reveal would mark the event revealed and silently
disqualify later admin runs. Local mode is open.

``POST /api/replay/run`` ``{case_id, variant}`` (pre-reveal):

1. the temporal gate: ``EvidenceStore`` over ``demo_cases/`` (``routes.cases.load_evidence_store``), then
   ``snap = get_as_of(case_id, <case cutoff>)`` and ``mi = snap.model_input(variant)``;
2. the model provider (``LocalOllamaProvider`` by default) gets exactly ``mi.prompt`` and ``mi.evidence_ids``;
3. ``agents.skeptic.review`` re-checks the answer; an error-level problem is a 422 and nothing is persisted;
4. ``PredictionStore.save(prediction, mi, final_prompt=result.final_prompt)`` persists the forecast BEFORE any
   reveal, with ``prompt_sha256 = sha256(final_prompt)`` (what the model saw, incl. a repair turn),
   ``gated_prompt_sha256 = mi.prompt_sha256`` and the run's attempts / transcript hash / num_ctx / num_predict /
   model digest;
5. the response is built from outcome-free models only, plus the market-implied probability at the cutoff
   from the same snapshot (or NOT AVAILABLE).

No provider error becomes a forecast: ``ModelUnavailable`` -> 503 MODEL_UNAVAILABLE; ``PromptTooLong`` /
``PromptNotVerified`` / ``ModelOutputInvalid`` -> 422 with their ``models.ErrorCode``; none of them is persisted.

``POST /api/replay/{prediction_id}/reveal`` (post-reveal): ``OutcomeVault.reveal`` (409 NOT_REVEALABLE unless
persisted with intact hashes; 404 NOT_FOUND when no sealed outcome exists), then per-prediction scores and the
naive / market baselines, the latter from the scoring context the gate fixed when the forecast was saved.
The run handler never touches the vault; the sealed directory is read only inside ``OutcomeVault.reveal``.
"""

from __future__ import annotations

import hmac
import os
from datetime import UTC, datetime
from typing import Annotated, Any, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, Request
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from agents import skeptic
from agents.local_ollama import LocalOllamaProvider
from agents.provider import (
    ForecastResult,
    ModelOutputInvalid,
    ModelProvider,
    ModelUnavailable,
    PromptNotVerified,
    PromptTooLong,
    ProviderError,
)
from agents.skeptic import SkepticProblem
from config import Settings, get_settings
from core import provenance as prov
from core import store as store_module
from core.evaluator import OutcomeVault, SealedOutcome, SealedOutcomeInvalid, brier, correct_at_half, log_loss
from core.store import HashMismatch, PredictionExists, PredictionStore
from core.temporal_gate import MarketNotAvailable, ModelInput
from errors import FaultlineError
from models import ApiError, ErrorCode, Identifier, Prediction, Provenance
from routes import CodedRoute, FieldIssue, RouteError
from routes.cases import MarketAtCutoff, coded_responses, market_at_cutoff, require_case_store

router = APIRouter(tags=["replay"], route_class=CodedRoute)

NAIVE_P_YES = 0.5
# A forecast made by running the model and persisting it with its hashes is recorded inference.
RUN_PROVENANCE = Provenance.RECORDED_RUN

_PROVIDER_ERRORS: dict[type[ProviderError], tuple[ErrorCode, int]] = {
    ModelUnavailable: (ErrorCode.MODEL_UNAVAILABLE, 503),
    PromptTooLong: (ErrorCode.PROMPT_TOO_LONG, 422),
    PromptNotVerified: (ErrorCode.PROMPT_NOT_VERIFIED, 422),
    ModelOutputInvalid: (ErrorCode.MODEL_OUTPUT_INVALID, 422),
}


# ---------------------------------------------------------------- dependencies (tests override these)


def get_provider(settings: Annotated[Settings, Depends(get_settings)]) -> ModelProvider:
    return LocalOllamaProvider.from_settings(settings)


def get_prediction_store() -> PredictionStore:
    # Read at call time: the configured store is the one OutcomeVault accepts for the configured sealed folder.
    return PredictionStore(store_module.DEFAULT_DB_PATH)


# ---------------------------------------------------------------- public-mode admin gate (route level)

# Same rules as PR #28 (config.admin_token_matches): a token shorter than this counts as not configured.
MIN_ADMIN_TOKEN_LEN = 32
_ADMIN_MESSAGE = (
    "Admin only on the public demo: running or revealing a forecast needs the admin token "
    "(Authorization: Bearer <FAULTLINE_ADMIN_TOKEN>). The public demo shows RECORDED RUN predictions; "
    "run the app locally for live replay."
)


def public_mode() -> bool:
    """Fail closed: anything but an unset/empty or ``local`` FAULTLINE_MODE is public."""
    return os.environ.get("FAULTLINE_MODE", "").strip().lower() not in ("", "local")


def require_admin_in_public_mode(request: Request) -> None:
    """401 when no bearer token is presented; 403 when it is wrong or no strong token is configured."""
    if not public_mode():
        return
    scheme, _, presented = request.headers.get("authorization", "").partition(" ")
    presented = presented.strip()
    if scheme.lower() != "bearer" or not presented:
        raise FaultlineError(ErrorCode.ADMIN_TOKEN_REQUIRED, _ADMIN_MESSAGE, status_code=401)
    expected = os.environ.get("FAULTLINE_ADMIN_TOKEN", "").strip()
    if len(expected) < MIN_ADMIN_TOKEN_LEN or not hmac.compare_digest(
        presented.encode("utf-8"), expected.encode("utf-8")
    ):
        raise FaultlineError(ErrorCode.ADMIN_TOKEN_REQUIRED, _ADMIN_MESSAGE, status_code=403)


_ADMIN_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"model": ApiError, "description": "ADMIN_TOKEN_REQUIRED (public mode): no bearer token presented"},
    403: {"model": ApiError, "description": "ADMIN_TOKEN_REQUIRED (public mode): wrong token, or none configured"},
}


# ---------------------------------------------------------------- run


class ReplayRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: Identifier = Field(description="event_id of a case from GET /api/cases.")
    variant: Literal["agent_only", "agent_plus_market"] = Field(
        description="agent_only: no market price in the prompt. agent_plus_market: same evidence plus the as-of quote."
    )


class SkepticReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    problems: list[SkepticProblem] = Field(
        description="Warnings only (an error-level problem rejects the forecast with 422 before it is saved)."
    )


class ReplayRunResponse(BaseModel):
    """Pre-reveal: no outcome-like field anywhere (tests walk the schema and the JSON)."""

    model_config = ConfigDict(extra="forbid", json_schema_serialization_defaults_required=True)

    prediction: Prediction = Field(description="As persisted, before any reveal. provenance = RECORDED_RUN.")
    skeptic: SkepticReview
    market_at_cutoff: MarketAtCutoff = Field(
        description="Market-implied probability at the cutoff from the same gate snapshot (the scoring baseline)."
    )
    persisted_at: AwareDatetime = Field(description="Store clock when the forecast was saved.")
    persist_seq: int = Field(description="Position of the save in the store's append-only audit log.")
    record_sha256: str = Field(
        description="SHA256 over the whole stored forecast, its scoring context and persist mark."
    )
    # Was this forecast saved after a reveal? (From the audit log; no value of any revealed result is exposed.)
    event_first_reveal_seq: int | None = Field(
        description="audit_log position of the first reveal of ANY prediction for this event; null = never revealed."
    )
    persisted_after_event_reveal: bool = Field(
        description="True: saved after this event's result was already revealed in this store. Not a blind "
        "forecast for scoring; the benchmark ignores it (persisted_after_outcome_revealed)."
    )
    store_first_reveal_seq: int | None = Field(
        description="audit_log position of the first reveal of any prediction in the whole store; null = none."
    )
    persisted_after_any_reveal: bool = Field(
        description="True: saved after some reveal in this store (any event); such a run cannot be OFFICIAL."
    )
    audit_note: str | None = Field(description="Plain-language warning when either flag is true; else null.")


def _audit_note(after_event: bool, after_any: bool) -> str | None:
    if after_event:
        return (
            "Saved AFTER this event's result was already revealed in this store: not a blind forecast. The "
            "benchmark ignores it, and it blocks an OFFICIAL scorecard."
        )
    if after_any:
        return (
            "Saved after another event's result was revealed in this store: the run cannot be OFFICIAL "
            "(every scored forecast must precede the first reveal anywhere)."
        )
    return None


def prediction_from_result(
    mi: ModelInput,
    result: ForecastResult,
    provider: ModelProvider,
    *,
    prediction_id: str,
    recorded_at: datetime,
    provenance: Provenance,
) -> Prediction:
    """The Prediction to persist for one validated forecast (shared with scripts/record_runs.py).

    ``prompt_sha256`` hashes what the model answered (``result.final_prompt``, incl. a repair turn) and
    ``gated_prompt_sha256`` the gate's prompt; persist it with ``store.save(prediction, mi, final_prompt=...)``.
    """
    out = result.output
    return Prediction(
        prediction_id=prediction_id,
        event_id=mi.event_id,
        as_of=datetime.fromisoformat(mi.as_of),
        agent_model=result.agent_model,
        model_digest=result.model_digest,
        variant=mi.variant,
        p_yes=out.p_yes,
        decision=out.decision,
        rationale=out.rationale,
        evidence_ids=list(out.evidence_ids),
        prompt_sha256=prov.prompt_sha256(result.final_prompt),
        snapshot_sha256=mi.snapshot_sha256,
        temperature=result.temperature,
        seed=result.seed,
        recorded_at=recorded_at,
        provenance=provenance,
        gated_prompt_sha256=mi.prompt_sha256,
        attempts=result.attempts,
        transcript_sha256=result.transcript_sha256,
        num_ctx=getattr(provider, "num_ctx", None),
        num_predict=getattr(provider, "num_predict", None),
    )


def _provider_error(exc: ProviderError) -> RouteError:
    for cls, (code, status) in _PROVIDER_ERRORS.items():
        if isinstance(exc, cls):
            # Provider messages name what failed (never a URL, never model text); no forecast is shown.
            return RouteError(code, f"No forecast: {exc}", status_code=status)
    return RouteError(ErrorCode.MODEL_UNAVAILABLE, f"No forecast: {type(exc).__name__}.", status_code=503)


def _skeptic_rejection(report: skeptic.SkepticReport) -> RouteError:
    errors = [p for p in report.problems if p.severity == "error"]
    # Codes and fixed messages only: the rejected forecast (and any id it invented) is not echoed.
    issues = [FieldIssue(loc=["skeptic", p.code], msg=p.message, type=p.code) for p in errors]
    return RouteError(
        ErrorCode.MODEL_OUTPUT_INVALID,
        "No forecast: the skeptic rejected the model's answer; it was not saved.",
        status_code=422,
        errors=issues,
    )


@router.post(
    "/replay/run",
    response_model=ReplayRunResponse,
    dependencies=[Depends(require_admin_in_public_mode)],
    responses=_ADMIN_RESPONSES
    | coded_responses(
        _404="NOT_FOUND: unknown case, or no cases yet",
        _422=(
            "VALIDATION_ERROR (bad body), INSUFFICIENT_DATA (agent_plus_market without a market quote), "
            "PROMPT_TOO_LONG, PROMPT_NOT_VERIFIED, MODEL_OUTPUT_INVALID (incl. skeptic rejection). Nothing saved."
        ),
        _409="PREDICTION_EXISTS: a forecast with this id is already persisted",
        _500="DATA_INVALID: a case file failed a check, or the forecast failed its audit-hash check (not saved)",
        _503="MODEL_UNAVAILABLE: the local model could not be called. Nothing saved; no substitute answer.",
    ),
    summary="Run one sealed Blind Replay forecast and persist it before any reveal",
)
async def run_replay(
    body: ReplayRunRequest,
    settings: Annotated[Settings, Depends(get_settings)],
    provider: Annotated[ModelProvider, Depends(get_provider)],
) -> ReplayRunResponse:
    cases = require_case_store(settings, body.case_id)
    snap = cases.get_as_of(body.case_id, cases.public_case(body.case_id).as_of)
    try:
        mi = snap.model_input(body.variant)
    except MarketNotAvailable:
        raise RouteError(
            ErrorCode.INSUFFICIENT_DATA,
            "agent_plus_market cannot run: no market quote within 24h before the cutoff (market NOT AVAILABLE).",
        ) from None

    try:
        result = await provider.forecast(mi.prompt, mi.evidence_ids)
    except ProviderError as exc:
        raise _provider_error(exc) from None

    report = skeptic.review(result.output, mi.evidence_ids)
    if report.rejected:
        raise _skeptic_rejection(report)

    prediction = prediction_from_result(
        mi,
        result,
        provider,
        prediction_id=f"pred_{uuid4().hex}",
        recorded_at=datetime.now(UTC),
        provenance=RUN_PROVENANCE,
    )
    store = get_prediction_store()
    try:
        stored = store.save(prediction, mi, final_prompt=result.final_prompt)
    except PredictionExists:
        raise RouteError(
            ErrorCode.PREDICTION_EXISTS, "A forecast with this id is already persisted; nothing was saved.", 409
        ) from None
    except HashMismatch:
        # The forecast does not match the gate input it was made from; the exception names hashes, not data.
        raise RouteError(
            ErrorCode.DATA_INVALID,
            "The forecast's audit hashes do not match its gated input; it was not saved.",
            status_code=500,
        ) from None
    event_first, store_first = store.first_reveal(mi.event_id), store.first_reveal_any()
    after_event = event_first is not None and event_first.seq < stored.persist_seq
    after_any = store_first is not None and store_first.seq < stored.persist_seq
    return ReplayRunResponse(
        prediction=stored.prediction,
        skeptic=SkepticReview(problems=list(report.problems)),
        market_at_cutoff=market_at_cutoff(snap, mi.market_baseline_ref, mi.market_baseline_p_yes),
        persisted_at=stored.persisted_at,
        persist_seq=stored.persist_seq,
        record_sha256=stored.record_sha256,
        event_first_reveal_seq=None if event_first is None else event_first.seq,
        persisted_after_event_reveal=after_event,
        store_first_reveal_seq=None if store_first is None else store_first.seq,
        persisted_after_any_reveal=after_any,
        audit_note=_audit_note(after_event, after_any),
    )


# ---------------------------------------------------------------- reveal (post-reveal)


class PredictionScores(BaseModel):
    model_config = ConfigDict(extra="forbid")

    brier: float
    log_loss: float
    accuracy_at_0_5: float = Field(description="1.0 if p > 0.5 called it right (p = 0.5 counts as NO), else 0.0.")


class MarketBaselineScores(BaseModel):
    model_config = ConfigDict(extra="forbid")

    p_yes: float = Field(description="Market-implied probability (price-derived) fixed by the gate before reveal.")
    brier: float
    log_loss: float


class NaiveBaselineScores(BaseModel):
    model_config = ConfigDict(extra="forbid")

    brier: float = Field(description="Scores of the constant forecast p = 0.5.")
    log_loss: float


class Baselines(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_serialization_defaults_required=True)

    market: MarketBaselineScores | None = Field(description="null = market baseline NOT AVAILABLE at this as_of.")
    naive: NaiveBaselineScores


class RevealResponse(BaseModel):
    """Contract fixed by the lead on #44 (2026-11-13)."""

    model_config = ConfigDict(extra="forbid", json_schema_serialization_defaults_required=True)

    prediction: Prediction
    y: Literal[0, 1]
    sealed: SealedOutcome
    revealed_at: AwareDatetime
    persisted_at: AwareDatetime
    persist_seq: int
    reveal_seq: int
    event_first_revealed_at: AwareDatetime
    event_first_reveal_seq: int
    persisted_before_outcome_revealed: bool = Field(
        description="persist_seq < event_first_reveal_seq. False: saved after this event's outcome was first "
        "revealed, so the benchmark ignores it."
    )
    scores: PredictionScores
    baselines: Baselines


def _reveal_responses() -> dict[int | str, dict[str, Any]]:
    return {
        404: {"model": ApiError, "description": "NOT_FOUND: no sealed outcome for this event (NOT AVAILABLE)"},
        409: {"model": ApiError, "description": "NOT_REVEALABLE: not persisted, or its audit hashes do not match"},
        **coded_responses(
            _422="VALIDATION_ERROR: malformed path", _500="DATA_INVALID: the sealed outcome file failed its check"
        ),
    }


@router.post(
    "/replay/{prediction_id}/reveal",
    response_model=RevealResponse,
    dependencies=[Depends(require_admin_in_public_mode)],
    responses=_ADMIN_RESPONSES | _reveal_responses(),
    summary="Reveal the outcome of a persisted forecast and score it (appends a reveal to the audit log)",
)
def reveal_prediction(prediction_id: str) -> RevealResponse:
    store = get_prediction_store()
    try:
        rev = OutcomeVault(store).reveal(prediction_id)  # NotRevealable (409) / OutcomeNotAvailable (404) pass through
    except SealedOutcomeInvalid:
        # A malformed sealed file or one naming another event (the message never carries the file's values).
        raise RouteError(
            ErrorCode.DATA_INVALID, "The sealed outcome file for this event failed its check.", status_code=500
        ) from None
    rec = store.get_record(prediction_id)
    assert rec is not None  # reveal() succeeded, so it is persisted
    p, y = rev.prediction.p_yes, rev.y
    market_p = rec.context.market_baseline_p_yes
    return RevealResponse(
        prediction=rev.prediction,
        y=y,
        sealed=rev.sealed,
        revealed_at=rev.revealed_at,
        persisted_at=rev.persisted_at,
        persist_seq=rev.persist_seq,
        reveal_seq=rev.reveal_seq,
        event_first_revealed_at=rev.event_first_revealed_at,
        event_first_reveal_seq=rev.event_first_reveal_seq,
        persisted_before_outcome_revealed=rev.persisted_before_outcome_revealed,
        scores=PredictionScores(brier=brier(p, y), log_loss=log_loss(p, y), accuracy_at_0_5=correct_at_half(p, y)),
        baselines=Baselines(
            market=None
            if market_p is None
            else MarketBaselineScores(p_yes=market_p, brier=brier(market_p, y), log_loss=log_loss(market_p, y)),
            naive=NaiveBaselineScores(brier=brier(NAIVE_P_YES, y), log_loss=log_loss(NAIVE_P_YES, y)),
        ),
    )
