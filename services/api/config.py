"""Runtime configuration read from environment variables (documented in /.env.example).

Settings are read on each call (no caching) so tests can monkeypatch the environment.
Secret values are never stored here: only whether each optional key is set.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

API_DIR = Path(__file__).resolve().parent

DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"
DEFAULT_OLLAMA_MODEL = "llama3.1:8b"
DEFAULT_WEB_ORIGIN = "http://localhost:3000"


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
    )
