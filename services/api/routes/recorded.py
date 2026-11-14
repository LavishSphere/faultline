"""GET /api/replay/recorded: committed RECORDED RUN forecasts for one case (issue #116; pre-reveal safe).

On a public deployment visitors cannot run the model (``POST /api/replay/run`` is admin-only), so DECISION shows
the forecast the official run script (``scripts/record_runs.py``) committed under
``<FAULTLINE_DATA_DIR>/recorded_runs/runs/<run_id>/``. Read-only, so it is open in public mode.

* Only runs whose ``manifest.json`` says ``dry_run: false`` (and is not a mocked provider) with provenance
  ``RECORDED_RUN`` are read. A dry run's SIMULATED rows are never served.
* Every row of a run is verified by ``routes.benchmark.load_run``, the same ``verify_row`` and manifest checks
  ``GET /api/benchmark`` relies on: every hash recomputes, the raw model output parses to the recorded answer,
  the row matches its manifest entry. A row that fails is skipped with a note; a run whose row index
  (``rows_sha256``) does not recompute is skipped whole.
* The response is built from ``RecordedForecast`` / ``RecordedResponse``, which have no outcome field at all. A row is
  written before anything is revealed and ``verify_row`` refuses one with an outcome-like key, but the scoring
  context is still not copied wholesale: only the named fields below are served.

It never opens the sealed folder, the prediction store (SQLite) or the demo case files. Nothing committed for
the case (or an unknown case) is ``NOT AVAILABLE`` with a note, never a placeholder.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from models import Decision, Identifier, Sha256Hex
from routes import NOT_AVAILABLE, CodedRoute, RouteErrorBody
from routes.benchmark import _RUN_ID, DRY_RUN_AGENT_MODEL, VARIANT_ORDER, load_run, recorded_runs_dir

_IDENTIFIER = r"^[A-Za-z0-9_.:\-]+$"
RecordedVariant = Literal["agent_only", "agent_plus_market"]


class CitedEvidence(BaseModel):
    """One evidence item the model cited, copied from the exact snapshot it was given (the gate's output)."""

    model_config = ConfigDict(extra="forbid")

    evidence_id: Identifier
    title: str | None
    available_at: str | None
    source_url: str | None
    provenance: str | None


class RecordedForecast(BaseModel):
    """One committed RECORDED RUN forecast, verbatim from its verified row. No outcome field exists here."""

    model_config = ConfigDict(extra="forbid")

    provenance: Literal["RECORDED_RUN"] = "RECORDED_RUN"
    run_id: str
    prediction_id: Identifier
    case_id: Identifier
    agent_variant: RecordedVariant
    as_of: AwareDatetime
    p_yes: float = Field(ge=0.0, le=1.0)
    decision: Decision
    rationale: str
    evidence_ids: list[Identifier]
    cited_evidence: list[CitedEvidence] = Field(description="evidence_ids resolved against the row's snapshot.")
    agent_model: str
    model_tag: str | None
    model_digest: str | None
    temperature: float
    seed: int | None
    attempts: int | None
    prompt_sha256: Sha256Hex
    gated_prompt_sha256: Sha256Hex | None
    snapshot_sha256: Sha256Hex
    record_sha256: Sha256Hex
    row_sha256: Sha256Hex
    recorded_at: AwareDatetime
    persisted_at: AwareDatetime
    case_synthetic: bool = Field(description="True when the case is a SYNTHETIC fixture (from the frozen context).")
    contamination_flag: str | None = Field(description="The case's curated contamination flag at record time.")
    model_card_contamination_flag: str | None


class RecordedResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_serialization_defaults_required=True)

    status: Literal["AVAILABLE", "NOT AVAILABLE"]
    provenance: Literal["RECORDED_RUN"] = "RECORDED_RUN"
    case_id: Identifier
    items: list[RecordedForecast] = Field(
        description="Newest run first; within a run agent_only before agent_plus_market."
    )
    notes: list[str]


def _cited(snapshot_json: str, evidence_ids: list[str]) -> list[CitedEvidence]:
    offered = {e.get("evidence_id"): e for e in json.loads(snapshot_json).get("evidence", []) if isinstance(e, dict)}
    out = []
    for eid in evidence_ids:
        e = offered.get(eid, {})
        out.append(
            CitedEvidence(
                evidence_id=eid,
                title=e.get("title"),
                available_at=e.get("available_at"),
                source_url=e.get("source_url"),
                provenance=e.get("provenance"),
            )
        )
    return out


def _forecast(row: dict) -> RecordedForecast:
    pred, call, ctx = row["prediction"], row["model_call"], row["context"]
    contamination = row.get("contamination") or {}
    return RecordedForecast(
        run_id=row["run_id"],
        prediction_id=pred["prediction_id"],
        case_id=pred["event_id"],
        agent_variant=pred["variant"],
        as_of=pred["as_of"],
        p_yes=pred["p_yes"],
        decision=pred["decision"],
        rationale=pred["rationale"],
        evidence_ids=pred["evidence_ids"],
        cited_evidence=_cited(row["snapshot_json"], pred["evidence_ids"]),
        agent_model=pred["agent_model"],
        model_tag=call.get("model_tag"),
        model_digest=pred.get("model_digest"),
        temperature=pred["temperature"],
        seed=pred.get("seed"),
        attempts=pred.get("attempts"),
        prompt_sha256=pred["prompt_sha256"],
        gated_prompt_sha256=pred.get("gated_prompt_sha256"),
        snapshot_sha256=pred["snapshot_sha256"],
        record_sha256=row["record_sha256"],
        row_sha256=row["row_sha256"],
        recorded_at=pred["recorded_at"],
        persisted_at=row["persisted_at"].replace("Z", "+00:00"),
        case_synthetic=bool(ctx["synthetic"]),
        contamination_flag=contamination.get("case_flag"),
        model_card_contamination_flag=contamination.get("model_card_flag"),
    )


def _run_dirs(runs_root: Path) -> list[Path]:
    if not runs_root.is_dir():
        return []
    return sorted(p for p in runs_root.iterdir() if p.is_dir() and (p / "manifest.json").is_file())


def recorded_forecasts(case_id: str, variant: str | None) -> RecordedResponse:
    runs_root = recorded_runs_dir() / "runs"
    notes: list[str] = []
    found: list[RecordedForecast] = []
    run_dirs = _run_dirs(runs_root)
    if not run_dirs:
        return RecordedResponse(
            status=NOT_AVAILABLE,
            case_id=case_id,
            items=[],
            notes=["No committed recorded run (recorded_runs/runs/ is empty): run the app locally for live replay."],
        )
    for run_dir in run_dirs:
        name = run_dir.name
        if not _RUN_ID.fullmatch(name):
            notes.append(f"run folder {name!r} skipped: not a valid run_id.")
            continue
        manifest, rows, problems = load_run(run_dir)
        if manifest is None:
            notes.append(f"run {name} skipped: {'; '.join(problems)}.")
            continue
        if manifest.get("dry_run") is not False or manifest.get("mocked_provider") is True:
            notes.append(f"run {name} skipped: a dry run (mocked provider) is never shown as a RECORDED RUN.")
            continue
        if manifest.get("provenance") != "RECORDED_RUN" or manifest.get("run_id") != name:
            notes.append(f"run {name} skipped: manifest provenance/run_id mismatch.")
            continue
        run_level = [p for p in problems if not p.startswith("rows/")]
        if run_level:
            notes.append(f"run {name} skipped: {'; '.join(run_level)}.")
            continue
        for meta in manifest.get("rows", []):
            if meta.get("event_id") != case_id or meta.get("variant") not in VARIANT_ORDER:
                continue
            if variant is not None and meta.get("variant") != variant:
                continue
            file = str(meta.get("file", ""))
            bad = [p for p in problems if p.startswith(f"{file}:")]
            row = rows.get(str(meta.get("prediction_id")))
            if row is None and not bad:
                bad = [f"{file}: missing"]
            if not bad:
                pred = row.get("prediction", {})
                if pred.get("provenance") != "RECORDED_RUN" or pred.get("agent_model") == DRY_RUN_AGENT_MODEL:
                    bad = [f"{file}: not a RECORDED_RUN forecast"]
            if bad:
                notes.append(f"run {name}: {file} skipped, failed verification ({'; '.join(bad)}).")
                continue
            try:
                found.append(_forecast(row))
            except (KeyError, TypeError, ValueError) as exc:
                notes.append(f"run {name}: {file} skipped, failed verification (malformed, {type(exc).__name__}).")
    order = {v: i for i, v in enumerate(VARIANT_ORDER)}
    # Newest run first (by its newest row); within a run agent_only before agent_plus_market.
    by_run: dict[str, float] = {}
    for f in found:
        by_run[f.run_id] = max(by_run.get(f.run_id, f.recorded_at.timestamp()), f.recorded_at.timestamp())
    found.sort(key=lambda f: (-by_run[f.run_id], f.run_id, order[f.agent_variant]))
    if not found:
        which = f" ({variant})" if variant else ""
        notes.append(f"No committed RECORDED RUN forecast for case {case_id}{which}.")
    return RecordedResponse(
        status="AVAILABLE" if found else NOT_AVAILABLE,
        case_id=case_id,
        items=found,
        notes=notes,
    )


router = APIRouter(tags=["replay"], route_class=CodedRoute)

_RESPONSES: dict[int | str, dict[str, Any]] = {
    422: {"model": RouteErrorBody, "description": "VALIDATION_ERROR: bad case_id or agent_variant"},
}


@router.get(
    "/replay/recorded",
    response_model=RecordedResponse,
    responses=_RESPONSES,
    summary="Committed RECORDED RUN forecasts for a case (read-only; pre-reveal safe; public)",
)
def get_recorded(
    case_id: Annotated[str, Query(min_length=1, max_length=200, pattern=_IDENTIFIER)],
    agent_variant: RecordedVariant | None = None,
) -> RecordedResponse:
    return recorded_forecasts(case_id, agent_variant)
