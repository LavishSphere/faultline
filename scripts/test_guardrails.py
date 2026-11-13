#!/usr/bin/env python3
"""Self-test for scripts/guardrails/ (guard.py blocking rules, sync.py banner helpers). Run: python3 scripts/test_guardrails.py"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "guardrails"))
import guard  # noqa: E402


def outcome(fn, *args) -> str:
    import contextlib
    import io
    try:
        with contextlib.redirect_stderr(io.StringIO()):
            fn(*args)
        return "allow"
    except SystemExit as e:
        return "block" if e.code == 2 else "allow"


CASES = [
    # (role, branch, command, expected)
    ("lead", "ash/1-x", "git push origin main", "block"),
    ("lead", "ash/1-x", "git push origin HEAD:main", "block"),
    ("lead", "main", "git push", "block"),
    ("lead", "main", "git commit -m wip", "block"),
    ("lead", "ash/1-x", "git status && git push origin main", "block"),
    ("lead", "ash/1-x", "git push --force origin ash/1-x", "block"),
    ("lead", "ash/1-x", "git push origin +ash/1-x", "block"),
    ("lead", "ash/1-x", "npx vercel --prod", "block"),
    ("lead", "ash/1-x", "gh api -X PUT repos/o/r/branches/main/protection", "block"),
    ("lead", "ash/1-x", "gh repo edit --visibility public", "block"),
    ("lead", "ash/1-x", "git push -u origin ash/1-x", "allow"),
    ("lead", "ash/1-x", "git push --force-with-lease origin ash/1-x", "allow"),
    ("lead", "ash/1-x", "gh pr merge 3 --squash", "allow"),
    ("lead", "ash/1-x", "gh api repos/o/r/rulesets", "allow"),
    ("lead", "ash/1-x", "git -C . push origin main", "block"),
    ("lead", "ash/1-x", "git -c core.hooksPath=/dev/null push origin ash/1-x", "block"),
    ("lead", "ash/1-x", "git --no-pager push origin HEAD:main", "block"),
    ("lead", "ash/1-x", "git push --no-verify origin ash/1-x", "block"),
    ("lead", "ash/1-x", "git commit --no-verify -m x", "block"),
    ("lead", "ash/1-x", "git config --unset core.hooksPath", "block"),
    ("lead", "ash/1-x", "git config core.hooksPath .githooks", "allow"),
    ("lead", "ash/1-x", "git config --get core.hooksPath", "allow"),
    ("lead", "ash/1-x", "git commit -m 'fix -n flag parsing'", "allow"),
    ("partner", "yaseen/2-cash", "rm AGENTS.md", "block"),
    ("partner", "yaseen/2-cash", "cp x .githooks/pre-push", "block"),
    ("partner", "yaseen/2-cash", "gh pr merge 3", "block"),
    ("partner", "yaseen/2-cash", "gh pr review 3 --approve", "block"),
    ("partner", "yaseen/2-cash", "gh issue create -t x", "block"),
    ("partner", "yaseen/2-cash", "rm .claude/settings.json", "block"),
    ("partner", "yaseen/2-cash", "sed -i '' s/a/b/ .github/CODEOWNERS", "block"),
    ("partner", "yaseen/2-cash", "git push -u origin yaseen/2-cash", "allow"),
    ("partner", "yaseen/2-cash", "gh pr create --fill", "allow"),
    ("partner", "yaseen/2-cash", "gh issue comment 2 --body hi", "allow"),
    ("partner", "yaseen/2-cash", "cat .agents/team.json", "allow"),
    ("partner", "yaseen/2-cash", "python -m pytest -q", "allow"),
]

WRITE_CASES = [
    ("partner", "scripts/guardrails/guard.py", "block"),
    ("partner", "docs/SPEC.md", "block"),
    ("partner", ".github/workflows/ci.yml", "block"),
    ("partner", "services/api/core/financials.py", "allow"),
    ("partner", "docs/MATH_MODEL.md", "allow"),
    ("lead", ".claude/settings.json", "allow"),
]


def main() -> int:
    failures = 0
    # Fake git so these tests never touch the network or depend on the real branch:
    # (fetch exit code, commits behind origin/main, commits ahead of origin/main)
    import tempfile
    real_run, real_cache = guard.run, guard.CACHE_DIR
    guard.CACHE_DIR = Path(tempfile.mkdtemp())

    def fake_git(fetch_code: int, behind: int, ahead: int = 0):
        def _run(cmd, timeout=10.0, cwd=None):
            if "fetch" in cmd:
                return fetch_code, ""
            if "rev-list" in cmd:
                return 0, str(ahead if cmd[-1].endswith("..HEAD") else behind)
            return real_run(cmd, timeout, cwd)
        return _run

    guard.run = fake_git(0, 0)
    for role, branch, cmd, want in CASES:
        guard.current_branch = lambda cwd=None, b=branch: b
        got = outcome(guard.check_bash, cmd, role)
        if got != want:
            failures += 1
            print(f"FAIL [{role}@{branch}] {cmd!r}: expected {want}, got {got}")

    # Max 3 commits per PR (amend is always allowed)
    LIMIT_CASES = [
        (2, "git commit -m third", "allow"),
        (3, "git commit -m fourth", "block"),
        (3, "git commit --amend --no-edit", "allow"),
    ]
    guard.current_branch = lambda cwd=None: "ash/9-x"
    for ahead, cmd, want in LIMIT_CASES:
        guard.run = fake_git(0, 0, ahead)
        got = outcome(guard.check_bash, cmd, "lead")
        if got != want:
            failures += 1
            print(f"FAIL commit-limit ahead={ahead} {cmd!r}: expected {want}, got {got}")
    guard.run = fake_git(0, 0)

    # commit-msg hook strips AI co-author trailers
    import githook
    msg = Path(tempfile.mkdtemp()) / "MSG"
    msg.write_text("finance: x (#2)\n\nbody\n\nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>\n")
    githook.strip_claude_trailer(str(msg))
    if "Co-Authored-By" in msg.read_text() or not msg.read_text().startswith("finance: x (#2)\n\nbody"):
        failures += 1
        print(f"FAIL commit-msg strip: {msg.read_text()!r}")
    for role, rel, want in WRITE_CASES:
        got = outcome(guard.check_write, str(guard.PROJECT_DIR / rel), role)
        if got != want:
            failures += 1
            print(f"FAIL [{role}] write {rel}: expected {want}, got {got}")

    # Pull-before-edit gate (partners only)
    fin = str(guard.PROJECT_DIR / "services/api/core/financials.py")
    FRESH_CASES = [
        ("partner", 0, 3, "block"),   # behind origin/main -> must pull first
        ("partner", 1, 0, "block"),   # cannot reach GitHub -> cannot confirm latest
        ("partner", 0, 0, "allow"),   # up to date
        ("lead", 0, 3, "allow"),      # leads are not gated
    ]
    for role, fetch_code, behind, want in FRESH_CASES:
        guard.run = fake_git(fetch_code, behind)
        (guard.CACHE_DIR / "last_fetch").unlink(missing_ok=True)
        got = outcome(guard.check_write, fin, role)
        if got != want:
            failures += 1
            print(f"FAIL fresh-gate [{role}] fetch={fetch_code} behind={behind}: expected {want}, got {got}")
    guard.run, guard.CACHE_DIR = real_run, real_cache

    # Session banner helpers (scripts/guardrails/sync.py): pure functions, no network
    import sync
    from datetime import datetime, timezone

    def pr(n, login="YaseenAhmad12", review="REVIEW_REQUIRED", checks=(("SUCCESS", "2026-11-13T10:00:00Z"),), closes=(), draft=False):
        roll = [{"name": "checks", "status": "COMPLETED", "conclusion": c, "startedAt": at} for c, at in checks]
        return {"number": n, "title": f"t{n}", "author": {"login": login}, "isDraft": draft, "reviewDecision": review,
                "statusCheckRollup": roll, "closingIssuesReferences": [{"number": c} for c in closes]}

    rerun = (("FAILURE", "2026-11-13T10:00:00Z"), ("SUCCESS", "2026-11-13T11:00:00Z"))  # the latest run wins
    prs = [pr(54, review="CHANGES_REQUESTED", closes=(20,)), pr(69, closes=(17,)), pr(43, checks=(("FAILURE", "x"),)),
           pr(76, login="LavishSphere", checks=rerun), pr(5, review="APPROVED"), pr(6, draft=True),
           pr(7, checks=())]
    issues = [{"number": 17, "title": "a", "body": ""}, {"number": 20, "title": "b", "body": ""},
              {"number": 47, "title": "c", "body": "**Starts after:** #17 merged, #29 merged"},
              {"number": 78, "title": "d", "body": "**Starts after:** #29 merged"}, {"number": 79, "title": "e", "body": None}]
    rows, ready = sync.task_rows(issues, prs, {"17": "OPEN", "29": "MERGED"})
    team = {"deadlines": [{"at": "2026-11-14T13:00:00-05:00", "name": "practice demos", "when": "Sat 1pm ET"},
                          {"at": "2026-11-15T11:00:00-05:00", "name": "code freeze", "when": "Sun 11am ET", "after": "CODE FREEZE."}]}
    before = "\n".join(sync.deadline_lines(team, datetime(2026, 11, 13, 21, 0, tzinfo=timezone.utc)))
    after = "\n".join(sync.deadline_lines(team, datetime(2026, 11, 15, 17, 0, tzinfo=timezone.utc)))
    queue = "\n".join(sync.lead_queue_lines(prs))
    mine = "\n".join(sync.partner_pr_lines(prs, "yaseenahmad12"))
    BANNER_CASES = [
        ("waits_on", [sync.waits_on(p) for p in prs], ["author", "review", "author", "review", "merge", "draft", "ci"]),
        ("why_author", [sync.why_author(prs[0]), sync.why_author(prs[2])], ["changes requested", "CI red"]),
        ("starts_after", sync.starts_after("x\n**Starts after:** #64 merged, #65 merged\n#99"), ["64", "65"]),
        ("task status", [r.rsplit("(", 1)[1] for r in rows],
         ["in review: PR #69)", "PR #54 needs fixes)", "waiting on #17)", "ready)", "ready)"]),
        ("ready count excludes tasks that already have a PR", ready, 2),
        ("deadline countdown", "practice demos in 21h 00m (Sat 1pm ET); code freeze in 1d 19h" in before, True),
        ("deadline passed", after.startswith("- PASSED: code freeze (Sun 11am ET). CODE FREEZE.") and "Clock" not in after, True),
        ("bad deadline entry is skipped", sync.deadline_lines({"deadlines": [{"at": "soon"}, {}]}), []),
        ("lead queue counts", "Open PRs: 7. 3 wait on a lead, 2 wait on their author, 2 not ready" in queue, True),
        ("lead queue keeps author-blocked PRs out of the review list",
         queue.index("#54 t54") > queue.index("Waiting on the author") > queue.index("#69 t69"), True),
        ("partner sees fixes first", mine.index("FIX THESE FIRST") < mine.index("#54") < mine.index("waiting for the lead"), True),
        ("partner list is only their PRs", "#76" in mine, False),
        ("no PRs", sync.lead_queue_lines([]), ["- Open PRs: none."]),
    ]
    for name, got, want in BANNER_CASES:
        if got != want:
            failures += 1
            print(f"FAIL banner {name}: expected {want!r}, got {got!r}")

    total = len(CASES) + len(WRITE_CASES) + len(FRESH_CASES) + len(LIMIT_CASES) + 1 + len(BANNER_CASES)
    print(f"guardrails: {total - failures}/{total} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
