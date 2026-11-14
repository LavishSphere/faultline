"""Runtime configuration read from environment variables (documented in /.env.example and deploy/.env.example).

Settings are read on each call (no caching) so tests can monkeypatch the environment.
Secret values are never stored here: only whether each optional key is set. The admin token is compared
in `admin_token_matches` and never kept on `Settings`.

Modes (docs/DEPLOY.md):
- `local` (default for `make api` / `make demo`): live replay enabled, CORS also allows the localhost web app,
  no rate limit.
- `public` (baked into the deploy image): model inference (`/api/replay/run`) requires FAULTLINE_ADMIN_TOKEN,
  CORS allows only https origins, per-IP rate limiting is on.
"""

from __future__ import annotations

import hmac
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

API_DIR = Path(__file__).resolve().parent

DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"
DEFAULT_OLLAMA_MODEL = "llama3.1:8b"
DEFAULT_WEB_ORIGIN = "http://localhost:3000"
# The OFFICIAL prediction store (issue #130): scripts/record_runs.py writes the official RECORDED RUN here unless
# FAULTLINE_PREDICTIONS_DB says otherwise. Stage demos point FAULTLINE_PREDICTIONS_DB at a scratch file instead.
DEFAULT_PREDICTIONS_DB = API_DIR / "var" / "predictions.sqlite3"
LOCAL_WEB_ORIGINS = (DEFAULT_WEB_ORIGIN, "http://127.0.0.1:3000")
# The public web origin. Overridden by FAULTLINE_PUBLIC_ORIGIN (one name for the site, see docs/DEPLOY.md).
DEFAULT_PUBLIC_ORIGIN = "https://faultline.khayrul.com"

Mode = Literal["public", "local"]
MODES: tuple[Mode, ...] = ("public", "local")
DEFAULT_MODE: Mode = "local"

DEFAULT_PUBLIC_RATE_LIMIT_PER_MIN = 120
DEFAULT_MAX_BODY_BYTES = 64 * 1024
# Shorter tokens never match (fail closed); in public mode a set-but-short token is a ConfigError.
# Generate with `openssl rand -hex 32`.
MIN_ADMIN_TOKEN_LEN = 32


class ConfigError(ValueError):
    """A deployment variable has an unusable value. Raised at startup so misconfiguration is loud."""


def _is_set(name: str) -> bool:
    return bool(os.environ.get(name, "").strip())


@dataclass(frozen=True)
class Settings:
    ollama_base_url: str
    ollama_model: str
    anthropic_api_key_set: bool
    tavily_api_key_set: bool
    data_dir: Path
    mode: Mode
    cors_origins: tuple[str, ...]
    admin_token_configured: bool
    rate_limit_per_min: int
    max_body_bytes: int
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


def _mode() -> Mode:
    raw = os.environ.get("FAULTLINE_MODE", "").strip().lower() or DEFAULT_MODE
    if raw not in MODES:
        raise ConfigError(f"FAULTLINE_MODE must be one of {MODES}, got {raw!r}.")
    return raw  # type: ignore[return-value]


def _origin(value: str, *, require_https: bool) -> str:
    """Normalise one CORS origin (`scheme://host[:port]`, no path). Wildcards and `null` are refused.

    Lower-cased, because browsers send the Origin scheme and host in lower case and CORS matching is exact.
    """
    candidate = value.strip().rstrip("/").lower()
    parts = urlsplit(candidate)
    allowed_schemes = ("https",) if require_https else ("https", "http")
    try:
        parts.port  # noqa: B018 - raises ValueError for a non-numeric or out-of-range port
    except ValueError:
        port_ok = False
    else:
        port_ok = True
    if (
        not port_ok
        or candidate in ("*", "null")
        or parts.scheme not in allowed_schemes
        or not parts.hostname
        or parts.path
        or parts.query
        or parts.fragment
        or parts.username
        or "*" in candidate
    ):
        need = "https://host[:port]" if require_https else "http(s)://host[:port]"
        raise ConfigError(f"CORS origin {value!r} is not a plain {need} origin.")
    return candidate


def _cors_origins(mode: Mode) -> tuple[str, ...]:
    public = mode == "public"
    configured = os.environ.get("FAULTLINE_CORS_ORIGINS", "").strip()
    if configured:
        entries = [e for e in configured.split(",") if e.strip()]
    else:
        entries = [os.environ.get("FAULTLINE_PUBLIC_ORIGIN", "").strip() or DEFAULT_PUBLIC_ORIGIN]
    origins = [_origin(e, require_https=public) for e in entries]
    if not public:
        legacy = os.environ.get("FAULTLINE_WEB_ORIGIN", "").strip()
        if legacy:
            origins.append(_origin(legacy, require_https=False))
        origins.extend(LOCAL_WEB_ORIGINS)
    return tuple(dict.fromkeys(origins))  # de-duplicate, keep order


def _non_negative_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    if not raw.isdigit():
        raise ConfigError(f"{name} must be a non-negative integer, got {raw!r}.")
    return int(raw)


def _admin_token() -> str:
    token = os.environ.get("FAULTLINE_ADMIN_TOKEN", "").strip()
    return token if len(token) >= MIN_ADMIN_TOKEN_LEN else ""


def _check_admin_token(mode: Mode) -> None:
    """A set-but-weak token in public mode is a mistake, not "inference off": refuse to start."""
    token = os.environ.get("FAULTLINE_ADMIN_TOKEN", "").strip()
    if mode == "public" and token and len(token) < MIN_ADMIN_TOKEN_LEN:
        raise ConfigError(
            f"FAULTLINE_ADMIN_TOKEN is set but shorter than {MIN_ADMIN_TOKEN_LEN} characters "
            "(generate one with `openssl rand -hex 32`, or leave it empty to keep inference disabled)."
        )


def admin_token_matches(presented: str | None) -> bool:
    """Constant-time check of a presented admin token. False when no (strong enough) token is configured."""
    expected = _admin_token()
    if not expected or not presented:
        return False
    return hmac.compare_digest(presented.encode("utf-8"), expected.encode("utf-8"))


def get_settings() -> Settings:
    data_dir = os.environ.get("FAULTLINE_DATA_DIR", "").strip()
    mode = _mode()
    _check_admin_token(mode)
    default_rate = DEFAULT_PUBLIC_RATE_LIMIT_PER_MIN if mode == "public" else 0
    max_body_bytes = _non_negative_int("FAULTLINE_MAX_BODY_BYTES", DEFAULT_MAX_BODY_BYTES)
    if max_body_bytes == 0:
        raise ConfigError("FAULTLINE_MAX_BODY_BYTES must be at least 1.")
    return Settings(
        ollama_base_url=(os.environ.get("OLLAMA_BASE_URL", "").strip() or DEFAULT_OLLAMA_BASE_URL).rstrip("/"),
        ollama_model=os.environ.get("FAULTLINE_OLLAMA_MODEL", "").strip() or DEFAULT_OLLAMA_MODEL,
        anthropic_api_key_set=_is_set("ANTHROPIC_API_KEY"),
        tavily_api_key_set=_is_set("TAVILY_API_KEY"),
        data_dir=Path(data_dir).expanduser() if data_dir else API_DIR / "data",
        mode=mode,
        cors_origins=_cors_origins(mode),
        admin_token_configured=bool(_admin_token()),
        rate_limit_per_min=_non_negative_int("FAULTLINE_RATE_LIMIT_PER_MIN", default_rate),
        max_body_bytes=max_body_bytes,
        predictions_db=predictions_db_from_env(),
        demo_store_set=_is_set("FAULTLINE_DEMO_STORE"),
    )
