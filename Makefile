# FAULTLINE developer targets. Run `make help` for a list.
.PHONY: help pull agent-start setup setup-deps api web dev test test-api check guard-test preflight web-build demo demo-scratch demo-api demo-web deploy-api

API_DIR  := services/api
VENV     := $(API_DIR)/.venv
# On Windows `python3` is often the Microsoft Store stub, so the default there is `python`.
ifeq ($(OS),Windows_NT)
PYTHON   ?= python
else
PYTHON   ?= python3
endif
# Use the API venv if `make setup` has created it, otherwise $(PYTHON) from PATH (CI installs deps globally).
# Windows venvs put the interpreter in Scripts/python.exe instead of bin/python; bin/ wins if both exist.
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
	@[ -x $(VENV)/bin/python ] || [ -x $(VENV)/Scripts/python.exe ] || $(PYTHON) -m venv $(VENV)
	@$(MAKE) --no-print-directory setup-deps

# A fresh `make` re-reads this file, so VENV_PY now sees the venv that `setup` may have just created.
setup-deps:
	@[ -n "$(VENV_PY)" ] || { echo "no venv in $(VENV): run make setup"; exit 1; }
	@$(API_PY) -m pip install --upgrade pip
	@cd $(API_DIR) && $(API_PY) -m pip install -e ".[dev]"
	@if [ -f apps/web/package.json ]; then cd apps/web && npm install; else echo "no web app yet (apps/web)"; fi

api:                    ## run the FastAPI server with reload on http://localhost:8000 (override: API_PORT=...)
	@$(LOAD_ENV) cd $(API_DIR) && $(API_PY) -m uvicorn main:app --reload --host 127.0.0.1 --port $(API_PORT)

web:                    ## run the Next.js dev server on http://localhost:3000
	@if [ -f apps/web/package.json ]; then cd apps/web && npm run dev; else echo "no web app yet (apps/web)"; fi

dev:                    ## run api + web together (Ctrl-C stops both)
	@$(MAKE) -j2 api web

deploy-api:             ## LEAD ONLY: deploy origin/main API to the server (SSH=<ssh-target> or env FAULTLINE_DEPLOY_SSH)
	@bash scripts/deploy-api.sh "$(SSH)"

test: guard-test test-api ## guardrail self-test + backend pytest

test-api:               ## backend pytest only
	@if [ -f $(API_DIR)/pyproject.toml ]; then cd $(API_DIR) && $(API_PY) -m pytest -q; else echo "no backend yet"; fi

check:                  ## web typecheck + lint
	@if [ -f apps/web/package.json ]; then cd apps/web && npm run typecheck && npm run lint; else echo "no web app yet"; fi

guard-test:             ## guardrail hook self-test
	@$(PYTHON) scripts/test_guardrails.py

preflight:              ## release preflight: PASS/WARN/FAIL per check (ARGS=--tests also runs pytest)
	@$(LOAD_ENV) $(API_PY) scripts/preflight.py $(ARGS)

web-build:              ## production build of apps/web (served by `make demo`)
	@cd apps/web && NEXT_PUBLIC_API_BASE=http://localhost:$(API_PORT) npm run build

# Scratch prediction store for stage demos (lead policy, #57). The official store is only for scripts/record_runs.py.
# scripts/demo_api.py refuses FAULTLINE_DEMO_STORE if it names the official store, else exports it as the
# FAULTLINE_PREDICTIONS_DB setting (#130) that every route, the evaluator and the computed-scorecards dir read.
SCRATCH_STORE ?= $(abspath $(API_DIR))/var/scratch/predictions.sqlite3

demo:                   ## API + web against local Ollama (store = FAULTLINE_PREDICTIONS_DB, default official; FAULTLINE_DEMO_STORE=<path> for scratch)
	@$(MAKE) -j2 demo-api demo-web

demo-scratch:           ## same as demo, but on a separate scratch prediction store (use this on stage)
	@FAULTLINE_DEMO_STORE=$(SCRATCH_STORE) $(MAKE) -j2 demo-api demo-web

demo-api:
	@$(LOAD_ENV) FAULTLINE_MODE=local API_PORT=$(API_PORT) $(API_PY) scripts/demo_api.py

demo-web:
	@if [ -f apps/web/.next/BUILD_ID ]; then cd apps/web && npx next start -p 3000; \
	 else echo "[demo] no web build (make web-build); using next dev"; cd apps/web && NEXT_PUBLIC_API_BASE=http://localhost:$(API_PORT) npm run dev; fi
