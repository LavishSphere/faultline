"""FAULTLINE API entry point. Run from services/api: `uvicorn main:app --reload`."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import get_settings
from errors import FaultlineError, faultline_error_handler
from routes import benchmark, cases, explore, health, integrity, replay, research, scenarios, simulate


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="FAULTLINE API",
        version="0.1.0",
        description="Time-aware decision intelligence: Blind Replay, deterministic simulation, honest scoring.",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.web_origins),
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )
    app.add_exception_handler(FaultlineError, faultline_error_handler)
    app.include_router(health.router, prefix="/api")
    app.include_router(simulate.router, prefix="/api")
    app.include_router(scenarios.router, prefix="/api")
    app.include_router(research.router, prefix="/api")
    app.include_router(cases.router, prefix="/api")
    app.include_router(replay.router, prefix="/api")
    app.include_router(integrity.router, prefix="/api")
    app.include_router(benchmark.router, prefix="/api")
    # LIVE EXPLORE (Tavily). Admin-gated inside the route in public mode; never used by the Blind Replay (#60).
    app.include_router(explore.router, prefix="/api")
    return app


app = create_app()
