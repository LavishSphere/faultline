# FAULTLINE developer targets. Run `make help` for a list.
.PHONY: help pull agent-start setup api web dev test test-api check guard-test preflight web-build demo demo-scratch demo-api demo-web

API_DIR  := services/api
VENV     := $(API_DIR)/.venv
PYTHON   ?= python3
# Use the API venv if `make setup` has created it, otherwise whatever python3 is on PATH (CI installs deps globally).
# Windows venvs put the interpreter in Scripts/ instead of bin/.
VENV_PY  := $(firstword $(wildcard $(VENV)/bin/python) $(wildcard $(VENV)/Scripts/python.exe))
API_PY   := $(if $(VENV_PY),$(abspath $(VENV_PY)),$(PYTHON))
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

test: guard-test test-api ## guardrail self-test + backend pytest

test-api:               ## backend pytest only
	@if [ -f $(API_DIR)/pyproject.toml ]; then cd $(API_DIR) && $(API_PY) -m pytest -q; else echo "no backend yet"; fi

check:                  ## web typecheck + lint
	@if [ -f apps/web/package.json ]; then cd apps/web && npm run typecheck && npm run lint; else echo "no web app yet"; fi

guard-test:             ## guardrail hook self-test
	@python3 scripts/test_guardrails.py

preflight:              ## release preflight: PASS/WARN/FAIL per check (ARGS=--tests also runs pytest)
	@$(LOAD_ENV) $(API_PY) scripts/preflight.py $(ARGS)

web-build:              ## production build of apps/web (served by `make demo`)
	@cd apps/web && NEXT_PUBLIC_API_BASE=http://localhost:$(API_PORT) npm run build

# Scratch prediction store for stage demos (lead policy, #57). The official store is only for scripts/record_runs.py.
SCRATCH_STORE ?= $(abspath $(API_DIR))/var/scratch/predictions.sqlite3

demo:                   ## API + web against local Ollama (official store; FAULTLINE_DEMO_STORE=<path> to override)
	@$(MAKE) -j2 demo-api demo-web

demo-scratch:           ## same as demo, but on a separate scratch prediction store (use this on stage)
	@FAULTLINE_DEMO_STORE=$(SCRATCH_STORE) $(MAKE) -j2 demo-api demo-web

demo-api:
	@$(LOAD_ENV) API_PORT=$(API_PORT) $(API_PY) scripts/demo_api.py

demo-web:
	@if [ -f apps/web/.next/BUILD_ID ]; then cd apps/web && npx next start -p 3000; \
	 else echo "[demo] no web build (make web-build); using next dev"; cd apps/web && NEXT_PUBLIC_API_BASE=http://localhost:$(API_PORT) npm run dev; fi
