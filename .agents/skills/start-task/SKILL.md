---
name: start-task
description: Pick up a delegated GitHub issue and start work on it correctly (verify it was assigned by a lead, sync, branch from origin/main, plan). Use when a partner (or any agent) begins work, when the user says "what should I work on", "next task", "start issue #N", or asks to build something. For partner sessions this is the ONLY valid way to begin implementation work.
argument-hint: "[issue number]"
---

# Start a delegated task

Read `.agents/team.json` for `leads`, `partners`, and `delegation_label`.

## 1. Find and verify the task
- If an issue number was given: `gh issue view <N> --json number,title,body,author,assignees,labels,state,comments`.
- Otherwise list candidates: `gh issue list --state open --label delegated --assignee @me --json number,title,author`.
- **Verify all of:** state is OPEN · has the `delegated` label · `author.login` is in `leads` (or a lead has commented approving it) · the current user is an assignee.
- **Partner session and verification fails →** do not implement. Say plainly:
  "This task wasn't delegated by a lead, so I can't build it. I can help you write a comment asking <lead> to file it."
  (Answering questions or explaining code is still fine.)
- **Lead session →** a lead may also ask you to work without an issue; then suggest `/delegate` to file one first so the PR can link it, but proceed if they insist.

## 2. Sync and branch
- Run the `/sync` procedure first.
- Branch from fresh main: `git switch -c <prefix><N>-<slug> origin/main`, where prefix is the partner's `branch_prefix`
  (e.g. `yaseen/`) or the lead's short name. Slug: 2–4 lowercase words from the title.
- Comment on the issue that work started: `gh issue comment <N> --body "Started on branch <branch>."`

## 3. Understand before building
- Read the issue's **Acceptance criteria**, **Files in scope**, and **Out of scope** sections. Stay inside them.
- Read the relevant parts of `docs/SPEC.md` and `docs/MATH_MODEL.md` cited in the issue. The matching domain skill
  (`finance-engine`, `replay-integrity`, `market-data`, `cascade-ui`, `research-lens`, `backend-api`) loads automatically.
- Write a short plan (≤ 8 bullets) and show it to the human. For a partner: plain language, formulas welcome, no jargon.
  If the issue is ambiguous, ask the human or draft a question comment on the issue. Do not guess silently.

## 4. Build
- Tests first where the task is computational (golden numbers from MATH_MODEL.md §9 style).
- Commit early and often on the branch with clear messages (`finance: add receipts timing to cash recurrence (#N)`).
- Anything you notice that is out of scope → note it for the PR description under "Follow-ups". Do not do it.

When the acceptance criteria are met, run `/ship-pr`.
