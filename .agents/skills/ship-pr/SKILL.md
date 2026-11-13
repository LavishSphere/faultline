---
name: ship-pr
description: Finish a task by verifying it, rebasing on the latest origin/main, pushing the feature branch, and opening (or updating) a pull request for lead review. Use when work on a task is done, when the user says "open a PR", "submit", "ship it", or "I'm done". Never merges and never deploys.
---

# Ship a PR (never merge, never deploy)

0. **Rules:** at most 3 commits on the branch (`git rev-list --count origin/main..HEAD`; squash with `git reset --soft origin/main` if over), and no `Co-Authored-By: Claude` trailers.
1. **Verify**
   - `make test` (or `cd services/api && python -m pytest -q`) and, if `apps/web` exists, `make check`.
   - Fix failures that are inside the task's scope. If something outside scope fails, report it; do not paper over it.
   - Run the `honesty-audit` checklist on your diff (`git diff origin/main...HEAD`).
   - If a formula changed, confirm `docs/MATH_MODEL.md` was updated in this branch.
2. **Sync:** run `/sync` (fetch + rebase onto `origin/main`), then re-run tests if anything upstream changed.
3. **Push the feature branch only:** `git push -u origin HEAD` (the guard hook blocks protected branches).
4. **Open the PR** (or update it if one exists: `gh pr view --json url` first):
   ```
   gh pr create --base main --head <branch> --title "<area>: <what> (#N)" --body-file <tmpfile>
   ```
   Body follows `.github/pull_request_template.md`: `Closes #N`, what changed, how verified (commands + results),
   what is NOT verified, data provenance labels touched, follow-ups. Do not tick review boxes for the lead.
   Add the workstream label: `gh pr edit --add-label ws:<area>`.
5. **Hand off:** tell the human the PR URL and, in plain language, what the lead should look at first.
   Then stop. Do not run `gh pr merge`, do not approve, do not deploy, do not close the issue.

If the lead requests changes later: `/sync`, address each review comment in new commits, push, and reply on the PR
summarizing what changed.
