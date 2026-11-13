#!/usr/bin/env python3
"""Self-test for scripts/guardrails/guard.py. Run: python3 scripts/test_guardrails.py"""
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
    for role, branch, cmd, want in CASES:
        guard.current_branch = lambda cwd=None, b=branch: b
        got = outcome(guard.check_bash, cmd, role)
        if got != want:
            failures += 1
            print(f"FAIL [{role}@{branch}] {cmd!r}: expected {want}, got {got}")
    # Fake git so these tests never touch the network: (fetch exit code, commits behind origin/main)
    import tempfile
    real_run, real_cache = guard.run, guard.CACHE_DIR
    guard.CACHE_DIR = Path(tempfile.mkdtemp())

    def fake_git(fetch_code: int, behind: int):
        def _run(cmd, timeout=10.0, cwd=None):
            if "fetch" in cmd:
                return fetch_code, ""
            if "rev-list" in cmd:
                return 0, str(behind)
            return real_run(cmd, timeout, cwd)
        return _run

    guard.run = fake_git(0, 0)
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

    total = len(CASES) + len(WRITE_CASES) + len(FRESH_CASES)
    print(f"guardrails: {total - failures}/{total} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
