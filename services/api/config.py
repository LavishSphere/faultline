"""Runtime configuration read from environment variables (documented in /.env.example and deploy/.env.example).

Settings are read on each call (no caching) so tests can monkeypatch the environment.
Secret values are never stored here: only whether each optional key is set. The admin token is compared
in `admin_token_matches` and never kept on `Settings`.

Modes (docs/DEPLOY.md):
- `local` (default for `make api` / `make demo`): live replay enabled, CORS also allows the localhost web app,
  no rate limit.
- `public` (baked into the deploy image): model inference (`/api/replay/run`) requires FAULTLINE_ADMIN_TOKEN,
  CORS allows only https origins, per-IP rate limiting is on and cannot be switched off (0 is a ConfigError).
"""

from __future__ import annotations

import hmac
import os
import re
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

# 600/min per client IP (10/s, burst 600). CASCADE sends POST /api/simulate plus POST /api/optimize on every
# slider change, and judges in one room usually share one NAT address, so 120/min ran out mid-demo (docs/DEPLOY.md).
DEFAULT_PUBLIC_RATE_LIMIT_PER_MIN = 600
DEFAULT_MAX_BODY_BYTES = 64 * 1024
# Shorter tokens never match (fail closed); in public mode a set-but-short token is a ConfigError.
# Generate with `openssl rand -hex 32`.
MIN_ADMIN_TOKEN_LEN = 32
# Public mode also requires exactly the `openssl rand -hex 32` shape: 64 lower-case hex characters. Anything else
# (a passphrase, a pasted-with-quotes value, upper case) is a ConfigError at startup and never matches.
PUBLIC_ADMIN_TOKEN_PATTERN = re.compile(r"^[0-9a-f]{64}$")


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
    """The configured token if it is strong enough to compare against, else "" (nothing ever matches)."""
    token = os.environ.get("FAULTLINE_ADMIN_TOKEN", "").strip()
    if len(token) < MIN_ADMIN_TOKEN_LEN:
        return ""
    public = os.environ.get("FAULTLINE_MODE", "").strip().lower() == "public"
    if public and not PUBLIC_ADMIN_TOKEN_PATTERN.fullmatch(token):
        return ""  # fail closed even if a caller skipped get_settings()
    return token


def _check_admin_token(mode: Mode) -> None:
    """A set-but-weak token in public mode is a mistake, not "inference off": refuse to start."""
    token = os.environ.get("FAULTLINE_ADMIN_TOKEN", "").strip()
    if mode != "public" or not token:
        return
    if len(token) < MIN_ADMIN_TOKEN_LEN:
        raise ConfigError(
            f"FAULTLINE_ADMIN_TOKEN is set but shorter than {MIN_ADMIN_TOKEN_LEN} characters "
            "(generate one with `openssl rand -hex 32`, or leave it empty to keep inference disabled)."
        )
    if not PUBLIC_ADMIN_TOKEN_PATTERN.fullmatch(token):
        raise ConfigError(
            "FAULTLINE_ADMIN_TOKEN must be 64 lower-case hex characters in public mode "
            "(the output of `openssl rand -hex 32`), or empty to keep inference disabled."
        )


def _rate_limit_per_min(mode: Mode) -> int:
    """Public: default DEFAULT_PUBLIC_RATE_LIMIT_PER_MIN, and 0 ("off") is refused (fail closed). Local: off."""
    if mode != "public":
        return _non_negative_int("FAULTLINE_RATE_LIMIT_PER_MIN", 0)
    value = _non_negative_int("FAULTLINE_RATE_LIMIT_PER_MIN", DEFAULT_PUBLIC_RATE_LIMIT_PER_MIN)
    if value == 0:
        raise ConfigError(
            "FAULTLINE_RATE_LIMIT_PER_MIN=0 would switch the per-IP rate limit off, which public mode does not allow. "
            f"Leave it empty for the default ({DEFAULT_PUBLIC_RATE_LIMIT_PER_MIN}/min) or set a positive number."
        )
    return value


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
        rate_limit_per_min=_rate_limit_per_min(mode),
        max_body_bytes=max_body_bytes,
        predictions_db=predictions_db_from_env(),
        demo_store_set=_is_set("FAULTLINE_DEMO_STORE"),
    )
