"""Tests for scripts/collect_market_snapshots.py (issue #51).

HTTP is mocked with httpx.MockTransport serving SYNTHETIC hand-written bodies built from the documented
schemas (see markets/README.md). They are not API responses and their values mean nothing. Sockets are
blocked, so no test can reach the network. The last section checks the REAL HISTORICAL snapshots the
collector stored under data/raw/ (offline, from saved bytes).
"""

from __future__ import annotations

import importlib.util
import json
import socket
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

import httpx
import pytest

from markets.base import MarketDataError
from markets.normalize import parse_iso_utc
from markets.raw_store import find_outcome_keys, load_manifest, verify_manifest

API_DIR = Path(__file__).resolve().parents[1]
REPO = API_DIR.parents[1]
RAW = API_DIR / "data" / "raw"

SCRIPT = REPO / "scripts" / "collect_market_snapshots.py"
_spec = importlib.util.spec_from_file_location("collect_market_snapshots", SCRIPT)
col = importlib.util.module_from_spec(_spec)
sys.modules["collect_market_snapshots"] = col
_spec.loader.exec_module(col)

CLOSE = datetime(2026, 7, 29, 17, 59, tzinfo=UTC)  # synthetic scheduled close
K_TICKER, K_EVENT, K_SERIES = "SYN-H0", "SYN-EVT", "SYNSERIES"
PM_ID, PM_YES, PM_NO = "999000001", "111", "222"


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def deny(*a, **k):
        raise RuntimeError("network access is forbidden in tests")

    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket.socket, "connect_ex", deny)
    monkeypatch.setattr(socket, "create_connection", deny)
    monkeypatch.setattr(socket, "getaddrinfo", deny)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


class FakeVenues:
    """SYNTHETIC Kalshi + Polymarket endpoints. Records every request."""

    def __init__(self, *, settled_at=CLOSE + timedelta(minutes=20), cutoff=datetime(2026, 9, 13, tzinfo=UTC),
                 candle_extra=None, pm_points=None, pm_close=CLOSE):
        self.settled_at, self.cutoff = settled_at, cutoff
        self.candle_extra = candle_extra or {}
        self.pm_points = pm_points  # callable(start, end) -> list[dict] or None for default
        self.pm_close = pm_close
        self.requests: list[httpx.Request] = []

    @property
    def live(self) -> bool:
        return not self.settled_at < self.cutoff

    def _market(self):
        return {"market": {
            "ticker": K_TICKER, "event_ticker": K_EVENT, "market_type": "binary", "title": "Synthetic",
            "yes_sub_title": "Synthetic yes", "rules_primary": "Synthetic rules.", "status": "finalized",
            "open_time": "2026-01-01T00:00:00Z", "close_time": _iso(CLOSE),
            # outcome keys: present so tests prove the collector never stores this body
            "result": "yes", "settlement_value_dollars": "1.0000", "settlement_ts": _iso(self.settled_at),
        }}

    def _candles(self, req, live):
        q = req.url.params
        lo, hi, step = int(q["start_ts"]), int(q["end_ts"]), int(q["period_interval"]) * 60
        sfx = "_dollars" if live else ""
        vol, oi = ("volume_fp", "open_interest_fp") if live else ("volume", "open_interest")
        candles = [{
            "end_period_ts": t,
            "yes_bid": {"close" + sfx: "0.4000"}, "yes_ask": {"close" + sfx: "0.4200"},
            "price": {"close" + sfx: "0.4100"}, vol: "1.00", oi: "2.00", **self.candle_extra,
        } for t in range(lo, hi + 1, step)]
        return {"ticker": K_TICKER, "candlesticks": candles}

    def _pm_market(self):
        return {"id": PM_ID, "question": "Synthetic?", "outcomes": '["Yes", "No"]',
                "clobTokenIds": json.dumps([PM_YES, PM_NO]), "endDate": _iso(self.pm_close),
                "startDate": "2026-01-01T00:00:00Z", "negRisk": True, "version": "v1",
                "outcomePrices": '["1", "0"]', "umaResolutionStatus": "resolved", "closed": True}

    def _pm_history(self, req):
        q = req.url.params
        lo, hi = int(q["startTs"]), int(q["endTs"])
        assert q["market"] == PM_YES
        pts = self.pm_points(lo, hi) if self.pm_points else [{"t": t + 5, "p": 0.41} for t in range(lo, hi - 5, 3600)]
        return {"history": pts}

    def __call__(self, req: httpx.Request) -> httpx.Response:
        self.requests.append(req)
        u = urlparse(str(req.url))
        host, path = u.netloc, u.path
        if host == "external-api.kalshi.com":
            path = path.removeprefix("/trade-api/v2")
            if path == "/historical/cutoff":
                c = _iso(self.cutoff)
                body = {"market_settled_ts": c, "trades_created_ts": c, "orders_updated_ts": c}
                return httpx.Response(200, json=body)
            if path == f"/markets/{K_TICKER}":
                return httpx.Response(200, json=self._market()) if self.live else httpx.Response(404, json={})
            if path == f"/historical/markets/{K_TICKER}":
                return httpx.Response(200, json=self._market())
            if path == f"/events/{K_EVENT}":
                return httpx.Response(200, json={"event": {"event_ticker": K_EVENT, "series_ticker": K_SERIES,
                                                           "mutually_exclusive": True}})
            if path == f"/historical/markets/{K_TICKER}/candlesticks" and not self.live:
                return httpx.Response(200, json=self._candles(req, live=False))
            if path == f"/series/{K_SERIES}/markets/{K_TICKER}/candlesticks" and self.live:
                return httpx.Response(200, json=self._candles(req, live=True))
        if host == "gamma-api.polymarket.com" and path == f"/markets/{PM_ID}":
            return httpx.Response(200, json=self._pm_market())
        if host == "clob.polymarket.com" and path == "/prices-history":
            return httpx.Response(200, json=self._pm_history(req))
        return httpx.Response(404, json={"error": f"unmocked {req.url}"})

    def count(self, fragment: str) -> int:
        return sum(fragment in str(r.url) for r in self.requests)


def _collect(venue, mid, fake, raw_root, **kw):
    client = col.make_client(httpx.MockTransport(fake))
    return col.collect_market(venue, mid, provider=col.make_provider(venue, client), raw_root=raw_root, **kw)


def _files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*") if p.is_file())


# --- window rule -------------------------------------------------------------------------------------


def test_t_minus_window_reproduces_pr12_window():
    w = col.t_minus_window(CLOSE, t_minus_days=7, lookback_days=14)
    assert (w.start, w.end) == (datetime(2026, 7, 8, tzinfo=UTC), datetime(2026, 7, 22, tzinfo=UTC))


def test_t_minus_window_default_and_end_never_after_t_minus():
    w = col.t_minus_window(CLOSE)
    assert (w.start, w.end) == (datetime(2026, 7, 19, tzinfo=UTC), datetime(2026, 7, 22, tzinfo=UTC))
    for close in (datetime(2026, 7, 29, tzinfo=UTC), datetime(2026, 7, 29, 23, 59, tzinfo=UTC)):
        assert col.t_minus_window(close).end <= close - timedelta(days=7)
    with pytest.raises(MarketDataError):
        col.t_minus_window(datetime(2026, 7, 29))  # naive


def test_lead_guard():
    ok = col.explicit_window(CLOSE - timedelta(days=10), CLOSE - timedelta(days=7), CLOSE)
    col.check_lead(ok, 7)
    late = col.explicit_window(CLOSE - timedelta(days=10), CLOSE - timedelta(days=2), CLOSE)
    with pytest.raises(MarketDataError, match="near-settlement"):
        col.check_lead(late, 7)


def test_covered_requires_contiguous_matching_spans():
    w = col.explicit_window(datetime(2026, 7, 19, tzinfo=UTC), datetime(2026, 7, 22, tzinfo=UTC), CLOSE)
    lo, hi = int(w.start.timestamp()), int(w.end.timestamp())
    ep = "kalshi.live_candlesticks"
    e = lambda a, b, period=60: {"endpoint": ep, "params": {"start_ts": a, "end_ts": b, "period_interval": period}}  # noqa: E731
    static = {"period_interval": 60}
    assert col.covered([e(lo - 99, hi)], ep, static, w)
    assert col.covered([e(lo, lo + 100), e(lo + 100, hi)], ep, static, w)
    assert not col.covered([e(lo, lo + 100), e(lo + 200, hi)], ep, static, w)  # gap
    assert not col.covered([e(lo + 1, hi)], ep, static, w)  # starts late
    assert not col.covered([e(lo, hi, period=1)], ep, static, w)  # different granularity
    assert not col.covered([e(lo, hi)], "kalshi.historical_candlesticks", static, w)
    assert not col.covered([], ep, static, w)


# --- collection with mocked transport -------------------------------------------------------------------


def test_kalshi_historical_collect_stores_history_bytes_only(tmp_path):
    fake = FakeVenues()
    r = _collect("kalshi", K_TICKER, fake, tmp_path)
    assert r.status == "stored" and r.points == 73  # hourly, both ends inclusive over 3 days
    files = _files(tmp_path)
    assert [f.name for f in files if f.name != "manifest.json"] == [Path(r.paths[0]).name]
    (entry,) = load_manifest(tmp_path, "kalshi", K_TICKER)
    assert entry["endpoint"] == "kalshi.historical_candlesticks"
    assert entry["notes"]["window_end"] == "2026-07-22T00:00:00+00:00"
    assert entry["notes"]["data_tier"] == "historical"
    assert entry["params"]["end_ts"] == int(datetime(2026, 7, 22, tzinfo=UTC).timestamp())
    assert verify_manifest(tmp_path, "kalshi", K_TICKER) == []
    # The metadata body (with result/settlement_*) was fetched but never written anywhere.
    for f in files:
        assert find_outcome_keys(f.read_bytes()) == set()
        assert b"settlement" not in f.read_bytes() and b'"result"' not in f.read_bytes()
    assert all(req.method == "GET" for req in fake.requests)


def test_kalshi_live_tier_uses_series_endpoint(tmp_path):
    fake = FakeVenues(settled_at=datetime(2026, 9, 20, tzinfo=UTC))  # settled after the cutoff -> live tier
    r = _collect("kalshi", K_TICKER, fake, tmp_path)
    assert r.status == "stored"
    (entry,) = load_manifest(tmp_path, "kalshi", K_TICKER)
    assert entry["endpoint"] == "kalshi.live_candlesticks"
    assert f"/series/{K_SERIES}/markets/{K_TICKER}/candlesticks" in entry["url"]


def test_second_run_is_idempotent_and_fetches_no_history(tmp_path):
    fake = FakeVenues()
    _collect("kalshi", K_TICKER, fake, tmp_path)
    before = {p: p.read_bytes() for p in _files(tmp_path)}
    n_hist = fake.count("/candlesticks")
    r2 = _collect("kalshi", K_TICKER, fake, tmp_path)
    assert r2.status == "skipped_existing"
    assert fake.count("/candlesticks") == n_hist
    assert {p: p.read_bytes() for p in _files(tmp_path)} == before


def test_narrower_window_inside_existing_snapshot_is_skipped(tmp_path):
    fake = FakeVenues()
    _collect("kalshi", K_TICKER, fake, tmp_path, lookback_days=14)
    assert _collect("kalshi", K_TICKER, fake, tmp_path, lookback_days=3).status == "skipped_existing"


def test_new_window_appends_and_never_overwrites(tmp_path):
    fake = FakeVenues()
    r1 = _collect("kalshi", K_TICKER, fake, tmp_path)
    first = tmp_path / r1.paths[0]
    first_bytes = first.read_bytes()
    r2 = _collect("kalshi", K_TICKER, fake, tmp_path, t_minus_days=10)
    assert r2.status == "stored" and r2.paths != r1.paths
    assert first.read_bytes() == first_bytes
    assert len(load_manifest(tmp_path, "kalshi", K_TICKER)) == 2
    assert verify_manifest(tmp_path, "kalshi", K_TICKER) == []


def test_polymarket_collect_stores_clob_history_not_gamma(tmp_path):
    fake = FakeVenues()
    r = _collect("polymarket", PM_ID, fake, tmp_path)
    assert r.status == "stored" and r.points == 72
    (entry,) = load_manifest(tmp_path, "polymarket", PM_ID)
    assert entry["endpoint"] == "polymarket.clob_prices_history"
    assert entry["params"]["market"] == PM_YES and entry["params"]["fidelity"] == 60
    for f in _files(tmp_path):
        assert b"outcomePrices" not in f.read_bytes() and b"umaResolution" not in f.read_bytes()


def test_outcome_bearing_history_is_refused_and_nothing_written(tmp_path):
    fake = FakeVenues(candle_extra={"result": "yes"})
    with pytest.raises(MarketDataError, match="outcome keys"):
        _collect("kalshi", K_TICKER, fake, tmp_path)
    assert _files(tmp_path) == []


def test_points_after_window_end_are_refused(tmp_path):
    fake = FakeVenues(pm_points=lambda lo, hi: [{"t": lo + 5, "p": 0.4}, {"t": hi + 3600, "p": 0.99}])
    with pytest.raises(MarketDataError, match="after window end"):
        _collect("polymarket", PM_ID, fake, tmp_path)
    assert _files(tmp_path) == []


def test_window_inside_lead_refused_before_any_history_request(tmp_path):
    fake = FakeVenues()
    with pytest.raises(MarketDataError, match="near-settlement"):
        _collect("kalshi", K_TICKER, fake, tmp_path, start=CLOSE - timedelta(days=4), end=CLOSE - timedelta(days=1))
    assert fake.count("/candlesticks") == 0 and _files(tmp_path) == []


def test_venue_close_earlier_than_reference_is_enforced_unless_disabled(tmp_path):
    fake = FakeVenues(pm_close=CLOSE - timedelta(days=30))  # venue metadata says it closed a month earlier
    with pytest.raises(MarketDataError, match="near-settlement"):
        _collect("polymarket", PM_ID, fake, tmp_path, reference_close=CLOSE)
    r = _collect("polymarket", PM_ID, fake, tmp_path, reference_close=CLOSE, check_venue_close=False)
    assert r.status == "stored"


def test_empty_history_is_stored_and_reported_not_available(tmp_path):
    fake = FakeVenues(pm_points=lambda lo, hi: [])
    r = _collect("polymarket", PM_ID, fake, tmp_path)
    assert r.status == "stored" and r.points == 0
    a = col.availability(tmp_path, "polymarket", PM_ID, CLOSE - timedelta(days=7))
    assert a["status"] == "NOT AVAILABLE" and "no price points" in a["reason"]


def test_availability_last_quote_at_or_before_as_of_within_24h(tmp_path):
    _collect("kalshi", K_TICKER, FakeVenues(), tmp_path)
    as_of = CLOSE - timedelta(days=7)  # 2026-07-22T17:59Z; last candle ends 2026-07-22T00:00Z
    a = col.availability(tmp_path, "kalshi", K_TICKER, as_of)
    assert a == {"status": "AVAILABLE", "quote_ts": "2026-07-22T00:00:00+00:00", "quote_kind": "midpoint", "points": 73}
    assert "p_yes" not in a and "price" not in json.dumps(a)
    stale = col.availability(tmp_path, "kalshi", K_TICKER, datetime(2026, 7, 24, tzinfo=UTC))
    assert stale["status"] == "NOT AVAILABLE"
    early = col.availability(tmp_path, "kalshi", K_TICKER, datetime(2026, 7, 10, tzinfo=UTC))
    assert early["status"] == "NOT AVAILABLE"
    assert col.availability(tmp_path, "kalshi", "NEVER-COLLECTED", as_of)["reason"] == "no snapshot collected"


@pytest.mark.parametrize("kw", [{"min_lead_days": 6}, {"t_minus_days": 3}, {"min_lead_days": 0}])
def test_lead_floor_cannot_be_lowered(tmp_path, kw):
    fake = FakeVenues()
    with pytest.raises(MarketDataError, match="7-day floor"):
        _collect("kalshi", K_TICKER, fake, tmp_path, **kw)
    assert fake.requests == [] and _files(tmp_path) == []


def test_venue_close_override_is_recorded_in_notes(tmp_path):
    fake = FakeVenues(pm_close=CLOSE - timedelta(days=30))
    _collect("polymarket", PM_ID, fake, tmp_path, reference_close=CLOSE, check_venue_close=False)
    (entry,) = load_manifest(tmp_path, "polymarket", PM_ID)
    assert entry["notes"]["venue_close_check"].startswith("DISABLED")
    assert entry["notes"]["min_lead_days"] == 7


def test_retry_on_429_and_refuse_non_get():
    calls, sleeps = [], []

    def handler(req):
        calls.append(req)
        return httpx.Response(429 if len(calls) < 3 else 200, json={})

    t = col.RetryOn429(httpx.MockTransport(handler), retries=5, sleep=sleeps.append)
    with httpx.Client(transport=t) as c:
        assert c.get("https://example.invalid/x").status_code == 200
        assert len(calls) == 3 and len(sleeps) == 2
        with pytest.raises(MarketDataError, match="refuses POST"):
            c.post("https://example.invalid/x")


def test_cli_market_and_plan_with_mock_transport(tmp_path, capsys):
    fake = FakeVenues()
    rc = col.main(["--raw-root", str(tmp_path), "market", "--venue", "kalshi", "--market-id", K_TICKER],
                  transport=httpx.MockTransport(fake))
    assert rc == 0
    assert json.loads(capsys.readouterr().out)["status"] == "stored"
    plan = {
        "window_rule": {"t_minus_days": 7, "lookback_days": 3, "granularity_minutes": 60, "min_lead_days": 7},
        "groups": [{"group": "SYN", "pairs": [{
            "leg": "syn", "reference_close": _iso(CLOSE),
            "kalshi": {"market_id": K_TICKER}, "polymarket": {"market_id": PM_ID},
        }]}],
    }
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan))
    rc = col.main(["--raw-root", str(tmp_path), "plan", "--plan", str(plan_path)], transport=httpx.MockTransport(fake))
    out = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert rc == 0 and [o["status"] for o in out] == ["skipped_existing", "stored"]
    rows = col.report_rows(col.load_plan(plan_path), tmp_path)
    assert [rows[0][v]["status"] for v in ("kalshi", "polymarket")] == ["AVAILABLE", "AVAILABLE"]


def test_plan_with_outcome_keys_is_rejected(tmp_path):
    p = tmp_path / "plan.json"
    p.write_text(json.dumps({"window_rule": {}, "groups": [{"group": "x", "result": "yes"}]}))
    with pytest.raises(MarketDataError, match="outcome keys"):
        col.load_plan(p)


# --- REAL HISTORICAL snapshots collected for #51 (offline checks of saved bytes) --------------------------


PLAN = col.load_plan(col.DEFAULT_PLAN) if col.DEFAULT_PLAN.exists() else None


def _all_pairs(plan):
    """Paired candidates plus pairs moved to diverging_pairs (snapshots kept, not paired)."""
    for g in plan["groups"]:
        for p in g.get("pairs", []) + g.get("diverging_pairs", []):
            yield g, p


PLAN_PAIR_VENUES = [(g["group"], p, v) for g, p in _all_pairs(PLAN) for v in ("kalshi", "polymarket")] if PLAN else []
PLAN_MARKETS = sorted({(v, p[v]["market_id"]) for _, p, v in PLAN_PAIR_VENUES})


def test_plan_file_is_metadata_only_and_windows_are_consistent():
    assert PLAN is not None and "no prices" in PLAN["_provenance"]
    rule = PLAN["window_rule"]
    assert (rule["t_minus_days"], rule["min_lead_days"]) == (7, 7)
    for _, p in col.iter_plan_pairs(PLAN):
        k, m = (parse_iso_utc(p[v]["scheduled_close"]) for v in ("kalshi", "polymarket"))
        ref = parse_iso_utc(p["reference_close"])
        if abs(k - m) <= timedelta(days=3):
            assert ref == min(k, m) and "close_mismatch_days" not in p
        else:
            assert ref == k and p["close_mismatch_days"] > 3
    text = col.DEFAULT_PLAN.read_text("utf-8").lower()
    for word in ("outcomeprices", "settlement_value", '"result"', "last_price", "lasttradeprice"):
        assert word not in text


@pytest.mark.parametrize("venue,mid", PLAN_MARKETS)
def test_collected_snapshot_verifies_and_ends_before_t_minus(venue, mid):
    if not (RAW / venue / mid / "manifest.json").exists():
        pytest.skip(f"{venue} {mid}: no snapshot collected (listed as NOT AVAILABLE in docs/CANDIDATE_MARKETS.md)")
    assert verify_manifest(RAW, venue, mid) == []
    for e in load_manifest(RAW, venue, mid):
        assert e["provenance"] == "REAL HISTORICAL"
        assert find_outcome_keys((RAW / e["path"]).read_bytes()) == set()
        notes = e.get("notes")
        if notes is None:  # PR #12 snapshot (July 2026 pair), collected before this script existed
            continue
        end = parse_iso_utc(notes["window_end"])
        assert end <= parse_iso_utc(notes["reference_close"]) - timedelta(days=7)
        assert all(q.ts <= end for q in col.entry_quotes(RAW, venue, mid, e))


@pytest.mark.parametrize(
    "group,pair,venue", PLAN_PAIR_VENUES, ids=[f"{v}-{p[v]['market_id']}-{g}" for g, p, v in PLAN_PAIR_VENUES]
)
def test_stored_window_matches_plan_and_venue_close(group, pair, venue):
    """Cross-check manifest notes against the plan, not only against themselves."""
    mid = pair[venue]["market_id"]
    if not (RAW / venue / mid / "manifest.json").exists():
        pytest.skip(f"{venue} {mid}: no snapshot collected")
    ref = parse_iso_utc(pair["reference_close"])
    expected = col.t_minus_window(ref, PLAN["window_rule"]["t_minus_days"], PLAN["window_rule"]["lookback_days"])
    venue_close = parse_iso_utc(pair[venue]["scheduled_close"])
    pair_closes = {parse_iso_utc(pair[v]["scheduled_close"]) for v in ("kalshi", "polymarket")}
    entries = load_manifest(RAW, venue, mid)
    noted = [e["notes"] for e in entries if e.get("notes")]
    if not noted:  # only the PR #12 July 2026 snapshot: its 14-day window must cover the plan window
        endpoint = entries[0]["endpoint"]
        static = {k: v for k, v in entries[0]["params"].items() if k not in col.PRICE_ENDPOINTS[endpoint]}
        assert col.covered(entries, endpoint, static, expected)
        return
    for n in noted:
        # Same window as the plan's reference close gives (windows floor to the UTC day).
        assert (parse_iso_utc(n["window_start"]), parse_iso_utc(n["window_end"])) == (expected.start, expected.end)
        # The reference recorded at collection time is one of this pair's scheduled closes.
        assert parse_iso_utc(n["reference_close"]) in pair_closes
        # The venue close the collector saw equals the plan's close for that venue ...
        assert parse_iso_utc(n["venue_scheduled_close"]) == venue_close
        # ... and the window ends at least 7 days before it and before the plan reference.
        end = parse_iso_utc(n["window_end"])
        assert end <= venue_close - timedelta(days=7)
        assert end <= ref - timedelta(days=7)


def test_diverging_pairs_are_not_paired():
    paired = {p["polymarket"]["market_id"] for _, p in col.iter_plan_pairs(PLAN)}
    diverging = [p for g in PLAN["groups"] for p in g.get("diverging_pairs", [])]
    assert {p["polymarket"]["market_id"] for p in diverging} == {"594157", "655625", "654401"}
    for p in diverging:
        assert p["polymarket"]["market_id"] not in paired
        assert p["non_release_clause"] == {"kalshi": True, "polymarket": False}
        assert "NOT the same question" in p["excluded_reason"]


def test_report_runs_offline_for_every_pair():
    rows = col.report_rows(PLAN)
    assert len(rows) == sum(1 for _ in col.iter_plan_pairs(PLAN))
    for row in rows:
        for v in ("kalshi", "polymarket"):
            assert row[v]["status"] in ("AVAILABLE", "NOT AVAILABLE")
            if row[v]["status"] == "AVAILABLE":
                assert parse_iso_utc(row[v]["quote_ts"]) <= parse_iso_utc(row["as_of"])
