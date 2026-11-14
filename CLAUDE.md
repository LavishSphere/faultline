@AGENTS.md

## Claude Code specifics
- `scripts/agent-start.sh` runs automatically: `.claude/settings.json` hooks run `scripts/guardrails/sync.py` at session
  start (and re-fetch every ~10 min on prompts), and `scripts/guardrails/guard.py` checks every Bash/Edit/Write call.
  If the guard blocks something, don't look for another route to do it; tell the human what was blocked and why.
- Skills load from `.claude/skills/` (a symlink to `.agents/skills/`): invoke as `/sync`, `/start-task`, `/ship-pr`,
  `/address-review`, and for leads `/merge-queue`, `/review-pr`, `/delegate`, `/sprint`. `/delegate` and `/sprint` only run when
  a human types them; to follow one mid-task, read its `SKILL.md`.
- Specialist subagents in `.claude/agents/`: `backend-engineer`, `finance-modeler`, `market-data-engineer`,
  `frontend-designer`, `research-curator`, and the read-only `integrity-auditor`. For parallel work use worktree isolation.
