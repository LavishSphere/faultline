"""GET /api/health: runtime status and model readiness. Must answer 200 even when Ollama is down.

Two shapes (docs/DEPLOY.md "Health"):
- local mode: ``HealthResponse`` (installed model tags, required model, notices, manifest hash), unchanged;
- public mode: ``PublicHealthResponse``, booleans only (``model_ready``, ``ollama_reachable``,
  ``tavily_configured``): no model list, no model tag, no error text, no key details.
``model_ready`` means the same in both, so the web app can read it whatever the mode.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Annotated, Literal

import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from agents.explore_web_search import provider_from_env as web_search_provider
from config import Settings, get_settings
from models import HealthResponse, OllamaStatus, OptionalKeys

router = APIRouter(tags=["health"])


class PublicHealthResponse(BaseModel):
    """`/api/health` in public mode (docs/DEPLOY.md): readiness booleans only.

    No model list, model tag, error text, key details, data paths or notices: the public server does not tell
    anonymous callers what it runs. `model_ready` has the same meaning as in HealthResponse (the web app reads it in
    both modes).
    """

    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"] = Field(description="The API process is up. Model readiness is reported separately.")
    model_ready: bool = Field(description="Ollama reachable AND the configured replay model is installed.")
    ollama_reachable: bool = Field(description="Ollama reachable at OLLAMA_BASE_URL.")
    tavily_configured: bool = Field(description="TAVILY_API_KEY is set (Live Explore still needs the admin token).")
    web_search_provider: str | None = Field(
        default=None, description="Backend name of the live chat's web_search tool (FAULTLINE_WEB_SEARCH_PROVIDER); "
        "null = web_search is off.")


OLLAMA_PROBE_TIMEOUT_S = 1.5


@dataclass
class OllamaProbe:
    reachable: bool
    models: list[str] = field(default_factory=list)
    error: str | None = None


def get_ollama_transport() -> httpx.AsyncBaseTransport | None:
    """Dependency hook: None = real network transport. Tests override this with httpx.MockTransport."""
    return None


async def probe_ollama(base_url: str, transport: httpx.AsyncBaseTransport | None = None) -> OllamaProbe:
    """List installed models via Ollama's GET /api/tags. Never raises."""
    try:
        async with httpx.AsyncClient(base_url=base_url, timeout=OLLAMA_PROBE_TIMEOUT_S, transport=transport) as client:
            resp = await client.get("/api/tags")
        resp.raise_for_status()
        payload = resp.json()
        entries = payload.get("models") if isinstance(payload, dict) else None
        if not isinstance(entries, list):
            return OllamaProbe(reachable=False, error="Unexpected response from OLLAMA_BASE_URL /api/tags.")
        names = sorted({e["name"] for e in entries if isinstance(e, dict) and isinstance(e.get("name"), str)})
        return OllamaProbe(reachable=True, models=names)
    # httpx.InvalidURL (malformed OLLAMA_BASE_URL) is not an httpx.HTTPError, so it is listed explicitly.
    except (httpx.HTTPError, httpx.InvalidURL, ValueError) as exc:
        # Report the error class only: the message can echo the configured URL (which may contain credentials).
        return OllamaProbe(reachable=False, error=f"Ollama not reachable at OLLAMA_BASE_URL ({type(exc).__name__}).")


def model_present(required: str, installed: list[str]) -> bool:
    """Ollama treats an untagged name as ':latest'."""
    wanted = {required} if ":" in required else {required, f"{required}:latest"}
    return any(name in wanted for name in installed)


def manifest_sha256(settings: Settings) -> str | None:
    path = settings.data_dir / "manifest.json"
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


@router.get("/health", response_model=HealthResponse | PublicHealthResponse)
async def health(
    settings: Annotated[Settings, Depends(get_settings)],
    transport: Annotated[httpx.AsyncBaseTransport | None, Depends(get_ollama_transport)],
) -> HealthResponse | PublicHealthResponse:
    probe = await probe_ollama(settings.ollama_base_url, transport)
    present = probe.reachable and model_present(settings.ollama_model, probe.models)
    if settings.mode == "public":
        return PublicHealthResponse(
            status="ok",
            model_ready=present,
            ollama_reachable=probe.reachable,
            tavily_configured=settings.tavily_api_key_set,
            web_search_provider=web_search_provider(),
        )
    manifest = manifest_sha256(settings)

    notices: list[str] = []
    if not probe.reachable:
        notices.append("Ollama is not reachable: Blind Replay inference is unavailable (MODEL_UNAVAILABLE).")
    elif not present:
        notices.append(
            f"Model {settings.ollama_model} is not installed in Ollama: run `ollama pull {settings.ollama_model}`."
        )
    if not settings.anthropic_api_key_set:
        notices.append("ANTHROPIC_API_KEY not set: hosted-model comparator is disabled.")
    if not settings.tavily_api_key_set:
        notices.append("TAVILY_API_KEY not set: Live Explore web search is disabled.")
    if manifest is None:
        notices.append("Data manifest NOT AVAILABLE (no manifest.json in FAULTLINE_DATA_DIR).")

    return HealthResponse(
        status="ok",
        ollama=probe.reachable,
        model_ready=present,
        ollama_status=OllamaStatus(
            reachable=probe.reachable,
            models=probe.models,
            required_model=settings.ollama_model,
            required_model_present=present,
            error=probe.error,
        ),
        optional_keys=OptionalKeys(
            anthropic_api_key=settings.anthropic_api_key_set,
            tavily_api_key=settings.tavily_api_key_set,
        ),
        data_dir_present=settings.data_dir.is_dir(),
        data_manifest_sha256=manifest,
        notices=notices,
        web_search_provider=web_search_provider(),
    )
