# FAULTLINE

**Test the decision before you live with it.** A time-aware decision-intelligence and financial stress-testing platform
with a sealed historical Blind Replay, a deterministic business simulator + MILP optimizer, and honest forecast scoring.

> Status: hackathon MVP under construction.

- Product spec: [docs/SPEC.md](docs/SPEC.md)
- Math model: [docs/MATH_MODEL.md](docs/MATH_MODEL.md)
- Team workflow: [docs/WORKFLOW.md](docs/WORKFLOW.md) · Partner guide: [docs/PARTNER_GUIDE.md](docs/PARTNER_GUIDE.md)

## Run locally

Requires Python 3.11+ (CI uses 3.12) and, for Blind Replay inference, [Ollama](https://ollama.com) running locally.
Everything else is optional: with no Ollama and no API keys the API still starts and `/api/health` says what is missing.

```bash
make setup                      # creates services/api/.venv and runs: pip install -e ".[dev]"
cp .env.example .env            # optional; edit values (never commit .env)
ollama pull llama3.1:8b         # optional; the replay model checked by /api/health
make api                        # FastAPI with reload on http://localhost:8000
curl -s http://localhost:8000/api/health
make test                       # guardrail self-test + backend pytest
```

`make dev` runs the API and the web app together once `apps/web` exists. Without `make`:

```bash
cd services/api
python3 -m venv .venv && .venv/bin/python -m pip install -e ".[dev]"
.venv/bin/python -m pytest -q
.venv/bin/python -m uvicorn main:app --reload --port 8000
```

Interactive API docs: http://localhost:8000/docs

## Working with Claude Code
Rules for every agent: [AGENTS.md](AGENTS.md). First command of every session: `bash scripts/agent-start.sh`
(installs git hooks, syncs with GitHub, shows your role and tasks). Skills live in `.agents/skills/`.
In Claude Code: `/sync`, `/start-task`, `/ship-pr` (everyone) · `/delegate`, `/review-pr`, `/sprint` (leads).
Guardrail self-test: `make guard-test`.
