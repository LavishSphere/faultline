#!/usr/bin/env python3
"""Scan ADDED lines (PR) or all tracked files (push) for secrets and dishonest claims.

  python3 scripts/ci/content_scan.py secrets <base_sha> <head_sha>
  python3 scripts/ci/content_scan.py honesty <base_sha> <head_sha>
  python3 scripts/ci/content_scan.py --self-test

Suppress a deliberate honesty hit with an inline comment containing `honesty-ok: <reason>`.
Secrets cannot be suppressed: remove them and rotate the key.
"""
from __future__ import annotations

import re
import subprocess
import sys

SECRETS = {
    "Anthropic API key": re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}"),
    "OpenAI API key": re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9]{32,}"),
    "Tavily API key": re.compile(r"\btvly-[A-Za-z0-9]{20,}"),
    "GitHub token": re.compile(r"\b(?:ghp|gho|ghs|ghu|github_pat)_[A-Za-z0-9_]{30,}"),
    "AWS access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "Private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
    "Slack token": re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}"),
}
HONESTY = {
    "headline accuracy/win-rate claim": re.compile(r"\b\d{1,3}(?:\.\d+)?\s?%\s*(?:accuracy|accurate|win rate|hit rate)\b", re.I),
    "superiority claim vs market/VCs": re.compile(
        r"\b(?:beat|beats|beating|outperform(?:s|ed|ing)?)\s+(?:the\s+)?(?:market|markets|kalshi|polymarket|vcs?|a16z|sequoia|bessemer|link ventures)\b", re.I),
    "VC accuracy score": re.compile(r"\bvc\s+(?:accuracy|score|prediction)\b", re.I),
    "fake live/thinking state": re.compile(r"(?:setTimeout|sleep)\([^)]*\)[^\n]*(?:result|answer|prediction|forecast)", re.I),
}
RANDOM_IN_ENGINE = re.compile(r"\b(?:Math\.random|random\.(?:random|uniform|choice|randint|gauss))\b")
SKIP_SUFFIX = (".lock", "package-lock.json", ".min.js", ".svg", ".png", ".jpg", ".woff2")
HONESTY_SKIP = ("docs/", "scripts/ci/", ".agents/skills/", "AGENTS.md", "CLAUDE.md", ".github/")


def added_lines(base: str, head: str) -> list[tuple[str, int, str]]:
    diff = subprocess.run(["git", "diff", "-U0", "--no-color", f"{base}...{head}"], capture_output=True, text=True).stdout
    out, path, lineno = [], None, 0
    for line in diff.splitlines():
        if line.startswith("+++ "):
            path = line[6:] if line.startswith("+++ b/") else None
        elif line.startswith("@@"):
            m = re.search(r"\+(\d+)", line)
            lineno = int(m.group(1)) if m else 0
        elif line.startswith("+") and path:
            out.append((path, lineno, line[1:]))
            lineno += 1
    return out


def all_lines() -> list[tuple[str, int, str]]:
    out = []
    for path in subprocess.run(["git", "ls-files"], capture_output=True, text=True).stdout.splitlines():
        try:
            for i, line in enumerate(open(path, encoding="utf-8", errors="ignore"), 1):
                out.append((path, i, line.rstrip("\n")))
        except (IsADirectoryError, FileNotFoundError):
            pass
    return out


def scan(kind: str, lines: list[tuple[str, int, str]]) -> list[str]:
    hits = []
    for path, n, text in lines:
        if path.endswith(SKIP_SUFFIX):
            continue
        if kind == "secrets":
            for name, rx in SECRETS.items():
                if rx.search(text):
                    hits.append(f"{path}:{n}: {name}")
        else:
            if "honesty-ok:" in text or path.startswith(HONESTY_SKIP) or "/tests/" in path or path.startswith("tests/"):
                continue
            for name, rx in HONESTY.items():
                if rx.search(text):
                    hits.append(f"{path}:{n}: {name}: {text.strip()[:120]}")
            if (path.startswith("services/api/core/") or path.startswith("apps/web/")) and RANDOM_IN_ENGINE.search(text):
                hits.append(f"{path}:{n}: randomness in deterministic engine/UI: {text.strip()[:120]}")
    return hits


def self_test() -> int:
    bad = [("a.py", 1, 'KEY="sk-ant-api03-' + "x" * 30 + '"'), ("b.tsx", 2, "<h1>Our AI beats the market</h1>"),
           ("c.tsx", 3, "const acc = '87% accuracy'"), ("services/api/core/x.py", 4, "p = random.random()")]
    good = [("d.tsx", 5, "label: 'No improvement measured'"), ("e.tsx", 6, "beats the market // honesty-ok: quoting a critic"),
            ("services/api/tests/t.py", 7, "assert '87% accuracy' not in html")]
    s, h = scan("secrets", bad), scan("honesty", bad)
    ok = len(s) == 1 and len(h) == 3 and not scan("honesty", good) and not scan("secrets", good)
    print("content_scan self-test:", "ok" if ok else f"FAILED secrets={s} honesty={h}")
    return 0 if ok else 1


def main() -> int:
    if sys.argv[1:] == ["--self-test"]:
        return self_test()
    kind = sys.argv[1]
    lines = added_lines(sys.argv[2], sys.argv[3]) if len(sys.argv) > 3 else all_lines()
    hits = scan(kind, lines)
    for h in hits:
        print(f"::error::{kind}: {h}")
    print(f"{kind} scan: {len(hits)} finding(s) in {len(lines)} line(s)")
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main())
