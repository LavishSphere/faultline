"""Shared helpers for FAULTLINE Claude Code hooks.

Role detection is FAIL-CLOSED: if we cannot prove the machine belongs to a lead,
the session is treated as `partner` (most restricted).

Note: these hooks only constrain Claude's tool calls on this machine. The real
lock is the GitHub ruleset on `main` (see scripts/setup-github.sh).
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

PROJECT_DIR = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[2])
TEAM_FILE = PROJECT_DIR / ".agents" / "team.json"
CACHE_DIR = PROJECT_DIR / ".git" / "faultline"
ROLE_CACHE = CACHE_DIR / "identity.json"
ROLE_TTL_SECONDS = 6 * 3600


def run(cmd: list[str], timeout: float = 10.0, cwd: Path | str | None = None) -> tuple[int, str]:
    try:
        p = subprocess.run(
            cmd,
            cwd=cwd or PROJECT_DIR,
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "GH_PROMPT_DISABLED": "1"},
        )
        return p.returncode, (p.stdout or "").strip()
    except (OSError, subprocess.TimeoutExpired):
        return 1, ""


def load_team() -> dict:
    try:
        return json.loads(TEAM_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        return {"leads": [], "partners": {}, "protected_branches": ["main", "master"], "default_branch": "main"}


def identity() -> dict:
    """Return {"login": str|None, "role": "lead"|"partner", "name": str}."""
    team = load_team()
    try:
        cached = json.loads(ROLE_CACHE.read_text())
        if time.time() - cached.get("ts", 0) < ROLE_TTL_SECONDS:
            return _apply_override(cached, team)
    except (OSError, json.JSONDecodeError):
        pass

    login = None
    code, out = run(["gh", "api", "user", "--jq", ".login"], timeout=8)
    if code == 0 and out:
        login = out
    else:
        code, out = run(["git", "config", "--get", "github.user"])
        login = out or None

    leads = {l.lower() for l in team.get("leads", [])}
    partners = {k.lower(): v for k, v in team.get("partners", {}).items()}
    if login and login.lower() in leads:
        ident = {"login": login, "role": "lead", "name": login}
    else:
        p = partners.get((login or "").lower(), {})
        ident = {"login": login, "role": "partner", "name": p.get("name", login or "unknown")}

    ident["ts"] = time.time()
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        ROLE_CACHE.write_text(json.dumps(ident))
    except OSError:
        pass
    return _apply_override(ident, team)


def _apply_override(ident: dict, team: dict) -> dict:
    # FAULTLINE_ROLE may only make a session MORE restrictive (lead -> partner), never less.
    if os.environ.get("FAULTLINE_ROLE", "").lower() == "partner":
        ident = {**ident, "role": "partner"}
    return ident


def current_branch(cwd: Path | str | None = None) -> str:
    """Branch checked out in `cwd` (a worktree has its own HEAD), defaulting to the project dir."""
    _, out = run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=cwd)
    return out


def repo_root(path: Path | str | None) -> Path:
    """Top level of the checkout/worktree containing `path`, else the project dir."""
    p = Path(path) if path else PROJECT_DIR
    d = p if p.is_dir() else p.parent
    while not d.exists() and d != d.parent:
        d = d.parent
    code, out = run(["git", "rev-parse", "--show-toplevel"], cwd=d)
    return Path(out) if code == 0 and out else PROJECT_DIR
