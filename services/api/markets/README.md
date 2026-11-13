# markets/: read-only Kalshi + Polymarket price adapters

SPEC §4, MATH_MODEL §7. Public, unauthenticated GET endpoints only. No credentials, wallets, orders or
trading code. Collection is an **offline** step; replay inference reads saved snapshots and never calls
these APIs.

| Module | Purpose |
|---|---|
| `base.py` | `EventMarketProvider` protocol, `MarketMeta` (no outcome fields), `RawQuote`, `NormalizedQuote`, errors, labels |
| `normalize.py` | `normalize_price` / `normalize_quote` (exactly once), `parse_epoch` (s vs ms), `select_quote` (as-of, 24h staleness) |
| `kalshi.py` | `KalshiProvider`, `parse_cutoff`, `parse_market`, `parse_candlesticks` (historical + live schemas) |
| `polymarket.py` | `PolymarketProvider`, `parse_gamma_market`, `parse_prices_history` |
| `raw_store.py` | exact-bytes storage + `manifest.json` (sha256), refuses outcome-bearing bodies |
| `testdata/synthetic_*.json` | SYNTHETIC hand-written payloads for parser branches (not API responses) |

Every quote carries the label **"market-implied probability (price-derived; affected by fees, spread,
liquidity), not a true probability"**. `select_quote(...) is None` means the baseline is **NOT AVAILABLE**.

## Verification record (official docs, checked 2026-11-12)

### Kalshi
- https://docs.kalshi.com/getting_started/historical_data: data is split into live and historical tiers.
  `GET /historical/cutoff` returns `market_settled_ts`, `trades_created_ts`, `orders_updated_ts`,
  `market_positions_last_updated_ts`. Markets and candlesticks settled before `market_settled_ts` are only
  in `/historical/markets...`. Live `GET /markets/{ticker}` stops returning them. Events and Series stay at
  their original endpoints.
- https://docs.kalshi.com/api-reference/historical/get-historical-cutoff-timestamps: all fields are ISO-8601
  `date-time` strings, `security: []`.
- **Routing (implemented as the docs describe):** `KalshiProvider.get_market` calls `GET /historical/cutoff`
  first. The tier is `historical` iff the market's `settlement_ts` < `market_settled_ts` (`tier_for`), else `live`.
  HTTP status codes only decide where the metadata can be read. If `/historical/markets` serves a market that the
  cutoff puts in the live tier, the adapter raises instead of guessing. The cutoff used is recorded in
  `MarketMeta.kalshi_tier_cutoff`. `settlement_ts` is read in memory for routing only and is never copied out.
- https://docs.kalshi.com/api-reference/historical/get-historical-market-candlesticks:
  `GET /historical/markets/{ticker}/candlesticks`. `start_ts`, `end_ts` (unix s, both inclusive of candle end) and
  `period_interval` ∈ {1, 60, 1440} are all required. Max 5,000 periods per request (400 otherwise).
  Candle: `end_period_ts`, `yes_bid`/`yes_ask` {open,low,high,close}, `price` {open,low,high,close,mean,previous}
  (nullable, null when no trades), `volume`, `open_interest`. **Prices are FixedPointDollars strings
  ("0.5600"), not integer cents.** `security: []`.
- https://docs.kalshi.com/api-reference/market/get-market-candlesticks: live
  `GET /series/{series_ticker}/markets/{ticker}/candlesticks` takes the same params, with field names
  `close_dollars` etc., `volume_fp`, `open_interest_fp`. Millisecond timestamps are rejected (400).
- https://docs.kalshi.com/api-reference/historical/get-historical-market and `/market/get-market`: `{market: Market}`
  with `market_type` (binary|scalar), `rules_primary/secondary`, and **settlement fields** (`result`,
  `settlement_value_dollars`, `settlement_ts`, `expiration_value`). These are dropped by `parse_market`.
- https://docs.kalshi.com/api-reference/events/get-event: `event.series_ticker`, `event.mutually_exclusive`.
- https://docs.kalshi.com/getting_started/fixed_point_migration: `*_dollars` strings (up to 6 dp in
  responses), `*_fp` counts. Unauthenticated rate limits are not published (rate_limits page): 429 on excess.
- Servers listed: `https://external-api.kalshi.com/trade-api/v2` (used), `https://api.elections.kalshi.com/trade-api/v2`.

**Docs vs SPEC:** SPEC §4, MATH_MODEL §7 and the market-data skill say Kalshi prices are cents (p = c/100).
The current docs say dollar strings, and our real responses confirm it. We follow the docs (`raw_scale="dollars"`,
p = x). The `cents` path stays implemented and tested for legacy integer-cent payloads.
MATH_MODEL §7 wording should be updated by its owner (follow-up).

### Polymarket (decentralized polymarket.com only, not polymarket.us)
- https://institute.polymarket.com/data (article dated July 24, 2026; WebFetch got 403, so it was read via
  a plain HTTP GET): Gamma for market metadata, `clobTokenIds` = per-outcome `token_id`, CLOB
  `GET /prices-history?market={token_id}&interval=..&fidelity=..` → `{"history":[{"t":1784493604,"p":0.505},...]}`
  (`t` in seconds). polymarket.com and polymarket.us use distinct APIs and data.
- https://docs.polymarket.com/api-spec/clob-openapi.yaml: `/prices-history`, `security: []`. `market` (required),
  `startTs`, `endTs` (unix timestamp, double), `interval` (max|all|1m|1w|1d|6h|1h), `fidelity` (minutes,
  default 1). Response `MarketPrice {t: uint32, p: float}`. Server `https://clob.polymarket.com`.
- https://docs.polymarket.com/api-spec/gamma-openapi.yaml: `GET /markets/{id}`, `GET /markets/slug/{slug}`,
  `GET /markets?clob_token_ids=..`. `outcomes`, `outcomePrices`, `clobTokenIds` are strings.
- https://docs.polymarket.com/market-data/market-details.md: those strings are JSON-encoded lists aligned
  by index, and for binary markets index 0 = YES. `version == "v2"` markets use `positionIds` instead of `clobTokenIds`.
- https://docs.polymarket.com/market-data/prices-order-books.md: documents a newer
  `data-api.polymarket.com/v2/prices-history` (`token_id`, `start`/`end` ≤ 15 days, `as_of`, `bucket_seconds`,
  retention floors: 1-minute data at least 7 days, 30-minute at least 90 days, 3h/12h permanent). It is **not used here** (follow-up).

**Not documented, so not assumed:** whether the CLOB `p` is a midpoint or a last trade (we label it
`price_history_point`). The CLOB's retention and maximum `startTs`/`endTs` span (we chunk at 14 days to be
conservative).

**Empirical: coarse fidelity = point samples (no look-ahead from bucketing).** PR #12's independent auditor
found that `fidelity=60` points equal the `fidelity=1` values at the same `t`. I re-checked on 2026-11-13 for
token `1116…6047`, 2026-07-08 00:00–12:00 UTC: all 12 stored hourly points appear in the `fidelity=1` series
(720 points) with identical `t` and `p`, with 0 absent and 0 different. So a coarse point is the minute-level
observation at `t`, not an aggregate over a bucket that extends past `t`, and selecting points with
`t <= as_of` does not leak later prices through bucketing. This is observed behavior, not a documented
guarantee. It says nothing about how the minute-level value itself is computed.

## Real retrieval check (2026-11-13 UTC, via these adapters)
- Kalshi `/historical/cutoff`: `market_settled_ts = 2026-09-13T00:00:00Z`.
- Kalshi `KXFEDDECISION-26JUL-H0` ("Fed maintains rate", July 2026 FOMC, closed 2026-07-29 17:59Z,
  settled before cutoff → historical tier): `/historical/markets/{ticker}/candlesticks`,
  2026-07-08 → 2026-07-22, hourly. **335 real candles returned.** Every candle had a two-sided book.
  6 had no trades (`price.close = null`).
- Polymarket Gamma market `1654958` ("no change after the July 2026 meeting", `negRisk=true`, `version=v1`) →
  YES token → CLOB `/prices-history` same window, `fidelity=60`. **335 real points returned**, `t` in seconds.
- The window deliberately ends 7 days before both markets' scheduled close, so the stored files contain no
  near-settlement prices. Market metadata responses (which include `result` / `outcomePrices`) were used
  in memory only and **not stored**. `store_raw` refuses them.

Stored under `services/api/data/raw/<venue>/<market_id>/` with `manifest.json` (url, params, collected_at,
sha256, `provenance: REAL HISTORICAL`). Tests verify the hashes.

## Using it
```python
from markets.kalshi import KalshiProvider
from markets.normalize import normalize_quotes, select_quote
raw = KalshiProvider().get_history("KXFEDDECISION-26JUL-H0", start, end)   # offline collection only
q = select_quote(normalize_quotes(raw), as_of)                              # None -> NOT AVAILABLE
```
Quote preference per observation (MATH_MODEL §7): bid/ask midpoint (only for a real two-sided book:
bid > 0, ask < 1, not crossed), then candle trade close, then last trade, then a Polymarket history point.
