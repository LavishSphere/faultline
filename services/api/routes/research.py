"""GET /api/vc-lenses: dated, sourced four-firm research context (SPEC §7, §8).

Two modes, distinguished by ``mode`` (a discriminator in the OpenAPI schema):

- ``point_in_time`` (``?as_of=<timezone-aware ISO-8601 instant>``): only lenses provably public at
  ``as_of`` (``core.research.eligible_lenses``), each reduced to ``core.research.lens_for_prompt``,
  i.e. content fields only, with none of the curation metadata that is dated after most cutoffs.
  Use this for Blind Replay / Thesis Court at a cutoff.
- ``live_explore`` (no ``as_of``): every curated item with its full sourcing (archive, access date,
  limitations). Not filtered to any cutoff; never feed it to a replay.

Both are labeled RESEARCH CONTEXT: public writing by the firms, not forecasts and not scored.
``as_of`` must be an instant with an offset (``...Z`` or ``...+00:00``; URL-encode ``+`` as ``%2B``).
Calendar dates, naive datetimes and unix timestamps are rejected with 422.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from config import Settings, get_settings
from core.research import eligible_lenses, lens_for_prompt, load_lenses
from routes import (
    NOT_AVAILABLE,
    CodedRoute,
    FieldIssue,
    RouteError,
    RouteErrorCode,
    error_responses,
    issues_from,
    read_json,
)

router = APIRouter(tags=["research"], route_class=CodedRoute)

LENSES_FILE = "research_lenses.json"
QuoteKind = Literal["documentary_fact", "analyst_interpretation", "quantitative_forecast"]
_DATE_ONLY = re.compile(r"^\d{4}-?\d{2}-?\d{2}$")
_DIGITS = re.compile(r"^[+-]?\d+(\.\d+)?$")


class LensQuote(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    kind: QuoteKind


class LensPointInTime(BaseModel):
    """Exactly the keys of core.research.lens_for_prompt. No curation metadata."""

    model_config = ConfigDict(extra="forbid")

    id: str
    firm: str
    title: str
    url: str
    published_at: str | None = Field(
        default=None, description="Displayed publication date (YYYY-MM-DD); null when the page shows none."
    )
    thesis: str
    hypotheses: list[str]
    quotes: list[LensQuote]


class LensQuoteNoted(LensQuote):
    note: str | None = None


class LensLiveExplore(BaseModel):
    """Full curated item for Live Explore. Unknown fixture keys (e.g. page_metadata) are not returned."""

    model_config = ConfigDict(extra="ignore")

    id: str
    firm: str
    title: str
    url: str
    source_type: str | None = None
    authors: list[str] = Field(default_factory=list)
    published_at: str | None
    published_at_basis: str | None = None
    available_at: str = Field(description="Conservative date the quoted text is proven public (YYYY-MM-DD).")
    available_at_basis: str
    archived_url: str | None
    archived_at: str | None = None
    accessed_at: str
    themes: list[str] = Field(default_factory=list)
    thesis: str
    thesis_review: str | None = None
    hypotheses: list[str]
    quotes: list[LensQuoteNoted]
    limitations: list[str]


class VcLensesPointInTime(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_serialization_defaults_required=True)

    mode: Literal["point_in_time"] = "point_in_time"
    status: Literal["AVAILABLE", "NOT AVAILABLE"]
    label: Literal["RESEARCH CONTEXT"] = "RESEARCH CONTEXT"
    mode_label: str
    provenance: Literal["REAL_HISTORICAL"] = "REAL_HISTORICAL"
    as_of: datetime = Field(description="The replay cutoff, normalized to UTC.")
    items: list[LensPointInTime]
    excluded_not_yet_public: int = Field(
        ge=0, description="Curated lenses hidden because they were not provably public at as_of."
    )
    notes: list[str]


class VcLensesLiveExplore(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_serialization_defaults_required=True)

    mode: Literal["live_explore"] = "live_explore"
    status: Literal["AVAILABLE", "NOT AVAILABLE"]
    label: Literal["RESEARCH CONTEXT"] = "RESEARCH CONTEXT"
    mode_label: str
    provenance: Literal["REAL_HISTORICAL"] = "REAL_HISTORICAL"
    as_of: None = None
    items: list[LensLiveExplore]
    notes: list[str]


VcLensesResponse = Annotated[VcLensesPointInTime | VcLensesLiveExplore, Field(discriminator="mode")]

POINT_IN_TIME_LABEL = "POINT-IN-TIME: only lenses provably public at as_of, content fields only"
LIVE_EXPLORE_LABEL = "LIVE EXPLORE: all curated lenses, not filtered to any replay cutoff; not for Blind Replay"
NOT_SCORED_NOTE = "Public writing by the firms, shown as research context. Not forecasts; never scored."


def parse_as_of(raw: str) -> datetime:
    """Timezone-aware ISO-8601 instant -> UTC datetime. Anything else -> 422 VALIDATION_ERROR."""
    text = raw.strip()
    problem = None
    if not text:
        problem = "as_of is empty"
    elif _DATE_ONLY.match(text):
        problem = "as_of must be an instant with a timezone, not a calendar date"
    elif _DIGITS.match(text):
        problem = "as_of must be an ISO-8601 instant, not a number"
    else:
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            parsed = None
            problem = "as_of is not an ISO-8601 instant (URL-encode '+' in offsets as %2B, or use 'Z')"
        if parsed is not None:
            if parsed.tzinfo is None or parsed.utcoffset() is None:
                problem = "as_of must include a timezone offset (e.g. 'Z' or '+00:00')"
            else:
                try:
                    return parsed.astimezone(UTC)
                except (OverflowError, ValueError):
                    problem = "as_of is outside the representable UTC range"
    raise RouteError(
        RouteErrorCode.VALIDATION_ERROR,
        "as_of must be a timezone-aware ISO-8601 instant, e.g. 2026-07-01T00:00:00Z.",
        errors=[FieldIssue(loc=["query", "as_of"], msg=problem, type="as_of_instant")],
    )


def _load(settings: Settings) -> list[dict] | None:
    """None when the file is missing; raises DATA_INVALID if it fails core.research validation."""
    path = settings.data_dir / LENSES_FILE
    if not path.is_file():
        return None
    read_json(path, LENSES_FILE)  # JSON syntax errors -> DATA_INVALID with line/column
    try:
        return load_lenses(path)
    except (ValueError, TypeError, AttributeError):
        # load_lenses lists every schema problem; summarize rather than echo fixture contents.
        raise RouteError(
            RouteErrorCode.DATA_INVALID,
            f"{LENSES_FILE} failed research-lens validation (run tests/test_research_lenses.py for details).",
            status_code=500,
        ) from None


def _live_items(items: list[dict]) -> list[LensLiveExplore]:
    out = []
    for i, item in enumerate(items):
        try:
            out.append(LensLiveExplore.model_validate(item))
        except ValidationError as exc:
            raise RouteError(
                RouteErrorCode.DATA_INVALID,
                f"{LENSES_FILE} item #{i} does not match the Live Explore lens schema.",
                status_code=500,
                errors=issues_from(exc.errors(), prefix=(LENSES_FILE, "items", i)),
            ) from None
    return out


@router.get(
    "/vc-lenses",
    response_model=VcLensesResponse,
    responses=error_responses(422, 500),
    summary="Four-firm VC research lenses, point-in-time (as_of) or Live Explore",
)
def vc_lenses(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    as_of: Annotated[
        str | None,
        Query(
            description=(
                "Replay cutoff as a timezone-aware ISO-8601 instant (e.g. 2026-07-01T00:00:00Z). "
                "Omit for Live Explore (all items, unfiltered)."
            ),
        ),
    ] = None,
) -> VcLensesPointInTime | VcLensesLiveExplore:
    if len(request.query_params.getlist("as_of")) > 1:
        raise RouteError(
            RouteErrorCode.VALIDATION_ERROR,
            "as_of must be given at most once.",
            errors=[FieldIssue(loc=["query", "as_of"], msg="as_of was repeated", type="as_of_repeated")],
        )
    instant = parse_as_of(as_of) if as_of is not None else None
    items = _load(settings)

    missing_note = f"Research lenses {NOT_AVAILABLE}: {LENSES_FILE} is missing from the data directory."
    if instant is None:
        if items is None:
            return VcLensesLiveExplore(status=NOT_AVAILABLE, mode_label=LIVE_EXPLORE_LABEL, items=[],
                                       notes=[missing_note])
        return VcLensesLiveExplore(status="AVAILABLE", mode_label=LIVE_EXPLORE_LABEL, items=_live_items(items),
                                   notes=[NOT_SCORED_NOTE])

    if items is None:
        return VcLensesPointInTime(status=NOT_AVAILABLE, mode_label=POINT_IN_TIME_LABEL, as_of=instant, items=[],
                                   excluded_not_yet_public=0, notes=[missing_note])
    eligible = eligible_lenses(instant, items)
    projected = [LensPointInTime.model_validate(lens_for_prompt(item, instant)) for item in eligible]
    excluded = len(items) - len(eligible)
    notes = [NOT_SCORED_NOTE]
    if excluded:
        notes.append(f"{excluded} curated lens(es) excluded: not provably public at as_of.")
    if not projected:
        notes.append(f"No research lens was provably public at as_of: {NOT_AVAILABLE}.")
    return VcLensesPointInTime(
        status="AVAILABLE" if projected else NOT_AVAILABLE,
        mode_label=POINT_IN_TIME_LABEL,
        as_of=instant,
        items=projected,
        excluded_not_yet_public=excluded,
        notes=notes,
    )
