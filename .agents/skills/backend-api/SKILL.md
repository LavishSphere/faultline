---
name: backend-api
description: Conventions for the FAULTLINE Python backend - FastAPI app layout, Pydantic v2 models, SQLite persistence, API contract (/api/cases, /evidence, /replay/run, /replay/{id}/reveal, /simulate, /optimize, /benchmark, /vc-lenses, /health), error handling, Makefile and preflight, pytest setup. Use for work in services/api/ (outside the finance/replay/market cores), the Makefile, README run instructions, or .env.example.
---

# Backend API (SPEC §8)

- Python ≥ 3.11, a venv at `services/api/.venv`, deps in `services/api/pyproject.toml`: fastapi, uvicorn, pydantic>=2, numpy, scipy, networkx, httpx, pytest.
- `main.py` mounts routers from `routes/`; CORS only for the local web origin. Every response model is explicit (`response_model=`).
- Pre-reveal routes use outcome-free response models (see `replay-integrity`). `/api/health` reports model readiness
  (`ollama` reachable? model tag present?), data manifest hash, and which optional keys are configured (booleans only, never values).
- Missing optional keys (`ANTHROPIC_API_KEY`, `TAVILY_API_KEY`) → feature disabled with a clear message; the app still runs.
- SQLite file under `services/api/var/` (git-ignored); fixtures under `data/` are versioned.
- Root `Makefile` targets: `setup`, `dev` (api + web), `api`, `web`, `test`, `check` (tsc + lint), `preflight`
  (python/node versions, ollama reachable, fixtures validate, tests pass) and `validate-fixtures`.
- Errors: typed `HTTPException` with machine-readable `code` (`MODEL_UNAVAILABLE`, `NO_FEASIBLE_PLAN`, `NOT_REVEALABLE`, `INSUFFICIENT_DATA`).
- Tests use FastAPI `TestClient`, no network, and run in < 30 s.
