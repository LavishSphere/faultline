# FAULTLINE developer targets. Run `make help` for a list.
.PHONY: help pull agent-start setup api web dev demo demo-api demo-web deploy-api test test-api check guard-test

API_DIR  := services/api
VENV     := $(API_DIR)/.venv
PYTHON   ?= python3
# Use the API venv if `make setup` has created it, otherwise whatever python3 is on PATH (CI installs deps globally).
API_PY   := $(if $(wildcard $(VENV)/bin/python),$(abspath $(VENV)/bin/python),$(PYTHON))
API_PORT ?= 8000
# Load .env (if present) into the environment of the API process without printing values.
LOAD_ENV := set -a; if [ -f "$(CURDIR)/.env" ]; then . "$(CURDIR)/.env"; fi; set +a;

help:                   ## list targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | sed -E 's/:.*## /\t/'

pull:                   ## safe "git pull": latest GitHub main, your work replayed on top. Run before ANY edits.
	@bash scripts/pull.sh
agent-start:            ## install git hooks + sync with GitHub + show role/tasks
	@bash scripts/agent-start.sh

setup:                  ## create services/api/.venv and install the API with dev extras (+ web deps if apps/web exists)
	@[ -x $(VENV)/bin/python ] || $(PYTHON) -m venv $(VENV)
	@$(VENV)/bin/python -m pip install --upgrade pip
	@cd $(API_DIR) && .venv/bin/python -m pip install -e ".[dev]"
	@if [ -f apps/web/package.json ]; then cd apps/web && npm install; else echo "no web app yet (apps/web)"; fi

api:                    ## run the FastAPI server with reload on http://localhost:8000 (override: API_PORT=...)
	@$(LOAD_ENV) cd $(API_DIR) && $(API_PY) -m uvicorn main:app --reload --host 127.0.0.1 --port $(API_PORT)

web:                    ## run the Next.js dev server (once apps/web exists)
	@if [ -f apps/web/package.json ]; then cd apps/web && npm run dev; else echo "no web app yet (apps/web)"; fi

dev:                    ## run api + web together (Ctrl-C stops both)
	@$(MAKE) -j2 api web

# Local demo mode (docs/DEPLOY.md): everything on 127.0.0.1, live replay against this laptop's Ollama,
# no admin token, no rate limit. Works with the internet off once `make setup` has run.
demo:                   ## local demo: API (FAULTLINE_MODE=local, live replay) + web on 127.0.0.1 (Ctrl-C stops both)
	@echo "FAULTLINE local demo  web: http://127.0.0.1:3000  api: http://127.0.0.1:$(API_PORT)"
	@$(MAKE) -j2 demo-api demo-web

demo-api:
	@$(LOAD_ENV) export FAULTLINE_MODE=local; \
	  ollama="$${OLLAMA_BASE_URL:-http://localhost:11434}"; \
	  curl -fsS --max-time 2 "$$ollama/api/tags" >/dev/null 2>&1 \
	    || echo "WARNING: Ollama not reachable at OLLAMA_BASE_URL: live replay will show MODEL_UNAVAILABLE (start it: ollama serve)"; \
	  cd $(API_DIR) && $(API_PY) -m uvicorn main:app --host 127.0.0.1 --port $(API_PORT)

demo-web:
	@if [ -f apps/web/package.json ]; then \
	  cd apps/web && NEXT_PUBLIC_API_BASE=http://127.0.0.1:$(API_PORT) NEXT_TELEMETRY_DISABLED=1 npm run dev -- --hostname 127.0.0.1 --port 3000; \
	else echo "no web app yet (apps/web)"; fi

deploy-api:             ## LEAD ONLY: deploy origin/main API to the server (SSH=<ssh-target> or env FAULTLINE_DEPLOY_SSH)
	@bash scripts/deploy-api.sh "$(SSH)"

test: guard-test test-api ## guardrail self-test + backend pytest

test-api:               ## backend pytest only
	@if [ -f $(API_DIR)/pyproject.toml ]; then cd $(API_DIR) && $(API_PY) -m pytest -q; else echo "no backend yet"; fi

check:                  ## web typecheck + lint
	@if [ -f apps/web/package.json ]; then cd apps/web && npm run typecheck && npm run lint; else echo "no web app yet"; fi

guard-test:             ## guardrail hook self-test
	@python3 scripts/test_guardrails.py
