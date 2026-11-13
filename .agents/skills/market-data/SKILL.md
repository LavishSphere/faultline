---
name: market-data
description: Building the read-only Kalshi and Polymarket adapters (EventMarketProvider interface), offline snapshot collection with raw payload + SHA256 provenance, as-of quote selection, and cents/decimal normalization. Use for work in services/api/markets/, scripts/collect_market_snapshots.py, data/raw/, or when sourcing historical prediction-market prices for replay cases.
---

# Market data (SPEC §4, MATH_MODEL §7)

## Hard rules
- Public read-only endpoints only. No credentials, wallets, orders, or trading code, ever.
- **Verify endpoint shapes against the official docs at coding time** (WebFetch the doc pages) before writing parsers:
  - Kalshi: https://docs.kalshi.com/getting_started/historical_data and
    https://docs.kalshi.com/api-reference/historical/get-historical-market-candlesticks (check `GET /historical/cutoff` to choose live vs historical endpoints).
  - Polymarket: https://institute.polymarket.com/data; Gamma `https://gamma-api.polymarket.com` for metadata/`token_id`;
    CLOB `https://clob.polymarket.com/prices-history` with `market=<token_id>`, `startTs`, `endTs`, `fidelity`. Verify timestamp units (s vs ms).
- Collection is an **offline step** (`scripts/collect_market_snapshots.py`). Replay inference never calls these APIs.
- If history can't be obtained reliably → mark `NOT AVAILABLE`. Never interpolate or invent a price.

## Interface
```python
class EventMarketProvider(Protocol):
    venue: Literal["kalshi", "polymarket"]
    def get_market(self, market_id: str) -> MarketMeta: ...          # rules, outcomes, settlement source, binary?
    def get_history(self, market_id: str, start: datetime, end: datetime) -> list[RawQuote]: ...
def select_quote(quotes: list[NormalizedQuote], as_of: datetime, max_staleness=timedelta(hours=24)) -> NormalizedQuote | None
```
`NormalizedQuote`: venue, market_id, url, outcome ("YES"), `p_yes` in [0,1], `quote_kind` (midpoint|candle_close|last_trade),
`ts` (UTC), raw price + raw scale, spread/volume if present, `collected_at`, `raw_sha256`.

## Storage
`data/raw/<venue>/<market_id>/<collected_at>.json` (exact response bytes) + `manifest.json` entries
`{path, sha256, url, params, collected_at}`. Outcomes/settlements go to `data/sealed_outcomes/` **only**, never in raw quote files the agent path can read.

## Tests (tests/test_market_normalization.py)
Kalshi 63¢ → 0.63; Polymarket "0.63" → 0.63; normalization applied exactly once (idempotence guard); missing price → None;
out-of-range → rejected; as-of selection picks last ≤ cutoff; stale → None; seconds vs milliseconds timestamps.
Mock HTTP from saved fixture files. Tests never hit the network.
