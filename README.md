# FAULTLINE

**Test the decision before you live with it.** A time-aware decision-intelligence and financial stress-testing platform
with a sealed historical Blind Replay, a deterministic business simulator + MILP optimizer, and honest forecast scoring.

> Status: hackathon MVP under construction.

- Product spec: [docs/SPEC.md](docs/SPEC.md)
- Math model: [docs/MATH_MODEL.md](docs/MATH_MODEL.md)
- Team workflow: [docs/WORKFLOW.md](docs/WORKFLOW.md) · Partner guide: [docs/PARTNER_GUIDE.md](docs/PARTNER_GUIDE.md)

## Run locally

Requires Python 3.11+ (CI uses 3.12), Node.js 22 for the web app (CI uses 22; `apps/web/.nvmrc`), and, for Blind
Replay inference, [Ollama](https://ollama.com) running locally.
Everything else is optional: with no Ollama and no API keys the API still starts and `/api/health` says what is missing.

```bash
make setup                      # creates services/api/.venv, runs pip install -e ".[dev]", then npm install in apps/web
cp .env.example .env            # optional; edit values (never commit .env)
ollama pull llama3.1:8b         # optional; the replay model checked by /api/health
make api                        # FastAPI with reload on http://localhost:8000
curl -s http://localhost:8000/api/health
make test                       # guardrail self-test + backend pytest
make dev                        # API on :8000 and web app on http://localhost:3000 together (Ctrl-C stops both)
```

### Without `make` (e.g. Git Bash on Windows, which has no `make`)

The venv's Python is `.venv/bin/python` on macOS/Linux and `.venv/Scripts/python` on Windows. On Windows, create the
venv with `python`, not `python3` (in a fresh Git Bash `python3` is often the Microsoft Store stub).

```bash
cd services/api
python3 -m venv .venv                                          # Windows: python -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"                    # Windows: .venv/Scripts/python -m pip install -e ".[dev]"
.venv/bin/python -m pytest -q                                  # Windows: .venv/Scripts/python -m pytest -q
.venv/bin/python -m uvicorn main:app --reload --port 8000      # Windows: .venv/Scripts/python -m uvicorn main:app --reload --port 8000
```

On Windows without admin rights or Developer Mode, a few backend tests are **skipped** with the reason
"OS refused to create a symlink": Windows does not let a normal user create symlinks. They run on macOS/Linux and in CI.

The web app, in a second terminal (Node.js 22 on `PATH`), from the repo root:

```bash
cd apps/web
npm ci
npm run dev                     # http://localhost:3000 (calls the API on :8000)
npm run typecheck && npm run lint && npm test
```

The Playwright smoke test is described in [apps/web/README.md](apps/web/README.md) (`npm run e2e`).

**Stopping the servers.** Press Ctrl-C in each terminal. On Windows, if port 3000 (or 8000) is still busy after a
terminal was closed, an orphaned `node.exe` (or `python.exe`) still holds it. Find its PID (last column) and stop it
with its child processes:

```bash
netstat -ano | grep ":3000 .*LISTENING"
taskkill //F //T //PID <pid>    # Git Bash needs the doubled slashes; in PowerShell or cmd: taskkill /F /T /PID <pid>
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
