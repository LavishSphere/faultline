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

# LIVE EXPLORE chat (routes/explore_chat.py). Hosted-model keys are read by the chat adapters at call time and never
# kept here; Settings only says whether each is set.
CHAT_PROVIDERS = ("openrouter", "openai", "anthropic")  # also the display order of the catalogue
CHAT_KEY_ENV = {"openrouter": "OPENROUTER_API_KEY", "openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}
DEFAULT_CHAT_PER_IP = 10  # chat turns per client IP per CHAT_WINDOW_S
CHAT_WINDOW_S = 600
DEFAULT_CHAT_CONCURRENCY = 4
DEFAULT_CHAT_DAILY_BUDGET_USD = 25.0  # in-process spend ceiling per UTC day; non-admin turns stop with 503 BUDGET
# Chat web_search (Tavily credits), non-admin callers only, per UTC day, in process memory. 0 = no web search.
DEFAULT_CHAT_WEB_PER_IP_DAY = 30
DEFAULT_CHAT_WEB_DAILY = 500
DEFAULT_CHAT_MAX_PRICE_PER_MTOK = 20.0  # USD per million OUTPUT tokens; dearer models leave the public catalogue
# OpenAI and Claude models are called only through their native APIs (lead rule): OpenRouter copies are never offered.
NATIVE_ONLY_PREFIXES = ("openai/", "anthropic/")
_CHAT_MODEL_ENTRY = re.compile(r"^(openrouter|openai|anthropic):([A-Za-z0-9._:/@-]{1,120})$")


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
    # LIVE EXPLORE chat (#187). Booleans only for keys.
    openrouter_api_key_set: bool = False
    openai_api_key_set: bool = False
    chat_models_pinned: tuple[tuple[str, str], ...] | None = None  # FAULTLINE_CHAT_MODELS; None = dynamic catalogue
    chat_per_ip: int = DEFAULT_CHAT_PER_IP  # turns per CHAT_WINDOW_S; 0 = off (local mode only)
    chat_concurrency: int = DEFAULT_CHAT_CONCURRENCY
    public_chat: bool = False  # FAULTLINE_PUBLIC_CHAT=1: POST /api/explore/chat open to visitors in public mode
    chat_max_price_per_mtok: float = DEFAULT_CHAT_MAX_PRICE_PER_MTOK
    chat_daily_budget_usd: float = DEFAULT_CHAT_DAILY_BUDGET_USD
    chat_web_per_ip_day: int = DEFAULT_CHAT_WEB_PER_IP_DAY  # web_search calls per client IP per UTC day
    chat_web_daily: int = DEFAULT_CHAT_WEB_DAILY  # web_search calls per UTC day, all non-admin callers together

    def chat_key_set(self, provider: str) -> bool:
        return {"openrouter": self.openrouter_api_key_set, "openai": self.openai_api_key_set,
                "anthropic": self.anthropic_api_key_set}.get(provider, False)

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


def public_chat_enabled() -> bool:
    """FAULTLINE_PUBLIC_CHAT=1 exactly (anything else, including "true", keeps the chat admin-only in public mode)."""
    return os.environ.get("FAULTLINE_PUBLIC_CHAT", "").strip() == "1"


def _chat_models_pinned() -> tuple[tuple[str, str], ...] | None:
    raw = os.environ.get("FAULTLINE_CHAT_MODELS", "").strip()
    if not raw:
        return None
    out: list[tuple[str, str]] = []
    for entry in (e.strip() for e in raw.split(",")):
        if not entry:
            continue
        match = _CHAT_MODEL_ENTRY.fullmatch(entry)
        if not match:
            raise ConfigError(
                f"FAULTLINE_CHAT_MODELS entry {entry!r} is not provider:model_id with provider one of {CHAT_PROVIDERS}."
            )
        if match.group(1) == "openrouter" and (match.group(2).startswith("~") or
                                               match.group(2).lstrip("~").lower().startswith(NATIVE_ONLY_PREFIXES)):
            raise ConfigError(
                f"FAULTLINE_CHAT_MODELS entry {entry!r}: OpenAI and Anthropic models go through their native APIs "
                "(openai:<model> / anthropic:<model>), never through OpenRouter."
            )
        out.append((match.group(1), match.group(2)))
    if not out:
        return None
    # Display order: OpenRouter, then OpenAI, then Anthropic (stable within a provider); duplicates dropped.
    unique = list(dict.fromkeys(out))
    return tuple(sorted(unique, key=lambda pm: CHAT_PROVIDERS.index(pm[0])))


def _chat_per_ip(mode: Mode) -> int:
    value = _non_negative_int("FAULTLINE_CHAT_PER_IP", DEFAULT_CHAT_PER_IP)
    if value == 0 and mode == "public":
        raise ConfigError("FAULTLINE_CHAT_PER_IP=0 would switch the chat's per-IP limit off, which public mode "
                          f"does not allow. Leave it empty for the default ({DEFAULT_CHAT_PER_IP} per 10 minutes).")
    return value


def _positive_usd(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        value = -1.0
    if not (value > 0 and value < 1e6):
        raise ConfigError(f"{name} must be a positive number of USD, got {raw!r}.")
    return value


def _chat_max_price() -> float:
    return _positive_usd("FAULTLINE_CHAT_MAX_PRICE_PER_MTOK", DEFAULT_CHAT_MAX_PRICE_PER_MTOK)


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
        openrouter_api_key_set=_is_set("OPENROUTER_API_KEY"),
        openai_api_key_set=_is_set("OPENAI_API_KEY"),
        chat_models_pinned=_chat_models_pinned(),
        chat_per_ip=_chat_per_ip(mode),
        chat_concurrency=max(1, _non_negative_int("FAULTLINE_CHAT_CONCURRENCY", DEFAULT_CHAT_CONCURRENCY)),
        public_chat=public_chat_enabled(),
        chat_max_price_per_mtok=_chat_max_price(),
        chat_daily_budget_usd=_positive_usd("FAULTLINE_CHAT_DAILY_BUDGET_USD", DEFAULT_CHAT_DAILY_BUDGET_USD),
        chat_web_per_ip_day=_non_negative_int("FAULTLINE_CHAT_WEB_PER_IP_DAY", DEFAULT_CHAT_WEB_PER_IP_DAY),
        chat_web_daily=_non_negative_int("FAULTLINE_CHAT_WEB_DAILY", DEFAULT_CHAT_WEB_DAILY),
    )
