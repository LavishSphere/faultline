"""POST /api/optimize: the MATH_MODEL §4 recovery MILP on the SYNTHETIC demo business (issue #47).

Every number in the response comes from ``core.optimizer.optimize`` run on the business and the signed-off
``optimizer_parameters`` in ``<FAULTLINE_DATA_DIR>/demo_business.json``. Nothing is cached, rounded or filled in here.

Request: ``{"scenario_id"?, "shock", "protect_payroll"}``, the same shock model as POST /api/simulate.

Response: the OptimizationResult fields verbatim (``provenance: "SIMULATED"``) plus ``business_provenance``.
The three statuses are all answers, so all are 200:
- ``OPTIMAL``: plan, chosen actions, cash path, min cash, binding constraints by name, objective.
- ``NO FEASIBLE PLAN``: every plan field is null; ``max_feasible_cash_floor`` is the smallest floor change that
  would make a plan exist (the highest minimum cash any plan can reach), ``diagnostic`` says it in words.
- ``SOLVER ERROR``: every plan field is null; ``solver_message`` is the solver's own message.

Bad input uses the /api/simulate coded 422 body (``RouteErrorBody``): VALIDATION_ERROR for shape / series length /
numeric overflow, INFEASIBLE_INPUT for a ValueError the engine raises on a well-shaped shock.
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from config import Settings, get_settings
from core.financials import ActionPlan, ScenarioShock
from core.optimizer import OptimizationResult, OptimizerSettings, optimize
from models import ErrorCode, Identifier
from routes import CodedRoute, RouteError, error_responses, issues_from, read_json
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
    responses=error_responses(422, 500, 503),
    summary="Least-harmful recovery plan (MILP) on the SYNTHETIC demo business",
)
def optimize_route(
    body: OptimizeRequest,
    settings: Annotated[Settings, Depends(get_settings)],
) -> OptimizeResponse:
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
        {**result.model_dump(), "business_provenance": business.provenance}
    )
