"""POST /api/optimize: the MATH_MODEL §4 recovery MILP on the SYNTHETIC demo business (issue #47).

Every number in the response comes from ``core.optimizer.optimize`` run on the business and the signed-off
``optimizer_parameters`` in ``<FAULTLINE_DATA_DIR>/demo_business.json``. Nothing is cached, rounded or filled in here.

Request: ``{"scenario_id"?, "shock", "protect_payroll"}``, the same shock model as POST /api/simulate.

Response: the OptimizationResult fields verbatim (``provenance: "SIMULATED"``) plus ``business_provenance``,
``payroll_cut_cap`` (the configured z-bar) and ``supplier_lag_weeks`` (L_p), both read from the fixture (#157).
The three statuses are all answers, so all are 200:
- ``OPTIMAL``: plan, chosen actions, cash path, min cash, binding constraints by name, objective.
- ``NO FEASIBLE PLAN``: every plan field is null; ``max_feasible_cash_floor`` is the smallest floor change that
  would make a plan exist (the highest minimum cash any plan can reach), ``diagnostic`` says it in words.
- ``SOLVER ERROR``: every plan field is null; ``solver_message`` is the solver's own message.

Bad input uses the /api/simulate coded 422 body (``RouteErrorBody``): VALIDATION_ERROR for shape / series length /
numeric overflow, INFEASIBLE_INPUT for a ValueError the engine raises on a well-shaped shock.

Concurrency cap: at most MAX_CONCURRENT_SOLVES solves run at once (per process; the deploy image runs one worker).
A request that finds every slot taken waits up to SOLVE_QUEUE_WAIT_S, then gets 503 ``BUSY`` with ``Retry-After``.
That is an honest "try again", never a cached or partial plan. Waiting requests hold no worker thread.
"""

from __future__ import annotations

import asyncio
import threading
import time
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from config import Settings, get_settings
from core.financials import ActionPlan, ScenarioShock
from core.optimizer import OptimizationResult, OptimizerSettings, optimize
from models import ErrorCode, Identifier
from routes import CodedRoute, RouteError, RouteErrorBody, error_responses, issues_from, read_json
from routes.simulate import (
    _OVERFLOW_MESSAGE,
    BASELINE_NAME,
    BUSINESS_FILE,
    CUSTOM_NAME,
    load_business,
    series_length_issues,
)

router = APIRouter(tags=["optimize"], route_class=CodedRoute)

SETTINGS_SECTION = "optimizer_parameters"

MAX_CONCURRENT_SOLVES = 2
SOLVE_QUEUE_WAIT_S = 2.0
BUSY_RETRY_AFTER_S = 2
_POLL_S = 0.02
BUSY_MESSAGE = (
    "The optimizer is busy with other requests. No plan was computed for this request; try again in a moment."
)


class SolveSlots:
    """A counting semaphore that does not bind to an event loop (module-level, shared by every request).

    ``acquire`` polls with ``asyncio.sleep`` instead of parking a worker thread, so queued requests cost no thread.
    """

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self._free = limit
        self._lock = threading.Lock()

    @property
    def in_use(self) -> int:
        with self._lock:
            return self.limit - self._free

    def try_acquire(self) -> bool:
        with self._lock:
            if self._free <= 0:
                return False
            self._free -= 1
            return True

    def release(self) -> None:
        with self._lock:
            if self._free >= self.limit:
                raise RuntimeError("SolveSlots released more often than acquired")
            self._free += 1

    async def acquire(self, wait_s: float) -> bool:
        deadline = time.monotonic() + wait_s
        while not self.try_acquire():
            if time.monotonic() >= deadline:
                return False
            await asyncio.sleep(_POLL_S)
        return True


SOLVE_SLOTS = SolveSlots(MAX_CONCURRENT_SOLVES)


class OptimizeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario_id: Identifier | None = Field(
        default=None,
        description="Optional named-scenario id, used only to name the result when `shock.name` is not given.",
    )
    shock: ScenarioShock = Field(description="Scenario shocks, same model as POST /api/simulate; `{}` = no shock.")
    protect_payroll: bool = Field(description="True: payroll cuts are forbidden (z_t <= 0, MATH_MODEL §4.5).")


class OptimizeResponse(OptimizationResult):
    """OptimizationResult verbatim, plus the provenance of the business it ran on."""

    business_provenance: Literal["SYNTHETIC", "ILLUSTRATIVE"] = Field(
        description="Provenance of the fictional demo business the optimizer ran on."
    )
    payroll_cut_cap: float = Field(
        description=(
            "z-bar, the configured payroll-cut cap per week (MATH_MODEL §4, §10), as read from the fixture. "
            "With protect_payroll the solver uses 0 instead (§4.5); this field still reports the configured cap."
        )
    )
    supplier_lag_weeks: int = Field(
        description="L_p, the supplier payment lag (MATH_MODEL §3, §10): a week-t purchase cut reaches cash in t + L_p."
    )


def load_optimizer_settings(settings: Settings) -> OptimizerSettings:
    payload = read_json(settings.data_dir / BUSINESS_FILE, BUSINESS_FILE)
    raw = payload.get(SETTINGS_SECTION) if isinstance(payload, dict) else None
    if not isinstance(raw, dict):
        raise RouteError(
            ErrorCode.DATA_INVALID, f"{BUSINESS_FILE} must contain an `{SETTINGS_SECTION}` object.", status_code=500
        )
    try:
        return OptimizerSettings.from_dict(raw)
    except ValidationError as exc:
        raise RouteError(
            ErrorCode.DATA_INVALID,
            f"{BUSINESS_FILE} `{SETTINGS_SECTION}` failed the OptimizerSettings schema.",
            status_code=500,
            errors=issues_from(exc.errors(), prefix=(BUSINESS_FILE, SETTINGS_SECTION)),
        ) from None


def _result_name(body: OptimizeRequest) -> str:
    explicit = "name" in body.shock.model_fields_set and body.shock.name not in ("", BASELINE_NAME)
    if explicit:
        return body.shock.name
    return body.scenario_id or CUSTOM_NAME


@router.post(
    "/optimize",
    response_model=OptimizeResponse,
    responses={
        **error_responses(422, 500, 503),
        503: {
            "model": RouteErrorBody,
            "description": "DATA_UNAVAILABLE: a required data file is missing; BUSY: every solver slot is taken "
            "(Retry-After says when to try again)",
        },
    },
    summary="Least-harmful recovery plan (MILP) on the SYNTHETIC demo business",
)
async def optimize_route(
    body: OptimizeRequest,
    settings: Annotated[Settings, Depends(get_settings)],
) -> OptimizeResponse:
    if not await SOLVE_SLOTS.acquire(SOLVE_QUEUE_WAIT_S):
        raise RouteError(
            ErrorCode.BUSY, BUSY_MESSAGE, status_code=503, headers={"Retry-After": str(BUSY_RETRY_AFTER_S)}
        )
    try:
        # Once the worker thread starts, anyio shields this await until the solve returns, so the slot is released
        # only after the solve really finished (a client disconnect cannot free it early).
        return await run_in_threadpool(_solve, body, settings)
    finally:
        SOLVE_SLOTS.release()


def _solve(body: OptimizeRequest, settings: Settings) -> OptimizeResponse:
    business = load_business(settings)
    opt_settings = load_optimizer_settings(settings)
    if business.min_cash is None or business.min_inventory is None:
        raise RouteError(
            ErrorCode.DATA_INVALID,
            f"{BUSINESS_FILE} `business` needs min_cash (C_min) and min_inventory (I_min) for the optimizer.",
            status_code=500,
        )

    issues = series_length_issues(business.horizon_weeks, body.shock, ActionPlan())
    if issues:
        raise RouteError(ErrorCode.VALIDATION_ERROR, "Weekly series length does not match the horizon.",
                         errors=issues)

    shock = body.shock.model_copy(update={"name": _result_name(body)})
    try:
        result = optimize(business, shock, body.protect_payroll, opt_settings)
    except (ValidationError, OverflowError):
        # Must precede ValueError (ValidationError subclasses it); its dump can echo values.
        raise RouteError(ErrorCode.VALIDATION_ERROR, _OVERFLOW_MESSAGE) from None
    except ValueError as exc:
        raise RouteError(ErrorCode.INFEASIBLE_INPUT, str(exc)) from None

    return OptimizeResponse.model_validate(
        {
            **result.model_dump(),
            "business_provenance": business.provenance,
            "payroll_cut_cap": opt_settings.payroll_cut_cap,
            "supplier_lag_weeks": business.supplier_lag_weeks,
        }
    )
