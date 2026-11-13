#!/usr/bin/env python3
"""PreToolUse guard for FAULTLINE agents.

Blocks (exit 2, reason fed back to Claude):
  ALL roles   - pushing to / committing on a protected branch (main, ...)
              - force pushes (except --force-with-lease to a non-protected branch)
              - production deploys (vercel --prod, netlify --prod, fly deploy, railway up, ...)
              - changing GitHub repo settings/rules/collaborators via gh
  PARTNER     - merging PRs, closing/editing others' issues, approving PRs
              - editing guardrail/config files (.claude/, .github/, CODEOWNERS, docs/SPEC.md)

This is a best-effort local guardrail. The authoritative lock is the GitHub ruleset.
"""
from __future__ import annotations

import json
import re
import shlex
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import time

from _team import CACHE_DIR, PROJECT_DIR, current_branch, identity, load_team, repo_root, run  # noqa: E402

PARTNER_PROTECTED_PATHS = (
    ".claude/", ".agents/", ".github/", ".githooks/", "scripts/guardrails/", "scripts/ci/", "scripts/setup-github.sh",
    "scripts/test_guardrails.py", "scripts/agent-start.sh", "CODEOWNERS", "AGENTS.md", "CLAUDE.md",
    "docs/SPEC.md", "docs/WORKFLOW.md",
)
# git options that take a separate value and come before the subcommand
GIT_GLOBAL_WITH_VALUE = {"-c", "-C", "--git-dir", "--work-tree", "--namespace", "--exec-path", "--config-env"}
WRITE_HINTS = re.compile(r"(\brm\b|\bmv\b|\bcp\b|\bsed\s+-i|\btee\b|>|\bchmod\b|\btruncate\b|\bgit\s+(checkout|restore|rm)\b|\bperl\s+-[a-z]*i)")


def block(msg: str) -> None:
    print(f"BLOCKED by FAULTLINE guard: {msg}\n"
          "If a human lead truly needs this, they should do it themselves outside the agent. "
          "Otherwise follow docs/WORKFLOW.md (branch -> PR -> lead review).", file=sys.stderr)
    sys.exit(2)


def segments(cmd: str) -> list[list[str]]:
    out = []
    for part in re.split(r"&&|\|\||;|\||\n", cmd):
        part = part.strip()
        if not part:
            continue
        try:
            toks = shlex.split(part)
        except ValueError:
            toks = part.split()
        # drop leading env assignments / wrappers
        while toks and (re.match(r"^\w+=", toks[0]) or toks[0] in {"sudo", "command", "env", "npx", "pnpm", "bunx", "time"}):
            toks = toks[1:]
        if toks:
            out.append(toks)
    return out


def check_bash(cmd: str, role: str, cwd: str | None = None) -> None:
    team = load_team()
    protected = {b.lower() for b in team.get("protected_branches", ["main", "master"])}
    # Track the directory each segment runs in (hook `cwd`, then any `cd X` / `git -C X`),
    # so agents in git worktrees are judged by THEIR branch, not the main checkout's.
    here = Path(cwd) if cwd else PROJECT_DIR

    for t in segments(cmd):
        low = [x.lower() for x in t]
        head = low[0]
        if head == "cd" and len(t) > 1:
            here = (here / Path(t[1]).expanduser()).resolve()
            continue
        seg_dir = here
        if head == "git":
            for j in range(1, len(t) - 1):
                if not t[j].startswith("-"):
                    break
                if t[j] == "-C":
                    seg_dir = (seg_dir / Path(t[j + 1]).expanduser()).resolve()
        branch = current_branch(seg_dir).lower()

        if head == "git":
            # strip global options (`git -C dir -c k=v --no-pager push ...`) so they can't hide the subcommand
            if any("hookspath" in x for x in low):
                is_config = len(low) > 1 and low[1] == "config"
                reading = is_config and any(f in low for f in ("--get", "--get-all", "--list", "-l", "--show-origin"))
                setting_ours = is_config and low[-1] == ".githooks" and not any("unset" in x for x in low)
                if not (reading or setting_ours):
                    block("changing or overriding git hook configuration (core.hooksPath). Only `.githooks` is allowed.")
            i = 1
            while i < len(t) and t[i].startswith("-"):
                i += 2 if t[i] in GIT_GLOBAL_WITH_VALUE else 1
            t, low = ["git"] + t[i:], ["git"] + low[i:]
        if head == "git" and len(low) > 1:
            sub = low[1]
            if sub == "push":
                if "--no-verify" in low:
                    block("`git push --no-verify` skips the repo's git hooks.")
                args = [a for a in t[2:] if not a.startswith("-")]
                flags = [a for a in low[2:] if a.startswith("-")]
                if any(f in ("--all", "--mirror", "--delete", "-d") for f in flags):
                    block("`git push --all/--mirror/--delete` is not allowed for agents.")
                forced = any(f in ("--force", "-f") or (f.startswith("-") and not f.startswith("--") and "f" in f) for f in flags)
                refspecs = args[1:] if len(args) > 1 else []
                targets = set()
                for r in refspecs:
                    if r.startswith("+"):
                        forced = True
                        r = r[1:]
                    dst = r.split(":")[-1].lower().replace("refs/heads/", "")
                    targets.add(branch if dst == "head" else dst)
                if not refspecs:
                    targets.add(branch)
                if targets & protected:
                    block(f"pushing to a protected branch ({', '.join(sorted(targets & protected))}). Push your feature branch and open a PR with /ship-pr.")
                if forced:
                    block("force push. Use `git push --force-with-lease` on your own feature branch only if you rebased.")
            elif sub == "commit" and "--no-verify" in low or (sub == "commit" and "-n" in low):
                block("`git commit --no-verify` skips the repo's git hooks.")
            elif sub == "commit" and branch in protected:
                block(f"committing directly on `{branch}`. Create a branch first: `git switch -c <prefix>/<issue>-<slug>`.")
            elif sub == "commit" and "--amend" not in low:
                limit = int(team.get("max_pr_commits", 3))
                _, ahead = run(["git", "rev-list", "--count", f"origin/{team.get('default_branch', 'main')}..HEAD"], cwd=seg_dir)
                if ahead.isdigit() and int(ahead) >= limit:
                    block(f"this branch already has {ahead} commit(s); a PR may have at most {limit}. "
                          "Fold the change in with `git commit --amend`, or squash: "
                          "`git reset --soft origin/main` then make 1-3 meaningful commits.")
            elif sub == "merge" and branch in protected and "--ff-only" not in low:
                block(f"merging into `{branch}` locally. Merges to main happen on GitHub after lead review.")
            elif sub in ("rebase",) and branch in protected:
                block(f"rewriting `{branch}`.")

        if head == "gh" and len(low) > 1:
            sub = " ".join(low[1:3])
            if low[1] == "api":
                method = None
                for i, x in enumerate(low):
                    if x in ("-x", "--method") and i + 1 < len(low):
                        method = low[i + 1]
                    elif x.startswith("--method="):
                        method = x.split("=", 1)[1]
                mutates = (method and method != "get") or any(x in ("-f", "-F", "--field", "--raw-field", "--input") for x in low)
                if mutates and re.search(r"protection|rulesets|collaborators|branches|/merges|/merge\b|hooks|actions/secrets|environments|deployments|/pulls/\d+/reviews", " ".join(low)):
                    block("modifying GitHub repo settings, rules, merges, reviews, or deployments via the API.")
            if sub.startswith("repo edit") or sub.startswith("repo delete") or sub.startswith("repo rename") or low[1] in ("ruleset", "secret", "release"):
                if not (low[1] == "ruleset" and len(low) > 2 and low[2] in ("list", "view", "check")):
                    block(f"`gh {sub}` changes repository settings/releases.")
            if sub.startswith("pr merge"):
                if role != "lead":
                    block("partners never merge PRs. A lead reviews and merges on GitHub.")
            if sub.startswith("pr review") and role != "lead":
                block("partners do not approve or review PRs; leads do.")
            if role != "lead" and (sub.startswith("issue close") or sub.startswith("issue edit") or sub.startswith("issue delete") or sub.startswith("issue create")):
                block("partners do not create, close, or edit issues; leads delegate work. You may comment with `gh issue comment`.")

        joined = " ".join(low)
        if head in ("vercel", "netlify", "fly", "flyctl", "railway", "heroku", "firebase", "wrangler") or (head == "npm" and "deploy" in joined):
            if re.search(r"--prod\b|--production\b|\bdeploy\b|\bup\b|\bpublish\b|promote", joined):
                block("production deploys are done only by a lead after review (they deploy from `main`).")

    if role != "lead" and any(p.lower() in cmd.lower() for p in PARTNER_PROTECTED_PATHS) and WRITE_HINTS.search(cmd):
        block("partners cannot modify guardrail/config files (.claude/, .github/, CODEOWNERS, docs/SPEC.md). Ask a lead.")


FRESH_SECONDS = 10 * 60


def require_fresh(root: Path | None = None) -> None:
    """Partners must be on the latest GitHub main before editing: fetch if stale, block if behind."""
    stamp = CACHE_DIR / "last_fetch"
    try:
        age = time.time() - float(stamp.read_text())
    except (OSError, ValueError):
        age = float("inf")
    if age > FRESH_SECONDS:
        code, _ = run(["git", "fetch", "origin", "--prune", "--quiet"], timeout=20, cwd=root)
        if code != 0:
            block("couldn't reach GitHub to pull the latest changes before editing. "
                  "Ask the human to check their internet / run `gh auth login`, then try again.")
        try:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            stamp.write_text(str(time.time()))
        except OSError:
            pass
    _, behind = run(["git", "rev-list", "--count", "HEAD..origin/main"], cwd=root)
    if behind.isdigit() and int(behind) > 0:
        block(f"this copy is {behind} commit(s) behind GitHub main. Pull first: run the /sync procedure "
              "(or the human runs `make pull`), then redo this edit.")


def check_write(path_str: str, role: str) -> None:
    if role == "lead" or not path_str:
        return
    root = repo_root(Path(path_str).resolve())  # the worktree/checkout the file lives in
    try:
        rel = Path(path_str).resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return
    require_fresh(root)
    for p in PARTNER_PROTECTED_PATHS:
        if rel == p.rstrip("/") or rel.startswith(p):
            block(f"partners cannot edit `{rel}` (guardrail/config file). If it needs a change, describe it in the PR and a lead will make it.")


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError:
        sys.exit(0)
    tool = data.get("tool_name", "")
    ti = data.get("tool_input", {}) or {}
    role = identity()["role"]
    if tool == "Bash":
        check_bash(ti.get("command", ""), role, data.get("cwd"))
    elif tool in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
        check_write(ti.get("file_path") or ti.get("notebook_path", ""), role)
    sys.exit(0)


if __name__ == "__main__":
    main()
