---
name: merge-queue
description: Lead-only. Triage every open pull request in one pass - who each one waits on, its risk tier, which files overlap with other open PRs, what it unblocks - and produce a merge order, then review and (when the lead says so) merge in that order. Use when a lead says "what's waiting for review", "clear the queue", "what should I merge", "triage the PRs", when the session banner says the review queue is the bottleneck, and before dispatching any new sprint.
argument-hint: "[PR numbers, optional]"
---

# Merge queue (leads only)

The session banner must say role = LEAD. Agents open PRs faster than one lead can review them, so the queue, not the
writing, decides what makes the demo. This procedure gets the most valuable green PRs merged first and keeps the rest from rotting.

## 1. Snapshot (two calls, not one per PR)
```bash
gh pr list --state open --limit 40 --json number,title,author,headRefName,isDraft,reviewDecision,mergeable,additions,deletions,updatedAt,files,closingIssuesReferences,statusCheckRollup
gh issue list --state open --limit 100 --label delegated --json number,title,assignees,body
```

## 2. Classify each PR
- **Waits on:** *author* (changes requested, or `checks` red on the latest run) · *CI* (running) · *lead* (green, not a draft). Drafts are parked.
- **Tier** A / B / C from its files (table in `review-pr`, paths in `.agents/team.json` → `integrity_core`).
- **Unblocks:** open issues whose `**Starts after:**` line names this PR or the issue it closes. More is better.
- **Overlap:** files it shares with other open PRs (group the `files` lists by path). `shared_files` in `team.json`
  (`services/api/main.py`, `models.py`, `apps/web/lib/api.ts`) overlap constantly; those PRs must merge one after another.
- **Stale:** `mergeable` = `CONFLICTING`, or a file it changes was changed on `main` after its CI ran.

## 3. Order
Only PRs that wait on a lead are ordered. Sort by:
1. On the golden demo path (SPEC §2) before anything else; P1 and polish last.
2. Unblocks the most waiting issues.
3. Inside an overlap group: contracts → engine → API → UI, smallest first so the later rebases are small.
4. Tier C and small tier B first among equals: they take minutes and shrink the queue.
5. Oldest.

Show the lead one table and wait for a go:
`order | PR | closes | by | tier | +/- | overlaps with | unblocks | next action`
then two short lists: **waiting on the author** (PR, what is needed) and **parked** (drafts, holds). Say plainly if the
queue cannot clear before the next deadline in the banner, and which PRs you would drop or park.

## 4. Work the queue in order
- Review each with the `review-pr` procedure at its tier. Tier-A audits for PRs that do not overlap can run in parallel (≤ 3).
- **Merge only when the lead says so in this session** ("merge the ones that pass" counts; an old go-ahead does not).
  - Partner PR: `gh pr review <N> --approve` then `gh pr merge <N> --squash`.
  - Lead-authored PR: GitHub will not let the lead approve it, so the gate is the audit plus green CI, and the merge is
    `gh pr merge <N> --squash --admin`. Say this in the merge report; it is a bypass of the approval rule, not an approval.
- **After every merge:** `git fetch origin`, then re-check the PRs that overlapped it
  (`gh pr view <M> --json mergeable,statusCheckRollup`). If one now conflicts, tell its author right away with a PR comment
  (`needs a rebase onto main after #<N>; run address-review`) or resume the agent that wrote it. Do not review it until it is rebased and green.
- A PR that should not merge yet (for example a deploy waiting on DNS) goes to draft, `gh pr ready <N> --undo`, with a
  comment saying what it waits for. Then it stops showing up as work for the lead.

## 5. Housekeeping (after a batch of merges)
Agent worktrees are about 0.5 GB each once `node_modules` is installed. Remove the ones whose branch has merged and that are clean:
```bash
merged=$(gh pr list --state merged --limit 200 --json headRefName --jq '.[].headRefName')
git worktree list --porcelain | awk '/^worktree /{w=$2} /^branch /{sub("refs/heads/","",$2); print w"\t"$2}' |
while IFS=$'\t' read -r w b; do
  echo "$merged" | grep -qxF "$b" || continue
  [ -z "$(git -C "$w" status --porcelain)" ] && git worktree remove "$w" && echo "removed $w ($b)"
done
git worktree prune
```
`git worktree remove` refuses a locked worktree (an agent is using it) or one with uncommitted files. Leave those; never add `--force`.

## 6. Report
What merged (PR → issue), what went back to its author and why, what is parked, which issues are now unblocked, and
the next three PRs in the queue.
