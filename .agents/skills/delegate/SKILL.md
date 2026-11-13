---
name: delegate
description: Lead-only. Turn a lead's request into a well-scoped GitHub issue assigned to Yaseen (or another teammate/agent), labeled `delegated` plus a workstream label, with plain-language goal, acceptance criteria, files in scope, and out-of-scope list. Use when a lead says "give Yaseen…", "delegate", "assign", or "make a task for".
disable-model-invocation: true
argument-hint: "<who> <what>"
---

# Delegate a task (leads only)

The session hook must say role = LEAD. If not, refuse: partners cannot delegate.

1. Clarify scope with the lead only if it is genuinely ambiguous. Prefer small tasks (≤ ~3 hours, one workstream, one PR).
2. Choose the workstream label from `.agents/team.json` (`ws:finance`, `ws:replay`, ...).
3. For Yaseen, write for a finance/math expert who is not a programmer: state the goal in finance terms, cite the
   MATH_MODEL.md section, and make acceptance criteria numeric and testable ("Case B golden test reproduces
   C_3 = 92,230.769 to the cent"). Good Yaseen tasks: financial assumptions, parameter values, formula correctness,
   golden test cases, optimizer constraints/disruption costs, case review, VC research accuracy.
4. Draft the issue body with these headings and show it to the lead before creating:
   ```
   ## Goal (plain language)
   ## Why it matters (SPEC §x / MATH_MODEL §y)
   ## Acceptance criteria   (checkboxes, testable)
   ## Files in scope
   ## Out of scope
   ## Notes for the agent   (gotchas, related PRs/issues)
   ```
5. Create it: `gh issue create --title "<area>: <task>" --body-file <tmp> --label delegated --label ws:<area> --assignee <login>`.
6. Report the issue URL. Tell the lead that Yaseen's agent will see it at session start or via `/start-task <N>`.
