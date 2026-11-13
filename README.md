# FAULTLINE

**Test the decision before you live with it.** A time-aware decision-intelligence and financial stress-testing platform
with a sealed historical Blind Replay, a deterministic business simulator + MILP optimizer, and honest forecast scoring.

> Status: hackathon MVP under construction. Run instructions will appear here as the app lands.

- Product spec: [docs/SPEC.md](docs/SPEC.md)
- Math model: [docs/MATH_MODEL.md](docs/MATH_MODEL.md)
- Team workflow: [docs/WORKFLOW.md](docs/WORKFLOW.md) · Partner guide: [docs/PARTNER_GUIDE.md](docs/PARTNER_GUIDE.md)

## Working with Claude Code
Rules for every agent: [AGENTS.md](AGENTS.md). First command of every session: `bash scripts/agent-start.sh`
(installs git hooks, syncs with GitHub, shows your role and tasks). Skills live in `.agents/skills/`.
In Claude Code: `/sync`, `/start-task`, `/ship-pr` (everyone) · `/delegate`, `/review-pr`, `/sprint` (leads).
Guardrail self-test: `make guard-test`.
