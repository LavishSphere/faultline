#!/usr/bin/env python3
"""FAULTLINE pull-request policy check (runs in CI on every PR event).

Rules come from `.agents/team.json` on the BASE branch, so a PR cannot loosen its own rules.

  1. At most `max_pr_commits` commits (default 3).
  2. No AI co-author trailers in any commit; no AI attribution line in the PR body.
  3. Title looks like `<area>: <what>`.
  4. Body closes an OPEN issue labeled `delegated` that a lead created (bots exempt).
     Partner PRs: the issue must be assigned to the PR author.
  5. Partners may not touch guardrail/config paths.
  6. Engine files changed without docs/MATH_MODEL.md -> the PR must tick "No formula change".

Exit 1 with a readable report if anything fails. Writes a summary to $GITHUB_STEP_SUMMARY.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import urllib.request

AI_TRAILER = re.compile(r"^\s*co-authored-by:.*\b(claude|anthropic)\b", re.I | re.M)
# An attribution LINE (as tools write it), not a sentence that merely mentions the rule.
AI_FOOTER = re.compile(
    r"^\W{0,4}(?:generated with \[?claude code|co-authored-by:.*\b(?:claude|anthropic)\b)", re.I | re.M)
CLOSES = re.compile(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#(\d+)\b", re.I)
TITLE = re.compile(r"^[a-z0-9][a-z0-9-]*(?:\([a-z0-9-]+\))?: \S")
PROTECTED = (".claude/", ".agents/", ".github/", ".githooks/", "scripts/guardrails/", "scripts/ci/",
             "scripts/setup-github.sh", "scripts/test_guardrails.py", "AGENTS.md", "CLAUDE.md", "docs/SPEC.md",
             "docs/WORKFLOW.md")
ENGINE = ("services/api/core/financials.py", "services/api/core/optimizer.py", "services/api/core/evaluator.py",
          "services/api/markets/normalize.py")
NO_FORMULA_BOX = re.compile(r"-\s*\[x\]\s*no formula", re.I)


def git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=False).stdout


def gh_issue(repo: str, number: int) -> dict | None:
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/issues/{number}",
        headers={"Authorization": f"Bearer {os.environ.get('GITHUB_TOKEN', '')}",
                 "Accept": "application/vnd.github+json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.load(r)
    except Exception:
        return None


def main() -> int:
    event = json.load(open(os.environ["GITHUB_EVENT_PATH"]))
    pr = event["pull_request"]
    repo = os.environ["GITHUB_REPOSITORY"]
    base_sha, head_sha = pr["base"]["sha"], pr["head"]["sha"]
    author = pr["user"]["login"]
    body = pr.get("body") or ""
    title = pr.get("title") or ""

    try:
        team = json.loads(git("show", f"{base_sha}:.agents/team.json"))
    except json.JSONDecodeError:
        team = {}
    leads = {x.lower() for x in team.get("leads", [])}
    partners = {x.lower() for x in team.get("partners", {})}
    limit = int(team.get("max_pr_commits", 3))
    is_bot = author.endswith("[bot]")
    is_partner = author.lower() in partners

    failures: list[str] = []
    notes: list[str] = []

    # 1. commit count
    n = int(pr.get("commits") or git("rev-list", "--count", f"{base_sha}..{head_sha}").strip() or 0)
    (failures if n > limit else notes).append(
        f"Commits: {n} (limit {limit})" + (": squash with `git reset --soft origin/main`, recommit, then `git push --force-with-lease`" if n > limit else ""))

    # 2. AI attribution
    msgs = git("log", "--format=%H%n%B%n--END--", f"{base_sha}..{head_sha}")
    if AI_TRAILER.search(msgs):
        failures.append("A commit has a `Co-Authored-By: Claude/Anthropic` trailer: remove it with `git commit --amend`, then force-push with lease")
    if AI_FOOTER.search(body):
        failures.append("PR description contains an AI attribution line (e.g. 'Generated with Claude Code'): delete it")

    # 3. title
    if not TITLE.match(title):
        failures.append(f"Title `{title}` should look like `<area>: <what>`, e.g. `finance: cash-flow engine (#2)`")

    # 4. linked delegated issue
    if is_bot:
        notes.append("Bot PR: issue-link rule skipped")
    else:
        nums = sorted({int(x) for x in CLOSES.findall(body)})
        if not nums:
            failures.append("PR body must close a delegated issue, e.g. `Closes #12`")
        for num in nums:
            iss = gh_issue(repo, num)
            if not iss:
                failures.append(f"#{num}: could not read the issue")
                continue
            if "pull_request" in iss:
                failures.append(f"#{num} is a PR, not an issue")
                continue
            labels = {l["name"] for l in iss.get("labels", [])}
            problems = []
            if iss.get("state") != "open":
                problems.append("is not open")
            if team.get("delegation_label", "delegated") not in labels:
                problems.append("lacks the `delegated` label")
            if iss["user"]["login"].lower() not in leads:
                problems.append(f"was created by {iss['user']['login']}, not a lead")
            if is_partner and author.lower() not in {a["login"].lower() for a in iss.get("assignees", [])}:
                problems.append(f"is not assigned to {author}")
            if problems:
                failures.append(f"#{num} " + ", ".join(problems))
            else:
                notes.append(f"Linked issue #{num}: delegated by {iss['user']['login']}")

    # 5/6. changed paths
    changed = [p for p in git("diff", "--name-only", f"{base_sha}...{head_sha}").splitlines() if p]
    if is_partner:
        bad = [p for p in changed if any(p == q.rstrip("/") or p.startswith(q) for q in PROTECTED)]
        if bad:
            failures.append("Partner PR touches lead-only files: " + ", ".join(bad))
    engine_changed = [p for p in changed if p in ENGINE]
    if engine_changed and "docs/MATH_MODEL.md" not in changed and not NO_FORMULA_BOX.search(body):
        failures.append("Engine files changed (" + ", ".join(engine_changed) + ") without docs/MATH_MODEL.md: "
                        "update the math doc, or tick `- [x] No formula change` in the PR body")
    if any(p.startswith("services/api/data/sealed_outcomes/") for p in changed):
        notes.append("::warning::PR changes sealed outcomes: reviewer must confirm nothing on the agent path reads them")

    report = ["## PR policy", ""] + [f"- ❌ {f}" for f in failures] + [f"- ✅ {x}" for x in notes if not x.startswith("::")]
    text = "\n".join(report)
    print(text)
    for x in notes:
        if x.startswith("::"):
            print(x)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as f:
            f.write(text + "\n")
    for f in failures:
        print(f"::error::{f}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
