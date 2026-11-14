---
name: ship-pr
description: Finish a task by verifying it, rebasing on the latest origin/main, pushing the feature branch, opening (or updating) a pull request for lead review, and waiting for CI to go green. Use when work on a task is done, when the user says "open a PR", "submit", "ship it", or "I'm done". Never merges and never deploys.
---

# Ship a PR (never merge, never deploy)

A PR is only useful once it merges, and a lead can only merge a green one. Hand off a PR that is ready to merge, not one that needs another round.

0. **Rules:** at most 3 commits on the branch (`git rev-list --count origin/main..HEAD`; if over, `git reset --soft origin/main`
   and recommit as 1–3), and no AI attribution (`Co-Authored-By: Claude`, "Generated with Claude Code") in commits or the PR body.
1. **Sync first:** run the `sync` procedure (fetch + rebase onto `origin/main`). Doing this before the tests means you test once, on what will be pushed.
2. **Verify**
   - `make test` and, if the diff touches `apps/web`, `make check`.
   - Fix failures that are inside the task's scope. If something outside scope fails, report it; do not paper over it.
   - Run the `honesty-audit` procedure on your diff.
   - If a formula changed, confirm `docs/MATH_MODEL.md` was updated in this branch.
3. **Push the feature branch only.**
   - First push: `git push -u origin HEAD`.
   - Branch already on GitHub and you rebased or amended: `git push --force-with-lease origin HEAD`. A plain push is
     rejected here, and `--force` is blocked. Never push `main`.
4. **Open the PR**, or update the existing one (`gh pr view --json url,number` tells you if there is one):
   ```
   gh pr create --base main --head <branch> --title "<area>: <what> (#N)" --body-file <tmpfile> --label ws:<area>
   ```
   Body follows `.github/pull_request_template.md`: `Closes #N`, what changed, how verified (commands + results),
   what is NOT verified, data provenance labels touched, follow-ups. Do not tick review boxes for the lead.
   Write the body completely the first time: every later edit of the title or body re-runs all of CI.
5. **Wait for CI** (about 90 seconds): `gh pr checks <PR> --watch --fail-fast`.
   - Red: read the failing job (`gh run view --log-failed`), fix, `git commit --amend`, `git push --force-with-lease origin HEAD`, watch again.
   - Do not hand off a red PR. If you cannot get it green, say exactly which check fails and why.
6. **Hand off:** tell the human the PR URL, that CI is green, and in plain language what the lead should look at first.
   Then stop. Do not run `gh pr merge`, do not approve, do not deploy, do not close the issue.

If the lead requests changes later, use the `address-review` procedure.
