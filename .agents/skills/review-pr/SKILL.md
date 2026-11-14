---
name: review-pr
description: Lead-only. Review a teammate's or agent's pull request against FAULTLINE's spec, math model, and honesty rules at a depth that matches its risk, and produce a clear verdict (approve / request changes) for the lead. Use when a lead says "review PR #N", "check Yaseen's PR", or "audit #N". For "what's waiting for review" or several PRs at once, use `merge-queue` first.
argument-hint: "<PR number>"
---

# Review a PR (leads only)

The session banner must say role = LEAD. Review time is the scarcest thing on this project: spend it where a mistake would
hurt the demo or the honesty rules, and do not redo what CI already proved.

## 1. Read it and check it is reviewable (one call each)
```bash
gh pr view <N> --json title,body,author,headRefName,headRefOid,files,commits,labels,isDraft,reviewDecision,mergeable,closingIssuesReferences,statusCheckRollup
gh pr diff <N>
```
- **CI not green on the current head → stop.** Say which check fails and that it waits on the author (`address-review`). Do not review red PRs.
- **Scope:** it closes a `delegated` issue and stays inside that issue's "Files in scope". Flag loudly any change to
  `.claude/`, `.agents/`, `.github/`, `scripts/guardrails/`, `docs/SPEC.md`, or `data/sealed_outcomes/`.

## 2. Pick the depth from the files changed (`integrity_core` in `.agents/team.json`)
| Tier | The PR touches | What to do |
|---|---|---|
| **A: integrity core** | any `integrity_core` path: `services/api/core/`, `agents/`, `routes/`, `data/sealed_outcomes/`, `data/demo_cases/`, `markets/normalize.py`, `docs/MATH_MODEL.md` | Full review: steps 3 + 4 + 5 |
| **B: other code** | `apps/web/`, the rest of `services/api/`, `scripts/`, the Makefile | Steps 3 + 5 from the diff. No worktree, no auditor, unless something looks wrong |
| **C: documents only** | only `*.md` / `docs/` and none of the above | Read it in full for claims (step 5, honesty items). Pitch, demo-script and brief documents are where superiority claims creep in |

Green `checks` on the current head already means ruff, pytest, typecheck, lint, the static build, the e2e smoke test and the
honesty and secrets scans passed. **Do not re-run `make test` locally to confirm it.** Run code locally only to test something
CI cannot: a behavior the PR claims but no test covers, anything that needs Ollama, or a click-through of a screen.

## 3. Read the diff against the contract
Formulas against `docs/MATH_MODEL.md`, routes and models against the domain skill for that directory, and every "verified"
claim in the PR body against the code or test that backs it.

## 4. Independent audit (tier A only)
Dispatch the `integrity-auditor` subagent with `isolation: "worktree"`. Prompt: the PR number, "check out the PR head with
`git fetch origin pull/<N>/head && git switch --detach FETCH_HEAD`", the issue's acceptance criteria, and the files changed.
Give it the code, not your conclusions. Reviewing several tier-A PRs? Send all the auditor calls in one message (at most 3 at once).

## 5. Checklist (SPEC §10 + MATH_MODEL)
- Formulas match MATH_MODEL.md; doc updated if a formula changed; golden tests exist and pass
- No LLM arithmetic in authoritative paths; no fabricated data/quotes/metrics; provenance labels present
- Temporal gate: nothing with `available_at > as_of`; no sealed outcome reachable pre-reveal
- Optimizer: payroll protection is a solver bound; infeasible returns `NO FEASIBLE PLAN`
- No secrets, no network calls in replay inference paths, no deploy config changes

## 6. Verdict
APPROVE or REQUEST CHANGES, with **numbered** blocking items (file:line, the failure it causes, what would fix it) and
separate non-blocking nits. The author's agent answers by number (`address-review`), so one item per number.
- Post it so the author's next session sees it: `gh pr review <N> --request-changes --body-file <tmp>`.
  GitHub does not allow a review verdict on your own PR; for a lead-authored PR use `gh pr comment <N> --body-file <tmp>`.
- `--approve` and `gh pr merge` only when the lead says so in this session. Never deploy as part of review.
