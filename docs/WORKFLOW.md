# FAULTLINE team workflow

## Roles
| Who | Role | Can | Cannot |
|---|---|---|---|
| LavishSphere | Lead (systems/backend) | delegate, review, merge, deploy | — |
| Yaseen (YaseenAhmad12) | Partner (finance/math owner) | work on delegated issues, push `yaseen/*` branches, open PRs, comment | merge, push/commit to `main`, deploy, create/close issues, edit guardrails |
| Specialist agents | Contributors | work on one issue in their directories, open PRs | merge, deploy, edit outside scope |

## The loop
```
Lead: /delegate ──► GitHub issue (label: delegated, ws:*, assignee)
                         │
Yaseen's agent: session start auto-syncs + lists his delegated issues
                         │  /start-task N  (verifies lead-authored, branches from origin/main)
                         ▼
                   yaseen/N-slug branch ──► /ship-pr ──► Pull request (Closes #N)
                                                              │
Lead: /review-pr N  (tests in a worktree + integrity-auditor) ─┤
                                                              ▼
                                          Lead approves & merges on GitHub ──► main ──► (lead deploys)
```
Lead-run parallel work: `/sprint <phase>` dispatches specialist subagents in isolated worktrees; each opens its own PR.

## Enforcement layers (strongest first)
1. **GitHub ruleset `protect-main`** (`scripts/setup-github.sh`): only repo admins can update `main`; PRs need code-owner
   approval; CI must pass; no force-push/deletion. Yaseen has *write* access, so he can push branches and open PRs but cannot merge.
2. **CODEOWNERS**: lead is required on everything; Yaseen is also requested on the math files.
3. **Git hooks** (`.githooks/`, any agent or human): `pre-commit` refuses commits on `main`, `pre-push` refuses pushes to
   `main` and remote branch deletion. Installed by `bash scripts/agent-start.sh` (sets `core.hooksPath`).
   A human lead can deliberately override with `FAULTLINE_LEAD_OVERRIDE=1 git push ...`.
4. **Claude Code hooks** (`.claude/settings.json`): `scripts/guardrails/guard.py` additionally blocks force pushes, `--no-verify`,
   prod deploys, repo-settings changes, and for partners: merges, approvals, issue creation, guardrail edits.
   `sync.py` fetches GitHub at session start (and every ~10 min on prompts) and tells the agent who it works for.
5. **AGENTS.md (imported by CLAUDE.md) + `.agents/skills/`** (symlinked as `.claude/skills/`): the instructions the agent reads.
Layers 3–5 are local guardrails that a determined user could disable; layer 1 is what actually protects `main`.

## Keeping everyone current
- Session start: auto `git fetch`, fast-forward a clean `main`, warn if your branch is behind, list your tasks/PRs.
- During a session: re-fetch at most every 10 minutes when you send a prompt; the agent is told if `origin/main` moved.
- `/sync` anytime; `/ship-pr` always rebases onto `origin/main` before pushing.

## Production
Production = deployment built from `main` (e.g. Vercel production branch = `main`). Only leads hold deploy credentials.
PR preview deploys are fine (not production). Agents are blocked from `--prod` deploy commands.

## Parallelism without collisions
Each workstream owns directories (see `/sprint` table). Shared contracts (`services/api/models.py`, `apps/web/lib/api.ts`)
land first in one PR. Merge order: contracts → engine → API → UI.

## Build plan to Sunday 2026-11-15 (P0 only; see SPEC §9)
| When | Lead + agents | Yaseen + his agent |
|---|---|---|
| Thu night | Merge this workflow; scaffold monorepo + contracts PR | Set up (PARTNER_GUIDE); review MATH_MODEL §1–4, §10; set parameters |
| Fri | Finance engine + optimizer (finance-modeler), temporal gate + seal + scoring (backend), web shell + cascade graph (frontend), market collectors (markets) | Golden test cases; disruption costs; pick + audit 2–4 real resolved events |
| Sat | Ollama recorded runs, benchmark, VC lenses, end-to-end golden path, polish | Case review; thesis summaries accuracy; financial narrative of demo |
| Sun AM | Freeze, offline test, record backup run, rehearse 2-min demo | Rehearse finance Q&A |

## CI merge checks (`.github/workflows/ci.yml`)
Every PR runs these in parallel; the single required check **`checks`** passes only if all of them pass.

| Job | Fails when |
|---|---|
| policy | > 3 commits · AI co-author trailer or "Generated with…" line · title not `<area>: <what>` · body doesn't close an open, lead-created `delegated` issue (partners: assigned to them) · partner touches lead-only files · engine file changed without MATH_MODEL.md or a ticked "No formula change" |
| guardrails | agent-hook or scanner self-tests fail |
| secrets | an added line contains an API key, token, or private key |
| honesty | added non-test code claims "% accuracy", "beats the market/VCs", a VC accuracy score, a fake timed "result", or uses randomness in the engine/UI (suppress a deliberate case with `honesty-ok: <reason>`) |
| backend | `ruff check` or `pytest` fails (skipped until `services/api` exists) |
| web | `typecheck`, `lint`, or the static-export build fails (skipped until `apps/web` exists) |

Rules are read from `.agents/team.json` on the **base** branch, so a PR can't relax its own checks.
Deploy (CD) lands with issue #13: GitHub Pages builds from `main` only; the API is deployed by a lead.
