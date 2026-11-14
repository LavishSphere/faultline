# Candidate markets for Blind Replay (issue #51, supports #20)

**What this is.** A list of resolved 2025–2026 binary markets on FOMC decisions and US CPI prints that exist on
**both** Kalshi and Polymarket with the same definition, and for each one whether a stored price exists 7 days
before the scheduled close. Prices were collected by `scripts/collect_market_snapshots.py` and stored under
`services/api/data/raw/` (provenance `REAL HISTORICAL`, exact bytes plus SHA-256 manifest).

**What this is not.** It is not a case selection and it does not say how any market went. Picking 2–4 cases,
writing the selection rule, the evidence and the sealed outcomes is Yaseen's judgment in #20. The pairing and
the stored files were produced without reading any settlement field. Market metadata bodies (which carry
`result`, `settlement_*`, `outcomePrices`, ...) were parsed in memory and never stored; `raw_store` refuses them.
The table reports only *whether* a quote exists at T−7, not its value. Read the value from the stored snapshot
with `markets.normalize.select_quote` when you build a case.

Everything was collected on 2026-11-13 (UTC). Plan file: `services/api/data/raw/candidate_plan_51.json`
(identifiers, question text, scheduled closes; no prices, no outcomes).

## Summary

| | Kalshi | Polymarket |
|---|---|---|
| Distinct candidate markets | 91 | 96 |
| Price exists at T−7 (last quote at or before T−7, within 24 h) | 85 | 88 |
| Markets with no T−7 price | 6 | 8 (6 returned no points, 2 not collected) |

96 cross-venue pairs (57 FOMC, 39 CPI). Both venues have a T−7 price for **82 pairs**. Kalshi has 5 fewer
distinct markets than pairs because the September 2026 FOMC has two Polymarket events that map onto the same
5 Kalshi markets.

Three more CPI pairs were found and collected but are **excluded from pairing**, because the venues' rules
diverge when the release does not happen (see Flags): September 2025 MoM, October 2025 MoM and October 2025 YoY.
Their snapshots stay in `data/raw/` for reference and are listed under `diverging_pairs` in the plan.

## How candidates were found

**Endpoints** (public, unauthenticated GETs; docs re-checked 2026-11-13 with WebFetch):

- Kalshi `GET /events?series_ticker=…` (docs.kalshi.com/api-reference/events/get-events: `security: []`;
  `mutually_exclusive` true only for MECNET events; nested markets omit markets settled before the historical
  cutoff), `GET /markets?event_ticker=…` and `GET /historical/markets?event_ticker=…`
  (docs.kalshi.com/api-reference/market/get-markets, .../historical/get-historical-markets: `security: []`;
  markets settled before the cutoff are only in `/historical/markets`). Series: `KXFEDDECISION`, `KXCPI`
  (CPI month-over-month), `KXCPIYOY` (CPI year-over-year).
- Polymarket Gamma `GET /public-search`, `GET /events?tag_slug=…&closed=true`, `GET /events/slug/{slug}`
  (docs.polymarket.com/api-spec/gamma-openapi.yaml: no security scheme declared).
- Prices: the #12 adapters (`markets/kalshi.py`, `markets/polymarket.py`), whose endpoint checks are recorded in
  `services/api/markets/README.md`. Kalshi candlesticks: historical or live endpoint chosen from
  `GET /historical/cutoff` (`market_settled_ts` was 2026-09-13T00:00Z on collection day). Polymarket CLOB
  `GET /prices-history?market=<YES token>&startTs&endTs&fidelity=60` (`t` in unix seconds).

Discovery printed whitelisted metadata fields only (ids, titles, rules text, open/close times, status). No price
or settlement field was printed or written.

**Resolved.** Every listed Kalshi market had `status = finalized` and every Polymarket market `closed = true` at
discovery. Those fields say a market is over; they do not say how it went.

**Pairing rules (same definition on both venues):**

- *FOMC.* Kalshi `KXFEDDECISION-<meeting>` legs vs Polymarket "Fed decision in <month>?" legs:
  `H0` ↔ "No change", `C25` ↔ "25 bps decrease", `C26` ("Cut >25bps") ↔ "50+ bps decrease",
  `H25` ↔ "25 bps increase", `H26` ("Hike >25bps") ↔ "50+ bps increase". Until April 2026 Polymarket listed one
  "25+ bps increase" leg, which matches no single Kalshi market, so the hike legs are excluded for those meetings.
  January 2025 split cuts into "50 bps" and "75+ bps", so `C26` has no single match there.
- *CPI.* Kalshi lists cumulative thresholds ("Above x%"); Polymarket lists mutually exclusive buckets of the
  one-decimal figure. Only Polymarket's **top bucket "≥ b%"** is the same event as a single Kalshi market,
  "Above (b − 0.1)%". The bottom bucket "≤ a%" is the *complement* of "Above a%" (YES on one = NO on the other):
  it is listed under exclusions and not collected (the adapters collect the YES side only). Exact-value buckets
  ("0.2%") equal a difference of two Kalshi markets, not one market, so they are excluded and only counted.

**Mutually exclusive groups (do not treat as independent events).** Every FOMC group is one mutually exclusive
set on both venues (Kalshi `mutually_exclusive = true`; Polymarket `negRisk = true`, except the second September
2026 event, which reports `negRisk = false` but has the same five legs). Every Polymarket CPI event is a
mutually exclusive bucket set. Kalshi CPI thresholds are not mutually exclusive but are nested ("Above 0.4%"
implies "Above 0.3%"). Per #20, one meeting or one CPI print should become **one** binary question, not several.

## Window rule and how to re-run

- `reference_close` per pair = the earlier of the two venues' scheduled closes if they are within 3 days of each
  other, otherwise the Kalshi `close_time` (the pair is then flagged "close mismatch"). Both venues use the same
  reference, so their windows match.
- Window: `end` = 00:00 UTC on the day of `reference_close − 7 days`, `start = end − 3 days`, hourly
  (`period_interval = 60` / `fidelity = 60`). The collector refuses any window that ends less than 7 days before
  the reference close **or** before the venue's own scheduled close, and refuses a response with any point after
  `end`, so no stored file contains near-settlement prices.
- **T−7 price** = the last stored quote with `as_of − 24 h ≤ ts ≤ as_of`, `as_of = reference_close − 7 days`
  (MATH_MODEL §7 staleness). Kalshi quote kinds: `midpoint` (two-sided book) or `candle_close` (trade); Polymarket:
  `price_history_point` (the docs do not say whether CLOB `p` is a midpoint or a last trade).
- The July 2026 `KXFEDDECISION-26JUL-H0` / `1654958` pair reuses the 14-day snapshot from #12, which covers this
  window, so nothing new was stored for it.

```bash
python scripts/collect_market_snapshots.py plan                   # idempotent: skips windows already stored
python scripts/collect_market_snapshots.py report                 # offline, prints availability per pair
python scripts/collect_market_snapshots.py market --venue kalshi --market-id KXFEDDECISION-25MAR-H0 \
    --reference-close 2025-03-19T12:00:00Z --lookback-days 14     # one market, wider window
```

## Flags for #20 (read before choosing)

- **Close mismatches.** Polymarket market `endDate` disagrees with the Kalshi close by more than 3 days for
  four pairs: `518813` (CPI YoY Jan 2025, Polymarket 2025-01-12 vs Kalshi 2025-02-12), `833219` (CPI MoM Dec 2025,
  2025-12-13 vs 2026-01-13), `522192` and `522186` (CPI Feb 2025, 2025-03-31 vs 2025-03-12). For `518813` and
  `833219` the Polymarket close is earlier than the T−7 window, so the collector **refused** to collect them
  (shown as NOT AVAILABLE, "no snapshot collected"). If a human confirms the venue date is a metadata error, run
  `market --venue polymarket --market-id <id> --reference-close <Kalshi close> --ignore-venue-close`.
- **January 2026 CPI** closes differ by two days (Polymarket 2026-02-11, Kalshi 2026-02-13). The earlier date was
  used as the reference for both venues. Check the actual BLS release date before setting `as_of`.
- **CPI rules diverge if the release does not happen. Three pairs are NOT the same question.** Every Kalshi CPI
  market's `rules_secondary` says that if a federal government shutdown delays the data, the latest expiration is
  extended to the release, or to six months after the shutdown ends if that is sooner. The Polymarket CPI markets
  up to and including October 2025 data have **no** non-release clause. From November 2025 data the Polymarket
  template says that if the figure is not released in time, the market resolves on the most recent previous month
  with data, which also differs from Kalshi. I checked this with a keyword search of the rule text only, recorded
  per pair as `non_release_clause` in the plan.
  - Excluded from pairing: September 2025 MoM (`KXCPI-25SEP-T0.4` / `594157`), October 2025 MoM
    (`KXCPI-25OCT-T0.4` / `655625`) and October 2025 YoY (`KXCPIYOY-25OCT-T3.1` / `654401`). Their releases fell
    in the period when public reporting (not verified here) says the late-2025 shutdown disrupted the BLS
    calendar.
  - For these, and for any release that was delayed, `as_of = scheduled close − 7 d` may not be 7 days before
    the real release.
  - The other pairs are the same question only if the release happened as the rules expect. Before using one,
    #20 should confirm against the BLS release record that the figure was published on schedule.
- **FOMC rule edge cases** (rule text checked on both venues):
  - *Cancelled meeting or no statement.* Polymarket resolves to "No change" if no statement is released by the
    end of the next scheduled meeting. Kalshi resolves all strikes to No for a cancelled meeting through the May
    2025 meeting (January–May 2025 markets; the June 2025 H0 text I checked still says all No). For "markets
    beginning after the May meeting" (note dated 4/28/25) it resolves "Fed maintains rate" to Yes. So in those
    early meetings `H0` and "No change" differ if the meeting is cancelled.
  - *Moves that are not a multiple of 25 bp.* Polymarket rounds up to the nearest 25 (that clause appears from
    late 2025 markets, e.g. `570362`, but not in `512324` or `516010`). Kalshi `C25` says "a Cut of 25bps" and
    does not define a sub-25 bp move.
- **Duplicate September 2026 FOMC event.** Polymarket has two events (`481717`, `negRisk = true`, and `432066`,
  `negRisk = false`). The CLOB returned no price points at T−7 for any `432066` leg. Use `481717`.
- **Definitions to confirm in the full rules.** Kalshi "Cut >25bps" vs Polymarket "50+ bps decrease" (equal only
  if moves are multiples of 25 bp); CPI thresholds vs buckets (seasonal adjustment and rounding must match on
  both venues). The plan file has the Kalshi `rules_primary` text; full Polymarket rules are in the Gamma
  `description` field, which was not stored because Gamma market bodies carry `outcomePrices`.
- **Thin markets.** Several Kalshi markets returned fewer hourly candles than there are hours in the window
  (observed; the docs do not say why). A T−7 "yes" can come from a quote up to 24 h before `as_of`; the table
  shows its timestamp.

## Candidates

### FOMC rate decisions

| Group | Leg | Kalshi ticker (YES side) | Kalshi close | Price at T−7 (Kalshi) | Polymarket Gamma id | Polymarket question | Polymarket close | Price at T−7 (Polymarket) |
|---|---|---|---|---|---|---|---|---|
| FOMC 2025-01 | no change | `KXFEDDECISION-25JAN-H0` (No change) | 2025-01-29 18:55Z | yes (2025-01-21 23:00Z, midpoint) | `512324` | No change in Fed interest rates after January 2025 meeting? | 2025-01-29 12:00Z | yes (2025-01-21 23:00Z, price_history_point) |
| FOMC 2025-01 | cut 25 | `KXFEDDECISION-25JAN-C25` (Cut 25bps) | 2025-01-29 18:55Z | yes (2025-01-21 20:00Z, midpoint) | `512323` | Fed decreases interest rates by 25 bps after January 2025 meeting? | 2025-01-29 12:00Z | yes (2025-01-21 23:00Z, price_history_point) |
| FOMC 2025-03 | no change | `KXFEDDECISION-25MAR-H0` (No change) | 2025-03-19 17:55Z | yes (2025-03-11 17:00Z, midpoint) | `516010` | No change in Fed interest rates after March 2025 meeting? | 2025-03-19 12:00Z | yes (2025-03-11 23:00Z, price_history_point) |
| FOMC 2025-03 | cut 25 | `KXFEDDECISION-25MAR-C25` (Cut 25bps) | 2025-03-19 17:55Z | yes (2025-03-11 23:00Z, midpoint) | `516009` | Fed decreases interest rates by 25 bps after March 2025 meeting? | 2025-03-19 12:00Z | yes (2025-03-11 23:00Z, price_history_point) |
| FOMC 2025-03 | cut >25 | `KXFEDDECISION-25MAR-C26` (Cut >25bps) | 2025-03-19 17:55Z | yes (2025-03-11 22:00Z, candle_close) | `516008` | Fed decreases interest rates by 50+ bps after March 2025 meeting? | 2025-03-19 12:00Z | yes (2025-03-11 23:00Z, price_history_point) |
| FOMC 2025-05 | no change | `KXFEDDECISION-25MAY-H0` (No change) | 2025-05-07 17:55Z | yes (2025-04-30 00:00Z, midpoint) | `519778` | No change in Fed interest rates after May 2025 meeting? | 2025-05-07 12:00Z | yes (2025-04-29 23:00Z, price_history_point) |
| FOMC 2025-05 | cut 25 | `KXFEDDECISION-25MAY-C25` (Cut 25bps) | 2025-05-07 17:55Z | yes (2025-04-30 00:00Z, midpoint) | `519777` | Fed decreases interest rates by 25 bps after May 2025 meeting? | 2025-05-07 12:00Z | yes (2025-04-29 23:00Z, price_history_point) |
| FOMC 2025-05 | cut >25 | `KXFEDDECISION-25MAY-C26` (Cut >25bps) | 2025-05-07 17:55Z | yes (2025-04-30 00:00Z, midpoint) | `519776` | Fed decreases interest rates by 50+ bps after May 2025 meeting? | 2025-05-07 12:00Z | yes (2025-04-29 23:00Z, price_history_point) |
| FOMC 2025-06 | no change | `KXFEDDECISION-25JUN-H0` (No change) | 2025-06-18 17:55Z | yes (2025-06-11 00:00Z, midpoint) | `521836` | No change in Fed interest rates after June 2025 meeting? | 2025-06-18 12:00Z | yes (2025-06-10 23:00Z, price_history_point) |
| FOMC 2025-06 | cut 25 | `KXFEDDECISION-25JUN-C25` (Cut 25bps) | 2025-06-18 17:55Z | yes (2025-06-11 00:00Z, midpoint) | `521835` | Fed decreases interest rates by 25 bps after June 2025 meeting? | 2025-06-18 12:00Z | yes (2025-06-10 23:00Z, price_history_point) |
| FOMC 2025-06 | cut >25 | `KXFEDDECISION-25JUN-C26` (Cut >25bps) | 2025-06-18 17:55Z | yes (2025-06-11 00:00Z, candle_close) | `521834` | Fed decreases interest rates by 50+ bps after June 2025 meeting? | 2025-06-18 12:00Z | yes (2025-06-10 23:00Z, price_history_point) |
| FOMC 2025-07 | no change | `KXFEDDECISION-25JUL-H0` (Fed maintains rate) | 2025-07-30 17:55Z | yes (2025-07-23 00:00Z, midpoint) | `528974` | No change in Fed interest rates after July 2025 meeting? | 2025-07-30 12:00Z | yes (2025-07-22 23:00Z, price_history_point) |
| FOMC 2025-07 | cut 25 | `KXFEDDECISION-25JUL-C25` (Cut 25bps) | 2025-07-30 17:55Z | yes (2025-07-23 00:00Z, midpoint) | `528973` | Fed decreases interest rates by 25 bps after July 2025 meeting? | 2025-07-30 12:00Z | yes (2025-07-22 23:00Z, price_history_point) |
| FOMC 2025-07 | cut >25 | `KXFEDDECISION-25JUL-C26` (Cut >25bps) | 2025-07-30 17:55Z | yes (2025-07-23 00:00Z, midpoint) | `528972` | Fed decreases interest rates by 50+ bps after July 2025 meeting? | 2025-07-30 12:00Z | yes (2025-07-22 23:00Z, price_history_point) |
| FOMC 2025-09 | no change | `KXFEDDECISION-25SEP-H0` (Fed maintains rate) | 2025-09-17 17:55Z | yes (2025-09-10 00:00Z, midpoint) | `542539` | No change in Fed interest rates after September 2025 meeting? | 2025-09-17 12:00Z | yes (2025-09-09 23:00Z, price_history_point) |
| FOMC 2025-09 | cut 25 | `KXFEDDECISION-25SEP-C25` (Cut 25bps) | 2025-09-17 17:55Z | yes (2025-09-10 00:00Z, midpoint) | `542538` | Fed decreases interest rates by 25 bps after September 2025 meeting? | 2025-09-17 12:00Z | yes (2025-09-09 23:00Z, price_history_point) |
| FOMC 2025-09 | cut >25 | `KXFEDDECISION-25SEP-C26` (Cut >25bps) | 2025-09-17 17:55Z | yes (2025-09-10 00:00Z, midpoint) | `542537` | Fed decreases interest rates by 50+ bps after September 2025 meeting? | 2025-09-17 12:00Z | yes (2025-09-09 23:00Z, price_history_point) |
| FOMC 2025-10 | no change | `KXFEDDECISION-25OCT-H0` (Fed maintains rate) | 2025-10-29 17:59Z | yes (2025-10-22 00:00Z, midpoint) | `553812` | No change in Fed interest rates after October 2025 meeting? | 2025-10-29 12:00Z | yes (2025-10-21 23:00Z, price_history_point) |
| FOMC 2025-10 | cut 25 | `KXFEDDECISION-25OCT-C25` (Cut 25bps) | 2025-10-29 17:59Z | yes (2025-10-22 00:00Z, midpoint) | `553811` | Fed decreases interest rates by 25 bps after October 2025 meeting? | 2025-10-29 12:00Z | yes (2025-10-21 23:00Z, price_history_point) |
| FOMC 2025-10 | cut >25 | `KXFEDDECISION-25OCT-C26` (Cut >25bps) | 2025-10-29 17:59Z | yes (2025-10-22 00:00Z, midpoint) | `553810` | Fed decreases interest rates by 50+ bps after October 2025 meeting? | 2025-10-29 12:00Z | yes (2025-10-21 23:00Z, price_history_point) |
| FOMC 2025-12 | no change | `KXFEDDECISION-25DEC-H0` (Fed maintains rate) | 2025-12-10 18:59Z | yes (2025-12-03 00:00Z, midpoint) | `570362` | No change in Fed interest rates after December 2025 meeting? | 2025-12-10 00:00Z | yes (2025-12-02 23:00Z, price_history_point) |
| FOMC 2025-12 | cut 25 | `KXFEDDECISION-25DEC-C25` (Cut 25bps) | 2025-12-10 18:59Z | yes (2025-12-03 00:00Z, midpoint) | `570361` | Fed decreases interest rates by 25 bps after December 2025 meeting? | 2025-12-10 00:00Z | yes (2025-12-02 23:00Z, price_history_point) |
| FOMC 2025-12 | cut >25 | `KXFEDDECISION-25DEC-C26` (Cut >25bps) | 2025-12-10 18:59Z | yes (2025-12-03 00:00Z, midpoint) | `570360` | Fed decreases interest rates by 50+ bps after December 2025 meeting? | 2025-12-10 00:00Z | yes (2025-12-02 23:00Z, price_history_point) |
| FOMC 2026-01 | no change | `KXFEDDECISION-26JAN-H0` (Fed maintains rate) | 2026-01-28 18:59Z | yes (2026-01-21 00:00Z, midpoint) | `601699` | No change in Fed interest rates after January 2026 meeting? | 2026-01-28 00:00Z | yes (2026-01-20 23:00Z, price_history_point) |
| FOMC 2026-01 | cut 25 | `KXFEDDECISION-26JAN-C25` (Cut 25bps) | 2026-01-28 18:59Z | yes (2026-01-21 00:00Z, midpoint) | `601698` | Fed decreases interest rates by 25 bps after January 2026 meeting? | 2026-01-28 00:00Z | yes (2026-01-20 23:00Z, price_history_point) |
| FOMC 2026-01 | cut >25 | `KXFEDDECISION-26JAN-C26` (Cut >25bps) | 2026-01-28 18:59Z | yes (2026-01-21 00:00Z, candle_close) | `601697` | Fed decreases interest rates by 50+ bps after January 2026 meeting? | 2026-01-28 00:00Z | yes (2026-01-20 23:00Z, price_history_point) |
| FOMC 2026-03 | no change | `KXFEDDECISION-26MAR-H0` (Fed maintains rate) | 2026-03-18 17:59Z | yes (2026-03-11 00:00Z, midpoint) | `654414` | Will there be no change in Fed interest rates after the March 2026 meeting? | 2026-03-18 00:00Z | yes (2026-03-10 23:00Z, price_history_point) |
| FOMC 2026-03 | cut 25 | `KXFEDDECISION-26MAR-C25` (Cut 25bps) | 2026-03-18 17:59Z | yes (2026-03-11 00:00Z, midpoint) | `654413` | Will the Fed decrease interest rates by 25 bps after the March 2026 meeting? | 2026-03-18 00:00Z | yes (2026-03-10 23:00Z, price_history_point) |
| FOMC 2026-03 | cut >25 | `KXFEDDECISION-26MAR-C26` (Cut >25bps) | 2026-03-18 17:59Z | yes (2026-03-11 00:00Z, candle_close) | `654412` | Will the Fed decrease interest rates by 50+ bps after the March 2026 meeting? | 2026-03-18 00:00Z | yes (2026-03-10 23:00Z, price_history_point) |
| FOMC 2026-04 | no change | `KXFEDDECISION-26APR-H0` (Fed maintains rate) | 2026-04-29 17:59Z | yes (2026-04-22 00:00Z, midpoint) | `669662` | Will there be no change in Fed interest rates after the April 2026 meeting? | 2026-04-29 00:00Z | yes (2026-04-21 23:00Z, price_history_point) |
| FOMC 2026-04 | cut 25 | `KXFEDDECISION-26APR-C25` (Cut 25bps) | 2026-04-29 17:59Z | yes (2026-04-22 00:00Z, candle_close) | `669661` | Will the Fed decrease interest rates by 25 bps after the April 2026 meeting? | 2026-04-29 00:00Z | yes (2026-04-21 23:00Z, price_history_point) |
| FOMC 2026-04 | cut >25 | `KXFEDDECISION-26APR-C26` (Cut >25bps) | 2026-04-29 17:59Z | yes (2026-04-22 00:00Z, candle_close) | `669660` | Will the Fed decrease interest rates by 50+ bps after the April 2026 meeting? | 2026-04-29 00:00Z | yes (2026-04-21 23:00Z, price_history_point) |
| FOMC 2026-06 | no change | `KXFEDDECISION-26JUN-H0` (Fed maintains rate) | 2026-06-17 17:59Z | yes (2026-06-10 00:00Z, midpoint) | `906974` | Will there be no change in Fed interest rates after the June 2026 meeting? | 2026-06-17 00:00Z | yes (2026-06-09 23:00Z, price_history_point) |
| FOMC 2026-06 | cut 25 | `KXFEDDECISION-26JUN-C25` (Cut 25bps) | 2026-06-17 17:59Z | yes (2026-06-10 00:00Z, midpoint) | `906973` | Will the Fed decrease interest rates by 25 bps after the June 2026 meeting? | 2026-06-17 00:00Z | yes (2026-06-09 23:00Z, price_history_point) |
| FOMC 2026-06 | cut >25 | `KXFEDDECISION-26JUN-C26` (Cut >25bps) | 2026-06-17 17:59Z | yes (2026-06-10 00:00Z, candle_close) | `906972` | Will the Fed decrease interest rates by 50+ bps after the June 2026 meeting? | 2026-06-17 00:00Z | yes (2026-06-09 23:00Z, price_history_point) |
| FOMC 2026-06 | hike 25 | `KXFEDDECISION-26JUN-H25` (Hike 25bps) | 2026-06-17 17:59Z | yes (2026-06-10 00:00Z, candle_close) | `906975` | Will the Fed increase interest rates by 25 bps after the June 2026 meeting? | 2026-06-17 00:00Z | yes (2026-06-09 23:00Z, price_history_point) |
| FOMC 2026-06 | hike >25 | `KXFEDDECISION-26JUN-H26` (Hike >25bps) | 2026-06-17 17:59Z | yes (2026-06-10 00:00Z, candle_close) | `906976` | Will the Fed increase interest rates by 50+ bps after the June 2026 meeting? | 2026-06-17 00:00Z | yes (2026-06-09 23:00Z, price_history_point) |
| FOMC 2026-07 | no change | `KXFEDDECISION-26JUL-H0` (Fed maintains rate) | 2026-07-29 17:59Z | yes (2026-07-22 00:00Z, midpoint) | `1654958` | Will there be no change in Fed interest rates after the July 2026 meeting? | 2026-07-29 00:00Z | yes (2026-07-21 23:00Z, price_history_point) |
| FOMC 2026-07 | cut 25 | `KXFEDDECISION-26JUL-C25` (Cut 25bps) | 2026-07-29 17:59Z | yes (2026-07-22 00:00Z, candle_close) | `1654957` | Will the Fed decrease interest rates by 25 bps after the July 2026 meeting? | 2026-07-29 00:00Z | yes (2026-07-21 23:00Z, price_history_point) |
| FOMC 2026-07 | cut >25 | `KXFEDDECISION-26JUL-C26` (Cut >25bps) | 2026-07-29 17:59Z | yes (2026-07-22 00:00Z, candle_close) | `1654956` | Will the Fed decrease interest rates by 50+ bps after the July 2026 meeting? | 2026-07-29 00:00Z | yes (2026-07-21 23:00Z, price_history_point) |
| FOMC 2026-07 | hike 25 | `KXFEDDECISION-26JUL-H25` (Hike 25bps) | 2026-07-29 17:59Z | yes (2026-07-22 00:00Z, midpoint) | `1654959` | Will the Fed increase interest rates by 25 bps after the July 2026 meeting? | 2026-07-29 00:00Z | yes (2026-07-21 23:00Z, price_history_point) |
| FOMC 2026-07 | hike >25 | `KXFEDDECISION-26JUL-H26` (Hike >25bps) | 2026-07-29 17:59Z | yes (2026-07-22 00:00Z, midpoint) | `1654960` | Will the Fed increase interest rates by 50+ bps after the July 2026 meeting? | 2026-07-29 00:00Z | yes (2026-07-21 23:00Z, price_history_point) |
| FOMC 2026-09 | no change | `KXFEDDECISION-26SEP-H0` (Fed maintains rate) | 2026-09-16 17:59Z | yes (2026-09-09 00:00Z, midpoint) | `2252244` | Will there be no change in Fed interest rates after the September 2026 meeting? | 2026-09-16 00:00Z | yes (2026-09-08 23:00Z, price_history_point) |
| FOMC 2026-09 | cut 25 | `KXFEDDECISION-26SEP-C25` (Cut 25bps) | 2026-09-16 17:59Z | yes (2026-09-09 00:00Z, candle_close) | `2252243` | Will the Fed decrease interest rates by 25 bps after the September 2026 meeting? | 2026-09-16 00:00Z | yes (2026-09-08 23:00Z, price_history_point) |
| FOMC 2026-09 | cut >25 | `KXFEDDECISION-26SEP-C26` (Cut >25bps) | 2026-09-16 17:59Z | yes (2026-09-08 21:00Z, candle_close) | `2252242` | Will the Fed decrease interest rates by 50+ bps after the September 2026 meeting? | 2026-09-16 00:00Z | yes (2026-09-08 23:00Z, price_history_point) |
| FOMC 2026-09 | hike 25 | `KXFEDDECISION-26SEP-H25` (Hike 25bps) | 2026-09-16 17:59Z | yes (2026-09-09 00:00Z, midpoint) | `2252245` | Will the Fed increase interest rates by 25 bps after the September 2026 meeting? | 2026-09-16 00:00Z | yes (2026-09-08 23:00Z, price_history_point) |
| FOMC 2026-09 | hike >25 | `KXFEDDECISION-26SEP-H26` (Hike >25bps) | 2026-09-16 17:59Z | yes (2026-09-09 00:00Z, midpoint) | `2252246` | Will the Fed increase interest rates by 50+ bps after the September 2026 meeting? | 2026-09-16 00:00Z | yes (2026-09-08 23:00Z, price_history_point) |
| FOMC 2026-09 (second Polymarket event) | no change | `KXFEDDECISION-26SEP-H0` (Fed maintains rate) | 2026-09-16 17:59Z | yes (2026-09-09 00:00Z, midpoint) | `2118744` | Will there be no change in Fed interest rates after the September 2026 meeting? | 2026-09-16 00:00Z | **NOT AVAILABLE**: venue returned no price points in the window |
| FOMC 2026-09 (second Polymarket event) | cut 25 | `KXFEDDECISION-26SEP-C25` (Cut 25bps) | 2026-09-16 17:59Z | yes (2026-09-09 00:00Z, candle_close) | `2118743` | Will the Fed decrease interest rates by 25 bps after the September 2026 meeting? | 2026-09-16 00:00Z | **NOT AVAILABLE**: venue returned no price points in the window |
| FOMC 2026-09 (second Polymarket event) | cut >25 | `KXFEDDECISION-26SEP-C26` (Cut >25bps) | 2026-09-16 17:59Z | yes (2026-09-08 21:00Z, candle_close) | `2118742` | Will the Fed decrease interest rates by 50+ bps after the September 2026 meeting? | 2026-09-16 00:00Z | **NOT AVAILABLE**: venue returned no price points in the window |
| FOMC 2026-09 (second Polymarket event) | hike 25 | `KXFEDDECISION-26SEP-H25` (Hike 25bps) | 2026-09-16 17:59Z | yes (2026-09-09 00:00Z, midpoint) | `2118745` | Will the Fed increase interest rates by 25 bps after the September 2026 meeting? | 2026-09-16 00:00Z | **NOT AVAILABLE**: venue returned no price points in the window |
| FOMC 2026-09 (second Polymarket event) | hike >25 | `KXFEDDECISION-26SEP-H26` (Hike >25bps) | 2026-09-16 17:59Z | yes (2026-09-09 00:00Z, midpoint) | `2118746` | Will the Fed increase interest rates by 50+ bps after the September 2026 meeting? | 2026-09-16 00:00Z | **NOT AVAILABLE**: venue returned no price points in the window |
| FOMC 2026-10 | no change | `KXFEDDECISION-26OCT-H0` (Fed maintains rate) | 2026-10-28 17:59Z | yes (2026-10-21 00:00Z, midpoint) | `2589812` | Will there be no change in Fed interest rates after the October 2026 meeting? | 2026-10-29 03:59Z | yes (2026-10-20 23:00Z, price_history_point) |
| FOMC 2026-10 | cut 25 | `KXFEDDECISION-26OCT-C25` (Cut 25bps) | 2026-10-28 17:59Z | yes (2026-10-21 00:00Z, candle_close) | `2589811` | Will the Fed decrease interest rates by 25 bps after the October 2026 meeting? | 2026-10-29 03:59Z | yes (2026-10-20 23:00Z, price_history_point) |
| FOMC 2026-10 | cut >25 | `KXFEDDECISION-26OCT-C26` (Cut >25bps) | 2026-10-28 17:59Z | yes (2026-10-20 19:00Z, candle_close) | `2589810` | Will the Fed decrease interest rates by 50+ bps after the October 2026 meeting? | 2026-10-29 03:59Z | yes (2026-10-20 23:00Z, price_history_point) |
| FOMC 2026-10 | hike 25 | `KXFEDDECISION-26OCT-H25` (Hike 25bps) | 2026-10-28 17:59Z | yes (2026-10-21 00:00Z, midpoint) | `2589813` | Will the Fed increase interest rates by 25 bps after the October 2026 meeting? | 2026-10-29 03:59Z | yes (2026-10-20 23:00Z, price_history_point) |
| FOMC 2026-10 | hike >25 | `KXFEDDECISION-26OCT-H26` (Hike >25bps) | 2026-10-28 17:59Z | yes (2026-10-20 18:00Z, candle_close) | `2589814` | Will the Fed increase interest rates by 50+ bps after the October 2026 meeting? | 2026-10-29 03:59Z | yes (2026-10-20 23:00Z, price_history_point) |

### CPI prints

| Group | Leg | Kalshi ticker (YES side) | Kalshi close | Price at T−7 (Kalshi) | Polymarket Gamma id | Polymarket question | Polymarket close | Price at T−7 (Polymarket) |
|---|---|---|---|---|---|---|---|---|
| CPI MoM 2024-12 (december-inflation-monthly) | ≥0.5% == Kalshi Above 0.4% | `KXCPI-24DEC-T0.4` (Above 0.4%) | 2025-01-15 13:25Z | yes (2025-01-07 23:00Z, midpoint) | `518390` | Will monthly inflation increase by 0.5% or more in December? | 2025-01-15 12:00Z | **NOT AVAILABLE**: venue returned no price points in the window |
| CPI YoY 2024-12 (december-inflation) | ≥2.9% == Kalshi Above 2.8% | `KXCPIYOY-24DEC-T2.8` (Above 2.8%) | 2025-01-15 13:25Z | yes (2025-01-08 00:00Z, midpoint) | `515388` | Will US annual inflation be 2.9% or greater in December? | 2025-01-15 12:00Z | yes (2025-01-07 23:00Z, price_history_point) |
| CPI MoM 2025-01 (january-inflation-monthly) | ≥0.4% == Kalshi Above 0.3% | `KXCPI-25JAN-T0.3` (Above 0.3%) | 2025-02-12 13:25Z | yes (2025-02-04 19:00Z, midpoint) | `518796` | Will monthly inflation increase by 0.4% or more in January? | 2025-02-12 12:00Z | yes (2025-02-04 23:00Z, price_history_point) |
| CPI YoY 2025-01 (january-inflation-annual) | ≥2.9% == Kalshi Above 2.8% | `KXCPIYOY-25JAN-T2.8` (Above 2.8%) | 2025-02-12 13:25Z | yes (2025-02-04 23:00Z, midpoint) | `518813` | Will annual inflation increase by 2.9% or more in January? | 2025-01-12 12:00Z (close mismatch 31.06 d) | **NOT AVAILABLE**: no snapshot collected |
| CPI MoM 2025-02 (february-inflation-monthly) | ≥0.5% == Kalshi Above 0.4% | `KXCPI-25FEB-T0.4` (Above 0.4%) | 2025-03-12 12:25Z | yes (2025-03-04 22:00Z, midpoint) | `522192` | Will monthly inflation increase by 0.5% or more in February? | 2025-03-31 12:00Z (close mismatch 18.98 d) | yes (2025-03-04 23:00Z, price_history_point) |
| CPI YoY 2025-02 (february-inflation-annual) | ≥3.1% == Kalshi Above 3.0% | `KXCPIYOY-25FEB-T3.0` (Above 3.0%) | 2025-03-12 12:25Z | yes (2025-03-04 22:00Z, midpoint) | `522186` | Will annual inflation increase by 3.1% or more in February? | 2025-03-31 12:00Z (close mismatch 18.98 d) | yes (2025-03-04 23:00Z, price_history_point) |
| CPI YoY 2025-03 (march-inflation-annual) | ≥2.8% == Kalshi Above 2.7% | `KXCPIYOY-25MAR-T2.7` (Above 2.7%) | 2025-04-10 12:25Z | yes (2025-04-03 00:00Z, midpoint) | `527847` | Will annual inflation increase by 2.8% or more in March? | 2025-04-10 12:00Z | yes (2025-04-02 23:00Z, price_history_point) |
| CPI MoM 2025-04 (april-inflation-monthly) | ≥0.5% == Kalshi Above 0.4% | `KXCPI-25APR-T0.4` (Above 0.4%) | 2025-05-13 12:25Z | yes (2025-05-06 00:00Z, midpoint) | `535929` | Will monthly inflation increase by 0.5% or more in April? | 2025-05-13 12:00Z | yes (2025-05-05 23:00Z, price_history_point) |
| CPI YoY 2025-04 (april-inflation-annual) | ≥2.7% == Kalshi Above 2.6% | `KXCPIYOY-25APR-T2.6` (Above 2.6%) | 2025-05-13 12:25Z | yes (2025-05-06 00:00Z, midpoint) | `535934` | Will annual inflation increase by 2.7% or more in April? | 2025-05-13 12:00Z | yes (2025-05-05 23:00Z, price_history_point) |
| CPI MoM 2025-05 (may-inflation-monthly) | ≥0.4% == Kalshi Above 0.3% | `KXCPI-25MAY-T0.3` (Above 0.3%) | 2025-06-11 12:25Z | yes (2025-06-04 00:00Z, midpoint) | `544344` | Will monthly inflation increase by 0.4% or more in May? | 2025-06-11 12:00Z | yes (2025-06-03 23:00Z, price_history_point) |
| CPI YoY 2025-05 (may-inflation-annual) | ≥2.6% == Kalshi Above 2.5% | `KXCPIYOY-25MAY-T2.5` (Above 2.5%) | 2025-06-11 12:25Z | yes (2025-06-04 00:00Z, midpoint) | `544349` | Will annual inflation increase by 2.6% or more in May? | 2025-06-11 12:00Z | yes (2025-06-03 23:00Z, price_history_point) |
| CPI MoM 2025-06 (june-inflation-monthly) | ≥0.4% == Kalshi Above 0.3% | `KXCPI-25JUN-T0.3` (Above 0.3%) | 2025-07-15 12:29Z | yes (2025-07-08 00:00Z, midpoint) | `551583` | Will monthly inflation increase by 0.4% or more in June? | 2025-07-15 12:30Z | yes (2025-07-07 23:00Z, price_history_point) |
| CPI YoY 2025-06 (june-inflation-annual) | ≥2.6% == Kalshi Above 2.5% | `KXCPIYOY-25JUN-T2.5` (Above 2.5%) | 2025-07-15 12:29Z | yes (2025-07-08 00:00Z, midpoint) | `551588` | Will annual inflation increase by 2.6% or more in June? | 2025-07-15 12:30Z | yes (2025-07-07 23:00Z, price_history_point) |
| CPI MoM 2025-07 (july-inflation-monthly) | ≥0.5% == Kalshi Above 0.4% | `KXCPI-25JUL-T0.4` (Above 0.4%) | 2025-08-12 12:29Z | yes (2025-08-05 00:00Z, midpoint) | `563695` | Will monthly inflation increase by 0.5% or more in July? | 2025-08-15 00:00Z | yes (2025-08-04 23:00Z, price_history_point) |
| CPI YoY 2025-07 (july-inflation-annual-462) | ≥3.0% == Kalshi Above 2.9% | `KXCPIYOY-25JUL-T2.9` (Above 2.9%) | 2025-08-12 12:29Z | yes (2025-08-05 00:00Z, midpoint) | `563709` | Will annual inflation increase by 3.0% or more in July? | 2025-08-12 00:00Z | yes (2025-08-04 23:00Z, price_history_point) |
| CPI MoM 2025-08 (august-inflation-monthly) | ≥0.4% == Kalshi Above 0.3% | `KXCPI-25AUG-T0.3` (Above 0.3%) | 2025-09-11 12:25Z | yes (2025-09-04 00:00Z, midpoint) | `575242` | Will monthly inflation increase by 0.4% or more in August? | 2025-09-11 00:00Z | yes (2025-09-03 23:00Z, price_history_point) |
| CPI YoY 2025-08 (august-inflation-annual) | ≥3.0% == Kalshi Above 2.9% | `KXCPIYOY-25AUG-T2.9` (Above 2.9%) | 2025-09-11 12:29Z | yes (2025-09-04 00:00Z, midpoint) | `575237` | Will annual inflation increase by 3.0% or more in August? | 2025-09-11 00:00Z | yes (2025-09-03 23:00Z, price_history_point) |
| CPI YoY 2025-11 (november-inflation-annual) | ≥3.2% == Kalshi Above 3.1% | `KXCPIYOY-25NOV-T3.1` (Above 3.1%) | 2025-12-18 13:29Z | yes (2025-12-11 00:00Z, midpoint) | `680537` | Will annual inflation increase by ≥3.2% in November? | 2025-12-18 00:00Z | yes (2025-12-10 23:00Z, price_history_point) |
| CPI MoM 2025-12 (december-inflation-us-monthly) | ≥0.5% == Kalshi Above 0.4% | `KXCPI-25DEC-T0.4` (Above 0.4%) | 2026-01-13 13:29Z | yes (2026-01-06 00:00Z, midpoint) | `833219` | Will monthly inflation increase by 0.5% or more in December? | 2025-12-13 00:00Z (close mismatch 31.56 d) | **NOT AVAILABLE**: no snapshot collected |
| CPI YoY 2025-12 (december-inflation-us-annual) | ≥3.2% == Kalshi Above 3.1% | `KXCPIYOY-25DEC-T3.1` (Above 3.1%) | 2026-01-13 13:29Z | yes (2026-01-05 19:00Z, candle_close) | `833214` | Will annual inflation increase by ≥3.2% in December? | 2026-01-13 00:00Z | yes (2026-01-05 23:00Z, price_history_point) |
| CPI MoM 2026-01 (january-inflation-us-monthly) | ≥0.5% == Kalshi Above 0.4% | `KXCPI-26JAN-T0.4` (Above 0.4%) | 2026-02-13 13:29Z | yes (2026-02-04 00:00Z, midpoint) | `969649` | Will monthly inflation increase by 0.5% or more in January? | 2026-02-11 00:00Z | yes (2026-02-03 23:00Z, price_history_point) |
| CPI YoY 2026-01 (january-inflation-us-annual) | ≥3.2% == Kalshi Above 3.1% | `KXCPIYOY-26JAN-T3.1` (Above 3.1%) | 2026-02-13 13:29Z | yes (2026-02-03 23:00Z, candle_close) | `969664` | Will annual inflation increase by ≥3.2% in January? | 2026-02-11 00:00Z | yes (2026-02-03 23:00Z, price_history_point) |
| CPI YoY 2026-01 (january-inflation-us-annual-lower-brackets-817) | ≥2.7% == Kalshi Above 2.6% | `KXCPIYOY-26JAN-T2.6` (Above 2.6%) | 2026-02-13 13:29Z | yes (2026-02-04 00:00Z, midpoint) | `1185722` | Will annual inflation increase by ≥2.7% in January? | 2026-02-11 00:00Z | yes (2026-02-03 23:00Z, price_history_point) |
| CPI MoM 2026-02 (february-inflation-us-monthly-231) | ≥0.4% == Kalshi Above 0.3% | `KXCPI-26FEB-T0.3` (Above 0.3%) | 2026-03-11 12:29Z | yes (2026-03-04 00:00Z, midpoint) | `1373678` | Will monthly inflation increase by 0.4% or more in February? | 2026-03-11 00:00Z | yes (2026-03-03 23:00Z, price_history_point) |
| CPI YoY 2026-02 (february-inflation-us-annual) | ≥2.7% == Kalshi Above 2.6% | `KXCPIYOY-26FEB-T2.6` (Above 2.6%) | 2026-03-11 12:29Z | yes (2026-03-04 00:00Z, midpoint) | `1373479` | Will annual inflation increase by ≥2.7% in February? | 2026-03-11 00:00Z | yes (2026-03-03 23:00Z, price_history_point) |
| CPI MoM 2026-03 (march-inflation-us-monthly) | ≥0.8% == Kalshi Above 0.7% | `KXCPI-26MAR-T0.7` (Above 0.7%) | 2026-04-10 12:25Z | yes (2026-04-03 00:00Z, midpoint) | `1559154` | Will monthly inflation increase by 0.8% or more in March? | 2026-04-10 00:00Z | yes (2026-04-02 23:00Z, price_history_point) |
| CPI YoY 2026-03 (march-inflation-us-annual) | ≥2.8% == Kalshi Above 2.7% | `KXCPIYOY-26MAR-T2.7` (Above 2.7%) | 2026-04-10 13:00Z | yes (2026-04-02 04:00Z, candle_close) | `1374263` | Will annual inflation increase by ≥2.8% in March? | 2026-04-10 00:00Z | yes (2026-04-02 23:00Z, price_history_point) |
| CPI YoY 2026-03 (march-inflation-us-annual-higher-brackets) | ≥3.4% == Kalshi Above 3.3% | `KXCPIYOY-26MAR-T3.3` (Above 3.3%) | 2026-04-10 13:00Z | yes (2026-04-03 00:00Z, midpoint) | `1559117` | Will annual inflation increase by ≥3.4% in March? | 2026-04-10 00:00Z | yes (2026-04-02 23:00Z, price_history_point) |
| CPI MoM 2026-04 (april-inflation-us-monthly) | ≥1.1% == Kalshi Above 1.0% | `KXCPI-26APR-T1.0` (Above 1.0%) | 2026-05-12 12:25Z | **NOT AVAILABLE**: no priced observation in the 24h before as_of | `1937996` | Will monthly inflation increase by ≥1.1% in April? | 2026-05-12 00:00Z | yes (2026-05-04 23:00Z, price_history_point) |
| CPI YoY 2026-04 (april-inflation-us-annual) | ≥4.1% == Kalshi Above 4.0% | `KXCPIYOY-26APR-T4.0` (Above 4.0%) | 2026-05-12 12:29Z | yes (2026-05-04 21:00Z, midpoint) | `1937962` | Will annual inflation increase by ≥4.1% in April? | 2026-05-12 00:00Z | yes (2026-05-04 23:00Z, price_history_point) |
| CPI MoM 2026-05 (may-inflation-us-monthly) | ≥0.9% == Kalshi Above 0.8% | `KXCPI-26MAY-T0.8` (Above 0.8%) | 2026-06-10 12:25Z | **NOT AVAILABLE**: no priced observation in the 24h before as_of | `2242053` | Will monthly inflation increase by 0.9% or more in May? | 2026-06-10 08:00Z | yes (2026-06-02 23:00Z, price_history_point) |
| CPI YoY 2026-05 (may-inflation-us-annual) | ≥4.4% == Kalshi Above 4.3% | `KXCPIYOY-26MAY-T4.3` (Above 4.3%) | 2026-06-10 12:29Z | yes (2026-06-03 00:00Z, midpoint) | `2242383` | Will annual inflation be 4.4% or more in May? | 2026-06-10 08:00Z | yes (2026-06-02 23:00Z, price_history_point) |
| CPI MoM 2026-07 (july-inflation-us-monthly-20260714151042665) | ≥0.1% == Kalshi Above 0.0% | `KXCPI-26JUL-T0.0` (Above 0.0%) | 2026-08-12 12:25Z | yes (2026-08-05 00:00Z, midpoint) | `2925106` | Will monthly inflation increase by 0.1% or more in July? | 2026-08-12 03:59Z | yes (2026-08-04 23:00Z, price_history_point) |
| CPI YoY 2026-07 (july-inflation-us-annual-20260714150613267) | ≥4.2% == Kalshi Above 4.1% | `KXCPIYOY-26JUL-T4.1` (Above 4.1%) | 2026-08-12 12:29Z | **NOT AVAILABLE**: no priced observation in the 24h before as_of | `2925083` | Will annual inflation be 4.2% or more in July? | 2026-08-12 03:59Z | yes (2026-08-04 23:00Z, price_history_point) |
| CPI MoM 2026-08 (august-inflation-us-monthly-1786474662954) | ≥0.5% == Kalshi Above 0.4% | `KXCPI-26AUG-T0.4` (Above 0.4%) | 2026-09-11 12:25Z | yes (2026-09-04 00:00Z, midpoint) | `3539668` | Will monthly inflation increase by 0.5% or more in August? | 2026-09-11 03:59Z | yes (2026-09-03 23:00Z, price_history_point) |
| CPI YoY 2026-08 (august-inflation-us-annual-1786474662954) | ≥4.0% == Kalshi Above 3.9% | `KXCPIYOY-26AUG-T3.9` (Above 3.9%) | 2026-09-11 12:29Z | **NOT AVAILABLE**: no priced observation in the 24h before as_of | `3539680` | Will annual inflation be 4.0% or more in August? | 2026-09-11 03:59Z | yes (2026-09-03 23:00Z, price_history_point) |
| CPI MoM 2026-09 (september-inflation-us-monthly) | ≥0.8% == Kalshi Above 0.7% | `KXCPI-26SEP-T0.7` (Above 0.7%) | 2026-10-14 12:29Z | yes (2026-10-07 00:00Z, midpoint) | `4469465` | Will monthly inflation increase by 0.8% or more in September? | 2026-10-15 03:59Z | yes (2026-10-06 23:00Z, price_history_point) |
| CPI YoY 2026-09 (september-inflation-us-annual) | ≥4.0% == Kalshi Above 3.9% | `KXCPIYOY-26SEP-T3.9` (Above 3.9%) | 2026-10-14 12:29Z | **NOT AVAILABLE**: no priced observation in the 24h before as_of | `4469403` | Will annual inflation be 4.0% or more in September? | 2026-10-15 03:59Z | yes (2026-10-06 23:00Z, price_history_point) |
| CPI MoM 2026-10 (october-inflation-us-monthly) | ≥0.9% == Kalshi Above 0.8% | `KXCPI-26OCT-T0.8` (Above 0.8%) | 2026-11-10 13:29Z | **NOT AVAILABLE**: venue returned 7 observations, none priced (no two-sided book and no trade) | `5691235` | Will monthly inflation increase by 0.9% or more in October? | 2026-11-11 04:59Z | yes (2026-11-02 23:00Z, price_history_point) |

## Excluded legs, per group

- **FOMC 2025-01** (Kalshi `KXFEDDECISION-25JAN`, mutually exclusive=True; Polymarket event `14220` negRisk=True): 2 pair(s). Excluded: kalshi `KXFEDDECISION-25JAN-C26` cut >25: no single Polymarket market with the same definition; kalshi `KXFEDDECISION-25JAN-H25` hike 25: no single Polymarket market with the same definition; kalshi `KXFEDDECISION-25JAN-H26` hike >25: no single Polymarket market with the same definition; polymarket `512321` cut 50: no single Kalshi market with the same definition; polymarket `512320` cut >=75: no single Kalshi market with the same definition; polymarket `512325` hike >=25: no single Kalshi market with the same definition
- **FOMC 2025-03** (Kalshi `KXFEDDECISION-25MAR`, mutually exclusive=True; Polymarket event `15665` negRisk=True): 3 pair(s). Excluded: kalshi `KXFEDDECISION-25MAR-H25` hike 25: no single Polymarket market with the same definition; kalshi `KXFEDDECISION-25MAR-H26` hike >25: no single Polymarket market with the same definition; polymarket `516011` hike >=25: no single Kalshi market with the same definition
- **FOMC 2025-05** (Kalshi `KXFEDDECISION-25MAY`, mutually exclusive=True; Polymarket event `17140` negRisk=True): 3 pair(s). Excluded: kalshi `KXFEDDECISION-25MAY-H25` hike 25: no single Polymarket market with the same definition; kalshi `KXFEDDECISION-25MAY-H26` hike >25: no single Polymarket market with the same definition; polymarket `519784` hike >=25: no single Kalshi market with the same definition
- **FOMC 2025-06** (Kalshi `KXFEDDECISION-25JUN`, mutually exclusive=True; Polymarket event `17792` negRisk=True): 3 pair(s). Excluded: kalshi `KXFEDDECISION-25JUN-H25` hike 25: no single Polymarket market with the same definition; kalshi `KXFEDDECISION-25JUN-H26` hike >25: no single Polymarket market with the same definition; polymarket `521837` hike >=25: no single Kalshi market with the same definition
- **FOMC 2025-07** (Kalshi `KXFEDDECISION-25JUL`, mutually exclusive=True; Polymarket event `21255` negRisk=True): 3 pair(s). Excluded: kalshi `KXFEDDECISION-25JUL-H25` hike 25: no single Polymarket market with the same definition; kalshi `KXFEDDECISION-25JUL-H26` hike >25: no single Polymarket market with the same definition; polymarket `528975` hike >=25: no single Kalshi market with the same definition
- **FOMC 2025-09** (Kalshi `KXFEDDECISION-25SEP`, mutually exclusive=True; Polymarket event `24087` negRisk=True): 3 pair(s). Excluded: kalshi `KXFEDDECISION-25SEP-H25` hike 25: no single Polymarket market with the same definition; kalshi `KXFEDDECISION-25SEP-H26` hike >25: no single Polymarket market with the same definition; polymarket `542540` hike >=25: no single Kalshi market with the same definition
- **FOMC 2025-10** (Kalshi `KXFEDDECISION-25OCT`, mutually exclusive=True; Polymarket event `27824` negRisk=True): 3 pair(s). Excluded: kalshi `KXFEDDECISION-25OCT-H25` hike 25: no single Polymarket market with the same definition; kalshi `KXFEDDECISION-25OCT-H26` hike >25: no single Polymarket market with the same definition; polymarket `553813` hike >=25: no single Kalshi market with the same definition
- **FOMC 2025-12** (Kalshi `KXFEDDECISION-25DEC`, mutually exclusive=True; Polymarket event `35090` negRisk=True): 3 pair(s). Excluded: kalshi `KXFEDDECISION-25DEC-H25` hike 25: no single Polymarket market with the same definition; kalshi `KXFEDDECISION-25DEC-H26` hike >25: no single Polymarket market with the same definition; polymarket `570363` hike >=25: no single Kalshi market with the same definition
- **FOMC 2026-01** (Kalshi `KXFEDDECISION-26JAN`, mutually exclusive=True; Polymarket event `45883` negRisk=True): 3 pair(s). Excluded: kalshi `KXFEDDECISION-26JAN-H25` hike 25: no single Polymarket market with the same definition; kalshi `KXFEDDECISION-26JAN-H26` hike >25: no single Polymarket market with the same definition; polymarket `601700` hike >=25: no single Kalshi market with the same definition
- **FOMC 2026-03** (Kalshi `KXFEDDECISION-26MAR`, mutually exclusive=True; Polymarket event `67284` negRisk=True): 3 pair(s). Excluded: kalshi `KXFEDDECISION-26MAR-H25` hike 25: no single Polymarket market with the same definition; kalshi `KXFEDDECISION-26MAR-H26` hike >25: no single Polymarket market with the same definition; polymarket `654415` hike >=25: no single Kalshi market with the same definition
- **FOMC 2026-04** (Kalshi `KXFEDDECISION-26APR`, mutually exclusive=True; Polymarket event `75478` negRisk=True): 3 pair(s). Excluded: kalshi `KXFEDDECISION-26APR-H25` hike 25: no single Polymarket market with the same definition; kalshi `KXFEDDECISION-26APR-H26` hike >25: no single Polymarket market with the same definition; polymarket `669663` hike >=25: no single Kalshi market with the same definition
- **FOMC 2026-06** (Kalshi `KXFEDDECISION-26JUN`, mutually exclusive=True; Polymarket event `101772` negRisk=True): 5 pair(s). Excluded: none
- **FOMC 2026-07** (Kalshi `KXFEDDECISION-26JUL`, mutually exclusive=True; Polymarket event `287395` negRisk=True): 5 pair(s). Excluded: none
- **FOMC 2026-09** (Kalshi `KXFEDDECISION-26SEP`, mutually exclusive=True; Polymarket event `481717` negRisk=True): 5 pair(s). Excluded: none
- **FOMC 2026-09 (second Polymarket event)** (Kalshi `KXFEDDECISION-26SEP`, mutually exclusive=True; Polymarket event `432066` negRisk=False): 5 pair(s). Excluded: none
- **FOMC 2026-10** (Kalshi `KXFEDDECISION-26OCT`, mutually exclusive=True; Polymarket event `606422` negRisk=True): 5 pair(s). Excluded: none
- **CPI MoM 2024-12 (december-inflation-monthly)** (Kalshi `KXCPI-24DEC`, mutually exclusive=False; Polymarket event `16709` negRisk=True): 1 pair(s). Excluded: polymarket `518385` ≤0.3%: complement of Kalshi KXCPI-24DEC-T0.3 (YES here = NO there); not collected; plus 1 exact-value bucket(s)
- **CPI YoY 2024-12 (december-inflation)** (Kalshi `KXCPIYOY-24DEC`, mutually exclusive=False; Polymarket event `15381` negRisk=True): 1 pair(s). Excluded: polymarket `515385` ≤2.6%: complement of Kalshi KXCPIYOY-24DEC-T2.6 (YES here = NO there); not collected; plus 2 exact-value bucket(s)
- **CPI MoM 2025-01 (january-inflation-monthly)** (Kalshi `KXCPI-25JAN`, mutually exclusive=False; Polymarket event `16790` negRisk=True): 1 pair(s). Excluded: polymarket `518699` ≤0.1%: complement of Kalshi KXCPI-25JAN-T0.1 (YES here = NO there); not collected; plus 2 exact-value bucket(s)
- **CPI YoY 2025-01 (january-inflation-annual)** (Kalshi `KXCPIYOY-25JAN`, mutually exclusive=False; Polymarket event `16808` negRisk=True): 1 pair(s). Excluded: polymarket `518808` ≤2.6%: complement of Kalshi KXCPIYOY-25JAN-T2.6 (YES here = NO there); not collected; plus 2 exact-value bucket(s)
- **CPI MoM 2025-02 (february-inflation-monthly)** (Kalshi `KXCPI-25FEB`, mutually exclusive=False; Polymarket event `17894` negRisk=True): 1 pair(s). Excluded: polymarket `522188` ≤0.1%: complement of Kalshi KXCPI-25FEB-T0.1 (YES here = NO there); not collected; plus 3 exact-value bucket(s)
- **CPI YoY 2025-02 (february-inflation-annual)** (Kalshi `KXCPIYOY-25FEB`, mutually exclusive=False; Polymarket event `17892` negRisk=True): 1 pair(s). Excluded: polymarket `522182` ≤2.7%: complement of Kalshi KXCPIYOY-25FEB-T2.7 (YES here = NO there); not collected; plus 3 exact-value bucket(s)
- **CPI MoM 2025-03 (march-inflation-monthly)** (Kalshi `KXCPI-25MAR`, mutually exclusive=False; Polymarket event `20808` negRisk=True): 0 pair(s). Excluded: polymarket `527838` ≤0.1%: complement of Kalshi KXCPI-25MAR-T0.1 (YES here = NO there); not collected; polymarket `527842` ≥0.5%: no Kalshi 'Above 0.4%' market; plus 3 exact-value bucket(s)
- **CPI YoY 2025-03 (march-inflation-annual)** (Kalshi `KXCPIYOY-25MAR`, mutually exclusive=False; Polymarket event `20809` negRisk=True): 1 pair(s). Excluded: polymarket `527843` ≤2.4%: complement of Kalshi KXCPIYOY-25MAR-T2.4 (YES here = NO there); not collected; plus 3 exact-value bucket(s)
- **CPI MoM 2025-04 (april-inflation-monthly)** (Kalshi `KXCPI-25APR`, mutually exclusive=False; Polymarket event `22581` negRisk=True): 1 pair(s). Excluded: polymarket `535925` ≤0.1%: complement of Kalshi KXCPI-25APR-T0.1 (YES here = NO there); not collected; plus 3 exact-value bucket(s)
- **CPI YoY 2025-04 (april-inflation-annual)** (Kalshi `KXCPIYOY-25APR`, mutually exclusive=False; Polymarket event `22582` negRisk=True): 1 pair(s). Excluded: polymarket `535930` ≤2.3%: complement of Kalshi KXCPIYOY-25APR-T2.3 (YES here = NO there); not collected; plus 3 exact-value bucket(s)
- **CPI MoM 2025-05 (may-inflation-monthly)** (Kalshi `KXCPI-25MAY`, mutually exclusive=False; Polymarket event `24432` negRisk=True): 1 pair(s). Excluded: polymarket `544340` ≤0.0%: complement of Kalshi KXCPI-25MAY-T0.0 (YES here = NO there); not collected; plus 3 exact-value bucket(s)
- **CPI YoY 2025-05 (may-inflation-annual)** (Kalshi `KXCPIYOY-25MAY`, mutually exclusive=False; Polymarket event `24433` negRisk=True): 1 pair(s). Excluded: polymarket `544345` ≤2.2%: complement of Kalshi KXCPIYOY-25MAY-T2.2 (YES here = NO there); not collected; plus 3 exact-value bucket(s)
- **CPI MoM 2025-06 (june-inflation-monthly)** (Kalshi `KXCPI-25JUN`, mutually exclusive=False; Polymarket event `26717` negRisk=True): 1 pair(s). Excluded: polymarket `551579` ≤0.0%: complement of Kalshi KXCPI-25JUN-T0.0 (YES here = NO there); not collected; plus 3 exact-value bucket(s)
- **CPI YoY 2025-06 (june-inflation-annual)** (Kalshi `KXCPIYOY-25JUN`, mutually exclusive=False; Polymarket event `26718` negRisk=True): 1 pair(s). Excluded: polymarket `551584` ≤2.2%: no Kalshi 'Above 2.2%' market; plus 3 exact-value bucket(s)
- **CPI MoM 2025-07 (july-inflation-monthly)** (Kalshi `KXCPI-25JUL`, mutually exclusive=False; Polymarket event `32575` negRisk=True): 1 pair(s). Excluded: polymarket `563690` ≤0.0%: complement of Kalshi KXCPI-25JUL-T0.0 (YES here = NO there); not collected; plus 4 exact-value bucket(s)
- **CPI YoY 2025-07 (july-inflation-annual-462)** (Kalshi `KXCPIYOY-25JUL`, mutually exclusive=False; Polymarket event `32581` negRisk=True): 1 pair(s). Excluded: polymarket `563705` ≤2.6%: complement of Kalshi KXCPIYOY-25JUL-T2.6 (YES here = NO there); not collected; plus 3 exact-value bucket(s)
- **CPI MoM 2025-08 (august-inflation-monthly)** (Kalshi `KXCPI-25AUG`, mutually exclusive=False; Polymarket event `37171` negRisk=True): 1 pair(s). Excluded: polymarket `575238` ≤0.0%: complement of Kalshi KXCPI-25AUG-T0.0 (YES here = NO there); not collected; plus 3 exact-value bucket(s)
- **CPI YoY 2025-08 (august-inflation-annual)** (Kalshi `KXCPIYOY-25AUG`, mutually exclusive=False; Polymarket event `37170` negRisk=True): 1 pair(s). Excluded: polymarket `575233` ≤2.6%: complement of Kalshi KXCPIYOY-25AUG-T2.6 (YES here = NO there); not collected; plus 3 exact-value bucket(s)
- **CPI MoM 2025-09 (september-inflation-monthly)** (Kalshi `KXCPI-25SEP`, mutually exclusive=False; Polymarket event `43393` negRisk=True): 0 pair(s). Excluded: pair Kalshi `KXCPI-25SEP-T0.4` / Polymarket `594157` (≥0.5% == Kalshi Above 0.4%): **definitions diverge under non-release; NOT the same question**; polymarket `594153` ≤0.1%: complement of Kalshi KXCPI-25SEP-T0.1 (YES here = NO there); not collected; plus 3 exact-value bucket(s)
- **CPI YoY 2025-09 (september-inflation-annual)** (Kalshi `KXCPIYOY-25SEP`, mutually exclusive=False; Polymarket event `43395` negRisk=True): 0 pair(s). Excluded: polymarket `594317` ≤2.9%: complement of Kalshi KXCPIYOY-25SEP-T2.9 (YES here = NO there); not collected; polymarket `594320` ≥3.3%: no Kalshi 'Above 3.2%' market; plus 3 exact-value bucket(s)
- **CPI MoM 2025-10 (october-inflation-monthly)** (Kalshi `KXCPI-25OCT`, mutually exclusive=False; Polymarket event `67929` negRisk=True): 0 pair(s). Excluded: pair Kalshi `KXCPI-25OCT-T0.4` / Polymarket `655625` (≥0.5% == Kalshi Above 0.4%): **definitions diverge under non-release; NOT the same question**; polymarket `655621` ≤0.1%: complement of Kalshi KXCPI-25OCT-T0.1 (YES here = NO there); not collected; plus 3 exact-value bucket(s)
- **CPI YoY 2025-10 (october-inflation-annual)** (Kalshi `KXCPIYOY-25OCT`, mutually exclusive=False; Polymarket event `67280` negRisk=True): 0 pair(s). Excluded: pair Kalshi `KXCPIYOY-25OCT-T3.1` / Polymarket `654401` (≥3.2% == Kalshi Above 3.1%): **definitions diverge under non-release; NOT the same question**; polymarket `654397` ≤2.8%: complement of Kalshi KXCPIYOY-25OCT-T2.8 (YES here = NO there); not collected; plus 3 exact-value bucket(s)
- **CPI MoM 2025-11 (november-inflation-monthly)** (Kalshi `KXCPI-25NOV`, mutually exclusive=False; Polymarket event `80638` negRisk=True): 0 pair(s). Excluded: polymarket `680561` ≤0.1%: complement of Kalshi KXCPI-25NOV-T0.1 (YES here = NO there); not collected; polymarket `680565` ≥0.5%: no Kalshi 'Above 0.4%' market; plus 3 exact-value bucket(s)
- **CPI YoY 2025-11 (november-inflation-annual)** (Kalshi `KXCPIYOY-25NOV`, mutually exclusive=False; Polymarket event `80636` negRisk=True): 1 pair(s). Excluded: polymarket `680533` ≤2.8%: complement of Kalshi KXCPIYOY-25NOV-T2.8 (YES here = NO there); not collected; plus 3 exact-value bucket(s)
- **CPI MoM 2025-12 (december-inflation-us-monthly)** (Kalshi `KXCPI-25DEC`, mutually exclusive=False; Polymarket event `97910` negRisk=True): 1 pair(s). Excluded: polymarket `833215` ≤0.1%: complement of Kalshi KXCPI-25DEC-T0.1 (YES here = NO there); not collected; plus 3 exact-value bucket(s)
- **CPI YoY 2025-12 (december-inflation-us-annual)** (Kalshi `KXCPIYOY-25DEC`, mutually exclusive=False; Polymarket event `97909` negRisk=True): 1 pair(s). Excluded: polymarket `833210` ≤2.8%: complement of Kalshi KXCPIYOY-25DEC-T2.8 (YES here = NO there); not collected; plus 3 exact-value bucket(s)
- **CPI MoM 2026-01 (january-inflation-us-monthly)** (Kalshi `KXCPI-26JAN`, mutually exclusive=False; Polymarket event `111039` negRisk=True): 1 pair(s). Excluded: polymarket `969645` ≤0.1%: complement of Kalshi KXCPI-26JAN-T0.1 (YES here = NO there); not collected; plus 3 exact-value bucket(s)
- **CPI YoY 2026-01 (january-inflation-us-annual)** (Kalshi `KXCPIYOY-26JAN`, mutually exclusive=False; Polymarket event `111050` negRisk=True): 1 pair(s). Excluded: polymarket `969660` ≤2.8%: complement of Kalshi KXCPIYOY-26JAN-T2.8 (YES here = NO there); not collected; plus 3 exact-value bucket(s)
- **CPI YoY 2026-01 (january-inflation-us-annual-lower-brackets-817)** (Kalshi `KXCPIYOY-26JAN`, mutually exclusive=False; Polymarket event `164580` negRisk=True): 1 pair(s). Excluded: polymarket `1185716` ≤2.1%: complement of Kalshi KXCPIYOY-26JAN-T2.1 (YES here = NO there); not collected; plus 5 exact-value bucket(s)
- **CPI MoM 2026-02 (february-inflation-us-monthly-231)** (Kalshi `KXCPI-26FEB`, mutually exclusive=False; Polymarket event `207993` negRisk=True): 1 pair(s). Excluded: polymarket `1373674` ≤0.0%: complement of Kalshi KXCPI-26FEB-T0.0 (YES here = NO there); not collected; plus 3 exact-value bucket(s)
- **CPI YoY 2026-02 (february-inflation-us-annual)** (Kalshi `KXCPIYOY-26FEB`, mutually exclusive=False; Polymarket event `207936` negRisk=True): 1 pair(s). Excluded: polymarket `1373473` ≤2.1%: no Kalshi 'Above 2.1%' market; plus 5 exact-value bucket(s)
- **CPI MoM 2026-03 (march-inflation-us-monthly)** (Kalshi `KXCPI-26MAR`, mutually exclusive=False; Polymarket event `261184` negRisk=True): 1 pair(s). Excluded: polymarket `1559150` ≤0.3%: complement of Kalshi KXCPI-26MAR-T0.3 (YES here = NO there); not collected; plus 4 exact-value bucket(s)
- **CPI YoY 2026-03 (march-inflation-us-annual)** (Kalshi `KXCPIYOY-26MAR`, mutually exclusive=False; Polymarket event `208170` negRisk=True): 1 pair(s). Excluded: polymarket `1374255` ≤2.0%: complement of Kalshi KXCPIYOY-26MAR-T2.0 (YES here = NO there); not collected; plus 7 exact-value bucket(s)
- **CPI YoY 2026-03 (march-inflation-us-annual-higher-brackets)** (Kalshi `KXCPIYOY-26MAR`, mutually exclusive=False; Polymarket event `261155` negRisk=True): 1 pair(s). Excluded: polymarket `1559109` ≤2.6%: complement of Kalshi KXCPIYOY-26MAR-T2.6 (YES here = NO there); not collected; plus 7 exact-value bucket(s)
- **CPI MoM 2026-04 (april-inflation-us-monthly)** (Kalshi `KXCPI-26APR`, mutually exclusive=False; Polymarket event `364618` negRisk=True): 1 pair(s). Excluded: polymarket `1937988` ≤0.3%: complement of Kalshi KXCPI-26APR-T0.3 (YES here = NO there); not collected; plus 7 exact-value bucket(s)
- **CPI YoY 2026-04 (april-inflation-us-annual)** (Kalshi `KXCPIYOY-26APR`, mutually exclusive=False; Polymarket event `364599` negRisk=True): 1 pair(s). Excluded: polymarket `1937952` ≤3.1%: complement of Kalshi KXCPIYOY-26APR-T3.1 (YES here = NO there); not collected; plus 9 exact-value bucket(s)
- **CPI MoM 2026-05 (may-inflation-us-monthly)** (Kalshi `KXCPI-26MAY`, mutually exclusive=False; Polymarket event `477898` negRisk=True): 1 pair(s). Excluded: polymarket `2242045` ≤0.1%: complement of Kalshi KXCPI-26MAY-T0.1 (YES here = NO there); not collected; plus 7 exact-value bucket(s)
- **CPI YoY 2026-05 (may-inflation-us-annual)** (Kalshi `KXCPIYOY-26MAY`, mutually exclusive=False; Polymarket event `477999` negRisk=True): 1 pair(s). Excluded: polymarket `2242373` ≤3.3%: complement of Kalshi KXCPIYOY-26MAY-T3.3 (YES here = NO there); not collected; plus 10 exact-value bucket(s)
- **CPI MoM 2026-06 (june-inflation-us-monthly-20260610151033433)** (Kalshi `KXCPI-26JUN`, mutually exclusive=False; Polymarket event `580295` negRisk=True): 0 pair(s). Excluded: polymarket `2491383` ≤0.1%: complement of Kalshi KXCPI-26JUN-T0.1 (YES here = NO there); not collected; polymarket `2491391` ≥0.9%: no Kalshi 'Above 0.8%' market; plus 7 exact-value bucket(s)
- **CPI YoY 2026-06 (june-inflation-us-annual-20260610151727862)** (Kalshi `KXCPIYOY-26JUN`, mutually exclusive=False; Polymarket event `580294` negRisk=True): 0 pair(s). Excluded: polymarket `2491371` ≤3.6%: complement of Kalshi KXCPIYOY-26JUN-T3.6 (YES here = NO there); not collected; polymarket `2491382` ≥4.7%: no Kalshi 'Above 4.6%' market; plus 10 exact-value bucket(s)
- **CPI MoM 2026-07 (july-inflation-us-monthly-20260714151042665)** (Kalshi `KXCPI-26JUL`, mutually exclusive=False; Polymarket event `703588` negRisk=True): 1 pair(s). Excluded: polymarket `2925098` ≤-0.7%: no Kalshi 'Above -0.7%' market; plus 7 exact-value bucket(s)
- **CPI YoY 2026-07 (july-inflation-us-annual-20260714150613267)** (Kalshi `KXCPIYOY-26JUL`, mutually exclusive=False; Polymarket event `703573` negRisk=True): 1 pair(s). Excluded: polymarket `2925072` ≤3.1%: complement of Kalshi KXCPIYOY-26JUL-T3.1 (YES here = NO there); not collected; plus 10 exact-value bucket(s)
- **CPI MoM 2026-08 (august-inflation-us-monthly-1786474662954)** (Kalshi `KXCPI-26AUG`, mutually exclusive=False; Polymarket event `838709` negRisk=True): 1 pair(s). Excluded: polymarket `3539660` ≤-0.3%: complement of Kalshi KXCPI-26AUG-T-0.3 (YES here = NO there); not collected; plus 7 exact-value bucket(s)
- **CPI YoY 2026-08 (august-inflation-us-annual-1786474662954)** (Kalshi `KXCPIYOY-26AUG`, mutually exclusive=False; Polymarket event `838710` negRisk=True): 1 pair(s). Excluded: polymarket `3539669` ≤2.9%: complement of Kalshi KXCPIYOY-26AUG-T2.9 (YES here = NO there); not collected; plus 10 exact-value bucket(s)
- **CPI MoM 2026-09 (september-inflation-us-monthly)** (Kalshi `KXCPI-26SEP`, mutually exclusive=False; Polymarket event `1005014` negRisk=True): 1 pair(s). Excluded: polymarket `4469455` ≤0.0%: complement of Kalshi KXCPI-26SEP-T0.0 (YES here = NO there); not collected; plus 7 exact-value bucket(s)
- **CPI YoY 2026-09 (september-inflation-us-annual)** (Kalshi `KXCPIYOY-26SEP`, mutually exclusive=False; Polymarket event `1005013` negRisk=True): 1 pair(s). Excluded: polymarket `4469383` ≤2.9%: no Kalshi 'Above 2.9%' market; plus 10 exact-value bucket(s)
- **CPI MoM 2026-10 (october-inflation-us-monthly)** (Kalshi `KXCPI-26OCT`, mutually exclusive=False; Polymarket event `1189083` negRisk=True): 1 pair(s). Excluded: polymarket `5691223` ≤0.1%: complement of Kalshi KXCPI-26OCT-T0.1 (YES here = NO there); not collected; plus 7 exact-value bucket(s)
- **CPI YoY 2026-10 (october-inflation-us-annual)** (Kalshi event `KXCPIYOY-26OCT` **not found** (HTTP 404, no markets); Polymarket event `1189074` negRisk=True): 0 pair(s). Excluded: polymarket `5691083` ≤3.2%: no Kalshi 'Above 3.2%' market; polymarket `5691094` ≥4.3%: no Kalshi 'Above 4.2%' market; plus 10 exact-value bucket(s)


## What is NOT verified

- That each pair's full settlement rules are identical on both venues. Titles, questions, the Kalshi
  `rules_primary` sentence, and a keyword search for non-release and FOMC edge-case clauses were compared;
  the full texts were not compared line by line. #20 must read both rule texts.
- Kalshi CPI YoY for October 2026: Kalshi event `KXCPIYOY-26OCT` was not found (`GET /events/KXCPIYOY-26OCT`
  returned 404 and the `KXCPIYOY` series listing has no such event), so that month has no YoY pair.
- Whether Polymarket CLOB `p` is a midpoint or a last trade (undocumented), and why some Kalshi windows have
  fewer candles than hours.
- Completeness of discovery: Polymarket events were found by search and tag listing; an event with an unusual
  slug or tag may be missing. The April 2025 CPI MoM event (`22581`) was found only through its slug.
- Nothing here checks how a market resolved, by design.
