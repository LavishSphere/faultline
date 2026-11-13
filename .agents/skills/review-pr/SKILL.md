---
name: review-pr
description: Lead-only. Review a teammate's or agent's pull request against FAULTLINE's spec, math model, and honesty rules, run its tests locally, and produce a clear verdict (approve / request changes) for the lead. Use when a lead says "review PR #N", "check Yaseen's PR", or "what's waiting for review".
disable-model-invocation: true
argument-hint: "<PR number>"
---

# Review a PR (leads only)

The session hook must say role = LEAD.

1. `gh pr view <N> --json title,body,author,headRefName,files,commits,labels,closingIssuesReferences` and `gh pr diff <N>`.
2. **Scope:** does it close a `delegated` issue, and stay within that issue's "Files in scope"? Flag any change to
   `.claude/`, `.github/`, `CODEOWNERS`, `docs/SPEC.md`, or `data/sealed_outcomes/` loudly.
3. **Run it:** check out in a worktree so the lead's checkout is untouched:
   `git fetch origin pull/<N>/head:pr-<N> && git worktree add ../faultline-pr-<N> pr-<N>`, then run `make test` / `make check` there.
   Remove the worktree afterwards.
4. **Independent audit:** delegate to the `integrity-auditor` subagent with the PR number and diff. Give it the code, not your conclusions.
5. **Checklist** (SPEC §10 + MATH_MODEL):
   - Formulas match MATH_MODEL.md; doc updated if a formula changed; golden tests exist and pass
   - No LLM arithmetic in authoritative paths; no fabricated data/quotes/metrics; provenance labels present
   - Temporal gate: nothing with `available_at > as_of`; no sealed outcome reachable pre-reveal
   - Optimizer: payroll protection is a solver bound; infeasible returns `NO FEASIBLE PLAN`
   - No secrets, no network calls in replay inference paths, no deploy config changes
6. **Verdict** to the lead: APPROVE or REQUEST CHANGES, with a numbered list of blocking items (file:line) and
   non-blocking nits. Offer to post it: `gh pr review <N> --comment --body-file <tmp>` (or `--request-changes`).
   Only `--approve` or `gh pr merge` when the lead explicitly says so in this session. Never deploy as part of review.
