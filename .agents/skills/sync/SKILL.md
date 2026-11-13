---
name: sync
description: Bring the local checkout up to date with GitHub (fetch, fast-forward main, rebase the current feature branch onto origin/main) without losing work. Use at the start of any task, whenever the session hook says the branch is behind origin/main, before opening or updating a PR, or when the user asks to "get the latest", "pull", or "update the repo".
---

# Sync with GitHub

Goal: you are building on the newest `origin/main`, and nothing uncommitted is lost.

1. `git fetch origin --prune`. If it fails (offline/auth), stop and tell the human. Suggest `gh auth login` / `gh auth setup-git`.
2. `git status --porcelain`. If there are uncommitted changes, **do not discard them**. Either commit them on the
   current feature branch (WIP commit) or `git stash push -m "sync-<date>"` and tell the human you stashed.
3. Current branch:
   - On `main`: `git merge --ff-only origin/main`. If that fails, local main has commits it should not have.
     Do NOT reset. Move them to a branch (`git switch -c <owner>/rescue-<date>`) and tell the human.
   - On a feature branch: `git rebase origin/main`. On conflicts, resolve only if the right answer is obvious and
     inside your workstream; otherwise `git rebase --abort` and explain the conflict in plain language.
     If the branch was already pushed, update it with `git push --force-with-lease` (never `--force`).
4. If you stashed, `git stash pop`.
5. Report in one or two lines: what changed upstream (`git log --oneline HEAD@{1}..HEAD` or the rebase range),
   and whether any files you were working on changed. Re-read those files before editing again.
6. If dependency files changed upstream (`pyproject.toml`, `requirements*.txt`, `package.json`, lockfiles), re-run install (`make setup`).
