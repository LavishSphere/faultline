---
name: my-sprint
description: Work on several of your delegated GitHub issues at the same time - checks which of your lead-assigned tasks are unblocked and don't touch the same files, then runs one specialist agent per task in its own isolated copy of the repo, each opening its own PR for lead review. Use when the partner (Yaseen) or a lead says "work on my tasks in parallel", "do several tasks at once", "my sprint", or "run all my tasks".
argument-hint: "[issue numbers, optional]"
---

# My sprint: several delegated tasks in parallel

Works for partners and leads. It never creates work: it only picks up issues a lead already delegated.

## 1. Sync and collect candidates
- Run the `sync` procedure first.
- Read `.agents/team.json`. List candidates:
  `gh issue list --state open --label delegated --assignee @me --json number,title,author,labels,body`
  (if issue numbers were given, use only those).
- Keep an issue only if **all** of these hold:
  - its `author.login` is in `leads`;
  - **it isn't blocked**: every `#N` on its `**Starts after:**` line is closed or merged. Check with
    `gh issue view N --json state` (PR numbers work too; merged means `CLOSED`). List blocked ones as "waiting on #N";
  - nobody is already on it: no open PR says `Closes #<it>` (`gh pr list --search "<it> in:body" --state open`).

## 2. Plan: no file overlap, at most 3 at once
- From each issue's **Files in scope**, check that no two chosen issues share a file or directory. If two overlap,
  run the lower-numbered one now and queue the other.
- At most **3 agents at once** (review bandwidth and laptop resources).
- Pick the specialist from the workstream label:
  `ws:finance` → `finance-modeler` · `ws:replay` / `ws:eval` / `ws:backend` → `backend-engineer` · `ws:markets` → `market-data-engineer` ·
  `ws:research` → `research-curator` · `ws:frontend` → `frontend-designer` · otherwise `general-purpose`.
- **Show the plan to the human in plain language** (task → agent → files → what will come back) and wait for a "go".
  For a partner, explain each task's goal in finance terms.

## 3. Dispatch: one message, all agents together
Send every Agent call in **one message**, each with `isolation: "worktree"`, the chosen `subagent_type`, and a prompt containing:
- the issue number and its full body (`gh issue view N`);
- who you work for, and that **partner rules apply**: work only on this issue; never merge, approve, deploy, or edit
  `.claude/`, `.agents/`, `.github/`, `.githooks/`, `scripts/`, `AGENTS.md`, `CLAUDE.md`, `docs/SPEC.md`;
- "Run `git fetch origin --prune`, then `git switch -c <prefix><N>-<slug> origin/main` (prefix from team.json, e.g. `yaseen/`).
  Follow the `start-task` and `ship-pr` procedures. ≤3 commits. No AI attribution lines (`Co-Authored-By: Claude`,
  'Generated with Claude Code') in commits or the PR. Finish by opening the PR with `Closes #N`";
- "Explain anything you report in plain finance/math language; your final message must give: PR URL, what changed,
  tests run and results, what is NOT verified, questions for the finance owner."

## 4. Collect and hand off
- As each agent finishes, record: issue → PR URL → CI (`gh pr checks <n>`) → open questions.
- Give the human one table plus a plain-language summary per PR, and **list every question the agents left for the
  finance owner**. Those need the human's judgment, not the agent's.
- Remind the human: the PRs go to the lead for review. Nothing is merged or deployed by this skill.
- If any task was queued (overlap or the 3-agent cap), offer to run the next batch.

## If something goes wrong
- An agent was blocked by the guard: report the exact message to the human; don't look for a workaround.
- CI is red on a PR: resume that agent (`SendMessage`) with the failing check's output, then amend and force-push with lease.
