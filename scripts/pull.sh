#!/usr/bin/env bash
# "git pull", done safely for FAULTLINE. Run before making ANY edits:   make pull
# - on main: fast-forward to the latest GitHub main
# - on a task branch: replay your work on top of the latest GitHub main (uncommitted edits are kept)
set -uo pipefail
cd "$(git rev-parse --show-toplevel)"

if ! git fetch origin --prune; then
  echo "Could not reach GitHub. Check your internet, then run: gh auth login"; exit 1
fi
mkdir -p .git/faultline && date +%s > .git/faultline/last_fetch

branch=$(git rev-parse --abbrev-ref HEAD)
if [ "$branch" = "main" ]; then
  git merge --ff-only origin/main || { echo "Your main has local changes it shouldn't. Ask Claude to run /sync."; exit 1; }
else
  if ! git rebase --autostash origin/main; then
    git rebase --abort
    echo "Your changes overlap with new changes on GitHub. Open Claude and say: run /sync and help me resolve it."; exit 1
  fi
fi
echo "Up to date with GitHub main ($(git rev-parse --short origin/main)) on branch $branch."
