#!/usr/bin/env python3
"""Keep every agent working on the latest GitHub state.

SessionStart (full):   git fetch, fast-forward a clean `main`, report branch drift,
                       announce who this session works for, list delegated tasks / PRs.
UserPromptSubmit (--quick): at most every 10 minutes, fetch again and speak up ONLY
                       if the local checkout has fallen behind origin/main.

Whatever this prints to stdout is injected into Claude's context. It never fails the
session: any error just means less context.
"""
from __future__ import annotations

import json
import re
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
from _team import CACHE_DIR, current_branch, identity, load_team, run  # noqa: E402

QUICK_INTERVAL = 600
LAST_FETCH = CACHE_DIR / "last_fetch"


def fetch() -> bool:
    code, _ = run(["git", "fetch", "origin", "--prune", "--quiet"], timeout=25)
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        LAST_FETCH.write_text(str(time.time()))
    except OSError:
        pass
    return code == 0


def ahead_behind(ref: str, base: str) -> tuple[int, int] | None:
    code, out = run(["git", "rev-list", "--left-right", "--count", f"{ref}...{base}"])
    if code != 0 or not out:
        return None
    a, b = out.split()
    return int(a), int(b)


def dirty() -> bool:
    _, out = run(["git", "status", "--porcelain"])
    return bool(out)


# ---------------------------------------------------------------- review queue / deadlines
def ci_state(pr: dict) -> str:
    """'green' | 'red' | 'running' | 'none', from the required `checks` job (the latest run wins)."""
    roll = pr.get("statusCheckRollup") or []
    runs = [c for c in roll if c.get("name") == "checks"]
    if runs:
        last = max(runs, key=lambda c: c.get("startedAt") or "")
        if last.get("status") != "COMPLETED":
            return "running"
        return "green" if last.get("conclusion") == "SUCCESS" else "red"
    if any(c.get("status") not in (None, "COMPLETED") for c in roll):
        return "running"
    return "none"


UPDATED_NOTE = "updated since changes requested"


def changes_requested_on_head(pr: dict) -> bool:
    """True if a CHANGES_REQUESTED decision still applies to the PR's current head commit.

    GitHub keeps CHANGES_REQUESTED until the reviewer submits a new review; a push does not clear it. So the
    decision blocks on the author only while the latest CHANGES_REQUESTED review is on `headRefOid`. Once the
    author has pushed past it, the PR waits on the reviewer again. Without review data, trust the decision.
    """
    if pr.get("reviewDecision") != "CHANGES_REQUESTED":
        return False
    head = pr.get("headRefOid")
    asks = [r for r in (pr.get("reviews") or []) if r.get("state") == "CHANGES_REQUESTED"]
    if not head or not asks:
        return True
    latest = max(asks, key=lambda r: r.get("submittedAt") or "")
    oid = (latest.get("commit") or {}).get("oid")
    return not oid or oid == head


def updated_since_changes(pr: dict) -> bool:
    return pr.get("reviewDecision") == "CHANGES_REQUESTED" and not changes_requested_on_head(pr)


def waits_on(pr: dict) -> str:
    """Who an open PR is waiting on: 'draft' | 'author' | 'ci' | 'merge' | 'review'."""
    ci = ci_state(pr)
    if pr.get("isDraft"):
        return "draft"
    if changes_requested_on_head(pr) or ci == "red":
        return "author"
    if ci != "green":
        return "ci"
    return "merge" if pr.get("reviewDecision") == "APPROVED" else "review"


def why_author(pr: dict) -> str:
    reasons = []
    if changes_requested_on_head(pr):
        reasons.append("changes requested")
    if ci_state(pr) == "red":
        reasons.append("CI red")
    return ", ".join(reasons)


def closes(pr: dict) -> list[int]:
    return [int(i["number"]) for i in (pr.get("closingIssuesReferences") or []) if "number" in i]


def pr_row(pr: dict, note: str = "") -> str:
    c = closes(pr)
    tail = f"by {pr['author']['login']}" + (f", closes #{', #'.join(map(str, c))}" if c else "")
    return f"  - #{pr['number']} {pr['title']} ({tail})" + (f" [{note}]" if note else "")


def open_prs() -> list[dict] | None:
    """All open PRs with review + CI state, in ONE GitHub call. None if GitHub can't be reached."""
    code, out = run(["gh", "pr", "list", "--state", "open", "--limit", "40", "--json",
                     "number,title,author,isDraft,reviewDecision,reviews,headRefOid,statusCheckRollup,closingIssuesReferences"], timeout=15)
    if code != 0:
        return None
    try:
        return sorted(json.loads(out or "[]"), key=lambda p: p["number"])
    except (json.JSONDecodeError, KeyError, TypeError):
        return None


def lead_queue_lines(prs: list[dict]) -> list[str]:
    """Open PRs grouped by what they wait on, oldest first, so the lead sees the real queue at a glance."""
    if not prs:
        return ["- Open PRs: none."]
    groups: dict[str, list[dict]] = {}
    for pr in prs:
        groups.setdefault(waits_on(pr), []).append(pr)
    n = {k: len(v) for k, v in groups.items()}
    lines = [f"- Open PRs: {len(prs)}. {n.get('review', 0) + n.get('merge', 0)} wait on a lead, "
             f"{n.get('author', 0)} wait on their author, {n.get('ci', 0) + n.get('draft', 0)} not ready (CI running / draft)."]
    if groups.get("merge"):
        lines.append("  Approved and green, ready to merge:")
        lines += [pr_row(p) for p in groups["merge"]]
    if groups.get("review"):
        lines.append("  CI green, waiting for lead review (oldest first):")
        lines += [pr_row(p, UPDATED_NOTE if updated_since_changes(p) else "") for p in groups["review"]]
    if groups.get("author"):
        lines.append("  Waiting on the author (nothing for the lead to do yet):")
        lines += [pr_row(p, why_author(p)) for p in groups["author"]]
    rest = groups.get("ci", []) + groups.get("draft", [])
    if rest:
        lines.append("  Not ready: " + ", ".join(f"#{p['number']}" for p in rest))
    if n.get("review", 0) + n.get("merge", 0) >= 3:
        lines.append("  -> The review queue is the bottleneck. Run the `merge-queue` skill (triage, overlap check, merge order) "
                     "before starting or dispatching new work.")
    return lines


def partner_pr_lines(prs: list[dict], login: str) -> list[str]:
    """The partner's own PRs: the ones that need a fix come first, because an unmerged PR counts for nothing."""
    mine = [p for p in prs if p["author"]["login"].lower() == login.lower()]
    if not mine:
        return []
    fix = [p for p in mine if waits_on(p) == "author"]
    rest = [p for p in mine if waits_on(p) != "author"]
    lines = []
    if fix:
        lines.append("- FIX THESE FIRST (your PRs that cannot merge as they are). Use the `address-review` skill:")
        lines += [pr_row(p, why_author(p)) for p in fix]
    if rest:
        lines.append("- Your PRs waiting for the lead (nothing to do): "
                     + ", ".join(f"#{p['number']}" + (f" ({UPDATED_NOTE})" if updated_since_changes(p) else "") for p in rest))
    return lines


def dep_states(repo: str, refs: list[str]) -> dict[str, str]:
    """State of each issue/PR number in ONE GraphQL call ('OPEN' | 'CLOSED' | 'MERGED' | 'UNKNOWN')."""
    refs = sorted(set(refs), key=int)
    if not refs or "/" not in repo:
        return {}
    owner, name = repo.split("/", 1)
    fields = " ".join(f"n{r}: issueOrPullRequest(number: {r}) {{ ... on Issue {{ state }} ... on PullRequest {{ state }} }}" for r in refs)
    _, out = run(["gh", "api", "graphql", "-f", f'query=query {{ repository(owner: "{owner}", name: "{name}") {{ {fields} }} }}'], timeout=12)
    try:  # a missing number makes gh exit non-zero but the other aliases are still in the payload
        data = (json.loads(out or "{}").get("data") or {}).get("repository") or {}
    except json.JSONDecodeError:
        data = {}
    return {r: ((data.get(f"n{r}") or {}).get("state") or "UNKNOWN") for r in refs}


def starts_after(body: str) -> list[str]:
    m = re.search(r"\*\*Starts after:\*\*([^\n]*)", body or "")
    return re.findall(r"#(\d+)", m.group(1) if m else "")


def task_rows(issues: list[dict], prs: list[dict] | None, states: dict[str, str]) -> tuple[list[str], int]:
    """One row per delegated issue with its real status. Returns (rows, number that are ready to start).

    `prs` is None when the open PRs could not be read: a task with no visible PR is then "unknown", not "ready".
    """
    by_issue: dict[int, dict] = {}
    for pr in prs or []:
        for num in closes(pr):
            by_issue.setdefault(num, pr)
    rows, ready = [], 0
    for i in sorted(issues, key=lambda x: x["number"]):
        pr = by_issue.get(i["number"])
        pending = [f"#{r}" for r in starts_after(i.get("body", "")) if states.get(r, "UNKNOWN") not in ("CLOSED", "MERGED")]
        if pr:
            status = f"PR #{pr['number']} needs fixes" if waits_on(pr) == "author" else f"in review: PR #{pr['number']}"
        elif pending:
            status = f"waiting on {', '.join(pending)}"
        elif prs is None:
            status = "status unknown: could not read open PRs"
        else:
            status, ready = "ready", ready + 1
        rows.append(f"  - #{i['number']} {i['title']}  ({status})")
    return rows, ready


def _span(seconds: float) -> str:
    m = int(seconds // 60)
    d, h, m = m // 1440, (m % 1440) // 60, m % 60
    return f"{d}d {h}h" if d else (f"{h}h {m:02d}m" if h else f"{m}m")


def rule_deadline_passed(team: dict, now: datetime | None = None) -> bool:
    """True once any deadline that carries an `after` rule (practice demos, code freeze) has passed."""
    now = now or datetime.now(timezone.utc)
    for d in team.get("deadlines", []):
        try:
            if d.get("after") and datetime.fromisoformat(d["at"]) <= now:
                return True
        except (KeyError, TypeError, ValueError, AttributeError):
            continue
    return False


def deadline_lines(team: dict, now: datetime | None = None) -> list[str]:
    """Time left to each upcoming deadline in team.json, and the rule of the latest one that has passed."""
    now = now or datetime.now(timezone.utc)
    upcoming, passed = [], []
    for d in team.get("deadlines", []):
        try:
            at = datetime.fromisoformat(d["at"])
        except (KeyError, TypeError, ValueError):
            continue
        (upcoming if at > now else passed).append((at, d))
    lines = []
    if passed:
        _, d = max(passed, key=lambda x: x[0])
        if d.get("after"):
            lines.append(f"- PASSED: {d.get('name', 'deadline')} ({d.get('when', d['at'])}). {d['after']}")
    if upcoming:
        parts = [f"{d.get('name', 'deadline')} in {_span((at - now).total_seconds())} ({d.get('when', d['at'])})"
                 for at, d in sorted(upcoming, key=lambda x: x[0])[:2]]
        lines.append("- Clock: " + "; ".join(parts) + ". Unmerged work at the freeze does not count: finish and fix before starting new scope.")
    return lines


def quick() -> None:
    try:
        if time.time() - float(LAST_FETCH.read_text()) < QUICK_INTERVAL:
            return
    except (OSError, ValueError):
        pass
    if not fetch():
        return
    team = load_team()
    main = f"origin/{team.get('default_branch', 'main')}"
    ab = ahead_behind("HEAD", main)
    if ab and ab[1] > 0:
        print(
            f"[faultline-sync] Heads up: {main} has {ab[1]} new commit(s) not in your branch "
            f"`{current_branch()}`. Before continuing substantial work or opening a PR, run the "
            f"/sync skill (rebase onto {main}) so you are building on the latest repo."
        )


def full() -> None:
    team = load_team()
    default = team.get("default_branch", "main")
    main = f"origin/{default}"
    ident = identity()
    lines: list[str] = ["# FAULTLINE session context (auto-generated by scripts/guardrails/sync.py)"]

    _, hooks_path = run(["git", "config", "--get", "core.hooksPath"])
    if hooks_path != ".githooks":
        code, _ = run(["git", "config", "core.hooksPath", ".githooks"])
        lines.append(f"- Git hooks: {'installed (.githooks: no commits/pushes to main)' if code == 0 else 'could not install; tell the human'}")

    ok = fetch()
    lines.append(f"- GitHub fetch: {'OK, refs are current' if ok else 'FAILED (offline or no auth). Tell the human; do not assume local main is current.'}")

    branch = current_branch()
    if branch == default and not dirty() and ok:
        code, _ = run(["git", "merge", "--ff-only", "--quiet", main])
        lines.append(f"- On `{default}`: {'fast-forwarded to latest' if code == 0 else 'could NOT fast-forward (local commits on main?). Tell the human.'}")
    ab = ahead_behind("HEAD", main)
    if ab:
        lines.append(f"- Branch `{branch}` is {ab[0]} ahead / {ab[1]} behind {main}.")
        if ab[1] and branch != default:
            lines.append(f"  -> Behind. Rebase onto {main} (see /sync) before new work or a PR.")
    if dirty():
        lines.append("- Working tree has uncommitted changes. Do not discard them; ask the human what they are.")

    if ident["role"] == "lead":
        lines.append(f"- You are working for **{ident['name']}**, a project LEAD. Leads assign work and are the only people who merge to `{default}`.")
        prs = open_prs()
        if prs is None:
            lines.append("- Open PRs: could not read them from GitHub (`gh pr list` failed). Tell the human.")
        else:
            lines += lead_queue_lines(prs)
    else:
        who = ident["name"] or "an unidentified user"
        lines.append(
            f"- You are working for **{who}** (role: PARTNER, GitHub `{ident['login'] or 'unknown'}`). PARTNER RULES ARE IN EFFECT:\n"
            "  1. Only work on GitHub issues a lead created/assigned with the `delegated` label (use /start-task). Politely decline anything else and suggest asking a lead to file an issue.\n"
            f"  2. Work on a branch, open a PR with /ship-pr. Never push to, commit on, or merge into `{default}`. Never deploy. A lead reviews and merges.\n"
            "  3. PULL BEFORE EDITING: run /sync before your first edit and whenever GitHub main moves (edits are blocked while behind).\n"
            "  4. The human is a finance/math expert, not a programmer: explain in plain language, no unexplained jargon, show numbers."
        )
        if ident["login"]:
            leads = team.get("leads", [])
            code, out = run(["gh", "issue", "list", "--state", "open", "--label", team.get("delegation_label", "delegated"),
                             "--assignee", ident["login"], "--json", "number,title,author,body"], timeout=10)
            if code == 0:
                try:
                    issues = json.loads(out or "[]")
                except json.JSONDecodeError:
                    issues = []
                lead_set = {l.lower() for l in leads}
                valid = [i for i in issues if i["author"]["login"].lower() in lead_set]
                prs = open_prs()
                if prs is None:
                    lines.append("- Your open PRs: could not read them from GitHub (`gh pr list` failed). Tell the human.")
                else:
                    lines += partner_pr_lines(prs, ident["login"])
                if valid:
                    refs = [r for i in valid for r in starts_after(i.get("body", ""))]
                    rows, ready = task_rows(valid, prs, dep_states(team.get("repo", ""), refs))
                    lines.append("- Delegated tasks for you:\n" + "\n".join(rows))
                    if prs is None:
                        pass  # task status is unknown; the line above already says so
                    elif ready > 1 and not rule_deadline_passed(team):
                        lines.append(f"  -> {ready} tasks are ready. Offer /my-sprint to run them in parallel (one agent each, separate PRs).")
                    elif ready == 0:
                        lines.append("  -> Nothing new can start yet. Fix PRs that need it; otherwise tell the human what is waiting on the lead.")
                else:
                    lines.append("- No delegated tasks are assigned right now. Say so, and suggest the human ask a lead for one.")
        else:
            lines.append("- Could not determine the GitHub login (`gh auth login` not done?). Help the human run `gh auth login` before doing anything else.")

    lines += deadline_lines(team)
    lines.append("- Source of truth: docs/SPEC.md (product), docs/MATH_MODEL.md (math), docs/WORKFLOW.md (process), "
                 "docs/HACKATHON.md (schedule, judging incl. the +2 AI-alignment bonus).")
    print("\n".join(lines))


if __name__ == "__main__":
    try:
        (quick if "--quick" in sys.argv else full)()
    except Exception as e:  # never break the session
        print(f"[faultline-sync] skipped: {e}")
    sys.exit(0)
