# Backend/web targets are filled in by the backend-engineer as the app is built.
.PHONY: pull agent-start test check guard-test
pull:                   ## safe "git pull": latest GitHub main, your work replayed on top. Run before ANY edits.
	@bash scripts/pull.sh
agent-start:            ## install git hooks + sync with GitHub + show role/tasks
	@bash scripts/agent-start.sh
test: guard-test
	@if [ -f services/api/pyproject.toml ]; then cd services/api && python -m pytest -q; else echo "no backend yet"; fi
check:
	@if [ -f apps/web/package.json ]; then cd apps/web && npm run typecheck && npm run lint; else echo "no web app yet"; fi
guard-test:
	@python3 scripts/test_guardrails.py
