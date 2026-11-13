"""GET /api/cases/{case_id}/evidence?as_of= (SPEC §8; #44): only what the temporal gate admits. Pre-reveal.

All fixtures are SYNTHETIC (tests/test_routes_replay.gate_case_file). The canary sits only in excluded evidence.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from test_routes_replay import CANARY, EVENT, MARKET_REF, assert_pre_reveal_clean, gate_case_file, make_world
from test_temporal_gate import AS_OF

from core.temporal_gate import EVIDENCE_PROMPT_FIELDS, EvidenceStore

ITEM_KEYS = set(EVIDENCE_PROMPT_FIELDS)
QUOTE_KEYS = {
    "venue", "market_id", "p_yes", "quote_kind", "ts", "spread", "volume", "open_interest", "period_seconds", "label",
}
BODY_KEYS = {
    "status", "event_id", "as_of", "case_as_of", "items", "market_quotes", "market_at_cutoff", "excluded_by_reason",
    "notes",
}


@pytest.fixture
def world(tmp_path, monkeypatch):
    return make_world(tmp_path, monkeypatch)


def _get(world, case_id=EVENT, **params):
    return world.client().get(f"/api/cases/{case_id}/evidence", params=params)


def _instant(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def test_default_as_of_is_the_case_cutoff_and_only_admitted_items_are_served(world):
    resp = _get(world)
    assert resp.status_code == 200, resp.text
    assert_pre_reveal_clean(resp)
    body = resp.json()
    assert set(body) == BODY_KEYS
    assert body["status"] == "AVAILABLE" and body["event_id"] == EVENT
    assert _instant(body["as_of"]) == _instant(body["case_as_of"]) == AS_OF
    assert [e["evidence_id"] for e in body["items"]] == ["evid_ok", "evid_edge"]  # boundary item included
    for item in body["items"]:
        assert set(item) == ITEM_KEYS  # the prompt projection: no observed_at, archive_url or content hash
        assert _instant(item["available_at"]) <= AS_OF and _instant(item["published_at"]) <= AS_OF
    # Excluded items: counts by reason only, never ids or content.
    assert body["excluded_by_reason"] == {"available_after_as_of": 1, "retrospective_unverified": 1}
    assert "evid_future" not in resp.text and "evid_unverified" not in resp.text
    [quote] = body["market_quotes"]
    assert set(quote) == QUOTE_KEYS and quote["p_yes"] == 0.56 and "price-derived" in quote["label"]
    assert _instant(quote["ts"]) == AS_OF - timedelta(hours=2)
    m = body["market_at_cutoff"]
    assert m["status"] == "AVAILABLE" and m["ref"] == MARKET_REF and m["p_yes"] == 0.56


def test_items_match_the_gate_projection_exactly(world):
    body = _get(world).json()
    cases = EvidenceStore.from_dir(world.data / "demo_cases")
    snap = cases.get_as_of(EVENT, AS_OF)
    assert [e["content"] for e in body["items"]] == [e["content"] for e in snap.evidence]
    assert [e["evidence_id"] for e in body["items"]] == list(cases.public_case(EVENT).evidence_ids)


def test_earlier_as_of_is_stricter_and_a_stale_market_is_not_available(world):
    earlier = AS_OF - timedelta(days=3)
    resp = _get(world, as_of=earlier.isoformat())
    assert resp.status_code == 200, resp.text
    assert_pre_reveal_clean(resp)
    body = resp.json()
    assert _instant(body["as_of"]) == earlier and _instant(body["case_as_of"]) == AS_OF
    assert [e["evidence_id"] for e in body["items"]] == ["evid_ok"]
    assert body["market_quotes"] == []
    assert body["market_at_cutoff"]["status"] == "NOT AVAILABLE" and body["market_at_cutoff"]["p_yes"] is None
    assert body["excluded_by_reason"]["no_quote_within_24h_before_as_of"] == 1


def test_nothing_public_yet_is_not_available(world):
    body = _get(world, as_of=(AS_OF - timedelta(days=30)).isoformat()).json()
    assert body["status"] == "NOT AVAILABLE" and body["items"] == []
    assert any("NOT AVAILABLE" in n for n in body["notes"])


def test_as_of_after_the_case_cutoff_is_422(world):
    resp = _get(world, as_of=(AS_OF + timedelta(seconds=1)).isoformat())
    assert resp.status_code == 422 and resp.json()["code"] == "VALIDATION_ERROR"
    assert "after the case cutoff" in resp.json()["message"]
    assert_pre_reveal_clean(resp)


@pytest.mark.parametrize(
    "bad",
    ["2025-01-15", "2025-01-15T12:00:00", "not-a-date-XYZZY", "2025-01-15T12:00:00 00:00", "2025-13-40T99:99Z"],
)
def test_malformed_or_naive_as_of_is_422_without_echo(world, bad):
    resp = _get(world, as_of=bad)
    assert resp.status_code == 422, resp.text
    assert resp.json()["code"] == "VALIDATION_ERROR"
    assert bad not in resp.text


@pytest.mark.parametrize("extreme", ["0001-01-01T00:00:00+23:59", "9999-12-31T23:59:59-23:59"])
def test_as_of_out_of_range_in_utc_is_422(world, extreme):
    resp = _get(world, as_of=extreme)
    assert resp.status_code == 422, resp.text
    assert resp.json()["code"] == "VALIDATION_ERROR"


def test_offset_as_of_is_normalized(world):
    resp = _get(world, as_of="2025-01-15T13:00:00+01:00")  # == AS_OF
    assert resp.status_code == 200, resp.text
    assert _instant(resp.json()["as_of"]) == AS_OF


def test_unknown_case_and_missing_directory_are_404(world):
    resp = _get(world, case_id="no_such_case")
    assert resp.status_code == 404 and resp.json()["code"] == "NOT_FOUND"
    (world.data / "demo_cases" / f"{EVENT}.json").unlink()
    (world.data / "demo_cases").rmdir()
    resp = _get(world)
    assert resp.status_code == 404 and resp.json()["code"] == "NOT_FOUND"
    assert CANARY not in resp.text


def test_case_file_with_an_outcome_key_is_refused_not_stripped(world):
    path = world.data / "demo_cases" / f"{EVENT}.json"
    text = path.read_text(encoding="utf-8").replace('"title": "SYNTHETIC source evid_ok"',
                                                    f'"title": "SYNTHETIC source evid_ok", "settlement": "{CANARY}"')
    path.write_text(text, encoding="utf-8")
    resp = _get(world)
    assert resp.status_code == 500 and resp.json()["code"] == "DATA_INVALID"
    assert CANARY not in resp.text


def test_gate_load_error_is_data_invalid_and_names_the_problem(world):
    """E.g. a market_quote_id that names no market in the file (the gate refuses an ambiguous benchmark)."""
    world.write_case(gate_case_file(market_quote_id="kalshi.SOME-OTHER-FORMAT"))
    for resp in (world.client().get("/api/cases"), _get(world)):
        assert resp.status_code == 500 and resp.json()["code"] == "DATA_INVALID"
        assert "market_quote_id" in resp.json()["message"]
        assert CANARY not in resp.text and str(world.data) not in resp.text


def test_polymarket_price_history_point_quotes_are_served(tmp_path, monkeypatch):
    """markets.base.QuoteKind includes "price_history_point" (Polymarket history); the views must accept it."""
    world = make_world(tmp_path, monkeypatch)
    payload = gate_case_file()
    for q in payload["market_quotes"]:
        q.update(venue="polymarket", quote_kind="price_history_point")
    world.write_case(payload)
    body = _get(world).json()
    assert body["market_quotes"][0]["quote_kind"] == "price_history_point"
    assert body["market_at_cutoff"]["quote_kind"] == "price_history_point"
    assert body["market_at_cutoff"]["venue"] == "polymarket" and body["market_at_cutoff"]["p_yes"] == 0.56
