"""POST /api/simulate: deterministic business scenario computation (SPEC §8, MATH_MODEL §1-3, §5).

Every number in the response comes from ``core.financials.simulate`` and ``cascade_deltas`` run on
the SYNTHETIC demo business in ``<FAULTLINE_DATA_DIR>/demo_business.json``. Nothing is cached,
rounded, or filled in here.

Response contract (fixed, the web app codes against it):
``{"provenance": "SIMULATED", "business_provenance": "SYNTHETIC", "baseline": SimulationResult,
"result": SimulationResult, "deltas": CascadeDeltas, "min_cash_floor": float | null,
"first_week_below_floor": int | null, "weeks_below_floor": [int]}``

- ``baseline`` = the business with no shock and no action (``ScenarioShock()``, ``ActionPlan()``),
  named "baseline".
- ``result`` = the requested shock with the requested plan (default: no action). Its name is the
  client's explicit ``shock.name``, else ``scenario_id``, else "custom"; it is never "baseline".
- Plans that would make purchases or inventory negative are rejected (422 INFEASIBLE_INPUT) until the
  engine enforces this itself (#32). Non-finite results (overflow) are rejected as VALIDATION_ERROR.
- ``deltas`` = ``cascade_deltas(baseline, result)``: per-node Δ = result - baseline (MATH_MODEL §5).
- ``min_cash_floor`` = the business's liquidity floor C_min (MATH_MODEL §4.1, §10: 25,000), read from the
  fixture; null when the fixture has none. ``weeks_below_floor`` = every week t of ``result`` with
  C_t < C_min (beyond FINANCING_TOL, so a plan that holds the floor exactly is not "below" it), and
  ``first_week_below_floor`` its first entry (null when cash never falls below the floor or there is no floor).
  The simulator does not enforce the floor (only the optimizer does, §4.1); these fields only report it.
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from config import Settings, get_settings
from core.financials import (
    FINANCING_TOL,
    ActionPlan,
    BusinessParams,
    CascadeDeltas,
    ScenarioShock,
    SimulationResult,
    cascade_deltas,
    simulate,
)
from models import ErrorCode, Identifier
from routes import (
    NOT_AVAILABLE,
    CodedRoute,
    FieldIssue,
    RouteError,
    error_responses,
    issues_from,
    read_json,
)

router = APIRouter(tags=["simulate"], route_class=CodedRoute)

BUSINESS_FILE = "demo_business.json"
# Plan / shock fields that may be a per-week list; a list must have exactly horizon_weeks entries.
_PLAN_SERIES = ("purchase_cut", "revolver_draw", "revolver_repay", "payroll_cut")


class SimulateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario_id: Identifier | None = Field(
        default=None,
        description=(
            "Optional id of the named scenario (GET /api/scenarios) the shock was taken from. Used only to "
            "name the result when `shock.name` is not given: `shock` is always the full input and is never "
            "replaced by a catalog lookup."
        ),
    )
    shock: ScenarioShock = Field(description="Scenario shocks; `{}` = no shock (baseline).")
    plan: ActionPlan | None = Field(default=None, description="Recovery actions; omitted = no action.")


class SimulateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provenance: Literal["SIMULATED"]
    business_provenance: Literal["SYNTHETIC", "ILLUSTRATIVE"] = Field(
        description="Provenance of the fictional demo business the simulation ran on."
    )
    baseline: SimulationResult = Field(description="No shock, no action.")
    result: SimulationResult = Field(description="Requested shock with the requested plan.")
    deltas: CascadeDeltas = Field(description="cascade_deltas(baseline, result), MATH_MODEL §5.")
    min_cash_floor: float | None = Field(
        description="The business's liquidity floor C_min (MATH_MODEL §4.1, §10); null when the fixture sets none."
    )
    first_week_below_floor: int | None = Field(
        description="First week t of `result` with C_t < C_min; null if cash never falls below it (or no floor)."
    )
    weeks_below_floor: list[int] = Field(
        description="Every week t of `result` with C_t < C_min, ascending; empty if none (or no floor)."
    )


def weeks_below(cash: list[float], floor: float | None) -> list[int]:
    """Weeks (1-based) whose closing cash is below the floor by more than FINANCING_TOL."""
    if floor is None:
        return []
    return [t for t, c in enumerate(cash, start=1) if c < floor - FINANCING_TOL]


def load_business(settings: Settings) -> BusinessParams:
    path = settings.data_dir / BUSINESS_FILE
    if not path.is_file():
        raise RouteError(
            ErrorCode.DATA_UNAVAILABLE,
            f"Demo business {NOT_AVAILABLE}: {BUSINESS_FILE} is missing from the data directory.",
            status_code=503,
        )
    payload = read_json(path, BUSINESS_FILE)
    raw = payload.get("business") if isinstance(payload, dict) else None
    if not isinstance(raw, dict):
        raise RouteError(
            ErrorCode.DATA_INVALID, f"{BUSINESS_FILE} must contain a `business` object.", status_code=500
        )
    try:
        return BusinessParams.model_validate(raw)
    except ValidationError as exc:
        raise RouteError(
            ErrorCode.DATA_INVALID,
            f"{BUSINESS_FILE} `business` failed the BusinessParams schema.",
            status_code=500,
            errors=issues_from(exc.errors(), prefix=(BUSINESS_FILE, "business")),
        ) from None


def series_length_issues(
    horizon: int, shock: ScenarioShock, plan: ActionPlan, prefix: tuple[str | int, ...] = ("body",)
) -> list[FieldIssue]:
    checks: list[tuple[list[str | int], object]] = [
        ([*prefix, "plan", name], getattr(plan, name)) for name in _PLAN_SERIES
    ]
    if shock.supplier is not None:
        checks.append(([*prefix, "shock", "supplier", "availability"], shock.supplier.availability))
    return [
        FieldIssue(
            loc=loc,
            msg=f"expected one number or a list of {horizon} weekly values (the business horizon), got {len(value)}",
            type="series_length",
        )
        for loc, value in checks
        if isinstance(value, list) and len(value) != horizon
    ]


BASELINE_NAME = "baseline"
CUSTOM_NAME = "custom"


def _result_name(body: SimulateRequest) -> str:
    explicit = "name" in body.shock.model_fields_set and body.shock.name not in ("", BASELINE_NAME)
    if explicit:
        return body.shock.name
    return body.scenario_id or CUSTOM_NAME


def _physical_issue(result: SimulationResult, plan: ActionPlan) -> str | None:
    """Purchases and inventory are physical stocks/flows and cannot be negative (engine fix owned by #32)."""
    for t, (p, inv) in enumerate(zip(result.purchases, result.inventory, strict=True), start=1):
        if p < -FINANCING_TOL:
            cut = plan.purchase_cut[t - 1] if isinstance(plan.purchase_cut, list) else plan.purchase_cut
            return (
                f"week {t}: purchase cut {cut:,.2f} is larger than that week's purchases before the cut "
                f"({p + cut:,.2f}); purchases cannot be negative."
            )
        if inv < -FINANCING_TOL:
            return (
                f"week {t}: cumulative purchase cuts would take inventory to {inv:,.2f}; inventory cannot be "
                "negative."
            )
    return None


_OVERFLOW_MESSAGE = (
    "Inputs out of numeric range: the simulation produced a non-finite value. Use realistic amounts and rates."
)


@router.post(
    "/simulate",
    response_model=SimulateResponse,
    responses=error_responses(422, 500, 503),
    summary="Simulate a scenario on the SYNTHETIC demo business",
)
def simulate_route(
    body: SimulateRequest,
    settings: Annotated[Settings, Depends(get_settings)],
) -> SimulateResponse:
    business = load_business(settings)
    plan = body.plan if body.plan is not None else ActionPlan()

    issues = series_length_issues(business.horizon_weeks, body.shock, plan)
    if issues:
        raise RouteError(ErrorCode.VALIDATION_ERROR, "Weekly series length does not match the horizon.",
                         errors=issues)

    try:
        baseline = simulate(business, ScenarioShock(), ActionPlan())
    except ValueError as exc:
        # The no-shock, no-action run failing means the fixture itself is inconsistent, not the request.
        raise RouteError(ErrorCode.DATA_INVALID, f"{BUSINESS_FILE} baseline cannot be simulated: {exc}",
                         status_code=500) from None
    shock = body.shock.model_copy(update={"name": _result_name(body)})
    try:
        result = simulate(business, shock, plan)
        deltas = cascade_deltas(baseline, result)
    except (ValidationError, OverflowError):
        # Must precede ValueError (ValidationError subclasses it): an overflow to inf/NaN fails the
        # finite-only result models. Its dump echoes values, so it is replaced by a short message.
        raise RouteError(ErrorCode.VALIDATION_ERROR, _OVERFLOW_MESSAGE) from None
    except ValueError as exc:
        # simulate() raises ValueError only for financing that cannot happen (MATH_MODEL §3), e.g. repaying
        # more revolver than is drawn. Its messages contain week numbers and amounts, never file contents.
        raise RouteError(ErrorCode.INFEASIBLE_INPUT, str(exc)) from None

    physical = _physical_issue(result, plan)
    if physical:
        raise RouteError(ErrorCode.INFEASIBLE_INPUT, physical)

    below = weeks_below(result.cash, business.min_cash)
    return SimulateResponse(
        provenance="SIMULATED",
        business_provenance=business.provenance,
        baseline=baseline,
        result=result,
        deltas=deltas,
        min_cash_floor=business.min_cash,
        first_week_below_floor=below[0] if below else None,
        weeks_below_floor=below,
    )
