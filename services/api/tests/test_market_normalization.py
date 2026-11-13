"""Market normalization, as-of selection and adapter parsing (SPEC §4, MATH_MODEL §7).

No test touches the network: sockets are blocked by an autouse fixture, and adapter tests
use ``httpx.MockTransport`` serving saved bytes.

Fixture provenance:
* ``data/raw/<venue>/<market_id>/*.json`` + ``manifest.json``: REAL HISTORICAL responses,
  collected 2026-11-13 UTC from public read-only endpoints (see markets/README.md).
* ``markets/testdata/synthetic_*.json``: SYNTHETIC, hand-written from documented schemas.
"""

from __future__ import annotations

import json
import socket
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from markets.base import (
    MARKET_LABEL,
    AlreadyNormalizedError,
    EventMarketProvider,
    HistoryNotAvailable,
    MarketDataError,
    MarketMeta,
    NormalizedQuote,
    OutOfRangePrice,
    RawQuote,
)
from markets.kalshi import (
    KalshiProvider,
    parse_candlesticks,
    parse_cutoff,
    parse_market,
    tier_for,
)
from markets.normalize import (
    normalize_price,
    normalize_quote,
    normalize_quotes,
    parse_epoch,
    parse_iso_utc,
    select_quote,
)
from markets.polymarket import (
    PolymarketProvider,
    parse_gamma_market,
    parse_prices_history,
)
from markets.raw_store import (
    RawResponse,
    find_outcome_keys,
    load_manifest,
    store_raw,
    verify_manifest,
)

API_DIR = Path(__file__).resolve().parents[1]
RAW = API_DIR / "data" / "raw"
SYN = API_DIR / "markets" / "testdata"


K_TICKER = "KXFEDDECISION-26JUL-H0"
PM_ID = "1654958"
PM_YES_TOKEN = "111604417349377875799825956621596386269673370070912696668140891647145772186047"
T0 = datetime(2026, 1, 1, tzinfo=UTC)
NOW = datetime(2026, 11, 13, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def deny(*a, **k):
        raise RuntimeError("network access is forbidden in tests")

    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket.socket, "connect_ex", deny)
    monkeypatch.setattr(socket, "create_connection", deny)
    monkeypatch.setattr(socket, "getaddrinfo", deny)


def test_network_is_blocked():
    with pytest.raises(RuntimeError, match="forbidden"):
        socket.getaddrinfo("example.com", 443)
    with pytest.raises(RuntimeError, match="forbidden"):
        socket.create_connection(("example.com", 443))


def _real(venue: str, market_id: str, endpoint: str) -> tuple[bytes, dict]:
    entries = [e for e in load_manifest(RAW, venue, market_id) if e["endpoint"] == endpoint]
    assert len(entries) == 1, entries
    e = entries[0]
    return (RAW / e["path"]).read_bytes(), e


def _raw(**kw) -> RawQuote:
    base = {
        "venue": "kalshi",
        "market_id": "SYN",
        "url": "https://example.invalid/syn",
        "source_url": "https://example.invalid/syn",
        "ts": T0,
        "raw_scale": "dollars",
        "collected_at": NOW,
        "raw_sha256": "0" * 64,
    }
    base.update(kw)
    return RawQuote(**base)


def _nq(ts: datetime, price: str = "0.5", kind: str = "price_history_point", **kw) -> NormalizedQuote:
    fields = {
        "price_history_point": "point",
        "midpoint": None,
        "candle_close": "trade_close",
        "last_trade": "last_trade",
    }
    if kind == "midpoint":
        q = normalize_quote(_raw(ts=ts, yes_bid=price, yes_ask=price, **kw))
    else:
        q = normalize_quote(_raw(ts=ts, **{fields[kind]: price}, **kw))
    assert q is not None and q.quote_kind == kind
    return q


# --- normalize_price ------------------------------------------------------------------------


def test_kalshi_cents_63_to_0_63():
    assert normalize_price(63, "cents") == Decimal("0.63")
    assert normalize_price("63", "cents") == Decimal("0.63")
    assert float(normalize_price(63, "cents")) == 0.63


def test_kalshi_dollars_string_to_probability():
    assert normalize_price("0.6300", "dollars") == Decimal("0.63")


def test_polymarket_decimal_string_and_float():
    assert normalize_price("0.63", "decimal") == Decimal("0.63")
    assert normalize_price(0.63, "decimal") == Decimal("0.63")
    assert normalize_price(Decimal("0.9265"), "decimal") == Decimal("0.9265")


def test_bounds_inclusive():
    assert normalize_price("0", "decimal") == 0
    assert normalize_price("1", "decimal") == 1
    assert normalize_price(100, "cents") == 1
    assert normalize_price(0, "cents") == 0


@pytest.mark.parametrize("raw", [None, "", "   "])
def test_missing_price_is_none(raw):
    assert normalize_price(raw, "decimal") is None
    assert normalize_price(raw, "cents") is None


@pytest.mark.parametrize(
    "raw,scale",
    [("1.2", "decimal"), ("-0.01", "decimal"), ("1.0001", "dollars"), (101, "cents"), (-1, "cents"),
     ("NaN", "decimal"), ("Infinity", "decimal"), (float("inf"), "dollars")],
)
def test_out_of_range_rejected(raw, scale):
    with pytest.raises(OutOfRangePrice):
        normalize_price(raw, scale)


def test_non_price_types_rejected():
    with pytest.raises(TypeError):
        normalize_price(True, "decimal")
    with pytest.raises(TypeError):
        normalize_price([0.5], "decimal")
    with pytest.raises(MarketDataError):
        normalize_price("sixty", "decimal")


# --- exactly-once guard ------------------------------------------------------------------------


def test_probability_declared_as_cents_is_double_normalization():
    # 0.63 already is a probability; dividing again would give 0.0063.
    with pytest.raises(AlreadyNormalizedError):
        normalize_price("0.63", "cents")


def test_normalize_quote_rejects_already_normalized():
    q = normalize_quote(_raw(point="0.63", raw_scale="decimal", venue="polymarket"))
    assert q is not None and q.p_yes == 0.63
    with pytest.raises(AlreadyNormalizedError):
        normalize_quote(q)  # type: ignore[arg-type]
    with pytest.raises(AlreadyNormalizedError):
        normalize_price(q, "decimal")


@pytest.mark.parametrize("bad_p", [0.0063, 63.0, 0.64])
def test_normalized_quote_must_match_its_raw_value(bad_p):
    good = normalize_quote(_raw(last_trade="63", raw_scale="cents"))
    assert good is not None and good.p_yes == 0.63 and good.raw_price == "63"
    with pytest.raises(ValueError):
        NormalizedQuote(**{**good.model_dump(), "p_yes": bad_p})


def test_normalization_once_is_stable():
    raws = [_raw(ts=T0 + timedelta(hours=i), trade_close=f"0.{60 + i}00") for i in range(3)]
    first = normalize_quotes(raws)
    second = normalize_quotes(raws)
    assert [q.p_yes for q in first] == [q.p_yes for q in second] == [0.6, 0.61, 0.62]


# --- normalize_quote preference -----------------------------------------------------------------


def test_preference_midpoint_then_close_then_last_trade():
    q = normalize_quote(_raw(yes_bid="0.6200", yes_ask="0.6400", trade_close="0.7000", last_trade="0.1"))
    assert q.quote_kind == "midpoint" and q.p_yes == 0.63 and q.raw_price == "0.63"
    assert q.spread == pytest.approx(0.02)
    q = normalize_quote(_raw(yes_bid="0.0000", yes_ask="1.0000", trade_close="0.7000"))
    assert q.quote_kind == "candle_close" and q.p_yes == 0.7 and q.spread is None
    q = normalize_quote(_raw(yes_bid="0.7000", yes_ask="0.6000", last_trade="0.6500"))  # crossed book
    assert q.quote_kind == "last_trade" and q.p_yes == 0.65


def test_cents_midpoint_half_cent():
    q = normalize_quote(_raw(raw_scale="cents", yes_bid="62", yes_ask="63"))
    assert q.quote_kind == "midpoint" and q.raw_price == "62.5" and q.p_yes == 0.625


def test_no_price_at_all_is_none():
    assert normalize_quote(_raw()) is None
    assert normalize_quote(_raw(yes_bid="0.0000", yes_ask="1.0000")) is None


def test_out_of_range_inside_quote_rejected():
    with pytest.raises(OutOfRangePrice):
        normalize_quote(_raw(trade_close="1.5"))


def test_label_is_price_derived():
    q = _nq(T0)
    assert q.label == MARKET_LABEL and "price-derived" in q.label and "not a true probability" in q.label


def test_label_cannot_be_overridden():
    q = _nq(T0)
    with pytest.raises(ValueError):
        NormalizedQuote(**{**q.model_dump(), "label": "true probability"})
    with pytest.raises(ValueError):
        NormalizedQuote.model_validate({**q.model_dump(), "label": "ground truth"})


def test_naive_timestamps_rejected():
    with pytest.raises(ValueError):
        _raw(ts=datetime(2026, 1, 1))


# --- select_quote --------------------------------------------------------------------------


def test_select_last_quote_at_or_before_cutoff():
    qs = [_nq(T0 + timedelta(hours=h), f"0.{h + 10}") for h in (0, 1, 2, 5)]
    got = select_quote(qs, T0 + timedelta(hours=3))
    assert got.ts == T0 + timedelta(hours=2) and got.raw_price == "0.12"


def test_select_includes_quote_exactly_at_as_of_and_never_after():
    qs = [_nq(T0, "0.40"), _nq(T0 + timedelta(seconds=1), "0.99")]
    got = select_quote(qs, T0)
    assert got.raw_price == "0.40"


def test_select_only_future_quotes_is_none():
    assert select_quote([_nq(T0 + timedelta(minutes=1))], T0) is None


def test_stale_quote_is_none():
    qs = [_nq(T0)]
    assert select_quote(qs, T0 + timedelta(hours=24, seconds=1)) is None
    assert select_quote(qs, T0 + timedelta(hours=24)) is not None  # boundary inclusive
    assert select_quote(qs, T0 + timedelta(hours=2), max_staleness=timedelta(hours=1)) is None


def test_select_accepts_one_shot_generator():
    qs = [_nq(T0 + timedelta(hours=h), f"0.{h + 10}") for h in (0, 1, 2, 5)]
    got = select_quote((q for q in qs), T0 + timedelta(hours=3))
    assert got is not None and got.ts == T0 + timedelta(hours=2) and got.raw_price == "0.12"
    assert select_quote(iter(qs), T0 + timedelta(hours=5)).raw_price == "0.15"


def test_select_empty_is_none_and_naive_as_of_rejected():
    assert select_quote([], T0) is None
    with pytest.raises(ValueError):
        select_quote([_nq(T0)], datetime(2026, 1, 1))


def test_select_order_independent_and_kind_tiebreak():
    a, b = _nq(T0, "0.40", kind="candle_close"), _nq(T0, "0.41", kind="midpoint")
    assert select_quote([a, b], T0).quote_kind == "midpoint"
    assert select_quote([b, a], T0).quote_kind == "midpoint"


def test_select_conflicting_duplicates_raise():
    with pytest.raises(MarketDataError):
        select_quote([_nq(T0, "0.40"), _nq(T0, "0.41")], T0)


def test_select_rejects_mixed_markets():
    with pytest.raises(ValueError):
        select_quote([_nq(T0), _nq(T0, market_id="OTHER")], T0)


def test_select_converts_as_of_timezone():
    q = _nq(T0)
    est = timezone(timedelta(hours=-5))
    assert select_quote([q], datetime(2025, 12, 31, 19, 0, tzinfo=est)) == q


# --- timestamps -----------------------------------------------------------------------------


def test_seconds_and_milliseconds_parse_to_same_instant():
    s = parse_epoch(1783468807, "s")
    ms = parse_epoch(1783468807000, "ms")
    assert s == ms == datetime(2026, 7, 8, 0, 0, 7, tzinfo=UTC)
    assert parse_epoch(1783468807123, "ms").microsecond == 123000


def test_unit_mixups_fail_loudly():
    with pytest.raises(MarketDataError):
        parse_epoch(1783468807000, "s")  # ms passed as seconds
    with pytest.raises(MarketDataError):
        parse_epoch(1783468807, "ms")  # seconds passed as ms


def test_iso_parsing_variants():
    assert parse_iso_utc("2026-07-29T17:59:00Z") == datetime(2026, 7, 29, 17, 59, tzinfo=UTC)
    assert parse_iso_utc("2026-07-29 20:06:41+00") == datetime(2026, 7, 29, 20, 6, 41, tzinfo=UTC)
    assert parse_iso_utc(None) is None
    with pytest.raises(MarketDataError):
        parse_iso_utc("2026-07-29T17:59:00")


# --- REAL HISTORICAL fixtures (saved bytes, manifest-verified) ------------------------------------


@pytest.mark.parametrize("venue,mid", [("kalshi", K_TICKER), ("polymarket", PM_ID), ("kalshi", "_historical_cutoff")])
def test_real_fixture_manifests_verify(venue, mid):
    assert verify_manifest(RAW, venue, mid) == []
    for e in load_manifest(RAW, venue, mid):
        assert e["provenance"] == "REAL HISTORICAL"
        assert {"path", "sha256", "url", "params", "collected_at"} <= e.keys()
        assert find_outcome_keys((RAW / e["path"]).read_bytes()) == set()


def test_real_kalshi_cutoff_parses():
    body, _ = _real("kalshi", "_historical_cutoff", "kalshi.historical_cutoff")
    cut = parse_cutoff(body)
    assert cut["market_settled_ts"] == datetime(2026, 9, 13, tzinfo=UTC)
    # The July 2026 market closed before the cutoff, so the historical tier was correct.
    assert datetime(2026, 7, 29, 17, 59, tzinfo=UTC) < cut["market_settled_ts"]


def test_real_kalshi_historical_candles():
    body, e = _real("kalshi", K_TICKER, "kalshi.historical_candlesticks")
    quotes = parse_candlesticks(
        body, ticker=K_TICKER, tier="historical", source_url=e["url"],
        collected_at=parse_iso_utc(e["collected_at"]), period_interval=60,
    )
    assert len(quotes) == 335
    assert all(q.raw_sha256 == e["sha256"] for q in quotes)
    assert all(q.raw_scale == "dollars" and q.period_seconds == 3600 for q in quotes)
    first = normalize_quote(quotes[0])
    assert first.ts == datetime(2026, 7, 8, tzinfo=UTC)
    assert (first.raw_bid, first.raw_ask, first.raw_price) == ("0.8200", "0.8300", "0.825")
    assert first.p_yes == 0.825 and first.quote_kind == "midpoint" and first.spread == pytest.approx(0.01)
    # Real candles where nobody traded still carry a two-sided book.
    assert sum(q.trade_close is None for q in quotes) == 6
    norm = normalize_quotes(quotes)
    assert len(norm) == 335 and all(0 <= q.p_yes <= 1 for q in norm)
    # Every candle ends no later than the requested end_ts (7 days before the market's close).
    assert max(q.ts for q in norm) <= datetime(2026, 7, 22, tzinfo=UTC)
    picked = select_quote(norm, datetime(2026, 7, 15, 12, 30, tzinfo=UTC))
    assert picked.ts == datetime(2026, 7, 15, 12, 0, tzinfo=UTC)


def test_real_polymarket_prices_history():
    body, e = _real("polymarket", PM_ID, "polymarket.clob_prices_history")
    assert e["params"]["market"] == PM_YES_TOKEN and e["params"]["fidelity"] == 60
    quotes = parse_prices_history(
        body, market_id=PM_ID, token_id=PM_YES_TOKEN, source_url=e["url"],
        collected_at=parse_iso_utc(e["collected_at"]), fidelity_minutes=60,
    )
    assert len(quotes) == 335
    first = normalize_quote(quotes[0])
    # t is unix seconds: 1783468807 -> 2026-07-08T00:00:07Z (inside the requested window).
    assert first.ts == datetime(2026, 7, 8, 0, 0, 7, tzinfo=UTC)
    assert first.raw_price == "0.815" and first.p_yes == 0.815
    assert first.quote_kind == "price_history_point" and first.raw_scale == "decimal"
    start, end = e["params"]["startTs"], e["params"]["endTs"]
    assert all(start <= q.ts.timestamp() <= end for q in quotes)


# --- metadata parsing drops outcome fields (SYNTHETIC payloads) ----------------------------------


def _keys(obj) -> set[str]:
    if isinstance(obj, dict):
        return set(obj) | {k for v in obj.values() for k in _keys(v)}
    if isinstance(obj, (list, tuple)):
        return {k for v in obj for k in _keys(v)}
    return set()


OUTCOME_WORDS = (
    "result", "settle", "resolution", "resolved", "outcomeprices", "winner", "final_price", "expiration_value",
)


def test_kalshi_market_meta_has_no_outcome_fields():
    body = (SYN / "synthetic_kalshi_market.json").read_bytes()
    meta = parse_market(body, tier="historical", source_url="https://example.invalid/m",
                        event_body=(SYN / "synthetic_kalshi_event.json").read_bytes())
    assert meta.is_binary and meta.series_ticker == "SYNTHETICSERIES" and meta.mutually_exclusive_group is True
    dumped = meta.model_dump(mode="json")
    assert not any(w in k.lower() for k in _keys(dumped) for w in OUTCOME_WORDS)
    assert "1.0000" not in json.dumps(dumped)  # settlement_value_dollars did not leak
    assert find_outcome_keys(body) >= {"result", "settlement_value_dollars"}


def test_gamma_market_meta_and_yes_token():
    meta = parse_gamma_market((SYN / "synthetic_gamma_market.json").read_bytes(), source_url="https://example.invalid/g")
    assert meta.is_binary and meta.yes_token_id == "111" and meta.sides == ("Yes", "No")
    assert meta.reference_source == "https://example.invalid/synthetic-source"
    dumped = meta.model_dump(mode="json")
    assert not any(w in k.lower() for k in _keys(dumped) for w in OUTCOME_WORDS + ("closedtime", "uma"))
    assert "resolutionSource" not in dumped


def test_meta_model_cannot_carry_outcome():
    with pytest.raises(ValueError):
        MarketMeta(venue="kalshi", market_id="X", url="u", title="t", is_binary=True, source_url="u", result="yes")


def test_gamma_non_binary_flagged():
    meta = parse_gamma_market((SYN / "synthetic_gamma_market_multi.json").read_bytes(), source_url="u")
    assert meta.is_binary is False and meta.yes_token_id is None


def test_kalshi_live_schema_candles_synthetic():
    quotes = parse_candlesticks(
        (SYN / "synthetic_kalshi_live_candles.json").read_bytes(), ticker="SYNTHETIC-MKT-YES", tier="live",
        source_url="u", collected_at=NOW, period_interval=60,
    )
    kinds = [normalize_quote(q) and normalize_quote(q).quote_kind for q in quotes]
    assert kinds == ["midpoint", "candle_close", None]
    assert normalize_quote(quotes[0]).p_yes == 0.63
    assert quotes[0].volume == "5.00" and quotes[0].open_interest == "12.00"


def test_kalshi_schema_mismatch_fails_loudly():
    # Historical schema parsed as live (wrong field names) must not silently yield empty prices.
    body, _e = _real("kalshi", K_TICKER, "kalshi.historical_candlesticks")
    with pytest.raises(MarketDataError):
        parse_candlesticks(body, ticker=K_TICKER, tier="live", source_url="u", collected_at=NOW, period_interval=60)
    with pytest.raises(MarketDataError):
        parse_candlesticks(
            body, ticker="WRONG", tier="historical", source_url="u", collected_at=NOW, period_interval=60
        )
    bad = json.dumps({"ticker": "X", "candlesticks": [{"end_period_ts": 1767225600, "yes_bid": {"close": 62},
                      "yes_ask": {"close": 64}, "price": {}, "volume": "0", "open_interest": "0"}]}).encode()
    with pytest.raises(MarketDataError):  # integer (legacy cents?) where a dollar string is documented
        parse_candlesticks(bad, ticker="X", tier="historical", source_url="u", collected_at=NOW, period_interval=60)


# --- providers over mocked HTTP (saved bytes only) -----------------------------------------------


def _transport(routes: dict[str, tuple[int, bytes]], seen: list[httpx.Request]):
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        assert request.method == "GET"
        assert "authorization" not in {k.lower() for k in request.headers}
        status, body = routes.get(request.url.path, (404, b'{"code":"not_found"}'))
        return httpx.Response(status, content=body)

    return httpx.MockTransport(handler)


def _syn_kalshi_market(settlement_ts: str | None) -> bytes:
    mkt = json.loads((SYN / "synthetic_kalshi_market.json").read_bytes())
    mkt["market"]["ticker"] = K_TICKER
    mkt["market"]["event_ticker"] = "SYNTHETIC-EVT"
    mkt["market"]["settlement_ts"] = settlement_ts
    return json.dumps(mkt).encode()


def _kalshi_routes(**extra) -> dict[str, tuple[int, bytes]]:
    cut, _ = _real("kalshi", "_historical_cutoff", "kalshi.historical_cutoff")  # market_settled_ts 2026-09-13
    routes = {
        "/trade-api/v2/historical/cutoff": (200, cut),
        "/trade-api/v2/events/SYNTHETIC-EVT": (200, (SYN / "synthetic_kalshi_event.json").read_bytes()),
    }
    routes.update(extra)
    return routes


def test_kalshi_provider_routes_by_cutoff_to_historical():
    cbody, ce = _real("kalshi", K_TICKER, "kalshi.historical_candlesticks")
    seen: list[httpx.Request] = []
    routes = _kalshi_routes(**{
        f"/trade-api/v2/historical/markets/{K_TICKER}": (200, _syn_kalshi_market("2026-07-29T18:00:00Z")),
        f"/trade-api/v2/historical/markets/{K_TICKER}/candlesticks": (200, cbody),
    })
    p = KalshiProvider(client=httpx.Client(transport=_transport(routes, seen)))
    assert isinstance(p, EventMarketProvider)
    quotes = p.get_history(K_TICKER, datetime(2026, 7, 8, tzinfo=UTC), datetime(2026, 7, 22, tzinfo=UTC))
    assert len(quotes) == 335 and quotes[0].raw_sha256 == ce["sha256"]
    paths = [r.url.path for r in seen]
    assert paths[0] == "/trade-api/v2/historical/cutoff"  # the cutoff is consulted first
    cand = [r for r in seen if r.url.path.endswith("/candlesticks")]
    assert len(cand) == 1 and cand[0].url.path.startswith("/trade-api/v2/historical/")
    assert dict(cand[0].url.params) == {k: str(v) for k, v in ce["params"].items()}
    meta = p.get_market(K_TICKER)
    assert meta.data_tier == "historical" and meta.kalshi_tier_cutoff == datetime(2026, 9, 13, tzinfo=UTC)


def test_kalshi_live_response_settled_before_cutoff_goes_historical():
    # Even if the live endpoint still answers, the cutoff rule decides the tier.
    seen: list[httpx.Request] = []
    body = _syn_kalshi_market("2026-07-29T18:00:00Z")
    routes = _kalshi_routes(**{
        f"/trade-api/v2/markets/{K_TICKER}": (200, body),
        f"/trade-api/v2/historical/markets/{K_TICKER}": (200, body),
    })
    meta = KalshiProvider(client=httpx.Client(transport=_transport(routes, seen))).get_market(K_TICKER)
    assert meta.data_tier == "historical"
    assert f"/trade-api/v2/historical/markets/{K_TICKER}" in [r.url.path for r in seen]


@pytest.mark.parametrize("settlement_ts", [None, "2026-10-01T00:00:00Z"])
def test_kalshi_unsettled_or_after_cutoff_is_live(settlement_ts):
    routes = _kalshi_routes(**{f"/trade-api/v2/markets/{K_TICKER}": (200, _syn_kalshi_market(settlement_ts))})
    meta = KalshiProvider(client=httpx.Client(transport=_transport(routes, []))).get_market(K_TICKER)
    assert meta.data_tier == "live" and meta.series_ticker == "SYNTHETICSERIES"


def test_kalshi_inconsistent_tiers_raise():
    # Live 404, historical serves it, but its settlement time is after the cutoff: refuse to guess.
    routes = _kalshi_routes(**{
        f"/trade-api/v2/historical/markets/{K_TICKER}": (200, _syn_kalshi_market("2026-10-01T00:00:00Z")),
    })
    with pytest.raises(MarketDataError, match="inconsistent"):
        KalshiProvider(client=httpx.Client(transport=_transport(routes, []))).get_market(K_TICKER)


def test_tier_for_boundary():
    cut = datetime(2026, 9, 13, tzinfo=UTC)
    assert tier_for(_syn_kalshi_market("2026-09-12T23:59:59Z"), cut) == "historical"
    assert tier_for(_syn_kalshi_market("2026-09-13T00:00:00Z"), cut) == "live"  # "before" is strict
    assert tier_for(_syn_kalshi_market(None), cut) == "live"


def test_kalshi_provider_chunks_to_5000_periods():
    seen: list[httpx.Request] = []
    p = KalshiProvider(client=httpx.Client(transport=_transport({}, seen)))
    meta = MarketMeta(venue="kalshi", market_id="SYN", url="u", title="t", is_binary=True, source_url="u",
                      data_tier="live", series_ticker="S")
    with pytest.raises(MarketDataError):  # mocked 404, but the request shape is what we check
        p.fetch_history_raw(meta, T0, T0 + timedelta(minutes=5001), period_interval=1)
    assert seen[0].url.path == "/trade-api/v2/series/S/markets/SYN/candlesticks"
    q = dict(seen[0].url.params)
    assert (int(q["end_ts"]) - int(q["start_ts"])) // 60 == 5000 and q["period_interval"] == "1"


def test_kalshi_live_requires_series_ticker():
    p = KalshiProvider(client=httpx.Client(transport=_transport({}, [])))
    meta = MarketMeta(
        venue="kalshi", market_id="SYN", url="u", title="t", is_binary=True, source_url="u", data_tier="live"
    )
    with pytest.raises(MarketDataError):
        p.fetch_history_raw(meta, T0, T0 + timedelta(hours=1))


def test_polymarket_provider_resolves_yes_token_and_fetches_history():
    hbody, he = _real("polymarket", PM_ID, "polymarket.clob_prices_history")
    gm = json.loads((SYN / "synthetic_gamma_market.json").read_bytes())
    gm["id"] = PM_ID
    gm["clobTokenIds"] = json.dumps([PM_YES_TOKEN, "222"])
    seen: list[httpx.Request] = []
    routes = {f"/markets/{PM_ID}": (200, json.dumps(gm).encode()), "/prices-history": (200, hbody)}
    p = PolymarketProvider(client=httpx.Client(transport=_transport(routes, seen)))
    assert isinstance(p, EventMarketProvider)
    quotes = p.get_history(PM_ID, datetime(2026, 7, 8, tzinfo=UTC), datetime(2026, 7, 22, tzinfo=UTC))
    assert len(quotes) == 335 and quotes[0].raw_sha256 == he["sha256"]
    hist_req = [r for r in seen if r.url.path == "/prices-history"]
    assert len(hist_req) == 1  # 14-day window fits one chunk
    assert dict(hist_req[0].url.params) == {k: str(v) for k, v in he["params"].items()}
    assert seen[0].url.host == "gamma-api.polymarket.com" and hist_req[0].url.host == "clob.polymarket.com"


def test_polymarket_empty_history_is_not_available():
    gm = (SYN / "synthetic_gamma_market.json").read_bytes()
    routes = {"/markets/999000001": (200, gm), "/prices-history": (200, b'{"history":[]}')}
    p = PolymarketProvider(client=httpx.Client(transport=_transport(routes, [])))
    with pytest.raises(HistoryNotAvailable):
        p.get_history("999000001", T0, T0 + timedelta(days=1))


def test_polymarket_non_binary_refused():
    routes = {"/markets/999000002": (200, (SYN / "synthetic_gamma_market_multi.json").read_bytes())}
    p = PolymarketProvider(client=httpx.Client(transport=_transport(routes, [])))
    with pytest.raises(MarketDataError):
        p.get_history("999000002", T0, T0 + timedelta(days=1))


# --- raw store ------------------------------------------------------------------------------


def test_store_raw_writes_exact_bytes_and_manifest(tmp_path):
    body = b'{"history":[{"t":1767225600,"p":0.5}]}'
    resp = RawResponse(url="https://example.invalid/x", params={"a": 1}, status_code=200, body=body,
                       collected_at=NOW, endpoint="synthetic.test")
    path = store_raw(tmp_path, "polymarket", "SYN", resp)
    assert path.read_bytes() == body
    assert verify_manifest(tmp_path, "polymarket", "SYN") == []
    path.write_bytes(body + b" ")
    assert verify_manifest(tmp_path, "polymarket", "SYN") != []


def test_store_raw_refuses_outcome_bearing_bodies(tmp_path):
    body = (SYN / "synthetic_kalshi_market.json").read_bytes()
    resp = RawResponse(url="u", params={}, status_code=200, body=body, collected_at=NOW)
    with pytest.raises(MarketDataError, match="sealed_outcomes"):
        store_raw(tmp_path, "kalshi", "SYN", resp)
    with pytest.raises(MarketDataError):
        escape = RawResponse(url="u", params={}, status_code=200, body=b"{}", collected_at=NOW)
        store_raw(tmp_path, "kalshi", "../escape", escape)


@pytest.mark.parametrize("body", [b"<html>rate limited</html>", b"", b'{"result": "yes"'])
def test_store_raw_rejects_non_json_bodies(tmp_path, body):
    # An unparseable body cannot be checked for outcome keys, so it must not be stored as clean.
    resp = RawResponse(url="u", params={}, status_code=200, body=body, collected_at=NOW)
    with pytest.raises(MarketDataError, match="not valid JSON"):
        store_raw(tmp_path, "kalshi", "SYN", resp)
    assert not (tmp_path / "kalshi" / "SYN").exists()


def test_store_raw_is_immutable_and_manifest_has_no_temp_files(tmp_path):
    resp = RawResponse(url="u", params={}, status_code=200, body=b'{"history":[]}', collected_at=NOW)
    store_raw(tmp_path, "polymarket", "SYN", resp)
    with pytest.raises(MarketDataError, match="immutable"):
        store_raw(tmp_path, "polymarket", "SYN", resp)
    files = sorted(p.name for p in (tmp_path / "polymarket" / "SYN").iterdir())
    assert files == ["20261113T000000000000Z.json", "manifest.json"]
    assert len(load_manifest(tmp_path, "polymarket", "SYN")) == 1
