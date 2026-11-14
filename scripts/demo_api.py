#!/usr/bin/env python3
"""Run the FAULTLINE API for a local demo (`make demo` / `make demo-scratch`, issue #57).

FAULTLINE_DEMO_STORE=<path> points the API's prediction store (and the reveal ledger in it) at a separate scratch
SQLite file, so stage runs and reveals never touch the official store that `scripts/record_runs.py` writes.
Unset, the API uses the official default store (services/api/var/predictions.sqlite3) and says so loudly.

How: the API resolves its store through `core.store.DEFAULT_DB_PATH` at call time (routes/replay.py,
routes/benchmark.py, routes/integrity.py, core/evaluator.py), so this launcher sets that module attribute before the
app is imported. `scripts/record_runs.py` never goes through this launcher, so the official run always uses the
official store. Follow-up: a first-class FAULTLINE_PREDICTIONS_DB setting in config.py/core/store.py.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

API_DIR = Path(__file__).resolve().parent.parent / "services" / "api"


def main() -> int:
    sys.path.insert(0, str(API_DIR))
    os.chdir(API_DIR)
    import uvicorn
    from core import store as store_module

    official = Path(store_module.DEFAULT_DB_PATH).resolve()
    override = os.environ.get("FAULTLINE_DEMO_STORE", "").strip()
    if override:
        scratch = Path(override).expanduser().resolve()
        if scratch == official:
            print(
                f"[demo] FAULTLINE_DEMO_STORE is the official store {official}; refusing.",
                file=sys.stderr,
            )
            return 2
        scratch.parent.mkdir(parents=True, exist_ok=True)
        store_module.DEFAULT_DB_PATH = scratch
        print(
            f"[demo] prediction store: SCRATCH {scratch} (official store {official} untouched)",
            flush=True,
        )
    else:
        print(
            f"[demo] WARNING prediction store: OFFICIAL {official}. Runs and reveals here count against the official "
            "ledger. For stage demos use `make demo-scratch`.",
            flush=True,
        )
    host = os.environ.get("API_HOST", "127.0.0.1")
    port = int(os.environ.get("API_PORT", "8000"))
    from main import app

    uvicorn.run(app, host=host, port=port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
