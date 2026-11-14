"""GET /api/judge-challenges: the Judge's Challenge shocks for CASCADE (issue #123, SPEC §9 P1).

Serves ``<FAULTLINE_DATA_DIR>/judge_challenges.json``: named surprise shocks, each a ``core.financials.ScenarioShock``
sized inside the ranges of ``explore_shock_guidance.json`` (tests/test_judge_challenges.py checks every parameter
and the mapping). The shocks are ILLUSTRATIVE inputs; nothing here computes a result. The web app posts a chosen
shock unchanged to POST /api/simulate, which is where every number comes from (SIMULATED).

"Surprise me" is deterministic: the file lists ``surprise_order`` and the client steps through it in sequence,
showing the pick number. There is no hidden randomness anywhere in this route or its data.

Missing file → ``status: "NOT AVAILABLE"`` with an empty list; a file that fails the schema → 500 DATA_INVALID.
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from config import Settings, get_settings
from core.financials import ActionPlan, ScenarioShock
from models import ErrorCode, Identifier
from routes import NOT_AVAILABLE, CodedRoute, RouteError, error_responses, issues_from, read_json
from routes.simulate import load_business, series_length_issues

router = APIRouter(tags=["scenarios"], route_class=CodedRoute)

CHALLENGES_FILE = "judge_challenges.json"


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class GuidanceRef(_Frozen):
    category: Identifier = Field(description="Category id in explore_shock_guidance.json whose ranges size this shock.")
    values: dict[str, dict[str, float]] = Field(
        description=(
            "Guidance parameters per shock block (rate / demand / supplier), each inside the category's [min, max]."
        )
    )


class JudgeChallenge(_Frozen):
    id: Identifier
    name: str = Field(min_length=1)
    description: str = Field(min_length=1, description="One line: what happens to the fictional business.")
    provenance: Literal["ILLUSTRATIVE"]
    guidance: GuidanceRef
    range_citation: str = Field(min_length=1, description="Human-readable citation of each parameter's guidance range.")
    shock: ScenarioShock


class _ChallengesFile(BaseModel):
    model_config = ConfigDict(extra="ignore")

    provenance: Literal["ILLUSTRATIVE"]
    label: str
    surprise_order: list[Identifier]
    challenges: list[JudgeChallenge]


class JudgeChallengesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_serialization_defaults_required=True)

    status: Literal["AVAILABLE", "NOT AVAILABLE"]
    provenance: Literal["ILLUSTRATIVE"] = "ILLUSTRATIVE"
    label: str
    items: list[JudgeChallenge]
    surprise_order: list[Identifier] = Field(
        description="Fixed order 'Surprise me' steps through (pick k → entry (k-1) mod n)."
    )
    notes: list[str]


def _invalid(message: str, errors=None) -> RouteError:
    return RouteError(ErrorCode.DATA_INVALID, message, status_code=500, errors=errors)


def load_challenges(settings: Settings) -> _ChallengesFile | None:
    """None when the file does not exist; raises DATA_INVALID if it exists but fails the schema."""
    path = settings.data_dir / CHALLENGES_FILE
    if not path.is_file():
        return None
    try:
        doc = _ChallengesFile.model_validate(read_json(path, CHALLENGES_FILE))
    except ValidationError as exc:
        raise _invalid(
            f"{CHALLENGES_FILE} failed the Judge's Challenge schema.",
            issues_from(exc.errors(), prefix=(CHALLENGES_FILE,)),
        ) from None
    ids = [c.id for c in doc.challenges]
    if len(ids) != len(set(ids)):
        raise _invalid(f"{CHALLENGES_FILE} has duplicate challenge ids.")
    if sorted(doc.surprise_order) != sorted(ids):
        raise _invalid(f"{CHALLENGES_FILE} surprise_order must list every challenge id exactly once.")
    try:
        horizon: int | None = load_business(settings).horizon_weeks
    except RouteError as exc:
        if exc.code != ErrorCode.DATA_UNAVAILABLE:
            raise
        horizon = None
    if horizon is not None:
        issues = [
            x
            for i, c in enumerate(doc.challenges)
            for x in series_length_issues(horizon, c.shock, ActionPlan(), prefix=(CHALLENGES_FILE, "challenges", i))
        ]
        if issues:
            raise _invalid(f"{CHALLENGES_FILE} has weekly series that do not match the business horizon.", issues)
    # The shock carries the challenge name, so a simulated result is never labeled "baseline".
    challenges = [c.model_copy(update={"shock": c.shock.model_copy(update={"name": c.name})}) for c in doc.challenges]
    return doc.model_copy(update={"challenges": challenges})


@router.get(
    "/judge-challenges",
    response_model=JudgeChallengesResponse,
    responses=error_responses(500),
    summary="Judge's Challenge: named ILLUSTRATIVE surprise shocks for the SYNTHETIC demo business",
)
def list_judge_challenges(settings: Annotated[Settings, Depends(get_settings)]) -> JudgeChallengesResponse:
    doc = load_challenges(settings)
    if doc is None or not doc.challenges:
        why = "has not been added" if doc is None else "is empty"
        return JudgeChallengesResponse(
            status=NOT_AVAILABLE,
            label=f"Judge's Challenge {NOT_AVAILABLE}",
            items=[],
            surprise_order=[],
            notes=[f"Judge's Challenge {NOT_AVAILABLE}: {CHALLENGES_FILE} {why}."],
        )
    return JudgeChallengesResponse(
        status="AVAILABLE", label=doc.label, items=doc.challenges, surprise_order=doc.surprise_order, notes=[]
    )
