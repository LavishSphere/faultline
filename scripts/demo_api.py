#!/usr/bin/env python3
"""Run the FAULTLINE API for a local demo (`make demo` / `make demo-scratch`, issues #57, #130).

The API opens its prediction store (and the reveal ledger in it) at the FAULTLINE_PREDICTIONS_DB setting
(services/api/config.py); unset, that is the official store services/api/var/predictions.sqlite3 that
`scripts/record_runs.py` writes the official RECORDED RUN into.

FAULTLINE_DEMO_STORE=<path> (set by `make demo-scratch`) asks for a separate scratch store: this launcher refuses it
if it names the official store, otherwise exports it as FAULTLINE_PREDICTIONS_DB before the app is imported, so every
route, the evaluator's vault check and the computed-scorecards directory use the scratch file. With neither variable
set the API uses the official store and this launcher says so loudly. `scripts/record_runs.py` never goes through
this launcher, so the official run keeps using the official store unless FAULTLINE_PREDICTIONS_DB is set for it.
Whenever the store is not the official one, FAULTLINE_DEMO_STORE is left set for the app, so no scorecard it computes
or serves can be OFFICIAL (#155); the official result is the committed RECORDED RUN.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from pathlib import Path

API_DIR = Path(__file__).resolve().parent.parent / "services" / "api"


def resolve_store(environ: Mapping[str, str]) -> tuple[Path | None, str | None]:
    """(store path the demo API will use, None), or (None, why it refuses). Shared with scripts/preflight.py."""
    if str(API_DIR) not in sys.path:
        sys.path.insert(0, str(API_DIR))
    from config import DEFAULT_PREDICTIONS_DB, predictions_db_from_env, same_path

    override = environ.get("FAULTLINE_DEMO_STORE", "").strip()
    if not override:
        return predictions_db_from_env(environ), None
    scratch = Path(override).expanduser().absolute()
    if same_path(scratch, DEFAULT_PREDICTIONS_DB):
        return None, f"FAULTLINE_DEMO_STORE is the official store {DEFAULT_PREDICTIONS_DB}; refusing."
    return scratch, None


def main() -> int:
    sys.path.insert(0, str(API_DIR))
    os.chdir(API_DIR)
    path, refusal = resolve_store(os.environ)
    if path is None:
        print(f"[demo] {refusal}", file=sys.stderr)
        return 2
    os.environ["FAULTLINE_PREDICTIONS_DB"] = str(path)

    from config import DEFAULT_PREDICTIONS_DB, get_settings, same_path

    settings = get_settings()
    if not same_path(settings.predictions_db, path):  # the setting is what the app reads; never start on another
        print(f"[demo] FAULTLINE_PREDICTIONS_DB resolves to {settings.predictions_db}, not {path}; refusing.")
        return 2
    if settings.predictions_db_is_official:
        print(
            f"[demo] WARNING prediction store: OFFICIAL {settings.predictions_db}. Runs and reveals here count "
            "against the official ledger. For stage demos use `make demo-scratch`.",
            flush=True,
        )
    else:
        # Any scratch store this launcher serves is a demo scratch store (#155): FAULTLINE_DEMO_STORE set means no
        # scorecard computed or served by this process is OFFICIAL (core/evaluator.py, routes/benchmark.py).
        os.environ["FAULTLINE_DEMO_STORE"] = str(settings.predictions_db)
        settings.predictions_db.parent.mkdir(parents=True, exist_ok=True)
        print(
            f"[demo] prediction store: SCRATCH {settings.predictions_db} "
            f"(official store {DEFAULT_PREDICTIONS_DB} untouched)",
            flush=True,
        )
    import uvicorn

    host = os.environ.get("API_HOST", "127.0.0.1")
    port = int(os.environ.get("API_PORT", "8000"))
    from main import app

    uvicorn.run(app, host=host, port=port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
