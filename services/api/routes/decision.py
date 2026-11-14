"""ACT / WAIT / HEDGE split view (issue #55; SPEC §2 Screen B; MATH_MODEL §8).

- ``GET /api/decision/frames`` lists the frames in ``<FAULTLINE_DATA_DIR>/decision_frames.json`` (#45): question,
  what YES / NO mean, the three policies with every fee, and the frame's ``forecast_sensitive``, ``caveat``,
  ``no_state_models`` and ``not_modelled_note`` fields verbatim. No numbers are computed here.
- ``POST /api/decision`` ``{frame_id, p_yes, protect_payroll?}`` runs ``core.decision.evaluate_policies`` on the
  SYNTHETIC demo business (the same loader as /api/simulate) and returns, per policy, V(a,1), V(a,0), E[V | a] at
  ``p_yes``, feasibility in each state with the breaches, the recommendation exactly as the engine gives it (a policy
  name or "NO SAFE POLICY"), and the break-even p* between the top two policies (MATH_MODEL §8).

Payoffs are SIMULATED lowest cash balances of a SYNTHETIC business; the frames are ILLUSTRATIVE. Never trading P&L.
Nothing here reads replay cases, outcomes or the sealed folder: this route is not part of the Blind Replay.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from config import Settings, get_settings
from core.decision import NO_SAFE_POLICY, TOL, Policy, PolicyEvaluation, evaluate_policies
from core.financials import ActionPlan, ScenarioShock
from models import ErrorCode, Identifier
from routes import NOT_AVAILABLE, CodedRoute, RouteError, error_responses, issues_from, read_json
from routes.simulate import load_business

router = APIRouter(tags=["decision"], route_class=CodedRoute)

FRAMES_FILE = "decision_frames.json"


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Fee(_Out):
    item: str
    amount: str
    when: str
    in_payoff: bool


class FramePolicy(_Out):
    name: str
    summary: str
    provenance: Literal["ILLUSTRATIVE"]
    fees: list[Fee]


class FrameSummary(_Out):
    id: str
    question_type: str
    provenance: Literal["ILLUSTRATIVE"]
    question_template: str
    yes_means: str
    no_means: str
    no_state_models: str | None
    not_modelled_note: str | None = Field(description="Verbatim from the frame; shown at reveal for an unmodelled NO.")
    forecast_sensitive: bool = Field(description="Verbatim: false means the recommendation does not depend on p.")
    caveat: str | None = Field(description="Verbatim; present when forecast_sensitive is false.")
    protect_payroll: bool = Field(description="The frame's default for evaluate_policies(protect_payroll=...).")
    policies: list[FramePolicy]


class FramesResponse(_Out):
    provenance: Literal["ILLUSTRATIVE"]
    business_provenance: Literal["SYNTHETIC", "ILLUSTRATIVE"]
    status: str = Field(description="Sign-off status of the frames file, verbatim.")
    payoff: str
    frames: list[FrameSummary]


class DecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    frame_id: Identifier
    p_yes: float = Field(ge=0.0, le=1.0, description="P(YES) to evaluate E[V | a] at (the forecast or the market).")
    protect_payroll: bool | None = Field(default=None, description="Omitted = the frame's own protect_payroll.")


class PolicyResult(_Out):
    name: str
    summary: str
    value_if_yes: float | None = Field(description="V(a, 1) = min_t C_t if YES; null = NOT AVAILABLE (rejected plan).")
    value_if_no: float | None = Field(description="V(a, 0) = min_t C_t if NO; null = NOT AVAILABLE.")
    value_week_if_yes: int | None
    value_week_if_no: int | None
    expected_value: float | None = Field(description="E[V | a] = p V(a,1) + (1-p) V(a,0); null if either V is null.")
    feasible_if_yes: bool
    feasible_if_no: bool
    feasible_in_both: bool
    breaches_if_yes: list[str]
    breaches_if_no: list[str]


class BreakEven(_Out):
    status: Literal["AVAILABLE", "NOT AVAILABLE"]
    policies: list[str] = Field(description="The top two policies by E[V] at p among those feasible in both states.")
    p_star: float | None = Field(description="P(YES) at which their E[V] are equal; null = NOT AVAILABLE.")
    note: str


class DecisionResponse(_Out):
    provenance: Literal["SIMULATED"]
    business_provenance: Literal["SYNTHETIC", "ILLUSTRATIVE"]
    frame_provenance: Literal["ILLUSTRATIVE"]
    frame_id: str
    question_type: str
    p_yes: float
    protect_payroll: bool
    payoff: str
    constraints_checked: list[str]
    policies: list[PolicyResult]
    recommendation: str = Field(
        description='A policy name, or "NO SAFE POLICY", exactly as evaluate_policies gives it.'
    )
    break_even: BreakEven
    forecast_sensitive: bool
    caveat: str | None
    not_modelled_note: str | None
    no_state_models: str | None


def _load_frames(settings: Settings) -> dict[str, Any]:
    path = settings.data_dir / FRAMES_FILE
    if not path.is_file():
        raise RouteError(
            ErrorCode.DATA_UNAVAILABLE,
            f"Decision frames {NOT_AVAILABLE}: {FRAMES_FILE} is missing from the data directory.",
            status_code=503,
        )
    doc = read_json(path, FRAMES_FILE)
    if not isinstance(doc, dict) or not isinstance(doc.get("frames"), list):
        raise RouteError(ErrorCode.DATA_INVALID, f"{FRAMES_FILE} must contain a `frames` list.", status_code=500)
    return doc


def _summary(frame: dict[str, Any]) -> FrameSummary:
    try:
        return FrameSummary(
            id=frame["id"], question_type=frame["question_type"], provenance=frame["provenance"],
            question_template=frame["question_template"], yes_means=frame["yes_means"], no_means=frame["no_means"],
            no_state_models=frame.get("no_state_models"), not_modelled_note=frame.get("not_modelled_note"),
            forecast_sensitive=frame["forecast_sensitive"], caveat=frame.get("caveat"),
            protect_payroll=frame["protect_payroll"],
            policies=[FramePolicy(name=p["name"], summary=p["summary"], provenance=p["provenance"], fees=p["fees"])
                      for p in frame["policies"]],
        )
    except (KeyError, TypeError, ValidationError):
        raise RouteError(
            ErrorCode.DATA_INVALID, f"{FRAMES_FILE} frame {frame.get('id', '?')!r} failed the frame schema.",
            status_code=500,
        ) from None


@router.get(
    "/decision/frames",
    response_model=FramesResponse,
    responses=error_responses(500, 503),
    summary="List the ACT / WAIT / HEDGE decision frames (ILLUSTRATIVE policies, SYNTHETIC business)",
)
def list_frames(settings: Annotated[Settings, Depends(get_settings)]) -> FramesResponse:
    doc = _load_frames(settings)
    label = doc.get("business_provenance")
    if label not in ("SYNTHETIC", "ILLUSTRATIVE"):  # a missing or unknown label is never filled in
        raise RouteError(
            ErrorCode.DATA_INVALID,
            f"{FRAMES_FILE} must state `business_provenance` (SYNTHETIC or ILLUSTRATIVE).",
            status_code=500,
        )
    return FramesResponse(
        provenance="ILLUSTRATIVE",
        business_provenance=label,
        status=str(doc.get("status", "")),
        payoff=str(doc.get("payoff", "")),
        frames=[_summary(f) for f in doc["frames"]],
    )


def _break_even(ranked: list[PolicyEvaluation]) -> BreakEven:
    """MATH_MODEL §8: p* where E[V | a] = E[V | b] for the top two policies a, b feasible in both states.

    p* = (V(b,0) - V(a,0)) / ((V(a,1) - V(a,0)) - (V(b,1) - V(b,0))). Not available when fewer than two policies are
    feasible in both states, when the two payoff lines are parallel (same V(·,1) - V(·,0), so the ranking never
    changes with p), or when they cross outside [0, 1].
    """
    if len(ranked) < 2:
        return BreakEven(status=NOT_AVAILABLE, policies=[e.policy.name for e in ranked], p_star=None,
                         note=f"{NOT_AVAILABLE}: fewer than two policies are feasible in both states.")
    a, b = ranked[0], ranked[1]
    names = [a.policy.name, b.policy.name]
    slope = (a.value_if_yes - a.value_if_no) - (b.value_if_yes - b.value_if_no)
    if abs(slope) <= TOL:
        return BreakEven(status=NOT_AVAILABLE, policies=names, p_star=None,
                         note=f"{NOT_AVAILABLE}: {names[0]} and {names[1]} differ by the same amount in both states, "
                              "so their ranking does not change with P(YES).")
    p_star = (b.value_if_no - a.value_if_no) / slope
    if not 0.0 <= p_star <= 1.0:
        return BreakEven(status=NOT_AVAILABLE, policies=names, p_star=None,
                         note=f"{NOT_AVAILABLE}: the E[V] lines of {names[0]} and {names[1]} cross at P(YES) = "
                              f"{p_star:.4f}, outside [0, 1], so their ranking does not change with P(YES).")
    return BreakEven(status="AVAILABLE", policies=names, p_star=p_star,
                     note=f"E[V | {names[0]}] = E[V | {names[1]}] at P(YES) = p*.")


@router.post(
    "/decision",
    response_model=DecisionResponse,
    responses=error_responses(422, 500, 503),
    summary="Evaluate ACT / WAIT / HEDGE for one frame at P(YES) (SIMULATED, SYNTHETIC business)",
)
def decision_route(
    body: DecisionRequest, settings: Annotated[Settings, Depends(get_settings)]
) -> DecisionResponse:
    doc = _load_frames(settings)
    frame = next((f for f in doc["frames"] if isinstance(f, dict) and f.get("id") == body.frame_id), None)
    if frame is None:
        known = sorted(f.get("id", "?") for f in doc["frames"] if isinstance(f, dict))
        raise RouteError(ErrorCode.VALIDATION_ERROR, f"Unknown frame_id {body.frame_id!r}. Known frames: {known}.")
    summary = _summary(frame)
    business = load_business(settings)
    try:
        shock_yes = ScenarioShock.model_validate(frame["shock_if_yes"])
        shock_no = ScenarioShock.model_validate(frame["shock_if_no"])
        policies = [Policy(name=p["name"], description=p["summary"], plan=ActionPlan.model_validate(p["plan"]))
                    for p in frame["policies"]]
    except (KeyError, TypeError, ValidationError) as exc:
        errors = issues_from(exc.errors(), prefix=(FRAMES_FILE, body.frame_id)) if isinstance(
            exc, ValidationError) else None
        raise RouteError(ErrorCode.DATA_INVALID, f"{FRAMES_FILE} frame {body.frame_id!r} has an invalid shock or plan.",
                         status_code=500, errors=errors) from None
    protect = summary.protect_payroll if body.protect_payroll is None else body.protect_payroll
    try:
        result = evaluate_policies(business, shock_yes, shock_no, policies, body.p_yes, protect_payroll=protect)
    except (ValidationError, OverflowError):
        raise RouteError(ErrorCode.VALIDATION_ERROR, "The evaluation produced a non-finite value.") from None
    except ValueError as exc:
        raise RouteError(ErrorCode.INFEASIBLE_INPUT, str(exc)) from None

    safe = [e for e in result.policies if e.feasible_in_both]
    # Stable sort: ties keep the frame's order, the same tie rule evaluate_policies uses for the recommendation.
    ranked = sorted(safe, key=lambda e: -e.expected_value)
    if result.recommended is not None and ranked and ranked[0].policy.name != result.recommendation:
        ranked = [result.recommended, *[e for e in ranked if e.policy.name != result.recommendation]]

    return DecisionResponse(
        provenance="SIMULATED",
        business_provenance=business.provenance,
        frame_provenance="ILLUSTRATIVE",
        frame_id=summary.id,
        question_type=summary.question_type,
        p_yes=result.p_yes,
        protect_payroll=protect,
        payoff=result.payoff,
        constraints_checked=result.constraints_checked,
        policies=[
            PolicyResult(
                name=e.policy.name, summary=e.policy.description,
                value_if_yes=e.value_if_yes, value_if_no=e.value_if_no,
                value_week_if_yes=e.if_yes.value_week, value_week_if_no=e.if_no.value_week,
                expected_value=e.expected_value,
                feasible_if_yes=e.if_yes.feasible, feasible_if_no=e.if_no.feasible, feasible_in_both=e.feasible_in_both,
                breaches_if_yes=e.if_yes.violations, breaches_if_no=e.if_no.violations,
            )
            for e in result.policies
        ],
        recommendation=result.recommendation if result.recommended is not None else NO_SAFE_POLICY,
        break_even=_break_even(ranked),
        forecast_sensitive=summary.forecast_sensitive,
        caveat=summary.caveat,
        not_modelled_note=summary.not_modelled_note,
        no_state_models=summary.no_state_models,
    )
