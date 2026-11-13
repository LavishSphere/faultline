#!/usr/bin/env bash
# Manual version of what Claude Code runs automatically at session start:
#   bash scripts/agent-start.sh
# 1) installs the repo's git hooks (no commits/pushes to main)
# 2) syncs with GitHub (fetch, fast-forward clean main, report drift)
# 3) prints who you are working for (lead/partner) and your delegated tasks or PRs to review
# Claude Code also runs step 2-3 automatically via .claude/settings.json hooks.
set -uo pipefail
cd "$(git rev-parse --show-toplevel)"
if [ "$(git config --get core.hooksPath)" != ".githooks" ]; then
  git config core.hooksPath .githooks && echo "[faultline] installed git hooks from .githooks/"
fi
python3 scripts/guardrails/sync.py
