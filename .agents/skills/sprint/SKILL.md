---
name: sprint
description: Lead-only orchestration. Break a SPEC phase or a set of open issues into parallel, non-overlapping workstreams and dispatch the specialist subagents (backend-engineer, finance-modeler, market-data-engineer, frontend-designer, research-curator) in isolated git worktrees, each producing its own PR. Use when a lead says "run phase N", "parallelize", "spin up the agents", or "build P0".
disable-model-invocation: true
argument-hint: "<phase or issue numbers>"
---

# Sprint: parallel specialist agents (leads only)

1. **Queue before new work.** Look at the banner's PR list (or run `merge-queue` step 1). If three or more green PRs
   already wait on a lead, say so and propose clearing them first: every new agent adds a PR to that queue, and a PR
   unmerged at the freeze counts for nothing. Proceed with new agents only if the lead still wants to.
2. Run the `sync` procedure. List open issues: `gh issue list --state open --label delegated --json number,title,labels,assignees,body`.
3. Map the requested phase (SPEC §9) or issue numbers to workstreams. **Partition by directory** so agents never edit the
   same files. The owner of each directory is in `.agents/team.json` → `workstreams` (`label → agent, paths`); an issue's
   own "Files in scope" overrides it. Skip an issue that already has an open PR, or whose `**Starts after:**` items are not merged.
   `shared_files` (`models.py` Pydantic schemas, `main.py` router wiring, `apps/web/lib/api.ts` types) are written
   **first, by one agent**, merged, and only then do the others start. Two issues that both need a shared file do not run together.
4. Every unit of work needs an issue. Create missing ones with the `delegate` procedure (assign to the lead's login for agent work, or to Yaseen for finance review).
5. Show the lead the plan (agent × issue × directories × what it unblocks) and get a go-ahead. At most 4 agents at once.
6. Dispatch in **one message**, each Agent call with `isolation: "worktree"` and the matching `subagent_type`. Each prompt
   includes: the issue number and full body, owned directories, "branch from origin/main, finish with the ship-pr
   procedure including waiting for CI to go green, do not merge", and the no-AI-attribution rule.
7. As agents return: collect PR URLs and CI state, then run `merge-queue` over the new PRs and report a table
   (issue → PR → CI → tier → verdict). Merge order: contracts → engine → API → UI.
