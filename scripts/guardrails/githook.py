#!/usr/bin/env python3
"""Agent-agnostic git hooks (installed via core.hooksPath=.githooks by scripts/agent-start.sh).

Applies to anything that uses git in this clone: Claude Code or a human in the terminal.
  pre-commit: refuse commits on a protected branch (main, ...)
  pre-push:   refuse pushes that update a protected branch, or delete a remote branch

Human leads can override deliberately with  FAULTLINE_LEAD_OVERRIDE=1 git push ...
Agents are instructed never to set it, and the GitHub ruleset still blocks non-admins regardless.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _team import current_branch, load_team  # noqa: E402

ZERO = "0" * 40


def deny(msg: str) -> None:
    print(f"\n[faultline] {msg}\n"
          "Workflow: create a branch (git switch -c <you>/<issue>-<slug> origin/main), push it, open a PR; "
          "a lead reviews and merges.\nSee AGENTS.md / docs/WORKFLOW.md.\n", file=sys.stderr)
    sys.exit(1)


CLAUDE_TRAILER = re.compile(r"^\s*co-authored-by:.*\b(claude|anthropic)\b", re.I)


def strip_claude_trailer(path: str) -> None:
    """commit-msg: remove AI co-author trailers (team rule: commits are authored by the human only)."""
    p = Path(path)
    lines = [l for l in p.read_text().splitlines() if not CLAUDE_TRAILER.match(l)]
    while lines and not lines[-1].strip():
        lines.pop()
    p.write_text("\n".join(lines) + "\n")


def main() -> None:
    hook = sys.argv[1] if len(sys.argv) > 1 else ""
    if hook == "commit-msg" and len(sys.argv) > 2:
        strip_claude_trailer(sys.argv[2])  # applies to everyone, overrides included
        return
    if os.environ.get("FAULTLINE_LEAD_OVERRIDE") == "1":
        return
    protected = {b.lower() for b in load_team().get("protected_branches", ["main", "master"])}

    if hook == "pre-commit":
        b = current_branch().lower()
        if b in protected:
            deny(f"Commits directly on `{b}` are not allowed.")
    elif hook == "pre-push":
        for line in sys.stdin:
            parts = line.split()
            if len(parts) != 4:
                continue
            _local_ref, local_sha, remote_ref, _remote_sha = parts
            name = remote_ref.removeprefix("refs/heads/").lower()
            if local_sha == ZERO:
                deny(f"Deleting remote branch `{name}` from the command line is not allowed.")
            if name in protected:
                deny(f"Pushing to `{name}` is not allowed.")


if __name__ == "__main__":
    main()
