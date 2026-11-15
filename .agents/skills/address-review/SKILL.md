---
name: address-review
description: Fix a pull request after a lead's review or a red CI check - read the review, change only what was asked, fold the fix into the existing commits (3-commit limit), force-push with lease, wait for CI, and reply on the PR point by point. Use when the session banner lists a PR under "FIX THESE FIRST", or the user says "address the review", "the lead asked for changes", "fix my PR", or "CI is red on my PR".
argument-hint: "[PR number]"
---

# Address a review (fix an open PR)

A PR with changes requested or red CI cannot merge, and everything queued behind it waits. These come before any new task.

## 1. Find the PR and read exactly what was asked
- No number given: `gh pr list --author @me --state open --json number,title,reviewDecision,headRefName` and take the ones with
  `CHANGES_REQUESTED` or failing checks (`gh pr checks <N>`), oldest first. Several? Do them one at a time.
- Read all three places a reviewer writes:
  ```bash
  gh pr view <N> --json title,headRefName,reviews,comments,closingIssuesReferences
  gh api repos/{owner}/{repo}/pulls/<N>/comments --jq '.[] | "\(.path):\(.line) \(.body)"'    # line-by-line comments
  gh pr checks <N>                                                                             # which check is red
  ```
- Write the requested changes as a numbered list. For a partner, restate each one in finance/math terms. If an item is a
  judgment call about a financial assumption, **ask the human before changing it**; the finance owner decides those.
- Blocking items are required. Nits are optional: do them only if they are quick.

## 2. Get on the branch, up to date
- `git fetch origin --prune`, `git switch <headRefName>` (if another worktree has it checked out, work there).
- Run the `sync` procedure so the branch sits on the latest `origin/main`.

## 3. Fix only what was asked
- Stay inside the review items and the issue's Files in scope. Anything else you notice goes under "Follow-ups" in the reply.
- If CI is red: `gh run view --log-failed` (or reproduce with `make test`), then fix the cause. Never skip, weaken, or delete a test to get green.
- Add or adjust a test for each behavioral fix.

## 4. Keep the commit count ≤ 3 and push
- Branch has fewer than 3 commits: one new commit `<area>: address review (#N)` is fine and is easiest for the reviewer to read.
- Branch already has 3: fold the fix into the last one with `git commit --amend --no-edit`. The guard blocks a 4th commit.
- `make test` (and `make check` if `apps/web` changed), then the `honesty-audit` procedure on the diff.
- `git push --force-with-lease origin HEAD`. Never `--force`.
- `gh pr checks <N> --watch --fail-fast`. Stay until it is green.

## 5. Reply on the PR, point by point
`gh pr comment <N> --body-file <tmp>` with the reviewer's numbered items and, under each, what changed (file:line) and how it
was verified, or why it was not changed. Then tell the human: PR URL, CI state, and that it is back with the lead.
Do not re-request review through the API, do not approve, do not merge.
