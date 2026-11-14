# FAULTLINE on Windows: fresh-clone runbook (Git Bash)

Dry run for issue #107, done on Friday 2026-11-13 (evening, US Eastern) against `main` at `9b23331`
("replay: run/reveal routes + case evidence route (#44) (#76)").

- **Machine:** Windows 11 Home 10.0.26200, Git Bash, Python 3.12.10 (python.org installer, user-level), `gh` logged in.
  No `make`, no Node.js, no Ollama to start with. No administrator rights used.
- **Result:** API and web app both ran locally. Clone to both servers up: **about 13 min 45 s**
  (19:39:06 → 19:52:52), most of it `pip install` (2 min) and `npm ci` (5 min). Backend tests:
  1144 passed, 5 failed (Windows symlink privilege, see Snag 6), 7 skipped. Web typecheck, lint, unit test and the
  Playwright e2e smoke test (3/3) all passed, the e2e only after a Windows workaround (Snag 5).

## Since this run (main has moved)

Checked on 2026-11-14 against `main` at `38c595a`. The steps and timings below are unchanged; they record the
Friday run.
- REWIND, DECISION and REVEAL are now wired to the API (#65, #64), and `GET /api/benchmark` is served (#91).
- Follow-up 6 is done. The two parts that were still missing when the lead reviewed this have also merged since:
  `POST /api/optimize` with the live Protect payroll switch (#127, built on #69) and the real demo cases (#54).
- On current main, 11 backend tests create symlinks, so on a Windows laptop without symlink rights expect **11**
  WinError 1314 failures, not 5. I ran those four files on this machine: 11 failed, 207 passed. New ones are in
  `tests/test_explore_curate.py` (4) and `tests/test_routes_integrity.py` (2); the other 5 are the ones in Snag 6.
  The fix is task #122.

- Times below are wall-clock, from `time` or timestamps in the logs. Commands are the ones I typed in Git Bash.
  I worked in a scratch folder; below, `~/faultline-fresh` stands for "any new empty folder".

## Steps

### 1. Install Node.js without admin rights (≈ 35 s)

The root README never says Node.js is needed (Snag 2). `apps/web/package.json` has no `engines` field and there is
no `.nvmrc`; CI (`.github/workflows/ci.yml`) uses `node-version: "22"`, so I used the latest Node 22.

First attempt (Snag 1): `winget install --id OpenJS.NodeJS.LTS -e` asks for administrator (UAC) approval. The prompt was
cancelled: installer exit code 1602, winget exit code 12. What worked instead is the official portable zip, checksum
verified, nothing installed system-wide:

```bash
mkdir -p ~/node-dl && cd ~/node-dl
curl -sSfL -o SHASUMS256.txt https://nodejs.org/dist/latest-v22.x/SHASUMS256.txt
curl -sSfL -o node-v22.23.5-win-x64.zip https://nodejs.org/dist/latest-v22.x/node-v22.23.5-win-x64.zip   # 1.4 s
grep node-v22.23.5-win-x64.zip SHASUMS256.txt | sha256sum -c -
#   node-v22.23.5-win-x64.zip: OK
#   (sha256 4a191082e9706866830379d577d2cc8a50c776fcd9436a8d061b063ed0d9a0e3)
mkdir -p ~/node-portable && cd ~/node-portable
unzip -q ~/node-dl/node-v22.23.5-win-x64.zip                      # 31 s
export PATH="$HOME/node-portable/node-v22.23.5-win-x64:$PATH"     # needed in EVERY new Git Bash window
node -v    # v22.23.5
npm -v     # 10.9.9
```

The file name changes when a new 22.x comes out: copy the `win-x64.zip` name from `SHASUMS256.txt`.
To keep Node on PATH, add that `export` line to `~/.bashrc`.

### 2. Clone into a new folder (6.5 s)

```bash
mkdir -p ~/faultline-fresh && cd ~/faultline-fresh
gh repo clone LavishSphere/faultline
cd faultline
```

572 files checked out. This machine has `core.autocrlf=true`; the clone is still fine (see Snag 7).

### 3. README "Run locally": `make setup` (fails at once)

```bash
make setup
#   bash: make: command not found        (exit 127)
```

Git Bash has no `make` (Snag 3). I switched to the README's "Without make" block.

### 4. Create the API virtual environment (25 s)

```bash
cd services/api
python3 -m venv .venv
```

Worked. `python3` here is a shim for the python.org Python 3.12.10.

### 5. Install the API with dev extras (2 min 05 s)

The README line `.venv/bin/python -m pip install -e ".[dev]"` fails on Windows (Snag 4):

```
bash: .venv/bin/python: No such file or directory
```

On Windows the venv puts Python in `.venv/Scripts/`, not `.venv/bin/`. What worked:

```bash
.venv/Scripts/python -m pip install -e ".[dev]"
#   Successfully installed ... fastapi-0.162.7 ... scipy-1.18.1 ... uvicorn-0.54.0 ... faultline-api-0.1.0
```

pip printed an "a new release of pip is available" notice; harmless.

### 6. Optional `.env` (instant)

```bash
cd ../..                    # back to the repo root
cp .env.example .env        # optional; contains no secrets, git-ignored (.gitignore: **/.env)
```

No API keys are needed. I left `ANTHROPIC_API_KEY` and `TAVILY_API_KEY` empty.

### 7. Optional `ollama pull llama3.1:8b` (skipped)

Ollama is not installed on this laptop (`which ollama` finds nothing), so I skipped this optional step. As the README
says, everything else works without it: `/api/health` reports it, and the app shows LOCAL MODEL UNAVAILABLE (Snag 8).

### 8. Backend tests (2 min 05 s)

```bash
cd services/api
.venv/Scripts/python -m pytest -q
#   5 failed, 1144 passed, 7 skipped, 1 warning in 120.39s
```

All 5 failures are Windows symlink tests (Snag 6). The 7 skips are expected: missing market snapshots, demo cases not
merged yet (#20), and a real-Ollama test marked LOCAL ONLY.

Guardrail self-test (the other half of `make test`), from the repo root:

```bash
python3 scripts/test_guardrails.py
#   guardrails: 49/49 passed
```

### 9. Start the API (ready in a few seconds)

In its own Git Bash window (it keeps running):

```bash
cd services/api
.venv/Scripts/python -m uvicorn main:app --reload --port 8000
#   Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
#   Application startup complete.
```

Check it from another window:

```bash
curl -s http://localhost:8000/api/health
```

HTTP 200 after **3.4 s** (the Ollama connection attempt has to time out first; Snag 8). Body: `"status":"ok"`,
`"ollama":false`, `"model_ready":false`, both optional keys `false`, `"data_dir_present":true`,
`"data_manifest_sha256":null`, and four plain-English `notices` saying what is missing. Port 8000 was free.

Routes served (from `/openapi.json`): `/api/health`, `/api/scenarios`, `/api/simulate`, `/api/vc-lenses`,
`/api/cases`, `/api/cases/{case_id}/evidence`, `/api/replay/run`, `/api/replay/{prediction_id}/reveal`.
Interactive docs: http://localhost:8000/docs

### 10. Install the web app's packages (5 min 03 s)

The root README's "Without make" block stops at the API (Snag 2); these steps come from `apps/web/README.md`.
In a new Git Bash window (re-run the `export PATH=...node...` line from step 1 first):

```bash
cd apps/web
npm ci
#   8 moderate severity vulnerabilities   (Snag 11)
```

### 11. Start the web app (ready in 3.4 s; first page 17 s)

```bash
npm run dev
#   ▲ Next.js 16.4.3 (Turbopack)
#   - Local:         http://localhost:3000
#   ✓ Ready in 3.4s
#   ✓ Running next.config.ts took 23.2s
#   ✓ Generated AGENTS.md for AI agents. ...
```

Open http://localhost:3000. The first page took **16.7 s** (first compile); later pages took 4.6 to 8.5 s each in dev mode.
Port 3000 was free. Next.js writes `apps/web/AGENTS.md` and `next-env.d.ts`; both are git-ignored, so `git status`
stays clean.

**Both servers up: 19:52:52, about 13 min 45 s after starting the clone.**

### 12. Web checks (about 1 min)

```bash
npm run typecheck    # tsc --noEmit: passed, 17.6 s
npm run lint         # eslint: passed, 37.7 s
npm test             # node --test: 0 failed, 4.6 s
```

### 13. Click through every screen (screenshots: Playwright, 1 min 53 s)

```bash
npx playwright install chromium   # 1 min 00 s; no admin, goes to %LOCALAPPDATA%\ms-playwright
```

I drove headless Chromium at 1440×900 with a small script kept outside the repo. It opened every screen, waited for
the network to go quiet, saved a full-page PNG, and logged console errors, page errors and failed requests. Results
are in the table below. Screenshots: `docs/screenshots/windows/`.

| Screen | Status | What I saw |
|---|---|---|
| `/` | works | Shows the Rewind screen (same content as `/rewind`). |
| `/rewind` | not built yet (works, shows an honest NOT AVAILABLE) | Header: API ONLINE, LOCAL MODEL UNAVAILABLE. Every panel says NOT AVAILABLE and names the endpoint it needs (`GET /api/cases`, `GET /api/cases/{id}/evidence?as_of=`, marked "not wired"). No console errors. |
| `/decision` | not built yet (works, shows an honest NOT AVAILABLE) | Agent decision, probability, market at cutoff, citations and the ACT/WAIT/HEDGE cards are all NOT AVAILABLE, naming `POST /api/replay/run` and `POST /api/simulate` as "not wired". No console errors. |
| `/cascade` | works | Live `POST /api/simulate` (200): baseline minimum cash $63,000, week 26, runway > 26 weeks, labeled SIMULATED / SYNTHETIC. Dependency network renders. 4 presets load from `GET /api/scenarios`. C.3 Recovery plan is NOT AVAILABLE (`POST /api/optimize` not wired). Console: 3 React Flow warnings and 1 aborted request (Snag 10). |
| `/cascade`, "Bad quarter" preset | works | Picked "Bad quarter: rate shock + demand drop + supplier outage" in the Preset dropdown. Minimum cash $13,950 (−$49,050 vs baseline $63,000), ending cash $13,950, runway > 26 weeks. Nodes show peak deltas (e.g. Cash −$64,515 at week 7). The API answered in 51 ms. |
| `/reveal` | not built yet (works, shows an honest NOT AVAILABLE) | Historical outcome NOT AVAILABLE (`POST /api/replay/{prediction_id}/reveal` not wired); Reveal button disabled; scorecard says INSUFFICIENT DATA: NO VALID COMPARISON (`GET /api/benchmark` not wired). No console errors. |
| `/research` | works | Thesis Court in POINT-IN-TIME mode with cutoff "now": 6 sources from 4 firms (Link Ventures, a16z, Sequoia, Bessemer), labeled REAL HISTORICAL, from live `GET /api/vc-lenses?as_of=...`. Model stance NOT AVAILABLE (needs a replay run). No console errors. |
| Keyboard nav | works | → on `/rewind` goes to `/decision`. |

No screen crashed, and no screen threw a page error.

### 14. Playwright e2e smoke test (from `apps/web/README.md`): 1 min 13 s after a workaround

```bash
npx playwright install chromium --only-shell   # already done by step 13
npm run e2e
#   [api] Python was not found; run without arguments to install from the Microsoft Store, or disable this
#   shortcut from Settings > Apps > Advanced app settings > App execution aliases.
#   Error: Process from config.webServer was not able to start. Exit code: 9009
```

See Snag 5. What worked:

```bash
export FAULTLINE_E2E_PYTHON="$(cygpath -w ../../services/api/.venv/Scripts/python.exe)"
npm run e2e
#   ok 1 CASCADE › baseline min cash equals the API; one slider move sends exactly one request and changes it
#   ok 2 CASCADE › API down: readouts are NOT AVAILABLE and inputs are disabled
#   ok 3 RESEARCH LENS › cutoff 2026-07-01T00:00:00Z shows the API's not-yet-public count
#   3 passed (1.1m)
```

### 15. Stop everything

Press Ctrl-C in each server window. When I killed the shell running `npm run dev` from outside, a child process
(`next\dist\server\lib\start-server.js`) kept port 3000 open (Snag 9). I freed it from PowerShell:

```powershell
taskkill /F /T /PID <pid of the npm/next node.exe>
```

(In Git Bash, `taskkill` needs doubled slashes: `taskkill //F //T //PID <pid>`. I did not test that form.)
Find the PID with `netstat -ano | grep ":3000 .*LISTEN"`. Port 8000 (uvicorn) freed itself.

## Snags

1. **winget needs admin.** `winget install --id OpenJS.NodeJS.LTS -e` (Node 26.13.1 LTS) opened a UAC prompt; it was
   cancelled, installer exit code **1602**, winget exit code **12**. *Fix:* portable Node 22 zip, SHA-256 checked
   against the release's `SHASUMS256.txt`, put on PATH (step 1).
2. **README doesn't say you need Node, which version, or how to start the web app without make.** The root README's
   "Run locally" section lists only Python 3.11+ and Ollama. Its "Without make" block covers only the API. There is no
   `engines` field and no `.nvmrc`. *Fix:* used Node 22 (what CI uses) and followed `apps/web/README.md`.
3. **`make: command not found`** (exit 127) on `make setup`: Git Bash ships without `make`. *Fix:* the README's
   "Without make" block. (The `Makefile` would also hit Snag 4: it calls `$(VENV)/bin/python`.)
4. **`bash: .venv/bin/python: No such file or directory`** (README "Without make", line 2). Windows venvs use
   `.venv/Scripts/python`. *Fix:* replaced `bin` with `Scripts` in every venv command.
5. **`npm run e2e`: `Python was not found; run without arguments to install from the Microsoft Store ...`,
   `Process from config.webServer was not able to start. Exit code: 9009`.** `playwright.config.ts` looks for
   `.venv/bin/python` (missing on Windows), then falls back to `python3`. Playwright starts the API through
   `cmd.exe`, where `python3` is the Microsoft Store placeholder, not Git Bash's Python. *Fix:*
   `export FAULTLINE_E2E_PYTHON="$(cygpath -w ../../services/api/.venv/Scripts/python.exe)"`; then 3/3 passed.
6. **5 backend tests fail with `OSError: [WinError 1314] A required privilege is not held by the client`.**
   Creating a symlink on Windows needs admin rights or Developer Mode. The 5 tests:
   `test_routes_cases.py::test_symlink_out_of_demo_cases_is_refused_unread[sealed_outcomes/case-a.json]`,
   `...[sealed_outcomes/valid-looking.json]`, `test_routes_cases.py::test_cases_directory_symlinked_to_sealed_outcomes_is_refused`,
   `test_temporal_gate.py::test_from_dir_refuses_a_symlink_into_sealed_outcomes`,
   `test_temporal_gate.py::test_from_dir_refuses_the_configured_sealed_dir_by_inode`. *Status:* not fixed (no admin);
   these failures come from the test setup, not from the app. CI on Linux runs them.
7. **`core.autocrlf=true`: no problem on this clone.** On older checkouts, 2 raw-fixture hash tests broke because of CRLF
   line endings. `main` now has `.gitattributes` marking `services/api/data/raw/**` and `services/api/markets/testdata/**`
   as `-text`, and they passed on this fresh clone.
8. **No Ollama: expected, not an error.** `/api/health`: `"Ollama not reachable at OLLAMA_BASE_URL (ConnectTimeout)."`;
   the header shows LOCAL MODEL UNAVAILABLE. Each `/api/health` call took 3.4 s while waiting for that timeout.
9. **Port 3000 stayed busy after stopping the dev server from outside.** An orphaned `start-server.js` node process.
   *Fix:* `taskkill /F /T /PID <pid>` (step 15).
10. **`/cascade` dev-mode console noise (screen works):** 3 warnings
    `[React Flow]: The parent container needs a width and a height to render the graph. Help: https://reactflow.dev/error#004`
    on first render (the graph then draws normally), and `requestfailed: GET http://localhost:8000/api/scenarios
    net::ERR_ABORTED`. The presets still loaded (4 named scenarios), so the aborted request is probably React dev mode
    mounting the component twice and cancelling the first fetch. Not checked in a production build.
11. **`npm ci`: "8 moderate severity vulnerabilities"**, plus an "npm 12 available" notice. Not looked into; nothing was changed.
12. **Slow first start:** `Running next.config.ts took 23.2s`, first page 16.7 s. Later pages took 4.6 to 8.5 s in dev.
    Rehearse with the pages already opened once.
13. Cosmetic, dev only: the round Next.js dev-tools "N" button sits over the left edge of every screen (visible in
    the screenshots).

## Follow-ups (for a lead to file; nothing was changed in code)

1. **README "Run locally":** add Node.js 22 as a prerequisite (match CI), and give the web steps
   (`cd apps/web && npm ci && npm run dev`) in the "Without make" block. Add `engines` (or a `.nvmrc`) to `apps/web`.
2. **README "Without make" on Windows:** add the `.venv/Scripts/python` form, e.g. "on Windows replace `.venv/bin/` with
   `.venv/Scripts/`", or one command that works on both.
3. **Makefile:** `VENV/bin/python` is hard-coded (`setup`, `API_PY`); support `.venv/Scripts/python.exe` too, for anyone
   who installs `make` on Windows.
4. **`apps/web/playwright.config.ts`:** also check `.venv/Scripts/python.exe`, and don't fall back to `python3` on
   Windows (it hits the Microsoft Store alias). Mention `FAULTLINE_E2E_PYTHON` for Windows in `apps/web/README.md`.
5. **Symlink tests:** skip them (with a reason) when the OS refuses to create a symlink (WinError 1314), so
   `pytest` is green on a normal Windows laptop.
6. **UI wiring:** the API on `main` now serves `GET /api/cases`, `GET /api/cases/{case_id}/evidence`,
   `POST /api/replay/run` and `POST /api/replay/{prediction_id}/reveal` (#44/#76). The web app's `PENDING_ENDPOINTS`
   still calls these "not wired", so Rewind, Decision and Reveal show NOT AVAILABLE. They also need the demo cases
   (#20). `POST /api/optimize` (Cascade C.3, #17) and `GET /api/benchmark` (Reveal scorecard) are not served yet.
7. **`/cascade` console:** look at the React Flow `#004` warning and the aborted `/api/scenarios` request in dev
   (Snag 10). Low priority; the screen works.
8. **`npm audit`:** go through the 8 moderate advisories (Snag 11).
9. **Docs:** a short "stopping the servers on Windows" note (Snag 9).
