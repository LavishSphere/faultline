---
name: delegate
description: Lead-only. Turn a lead's request into a well-scoped GitHub issue assigned to Yaseen (or another teammate/agent), labeled `delegated` plus a workstream label, with plain-language goal, acceptance criteria, files in scope, dependencies, and out-of-scope list. Use when a lead says "give Yaseen…", "delegate", "assign", or "make a task for".
disable-model-invocation: true
argument-hint: "<who> <what>"
---

# Delegate a task (leads only)

The session banner must say role = LEAD. If not, refuse: partners cannot delegate.

1. **Check the load first.** `gh issue list --state open --label delegated --assignee <login> --json number,title` and the
   banner's PR list. If the assignee already has PRs that need fixes, or more ready tasks than they can finish before the
   next deadline, tell the lead before adding more: a task that cannot be reviewed and merged in time costs effort and
   returns nothing. Check the new task is not already covered by an open issue.
2. Clarify scope with the lead only if it is genuinely ambiguous. Prefer small tasks (≤ ~3 hours, one workstream, one PR).
3. Choose the workstream label from `.agents/team.json` → `workstreams`; its `paths` are the default "Files in scope".
4. For Yaseen, write for a finance/math expert who is not a programmer: state the goal in finance terms, cite the
   MATH_MODEL.md section, and make acceptance criteria numeric and testable ("Case B golden test reproduces
   C_3 = 92,230.769 to the cent"). Good Yaseen tasks: financial assumptions, parameter values, formula correctness,
   golden test cases, optimizer constraints/disruption costs, case review, VC research accuracy.
5. Draft the issue body with these headings and show it to the lead before creating:
   ```
   **Starts after:** #A merged, #B merged        ← only if it builds on unmerged work; omit the line otherwise
   ## Goal (plain language)
   ## Why it matters (SPEC §x / MATH_MODEL §y / judging criterion)
   ## Acceptance criteria   (checkboxes, testable)
   ## Files in scope        (exact paths, one per line)
   ## Out of scope
   ## Notes for the agent   (gotchas, related PRs/issues)
   ```
   - The `**Starts after:**` line is machine-read by the session banner, `start-task` and `my-sprint`. Keep the exact
     spelling, on one line, with issue or PR numbers. A task that needs code from an open PR must name it.
   - "Files in scope" is machine-compared by `my-sprint` and `merge-queue` to keep parallel work from colliding. Use real
     paths, not descriptions. If the task must touch a `shared_files` entry (`services/api/main.py`, `models.py`,
     `apps/web/lib/api.ts`), say so in Notes: PRs that touch those merge one at a time.
6. Create it: `gh issue create --title "<area>: <task>" --body-file <tmp> --label delegated --label ws:<area> --assignee <login>`.
   Several related tasks: draft them all, show the lead one list (title, files, starts-after), then create them together.
7. Report the issue URL(s). Yaseen's agent sees new tasks at session start or via `/start-task <N>`.
