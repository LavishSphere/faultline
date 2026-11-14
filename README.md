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

With `TAVILY_API_KEY` set, any website open in your browser can send requests to the local API (CORS stops it reading
the answers, not sending them), so it could spend your Tavily credits on Live Explore searches. Leave the key unset
when you are not using Live Explore.

## Release demo (clean clone)

Exact commands from a clean clone (macOS/Linux; on Windows run them from Git Bash, the venv's `Scripts/python.exe` is
picked up automatically):

```bash
git clone https://github.com/LavishSphere/faultline.git && cd faultline
make setup                      # services/api/.venv + pip install -e ".[dev]", then npm install in apps/web
ollama pull llama3.1:8b         # local replay model; without it replay shows MODEL_UNAVAILABLE (never a canned answer)
make web-build                  # production build of apps/web (optional; demo falls back to `next dev`)
make preflight                  # one PASS/WARN/FAIL line per check; exits 1 on any FAIL
make preflight ARGS=--tests     # same, plus the backend pytest suite
make demo-scratch               # API on :8000 + web on :3000, on a SCRATCH prediction store (use this on stage)
```

Open http://localhost:3000. `make demo` does the same on the **official** prediction store
(`services/api/var/predictions.sqlite3`) and prints a warning. Lead policy: the official RECORDED RUN is made with
`scripts/record_runs.py` before any stage demo, and every stage run or reveal uses the scratch store
(`services/api/var/scratch/predictions.sqlite3`, or any path via `FAULTLINE_DEMO_STORE=<path> make demo`).
`FAULTLINE_DEMO_STORE=<path> make preflight` confirms which store is in use. Release status and evidence:
[`docs/RELEASE_CHECKLIST.md`](docs/RELEASE_CHECKLIST.md).

## Working with Claude Code
Rules for every agent: [AGENTS.md](AGENTS.md). First command of every session: `bash scripts/agent-start.sh`
(installs git hooks, syncs with GitHub, shows your role and tasks). Skills live in `.agents/skills/`.
In Claude Code: `/sync`, `/start-task`, `/ship-pr` (everyone) · `/delegate`, `/review-pr`, `/sprint` (leads).
Guardrail self-test: `make guard-test`.
