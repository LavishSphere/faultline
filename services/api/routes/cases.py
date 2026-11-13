"""GET /api/cases: Blind Replay demo cases as ``ReplayCasePublic`` (SPEC §5, §8). Pre-reveal.

Isolation is structural:
- Only ``<FAULTLINE_DATA_DIR>/demo_cases/*.json`` is read; ``sealed_outcomes/`` is never opened.
  A case file that resolves (e.g. via a symlink) outside ``demo_cases/`` is refused, unread.
- A file with an outcome-like key (``models.OUTCOME_FIELD_PATTERN``) ANYWHERE in it is rejected, unserved.
  Exceptions: ``case.resolution_rule`` (the rule text, as a string) and the market side marker
  ``"outcome": "YES"`` directly on a ``market_quotes[i]`` object (``markets.base.NormalizedQuote``).
- Top-level keys are allow-listed; ``case`` is validated as the internal ``models.ReplayCase``
  (``extra="forbid"``, no outcome field).
- The response model is ``ReplayCasePublic``, which has no outcome-like field at all.
- Error responses carry only file names, field locations and error types, never file contents.

Case file shape (docs/EVALUATION_PROTOCOL.md §7, PR #29):
``{"case": ReplayCase, "evidence": [...], "market_quotes": [...], "curation_notes": ...}``. Only
``case`` is required; ``evidence`` and ``market_quotes`` are not served here (the temporal gate owns
them). Any other top-level key is rejected. Dotfiles (e.g. macOS ``._x.json``) are skipped.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, ValidationError

from config import Settings, get_settings
from models import OUTCOME_FIELD_PATTERN, ErrorCode, ReplayCase, ReplayCasePublic
from routes import NOT_AVAILABLE, CodedRoute, RouteError, error_responses, issues_from, read_json

router = APIRouter(tags=["cases"], route_class=CodedRoute)

CASES_DIR = "demo_cases"
SEALED_DIR = "sealed_outcomes"  # never opened here; only used to refuse an overlapping cases directory
ALLOWED_TOP_LEVEL = frozenset({"case", "evidence", "market_quotes", "curation_notes"})
_MARKET_SIDE_KEY, _MARKET_SIDE_VALUE = "outcome", "YES"
# ReplayCase.resolution_rule is the settlement RULE text (served as question_criteria), never the result.
_RULE_PATH = "case.resolution_rule"


def _allowed(path: str, key: str, value: object, in_quote: bool) -> bool:
    if path == _RULE_PATH:
        return isinstance(value, str)
    return in_quote and key == _MARKET_SIDE_KEY and value == _MARKET_SIDE_VALUE


def outcome_key_paths(payload: object) -> list[str]:
    """JSON paths of every outcome-like key in a case file, except the two allow-listed keys:
    ``case.resolution_rule`` (rule text) and ``market_quotes[i].outcome == "YES"`` (quote side marker)."""
    found: list[str] = []

    def walk(node: object, path: str, in_quote: bool) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                key = str(k)
                here = f"{path}.{key}" if path else key
                if OUTCOME_FIELD_PATTERN.search(key) and not _allowed(here, key, v, in_quote):
                    found.append(here)
                walk(v, here, False)
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{path}[{i}]", in_quote=(path == "market_quotes"))

    walk(payload, "", False)
    return found


class CasesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_serialization_defaults_required=True)

    status: Literal["AVAILABLE", "NOT AVAILABLE"]
    items: list[ReplayCasePublic]
    notes: list[str]


def _invalid(message: str, errors=None) -> RouteError:
    return RouteError(ErrorCode.DATA_INVALID, message, status_code=500, errors=errors)


def _load_case(path: Path, root: Path) -> ReplayCasePublic:
    name = f"{CASES_DIR}/{path.name}"
    resolved = path.resolve()
    if not resolved.is_relative_to(root) or not resolved.is_file():
        raise _invalid(f"{name} is not a regular file inside {CASES_DIR}/; refusing to read it.")
    payload = read_json(resolved, name)
    if not isinstance(payload, dict) or not isinstance(payload.get("case"), dict):
        raise _invalid(f"{name} must be an object with a `case` (ReplayCase) object.")
    leaked = outcome_key_paths(payload)
    if leaked:
        # Paths (key names) only, never values: the values are exactly what must not leak.
        raise _invalid(f"{name} contains outcome-like keys and is refused: {', '.join(leaked)}.")
    unknown = sorted(set(payload) - ALLOWED_TOP_LEVEL)
    if unknown:
        raise _invalid(
            f"{name} has unexpected top-level keys {unknown}; allowed: {sorted(ALLOWED_TOP_LEVEL)}."
        )
    raw = payload["case"]
    try:
        return ReplayCasePublic.from_case(ReplayCase.model_validate(raw))
    except ValidationError as exc:
        raise _invalid(f"{name} failed the ReplayCase schema.", issues_from(exc.errors(), prefix=(name,))) from None


def load_public_cases(settings: Settings) -> list[ReplayCasePublic] | None:
    """None when the cases directory does not exist yet."""
    directory = settings.data_dir / CASES_DIR
    if not directory.is_dir():
        return None
    root = directory.resolve()
    sealed = (settings.data_dir / SEALED_DIR).resolve()
    if root.is_relative_to(sealed) or sealed.is_relative_to(root):
        raise _invalid(f"{CASES_DIR}/ overlaps {SEALED_DIR}/; refusing to read it.")
    files = sorted((p for p in directory.glob("*.json") if not p.name.startswith(".")), key=lambda p: p.name)
    cases = [_load_case(p, root) for p in files]
    ids = [c.event_id for c in cases]
    if len(ids) != len(set(ids)):
        raise _invalid(f"{CASES_DIR}/ has duplicate event_id values.")
    return cases


@router.get(
    "/cases",
    response_model=CasesResponse,
    responses=error_responses(500),
    summary="Blind Replay demo cases (public view, no outcomes)",
)
def list_cases(settings: Annotated[Settings, Depends(get_settings)]) -> CasesResponse:
    cases = load_public_cases(settings)
    if not cases:
        reason = "has not been added yet (issue #20)" if cases is None else "contains no case files yet"
        note = f"Replay cases {NOT_AVAILABLE}: {CASES_DIR}/ {reason}."
        return CasesResponse(status=NOT_AVAILABLE, items=[], notes=[note])
    return CasesResponse(status="AVAILABLE", items=cases, notes=[])
