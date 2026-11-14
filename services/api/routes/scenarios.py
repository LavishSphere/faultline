"""GET /api/scenarios: named stress scenarios from ``<FAULTLINE_DATA_DIR>/scenarios.json`` (issue #19).

If the file does not exist yet the response is an empty list with a NOT AVAILABLE note. Nothing
here invents a scenario.

Expected file shape (either form):
  ``[{scenario}, ...]``  or  ``{"scenarios": [{scenario}, ...], ...other metadata}``
where each scenario is
  ``{"id": str, "name": str, "rationale": str, "provenance": "SYNTHETIC" | "ILLUSTRATIVE",
     "shock": ScenarioShock}``
``shock`` uses the ``core.financials.ScenarioShock`` schema, so it can be posted unchanged to
POST /api/simulate; the route sets ``shock.name`` to the scenario's ``name``. Weekly series must match
the demo business horizon. Unknown extra keys on a scenario are ignored (not returned).
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

SCENARIOS_FILE = "scenarios.json"


class NamedScenario(BaseModel):
    # Input from the fixture: ignore unknown keys rather than failing, but only declared fields are returned.
    model_config = ConfigDict(extra="ignore", frozen=True)

    id: Identifier
    name: str = Field(min_length=1)
    rationale: str = Field(min_length=1, description="One-line economic rationale (no real companies or events).")
    provenance: Literal["SYNTHETIC", "ILLUSTRATIVE"] = Field(
        description="Scenarios for a fictional business are never REAL_HISTORICAL."
    )
    shock: ScenarioShock


class ScenariosResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_serialization_defaults_required=True)

    status: Literal["AVAILABLE", "NOT AVAILABLE"]
    items: list[NamedScenario]
    notes: list[str]


def _invalid(message: str, errors=None) -> RouteError:
    return RouteError(ErrorCode.DATA_INVALID, message, status_code=500, errors=errors)


def load_scenarios(settings: Settings) -> list[NamedScenario] | None:
    """None when the file does not exist; raises DATA_INVALID if it exists but fails the schema."""
    path = settings.data_dir / SCENARIOS_FILE
    if not path.is_file():
        return None
    payload = read_json(path, SCENARIOS_FILE)
    raw = payload.get("scenarios") if isinstance(payload, dict) else payload
    if not isinstance(raw, list):
        raise _invalid(f"{SCENARIOS_FILE} must be a list of scenarios or an object with a `scenarios` list.")
    out: list[NamedScenario] = []
    for i, entry in enumerate(raw):
        try:
            out.append(NamedScenario.model_validate(entry))
        except ValidationError as exc:
            raise _invalid(
                f"{SCENARIOS_FILE} scenario #{i} failed the scenario schema.",
                issues_from(exc.errors(), prefix=(SCENARIOS_FILE, i)),
            ) from None
    ids = [s.id for s in out]
    if len(ids) != len(set(ids)):
        raise _invalid(f"{SCENARIOS_FILE} has duplicate scenario ids.")
    horizon = _business_horizon(settings)
    if horizon is not None:
        issues = [x for i, s in enumerate(out)
                  for x in series_length_issues(horizon, s.shock, ActionPlan(), prefix=(SCENARIOS_FILE, i))]
        if issues:
            raise _invalid(f"{SCENARIOS_FILE} has weekly series that do not match the business horizon.", issues)
    # A listed shock carries its catalog name, so a simulated result is never labeled "baseline".
    return [s.model_copy(update={"shock": s.shock.model_copy(update={"name": s.name})}) for s in out]


def _business_horizon(settings: Settings) -> int | None:
    """Horizon of the demo business, or None if its file is missing (then /api/simulate reports that)."""
    try:
        return load_business(settings).horizon_weeks
    except RouteError as exc:
        if exc.code == ErrorCode.DATA_UNAVAILABLE:
            return None
        raise


@router.get(
    "/scenarios",
    response_model=ScenariosResponse,
    responses=error_responses(500),
    summary="Named stress scenarios for the SYNTHETIC demo business",
)
def list_scenarios(settings: Annotated[Settings, Depends(get_settings)]) -> ScenariosResponse:
    scenarios = load_scenarios(settings)
    if scenarios is None:
        return ScenariosResponse(
            status=NOT_AVAILABLE,
            items=[],
            notes=[f"Named scenarios {NOT_AVAILABLE}: {SCENARIOS_FILE} has not been added yet (issue #19)."],
        )
    if not scenarios:
        return ScenariosResponse(
            status=NOT_AVAILABLE, items=[], notes=[f"Named scenarios {NOT_AVAILABLE}: {SCENARIOS_FILE} is empty."]
        )
    return ScenariosResponse(status="AVAILABLE", items=scenarios, notes=[])
