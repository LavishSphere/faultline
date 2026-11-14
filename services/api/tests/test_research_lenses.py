"""Research lens dataset: schema, firm coverage, honesty wording, point-in-time eligibility (SPEC §7, §10)."""

import copy
import json
import re
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from core.research import (
    DATA_PATH,
    FIRMS,
    QUOTE_KINDS,
    eligible_lenses,
    is_eligible,
    lens_for_prompt,
    load_lenses,
    public_from,
    validate_lens,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
RESEARCH_MODULE = REPO_ROOT / "services" / "api" / "core" / "research.py"
PROVENANCE_DOC = REPO_ROOT / "docs" / "DATA_PROVENANCE.md"

SEQUOIA_ETCHED = "sequoia-partnering-with-etched"
BESSEMER_AI_2025 = "bessemer-state-of-ai-2025"
STITCH = "a16z-investing-in-stitch"


def _at(y, m, d, hh=0, mm=0, ss=0):
    return datetime(y, m, d, hh, mm, ss, tzinfo=UTC)


@pytest.fixture(scope="module")
def lenses():
    return load_lenses()


def _ids(items):
    return {item["id"] for item in items}


def _by_id(lenses, ident):
    return next(item for item in lenses if item["id"] == ident)


# --- schema ---------------------------------------------------------------

def test_dataset_loads_and_every_item_is_valid(lenses):
    assert all(validate_lens(item) == [] for item in lenses)


def test_item_count_within_spec(lenses):
    assert 4 <= len(lenses) <= 8


def test_all_four_firms_present(lenses):
    assert {item["firm"] for item in lenses} == set(FIRMS)


def test_dataset_label_and_canonical_provenance():
    payload = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    assert payload["label"] == "RESEARCH CONTEXT"
    assert payload["provenance"] == "REAL_HISTORICAL"  # wire value; UI shows "REAL HISTORICAL"


def test_quote_kinds_are_classified(lenses):
    kinds = [q["kind"] for item in lenses for q in item["quotes"]]
    assert kinds and set(kinds) <= set(QUOTE_KINDS)


FINANCE_REVIEW_PREFIX = re.compile(r"^(PENDING FINANCE REVIEW|Reviewed by Yaseen \(\d{4}-\d{2}-\d{2}\):)")


def test_every_thesis_is_pending_or_reviewed_by_finance_owner(lenses):
    # Thesis summaries are curator paraphrases: each stays flagged PENDING FINANCE REVIEW until the
    # finance owner signs off, then carries "Reviewed by Yaseen (YYYY-MM-DD):" (issue #21).
    for item in lenses:
        assert FINANCE_REVIEW_PREFIX.match(item["thesis_review"]), item["id"]


def test_portfolio_pages_carry_the_not_a_returns_record_caveat(lenses):
    for item in lenses:
        if item.get("source_type") == "portfolio_page":
            text = " ".join(item["limitations"]).lower()
            assert "rejected" in text and "returns" in text


def test_validate_lens_reports_problems():
    bad = {
        "id": "x", "firm": "Some Other Fund", "title": "t", "url": "http://insecure",
        "published_at": "July 23", "archived_url": None, "accessed_at": "2026-11-13T00:00:00Z",
        "available_at": "2026-07-23", "available_at_basis": "b", "thesis": "t",
        "hypotheses": [], "quotes": [{"text": "q", "kind": "vc_prediction"}], "limitations": [],
    }
    errors = "\n".join(validate_lens(bad))
    for fragment in ("unknown firm", "https", "published_at", "hypotheses", "limitations", "kind"):
        assert fragment in errors


@pytest.mark.parametrize("not_an_object", [["x"], "x", None, 3])
def test_validate_lens_returns_error_for_non_object(not_an_object):
    errors = validate_lens(not_an_object)
    assert errors and "JSON object" in errors[0]


def test_validate_lens_rejects_available_before_published(lenses):
    item = dict(_by_id(lenses, SEQUOIA_ETCHED), available_at="2026-07-22")
    assert any("earlier than published_at" in e for e in validate_lens(item))


# --- honesty wording ------------------------------------------------------

# Phrases are assembled from parts so this file does not itself contain them.
_FORBIDDEN = [
    r"\bvc\s+predict",
    r"\bvc\s+" + "accura" + r"cy",
    r"\bbeat(s|ing)?\s+(the\s+)?(vcs?|link|a16z|andreessen|sequoia|bessemer)\b",
    r"\bbeats?\s+vcs?\b",
    r"\boutperform(s|ed)?\s+(the\s+)?(vcs?|link|a16z|andreessen|sequoia|bessemer)\b",
]


@pytest.mark.parametrize("path", [DATA_PATH, PROVENANCE_DOC, RESEARCH_MODULE], ids=lambda p: p.name)
def test_no_vc_prediction_or_competitive_score_language(path):
    text = path.read_text(encoding="utf-8").lower()
    for pattern in _FORBIDDEN:
        assert not re.search(pattern, text), f"{path.name}: {pattern}"


# --- point-in-time eligibility (as_of is the replay instant) --------------

def test_known_publication_dates(lenses):
    assert _by_id(lenses, SEQUOIA_ETCHED)["published_at"] == "2026-07-23"
    assert _by_id(lenses, BESSEMER_AI_2025)["published_at"] == "2025-08-13"
    assert _by_id(lenses, STITCH)["published_at"] == "2026-05-13"


def test_day_only_dates_are_public_once_the_day_ends_everywhere():
    # A publisher-local day D has ended in every time zone (UTC-12) at D+1 12:00 UTC.
    assert public_from(date(2026, 7, 23)) == _at(2026, 7, 24, 12)


def test_sequoia_boundary_2026_07_23(lenses):
    assert SEQUOIA_ETCHED not in _ids(eligible_lenses(_at(2026, 7, 23, 23), lenses))
    assert SEQUOIA_ETCHED not in _ids(eligible_lenses(_at(2026, 7, 24, 11, 59, 59), lenses))
    assert SEQUOIA_ETCHED in _ids(eligible_lenses(_at(2026, 7, 24, 12), lenses))
    assert SEQUOIA_ETCHED in _ids(eligible_lenses("2026-07-24T12:00:00Z", lenses))


def test_bessemer_boundary_2025_08_13(lenses):
    assert BESSEMER_AI_2025 not in _ids(eligible_lenses(_at(2025, 8, 13, 23, 59, 59), lenses))
    assert BESSEMER_AI_2025 not in _ids(eligible_lenses(_at(2025, 8, 14, 11, 59, 59), lenses))
    assert BESSEMER_AI_2025 in _ids(eligible_lenses(_at(2025, 8, 14, 12), lenses))


def test_conservative_available_at_wins_over_displayed_date(lenses):
    # Stitch displays May 13, 2026 but its machine timestamp is 2026-05-14 UTC.
    stitch = _by_id(lenses, STITCH)
    assert not is_eligible(stitch, _at(2026, 5, 14, 12))
    assert not is_eligible(stitch, _at(2026, 5, 15, 11, 59, 59))
    assert is_eligible(stitch, _at(2026, 5, 15, 12))


def test_between_bessemer_and_sequoia_only_bessemer_is_eligible(lenses):
    ids = _ids(eligible_lenses(_at(2026, 1, 1), lenses))
    assert BESSEMER_AI_2025 in ids
    assert SEQUOIA_ETCHED not in ids


def test_nothing_eligible_before_earliest_evidence(lenses):
    earliest = min(date.fromisoformat(item["available_at"]) for item in lenses)
    assert eligible_lenses(public_from(earliest) - timedelta(microseconds=1), lenses) == []


@pytest.mark.parametrize("cut_down", [date(2026, 7, 24), "2026-07-24", datetime(2026, 7, 24, 12)])
def test_calendar_dates_and_naive_datetimes_are_rejected(lenses, cut_down):
    with pytest.raises((TypeError, ValueError)):
        eligible_lenses(cut_down, lenses)


def test_eligible_lenses_defaults_to_dataset_file():
    assert _ids(eligible_lenses(_at(2026, 11, 13, 12))) == _ids(load_lenses())


# --- prompt-safe projection ------------------------------------------------

_PROMPT_KEYS = {"id", "firm", "title", "url", "published_at", "thesis", "hypotheses", "quotes"}
_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}
_ISO = re.compile(r"(?<!\d)(\d{4})-(\d{2})(?:-(\d{2}))?(?!\d)")
_US = re.compile(r"(?<!\d)(\d{2})/(\d{2})/(\d{4})(?!\d)")
_WAYBACK = re.compile(r"(?<!\d)(\d{4})(\d{2})(\d{2})\d{6}(?!\d)")
_NAMED = re.compile(
    r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(\d{1,2}),?\s+(\d{4})\b",
    re.IGNORECASE,
)
_YEAR = re.compile(r"(?<!\d)((?:19|20)\d{2})(?!\d)")


def _late_dates(text, as_of, check_bare_years):
    """Every date-like string in ``text`` that is later than ``as_of`` (UTC)."""
    cutoff = as_of.astimezone(UTC).date()
    late = []
    for m in _ISO.finditer(text):
        y, mo, d = int(m[1]), int(m[2]), m[3]
        if not 1 <= mo <= 12:
            continue
        if (d and date(y, mo, int(d)) > cutoff) or (not d and (y, mo) > (cutoff.year, cutoff.month)):
            late.append(m[0])
    for m in _US.finditer(text):
        if date(int(m[3]), int(m[1]), int(m[2])) > cutoff:
            late.append(m[0])
    for m in _WAYBACK.finditer(text):
        if date(int(m[1]), int(m[2]), int(m[3])) > cutoff:
            late.append(m[0])
    for m in _NAMED.finditer(text):
        if date(int(m[3]), _MONTHS[m[1].lower()[:3]], int(m[2])) > cutoff:
            late.append(m[0])
    if check_bare_years:
        late += [m[0] for m in _YEAR.finditer(text) if int(m[0]) > cutoff.year]
    return late


def _walk(node, as_of, in_quote=False):
    """Collect late dates anywhere in a projection, including dict keys.

    Bare years are checked everywhere except verbatim quote text: a quote is source content that was
    itself public at as_of, and may legitimately name a forecast horizon (e.g. Bessemer's "2025–2026").
    Full and partial dates are checked everywhere.
    """
    if isinstance(node, dict):
        late = []
        for key, value in node.items():
            late += _late_dates(str(key), as_of, True)
            late += _walk(value, as_of, in_quote=in_quote or key == "quotes")
        return late
    if isinstance(node, list):
        return [x for v in node for x in _walk(v, as_of, in_quote)]
    if isinstance(node, str):
        return _late_dates(node, as_of, check_bare_years=not in_quote)
    return []


def _boundary_instants(lenses):
    instants = {_at(2023, 1, 1), _at(2026, 11, 13, 12)}
    for item in lenses:
        for field in ("available_at", "published_at"):
            if item.get(field):
                day = date.fromisoformat(item[field])
                start = datetime(day.year, day.month, day.day, tzinfo=UTC)
                edge = public_from(day)
                instants |= {start, edge - timedelta(seconds=1), edge, edge + timedelta(days=1)}
    return sorted(instants)


def test_date_detector_catches_post_cutoff_metadata(lenses):
    # Guard against a vacuous walk: the full item does leak later dates at an early cutoff.
    as_of = _at(2025, 8, 14, 12)
    full = _by_id(lenses, BESSEMER_AI_2025)
    assert is_eligible(full, as_of)
    assert "2026-11-13" in " ".join(_walk(full, as_of))  # accessed_at


def test_prompt_projection_has_no_date_after_as_of_at_every_boundary(lenses):
    checked = 0
    for as_of in _boundary_instants(lenses):
        for item in eligible_lenses(as_of, lenses):
            projected = lens_for_prompt(item, as_of)
            assert set(projected) <= _PROMPT_KEYS
            assert _walk(projected, as_of) == [], (item["id"], as_of.isoformat())
            checked += 1
    assert checked > 0


def test_prompt_projection_contents(lenses):
    item = _by_id(lenses, SEQUOIA_ETCHED)
    projected = lens_for_prompt(item, _at(2026, 7, 24, 12))
    assert projected["published_at"] == "2026-07-23"
    assert projected["quotes"] == [{"text": q["text"], "kind": q["kind"]} for q in item["quotes"]]
    for dropped in ("accessed_at", "archived_url", "archived_at", "available_at", "available_at_basis",
                    "published_at_basis", "page_metadata", "limitations", "thesis_review"):
        assert dropped not in projected


def test_prompt_projection_omits_null_published_at(lenses):
    projected = lens_for_prompt(_by_id(lenses, "link-ventures-home"), _at(2026, 11, 13, 12))
    assert "published_at" not in projected


def test_prompt_projection_refuses_ineligible_item(lenses):
    with pytest.raises(ValueError):
        lens_for_prompt(_by_id(lenses, SEQUOIA_ETCHED), _at(2026, 7, 23, 12))


# --- scorable (issue #52) -------------------------------------------------
# `scorable` says whether a quoted forecast is stated precisely enough to be checked (metric, threshold,
# horizon, resolution source). It is read from the dataset, never inferred, and absent when the dataset is
# silent (NOT AVAILABLE). Quote-level wins; item-level applies to the item's quantitative_forecast quotes only.

def _with_quotes(lenses, ident, quotes, **item_fields):
    item = copy.deepcopy(_by_id(lenses, ident))
    item["quotes"] = quotes
    item.update(item_fields)
    return item


def _expected_scorable(item, quote):
    if "scorable" in quote:
        return quote["scorable"]
    if quote["kind"] == "quantitative_forecast" and "scorable" in item:
        return item["scorable"]
    return None


def test_scorable_in_projection_matches_dataset_for_every_quote(lenses):
    as_of = _at(2026, 11, 13, 12)
    for item in eligible_lenses(as_of, lenses):
        for quote, projected in zip(item["quotes"], lens_for_prompt(item, as_of)["quotes"], strict=True):
            expected = _expected_scorable(item, quote)
            if expected is None:
                assert "scorable" not in projected, item["id"]
            else:
                assert projected["scorable"] is expected, item["id"]


def test_quote_level_scorable_wins_over_item_level(lenses):
    item = _with_quotes(lenses, BESSEMER_AI_2025, [
        {"text": "f1", "kind": "quantitative_forecast", "scorable": True},
        {"text": "f2", "kind": "quantitative_forecast"},
    ], scorable=False, scorable_reason="no defined metric")
    assert validate_lens(item) == []
    quotes = lens_for_prompt(item, _at(2026, 11, 13, 12))["quotes"]
    assert quotes == [
        {"text": "f1", "kind": "quantitative_forecast", "scorable": True},
        {"text": "f2", "kind": "quantitative_forecast", "scorable": False},
    ]


def test_item_level_scorable_applies_only_to_quantitative_forecasts(lenses):
    item = _with_quotes(lenses, BESSEMER_AI_2025, [
        {"text": "fact", "kind": "documentary_fact"},
        {"text": "view", "kind": "analyst_interpretation"},
        {"text": "forecast", "kind": "quantitative_forecast"},
    ], scorable=False)
    quotes = lens_for_prompt(item, _at(2026, 11, 13, 12))["quotes"]
    assert [("scorable" in q) for q in quotes] == [False, False, True]
    assert quotes[2]["scorable"] is False


def test_scorable_absent_when_dataset_is_silent(lenses):
    item = _with_quotes(lenses, BESSEMER_AI_2025, [{"text": "forecast", "kind": "quantitative_forecast"}])
    item.pop("scorable", None)
    assert lens_for_prompt(item, _at(2026, 11, 13, 12))["quotes"] == [
        {"text": "forecast", "kind": "quantitative_forecast"}
    ]


def test_scorable_reason_and_quote_notes_never_reach_the_prompt(lenses):
    item = _with_quotes(lenses, BESSEMER_AI_2025, [
        {"text": "forecast", "kind": "quantitative_forecast", "note": "curator note", "scorable": False},
    ], scorable=False, scorable_reason="curator reason")
    projected = lens_for_prompt(item, _at(2026, 11, 13, 12))
    assert "scorable" not in projected and "scorable_reason" not in projected
    assert set(projected) <= _PROMPT_KEYS
    assert projected["quotes"] == [{"text": "forecast", "kind": "quantitative_forecast", "scorable": False}]


@pytest.mark.parametrize("bad", ["false", 0, 1, None, []])
def test_validate_lens_rejects_non_boolean_scorable(lenses, bad):
    at_quote = _with_quotes(lenses, BESSEMER_AI_2025, [{"text": "f", "kind": "quantitative_forecast", "scorable": bad}])
    assert any("quotes[0].scorable" in e for e in validate_lens(at_quote))
    at_item = _with_quotes(lenses, BESSEMER_AI_2025, [{"text": "f", "kind": "quantitative_forecast"}], scorable=bad)
    assert any("scorable must be true or false" in e for e in validate_lens(at_item))


@pytest.mark.parametrize("kind", ["documentary_fact", "analyst_interpretation"])
def test_validate_lens_rejects_scorable_true_on_a_non_forecast_quote(lenses, kind):
    item = _with_quotes(lenses, BESSEMER_AI_2025, [{"text": "q", "kind": kind, "scorable": True}])
    assert any("only a quantitative_forecast can be scorable" in e for e in validate_lens(item))
