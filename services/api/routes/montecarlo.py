"""POST /api/montecarlo/decision and POST /api/montecarlo/cash (docs/MATH_MODEL.md §11, issue #208).

Every number in a response is computed by ``core.montecarlo`` (seeded numpy). Nothing is cached or filled in here.

- ``/montecarlo/decision``: a generic decision Monte Carlo. The inputs (drivers and their ranges) are assumptions,
  typically estimated by a model in the chat; the arithmetic is FAULTLINE's. Provenance ``SIMULATED``.
- ``/montecarlo/cash``: the §3 cash recurrence on the SYNTHETIC demo business over many shock paths drawn around a
  central scenario. With ``with_plan`` the §4 optimizer plan is computed once on the central scenario (the same solve as
  POST /api/optimize) and held fixed on every path. Provenance ``SIMULATED``; the uncertainty ranges are ILLUSTRATIVE.

Both are deterministic for a given request (same input + seed -> same output; ``runtime_ms`` aside) and public in
public mode, like /api/simulate. Bad input returns the coded 422 body (``RouteErrorBody``).
"""

from __future__ import annotations

import time
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from config import Settings, get_settings
from core.financials import ActionPlan, ScenarioShock, simulate
from core.montecarlo import (
    DEFAULT_SEED,
    CashResponse,
    DecisionRequest,
    DecisionResponse,
    canonical_sha256,
    run_cash,
    run_decision,
)
from core.optimizer import optimize
from models import ErrorCode, Identifier
from routes import CodedRoute, RouteError, RouteErrorBody, error_responses
from routes.optimize import (
    BUSY_MESSAGE,
    BUSY_RETRY_AFTER_S,
    SOLVE_QUEUE_WAIT_S,
    SOLVE_SLOTS,
    load_optimizer_settings,
)
from routes.scenarios import load_scenarios
from routes.simulate import _OVERFLOW_MESSAGE, CUSTOM_NAME, load_business, series_length_issues

router = APIRouter(tags=["montecarlo"], route_class=CodedRoute)


@router.post(
    "/montecarlo/decision",
    response_model=DecisionResponse,
    responses=error_responses(422),
    summary="Decision Monte Carlo: compare 2-4 options over sampled drivers (SIMULATED)",
)
def decision_montecarlo(body: DecisionRequest) -> DecisionResponse:
    try:
        return run_decision(body)
    except (ValidationError, OverflowError, ValueError) as exc:
        message = str(exc) if type(exc) is ValueError else "the drivers produced a non-finite value"
        raise RouteError(ErrorCode.VALIDATION_ERROR, f"Monte Carlo inputs out of range: {message}.") from None


class CashRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario_id: Identifier | None = Field(
        default=None,
        description="Named scenario (GET /api/scenarios). Used for the central shock when `shock` is not given.",
    )
    shock: ScenarioShock | None = Field(
        default=None, description="Central shock, same model as POST /api/simulate. Wins over `scenario_id`."
    )
    protect_payroll: bool = True
    with_plan: bool = True
    n_paths: Annotated[int, Field(ge=1000, le=50_000)] = 10_000
    seed: Annotated[int, Field(ge=0, le=2**63 - 1)] = DEFAULT_SEED


def _central_shock(body: CashRequest, settings: Settings) -> ScenarioShock:
    if body.shock is not None:
        explicit = "name" in body.shock.model_fields_set and body.shock.name not in ("", "baseline")
        return body.shock if explicit else body.shock.model_copy(update={"name": body.scenario_id or CUSTOM_NAME})
    if body.scenario_id is None:
        return ScenarioShock()  # no shock: only the weekly demand noise varies
    scenarios = load_scenarios(settings) or []
    match = next((s for s in scenarios if s.id == body.scenario_id), None)
    if match is None:
        raise RouteError(ErrorCode.NOT_FOUND, f"Unknown scenario_id '{body.scenario_id}' (see GET /api/scenarios).",
                         status_code=404)
    return match.shock


@router.post(
    "/montecarlo/cash",
    response_model=CashResponse,
    responses={
        **error_responses(422, 500),
        404: {"model": RouteErrorBody, "description": "NOT_FOUND: unknown scenario_id"},
        503: {"model": RouteErrorBody, "description": "DATA_UNAVAILABLE, or BUSY: every solver slot is taken"},
    },
    summary="Cash-flow Monte Carlo on the SYNTHETIC demo business (SIMULATED, ILLUSTRATIVE ranges)",
)
async def cash_montecarlo(
    body: CashRequest, settings: Annotated[Settings, Depends(get_settings)]
) -> CashResponse:
    if not body.with_plan:
        return await run_in_threadpool(_run_cash, body, settings)
    # The plan is one /api/optimize solve, so it shares that route's concurrency cap.
    if not await SOLVE_SLOTS.acquire(SOLVE_QUEUE_WAIT_S):
        raise RouteError(
            ErrorCode.BUSY, BUSY_MESSAGE, status_code=503, headers={"Retry-After": str(BUSY_RETRY_AFTER_S)}
        )
    try:
        return await run_in_threadpool(_run_cash, body, settings)
    finally:
        SOLVE_SLOTS.release()


def _run_cash(body: CashRequest, settings: Settings) -> CashResponse:
    started = time.perf_counter()
    business = load_business(settings)
    shock = _central_shock(body, settings)
    issues = series_length_issues(business.horizon_weeks, shock, ActionPlan())
    if issues:
        raise RouteError(ErrorCode.VALIDATION_ERROR, "Weekly series length does not match the horizon.",
                         errors=issues)
    try:
        simulate(business, shock, ActionPlan())  # the central path must be physically possible (§3), as in /simulate
        plan_result = None
        if body.with_plan:
            opt_settings = load_optimizer_settings(settings)
            plan_result = optimize(business, shock, body.protect_payroll, opt_settings)
        return run_cash(
            business, shock, scenario_id=body.scenario_id, n_paths=body.n_paths, seed=body.seed,
            input_sha256=canonical_sha256(body.model_dump(mode="json")), plan_result=plan_result,
            started_at=started,
        )
    except (ValidationError, OverflowError):
        raise RouteError(ErrorCode.VALIDATION_ERROR, _OVERFLOW_MESSAGE) from None
    except ValueError as exc:
        raise RouteError(ErrorCode.INFEASIBLE_INPUT, str(exc)) from None
