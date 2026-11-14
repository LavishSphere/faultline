"""Runtime configuration read from environment variables (documented in /.env.example).

Settings are read on each call (no caching) so tests can monkeypatch the environment.
Secret values are never stored here: only whether each optional key is set.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

API_DIR = Path(__file__).resolve().parent

DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"
DEFAULT_OLLAMA_MODEL = "llama3.1:8b"
DEFAULT_WEB_ORIGIN = "http://localhost:3000"
# The OFFICIAL prediction store (issue #130): scripts/record_runs.py writes the official RECORDED RUN here unless
# FAULTLINE_PREDICTIONS_DB says otherwise. Stage demos point FAULTLINE_PREDICTIONS_DB at a scratch file instead.
DEFAULT_PREDICTIONS_DB = API_DIR / "var" / "predictions.sqlite3"


def _is_set(name: str) -> bool:
    return bool(os.environ.get(name, "").strip())


@dataclass(frozen=True)
class Settings:
    ollama_base_url: str
    ollama_model: str
    anthropic_api_key_set: bool
    tavily_api_key_set: bool
    data_dir: Path
    web_origins: tuple[str, ...]
    # The ONE prediction store (and reveal ledger) every route, the evaluator's vault check and record_runs.py
    # open; computed scorecards live next to it. Absolute. Default: DEFAULT_PREDICTIONS_DB (the official store).
    predictions_db: Path
    # FAULTLINE_DEMO_STORE is set (scripts/demo_api.py, `make demo-scratch`): this process serves a demo scratch
    # store, so no scorecard computed or served from it may be OFFICIAL (#155). Presence only, read per call.
    demo_store_set: bool

    @property
    def predictions_db_is_official(self) -> bool:
        """True when the configured store is the default official store (same file, however spelled)."""
        return same_path(self.predictions_db, DEFAULT_PREDICTIONS_DB)


def same_path(a: Path | str, b: Path | str) -> bool:
    """Same file (or, if either does not exist yet, the same absolute path after resolving links)."""
    a, b = Path(a), Path(b)
    try:
        if a.exists() and b.exists():
            return os.path.samefile(a, b)
    except OSError:
        pass
    return os.path.normcase(str(a.resolve())) == os.path.normcase(str(b.resolve()))


def predictions_db_from_env(environ: Mapping[str, str] | None = None) -> Path:
    """FAULTLINE_PREDICTIONS_DB as an absolute path, or the official default when unset or blank."""
    raw = (os.environ if environ is None else environ).get("FAULTLINE_PREDICTIONS_DB", "").strip()
    return Path(raw).expanduser().absolute() if raw else DEFAULT_PREDICTIONS_DB


def get_settings() -> Settings:
    data_dir = os.environ.get("FAULTLINE_DATA_DIR", "").strip()
    origin = os.environ.get("FAULTLINE_WEB_ORIGIN", "").strip() or DEFAULT_WEB_ORIGIN
    origins = [origin]
    # localhost and 127.0.0.1 are the same local web app; allow both spellings of the default.
    if origin == DEFAULT_WEB_ORIGIN:
        origins.append("http://127.0.0.1:3000")
    return Settings(
        ollama_base_url=(os.environ.get("OLLAMA_BASE_URL", "").strip() or DEFAULT_OLLAMA_BASE_URL).rstrip("/"),
        ollama_model=os.environ.get("FAULTLINE_OLLAMA_MODEL", "").strip() or DEFAULT_OLLAMA_MODEL,
        anthropic_api_key_set=_is_set("ANTHROPIC_API_KEY"),
        tavily_api_key_set=_is_set("TAVILY_API_KEY"),
        data_dir=Path(data_dir).expanduser() if data_dir else API_DIR / "data",
        web_origins=tuple(origins),
        predictions_db=predictions_db_from_env(),
        demo_store_set=_is_set("FAULTLINE_DEMO_STORE"),
    )
