# FAULTLINE: rules for every AI agent

The team (leads and Yaseen) builds with Claude Code; `CLAUDE.md` imports this file.

FAULTLINE is a time-aware decision-intelligence and financial stress-testing platform (hackathon MVP, deadline
Sunday 2026-11-15). Sources of truth:
- **docs/SPEC.md**: product spec. Its principles (§1) are non-negotiable.
- **docs/MATH_MODEL.md**: the formal math (cash recurrence, optimizer MILP, scoring). Code must match it exactly.
- **docs/WORKFLOW.md**: who does what, branches, PRs, review.

## 0. First thing in every session (any agent)
```bash
bash scripts/agent-start.sh
```
It installs the repo's git hooks, syncs with GitHub, and prints **who you are working for** (LEAD or PARTNER) and their
delegated tasks / PRs to review. Obey its output. If it reports a failed fetch, tell the human before doing anything else.
(Claude Code runs this automatically through `.claude/settings.json`; running it again is harmless.)

## 1. Always build on the latest GitHub state
- Before a task: `git fetch origin --prune`, branch from **`origin/main`** (not a stale local main).
- Before opening/updating a PR: fetch again, `git rebase origin/main`, re-run tests.
- If `origin/main` moved while you worked, re-read files you are editing before changing them again.

## 2. Git and production rules (enforced by GitHub ruleset + git hooks + agent hooks)
- **No agent pushes to, commits on, or force-pushes `main`.** Flow: branch → PR → lead review → lead merges.
- **Only leads merge. Only leads deploy to production** (production = what is built from `main`).
- Never bypass hooks: no `--no-verify`, no changing `core.hooksPath`, never set `FAULTLINE_LEAD_OVERRIDE`.
- Branches: `<owner>/<issue#>-<slug>`, e.g. `yaseen/14-cash-recurrence`. One issue → one branch → one PR, inside one workstream's directories.
- **Max 3 commits per PR** (guard blocks a 4th; CI fails >3). Use `git commit --amend` for follow-up fixes.
- **No `Co-Authored-By: Claude` (or any AI co-author) trailers** in commits. The `.githooks/commit-msg` hook strips them and CI rejects them.
- Don't modify `.agents/`, `.claude/`, `.github/`, `.githooks/`, `scripts/guardrails/`, `AGENTS.md`, `CLAUDE.md`, `CODEOWNERS`, or
  `docs/SPEC.md` unless a lead explicitly asked in this session.
- Never commit secrets. `.env` is git-ignored; document variables in `.env.example`.

## 3. Partner sessions (Yaseen, finance/math owner, not a programmer)
When the start script says role = PARTNER:
- **Only work on GitHub issues created by a lead, labeled `delegated`, and assigned to the partner** (procedure: `start-task`).
  For anything else, decline kindly and offer to draft a `gh issue comment` asking the lead. Explaining code/answering questions is always fine.
- Finish with the `ship-pr` procedure. The PR is the deliverable. Never merge, approve, deploy, create or close issues.
- Talk in finance/math language; explain any CS concept in one plain sentence; show formulas and numbers.
  Yaseen is the authority on financial assumptions; you are responsible for correct, tested code.
- Before any command that changes files or git state, say in one line what it does.
- **Pull before editing.** Before the first edit of a session, and whenever GitHub `main` has moved, run the `sync`
  procedure (equivalent: `make pull`). The guard enforces this: partner edits are blocked while the copy is behind
  `origin/main` or GitHub can't be reached. When blocked, sync, re-read the files, then redo the edit.

## 4. Honesty rules (SPEC §1, §6): these override convenience
- LLMs never do authoritative arithmetic; typed Python functions and the optimizer do.
- Never fabricate data, market quotes, model outputs, benchmark numbers, or "live" states.
  Missing data → `NOT AVAILABLE` / `INSUFFICIENT DATA`, never a plausible placeholder.
- Every displayed datum has a provenance label: `REAL HISTORICAL`, `SYNTHETIC`, `RECORDED RUN`, `SIMULATED`, `ILLUSTRATIVE`.
- Sealed outcomes never reach model context, pre-reveal endpoints, or prompts. Evidence must satisfy `available_at <= as_of`.
- No claims of beating markets/VCs unless computed on a locked dataset with n, baselines, and a CI (MATH_MODEL §6).

## 5. Skills (procedures): `.agents/skills/<name>/SKILL.md`
These are plain Markdown in the open Agent Skills format. If your agent doesn't load skills natively, **read the file and
follow it** when the trigger applies (e.g. the user says "start task 12" → read `.agents/skills/start-task/SKILL.md`).

| Skill | Use when | Who |
|---|---|---|
| `sync` | start of work, branch behind, before PR | everyone |
| `start-task` | beginning any implementation task | everyone (mandatory for partners) |
| `ship-pr` | work is done → verify, rebase, push branch, open PR | everyone |
| `delegate` | turn a lead's request into a scoped GitHub issue | leads only |
| `review-pr` | review a PR against spec + honesty rules | leads only |
| `sprint` | run parallel specialist agents on a phase | leads only |
| `finance-engine` | `core/financials.py`, `core/optimizer.py`, demo business | domain |
| `replay-integrity` | temporal gate, sealed outcomes, provider, scoring | domain |
| `market-data` | Kalshi/Polymarket adapters, snapshots, normalization | domain |
| `cascade-ui` | anything in `apps/web/` | domain |
| `research-lens` | VC research lenses, Thesis Court | domain |
| `backend-api` | FastAPI app, Makefile, routes, config | domain |
| `honesty-audit` | before any PR, before demos | everyone |

Specialist roles (for orchestrating several agents) are defined in `.claude/agents/*.md`; any agent can adopt one by reading it.

## 6. Repo layout (target, SPEC §8) and ownership
```
apps/web/                 Next.js + TS + Tailwind + React Flow            ws:frontend
services/api/             FastAPI + Pydantic v2                           ws:backend
  core/financials.py, core/optimizer.py                                   ws:finance
  core/temporal_gate.py, provenance.py, forecasting.py, evaluator.py      ws:replay / ws:eval
  markets/                                                                ws:markets
  agents/                                                                 ws:backend
  data/research_lenses.json                                               ws:research
  data/sealed_outcomes/   ← model runtime must never read this
  tests/
scripts/  docs/
```

## 7. Done means
`make test` passes (plus `make check` once the web app exists); everything displayed is honestly labeled;
`docs/MATH_MODEL.md` is updated in the same PR if a formula changed; the PR body says what was verified and what was not.
