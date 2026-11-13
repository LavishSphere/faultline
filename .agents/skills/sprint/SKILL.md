---
name: sprint
description: Lead-only orchestration. Break a SPEC phase or a set of open issues into parallel, non-overlapping workstreams and dispatch the specialist subagents (backend-engineer, finance-modeler, market-data-engineer, frontend-designer, research-curator) in isolated git worktrees, each producing its own PR. Use when a lead says "run phase N", "parallelize", "spin up the agents", or "build P0".
disable-model-invocation: true
argument-hint: "<phase or issue numbers>"
---

# Sprint: parallel specialist agents (leads only)

1. `/sync`. List open issues: `gh issue list --state open --json number,title,labels,assignees`.
2. Map the requested phase (SPEC §9) to workstreams. **Partition by directory** so agents never edit the same files:
   | Agent | Owns |
   |---|---|
   | backend-engineer | `services/api/main.py`, `routes/`, `models.py`, `agents/`, `Makefile`, root config |
   | finance-modeler | `services/api/core/financials.py`, `core/optimizer.py`, `tests/test_financials.py`, `tests/test_optimizer.py` |
   | backend-engineer (replay) | `core/temporal_gate.py`, `core/provenance.py`, `core/evaluator.py`, `core/forecasting.py`, replay/scoring tests |
   | market-data-engineer | `services/api/markets/`, `scripts/collect_market_snapshots.py`, `data/raw/`, market tests |
   | frontend-designer | `apps/web/` |
   | research-curator | `services/api/data/research_lenses.json`, `docs/DATA_PROVENANCE.md` |
   Shared contracts (`models.py` Pydantic schemas, `apps/web/lib/api.ts` types) are written **first, by one agent**, merged, then the others start.
3. Every unit of work needs an issue. Create missing ones via `/delegate` (assign to the lead's login for agent work, or to Yaseen for finance review).
4. Show the lead the plan (agents × issues × directories) and get a go-ahead.
5. Dispatch in **one message**, each Agent call with `isolation: "worktree"` and the matching `subagent_type`. Each prompt
   includes: issue number, acceptance criteria, owned directories, "branch from origin/main, finish with /ship-pr, do not merge".
6. As agents return: collect PR URLs, run `/review-pr` on each (or queue them for the lead), and report a table
   (issue → PR → tests → verdict). Merge order: contracts → engine → API → UI.
