#!/usr/bin/env python3
"""Official Blind Replay run: forecast every committed case x variant, save, THEN score (EVALUATION_PROTOCOL §8).

Lead-only procedure, run once the reviewed case files and sealed outcomes are on main:

    python scripts/record_runs.py                      # forecast all, save, write rows, then score
    python scripts/record_runs.py --forecast-only      # stop after the rows (commit them first, score later)
    python scripts/record_runs.py --score <RUN_ID>     # score a run whose forecasts are already saved
    python scripts/record_runs.py --resume <RUN_ID>    # finish a run that stopped (e.g. Ollama went down)
    python scripts/record_runs.py --dry-run [--out DIR]  # mocked provider, scratch store, never scores

Order of operations (each step refuses rather than guessing):

1. Pre-flight, before any model call: refuse if the configured prediction store has a counted reveal in its audit
   log (no peeking; ``core.evaluator.first_counted_reveal``, the scorecard's own ``late`` rule: only a reveal
   logged with sealed provenance SYNTHETIC of a committed SYNTHETIC case whose every stored forecast froze
   ``synthetic=True`` is exempt), or already holds a forecast for a committed case x variant (other than this run's, on
   ``--resume``); refuse if a case's curated ``contamination_flag`` is weaker than the one derived from the
   model card (``agents.model_cards.contamination_flag``, model cutoff vs. the case horizon end
   ``as_of + horizon_days``); a dry run records the disagreement instead.
2. Forecast: for every committed case at its cutoff and every variant, ``EvidenceStore.get_as_of`` ->
   ``model_input`` -> ``LocalOllamaProvider.forecast`` (#40) -> skeptic -> ``PredictionStore.save(...,
   final_prompt=...)`` with the Prediction built by ``routes.replay.prediction_from_result`` (the same as
   ``POST /api/replay/run``). Nothing is revealed. ``MODEL_UNAVAILABLE`` aborts the run (resume later); invalid
   output, an over-long or unverified prompt, a skeptic rejection, or a model prompt the store refuses is recorded
   as failed and never persisted; ``agent_plus_market`` without a market quote is skipped (NOT AVAILABLE).
3. Rows: each saved forecast is written as a RECORDED RUN row (``runs/<run_id>/rows/<prediction_id>.json``)
   with the exact prompt and snapshot JSON, the model-call audit fields and every hash, plus ``manifest.json``.
4. Score (only if nothing failed, or explicitly with ``--score``): verify every row against its hashes
   (``routes.benchmark.verify_row``) and against the store's copy, then ``build_scorecard`` once per variant and
   case set (real, then synthetic, never pooled; #102) via ``routes.benchmark.compute_and_record`` (this
   reveals), and write each Scorecard as a RECORDED RUN snapshot to ``<out>/scorecards/``. A run is scored at most
   once.

Default output: ``<FAULTLINE_DATA_DIR>/recorded_runs/`` (committed). Exit codes: 0 done, 2 refused, 3 incomplete.
No path substitutes a canned answer for a model forecast; the dry run's mocked answers are labeled SIMULATED,
``agent_model = "ollama/dry-run-mock"`` and are never scored or served.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

API_DIR = Path(__file__).resolve().parents[1] / "services" / "api"
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

import httpx  # noqa: E402

from agents import skeptic  # noqa: E402
from agents.local_ollama import PROVIDER_ID, LocalOllamaProvider  # noqa: E402
from agents.model_cards import contamination_flag  # noqa: E402
from agents.provider import (  # noqa: E402
    ModelOutputInvalid,
    ModelProvider,
    ModelUnavailable,
    PromptNotVerified,
    PromptTooLong,
)
from config import get_settings  # noqa: E402
from core import store as store_module  # noqa: E402
from core.evaluator import first_counted_reveal  # noqa: E402
from core.store import HashMismatch, PredictionStore  # noqa: E402
from core.temporal_gate import PROMPT_VARIANTS, EvidenceStore, MarketNotAvailable  # noqa: E402
from models import ErrorCode, Provenance  # noqa: E402
from routes.benchmark import (  # noqa: E402
    DRY_RUN_AGENT_MODEL,
    canon_sha,
    compute_and_record,
    load_run,
    verify_row,
    verify_run,
)
from routes.replay import prediction_from_result  # noqa: E402

__all__ = ["verify_row", "verify_run", "run_forecasts", "score_run", "main", "Refused", "Aborted"]

ROW_SCHEMA = "faultline.recorded_run_row/1"
MANIFEST_SCHEMA = "faultline.recorded_run_manifest/1"
DRY_RUN_MODEL = DRY_RUN_AGENT_MODEL.removeprefix(f"{PROVIDER_ID}/")
DRY_RUN_RATIONALE = "DRY RUN: mocked provider output, not a model forecast."
_SEVERITY = {"unlikely": 0, "unknown": 1, "likely": 2}


class Refused(RuntimeError):
    """Pre-flight or verification refused the run; nothing was forecast or revealed by this call."""


class Aborted(RuntimeError):
    """The run stopped part-way (model unavailable); saved forecasts stay saved, nothing was revealed."""


@dataclass
class RunOutcome:
    run_dir: Path
    manifest: dict[str, Any]

    @property
    def complete(self) -> bool:
        return self.manifest["phase"] == "forecasts_saved"


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


_canon_sha = canon_sha


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _read_manifest(run_dir: Path) -> dict:
    try:
        manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise Refused(f"no run {run_dir.name!r}: {run_dir / 'manifest.json'} does not exist") from None
    except (OSError, ValueError) as exc:
        raise Refused(f"run {run_dir.name!r}: manifest.json unreadable ({type(exc).__name__})") from None
    if not isinstance(manifest, dict):
        raise Refused(f"run {run_dir.name!r}: manifest.json is not a JSON object")
    return manifest


def prediction_id_for(run_id: str, variant: str, event_id: str) -> str:
    pid = f"rr-{run_id}-{variant}-{event_id}"
    return pid if len(pid) <= 200 else f"rr-{run_id}-{variant}-{hashlib.sha256(event_id.encode()).hexdigest()[:16]}"


# ---------------------------------------------------------------- mocked provider (dry run and tests)


def mock_transport(
    answer: Callable[[str], str],
    *,
    model_tag: str = DRY_RUN_MODEL,
    digest: str | None = None,
    unavailable: Callable[[int], bool] | None = None,
) -> httpx.MockTransport:
    """An Ollama stand-in for ``LocalOllamaProvider``: ``/api/tags`` lists ``model_tag``; ``/api/chat`` returns
    ``answer(user_message)`` with a prompt token count consistent with the whole message being read.
    ``unavailable(n_chat_calls_so_far)`` -> True makes every request fail as unreachable."""
    chats = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal chats
        if unavailable is not None and unavailable(chats):
            raise httpx.ConnectError("mock Ollama unavailable", request=request)
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": model_tag, "model": model_tag, "digest": digest}]})
        if request.url.path == "/api/chat":
            chats += 1
            body = json.loads(request.content)
            text = "".join(m["content"] for m in body["messages"])
            return httpx.Response(
                200,
                json={
                    "message": {"role": "assistant", "content": answer(text)},
                    "done_reason": "stop",
                    "prompt_eval_count": len(text.encode("utf-8")) // 4 + 10,
                    "eval_count": 40,
                },
            )
        return httpx.Response(404, json={"error": "not found"})

    return httpx.MockTransport(handler)


def dry_run_provider() -> LocalOllamaProvider:
    answer = json.dumps({"p_yes": 0.5, "decision": "wait", "rationale": DRY_RUN_RATIONALE, "evidence_ids": []})
    return LocalOllamaProvider("http://dry-run.invalid", DRY_RUN_MODEL, transport=mock_transport(lambda _p: answer))


# ---------------------------------------------------------------- rows


def build_row(*, run_id, prov: Provenance, saved, mi, result, report, provider_id, contamination) -> dict:
    pred = saved.prediction
    final_prompt = saved.model_prompt
    if not final_prompt.startswith(mi.prompt):  # the store already refused anything else; never write such a row
        raise HashMismatch("the saved model prompt does not start with the gated prompt")
    row = {
        "schema": ROW_SCHEMA,
        "provenance": prov.value,
        "run_id": run_id,
        "prediction": pred.model_dump(mode="json"),
        "context": saved.context.as_json(),
        "persisted_at": _iso(saved.persisted_at),
        "persist_seq": saved.persist_seq,
        "record_sha256": saved.record_sha256,
        "template_version": mi.template_version,
        "prompt": mi.prompt,
        "snapshot_json": mi.snapshot_json,
        "model_call": {
            "provider_id": provider_id,
            "model_tag": result.model_tag,
            "model_digest": result.model_digest,
            "temperature": result.temperature,
            "seed": result.seed,
            "num_ctx": pred.num_ctx,
            "num_predict": pred.num_predict,
            "attempts": pred.attempts,
            "final_prompt_suffix": final_prompt[len(mi.prompt) :],
            "final_prompt_sha256": pred.prompt_sha256,
            "transcript_sha256": pred.transcript_sha256,
            "raw_output": result.raw_output,
            "raw_output_sha256": result.raw_output_sha256,
            "prompt_eval_count": result.prompt_eval_count,
            "eval_count": result.eval_count,
            "done_reason": result.done_reason,
            "latency_ms": result.latency_ms,
        },
        "skeptic": [p.model_dump(mode="json") for p in report.problems],
        "contamination": contamination,
    }
    row["row_sha256"] = canon_sha(row)
    return row


# ---------------------------------------------------------------- forecast phase


def _contamination(cases: EvidenceStore, model_tag: str | None) -> list[dict]:
    out = []
    for cid in cases.case_ids():
        case = cases.public_case(cid)
        horizon_end = case.as_of + timedelta(days=case.horizon_days)
        derived = contamination_flag(model_tag, horizon_end) if model_tag else "unknown"
        out.append(
            {
                "event_id": cid,
                "as_of": _iso(case.as_of),
                "case_sha256": cases.case_sha256(cid),
                "contamination_flag": case.contamination_flag,
                "model_card_contamination_flag": derived,
                "horizon_end_at": _iso(horizon_end),
            }
        )
    return out


def _preflight(store: PredictionStore, cases: EvidenceStore, variants, resume_rows: dict, enforce, contamination):
    # The evaluator's own rule (#118): only a reveal LOGGED as SYNTHETIC of a committed SYNTHETIC case whose every
    # stored forecast froze synthetic=True (e.g. the fallback revealed on stage) does not count.
    first = first_counted_reveal(store, cases)
    if first is not None:
        raise Refused(
            f"the prediction store already has a reveal (audit_log seq {first.seq}); an official run needs every "
            "forecast saved before any outcome is revealed (only logged-SYNTHETIC reveals of committed synthetic "
            "cases are exempt). Use a fresh store."
        )
    clashes = []
    for cid in cases.case_ids():
        as_of = cases.public_case(cid).as_of
        for variant in variants:
            ids = [r.prediction.prediction_id for r in store.records_for(cid, as_of, variant)]
            if ids and ids != [resume_rows.get((cid, variant))]:
                clashes.append(f"{cid}/{variant}: {ids}")
    if clashes:
        raise Refused(
            "forecasts already exist for these case x variant keys (one forecast each is allowed; resume the run "
            "that saved them with --resume RUN_ID): " + "; ".join(clashes)
        )
    weak = [
        f"{c['event_id']}: case says {c['contamination_flag']!r}, "
        f"model card says {c['model_card_contamination_flag']!r}"
        for c in contamination
        if _SEVERITY[c["contamination_flag"]] < _SEVERITY[c["model_card_contamination_flag"]]
    ]
    if weak and enforce:
        raise Refused(
            "curated contamination_flag is weaker than the model card allows (fix the case files in a reviewed PR "
            "before the official run): " + "; ".join(weak)
        )
    return weak


def _manifest_shell(run_id, prov, dry_run, mocked, provider, model_tag, variants, contamination, clock) -> dict:
    return {
        "schema": MANIFEST_SCHEMA,
        "provenance": prov.value,
        "run_id": run_id,
        "dry_run": dry_run,
        "mocked_provider": mocked,
        "created_at": _iso(clock()),
        "phase": "forecasting",
        "provider_id": provider.provider_id,
        "model_tag": model_tag,
        "variants": list(variants),
        "cases": contamination,
        "contamination_warnings": [],
        "rows": [],
        "skipped": [],
        "failed": [],
        "scorecards": [],
        "rows_sha256": canon_sha([]),
    }


def _save_manifest(run_dir: Path, manifest: dict) -> None:
    manifest["rows_sha256"] = canon_sha([r["row_sha256"] for r in manifest["rows"]])
    _write_json(run_dir / "manifest.json", manifest)


_FAILURE_CODES = {
    ModelOutputInvalid: ErrorCode.MODEL_OUTPUT_INVALID.value,
    PromptTooLong: ErrorCode.PROMPT_TOO_LONG.value,
    PromptNotVerified: ErrorCode.PROMPT_NOT_VERIFIED.value,
}


def run_forecasts(
    provider: ModelProvider,
    *,
    cases: EvidenceStore,
    store: PredictionStore,
    out_root: Path,
    variants: tuple[str, ...] = PROMPT_VARIANTS,
    clock: Callable[[], datetime] = _now,
    dry_run: bool = False,
    mocked: bool | None = None,
    resume: str | None = None,
) -> RunOutcome:
    """Steps 1-3. Raises Refused (pre-flight) or Aborted (model unavailable). Never reveals."""
    mocked = dry_run if mocked is None else mocked
    prov = Provenance.SIMULATED if dry_run else Provenance.RECORDED_RUN
    model_tag = getattr(provider, "model", None)
    contamination = _contamination(cases, model_tag)

    if resume:
        run_id = resume
        run_dir = out_root / "runs" / run_id
        manifest = _read_manifest(run_dir)
        problems = verify_run(run_dir)
        if problems:
            raise Refused(f"run {run_id} does not verify: " + "; ".join(problems))
        if manifest.get("dry_run") != dry_run or manifest.get("phase") == "scored":
            raise Refused(
                f"run {run_id} cannot be resumed (dry_run={manifest.get('dry_run')}, phase={manifest.get('phase')})"
            )
        variants = tuple(manifest["variants"])
    else:
        run_id = clock().strftime("%Y%m%dT%H%M%SZ")
        run_dir = out_root / "runs" / run_id
        if run_dir.exists():
            raise Refused(f"run directory {run_id} already exists")
        manifest = _manifest_shell(run_id, prov, dry_run, mocked, provider, model_tag, variants, contamination, clock)
    done = {(r["event_id"], r["variant"]): r["prediction_id"] for r in manifest["rows"]}
    manifest["contamination_warnings"] = _preflight(store, cases, variants, done, not dry_run, contamination)
    manifest["cases"] = contamination
    manifest["skipped"], manifest["failed"] = [], []
    if not run_dir.exists():
        _save_manifest(run_dir, manifest)

    flags = {c["event_id"]: c for c in contamination}
    try:
        asyncio.run(_forecast_all(provider, cases, store, variants, run_dir, manifest, done, prov, flags, clock))
    except ModelUnavailable as exc:
        manifest["phase"] = "incomplete"
        manifest["failed"].append({"code": ErrorCode.MODEL_UNAVAILABLE.value, "message": str(exc)})
        _save_manifest(run_dir, manifest)
        raise Aborted(f"MODEL_UNAVAILABLE: {exc} Saved forecasts are kept; resume with --resume {run_id}.") from None
    manifest["phase"] = "incomplete" if manifest["failed"] else "forecasts_saved"
    _save_manifest(run_dir, manifest)
    return RunOutcome(run_dir=run_dir, manifest=manifest)


def _fail(manifest: dict, cid: str, variant: str, code: str, message: str) -> None:
    manifest["failed"].append({"event_id": cid, "variant": variant, "code": code, "message": message})


async def _forecast_all(provider, cases, store, variants, run_dir, manifest, done, prov, flags, clock) -> None:
    for cid in cases.case_ids():
        snap = cases.get_as_of(cid, cases.public_case(cid).as_of)
        for variant in variants:
            if (cid, variant) in done:
                continue
            try:
                mi = snap.model_input(variant)
            except MarketNotAvailable:
                manifest["skipped"].append({"event_id": cid, "variant": variant, "reason": "market_not_available"})
                continue
            if first_counted_reveal(store, cases) is not None:
                raise Refused("a reveal appeared in the store during the run; stopping (nothing more is saved)")
            try:
                result = await provider.forecast(mi.prompt, mi.evidence_ids)
            except (ModelOutputInvalid, PromptTooLong, PromptNotVerified) as exc:
                code = next(c for cls, c in _FAILURE_CODES.items() if isinstance(exc, cls))
                _fail(manifest, cid, variant, code, str(exc))
                continue
            report = skeptic.review(result.output, mi.evidence_ids)
            if report.rejected:
                _fail(manifest, cid, variant, "SKEPTIC_REJECTED", ", ".join(report.codes()))
                continue
            pid = prediction_id_for(manifest["run_id"], variant, cid)
            prediction = prediction_from_result(
                mi, result, provider, prediction_id=pid, recorded_at=clock(), provenance=prov
            )
            try:
                # The store refuses a model prompt that is not the gated prompt (attempts 1) or the gated prompt
                # plus exactly the provider's repair instruction (attempts 2), and any hash that does not match.
                saved = store.save(prediction, mi, final_prompt=result.final_prompt)
            except HashMismatch as exc:
                _fail(manifest, cid, variant, "FINAL_PROMPT_NOT_GATED", f"not saved: {exc}")
                continue
            flag = flags[cid]
            row = build_row(
                run_id=manifest["run_id"],
                prov=prov,
                saved=saved,
                mi=mi,
                result=result,
                report=report,
                provider_id=provider.provider_id,
                contamination={
                    "case_flag": flag["contamination_flag"],
                    "model_card_flag": flag["model_card_contamination_flag"],
                    "horizon_end_at": flag["horizon_end_at"],
                },
            )
            file = f"rows/{pid}.json"
            _write_json(run_dir / file, row)
            manifest["rows"].append(
                {
                    "prediction_id": pid,
                    "event_id": cid,
                    "variant": variant,
                    "file": file,
                    "row_sha256": row["row_sha256"],
                    "record_sha256": saved.record_sha256,
                }
            )
            _save_manifest(run_dir, manifest)


# ---------------------------------------------------------------- score phase


def score_run(
    run_dir: Path,
    *,
    store: PredictionStore | None = None,
    cases: EvidenceStore | None = None,
    out_root: Path,
    clock: Callable[[], datetime] = _now,
) -> list[Path]:
    """Step 4: verify the run's rows against their hashes and the store, then score each variant once (REVEALS)."""
    manifest = _read_manifest(run_dir)
    if manifest.get("dry_run") is not False:
        raise Refused("a dry run (mocked provider) is never scored")
    if manifest.get("phase") == "scored":
        raise Refused(f"run {run_dir.name} is already scored; a run is scored once")
    _manifest, rows, problems = load_run(run_dir)
    store = store if store is not None else PredictionStore(store_module.DEFAULT_DB_PATH)
    for meta in manifest["rows"]:
        pid = meta["prediction_id"]
        rec, row = store.get_record(pid), rows.get(pid)
        if rec is None or rec.record_sha256 != meta["record_sha256"]:
            problems.append(f"{pid}: not in the store with the recorded record_sha256")
            continue
        if row is None:
            continue  # already reported by load_run
        final_prompt = row["prompt"] + row["model_call"]["final_prompt_suffix"]
        if (row["prompt"], final_prompt, row["snapshot_json"]) != (rec.prompt, rec.model_prompt, rec.snapshot_json):
            problems.append(f"{pid}: the row's gated prompt, model prompt or snapshot differs from the store's")
        if row["prediction"] != rec.prediction.model_dump(mode="json"):
            problems.append(f"{pid}: the row's prediction differs from the store's")
    if problems:
        raise Refused("rows do not verify; nothing was revealed: " + "; ".join(problems))
    cases = cases if cases is not None else EvidenceStore.from_dir()
    paths = []
    for variant in manifest["variants"]:
        # One snapshot per case set present (real first, then synthetic); they are never pooled (#102).
        for path, record in compute_and_record(
            variant,
            directory=out_root / "scorecards",
            source="record_runs_script",
            run_id=manifest["run_id"],
            store=store,
            cases=cases,
            clock=clock,
        ):
            paths.append(path)
            card = record.scorecard
            manifest["scorecards"].append(
                {
                    "agent_variant": variant,
                    "case_set": card.case_set,
                    "file": f"scorecards/{path.name}",
                    "scorecard_sha256": record.scorecard_sha256,
                    "label": card.label,
                    "verdict": card.verdict,
                    "n_events": card.n_events,
                    "official_blockers": card.official_blockers,
                }
            )
    manifest["phase"] = "scored"
    _save_manifest(run_dir, manifest)
    return paths


# ---------------------------------------------------------------- CLI


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dry-run", action="store_true", help="mocked provider, scratch store, never scores")
    ap.add_argument("--out", type=Path, help="output root (default <FAULTLINE_DATA_DIR>/recorded_runs)")
    ap.add_argument("--variants", nargs="+", choices=PROMPT_VARIANTS, default=list(PROMPT_VARIANTS))
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--forecast-only", action="store_true", help="stop after saving forecasts and rows")
    mode.add_argument("--score", metavar="RUN_ID", help="score a run whose forecasts are already saved")
    mode.add_argument("--resume", metavar="RUN_ID", help="finish a run that stopped part-way")
    args = ap.parse_args(argv)

    if args.dry_run:
        if args.score:
            print("refused: a dry run is never scored", file=sys.stderr)
            return 2
        out_root = args.out or Path(tempfile.mkdtemp(prefix="faultline-dry-run-"))
        store = PredictionStore(out_root / "dry-run.sqlite3")
        provider: ModelProvider = dry_run_provider()
    else:
        out_root = args.out or get_settings().data_dir / "recorded_runs"
        store = PredictionStore(store_module.DEFAULT_DB_PATH)
        provider = LocalOllamaProvider.from_settings()

    try:
        if args.score:
            paths = score_run(out_root / "runs" / args.score, store=store, out_root=out_root)
            print(f"scored run {args.score}: " + ", ".join(p.name for p in paths))
            return 0
        outcome = run_forecasts(
            provider,
            cases=EvidenceStore.from_dir(),
            store=store,
            out_root=out_root,
            variants=tuple(args.variants),
            dry_run=args.dry_run,
            resume=args.resume,
        )
    except Refused as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    except Aborted as exc:
        print(f"incomplete: {exc}", file=sys.stderr)
        return 3

    m = outcome.manifest
    print(f"run {m['run_id']}: {len(m['rows'])} saved, {len(m['skipped'])} skipped, {len(m['failed'])} failed")
    print(f"rows + manifest: {outcome.run_dir}")
    for w in m["contamination_warnings"]:
        print(f"contamination warning: {w}")
    if args.dry_run:
        print("dry run: not scored (scoring would reveal real outcomes into a scratch store).")
        return 0
    if not outcome.complete:
        print(
            f"not scored: {len(m['failed'])} forecast(s) failed. Fix and --resume {m['run_id']}, or score anyway "
            f"with --score {m['run_id']} (missing forecasts then block the OFFICIAL label)."
        )
        return 3
    if args.forecast_only:
        print(f"forecasts saved, nothing revealed. Commit the rows, then: --score {m['run_id']}")
        return 0
    try:
        paths = score_run(outcome.run_dir, store=store, out_root=out_root)
    except Refused as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    print("scorecards: " + ", ".join(p.name for p in paths))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
