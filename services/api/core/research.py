"""VC research lenses: loading, schema validation, and point-in-time eligibility (SPEC §7, §10).

Lenses are public writing from four venture firms, shown as RESEARCH CONTEXT. They are not
predictions, not investment records, and are never scored against FAULTLINE.

Point-in-time rule: a lens may be shown in a replay only if it was provably public at the replay
cutoff. Each item carries
  - ``published_at``: the date displayed on the page (``None`` when the page shows none), and
  - ``available_at``: the conservative date we can prove the quoted text existed, i.e. the later
    of the displayed date and any machine-readable publish timestamp, or for undated living pages
    the date of the earliest checked archive capture containing every quote.

``as_of`` contract: callers must pass the replay **instant**, a timezone-aware ``datetime``
(or an ISO-8601 string with an offset). Never pass a cut-down calendar date: ``date`` objects,
``"YYYY-MM-DD"`` strings, and naive datetimes are rejected.

Day-only item dates are publisher-local and the publisher's time zone is not known, so they are
treated conservatively. An item dated ``D`` counts as public only once ``D`` has ended in every
time zone, i.e. from ``D+1 12:00 UTC`` (the end of ``D`` at UTC-12). Excluding a source that was
in fact public is harmless; including one that was not yet public is leakage.

Prompts must never receive the full item: it carries curation metadata dated after most
cutoffs (``accessed_at``, archive capture times, page-modified timestamps, basis notes). Use
``lens_for_prompt(item, as_of)``, which returns only content fields.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any

DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "research_lenses.json"

LABEL = "RESEARCH CONTEXT"
PROVENANCE = "REAL_HISTORICAL"  # canonical wire value; displayed as "REAL HISTORICAL"
FIRMS = (
    "Link Ventures",
    "Andreessen Horowitz (a16z)",
    "Sequoia Capital",
    "Bessemer Venture Partners",
)
QUOTE_KINDS = ("documentary_fact", "analyst_interpretation", "quantitative_forecast")
REQUIRED_FIELDS = (
    "id",
    "firm",
    "title",
    "url",
    "published_at",
    "archived_url",
    "accessed_at",
    "available_at",
    "thesis",
    "hypotheses",
    "quotes",
    "limitations",
)
# Latest UTC offset in use is UTC-12, so a local calendar day D has ended everywhere by D+1 12:00 UTC.
_DAY_END_EVERYWHERE = timedelta(days=1, hours=12)
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _parse_date(value: Any, field: str) -> date:
    if not isinstance(value, str) or not _DATE_RE.match(value):
        raise ValueError(f"{field} must be a 'YYYY-MM-DD' string, got {value!r}")
    return date.fromisoformat(value)


def _parse_utc_timestamp(value: Any, field: str) -> datetime:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be an ISO-8601 string, got {value!r}")
    ts = datetime.fromisoformat(value)
    if ts.tzinfo is None:
        raise ValueError(f"{field} must include a timezone, got {value!r}")
    return ts


def validate_lens(item: Any) -> list[str]:
    """Return a list of schema problems for one lens item (empty list means valid)."""
    if not isinstance(item, dict):
        return [f"lens item must be a JSON object, got {type(item).__name__}"]
    errors: list[str] = []
    ident = item.get("id", "<missing id>")
    for field in REQUIRED_FIELDS:
        if field not in item:
            errors.append(f"{ident}: missing field {field!r}")
    if errors:
        return errors

    if item["firm"] not in FIRMS:
        errors.append(f"{ident}: unknown firm {item['firm']!r}")
    for field in ("id", "title", "thesis"):
        if not isinstance(item[field], str) or not item[field].strip():
            errors.append(f"{ident}: {field} must be a non-empty string")
    for field in ("url", "archived_url"):
        value = item[field]
        if value is not None and not (isinstance(value, str) and value.startswith("https://")):
            errors.append(f"{ident}: {field} must be an https URL or null")
    if not isinstance(item["url"], str):
        errors.append(f"{ident}: url is required")

    try:
        published = None if item["published_at"] is None else _parse_date(item["published_at"], "published_at")
        available = _parse_date(item["available_at"], "available_at")
        accessed = _parse_utc_timestamp(item["accessed_at"], "accessed_at")
        if published is not None and available < published:
            errors.append(f"{ident}: available_at is earlier than published_at")
        if available > accessed.date():
            errors.append(f"{ident}: available_at is after accessed_at")
    except (TypeError, ValueError) as exc:
        errors.append(f"{ident}: {exc}")

    if item["published_at"] is None and not item.get("published_at_basis"):
        errors.append(f"{ident}: published_at is null but published_at_basis is missing")
    if not item.get("available_at_basis"):
        errors.append(f"{ident}: available_at_basis is missing")

    if not (isinstance(item["hypotheses"], list) and item["hypotheses"]
            and all(isinstance(h, str) and h.strip() for h in item["hypotheses"])):
        errors.append(f"{ident}: hypotheses must be a non-empty list of strings")
    if not (isinstance(item["limitations"], list) and item["limitations"]
            and all(isinstance(x, str) and x.strip() for x in item["limitations"])):
        errors.append(f"{ident}: limitations must be a non-empty list of strings")

    quotes = item["quotes"]
    if not (isinstance(quotes, list) and quotes):
        errors.append(f"{ident}: quotes must be a non-empty list")
    else:
        for i, quote in enumerate(quotes):
            if not isinstance(quote, dict) or not isinstance(quote.get("text"), str) or not quote["text"].strip():
                errors.append(f"{ident}: quotes[{i}].text must be a non-empty string")
                continue
            if quote.get("kind") not in QUOTE_KINDS:
                errors.append(f"{ident}: quotes[{i}].kind must be one of {QUOTE_KINDS}")
    return errors


def load_lenses(path: Path | str = DATA_PATH) -> list[dict[str, Any]]:
    """Load and validate all lens items. Raises ValueError listing every schema problem."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("label") != LABEL:
        raise ValueError(f"dataset label must be {LABEL!r}")
    if payload.get("provenance") != PROVENANCE:
        raise ValueError(f"dataset provenance must be {PROVENANCE!r}")
    items = payload.get("items")
    if not isinstance(items, list):
        raise ValueError("dataset must contain an 'items' list")  # noqa: TRY004 - schema error contract
    errors = [err for item in items for err in validate_lens(item)]
    ids = [item.get("id") for item in items if isinstance(item, dict)]
    if len(ids) != len(set(ids)):
        errors.append("duplicate lens ids")
    if errors:
        raise ValueError("invalid research lenses:\n" + "\n".join(errors))
    return items


def _as_of_instant(as_of: datetime | str) -> datetime:
    """Normalize the replay instant to UTC; reject calendar dates and naive datetimes."""
    if isinstance(as_of, str):
        if _DATE_RE.match(as_of):
            raise ValueError("as_of must be the replay instant with a timezone, not a calendar date")
        as_of = _parse_utc_timestamp(as_of, "as_of")
    if not isinstance(as_of, datetime):  # also rejects date, which is not a datetime
        raise TypeError(f"as_of must be a timezone-aware datetime, got {type(as_of).__name__}")
    if as_of.tzinfo is None:
        raise ValueError("as_of datetime must be timezone-aware")
    return as_of.astimezone(UTC)


def public_from(day: date) -> datetime:
    """Earliest instant at which a publisher-local calendar day has ended in every time zone."""
    return datetime.combine(day, time(0, 0), tzinfo=UTC) + _DAY_END_EVERYWHERE


def is_eligible(item: dict[str, Any], as_of: datetime | str) -> bool:
    """True only if the lens was provably public at the replay instant ``as_of``."""
    instant = _as_of_instant(as_of)
    markers = [_parse_date(item["available_at"], "available_at")]
    if item.get("published_at") is not None:
        markers.append(_parse_date(item["published_at"], "published_at"))
    return public_from(max(markers)) <= instant


def eligible_lenses(
    as_of: datetime | str,
    lenses: Iterable[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Lenses usable at ``as_of``; anything published or first evidenced after it is excluded."""
    items = load_lenses() if lenses is None else list(lenses)
    return [item for item in items if is_eligible(item, as_of)]


def lens_for_prompt(item: dict[str, Any], as_of: datetime | str) -> dict[str, Any]:
    """Prompt-safe projection of an eligible lens: content only, no post-cutoff curation metadata.

    Keeps id, firm, title, url, published_at (only when on or before ``as_of``), thesis,
    hypotheses, and quotes as {text, kind}. Drops accessed_at, archive fields, page metadata,
    basis notes, quote notes, and limitations. Raises ValueError for an item not eligible at ``as_of``.
    """
    instant = _as_of_instant(as_of)
    if not is_eligible(item, instant):
        raise ValueError(f"lens {item.get('id')!r} is not eligible at {instant.isoformat()}")
    out: dict[str, Any] = {
        "id": item["id"],
        "firm": item["firm"],
        "title": item["title"],
        "url": item["url"],
    }
    published = item.get("published_at")
    if published is not None and public_from(_parse_date(published, "published_at")) <= instant:
        out["published_at"] = published
    out["thesis"] = item["thesis"]
    out["hypotheses"] = list(item["hypotheses"])
    out["quotes"] = [{"text": q["text"], "kind": q["kind"]} for q in item["quotes"]]
    return out
