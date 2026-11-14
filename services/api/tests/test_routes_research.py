"""GET /api/vc-lenses: point-in-time (as_of) vs Live Explore, strict as_of parsing, no post-cutoff leakage.

The leakage walk below is deliberately self-contained (not imported from core or other tests), so
weakening the production filter cannot weaken the test.
"""

from __future__ import annotations

import json
import re
import shutil
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from core.research import LABEL, PROVENANCE, eligible_lenses, lens_for_prompt, load_lenses, public_from
from main import create_app

REAL_DATA = Path(__file__).resolve().parent.parent / "data"
OUTCOME_LIKE = re.compile(r"outcome|resolution|resolved|settle|result|winner|final_price", re.IGNORECASE)

SEQUOIA = "sequoia-partnering-with-etched"
BESSEMER = "bessemer-state-of-ai-2025"


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    d = tmp_path / "data"
    d.mkdir()
    shutil.copy(REAL_DATA / "research_lenses.json", d / "research_lenses.json")
    monkeypatch.setenv("FAULTLINE_DATA_DIR", str(d))
    return d


@pytest.fixture
def client(data_dir):
    return TestClient(create_app())


@pytest.fixture(scope="module")
def lenses():
    return load_lenses(REAL_DATA / "research_lenses.json")


def _get(client, as_of: str | None = None):
    return client.get("/api/vc-lenses", params={} if as_of is None else {"as_of": as_of})


# --------------------------------------------------------------------------- leakage walk

_ISO = re.compile(r"(?<!\d)(\d{4})-(\d{2})(?:-(\d{2}))?(?!\d)")
_WAYBACK = re.compile(r"(?<!\d)(\d{4})(\d{2})(\d{2})\d{6}(?!\d)")
_NAMED = re.compile(
    r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(\d{1,2}),?\s+(\d{4})\b", re.IGNORECASE
)
_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}
_YEAR = re.compile(r"(?<!\d)((?:19|20)\d{2})(?!\d)")


def _late(text: str, cutoff: date, bare_years: bool) -> list[str]:
    out = []
    for m in _ISO.finditer(text):
        y, mo, d = int(m[1]), int(m[2]), m[3]
        if not 1 <= mo <= 12:
            continue
        if (d and date(y, mo, int(d)) > cutoff) or (not d and (y, mo) > (cutoff.year, cutoff.month)):
            out.append(m[0])
    out += [m[0] for m in _WAYBACK.finditer(text) if date(int(m[1]), int(m[2]), int(m[3])) > cutoff]
    out += [m[0] for m in _NAMED.finditer(text)
            if date(int(m[3]), _MONTHS[m[1].lower()[:3]], int(m[2])) > cutoff]
    if bare_years:
        out += [m[0] for m in _YEAR.finditer(text) if int(m[0]) > cutoff.year]
    return out


def walk(node, cutoff: date, in_quote: bool = False) -> tuple[list[str], list[str]]:
    """(outcome-like keys, date strings later than cutoff) anywhere in a JSON value.

    Bare years are not checked inside verbatim quote text (a quote public at as_of may name a future
    horizon such as "2025-2026"); full and partial dates are checked everywhere.
    """
    keys: list[str] = []
    late: list[str] = []
    if isinstance(node, dict):
        for k, v in node.items():
            if OUTCOME_LIKE.search(str(k)):
                keys.append(str(k))
            late += _late(str(k), cutoff, True)
            k2, l2 = walk(v, cutoff, in_quote or k == "quotes")
            keys += k2
            late += l2
    elif isinstance(node, list):
        for v in node:
            k2, l2 = walk(v, cutoff, in_quote)
            keys += k2
            late += l2
    elif isinstance(node, str):
        late += _late(node, cutoff, not in_quote)
    return keys, late


def _boundaries(lenses) -> list[datetime]:
    out = {datetime(2023, 1, 1, tzinfo=UTC), datetime(2026, 11, 13, 12, tzinfo=UTC)}
    for item in lenses:
        for field in ("available_at", "published_at"):
            if item.get(field):
                day = date.fromisoformat(item[field])
                edge = public_from(day)
                out |= {datetime(day.year, day.month, day.day, tzinfo=UTC), edge - timedelta(seconds=1), edge,
                        edge + timedelta(days=1)}
    return sorted(out)


def test_walk_is_not_vacuous(client):
    # The Live Explore response carries curation metadata (accessed_at 2026-11-13) that WOULD leak at an
    # early cutoff; the walk must see it, or the point-in-time test below proves nothing.
    _, late = walk(_get(client).json(), date(2025, 8, 15))
    assert "2026-11-13" in late


def test_point_in_time_response_has_no_outcome_keys_or_late_dates_at_every_boundary(client, lenses):
    checked = 0
    for as_of in _boundaries(lenses):
        resp = _get(client, as_of.isoformat())
        assert resp.status_code == 200, resp.text
        body = resp.json()
        keys, late = walk(body, as_of.date())
        assert keys == [], (as_of, keys)
        assert late == [], (as_of, late)
        checked += len(body["items"])
    assert checked > 0


# --------------------------------------------------------------------------- point-in-time mode


def test_point_in_time_items_are_exactly_the_prompt_projection(client, lenses):
    as_of = datetime(2026, 7, 1, tzinfo=UTC)
    body = _get(client, "2026-07-01T00:00:00Z").json()
    assert body["mode"] == "point_in_time"
    assert body["label"] == LABEL == "RESEARCH CONTEXT"
    assert body["provenance"] == PROVENANCE == "REAL_HISTORICAL"
    assert datetime.fromisoformat(body["as_of"]) == as_of
    expected = [lens_for_prompt(item, as_of) for item in eligible_lenses(as_of, lenses)]
    got = [{k: v for k, v in item.items() if v is not None} for item in body["items"]]
    assert got == expected
    assert body["excluded_not_yet_public"] == len(lenses) - len(expected)
    for item in body["items"]:
        assert set(item) <= {"id", "firm", "title", "url", "published_at", "thesis", "hypotheses", "quotes"}


def test_sequoia_excluded_before_its_publication_and_bessemer_included(client):
    ids = [i["id"] for i in _get(client, "2026-07-20T00:00:00+00:00").json()["items"]]
    assert BESSEMER in ids
    assert SEQUOIA not in ids
    ids_after = [i["id"] for i in _get(client, "2026-07-25T00:00:00+00:00").json()["items"]]
    assert SEQUOIA in ids_after


def test_offset_as_of_is_normalized_to_utc(client):
    body = _get(client, "2026-07-24T20:00:00-05:00").json()
    assert body["as_of"].startswith("2026-07-25T01:00:00")


def test_nothing_eligible_reports_empty_with_exclusion_count(client, lenses):
    body = _get(client, "2020-01-01T00:00:00Z").json()
    assert body["items"] == []
    assert body["status"] == "NOT AVAILABLE"
    assert body["excluded_not_yet_public"] == len(lenses)


@pytest.mark.parametrize("extreme", ["0001-01-01T00:00:00+14:00", "9999-12-31T23:59:59-14:00"])
def test_as_of_outside_utc_range_is_coded_422(client, extreme):
    resp = _get(client, extreme)
    assert resp.status_code == 422, resp.text
    assert resp.json()["code"] == "VALIDATION_ERROR"


def test_repeated_as_of_is_coded_422(client):
    resp = client.get("/api/vc-lenses?as_of=2026-07-01T00:00:00Z&as_of=2020-01-01T00:00:00Z")
    assert resp.status_code == 422
    body = resp.json()
    assert body["code"] == "VALIDATION_ERROR"
    assert ["query", "as_of"] in [e["loc"] for e in body["errors"]]


@pytest.mark.parametrize(
    "bad",
    [
        "2026-07-01",  # calendar date
        "2026-07-01T00:00:00",  # naive
        "2026-07-01T00:00:00 00:00",  # unencoded '+' arrives as a space
        "1700000000",  # unix seconds
        "yesterday",
        "",
    ],
)
def test_non_instant_as_of_is_coded_422(client, bad):
    resp = _get(client, bad)
    assert resp.status_code == 422, resp.text
    body = resp.json()
    assert body["code"] == "VALIDATION_ERROR"
    assert ["query", "as_of"] in [e["loc"] for e in body["errors"]]


# --------------------------------------------------------------------------- Live Explore mode


def test_without_as_of_returns_all_items_labeled_live_explore(client, lenses):
    body = _get(client).json()
    assert body["mode"] == "live_explore"
    assert body["label"] == "RESEARCH CONTEXT"
    assert body["as_of"] is None
    assert "LIVE EXPLORE" in body["mode_label"]
    assert [i["id"] for i in body["items"]] == [i["id"] for i in lenses]
    first = body["items"][0]
    assert first["limitations"] and first["available_at"] and first["accessed_at"]
    assert all("note" in q for q in first["quotes"])


# --------------------------------------------------------------------------- data problems


@pytest.mark.parametrize("as_of", [None, "2026-07-01T00:00:00Z"])
def test_missing_file_is_not_available(client, data_dir, as_of):
    (data_dir / "research_lenses.json").unlink()
    resp = _get(client, as_of)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "NOT AVAILABLE"
    assert body["items"] == []
    assert any("NOT AVAILABLE" in n for n in body["notes"])


def test_missing_file_reports_exclusion_count_as_null_not_zero(client, data_dir):
    # With no dataset we cannot know how many lenses were excluded; 0 would be a fabricated count.
    (data_dir / "research_lenses.json").unlink()
    body = _get(client, "2026-07-01T00:00:00Z").json()
    assert "excluded_not_yet_public" in body
    assert body["excluded_not_yet_public"] is None


# --------------------------------------------------------------------------- scorable (issue #52)


def _write_scorable_fixture(data_dir: Path) -> dict:
    """Copy of the real dataset with scorable set at quote level (Sequoia) and item level (Bessemer)."""
    path = data_dir / "research_lenses.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    by_id = {item["id"]: item for item in payload["items"]}
    by_id[SEQUOIA]["quotes"][0]["scorable"] = False
    by_id[BESSEMER]["scorable"] = False
    by_id[BESSEMER]["scorable_reason"] = "curator reason, never returned"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return by_id


def _quote_scorable(item: dict, quote: dict) -> bool | None:
    if "scorable" in quote:
        return quote["scorable"]
    if quote["kind"] == "quantitative_forecast":
        return item.get("scorable")
    return None


def _assert_scorable_matches(body: dict, by_id: dict) -> int:
    seen = 0
    for item in body["items"]:
        source = by_id[item["id"]]
        assert "scorable" not in item and "scorable_reason" not in item
        for got, quote in zip(item["quotes"], source["quotes"], strict=True):
            expected = _quote_scorable(source, quote)
            if expected is None:
                assert "scorable" not in got, (item["id"], got)  # absent = NOT AVAILABLE, never null or a guess
            else:
                assert got["scorable"] is expected, (item["id"], got)
                seen += 1
    return seen


@pytest.mark.parametrize("as_of", [None, "2026-11-13T12:00:00Z"])
def test_scorable_is_exposed_in_both_modes(client, data_dir, as_of):
    by_id = _write_scorable_fixture(data_dir)
    resp = _get(client, as_of)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["mode"] == ("live_explore" if as_of is None else "point_in_time")
    assert _assert_scorable_matches(body, by_id) >= 2  # Sequoia quote-level + Bessemer forecast(s)


def test_point_in_time_scorable_is_exactly_the_prompt_projection(client, data_dir):
    _write_scorable_fixture(data_dir)
    as_of = datetime(2026, 11, 13, 12, tzinfo=UTC)
    lenses = load_lenses(data_dir / "research_lenses.json")
    expected = [lens_for_prompt(item, as_of) for item in eligible_lenses(as_of, lenses)]
    body = _get(client, "2026-11-13T12:00:00Z").json()
    assert [item["quotes"] for item in body["items"]] == [item["quotes"] for item in expected]


def test_real_dataset_has_no_null_scorable(client):
    for as_of in (None, "2026-11-13T12:00:00Z"):
        for item in _get(client, as_of).json()["items"]:
            assert all(q.get("scorable", True) is not None for q in item["quotes"])


@pytest.mark.parametrize("content", ["{oops", json.dumps({"label": "RESEARCH CONTEXT", "items": []})])
def test_invalid_file_is_data_invalid(client, data_dir, content):
    (data_dir / "research_lenses.json").write_text(content, encoding="utf-8")
    resp = _get(client)
    assert resp.status_code == 500
    assert resp.json()["code"] == "DATA_INVALID"
    assert str(data_dir) not in resp.text
