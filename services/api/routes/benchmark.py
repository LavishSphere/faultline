"""Benchmark scorecards (SPEC §6; MATH_MODEL §6; docs/EVALUATION_PROTOCOL.md §6, §8, §10).

Two routes, split by whether they can reveal an outcome (lead contract decisions on issue #44):

* ``POST /api/benchmark/compute {agent_variant}`` runs ``core.evaluator.build_scorecard`` on the configured
  prediction store, the configured sealed folder and ``EvidenceStore.from_dir()`` (the only setup that can earn
  the OFFICIAL label). Scoring REVEALS outcomes (each reveal is logged in ``audit_log``), so in public mode the
  route needs the admin token. The check is ``routes.replay.require_admin_in_public_mode``, the same as for run
  and reveal, applied by ``AdminGatedRoute`` before the body is read. Real and synthetic cases are scored as
  separate case sets (issue #102; real first; a synthetic card is never OFFICIAL). Each resulting ``Scorecard`` is
  persisted, unchanged, as a ``RECORDED_RUN`` snapshot with its SHA-256 under ``services/api/var/scorecards/`` and
  returned.
* ``GET /api/benchmark`` is read-only. It serves recorded snapshots: the newest COMMITTED one per variant
  (``<FAULTLINE_DATA_DIR>/recorded_runs/scorecards/``, written by ``scripts/record_runs.py``), then the newest
  COMPUTED one per variant (``services/api/var/scorecards/``), for the real case set and then the synthetic one.
  It never builds a vault, never opens the SQLite store and never touches the sealed folder, so a public visitor
  cannot reveal early and disqualify a later official run.

A snapshot is served only if it passes ``verify_snapshot``. Its hashes must recompute. Its label, verdict, caveat,
summary and CI must be exactly what the evaluator's display rules give for its own per-event rows. No dry-run
model may appear in it. A COMMITTED snapshot must also be listed, with its hash, in the manifest of a scored,
non-dry run whose rows all verify, and its per-event agent and market scores must recompute from those rows.
Hashes are not signatures: someone who rewrites rows, manifest and snapshot consistently is caught only by
review of the commit. These checks stop a hand-edited or inconsistent card from being shown.

Snapshot file (``<variant>--<UTC timestamp>--<sha12>.json``): ``RecordedScorecard`` below.
``scorecard_sha256`` = SHA-256 of the canonical JSON of ``scorecard``; ``snapshot_sha256`` = SHA-256 of the
canonical JSON of the whole file without ``snapshot_sha256`` (core/provenance.py canonical JSON).
"""

from __future__ import annotations

import json
import os
import re
import threading
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import numpy as np
from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError

from agents.provider import ForecastOutput
from config import get_settings
from core import provenance
from core import store as store_module
from core.evaluator import (
    AGENT_BETTER,
    BOOTSTRAP_SEED,
    CASE_SETS,
    CONFIDENCE,
    DEFAULT_RESAMPLES,
    INSUFFICIENT_DATA,
    LABEL_ILLUSTRATIVE,
    LABEL_INSUFFICIENT,
    LABEL_NOT_OFFICIAL,
    MIN_EVENTS,
    NO_IMPROVEMENT,
    SMALL_SAMPLE_EVENTS,
    CaseSet,
    OutcomeVault,
    Scorecard,
    brier,
    build_scorecard,
    case_sets_present,
    correct_at_half,
    event_case_sets,
    log_loss,
    market_label_for,
    paired_bootstrap,
)
from core.store import PredictionStore, ScoringContext, model_prompt_problems, record_sha256
from core.temporal_gate import EvidenceStore, SealedDataError
from errors import FaultlineError
from markets.base import MARKET_LABEL, SYNTHETIC_VENUE
from models import OUTCOME_FIELD_PATTERN, ApiError, ErrorCode, Prediction, Provenance, Sha256Hex
from routes import NOT_AVAILABLE, CodedRoute, RouteError, error_responses
from routes.replay import require_admin_in_public_mode

SNAPSHOT_SCHEMA_VERSION = 1
RECORDED_RUNS_SUBDIR = Path("recorded_runs")
VARIANT_ORDER = ("agent_only", "agent_plus_market")
ScoredVariant = Literal["agent_only", "agent_plus_market"]
Origin = Literal["committed", "computed"]
# agent_model of the dry run's mocked provider (scripts/record_runs.py --dry-run). Never in a served scorecard.
DRY_RUN_AGENT_MODEL = "ollama/dry-run-mock"
_RUN_ID = re.compile(r"^[0-9A-Za-z_\-]{1,64}$")


# ---------------------------------------------------------------- contracts


class BenchmarkComputeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_variant: ScoredVariant = Field(
        description="Agent variant to score against the naive and market-only baselines (scored separately)."
    )


class ScorecardRecord(BaseModel):
    """Where one served scorecard came from and its hashes (same order as ``items``)."""

    model_config = ConfigDict(extra="forbid")

    agent_variant: ScoredVariant
    case_set: CaseSet = Field(
        description="real: REAL HISTORICAL cases (can be OFFICIAL); synthetic: SYNTHETIC cases, scored separately "
        "and never OFFICIAL. Real items come first."
    )
    recorded_at: AwareDatetime = Field(description="When the scorecard was computed (UTC).")
    source: Literal["compute_route", "record_runs_script"]
    origin: Origin = Field(
        description="committed: data/recorded_runs/ in git (official run script); computed: var/scorecards/ on "
        "this server (admin compute). Committed items come first."
    )
    run_id: str | None
    file: str = Field(description="Snapshot file name (no directory).")
    scorecard_sha256: Sha256Hex
    snapshot_sha256: Sha256Hex
    agent_models: list[str] = Field(description="agent_model of every scored forecast (e.g. ollama/llama3.1:8b).")


class BenchmarkResponse(BaseModel):
    """Same envelope as the other list routes: ``{status, items, notes}``, plus provenance and per-item records."""

    model_config = ConfigDict(extra="forbid", json_schema_serialization_defaults_required=True)

    status: Literal["AVAILABLE", "NOT AVAILABLE"]
    provenance: Literal["RECORDED_RUN"] = "RECORDED_RUN"
    items: list[Scorecard] = Field(
        description="Real case set first, then synthetic. Within a set: newest committed scorecard per variant, "
        "then newest computed one per variant (agent_only before agent_plus_market). Prefer the first item for a "
        "variant; a synthetic item is never OFFICIAL."
    )
    records: list[ScorecardRecord] = Field(description="Provenance of items[i], same order.")
    notes: list[str]


class RecordedScorecard(BaseModel):
    """File format of one recorded scorecard snapshot (RECORDED RUN)."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    provenance: Literal["RECORDED_RUN"]
    source: Literal["compute_route", "record_runs_script"]
    run_id: str | None
    recorded_at: AwareDatetime
    agent_variant: ScoredVariant
    agent_models: list[str]
    cases_sha256: dict[str, Sha256Hex]
    scorecard: Scorecard
    scorecard_sha256: Sha256Hex
    snapshot_sha256: Sha256Hex


# ---------------------------------------------------------------- admin gate (shared with routes/replay.py)


class AdminGatedRoute(CodedRoute):
    """CodedRoute that runs ``require_admin_in_public_mode`` before anything else, including body parsing."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()

        async def gated_handler(request: Request) -> Response:
            try:
                require_admin_in_public_mode(request)
            except FaultlineError as exc:
                body = ApiError(code=exc.code, message=exc.message)
                return JSONResponse(status_code=exc.status_code, content=body.model_dump(mode="json"))
            return await handler(request)

        return gated_handler


# ---------------------------------------------------------------- paths and hashes


def computed_dir() -> Path:
    """services/api/var/scorecards/ (next to the configured prediction store; git-ignored)."""
    return store_module.DEFAULT_DB_PATH.parent / "scorecards"


def recorded_runs_dir() -> Path:
    return get_settings().data_dir / RECORDED_RUNS_SUBDIR


def committed_dir() -> Path:
    return recorded_runs_dir() / "scorecards"


def canon_sha(obj: Any) -> str:
    return provenance.sha256_hex(provenance.canonical_json(obj))


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- recorded run rows (scripts/record_runs.py)


def verify_row(row: Any) -> list[str]:
    """Recompute every hash in one RECORDED RUN row and check its model call against its forecast. Empty = intact.

    * ``prompt`` (the gate's prompt) hashes to ``gated_prompt_sha256``; ``prompt + final_prompt_suffix`` (what
      the model answered) hashes to ``prompt_sha256`` and, as one user message, to ``transcript_sha256``;
      ``attempts`` is 1 (empty suffix) or 2 (suffix is exactly the provider's repair instruction): all via
      ``core.store.model_prompt_problems``, the store's own rule;
    * ``raw_output`` parses as a ``ForecastOutput`` (against the snapshot's evidence ids) whose p_yes, decision,
      rationale and evidence_ids are the prediction's;
    * snapshot, record, raw-output and row hashes recompute; no outcome-like key anywhere.
    """
    if not isinstance(row, dict):
        return ["row is not a JSON object"]
    problems: list[str] = []
    try:
        if canon_sha({k: v for k, v in row.items() if k != "row_sha256"}) != row.get("row_sha256"):
            problems.append("row_sha256 does not match the row")
        pred = Prediction.model_validate(row["prediction"])
        call = row["model_call"]
        final_prompt = row["prompt"] + call["final_prompt_suffix"]
        problems += model_prompt_problems(pred, row["prompt"], final_prompt)
        if pred.gated_prompt_sha256 is None:
            problems.append("gated_prompt_sha256 missing: a recorded run always comes from a model call")
        if call["final_prompt_sha256"] != pred.prompt_sha256:
            problems.append("final_prompt_sha256 differs from the prediction's prompt_sha256")
        if (call["attempts"], call["transcript_sha256"]) != (pred.attempts, pred.transcript_sha256):
            problems.append("model_call attempts/transcript_sha256 differ from the prediction")
        snapshot = row["snapshot_json"]
        if provenance.sha256_hex(snapshot) != pred.snapshot_sha256:
            problems.append("snapshot_sha256 does not match the stored snapshot JSON")
        ctx = ScoringContext(**row["context"])
        persisted_at = datetime.fromisoformat(row["persisted_at"].replace("Z", "+00:00"))
        if record_sha256(pred, ctx, persisted_at, int(row["persist_seq"])) != row["record_sha256"]:
            problems.append("record_sha256 does not match the forecast, context and persist mark")
        raw = call["raw_output"]
        if provenance.sha256_hex(raw) != call["raw_output_sha256"]:
            problems.append("raw_output_sha256 does not match raw_output")
        offered = [e.get("evidence_id") for e in json.loads(snapshot).get("evidence", [])]
        try:
            out = ForecastOutput.parse_model_json(raw, offered)
        except ValidationError:
            problems.append("raw_output is not a valid forecast for this snapshot")
        else:
            answer = (out.p_yes, out.decision, out.rationale, list(out.evidence_ids))
            if answer != (pred.p_yes, pred.decision, pred.rationale, list(pred.evidence_ids)):
                problems.append("raw_output differs from the recorded prediction (p_yes/decision/rationale/evidence)")
        if pred.provenance.value != row["provenance"]:
            problems.append("prediction provenance differs from the row provenance")
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        problems.append(f"row is malformed ({type(exc).__name__})")
    leaked = sorted({k for k in _keys(row) if OUTCOME_FIELD_PATTERN.search(k)})
    if leaked:
        problems.append(f"outcome-like keys in a recorded row: {leaked}")
    return problems


def _keys(obj: Any):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield str(k)
            yield from _keys(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _keys(v)


def load_run(run_dir: Path) -> tuple[dict | None, dict[str, dict], list[str]]:
    """(manifest, rows by prediction_id, problems) for one run folder; verifies every row and the row index."""
    try:
        manifest = _read_json(run_dir / "manifest.json")
    except (OSError, ValueError) as exc:
        return None, {}, [f"manifest.json unreadable ({type(exc).__name__})"]
    if not isinstance(manifest, dict):
        return None, {}, ["manifest.json is not a JSON object"]
    problems: list[str] = []
    rows: dict[str, dict] = {}
    hashes = []
    for meta in manifest.get("rows", []):
        file = str(meta.get("file", ""))
        try:
            if not re.fullmatch(r"rows/[A-Za-z0-9_.:\-]+\.json", file):
                raise ValueError("unexpected row file name")
            row = _read_json(run_dir / file)
        except (OSError, ValueError) as exc:
            problems.append(f"{file}: unreadable ({type(exc).__name__})")
            continue
        problems += [f"{file}: {p}" for p in verify_row(row)]
        pred = row.get("prediction", {}) if isinstance(row, dict) else {}
        if row.get("row_sha256") != meta.get("row_sha256"):
            problems.append(f"{file}: row_sha256 differs from the manifest")
        if (pred.get("prediction_id"), pred.get("event_id"), pred.get("variant")) != (
            meta.get("prediction_id"),
            meta.get("event_id"),
            meta.get("variant"),
        ):
            problems.append(f"{file}: prediction id/event/variant differ from the manifest")
        if row.get("run_id") != manifest.get("run_id"):
            problems.append(f"{file}: run_id differs from the manifest")
        rows[str(meta.get("prediction_id"))] = row
        hashes.append(meta.get("row_sha256"))
    if canon_sha(hashes) != manifest.get("rows_sha256"):
        problems.append("rows_sha256 does not match the manifest's row list")
    return manifest, rows, problems


def verify_run(run_dir: Path) -> list[str]:
    """Verify every row listed in ``run_dir/manifest.json`` and the manifest's row index. Empty = intact."""
    return load_run(run_dir)[2]


# ---------------------------------------------------------------- scorecard snapshots


def write_scorecard_snapshot(
    card: Scorecard,
    directory: Path,
    *,
    source: Literal["compute_route", "record_runs_script"],
    run_id: str | None,
    recorded_at: datetime,
    agent_models: list[str],
    cases_sha256: dict[str, str],
) -> tuple[Path, RecordedScorecard]:
    """Write one RECORDED RUN snapshot atomically; never overwrites an existing file."""
    scorecard = card.model_dump(mode="json")
    data: dict[str, Any] = {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "provenance": "RECORDED_RUN",
        "source": source,
        "run_id": run_id,
        "recorded_at": recorded_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "agent_variant": card.agent_variant,
        "agent_models": sorted(set(agent_models)),
        "cases_sha256": dict(sorted(cases_sha256.items())),
        "scorecard": scorecard,
        "scorecard_sha256": canon_sha(scorecard),
    }
    data["snapshot_sha256"] = canon_sha(data)
    record = RecordedScorecard.model_validate(data)
    directory.mkdir(parents=True, exist_ok=True)
    stamp = recorded_at.astimezone(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    path = directory / f"{card.agent_variant}--{stamp}--{data['scorecard_sha256'][:12]}.json"
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(provenance.canonical_json(data) + "\n", encoding="utf-8")
    if path.exists():
        tmp.unlink()
        raise FileExistsError(f"scorecard snapshot {path.name} already exists")
    os.replace(tmp, path)
    return path, record


def _mean(values: list[float]) -> float:
    return float(np.mean(values))


def scorecard_problems(card: Scorecard) -> list[str]:
    """The evaluator's display rules (MATH_MODEL §6), re-applied to a recorded card's own per-event rows.

    Label, verdict, caveat, provenance, counts, summary and CI must all be what ``build_scorecard`` produces for
    ``per_event``; naive scores must be those of p = 0.5. Empty list = consistent.
    """
    p: list[str] = []
    n, v = card.n_events, card.agent_variant
    forecasters = ["naive", "market", v]
    if card.forecasters != forecasters:
        p.append(f"forecasters must be {forecasters}")
    if n != len(card.per_event):
        p.append("n_events differs from the number of per-event rows")
    if card.n_excluded != len(card.exclusions):
        p.append("n_excluded differs from the exclusions listed")
    counts: dict[str, int] = {}
    for x in card.exclusions:
        counts[x.reason] = counts.get(x.reason, 0) + 1
    if card.exclusions_by_reason != counts:
        p.append("exclusions_by_reason differs from the exclusions listed")
    if (card.provenance is None) != (n == 0):
        p.append("provenance must be null exactly when no event was scored")
    allowed = {"real": Provenance.REAL_HISTORICAL, "synthetic": Provenance.SYNTHETIC}.get(card.case_set or "")
    if card.case_set is not None and card.provenance not in (None, allowed):
        p.append(f"a {card.case_set} case-set card cannot have provenance {card.provenance}")
    if card.case_set == "synthetic" and card.label.startswith("OFFICIAL"):
        p.append("a synthetic case-set card is never OFFICIAL")
    if card.market_label != market_label_for([ref for e in card.per_event for ref in e.market_refs]):
        p.append("market_label does not match the per-event market refs (synthetic prices must say SYNTHETIC)")
    if card.provenance == Provenance.REAL_HISTORICAL or card.case_set == "real":
        # A real card's baselines are real-venue quotes only: the gate refuses a synthetic quote on a real case.
        synthetic_refs = sorted(
            {e.event_id for e in card.per_event if any(r.startswith(f"{SYNTHETIC_VENUE}:") for r in e.market_refs)}
        )
        if synthetic_refs:
            p.append(f"a real card cannot have synthetic: market refs (events {synthetic_refs})")
        if card.market_label != MARKET_LABEL:
            p.append(f"a real card cannot carry a synthetic market_label (must be {MARKET_LABEL!r})")
    for e in card.per_event:
        if set(e.brier) != set(forecasters) or set(e.log_loss) != set(forecasters):
            p.append(f"{e.event_id}: per-event scores must cover exactly {forecasters}")
            continue
        if (e.brier["naive"], e.log_loss["naive"], e.accuracy_at_0_5.get("naive")) != (
            brier(0.5, e.y),
            log_loss(0.5, e.y),
            correct_at_half(0.5, e.y),
        ):
            p.append(f"{e.event_id}: naive scores are not those of p = 0.5")
        if e.n_snapshots != len(e.prediction_ids) or e.n_snapshots < 1:
            p.append(f"{e.event_id}: n_snapshots differs from prediction_ids")

    if n < MIN_EVENTS:
        expected = (LABEL_INSUFFICIENT, INSUFFICIENT_DATA, None)
        if (card.label, card.verdict, card.caveat) != expected:
            p.append(f"n = {n} < {MIN_EVENTS}: label/verdict/caveat must be {expected}")
        if card.summary is not None or card.comparison is not None:
            p.append(f"n = {n} < {MIN_EVENTS}: no summary and no comparison")
        return p

    if card.provenance == Provenance.SYNTHETIC:
        label = LABEL_ILLUSTRATIVE
    elif card.provenance == Provenance.REAL_HISTORICAL:
        label = LABEL_NOT_OFFICIAL if card.official_blockers else f"OFFICIAL: Computed from {n} historical cases"
    else:
        label = None
        p.append(f"provenance {card.provenance} cannot be scored")
    if label is not None and card.label != label:
        p.append(f"label must be {label!r} for provenance {card.provenance} with these official_blockers")
    caveat = None if n >= SMALL_SAMPLE_EVENTS else f"small sample: n = {n} events (< {SMALL_SAMPLE_EVENTS})"
    if card.caveat != caveat:
        p.append(f"caveat must be {caveat!r}")
    if p:
        return p
    summary = {
        f: (
            _mean([e.brier[f] for e in card.per_event]),
            _mean([e.log_loss[f] for e in card.per_event]),
            _mean([e.accuracy_at_0_5[f] for e in card.per_event]),
        )
        for f in forecasters
    }
    got = (
        None
        if card.summary is None
        else {f: (s.mean_brier, s.mean_log_loss, s.accuracy_at_0_5) for f, s in card.summary.items()}
    )
    if got != summary:
        p.append("summary does not recompute from the per-event scores")
    c = card.comparison
    if c is None:
        p.append(f"n = {n} >= {MIN_EVENTS}: a comparison with a CI is required")
        return p
    boot = paired_bootstrap([e.brier[v] for e in card.per_event], [e.brier["market"] for e in card.per_event])
    if (c.agent_variant, c.n_resamples, c.seed, c.confidence) != (v, DEFAULT_RESAMPLES, BOOTSTRAP_SEED, CONFIDENCE):
        p.append("comparison must use this variant and the pre-specified B, seed and confidence")
    if (c.mean_delta_brier, c.ci_low, c.ci_high) != (boot.mean_delta, boot.ci_low, boot.ci_high):
        p.append("comparison CI does not recompute from the per-event scores")
    verdict = AGENT_BETTER if c.ci_high < 0 else NO_IMPROVEMENT
    if card.verdict != verdict:
        p.append(f"verdict must be {verdict!r} (CI upper bound {c.ci_high})")
    return p


def cases_sha256_problems(record: RecordedScorecard) -> list[str]:
    """``cases_sha256`` must agree with the card's case set (#118).

    ``compute_and_record`` lists exactly the committed cases of the card's set (``event_case_sets``), and every
    such case is a key of the card at its cutoff, so each listed case is either scored (``per_event``) or excluded
    (``exclusions``). A listed case that is in neither belongs to the other set (or to no card) and is refused.
    The other direction (every committed case of the set is listed) needs the case files and is not checked here.
    """
    card = record.scorecard
    in_card = {e.event_id for e in card.per_event} | {x.event_id for x in card.exclusions}
    stray = sorted(set(record.cases_sha256) - in_card)
    if not stray:
        return []
    return [f"cases_sha256 lists case(s) that are not in this {case_set_of(card)} case-set card: {stray}"]


def _committed_problems(record: RecordedScorecard, file_name: str, runs_root: Path) -> list[str]:
    """A committed snapshot must belong to a scored, non-dry official run whose rows verify and match it."""
    if record.source != "record_runs_script" or record.run_id is None or not _RUN_ID.fullmatch(record.run_id):
        return ["a committed snapshot must come from scripts/record_runs.py with a valid run_id"]
    run_dir = runs_root / record.run_id
    if not (run_dir / "manifest.json").is_file():
        return [f"run {record.run_id}: no manifest.json in recorded_runs/runs/"]
    manifest, rows, problems = load_run(run_dir)
    if manifest is None:
        return [f"run {record.run_id}: {'; '.join(problems)}"]
    problems = [f"run {record.run_id}: {x}" for x in problems]
    if manifest.get("dry_run") is not False or manifest.get("phase") != "scored":
        problems.append(f"run {record.run_id}: must be a scored, non-dry run")
    if manifest.get("provenance") != "RECORDED_RUN" or manifest.get("run_id") != record.run_id:
        problems.append(f"run {record.run_id}: manifest provenance/run_id mismatch")
    listed = [
        s
        for s in manifest.get("scorecards", [])
        if s.get("file") == f"scorecards/{file_name}" and s.get("scorecard_sha256") == record.scorecard_sha256
    ]
    if not listed:
        problems.append(f"run {record.run_id}: the manifest does not list this snapshot with this scorecard_sha256")
    if problems:
        return problems
    card, v = record.scorecard, record.agent_variant
    for e in card.per_event:
        mine = [rows.get(pid) for pid in e.prediction_ids]
        if any(r is None or r["prediction"]["variant"] != v or r["prediction"]["event_id"] != e.event_id for r in mine):
            problems.append(f"{e.event_id}: prediction_ids are not this run's {v} rows for this event")
            continue
        agent = [float(r["prediction"]["p_yes"]) for r in mine]
        market = [r["context"]["market_baseline_p_yes"] for r in mine]
        if any(m is None for m in market):
            problems.append(f"{e.event_id}: a scored row has no market baseline")
            continue
        for f, probs in ((v, agent), ("market", [float(m) for m in market])):
            want = (
                _mean([brier(q, e.y) for q in probs]),
                _mean([log_loss(q, e.y) for q in probs]),
                _mean([correct_at_half(q, e.y) for q in probs]),
            )
            if (e.brier[f], e.log_loss[f], e.accuracy_at_0_5[f]) != want:
                problems.append(f"{e.event_id}: {f} scores do not recompute from the run's rows")
        if e.market_refs != sorted({r["context"]["market_baseline_ref"] for r in mine} - {None}):
            problems.append(f"{e.event_id}: market_refs differ from the run's rows")
    scored = [rows[pid] for e in card.per_event for pid in e.prediction_ids if pid in rows]
    models = sorted({r["prediction"]["agent_model"] for r in scored})
    if record.agent_models != models:
        problems.append("agent_models differ from the run's scored rows")
    synthetic = {bool(r["context"]["synthetic"]) for r in scored}
    expected = {
        frozenset(): None,
        frozenset({True}): Provenance.SYNTHETIC,
        frozenset({False}): Provenance.REAL_HISTORICAL,
    }.get(frozenset(synthetic), "mixed")
    if card.provenance != expected:
        problems.append(f"provenance {card.provenance} differs from the run's scored rows ({expected})")
    return problems


def verify_snapshot(
    raw: Any, *, origin: Origin = "computed", file_name: str | None = None, runs_root: Path | None = None
) -> tuple[RecordedScorecard | None, list[str]]:
    """Validate one snapshot: both hashes recomputed from the stored JSON, the evaluator's display rules
    (``scorecard_problems``), no dry-run model, and, for ``origin == "committed"``, the official run it came from
    (``runs_root/<run_id>``). Returns (record, []) if it may be served, else (None, problems)."""
    if not isinstance(raw, dict):
        return None, ["not a JSON object"]
    problems: list[str] = []
    if isinstance(raw.get("scorecard"), dict):
        try:
            if canon_sha(raw["scorecard"]) != raw.get("scorecard_sha256"):
                problems.append("scorecard_sha256 does not match the stored scorecard")
            rest = {k: v for k, v in raw.items() if k != "snapshot_sha256"}
            if canon_sha(rest) != raw.get("snapshot_sha256"):
                problems.append("snapshot_sha256 does not match the stored snapshot")
        except (TypeError, ValueError):
            problems.append("snapshot is not plain canonical JSON")
    try:
        record = RecordedScorecard.model_validate(raw)
    except ValidationError as exc:
        return None, [*problems, f"schema: {exc.error_count()} error(s)"]
    if problems:
        return None, problems
    if record.scorecard.agent_variant != record.agent_variant:
        problems.append("agent_variant differs from the scorecard's agent_variant")
    if DRY_RUN_AGENT_MODEL in record.agent_models:
        problems.append(f"{DRY_RUN_AGENT_MODEL} (dry-run mock) is never a scored model")
    problems += scorecard_problems(record.scorecard)
    problems += cases_sha256_problems(record)
    if origin == "committed" and not problems:
        if file_name is None or runs_root is None:
            problems.append("a committed snapshot needs its file name and the runs folder to be verified")
        else:
            problems += _committed_problems(record, file_name, runs_root)
    return (None if problems else record), problems


def _load_dir(directory: Path, origin: Origin, notes: list[str]):
    if not directory.is_dir():
        return []
    found = []
    runs_root = recorded_runs_dir() / "runs"
    for path in sorted(p for p in directory.glob("*.json") if not p.name.startswith(".")):
        label = f"{origin} snapshot {path.name}"
        try:
            raw = _read_json(path)
        except (OSError, UnicodeDecodeError, ValueError):
            notes.append(f"{label} could not be read as JSON; not served.")
            continue
        record, problems = verify_snapshot(raw, origin=origin, file_name=path.name, runs_root=runs_root)
        if record is None:
            kind = "failed its hash check" if any("sha256 does not match" in p for p in problems) else "failed checks"
            notes.append(f"{label} {kind} ({'; '.join(problems[:5])}); not served.")
            continue
        found.append((record, origin, path.name))
    return found


def case_set_of(card: Scorecard) -> CaseSet:
    """The card's case set; a snapshot from before #102 (no case_set) is synthetic iff its provenance is."""
    if card.case_set is not None:
        return card.case_set
    return "synthetic" if card.provenance == Provenance.SYNTHETIC else "real"


def _record(record: RecordedScorecard, origin: Origin, name: str) -> ScorecardRecord:
    return ScorecardRecord(
        agent_variant=record.agent_variant,
        case_set=case_set_of(record.scorecard),
        recorded_at=record.recorded_at,
        source=record.source,
        origin=origin,
        run_id=record.run_id,
        file=name,
        scorecard_sha256=record.scorecard_sha256,
        snapshot_sha256=record.snapshot_sha256,
        agent_models=record.agent_models,
    )


def latest_scorecards() -> BenchmarkResponse:
    """Per case set (real first): newest verified committed snapshot per variant, then newest verified computed
    one. Reads files only."""
    notes: list[str] = []
    by_origin = {"committed": _load_dir(committed_dir(), "committed", notes)}
    by_origin["computed"] = _load_dir(computed_dir(), "computed", notes)
    items: list[Scorecard] = []
    records: list[ScorecardRecord] = []
    for case_set in CASE_SETS:
        for origin in ("committed", "computed"):
            for variant in VARIANT_ORDER:
                mine = [
                    c
                    for c in by_origin[origin]
                    if c[0].agent_variant == variant and case_set_of(c[0].scorecard) == case_set
                ]
                if mine:
                    record, _origin, name = max(mine, key=lambda c: (c[0].recorded_at, c[2]))
                    items.append(record.scorecard)
                    records.append(_record(record, origin, name))
    if not items:
        notes.insert(
            0,
            f"Benchmark {NOT_AVAILABLE}: no recorded scorecard yet. Scores appear only after an admin runs the "
            "official run procedure (docs/EVALUATION_PROTOCOL.md §8); this page never computes or reveals.",
        )
    missing = [v for v in VARIANT_ORDER if v not in {r.agent_variant for r in records}]
    if items and missing:
        notes.append(f"No recorded scorecard for {', '.join(missing)} ({NOT_AVAILABLE}).")
    return BenchmarkResponse(status="AVAILABLE" if items else NOT_AVAILABLE, items=items, records=records, notes=notes)


# ---------------------------------------------------------------- compute


_COMPUTE_LOCK = threading.Lock()


def compute_and_record(
    agent_variant: ScoredVariant,
    *,
    directory: Path | None = None,
    source: Literal["compute_route", "record_runs_script"] = "compute_route",
    run_id: str | None = None,
    store: PredictionStore | None = None,
    cases: EvidenceStore | None = None,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> list[tuple[Path, RecordedScorecard]]:
    """Score ``agent_variant`` on the configured store / sealed folder / committed cases and record one snapshot
    per case set present (real first, then synthetic; ``core.evaluator.case_sets_present``). With no case at all,
    one empty real card is recorded (INSUFFICIENT DATA). Real and synthetic cases are never pooled.

    This REVEALS (through ``OutcomeVault``). Callers: the admin-gated route and scripts/record_runs.py.
    """
    with _COMPUTE_LOCK:
        store = store if store is not None else PredictionStore(store_module.DEFAULT_DB_PATH)
        cases = cases if cases is not None else EvidenceStore.from_dir()
        out = []
        for case_set in case_sets_present(store, cases) or ["real"]:
            card = build_scorecard(OutcomeVault(store), agent_variant=agent_variant, cases=cases, case_set=case_set)
            scored = {pid for e in card.per_event for pid in e.prediction_ids}
            recs = store.all_records()
            models = [r.prediction.agent_model for r in recs if r.prediction.prediction_id in scored]
            sets = event_case_sets(cases, recs)
            out.append(
                write_scorecard_snapshot(
                    card,
                    directory if directory is not None else computed_dir(),
                    source=source,
                    run_id=run_id,
                    recorded_at=clock(),
                    agent_models=models,
                    cases_sha256={cid: cases.case_sha256(cid) for cid in cases.case_ids() if sets[cid] == case_set},
                )
            )
        return out


# ---------------------------------------------------------------- routers

router = APIRouter(tags=["benchmark"], route_class=CodedRoute)
admin_router = APIRouter(tags=["benchmark"], route_class=AdminGatedRoute)

_ADMIN_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"model": ApiError, "description": "ADMIN_TOKEN_REQUIRED (public mode): no bearer token presented"},
    403: {"model": ApiError, "description": "ADMIN_TOKEN_REQUIRED (public mode): wrong token, or none configured"},
}


@router.get(
    "/benchmark",
    response_model=BenchmarkResponse,
    summary="Recorded benchmark scorecards (read-only; never reveals)",
)
def get_benchmark() -> BenchmarkResponse:
    return latest_scorecards()


@admin_router.post(
    "/benchmark/compute",
    response_model=BenchmarkResponse,
    responses={**_ADMIN_RESPONSES, **error_responses(422, 500)},
    summary="Score one agent variant (REVEALS outcomes; admin only in public mode) and record the scorecard",
)
def compute_benchmark(body: BenchmarkComputeRequest) -> BenchmarkResponse:
    try:
        recorded = compute_and_record(body.agent_variant)
    except (SealedDataError, ValidationError) as exc:
        raise _data_invalid(f"a committed case file was refused ({type(exc).__name__})") from None
    except ValueError as exc:
        raise _data_invalid(f"the case or outcome data could not be scored ({type(exc).__name__})") from None
    except (RuntimeError, OSError) as exc:
        raise _data_invalid(f"the scorecard could not be computed or recorded ({type(exc).__name__})") from None
    return BenchmarkResponse(
        status="AVAILABLE",
        items=[record.scorecard for _path, record in recorded],
        records=[_record(record, "computed", path.name) for path, record in recorded],
        notes=[],
    )


def _data_invalid(what: str) -> RouteError:
    # Exception text is not echoed: a refused file's message could quote its content.
    return RouteError(ErrorCode.DATA_INVALID, f"Benchmark not computed: {what}.", status_code=500)


router.include_router(admin_router)
