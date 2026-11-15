#!/usr/bin/env python3
"""FAULTLINE release preflight (issue #57). Run with `make preflight` (add `ARGS=--tests` to also run pytest).

Prints one PASS / WARN / FAIL line per check and exits 1 if any check FAILs (WARN does not fail the run).

Honesty rules this script follows:
* Sealed outcomes are never parsed or printed: only "file exists" and the SHA-256 of its raw bytes.
* A missing model, build or recorded run is reported as missing, with the honest fallback; nothing is faked.
* The prediction store path in use (the FAULTLINE_PREDICTIONS_DB setting, #130) is printed. Lead policy (#57): the
  official RECORDED RUN is made with `scripts/record_runs.py` before any stage demo, and stage demos use a separate
  scratch store (`make demo-scratch`, FAULTLINE_DEMO_STORE=<path> or FAULTLINE_PREDICTIONS_DB=<path>). Using the
  official default store is a WARN.

Standard library only at import time, so it can report missing dependencies instead of crashing on them.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
API_DIR = ROOT / "services" / "api"
WEB_DIR = ROOT / "apps" / "web"
MIN_PYTHON = (3, 11)
MIN_NODE = (20, 9)  # Next.js 16 minimum
API_DEPS = ("fastapi", "uvicorn", "pydantic", "numpy", "scipy", "networkx", "httpx")
DEV_DEPS = ("pytest", "ruff")
MODEL_FALLBACK = (
    "honest fallback: Blind Replay returns MODEL_UNAVAILABLE (no canned answer is substituted); "
    "committed RECORDED RUN scorecards are still served read-only by GET /api/benchmark"
)

results: list[tuple[str, str, str]] = []


def report(status: str, name: str, detail: str) -> None:
    results.append((status, name, detail))
    print(f"[{status:<4}] {name}: {detail}", flush=True)


def venv_python() -> Path | None:
    """services/api/.venv interpreter; `Scripts/python.exe` is the Windows layout."""
    for rel in ("bin/python", "Scripts/python.exe", "Scripts/python"):
        p = API_DIR / ".venv" / rel
        if p.exists():
            return p
    return None


def _version_tuple(text: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", text)[:3])


# ---------------------------------------------------------------- environment


def check_python() -> None:
    v = sys.version_info
    status = "PASS" if (v.major, v.minor) >= MIN_PYTHON else "FAIL"
    report(
        status,
        "python",
        f"{v.major}.{v.minor}.{v.micro} at {sys.executable} (need >= 3.11)",
    )
    vp = venv_python()
    if vp is None:
        report(
            "WARN",
            "python venv",
            "services/api/.venv not found (run `make setup`); using the interpreter above",
        )
    else:
        report("PASS", "python venv", str(vp.relative_to(ROOT)))


def check_api_deps() -> bool:
    import importlib.util

    missing = [m for m in API_DEPS if importlib.util.find_spec(m) is None]
    if missing:
        report("FAIL", "api deps", f"missing {', '.join(missing)} (run `make setup`)")
        return False
    report("PASS", "api deps", ", ".join(API_DEPS))
    dev_missing = [m for m in DEV_DEPS if importlib.util.find_spec(m) is None]
    if dev_missing:
        report(
            "WARN",
            "dev deps",
            f"missing {', '.join(dev_missing)} (tests/lint need `make setup`)",
        )
    else:
        report("PASS", "dev deps", ", ".join(DEV_DEPS))
    return True


def check_node() -> None:
    node = shutil.which("node")
    if node is None:
        report(
            "FAIL",
            "node",
            f"not on PATH (need >= {MIN_NODE[0]}.{MIN_NODE[1]} for apps/web)",
        )
        return
    try:
        out = subprocess.run(
            [node, "--version"], check=False, capture_output=True, text=True, timeout=10
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        report("FAIL", "node", f"`node --version` failed ({type(exc).__name__})")
        return
    ok = _version_tuple(out)[:2] >= MIN_NODE
    report(
        "PASS" if ok else "FAIL", "node", f"{out} (need >= {MIN_NODE[0]}.{MIN_NODE[1]})"
    )
    if not (WEB_DIR / "package.json").exists():
        report("FAIL", "web deps", "apps/web/package.json missing")
    elif (WEB_DIR / "node_modules" / "next").is_dir():
        report("PASS", "web deps", "apps/web/node_modules present")
    else:
        report("FAIL", "web deps", "apps/web/node_modules missing (run `make setup`)")


def check_web_build() -> None:
    build_id = WEB_DIR / ".next" / "BUILD_ID"
    export_index = WEB_DIR / "out" / "index.html"
    if build_id.exists():
        report(
            "PASS",
            "web build",
            f"apps/web/.next (BUILD_ID {build_id.read_text().strip()[:12]}); `make demo` serves it",
        )
    elif export_index.exists():
        report("PASS", "web build", "apps/web/out (static export)")
    else:
        report(
            "WARN",
            "web build",
            "no production build (run `make web-build`); `make demo` falls back to `next dev`",
        )


# ---------------------------------------------------------------- model


def check_ollama(base_url: str, model: str) -> None:
    try:
        with urllib.request.urlopen(f"{base_url}/api/tags", timeout=3) as resp:
            tags = json.load(resp)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        report(
            "WARN",
            "ollama",
            f"not reachable at {base_url} ({type(exc).__name__}); {MODEL_FALLBACK}",
        )
        return
    report("PASS", "ollama", f"reachable at {base_url}")
    names = {m.get("name") for m in tags.get("models", []) if isinstance(m, dict)}
    match = next(
        (
            m
            for m in tags.get("models", [])
            if isinstance(m, dict) and m.get("name") == model
        ),
        None,
    )
    if match is None:
        report(
            "WARN",
            "ollama model",
            f"{model} not installed (`ollama pull {model}`); {MODEL_FALLBACK}",
        )
    else:
        digest = str(match.get("digest", ""))[:12] or "NOT AVAILABLE"
        report(
            "PASS",
            "ollama model",
            f"{model} present (digest {digest}); {len(names)} model(s) installed",
        )


# ---------------------------------------------------------------- data


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_cases_and_seals(data_dir: Path) -> None:
    from core.temporal_gate import EvidenceStore

    try:
        store = EvidenceStore.from_dir()
        case_ids = store.case_ids()
        for cid in case_ids:
            store.public_case(
                cid
            )  # the same gated, outcome-free view GET /api/cases serves
    except Exception as exc:  # noqa: BLE001 - any load failure is a FAIL line, not a crash
        report(
            "FAIL",
            "demo cases",
            f"failed to load through the temporal gate ({type(exc).__name__}: {exc})",
        )
        return
    if not case_ids:
        report("FAIL", "demo cases", f"no case files in {data_dir / 'demo_cases'}")
        return
    report(
        "PASS",
        "demo cases",
        f"{len(case_ids)} loaded through the temporal gate: {', '.join(case_ids)}",
    )

    sealed_dir = data_dir / "sealed_outcomes"
    for cid in case_ids:
        path = sealed_dir / f"{cid}.json"
        if path.is_file():
            # Raw-byte hash only: the file is never parsed and its content is never printed.
            report(
                "PASS", f"sealed {cid}", f"exists, sha256 {sha256_file(path)[:16]}..."
            )
        else:
            report(
                "FAIL",
                f"sealed {cid}",
                "no sealed outcome file; this case cannot be scored",
            )


def check_recorded_runs() -> None:
    from routes import benchmark

    runs_root = benchmark.recorded_runs_dir() / "runs"
    run_dirs = (
        sorted(p for p in runs_root.iterdir() if p.is_dir())
        if runs_root.is_dir()
        else []
    )
    if not run_dirs:
        report(
            "WARN",
            "recorded runs",
            "none committed yet (official RECORDED RUN is PENDING #57)",
        )
    for run_dir in run_dirs:
        problems = benchmark.verify_run(run_dir)
        if problems:
            report(
                "FAIL",
                f"recorded run {run_dir.name}",
                f"{len(problems)} problem(s): {'; '.join(problems[:3])}",
            )
        else:
            report(
                "PASS",
                f"recorded run {run_dir.name}",
                "manifest and every row hash recompute",
            )

    cards = sorted(
        p
        for p in benchmark.committed_dir().glob("*.json")
        if not p.name.startswith(".")
    )
    if not cards:
        report(
            "WARN",
            "recorded scorecards",
            "none committed yet; GET /api/benchmark shows NOT AVAILABLE",
        )
    for path in cards:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            report(
                "FAIL", f"scorecard {path.name}", f"unreadable ({type(exc).__name__})"
            )
            continue
        record, problems = benchmark.verify_snapshot(
            raw, origin="committed", file_name=path.name, runs_root=runs_root
        )
        if record is None:
            report("FAIL", f"scorecard {path.name}", "; ".join(problems[:3]))
        else:
            report(
                "PASS",
                f"scorecard {path.name}",
                "hashes recompute; listed in a verified run",
            )


def check_store() -> None:
    """The prediction store the API will open: the FAULTLINE_PREDICTIONS_DB setting, as `scripts/demo_api.py` resolves
    it (FAULTLINE_DEMO_STORE, from `make demo-scratch`, wins and may not name the official store). Only the path and
    file size are printed; the store is not opened."""
    sys.path.insert(0, str(ROOT / "scripts"))
    from demo_api import resolve_store

    from config import DEFAULT_PREDICTIONS_DB, same_path

    in_use, refusal = resolve_store(os.environ)
    if in_use is None:
        report("FAIL", "prediction store", refusal or "could not resolve the prediction store")
        return
    state = f"{in_use.stat().st_size} bytes" if in_use.exists() else "not created yet"
    if same_path(in_use, DEFAULT_PREDICTIONS_DB):
        report(
            "WARN",
            "prediction store",
            f"{in_use} ({state}) is the OFFICIAL default store (FAULTLINE_PREDICTIONS_DB unset). Make the official "
            "recorded run first (scripts/record_runs.py), then demo with `make demo-scratch` or "
            "FAULTLINE_PREDICTIONS_DB=<scratch path>",
        )
    else:
        report(
            "PASS",
            "prediction store",
            f"scratch store {in_use} ({state}); official store {DEFAULT_PREDICTIONS_DB} untouched",
        )


# ---------------------------------------------------------------- tests


def run_tests() -> None:
    py = venv_python() or Path(sys.executable)
    proc = subprocess.run(
        [str(py), "-m", "pytest", "-q"],
        check=False,
        cwd=API_DIR,
        capture_output=True,
        text=True,
    )
    lines = [ln for ln in proc.stdout.strip().splitlines() if ln.strip()]
    summary = lines[-1] if lines else "no output"
    report("PASS" if proc.returncode == 0 else "FAIL", "pytest", summary)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--tests", action="store_true", help="also run the backend pytest suite"
    )
    args = parser.parse_args(argv)

    print(f"FAULTLINE preflight ({ROOT})")
    check_python()
    check_node()
    check_web_build()
    if not check_api_deps():
        report(
            "FAIL",
            "api checks",
            "skipped: cases, sealed outcomes, recorded runs and store need the API deps",
        )
    else:
        sys.path.insert(0, str(API_DIR))
        from config import get_settings

        settings = get_settings()
        report("PASS", "data dir", str(settings.data_dir))
        check_ollama(settings.ollama_base_url, settings.ollama_model)
        check_cases_and_seals(settings.data_dir)
        check_recorded_runs()
        check_store()
    if args.tests:
        run_tests()
    else:
        report("WARN", "pytest", "not run (use `make preflight ARGS=--tests`)")

    counts = {s: sum(1 for r in results if r[0] == s) for s in ("PASS", "WARN", "FAIL")}
    verdict = "FAIL" if counts["FAIL"] else "PASS"
    print(
        f"preflight {verdict}: {counts['PASS']} pass, {counts['WARN']} warn, {counts['FAIL']} fail"
    )
    return 1 if counts["FAIL"] else 0


if __name__ == "__main__":
    sys.exit(main())
