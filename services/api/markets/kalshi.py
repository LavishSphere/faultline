"""Read-only Kalshi adapter (public, unauthenticated GET endpoints only).

Verified against the official docs on 2026-11-12 (see markets/README.md for the full record):

* Base URL ``https://external-api.kalshi.com/trade-api/v2`` (docs list it as "Production Trade API";
  ``https://api.elections.kalshi.com/trade-api/v2`` is also listed). Every endpoint used here
  declares ``security: []``.
* ``GET /historical/cutoff`` -> ``market_settled_ts``, ``trades_created_ts``, ``orders_updated_ts``
  (+ optional ``market_positions_last_updated_ts``), all ISO-8601 date-time strings.
  Markets settled before ``market_settled_ts`` are only served by ``/historical/markets...``;
  live ``GET /markets/{ticker}`` stops returning them. ``KalshiProvider.get_market`` fetches the
  cutoff first and routes by ``tier_for`` (settlement_ts < market_settled_ts -> historical).
* ``GET /historical/markets/{ticker}`` and ``GET /markets/{ticker}`` -> ``{"market": Market}``.
* ``GET /historical/markets/{ticker}/candlesticks?start_ts&end_ts&period_interval`` (all required;
  unix seconds; period_interval in {1, 60, 1440} minutes; at most 5,000 periods per request).
  Candle fields: ``end_period_ts`` (int), ``yes_bid``/``yes_ask`` {open,low,high,close},
  ``price`` {open,low,high,close,mean,previous} (nullable when no trades), ``volume``,
  ``open_interest``. Prices are FixedPointDollars strings ("0.5600"), NOT integer cents.
* ``GET /series/{series_ticker}/markets/{ticker}/candlesticks`` (live tier) uses the same
  parameters but suffixed names: ``close_dollars`` etc., ``volume_fp``, ``open_interest_fp``.
  Millisecond timestamps are rejected with HTTP 400.
* ``GET /events/{event_ticker}`` -> ``event.series_ticker``, ``event.mutually_exclusive``.

SPEC §4 and the market-data skill describe Kalshi prices as cents; the current docs say dollar
strings. We follow the docs (``raw_scale="dollars"``). The ``cents`` scale is still supported in
``normalize.py`` for legacy integer-cent payloads.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal

import httpx

from .base import HistoryNotAvailable, MarketDataError, MarketMeta, RawQuote
from .normalize import parse_epoch, parse_iso_utc
from .raw_store import RawResponse, sha256_hex

DEFAULT_BASE_URL = "https://external-api.kalshi.com/trade-api/v2"
PERIOD_INTERVALS = (1, 60, 1440)  # minutes, per docs
MAX_PERIODS_PER_REQUEST = 5000  # per docs
USER_AGENT = "faultline-research-client/0.1 (read-only)"

Tier = Literal["live", "historical"]


def _str_or_none(v: Any, field: str) -> str | None:
    if v is None:
        return None
    if isinstance(v, str):
        return v
    # The documented schema is FixedPointDollars/FixedPointCount strings. An int here would
    # most likely be a legacy integer-cent field; refuse rather than guess its scale.
    raise MarketDataError(f"Kalshi field {field!r} expected a string, got {type(v).__name__}: {v!r}")


def parse_cutoff(body: bytes) -> dict[str, datetime]:
    data = json.loads(body)
    out: dict[str, datetime] = {}
    for k in ("market_settled_ts", "trades_created_ts", "orders_updated_ts"):
        if k not in data:
            raise MarketDataError(f"/historical/cutoff missing required field {k!r}")
        out[k] = parse_iso_utc(data[k])  # type: ignore[assignment]
    if data.get("market_positions_last_updated_ts"):
        out["market_positions_last_updated_ts"] = parse_iso_utc(data["market_positions_last_updated_ts"])  # type: ignore[assignment]
    return out


def tier_for(market_body: bytes, market_settled_cutoff: datetime) -> Tier:
    """Docs rule: a market that settled before ``market_settled_ts`` lives in the historical tier.

    Reads ``market.settlement_ts`` (null until settled) in memory only, for routing.
    """
    m = json.loads(market_body).get("market")
    if not isinstance(m, dict):
        raise MarketDataError("Kalshi market response missing 'market'")
    settled_at = parse_iso_utc(m.get("settlement_ts"))
    if settled_at is not None and settled_at < market_settled_cutoff:
        return "historical"
    return "live"


def parse_market(
    body: bytes,
    *,
    tier: Tier,
    source_url: str,
    event_body: bytes | None = None,
    tier_cutoff: datetime | None = None,
) -> MarketMeta:
    """Parse ``{"market": Market}`` into MarketMeta, dropping every outcome/settlement field."""
    data = json.loads(body)
    m = data.get("market")
    if not isinstance(m, dict) or "ticker" not in m:
        raise MarketDataError("Kalshi market response missing 'market.ticker'")
    series_ticker = None
    mutually_exclusive = None
    if event_body is not None:
        ev = json.loads(event_body).get("event") or {}
        if ev.get("event_ticker") not in (None, m.get("event_ticker")):
            raise MarketDataError("event response does not match market.event_ticker")
        series_ticker = ev.get("series_ticker")
        mutually_exclusive = ev.get("mutually_exclusive")
    rules = "\n\n".join(x for x in (m.get("rules_primary"), m.get("rules_secondary")) if x) or None
    return MarketMeta(
        venue="kalshi",
        market_id=m["ticker"],
        # Kalshi's public web URL scheme is not documented in the API reference; we record the
        # API resource URL instead of guessing a web URL.
        url=source_url,
        title=m.get("title") or m.get("yes_sub_title") or m["ticker"],
        yes_label=m.get("yes_sub_title"),
        rules=rules,
        reference_source=None,  # not on Market; series-level settlement_sources not fetched
        is_binary=m.get("market_type") == "binary",
        sides=("YES", "NO") if m.get("market_type") == "binary" else (),
        open_time=parse_iso_utc(m.get("open_time")),
        close_time=parse_iso_utc(m.get("close_time")),
        mutually_exclusive_group=mutually_exclusive,
        group_id=m.get("event_ticker"),
        series_ticker=series_ticker,
        data_tier=tier,
        kalshi_tier_cutoff=tier_cutoff,
        source_url=source_url,
    )


def parse_candlesticks(
    body: bytes,
    *,
    ticker: str,
    tier: Tier,
    source_url: str,
    collected_at: datetime,
    period_interval: int,
    market_url: str | None = None,
) -> list[RawQuote]:
    """Parse a candlesticks response (historical or live schema) into RawQuotes.

    Field names differ by tier (verified in docs): historical uses ``close``/``volume``,
    live uses ``close_dollars``/``volume_fp``. The tier is declared by the caller, never guessed.
    """
    if period_interval not in PERIOD_INTERVALS:
        raise MarketDataError(f"period_interval must be one of {PERIOD_INTERVALS}")
    digest = sha256_hex(body)
    data = json.loads(body, parse_float=Decimal)
    if data.get("ticker") != ticker:
        raise MarketDataError(f"candlesticks ticker {data.get('ticker')!r} != requested {ticker!r}")
    candles = data.get("candlesticks")
    if not isinstance(candles, list):
        raise MarketDataError("candlesticks response missing 'candlesticks' list")
    sfx = "" if tier == "historical" else "_dollars"
    vol_key, oi_key = ("volume", "open_interest") if tier == "historical" else ("volume_fp", "open_interest_fp")
    out: list[RawQuote] = []
    for i, c in enumerate(candles):
        try:
            ts = parse_epoch(c["end_period_ts"], "s")
            bid = _str_or_none(c["yes_bid"]["close" + sfx], "yes_bid.close" + sfx)
            ask = _str_or_none(c["yes_ask"]["close" + sfx], "yes_ask.close" + sfx)
            price = c.get("price") or {}
            close = _str_or_none(price.get("close" + sfx), "price.close" + sfx)
            vol = _str_or_none(c.get(vol_key), vol_key)
            oi = _str_or_none(c.get(oi_key), oi_key)
        except (KeyError, TypeError) as exc:
            raise MarketDataError(f"candle {i} does not match the {tier} schema: {exc!r}") from exc
        out.append(
            RawQuote(
                venue="kalshi",
                market_id=ticker,
                url=market_url or source_url,
                source_url=source_url,
                ts=ts,
                raw_scale="dollars",
                yes_bid=bid,
                yes_ask=ask,
                trade_close=close,
                volume=vol,
                open_interest=oi,
                period_seconds=period_interval * 60,
                collected_at=collected_at,
                raw_sha256=digest,
            )
        )
    return out


class KalshiProvider:
    """EventMarketProvider for Kalshi. Read-only; no credentials are accepted or sent."""

    venue: Literal["kalshi"] = "kalshi"

    def __init__(self, client: httpx.Client | None = None, base_url: str = DEFAULT_BASE_URL) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = client or httpx.Client(timeout=30.0, headers={"User-Agent": USER_AGENT})

    # -- HTTP ---------------------------------------------------------------------------------
    def _get(self, path: str, params: dict[str, Any] | None = None, endpoint: str = "") -> RawResponse:
        url = f"{self.base_url}{path}"
        r = self._client.get(url, params=params or None)
        return RawResponse(
            url=url,
            params=dict(params or {}),
            status_code=r.status_code,
            body=r.content,
            collected_at=datetime.now(UTC),
            endpoint=endpoint,
        )

    @staticmethod
    def _ok(resp: RawResponse) -> RawResponse:
        if resp.status_code != 200:
            raise MarketDataError(f"GET {resp.url} -> HTTP {resp.status_code}: {resp.body[:200]!r}")
        return resp

    # -- endpoints ----------------------------------------------------------------------------
    def fetch_cutoff(self) -> RawResponse:
        return self._ok(self._get("/historical/cutoff", endpoint="kalshi.historical_cutoff"))

    def get_cutoff(self) -> dict[str, datetime]:
        return parse_cutoff(self.fetch_cutoff().body)

    def fetch_market(self, ticker: str, market_settled_cutoff: datetime) -> tuple[RawResponse, Tier]:
        """Fetch a market and decide its tier from ``GET /historical/cutoff`` (per the docs).

        The tier is always ``tier_for(settlement_ts, market_settled_ts)``; HTTP status codes
        only tell us where the metadata could be read. The settlement timestamp is used in
        memory for routing and never copied into MarketMeta.

        NOTE: the body contains settlement fields (result, settlement_value_dollars, ...).
        Do not store it in data/raw (``store_raw`` refuses it).
        """
        live = self._get(f"/markets/{ticker}", endpoint="kalshi.market")
        if live.status_code not in (200, 404):
            self._ok(live)
        if live.status_code == 200:
            tier = tier_for(live.body, market_settled_cutoff)
            if tier == "live":
                return live, "live"
            # Settled before the cutoff: the docs say it is served by the historical tier.
        hist = self._ok(self._get(f"/historical/markets/{ticker}", endpoint="kalshi.historical_market"))
        if tier_for(hist.body, market_settled_cutoff) != "historical":
            raise MarketDataError(
                f"{ticker}: served by /historical/markets but its settlement time is not before "
                f"market_settled_ts={market_settled_cutoff.isoformat()}; tiers are inconsistent"
            )
        return hist, "historical"

    def fetch_event(self, event_ticker: str) -> RawResponse:
        return self._ok(self._get(f"/events/{event_ticker}", endpoint="kalshi.event"))

    def get_market(self, market_id: str) -> MarketMeta:
        cutoff = self.get_cutoff()["market_settled_ts"]
        resp, tier = self.fetch_market(market_id, cutoff)
        event_ticker = json.loads(resp.body)["market"].get("event_ticker")
        event_body = self.fetch_event(event_ticker).body if event_ticker else None
        return parse_market(
            resp.body, tier=tier, source_url=resp.url, event_body=event_body, tier_cutoff=cutoff
        )

    def fetch_history_raw(
        self,
        meta: MarketMeta,
        start: datetime,
        end: datetime,
        period_interval: int = 60,
    ) -> list[RawResponse]:
        """Fetch candlesticks for [start, end], split into <= 5,000-period requests."""
        if period_interval not in PERIOD_INTERVALS:
            raise MarketDataError(f"period_interval must be one of {PERIOD_INTERVALS}")
        if start.tzinfo is None or end.tzinfo is None or end <= start:
            raise MarketDataError("start/end must be aware datetimes with start < end")
        if meta.data_tier == "historical":
            path = f"/historical/markets/{meta.market_id}/candlesticks"
            endpoint = "kalshi.historical_candlesticks"
        elif meta.data_tier != "live":
            raise MarketDataError("MarketMeta.data_tier must be 'live' or 'historical'")
        else:
            if not meta.series_ticker:
                raise MarketDataError("live candlesticks need series_ticker (from GET /events)")
            path = f"/series/{meta.series_ticker}/markets/{meta.market_id}/candlesticks"
            endpoint = "kalshi.live_candlesticks"
        span = timedelta(minutes=period_interval * MAX_PERIODS_PER_REQUEST)
        out: list[RawResponse] = []
        lo = start
        while lo < end:
            hi = min(lo + span, end)
            params = {
                "start_ts": int(lo.timestamp()),
                "end_ts": int(hi.timestamp()),
                "period_interval": period_interval,
            }
            out.append(self._ok(self._get(path, params, endpoint=endpoint)))
            lo = hi
        return out

    def parse_history(self, meta: MarketMeta, responses: list[RawResponse], period_interval: int) -> list[RawQuote]:
        if meta.data_tier not in ("live", "historical"):
            raise MarketDataError("MarketMeta.data_tier must be set to pick the candle schema")
        quotes: dict[datetime, RawQuote] = {}
        for resp in responses:
            for q in parse_candlesticks(
                resp.body,
                ticker=meta.market_id,
                tier=meta.data_tier,
                source_url=resp.url,
                collected_at=resp.collected_at,
                period_interval=period_interval,
                market_url=meta.url,
            ):
                prev = quotes.get(q.ts)
                if prev is not None and (prev.yes_bid, prev.yes_ask, prev.trade_close) != (
                    q.yes_bid,
                    q.yes_ask,
                    q.trade_close,
                ):
                    raise MarketDataError(f"conflicting candles at {q.ts.isoformat()} across chunks")
                quotes.setdefault(q.ts, q)
        return [quotes[k] for k in sorted(quotes)]

    def get_history(
        self, market_id: str, start: datetime, end: datetime, period_interval: int = 60
    ) -> list[RawQuote]:
        meta = self.get_market(market_id)
        if not meta.is_binary:
            raise MarketDataError(f"{market_id} is not a binary market (MVP supports binary only)")
        quotes = self.parse_history(meta, self.fetch_history_raw(meta, start, end, period_interval), period_interval)
        if not quotes:
            raise HistoryNotAvailable(f"Kalshi returned no candlesticks for {market_id} in [{start}, {end}]")
        return quotes
