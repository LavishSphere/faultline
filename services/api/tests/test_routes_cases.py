"""GET /api/cases: public case views only (ReplayCasePublic), never sealed outcomes.

Isolation is checked three ways: the response model has no outcome field (test_contracts.py), a
case file that smuggles an outcome is rejected without echoing it, and a canary planted only in
data/sealed_outcomes/ never appears in any /api/cases response, even via a symlink.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from test_temporal_gate import evidence_dict, quote_dict

from main import create_app

REAL_DATA = Path(__file__).resolve().parent.parent / "data"
OUTCOME_LIKE = re.compile(r"outcome|resolution|resolved|settle|result|winner|final_price", re.IGNORECASE)
CANARY = f"CANARY-{uuid.uuid4()}"
ISO_DATETIME = re.compile(r"\d{4}-\d{2}-\d{2}(?:T[0-9:.]+(?:Z|[+-]\d{2}:\d{2})?)?")


def _case(event_id: str, **overrides) -> dict:
    """Test-only SYNTHETIC case in the internal ReplayCase shape (as stored under data/demo_cases/)."""
    case = {
        "event_id": event_id,
        "title": f"TEST FIXTURE {event_id}",
        "as_of": "2026-01-21T00:00:00Z",
        "horizon_days": 7,
        "resolution_rule": "TEST FIXTURE: resolves YES if the test condition holds.",
        "evidence_ids": ["ev-1", "ev-2"],
        "market_quote_id": None,
        "snapshot_hash": "sha256:" + "b" * 64,
        "synthetic": True,
        "contamination_flag": "unlikely",
        "provenance": "SYNTHETIC",
    }
    case.update(overrides)
    return case


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    d = tmp_path / "data"
    (d / "demo_cases").mkdir(parents=True)
    sealed = d / "sealed_outcomes"
    sealed.mkdir()
    # Excluded data only: the canary and the outcome exist nowhere on the public path.
    (sealed / "case-a.json").write_text(
        json.dumps({"event_id": "case-a", "outcome": "YES", "resolved_at": "2026-01-28T00:00:00Z", "note": CANARY}),
        encoding="utf-8",
    )
    monkeypatch.setenv("FAULTLINE_DATA_DIR", str(d))
    return d


@pytest.fixture
def client(data_dir):
    return TestClient(create_app())


def _file(case: dict, **siblings) -> dict:
    """Case file in the docs/EVALUATION_PROTOCOL.md §7 shape: {"case": ReplayCase, ...}."""
    return {"case": case, **siblings}


# Full NormalizedQuote / EvidenceItem fixtures: since #44 the temporal gate (EvidenceStore) loads every case file.
QUOTE = quote_dict(datetime(2026, 1, 20, 12, 0, tzinfo=UTC), "0.5000", market_id="TEST-FIXTURE")
EV_1 = evidence_dict("ev-1", datetime(2026, 1, 20, 0, 0, tzinfo=UTC), "TEST FIXTURE text.", event_id="case-a")


def _write_case(data_dir: Path, name: str, payload) -> None:
    (data_dir / "demo_cases" / name).write_text(json.dumps(payload), encoding="utf-8")


def _walk_keys(node) -> list[str]:
    if isinstance(node, dict):
        return [k for k in node if OUTCOME_LIKE.search(k)] + [x for v in node.values() for x in _walk_keys(v)]
    if isinstance(node, list):
        return [x for v in node for x in _walk_keys(v)]
    return []


def _walk_strings(node) -> list[str]:
    if isinstance(node, dict):
        return [x for k, v in node.items() for x in [k, *_walk_strings(v)]]
    if isinstance(node, list):
        return [x for v in node for x in _walk_strings(v)]
    return [node] if isinstance(node, str) else []


# --------------------------------------------------------------------------- availability


def test_no_case_directory_is_empty_and_not_available(client, data_dir):
    (data_dir / "demo_cases").rmdir()
    body = client.get("/api/cases").json()
    assert body["status"] == "NOT AVAILABLE"
    assert body["items"] == []
    assert any("NOT AVAILABLE" in n for n in body["notes"])


def test_empty_case_directory_is_empty_list(client):
    resp = client.get("/api/cases")
    assert resp.status_code == 200
    assert resp.json()["items"] == []
    assert resp.json()["status"] == "NOT AVAILABLE"


# --------------------------------------------------------------------------- public projection


def test_cases_are_listed_as_public_views_sorted_by_file_name(client, data_dir):
    _write_case(data_dir, "case-b.json", _file(_case("case-b")))
    # Bundled evidence / quotes are allowed (not served here); the quote's YES side marker is allow-listed.
    _write_case(data_dir, "case-a.json", _file(_case("case-a"), evidence=[EV_1],
                                               market_quotes=[QUOTE], curation_notes="test fixture"))
    body = client.get("/api/cases").json()
    assert body["status"] == "AVAILABLE"
    assert [c["event_id"] for c in body["items"]] == ["case-a", "case-b"]
    first = body["items"][0]
    assert first["question_criteria"] == "TEST FIXTURE: resolves YES if the test condition holds."
    assert "resolution_rule" not in first
    assert "evidence" not in first and "market_quotes" not in first
    assert first["provenance"] == "SYNTHETIC"
    assert first["contamination_flag"] == "unlikely"
    # EvidenceStore.public_case (#44): only ids the gate admits at the cutoff, not the case file's own list.
    assert first["evidence_ids"] == ["ev-1"]
    assert body["items"][1]["evidence_ids"] == []


def test_response_walk_no_outcome_keys_no_late_dates_no_canary(client, data_dir):
    _write_case(data_dir, "case-a.json", _file(_case("case-a"), market_quotes=[QUOTE]))
    _write_case(data_dir, "case-b.json", _file(_case("case-b", as_of="2026-03-01T12:00:00+00:00")))
    resp = client.get("/api/cases")
    assert resp.status_code == 200
    assert CANARY not in resp.text
    body = resp.json()
    assert _walk_keys(body) == []
    for item in body["items"]:
        as_of = datetime.fromisoformat(item["as_of"])
        for s in _walk_strings(item):
            for m in ISO_DATETIME.finditer(s):
                stamp = datetime.fromisoformat(m[0]) if "T" in m[0] else datetime.fromisoformat(m[0] + "T00:00:00Z")
                assert stamp <= as_of, (item["event_id"], m[0])


@pytest.mark.parametrize(
    "payload",
    [
        _file({**_case("case-a"), "outcome": "YES"}),  # inside the case
        _file({**_case("case-a"), "final_price": 0.99}),
        _file(_case("case-a"), outcome=CANARY, resolved_value=1),  # sibling of the case
        _file(_case("case-a"), evidence=[{"evidence_id": "ev-1", "meta": {"Settlement": CANARY}}]),  # nested
        _file(_case("case-a"), market_quotes=[{**QUOTE, "outcome": "NO"}]),  # only "YES" is a side marker
        _file(_case("case-a"), market_quotes=[{**QUOTE, "winner": CANARY}]),
        _file(_case("case-a"), evidence=[{"outcome": "YES"}]),  # side marker allowed on quotes only
    ],
)
def test_case_file_with_outcome_key_anywhere_is_rejected_without_echo(client, data_dir, payload):
    _write_case(data_dir, "case-a.json", payload)
    resp = client.get("/api/cases")
    assert resp.status_code == 500
    body = resp.json()
    assert body["code"] == "DATA_INVALID"
    assert "a.json" in body["message"]
    assert CANARY not in resp.text
    assert "0.99" not in resp.text and '"NO"' not in resp.text


@pytest.mark.parametrize("target", ["sealed_outcomes/case-a.json", "sealed_outcomes/valid-looking.json"])
def test_symlink_out_of_demo_cases_is_refused_unread(client, data_dir, target, make_symlink):
    # The second target is a schema-valid case, so only the path check (not validation) can stop it.
    (data_dir / "sealed_outcomes" / "valid-looking.json").write_text(
        json.dumps(_file(_case("case-z", title=CANARY))), encoding="utf-8"
    )
    _write_case(data_dir, "case-a.json", _file(_case("case-a")))
    make_symlink(data_dir / "demo_cases" / "z.json", data_dir / target)
    resp = client.get("/api/cases")
    assert resp.status_code == 500
    body = resp.json()
    assert body["code"] == "DATA_INVALID"
    assert "refusing to read" in body["message"]
    assert CANARY not in resp.text
    assert str(data_dir) not in resp.text


def test_cases_directory_symlinked_to_sealed_outcomes_is_refused(client, data_dir, make_symlink):
    (data_dir / "demo_cases").rmdir()
    (data_dir / "sealed_outcomes" / "valid-looking.json").write_text(
        json.dumps(_file(_case("case-z", title=CANARY))), encoding="utf-8"
    )
    make_symlink(data_dir / "demo_cases", data_dir / "sealed_outcomes", target_is_directory=True)
    resp = client.get("/api/cases")
    assert resp.status_code == 500
    assert resp.json()["code"] == "DATA_INVALID"
    assert CANARY not in resp.text


@pytest.mark.parametrize(
    "payload",
    [
        "{nope",
        [],
        {"case": "x"},
        {"case": {"event_id": "only-an-id"}},
        _case("bare-case"),  # bare ReplayCase without the "case" wrapper
        _file(_case("case-a"), extra_material=[1]),  # top-level keys are allow-listed
    ],
)
def test_invalid_case_file_is_data_invalid(client, data_dir, payload):
    path = data_dir / "demo_cases" / "bad.json"
    path.write_text(payload if isinstance(payload, str) else json.dumps(payload), encoding="utf-8")
    resp = client.get("/api/cases")
    assert resp.status_code == 500
    assert resp.json()["code"] == "DATA_INVALID"


def test_duplicate_event_ids_are_data_invalid(client, data_dir):
    _write_case(data_dir, "case-a.json", _file(_case("case-a")))
    _write_case(data_dir, "b.json", _file(_case("case-a")))
    resp = client.get("/api/cases")
    assert resp.status_code == 500
    assert resp.json()["code"] == "DATA_INVALID"


def test_non_json_files_are_ignored(client, data_dir):
    (data_dir / "demo_cases" / "README.md").write_text("notes", encoding="utf-8")
    (data_dir / "demo_cases" / ".gitkeep").write_text("", encoding="utf-8")
    (data_dir / "demo_cases" / "._a.json").write_text("\x00 resource fork", encoding="utf-8")
    assert client.get("/api/cases").json()["items"] == []


@pytest.mark.skipif(not (REAL_DATA / "demo_cases").is_dir(), reason="data/demo_cases not merged yet (#20)")
def test_real_case_files_list_without_outcomes(monkeypatch):
    monkeypatch.setenv("FAULTLINE_DATA_DIR", str(REAL_DATA))
    resp = TestClient(create_app()).get("/api/cases")
    assert resp.status_code == 200, resp.text
    assert _walk_keys(resp.json()) == []
