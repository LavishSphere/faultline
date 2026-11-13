#!/usr/bin/env python3
"""Find CANDIDATE historical sources for a Blind Replay case with Tavily (supports #20; issue #60).

    TAVILY_API_KEY=... python scripts/tavily_curate.py "Will the Fed cut rates in March 2025?" \\
        --before 2025-03-01T00:00:00Z [--case fed-march-2025] [--max-results 10] [--topic news]

Writes ``docs/curation/<case>.md``: for each Tavily result, its url, title, Tavily's claimed publish date, and a
Wayback Machine availability lookup for the capture closest to ``as_of``. Everything in that file is labeled
``CANDIDATES, NOT VERIFIED: human must confirm available_at from an archive capture``.

What this script never does:
- It never writes ``demo_cases/``, ``sealed_outcomes/``, evidence files, or anything under services/api/data.
  It refuses such an output directory. A human turns a candidate into an ``EvidenceItem`` by hand, with
  ``available_at`` taken from an archive capture they opened and checked.
- It never treats Tavily's ``published_date`` as proof: Tavily documents it as a best estimate of when a page
  was "published or last updated", which "can be later than the original publish date". The search runs
  today, so results can describe what happened after ``as_of``; the file is curation input, never replay input.
- It never prints or writes the API key.

Wayback Availability API (verified 2026-11-13, https://archive.org/help/wayback_api.php):
``GET https://archive.org/wayback/available?url=<url>&timestamp=<YYYYMMDDhhmmss>`` returns
``{"archived_snapshots": {"closest": {"available", "url", "timestamp", "status"}}}`` (empty object when none).
"closest" can be AFTER the requested timestamp, so each lookup is marked BEFORE / AFTER as_of explicitly.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parent.parent
API_DIR = REPO_ROOT / "services" / "api"
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

from agents import tavily  # noqa: E402  (Live Explore client; allowed importer, see test_explore_separation.py)

DEFAULT_OUT_DIR = REPO_ROOT / "docs" / "curation"
LABEL = "CANDIDATES, NOT VERIFIED: human must confirm available_at from an archive capture"
WAYBACK_AVAILABLE_URL = "https://archive.org/wayback/available"
WAYBACK_TIMEOUT_S = 15.0
USER_AGENT = "faultline-curation/0.1"
PROTECTED_DIR_NAMES = frozenset({"demo_cases", "sealed_outcomes", "evidence"})
_DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_SLUG = re.compile(r"[^a-z0-9]+")
_MD_SPECIAL = re.compile(r"([\\`*_\[\]<>|#])")

EXIT_OK, EXIT_USAGE, EXIT_UNAVAILABLE, EXIT_SEARCH_FAILED, EXIT_EXISTS = 0, 2, 3, 4, 5


class CurationError(Exception):
    def __init__(self, message: str, exit_code: int = EXIT_USAGE) -> None:
        super().__init__(message)
        self.exit_code = exit_code


def parse_as_of(raw: str) -> tuple[datetime, str]:
    """Timezone-aware instant, or a calendar date read as 00:00 UTC that day (the earlier, safer cutoff)."""
    text = raw.strip()
    if _DATE_ONLY.match(text):
        day = datetime.fromisoformat(text).replace(tzinfo=UTC)
        return day, f"{text} read as {day.isoformat()} (start of the day, UTC)"
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00") if text.endswith("Z") else text)
    except ValueError:
        msg = f"--before must be an ISO-8601 instant with a timezone, or YYYY-MM-DD; got {raw!r}"
        raise CurationError(msg) from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise CurationError("--before must include a timezone offset (e.g. 2025-03-01T00:00:00Z)")
    utc = parsed.astimezone(UTC)
    return utc, utc.isoformat()


def slugify(text: str) -> str:
    slug = _SLUG.sub("-", text.lower()).strip("-")[:60].strip("-")
    if not slug:
        raise CurationError("cannot derive a case slug from the question; pass --case")
    return slug


def _within(target: Path, root: Path) -> bool:
    """True if `target` is `root` or inside it. Compared by file identity (``os.path.samefile``) on the target and
    each existing ancestor, so case variants on case-insensitive file systems (APFS: ``services/api/DATA``),
    symlinks and ``..`` all resolve to the same directory. Falls back to a case-folded path compare when
    `root` does not exist."""
    if not root.exists():
        r = str(root.resolve()).casefold()
        return any(str(p).casefold() == r for p in (target, *target.parents))
    for p in (target, *target.parents):
        try:
            if p.exists() and os.path.samefile(p, root):
                return True
        except OSError:
            continue
    return False


def check_out_dir(out_dir: Path) -> Path:
    """Refuse any directory that is, or is inside, replay data (services/api/data or a protected name)."""
    resolved = out_dir.expanduser().resolve()
    data_root = API_DIR / "data"
    if _within(resolved, data_root):
        raise CurationError(f"refusing to write under {data_root}: this script only writes curation notes")
    configured = os.environ.get("FAULTLINE_DATA_DIR", "").strip()
    if configured and _within(resolved, Path(configured).expanduser()):
        raise CurationError("refusing to write under FAULTLINE_DATA_DIR: this script only writes curation notes")
    bad = PROTECTED_DIR_NAMES.intersection(part.lower() for part in resolved.parts)
    if bad:
        raise CurationError(f"refusing to write into a {sorted(bad)[0]!r} directory")
    return resolved


def _check_out_path(out_path: Path, force: bool) -> None:
    """Refuse a symlinked output file (it could point into replay data), re-check the directory the file really
    lands in, and refuse an existing file unless --force."""
    if out_path.is_symlink():
        raise CurationError(f"refusing to write through a symlink: {out_path}")
    check_out_dir(out_path.resolve().parent)
    if out_path.exists() and not force:
        raise CurationError(f"{out_path} exists; pass --force to overwrite", EXIT_EXISTS)


def wayback_stamp(instant: datetime) -> str:
    return instant.astimezone(UTC).strftime("%Y%m%d%H%M%S")


def _stamp_to_dt(stamp: str) -> datetime | None:
    if not re.fullmatch(r"\d{14}", stamp or ""):
        return None
    try:
        return datetime.strptime(stamp, "%Y%m%d%H%M%S").replace(tzinfo=UTC)
    except ValueError:
        return None


@dataclass(frozen=True)
class WaybackLookup:
    status: str  # "before_as_of" | "after_as_of" | "none" | "failed"
    capture_url: str | None = None
    capture_at: datetime | None = None
    detail: str | None = None


def wayback_lookup(client: httpx.Client, url: str, as_of: datetime) -> WaybackLookup:
    failure: WaybackLookup | None = None
    try:
        resp = client.get(WAYBACK_AVAILABLE_URL, params={"url": url, "timestamp": wayback_stamp(as_of)})
        resp.raise_for_status()
        payload = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        failure = WaybackLookup("failed", detail=type(exc).__name__)
    if failure is not None:
        return failure
    snaps = payload.get("archived_snapshots") if isinstance(payload, dict) else None
    closest = snaps.get("closest") if isinstance(snaps, dict) else None
    if not isinstance(closest, dict) or closest.get("available") is not True:
        return WaybackLookup("none")
    capture_url = closest.get("url") if isinstance(closest.get("url"), str) else None
    capture_at = _stamp_to_dt(str(closest.get("timestamp", "")))
    if capture_at is None or capture_url is None:
        return WaybackLookup("failed", detail="unexpected snapshot fields")
    status = "before_as_of" if capture_at <= as_of else "after_as_of"
    if capture_url.startswith("http://archive.org/") or capture_url.startswith("http://web.archive.org/"):
        capture_url = "https://" + capture_url[len("http://"):]
    return WaybackLookup(status, capture_url=capture_url, capture_at=capture_at)


def md(text: str | None) -> str:
    """Plain text for Markdown: one line, Markdown/HTML control characters escaped."""
    if not text:
        return ""
    return _MD_SPECIAL.sub(r"\\\1", " ".join(text.split()))


def _claimed_date_line(hit: tavily.TavilyHit, as_of: datetime) -> str:
    if hit.published_at is not None:
        verdict = "before as_of" if hit.published_at <= as_of else "AFTER as_of: not a valid replay source as dated"
        return f"`{md(hit.published_at_raw)}` = {hit.published_at.isoformat()} ({verdict})"
    if hit.published_at_raw:
        return f"`{md(hit.published_at_raw)}` (not an instant; compare with as_of by hand)"
    return "NOT AVAILABLE (Tavily detected no date)"


def _wayback_line(lookup: WaybackLookup | None) -> str:
    if lookup is None:
        return "not checked (--no-wayback)"
    if lookup.status == "none":
        return "no capture found: available_at cannot be proven from the Wayback Machine"
    if lookup.status == "failed":
        return f"lookup failed ({md(lookup.detail)}): NOT AVAILABLE"
    assert lookup.capture_at is not None and lookup.capture_url is not None
    verdict = ("capture BEFORE as_of: open it and confirm the quoted text is present"
               if lookup.status == "before_as_of"
               else "closest capture is AFTER as_of: does not prove the page was public at as_of")
    return f"{lookup.capture_at.isoformat()} <{lookup.capture_url}> ({verdict})"


def render_report(question: str, case: str, as_of: datetime, as_of_note: str, result: tavily.TavilySearchResponse,
                  lookups: Sequence[WaybackLookup | None]) -> str:
    params = {k: v for k, v in result.params.items() if k != "query"}
    lines = [
        f"# Curation candidates: {md(case)}",
        "",
        f"**{LABEL}**",
        "",
        f"- Question: {md(question)}",
        f"- as_of (cutoff): {as_of_note}",
        f"- Searched: {result.retrieved_at.isoformat()} via Tavily (Search powered by Tavily); "
        f"parameters: `{md(repr(params))}`",
        f"- Results: {len(result.items)} kept, {result.dropped} dropped (no title, invalid url or duplicate)",
        "",
        "> This search ran today, not at as_of, so results may describe events after the cutoff. Tavily's",
        "> published date is its estimate of when a page was published or last updated, not proof of availability.",
        "> Nothing here is evidence until a human opens an archive capture dated at or before as_of, confirms the",
        "> quoted text is in it, and records `available_at` from that capture in the case file by hand.",
        "> This file is curation input only: the Blind Replay never reads docs/.",
        "",
    ]
    if not result.items:
        lines += ["No candidates: Tavily returned no usable results.", ""]
    for i, (hit, lookup) in enumerate(zip(result.items, lookups, strict=True), start=1):
        lines += [
            f"## {i}. {md(hit.title)}",
            "",
            f"- URL: <{hit.url}>",
            f"- Claimed publish date (Tavily estimate): {_claimed_date_line(hit, as_of)}",
            f"- Wayback capture closest to as_of: {_wayback_line(lookup)}",
            f"- Snippet (as retrieved {hit.retrieved_at.isoformat()}): {md(hit.snippet) or 'NOT AVAILABLE'}",
            "- [ ] Human check: archive capture opened, text confirmed, available_at recorded from the capture",
            "",
        ]
    return "\n".join(lines)


async def _search(question: str, as_of: datetime, args: argparse.Namespace,
                  transport: httpx.AsyncBaseTransport | None) -> tavily.TavilySearchResponse:
    client = tavily.client_from_env(transport=transport, timeout_s=20.0)
    return await client.search(
        question,
        max_results=args.max_results,
        topic=args.topic,
        end_date=as_of.date().isoformat(),
        start_date=args.after,
        include_domains=args.include_domain or None,
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("question", help="the replay question or search text")
    p.add_argument("--before", required=True, help="the case as_of: ISO instant with timezone, or YYYY-MM-DD")
    p.add_argument("--case", help="case slug for the output file name (default: from the question)")
    p.add_argument("--max-results", type=int, default=10, help=f"1-{tavily.TAVILY_MAX_RESULTS} (default 10)")
    p.add_argument("--topic", choices=("general", "news", "finance"), default="news")
    p.add_argument("--after", help="optional earliest publish date, YYYY-MM-DD")
    p.add_argument("--include-domain", action="append", help="restrict to this domain (repeatable)")
    p.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR), help="default docs/curation")
    p.add_argument("--no-wayback", action="store_true", help="skip the Wayback availability lookups")
    p.add_argument("--force", action="store_true", help="overwrite an existing curation file")
    return p


def run(argv: Sequence[str] | None = None, *, tavily_transport: httpx.AsyncBaseTransport | None = None,
        wayback_transport: httpx.BaseTransport | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        as_of, as_of_note = parse_as_of(args.before)
        case = slugify(args.case or args.question)
        out_dir = check_out_dir(Path(args.out_dir))
        out_path = out_dir / f"{case}.md"
        _check_out_path(out_path, args.force)  # before searching, so a refusal spends no credits
        failure: CurationError | None = None
        try:
            result = asyncio.run(_search(args.question, as_of, args, tavily_transport))
        except tavily.TavilyUnavailable as err:
            failure = CurationError(str(err), EXIT_UNAVAILABLE)
        except tavily.TavilyError as err:
            failure = CurationError(f"Tavily search failed: {err}", EXIT_SEARCH_FAILED)
        except ValueError as err:
            failure = CurationError(str(err))
        if failure is not None:
            raise failure
        lookups: list[WaybackLookup | None]
        if args.no_wayback:
            lookups = [None] * len(result.items)
        else:
            with httpx.Client(timeout=WAYBACK_TIMEOUT_S, transport=wayback_transport, follow_redirects=True,
                              headers={"User-Agent": USER_AGENT}) as wb:
                lookups = [wayback_lookup(wb, hit.url, as_of) for hit in result.items]
        report = render_report(args.question, case, as_of, as_of_note, result, lookups)
        out_dir.mkdir(parents=True, exist_ok=True)
        _check_out_path(out_path, args.force)  # again: the directory may have changed during the search
        # O_EXCL (mode "x") fails if the file appeared meanwhile, so there is no exists-then-write race; O_NOFOLLOW
        # refuses a symlink swapped in after the check. --force truncates an existing regular file instead.
        flags = os.O_WRONLY | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0) | (os.O_TRUNC if args.force else os.O_EXCL)
        try:
            fd = os.open(out_path, flags, 0o644)
        except FileExistsError:
            raise CurationError(f"{out_path} exists; pass --force to overwrite", EXIT_EXISTS) from None
        except OSError as exc:  # ELOOP: a symlink appeared at out_path
            raise CurationError(f"could not create {out_path} ({type(exc).__name__})") from None
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(report)
    except CurationError as err:
        print(f"tavily_curate: {err}", file=sys.stderr)
        return err.exit_code
    print(f"wrote {out_path} ({len(result.items)} candidates; {LABEL})")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(run())
