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
Lead: /merge-queue (order) → /review-pr N (depth by risk tier) ─┤◄── changes requested / red CI:
                                                              ▼      author runs /address-review
                                          Lead approves & merges on GitHub ──► main ──► (lead deploys)
```
Lead-run parallel work: `/sprint <phase>` dispatches specialist subagents in isolated worktrees; each opens its own PR.

## The review queue is the constraint
Agents write PRs in minutes; one lead reviews them. On Fri Nov 13 at 4pm there were 15 open PRs, 13 of them green and
waiting on the lead. The rules that follow from that:
- **Merged is the only state that counts.** At the freeze, an open PR is worth nothing.
- **Fix before new.** A PR with changes requested or red CI is fixed (`/address-review`) before its author starts another task.
- **Queue before dispatch.** With three or more green PRs waiting, the lead runs `/merge-queue` before `/sprint`.
- **Hand off green.** `/ship-pr` waits for CI (about 90 s) and fixes a red run before telling the human it is done.
- **Review depth follows risk** (`/review-pr`): tier A = integrity core (`integrity_core` in `.agents/team.json`) gets the
  full independent audit; tier B = other code is reviewed from the diff; tier C = documents are read for claims.
  Green CI is not re-run locally.
- **Who approves what.** A partner PR gets a lead approval on GitHub. A lead cannot approve their own PR, so a
  lead-authored PR is gated by green CI plus the `integrity-auditor` report and is merged with the admin bypass
  (`gh pr merge --squash --admin`). That is a weaker gate than a second human; the finance owner is also requested on the math files.
  `--admin` also bypasses the required `checks` status, so run `gh pr checks <N>` on the current head right before merging
  and pass `--match-head-commit <headRefOid>` (see the `merge-queue` skill).
- **Parking.** A PR that must not merge yet becomes a draft with a comment saying what it waits for.

The session banner shows this state every time a session starts: for a lead, open PRs grouped by who they wait on; for a
partner, their PRs that need fixes first, then each task as ready / waiting on #N / in review.

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
- Every session start also prints the time left to the next deadline (from `deadlines` in `.agents/team.json`).

## Production
Production = what is built from `main`: the static web export on GitHub Pages and the API on the lead's own server
(issue #13, PR #28, which is still open, so this is the plan rather than a running setup). Only leads hold deploy credentials. Agents are blocked from deploy commands.

## Parallelism without collisions
Each workstream owns directories (`workstreams` in `.agents/team.json`). Shared files (`services/api/main.py`,
`services/api/models.py`, `apps/web/lib/api.ts`) are touched by one open PR at a time where possible; when several
PRs do touch one, they merge one after another and the later ones rebase. Merge order: contracts → engine → API → UI.

## Build plan to Sunday 2026-11-15 (P0 only; see SPEC §9)
The original plan, kept for reference. The live state is the GitHub issue and PR lists; deadlines are in docs/HACKATHON.md.
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
| e2e | the Playwright smoke test fails against the real API and the static export |

A full run takes about 90 seconds. Editing a PR's title or body re-runs everything, so write the body once.

Rules are read from `.agents/team.json` on the **base** branch, so a PR can't relax its own checks.
Deploy (CD) lands with issue #13: GitHub Pages builds from `main` only; the API is deployed by a lead.
