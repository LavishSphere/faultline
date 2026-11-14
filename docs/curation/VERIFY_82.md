# VERIFY_82: finance owner's check of the #82 CPI evidence

**Status: admitted on an independent AI re-check that the finance owner requested, NOT a manual human check.**
On 2026-11-14 Yaseen (finance owner, #82) asked Claude Code to complete this check. A separate read-only auditor agent,
which did not build these cases, re-checked all 49 rows, the rule application for all 23 prints and the flagged points
with its own code: everything passed. The row boxes record that AI re-check, **not** that Yaseen opened each page
himself. Yaseen accepted the Part 4 rule and the 13/10 split himself (sign-off below). Same approach as #67, which the
lead accepted together with an independent audit.

The 13 new cases are `services/api/data/demo_cases/cpi-2025-{jan,feb,apr,may,jun,jul,aug}.json` and
`cpi-2026-{feb,mar,may,jul,aug,sep}.json`. A case id names the **reference month** (`cpi-2025-jan` = January 2025
CPI, released February 12, 2025). The rule that picked them, and every print it yields (included or excluded, with
the reason), is in `docs/CASES.md` Part 4.

This file contains no CPI result. Please keep it that way: write no printed figure, no "it came in above/below", and
no after-the-fact coverage here, in a commit message or in a PR comment.

## What the agent already checked (by code, 2026-11-14)

For every one of the 49 items below:
- the excerpt is taken mechanically by `docs/CASES.md` Part 4 rule 9 (the CPI, statement and minutes excerpts use
  the same extraction code as #54/#67);
- `available_at` is before `as_of`. BLS: "embargoed until 8:30 a.m. (ET)" on the release, converted with US
  daylight-saving dates. Fed: "For release at 2:00 p.m. EST/EDT" on the document. Cleveland Fed nowcast: the
  archive capture time (the file's own update stamp has no time zone, so the later, verifiable time is used);
- the archive capture listed was taken before `as_of`, it was downloaded, and every excerpt paragraph was found in
  it word for word (after whitespace normalization);
- Federal Reserve pages were also fetched live (HTTP 200): 26 items (13 statements, 13 minutes). Live BLS pages
  return HTTP 403 to automated requests (rechecked 2026-11-14), so the 13 BLS items come only from archive captures:
  the permanent archive URL, corroborated by the BLS current-release page captured before `as_of`. The 10 Cleveland
  Fed items are archive-only too: the live data file shows today's charts, not the historical one;
- the BLS release used is the one the last pre-`as_of` capture of the BLS current-release page showed (linked under
  each table), and in all 13 cases it is the previous month's CPI;
- leak check: no item is the reference month's own release; no item contains that release's title line or any of
  its opening paragraphs; each Cleveland Fed capture had an empty "Actual CPI Inflation" value for the reference
  month;
- market quotes: only from the saved #66 snapshots (bytes from git, SHA-256 checked against each manifest), through
  the repo parsers, `normalize_quotes` and `select_quote`.

The agent cannot stand in for the human check the issue asks for, and nothing here was admitted on the agent's word.

## How to check one row (about 2 minutes each)

1. **Source ok:** open the source URL. Confirm the title matches the document and that it is the official page
   (bls.gov, federalreserve.gov or clevelandfed.org). BLS may block the live page; if it does, use the archive link.
2. **Capture before `as_of`:** open the archive URL. The 14-digit number after `/web/` is the capture time in UTC
   (YYYYMMDDhhmmss). Confirm it is earlier than the case's `as_of` and that the page shows the same document.
3. **No leak:** read the excerpt in the case file (`evidence[].content`). Confirm it says nothing about the CPI figure
   for the case's own month. The previous month's CPI release is allowed: it was public before `as_of`.

Tick the three boxes in the row. If any box fails, write the problem next to the row and do not tick it. Under
Part 4 rule 11 a case with fewer than 3 confirmed items is excluded, and that must be recorded in `docs/CASES.md`.
Three cases (`cpi-2025-may`, `cpi-2025-jun`, `cpi-2025-aug`) have exactly 3 items, so one failed row excludes them.

## Points that need a closer look

- **The rule itself (Part 4).** Please confirm you accept: month-over-month only (the reasons are in rule 3); the
  top bucket as the one question per print; `as_of` = 00:00 UTC seven days before the BLS release; and the 13
  inclusions and 10 exclusions in the table in `docs/CASES.md` Part 4.
- **Same question on both venues.** Each case's `curation_notes.market.venue_rule_differences` says why Polymarket
  "b% or more" equals Kalshi "Above (b - 0.1)%". The Kalshi `KXCPI` contract terms
  (https://assets.kalshi.com/contract_terms/CPI.pdf) define the Underlying as the one-month, one-decimal change in
  the seasonally adjusted CPI-U, first published, with payout "strictly greater than" the level. The agent read
  today's version of that PDF; please check one Kalshi market page and one Polymarket market page for a 2025 case.
- **`cpi-2026-may` market quote.** #66's table shows the Kalshi leg as NOT AVAILABLE, because #66 used
  `as_of` = scheduled close - 7 days (2026-06-03T08:00Z). Part 4 uses 00:00Z on that day (2026-06-03T00:00Z), and
  the saved snapshot has a trade candle at 2026-06-02T06:00Z inside that 24-hour window. Please confirm you accept
  this. It is the only case where the Kalshi quote is a single trade candle (bid 0.0000, ask 0.0300).
- **`cpi-2025-feb` close mismatch.** Polymarket's market `522192` lists an end date of 2025-03-31, 19 days after the
  release. #66 used the Kalshi close (2025-03-12, the release date) for both windows. Please confirm the Polymarket
  market was about the February 2025 print released on March 12.
- **Cleveland Fed nowcast captures can be stale.** Rule 9.4 takes the latest capture before `as_of`. For
  `cpi-2025-jan` that capture is from 2025-01-13 (23 days before `as_of`), so it shows the nowcast as of 2025-01-10,
  not the latest one that existed at `as_of`. Three 2025 cases have no usable capture and so only 3 items. The
  nowcast is a forecast, not a fact; please confirm it is labelled that way in each case
  (`curation_notes.evidence_classification`).
- **CPI excerpts with a boxed notice (`cpi-2025-feb`, `cpi-2025-may`, `cpi-2025-aug`).** As in #67, rule 9.1 takes
  every paragraph before "Table A.", so BLS's methodology box is included verbatim, dashed borders included. Please
  confirm the box says nothing about the month being forecast.
- **Cross-case visibility.** Each case's first item is the previous month's CPI release, which settles the previous
  CPI case (for example `cpi-2025-feb` contains the release that settles `cpi-2025-jan`). The FOMC cases from #67
  also contain CPI releases that settle CPI cases (for example `fomc-2025-mar` contains the January 2025 CPI
  release). All forecasts must be run before any reveal (`docs/CASES.md` Part 4).
- **Sealed results.** Written last, from each month's own BLS release (archive copy; live bls.gov returned 403). The
  agent printed only ok/mismatch: for all 13, the release date matched the case, the first sentence and Table A
  agreed, and the two venue rules gave the same answer. Please open two sealed files of your choice and compare them
  with the BLS release yourself. Do this **after** the evidence check above, and do not write what you saw here.

## Items to confirm (49)

### `cpi-2025-jan` (January 2025 CPI, released 2025-02-12; `as_of` 2025-02-05T00:00:00Z)

| # | Title | Source URL | Archive URL (capture time, UTC) | `available_at` | Does not leak the print because... | Check |
|---|---|---|---|---|---|---|
| 1 | BLS news release: Consumer Price Index - December 2024 (verbatim excerpt: opening summary paragraphs) | https://www.bls.gov/news.release/archives/cpi_01152025.htm | https://web.archive.org/web/20250202050707/https://www.bls.gov/news.release/archives/cpi_01152025.htm (2025-02-02T05:07:07Z) | 2025-01-15T13:30:00Z (EST) | It is the CPI release for an earlier month, public since 2025-01-15; it does not contain the January 2025 figure. | [x] source ok [x] capture before `as_of` [x] no leak (AI re-check) |
| 2 | Federal Reserve issues FOMC statement (January 29, 2025; full statement text) | https://www.federalreserve.gov/newsevents/pressreleases/monetary20250129a.htm | https://web.archive.org/web/20250204212643/https://www.federalreserve.gov/newsevents/pressreleases/monetary20250129a.htm (2025-02-04T21:26:43Z) | 2025-01-29T19:00:00Z (EST) | FOMC statement released 2025-01-29, before the January 2025 CPI release; the Fed does not publish CPI figures ahead of BLS. | [x] source ok [x] capture before `as_of` [x] no leak (AI re-check) |
| 3 | Minutes of the Federal Open Market Committee, December 17-18, 2024 (verbatim excerpt: paragraphs containing 'outlook for monetary policy') | https://www.federalreserve.gov/monetarypolicy/fomcminutes20241218.htm | https://web.archive.org/web/20250202200434/https://www.federalreserve.gov/monetarypolicy/fomcminutes20241218.htm (2025-02-02T20:04:34Z) | 2025-01-08T19:00:00Z (EST) | FOMC minutes released 2025-01-08; they summarise a meeting held weeks before the January 2025 CPI release. | [x] source ok [x] capture before `as_of` [x] no leak (AI re-check) |
| 4 | Federal Reserve Bank of Cleveland Inflation Nowcasting: month-over-month CPI nowcast for January 2025 (verbatim values from the archived data file nowcast_month.json) | https://www.clevelandfed.org/-/media/files/webcharts/inflationnowcasting/nowcast_month.json?sc_lang=en&_=1736732914354 | https://web.archive.org/web/20250113014836/https://www.clevelandfed.org/-/media/files/webcharts/inflationnowcasting/nowcast_month.json?sc_lang=en&_=1736732914354 (2025-01-13T01:48:36Z) | 2025-01-13T01:48:36Z (capture time) | A model estimate captured 2025-01-13, before the release; the capture's 'Actual CPI' values for January 2025 were empty (checked by code). | [x] source ok [x] capture before `as_of` [x] no leak (AI re-check) |

BLS release current at `as_of`, read from the last pre-`as_of` capture of the BLS current-release page: CONSUMER PRICE INDEX - DECEMBER 2024 (https://web.archive.org/web/20250204141829/https://www.bls.gov/news.release/cpi.nr0.htm). Minutes release time from the Fed press release https://www.federalreserve.gov/newsevents/pressreleases/monetary20250108a.htm.

### `cpi-2025-feb` (February 2025 CPI, released 2025-03-12; `as_of` 2025-03-05T00:00:00Z)

| # | Title | Source URL | Archive URL (capture time, UTC) | `available_at` | Does not leak the print because... | Check |
|---|---|---|---|---|---|---|
| 1 | BLS news release: Consumer Price Index - January 2025 (verbatim excerpt: opening summary paragraphs) | https://www.bls.gov/news.release/archives/cpi_02122025.htm | https://web.archive.org/web/20250304113507/https://www.bls.gov/news.release/archives/cpi_02122025.htm (2025-03-04T11:35:07Z) | 2025-02-12T13:30:00Z (EST) | It is the CPI release for an earlier month, public since 2025-02-12; it does not contain the February 2025 figure. | [x] source ok [x] capture before `as_of` [x] no leak (AI re-check) |
| 2 | Federal Reserve issues FOMC statement (January 29, 2025; full statement text) | https://www.federalreserve.gov/newsevents/pressreleases/monetary20250129a.htm | https://web.archive.org/web/20250304223124/https://www.federalreserve.gov/newsevents/pressreleases/monetary20250129a.htm (2025-03-04T22:31:24Z) | 2025-01-29T19:00:00Z (EST) | FOMC statement released 2025-01-29, before the February 2025 CPI release; the Fed does not publish CPI figures ahead of BLS. | [x] source ok [x] capture before `as_of` [x] no leak (AI re-check) |
| 3 | Minutes of the Federal Open Market Committee, January 28-29, 2025 (verbatim excerpt: paragraphs containing 'outlook for monetary policy') | https://www.federalreserve.gov/monetarypolicy/fomcminutes20250129.htm | https://web.archive.org/web/20250224233403/https://www.federalreserve.gov/monetarypolicy/fomcminutes20250129.htm (2025-02-24T23:34:03Z) | 2025-02-19T19:00:00Z (EST) | FOMC minutes released 2025-02-19; they summarise a meeting held weeks before the February 2025 CPI release. | [x] source ok [x] capture before `as_of` [x] no leak (AI re-check) |
| 4 | Federal Reserve Bank of Cleveland Inflation Nowcasting: month-over-month CPI nowcast for February 2025 (verbatim values from the archived data file nowcast_month.json) | https://www.clevelandfed.org/-/media/files/webcharts/inflationnowcasting/nowcast_month.json?sc_lang=en&_=1739606410116 | https://web.archive.org/web/20250215080013/https://www.clevelandfed.org/-/media/files/webcharts/inflationnowcasting/nowcast_month.json?sc_lang=en&_=1739606410116 (2025-02-15T08:00:13Z) | 2025-02-15T08:00:13Z (capture time) | A model estimate captured 2025-02-15, before the release; the capture's 'Actual CPI' values for February 2025 were empty (checked by code). | [x] source ok [x] capture before `as_of` [x] no leak (AI re-check) |

BLS release current at `as_of`, read from the last pre-`as_of` capture of the BLS current-release page: CONSUMER PRICE INDEX - JANUARY 2025 (https://web.archive.org/web/20250304235642/https://www.bls.gov/news.release/cpi.nr0.htm). Minutes release time from the Fed press release https://www.federalreserve.gov/newsevents/pressreleases/monetary20250219a.htm.

### `cpi-2025-apr` (April 2025 CPI, released 2025-05-13; `as_of` 2025-05-06T00:00:00Z)

| # | Title | Source URL | Archive URL (capture time, UTC) | `available_at` | Does not leak the print because... | Check |
|---|---|---|---|---|---|---|
| 1 | BLS news release: Consumer Price Index - March 2025 (verbatim excerpt: opening summary paragraphs) | https://www.bls.gov/news.release/archives/cpi_04102025.htm | https://web.archive.org/web/20250428021424/https://www.bls.gov/news.release/archives/cpi_04102025.htm (2025-04-28T02:14:24Z) | 2025-04-10T12:30:00Z (EDT) | It is the CPI release for an earlier month, public since 2025-04-10; it does not contain the April 2025 figure. | [x] source ok [x] capture before `as_of` [x] no leak (AI re-check) |
| 2 | Federal Reserve issues FOMC statement (March 19, 2025; full statement text) | https://www.federalreserve.gov/newsevents/pressreleases/monetary20250319a.htm | https://web.archive.org/web/20250503000024/https://www.federalreserve.gov/newsevents/pressreleases/monetary20250319a.htm (2025-05-03T00:00:24Z) | 2025-03-19T18:00:00Z (EDT) | FOMC statement released 2025-03-19, before the April 2025 CPI release; the Fed does not publish CPI figures ahead of BLS. | [x] source ok [x] capture before `as_of` [x] no leak (AI re-check) |
| 3 | Minutes of the Federal Open Market Committee, March 18-19, 2025 (verbatim excerpt: paragraphs containing 'outlook for monetary policy') | https://www.federalreserve.gov/monetarypolicy/fomcminutes20250319.htm | https://web.archive.org/web/20250422131304/https://www.federalreserve.gov/monetarypolicy/fomcminutes20250319.htm (2025-04-22T13:13:04Z) | 2025-04-09T18:00:00Z (EDT) | FOMC minutes released 2025-04-09; they summarise a meeting held weeks before the April 2025 CPI release. | [x] source ok [x] capture before `as_of` [x] no leak (AI re-check) |
| 4 | Federal Reserve Bank of Cleveland Inflation Nowcasting: month-over-month CPI nowcast for April 2025 (verbatim values from the archived data file nowcast_month.json) | https://www.clevelandfed.org/-/media/files/webcharts/inflationnowcasting/nowcast_month.json?sc_lang=en&_=1666959578504 | https://web.archive.org/web/20250415233207/https://www.clevelandfed.org/-/media/files/webcharts/inflationnowcasting/nowcast_month.json?sc_lang=en&_=1666959578504 (2025-04-15T23:32:07Z) | 2025-04-15T23:32:07Z (capture time) | A model estimate captured 2025-04-15, before the release; the capture's 'Actual CPI' values for April 2025 were empty (checked by code). | [x] source ok [x] capture before `as_of` [x] no leak (AI re-check) |

BLS release current at `as_of`, read from the last pre-`as_of` capture of the BLS current-release page: CONSUMER PRICE INDEX - MARCH 2025 (https://web.archive.org/web/20250504192623/https://www.bls.gov/news.release/cpi.nr0.htm). Minutes release time from the Fed press release https://www.federalreserve.gov/newsevents/pressreleases/monetary20250409a.htm.

### `cpi-2025-may` (May 2025 CPI, released 2025-06-11; `as_of` 2025-06-04T00:00:00Z)

| # | Title | Source URL | Archive URL (capture time, UTC) | `available_at` | Does not leak the print because... | Check |
|---|---|---|---|---|---|---|
| 1 | BLS news release: Consumer Price Index - April 2025 (verbatim excerpt: opening summary paragraphs) | https://www.bls.gov/news.release/archives/cpi_05132025.htm | https://web.archive.org/web/20250522021145/https://www.bls.gov/news.release/archives/cpi_05132025.htm (2025-05-22T02:11:45Z) | 2025-05-13T12:30:00Z (EDT) | It is the CPI release for an earlier month, public since 2025-05-13; it does not contain the May 2025 figure. | [x] source ok [x] capture before `as_of` [x] no leak (AI re-check) |
| 2 | Federal Reserve issues FOMC statement (May 7, 2025; full statement text) | https://www.federalreserve.gov/newsevents/pressreleases/monetary20250507a.htm | https://web.archive.org/web/20250524072655/https://www.federalreserve.gov/newsevents/pressreleases/monetary20250507a.htm (2025-05-24T07:26:55Z) | 2025-05-07T18:00:00Z (EDT) | FOMC statement released 2025-05-07, before the May 2025 CPI release; the Fed does not publish CPI figures ahead of BLS. | [x] source ok [x] capture before `as_of` [x] no leak (AI re-check) |
| 3 | Minutes of the Federal Open Market Committee, May 6-7, 2025 (verbatim excerpt: paragraphs containing 'outlook for monetary policy') | https://www.federalreserve.gov/monetarypolicy/fomcminutes20250507.htm | https://web.archive.org/web/20250602102115/https://www.federalreserve.gov/monetarypolicy/fomcminutes20250507.htm (2025-06-02T10:21:15Z) | 2025-05-28T18:00:00Z (EDT) | FOMC minutes released 2025-05-28; they summarise a meeting held weeks before the May 2025 CPI release. | [x] source ok [x] capture before `as_of` [x] no leak (AI re-check) |

BLS release current at `as_of`, read from the last pre-`as_of` capture of the BLS current-release page: CONSUMER PRICE INDEX - APRIL 2025 (https://web.archive.org/web/20250602061554/https://www.bls.gov/news.release/cpi.nr0.htm). Minutes release time from the Fed press release https://www.federalreserve.gov/newsevents/pressreleases/monetary20250528a.htm. Cleveland Fed nowcast: not used (latest pre-as_of capture (20250415233207) has no chart for 2025-5).

### `cpi-2025-jun` (June 2025 CPI, released 2025-07-15; `as_of` 2025-07-08T00:00:00Z)

| # | Title | Source URL | Archive URL (capture time, UTC) | `available_at` | Does not leak the print because... | Check |
|---|---|---|---|---|---|---|
| 1 | BLS news release: Consumer Price Index - May 2025 (verbatim excerpt: opening summary paragraphs) | https://www.bls.gov/news.release/archives/cpi_06112025.htm | https://web.archive.org/web/20250629234948/https://www.bls.gov/news.release/archives/cpi_06112025.htm (2025-06-29T23:49:48Z) | 2025-06-11T12:30:00Z (EDT) | It is the CPI release for an earlier month, public since 2025-06-11; it does not contain the June 2025 figure. | [x] source ok [x] capture before `as_of` [x] no leak (AI re-check) |
| 2 | Federal Reserve issues FOMC statement (June 18, 2025; full statement text) | https://www.federalreserve.gov/newsevents/pressreleases/monetary20250618a.htm | https://web.archive.org/web/20250707152142/https://www.federalreserve.gov/newsevents/pressreleases/monetary20250618a.htm (2025-07-07T15:21:42Z) | 2025-06-18T18:00:00Z (EDT) | FOMC statement released 2025-06-18, before the June 2025 CPI release; the Fed does not publish CPI figures ahead of BLS. | [x] source ok [x] capture before `as_of` [x] no leak (AI re-check) |
| 3 | Minutes of the Federal Open Market Committee, May 6-7, 2025 (verbatim excerpt: paragraphs containing 'outlook for monetary policy') | https://www.federalreserve.gov/monetarypolicy/fomcminutes20250507.htm | https://web.archive.org/web/20250707221158/https://www.federalreserve.gov/monetarypolicy/fomcminutes20250507.htm (2025-07-07T22:11:58Z) | 2025-05-28T18:00:00Z (EDT) | FOMC minutes released 2025-05-28; they summarise a meeting held weeks before the June 2025 CPI release. | [x] source ok [x] capture before `as_of` [x] no leak (AI re-check) |

BLS release current at `as_of`, read from the last pre-`as_of` capture of the BLS current-release page: CONSUMER PRICE INDEX - MAY 2025 (https://web.archive.org/web/20250706210529/https://www.bls.gov/news.release/cpi.nr0.htm). Minutes release time from the Fed press release https://www.federalreserve.gov/newsevents/pressreleases/monetary20250528a.htm. Cleveland Fed nowcast: not used (latest pre-as_of capture (20250415233207) has no chart for 2025-6).

### `cpi-2025-jul` (July 2025 CPI, released 2025-08-12; `as_of` 2025-08-05T00:00:00Z)

| # | Title | Source URL | Archive URL (capture time, UTC) | `available_at` | Does not leak the print because... | Check |
|---|---|---|---|---|---|---|
| 1 | BLS news release: Consumer Price Index - June 2025 (verbatim excerpt: opening summary paragraphs) | https://www.bls.gov/news.release/archives/cpi_07152025.htm | https://web.archive.org/web/20250802181002/https://www.bls.gov/news.release/archives/cpi_07152025.htm (2025-08-02T18:10:02Z) | 2025-07-15T12:30:00Z (EDT) | It is the CPI release for an earlier month, public since 2025-07-15; it does not contain the July 2025 figure. | [x] source ok [x] capture before `as_of` [x] no leak (AI re-check) |
| 2 | Federal Reserve issues FOMC statement (July 30, 2025; full statement text) | https://www.federalreserve.gov/newsevents/pressreleases/monetary20250730a.htm | https://web.archive.org/web/20250803153754/https://www.federalreserve.gov/newsevents/pressreleases/monetary20250730a.htm (2025-08-03T15:37:54Z) | 2025-07-30T18:00:00Z (EDT) | FOMC statement released 2025-07-30, before the July 2025 CPI release; the Fed does not publish CPI figures ahead of BLS. | [x] source ok [x] capture before `as_of` [x] no leak (AI re-check) |
| 3 | Minutes of the Federal Open Market Committee, June 17-18, 2025 (verbatim excerpt: paragraphs containing 'outlook for monetary policy') | https://www.federalreserve.gov/monetarypolicy/fomcminutes20250618.htm | https://web.archive.org/web/20250723170814/https://www.federalreserve.gov/monetarypolicy/fomcminutes20250618.htm (2025-07-23T17:08:14Z) | 2025-07-09T18:00:00Z (EDT) | FOMC minutes released 2025-07-09; they summarise a meeting held weeks before the July 2025 CPI release. | [x] source ok [x] capture before `as_of` [x] no leak (AI re-check) |
| 4 | Federal Reserve Bank of Cleveland Inflation Nowcasting: month-over-month CPI nowcast for July 2025 (verbatim values from the archived data file nowcast_month.json) | https://www.clevelandfed.org/-/media/files/webcharts/inflationnowcasting/nowcast_month.json?sc_lang=en&_=1753578337983 | https://web.archive.org/web/20250727010540/https://www.clevelandfed.org/-/media/files/webcharts/inflationnowcasting/nowcast_month.json?sc_lang=en&_=1753578337983 (2025-07-27T01:05:40Z) | 2025-07-27T01:05:40Z (capture time) | A model estimate captured 2025-07-27, before the release; the capture's 'Actual CPI' values for July 2025 were empty (checked by code). | [x] source ok [x] capture before `as_of` [x] no leak (AI re-check) |

BLS release current at `as_of`, read from the last pre-`as_of` capture of the BLS current-release page: CONSUMER PRICE INDEX - JUNE 2025 (https://web.archive.org/web/20250802071435/https://www.bls.gov/news.release/cpi.nr0.htm). Minutes release time from the Fed press release https://www.federalreserve.gov/newsevents/pressreleases/monetary20250709a.htm.

### `cpi-2025-aug` (August 2025 CPI, released 2025-09-11; `as_of` 2025-09-04T00:00:00Z)

| # | Title | Source URL | Archive URL (capture time, UTC) | `available_at` | Does not leak the print because... | Check |
|---|---|---|---|---|---|---|
| 1 | BLS news release: Consumer Price Index - July 2025 (verbatim excerpt: opening summary paragraphs) | https://www.bls.gov/news.release/archives/cpi_08122025.htm | https://web.archive.org/web/20250814195247/https://www.bls.gov/news.release/archives/cpi_08122025.htm (2025-08-14T19:52:47Z) | 2025-08-12T12:30:00Z (EDT) | It is the CPI release for an earlier month, public since 2025-08-12; it does not contain the August 2025 figure. | [x] source ok [x] capture before `as_of` [x] no leak (AI re-check) |
| 2 | Federal Reserve issues FOMC statement (July 30, 2025; full statement text) | https://www.federalreserve.gov/newsevents/pressreleases/monetary20250730a.htm | https://web.archive.org/web/20250902071352/https://www.federalreserve.gov/newsevents/pressreleases/monetary20250730a.htm (2025-09-02T07:13:52Z) | 2025-07-30T18:00:00Z (EDT) | FOMC statement released 2025-07-30, before the August 2025 CPI release; the Fed does not publish CPI figures ahead of BLS. | [x] source ok [x] capture before `as_of` [x] no leak (AI re-check) |
| 3 | Minutes of the Federal Open Market Committee, July 29-30, 2025 (verbatim excerpt: paragraphs containing 'outlook for monetary policy') | https://www.federalreserve.gov/monetarypolicy/fomcminutes20250730.htm | https://web.archive.org/web/20250825123106/https://www.federalreserve.gov/monetarypolicy/fomcminutes20250730.htm (2025-08-25T12:31:06Z) | 2025-08-20T18:00:00Z (EDT) | FOMC minutes released 2025-08-20; they summarise a meeting held weeks before the August 2025 CPI release. | [x] source ok [x] capture before `as_of` [x] no leak (AI re-check) |

BLS release current at `as_of`, read from the last pre-`as_of` capture of the BLS current-release page: CONSUMER PRICE INDEX - JULY 2025 (https://web.archive.org/web/20250903214023/https://www.bls.gov/news.release/cpi.nr0.htm). Minutes release time from the Fed press release https://www.federalreserve.gov/newsevents/pressreleases/monetary20250820a.htm. Cleveland Fed nowcast: not used (latest pre-as_of capture (20250727010540) has no chart for 2025-8).

### `cpi-2026-feb` (February 2026 CPI, released 2026-03-11; `as_of` 2026-03-04T00:00:00Z)

| # | Title | Source URL | Archive URL (capture time, UTC) | `available_at` | Does not leak the print because... | Check |
|---|---|---|---|---|---|---|
| 1 | BLS news release: Consumer Price Index - January 2026 (verbatim excerpt: opening summary paragraphs) | https://www.bls.gov/news.release/archives/cpi_02132026.htm | https://web.archive.org/web/20260214212746/https://www.bls.gov/news.release/archives/cpi_02132026.htm (2026-02-14T21:27:46Z) | 2026-02-13T13:30:00Z (EST) | It is the CPI release for an earlier month, public since 2026-02-13; it does not contain the February 2026 figure. | [x] source ok [x] capture before `as_of` [x] no leak (AI re-check) |
| 2 | Federal Reserve issues FOMC statement (January 28, 2026; full statement text) | https://www.federalreserve.gov/newsevents/pressreleases/monetary20260128a.htm | https://web.archive.org/web/20260302005226/https://www.federalreserve.gov/newsevents/pressreleases/monetary20260128a.htm (2026-03-02T00:52:26Z) | 2026-01-28T19:00:00Z (EST) | FOMC statement released 2026-01-28, before the February 2026 CPI release; the Fed does not publish CPI figures ahead of BLS. | [x] source ok [x] capture before `as_of` [x] no leak (AI re-check) |
| 3 | Minutes of the Federal Open Market Committee, January 27-28, 2026 (verbatim excerpt: paragraphs containing 'outlook for monetary policy') | https://www.federalreserve.gov/monetarypolicy/fomcminutes20260128.htm | https://web.archive.org/web/20260226005222/https://www.federalreserve.gov/monetarypolicy/fomcminutes20260128.htm (2026-02-26T00:52:22Z) | 2026-02-18T19:00:00Z (EST) | FOMC minutes released 2026-02-18; they summarise a meeting held weeks before the February 2026 CPI release. | [x] source ok [x] capture before `as_of` [x] no leak (AI re-check) |
| 4 | Federal Reserve Bank of Cleveland Inflation Nowcasting: month-over-month CPI nowcast for February 2026 (verbatim values from the archived data file nowcast_month.json) | https://www.clevelandfed.org/-/media/files/webcharts/inflationnowcasting/nowcast_month.json?sc_lang=en&_=1665929622162 | https://web.archive.org/web/20260222030127/https://www.clevelandfed.org/-/media/files/webcharts/inflationnowcasting/nowcast_month.json?sc_lang=en&_=1665929622162 (2026-02-22T03:01:27Z) | 2026-02-22T03:01:27Z (capture time) | A model estimate captured 2026-02-22, before the release; the capture's 'Actual CPI' values for February 2026 were empty (checked by code). | [x] source ok [x] capture before `as_of` [x] no leak (AI re-check) |

BLS release current at `as_of`, read from the last pre-`as_of` capture of the BLS current-release page: CONSUMER PRICE INDEX - JANUARY 2026 (https://web.archive.org/web/20260302234659/https://www.bls.gov/news.release/cpi.nr0.htm). Minutes release time from the Fed press release https://www.federalreserve.gov/newsevents/pressreleases/monetary20260218a.htm.

### `cpi-2026-mar` (March 2026 CPI, released 2026-04-10; `as_of` 2026-04-03T00:00:00Z)

| # | Title | Source URL | Archive URL (capture time, UTC) | `available_at` | Does not leak the print because... | Check |
|---|---|---|---|---|---|---|
| 1 | BLS news release: Consumer Price Index - February 2026 (verbatim excerpt: opening summary paragraphs) | https://www.bls.gov/news.release/archives/cpi_03112026.htm | https://web.archive.org/web/20260313133909/https://www.bls.gov/news.release/archives/cpi_03112026.htm (2026-03-13T13:39:09Z) | 2026-03-11T12:30:00Z (EDT) | It is the CPI release for an earlier month, public since 2026-03-11; it does not contain the March 2026 figure. | [x] source ok [x] capture before `as_of` [x] no leak (AI re-check) |
| 2 | Federal Reserve issues FOMC statement (March 18, 2026; full statement text) | https://www.federalreserve.gov/newsevents/pressreleases/monetary20260318a.htm | https://web.archive.org/web/20260402221750/https://www.federalreserve.gov/newsevents/pressreleases/monetary20260318a.htm (2026-04-02T22:17:50Z) | 2026-03-18T18:00:00Z (EDT) | FOMC statement released 2026-03-18, before the March 2026 CPI release; the Fed does not publish CPI figures ahead of BLS. | [x] source ok [x] capture before `as_of` [x] no leak (AI re-check) |
| 3 | Minutes of the Federal Open Market Committee, January 27-28, 2026 (verbatim excerpt: paragraphs containing 'outlook for monetary policy') | https://www.federalreserve.gov/monetarypolicy/fomcminutes20260128.htm | https://web.archive.org/web/20260323170827/https://www.federalreserve.gov/monetarypolicy/fomcminutes20260128.htm (2026-03-23T17:08:27Z) | 2026-02-18T19:00:00Z (EST) | FOMC minutes released 2026-02-18; they summarise a meeting held weeks before the March 2026 CPI release. | [x] source ok [x] capture before `as_of` [x] no leak (AI re-check) |
| 4 | Federal Reserve Bank of Cleveland Inflation Nowcasting: month-over-month CPI nowcast for March 2026 (verbatim values from the archived data file nowcast_month.json) | https://www.clevelandfed.org/-/media/files/webcharts/inflationnowcasting/nowcast_month.json | https://web.archive.org/web/20260325052951/https://www.clevelandfed.org/-/media/files/webcharts/inflationnowcasting/nowcast_month.json (2026-03-25T05:29:51Z) | 2026-03-25T05:29:51Z (capture time) | A model estimate captured 2026-03-25, before the release; the capture's 'Actual CPI' values for March 2026 were empty (checked by code). | [x] source ok [x] capture before `as_of` [x] no leak (AI re-check) |

BLS release current at `as_of`, read from the last pre-`as_of` capture of the BLS current-release page: CONSUMER PRICE INDEX - FEBRUARY 2026 (https://web.archive.org/web/20260402214015/https://www.bls.gov/news.release/cpi.nr0.htm). Minutes release time from the Fed press release https://www.federalreserve.gov/newsevents/pressreleases/monetary20260218a.htm.

### `cpi-2026-may` (May 2026 CPI, released 2026-06-10; `as_of` 2026-06-03T00:00:00Z)

| # | Title | Source URL | Archive URL (capture time, UTC) | `available_at` | Does not leak the print because... | Check |
|---|---|---|---|---|---|---|
| 1 | BLS news release: Consumer Price Index - April 2026 (verbatim excerpt: opening summary paragraphs) | https://www.bls.gov/news.release/archives/cpi_05122026.htm | https://web.archive.org/web/20260516131121/https://www.bls.gov/news.release/archives/cpi_05122026.htm (2026-05-16T13:11:21Z) | 2026-05-12T12:30:00Z (EDT) | It is the CPI release for an earlier month, public since 2026-05-12; it does not contain the May 2026 figure. | [x] source ok [x] capture before `as_of` [x] no leak (AI re-check) |
| 2 | Federal Reserve issues FOMC statement (April 29, 2026; full statement text) | https://www.federalreserve.gov/newsevents/pressreleases/monetary20260429a.htm | https://web.archive.org/web/20260531041029/https://www.federalreserve.gov/newsevents/pressreleases/monetary20260429a.htm (2026-05-31T04:10:29Z) | 2026-04-29T18:00:00Z (EDT) | FOMC statement released 2026-04-29, before the May 2026 CPI release; the Fed does not publish CPI figures ahead of BLS. | [x] source ok [x] capture before `as_of` [x] no leak (AI re-check) |
| 3 | Minutes of the Federal Open Market Committee, April 28-29, 2026 (verbatim excerpt: paragraphs containing 'outlook for monetary policy') | https://www.federalreserve.gov/monetarypolicy/fomcminutes20260429.htm | https://web.archive.org/web/20260524221128/https://www.federalreserve.gov/monetarypolicy/fomcminutes20260429.htm (2026-05-24T22:11:28Z) | 2026-05-20T18:00:00Z (EDT) | FOMC minutes released 2026-05-20; they summarise a meeting held weeks before the May 2026 CPI release. | [x] source ok [x] capture before `as_of` [x] no leak (AI re-check) |
| 4 | Federal Reserve Bank of Cleveland Inflation Nowcasting: month-over-month CPI nowcast for May 2026 (verbatim values from the archived data file nowcast_month.json) | https://www.clevelandfed.org/-/media/files/webcharts/inflationnowcasting/nowcast_month.json?sc_lang=en&_=1778080958753 | https://web.archive.org/web/20260506152241/https://www.clevelandfed.org/-/media/files/webcharts/inflationnowcasting/nowcast_month.json?sc_lang=en&_=1778080958753 (2026-05-06T15:22:41Z) | 2026-05-06T15:22:41Z (capture time) | A model estimate captured 2026-05-06, before the release; the capture's 'Actual CPI' values for May 2026 were empty (checked by code). | [x] source ok [x] capture before `as_of` [x] no leak (AI re-check) |

BLS release current at `as_of`, read from the last pre-`as_of` capture of the BLS current-release page: CONSUMER PRICE INDEX - APRIL 2026 (https://web.archive.org/web/20260602232244/https://www.bls.gov/news.release/cpi.nr0.htm). Minutes release time from the Fed press release https://www.federalreserve.gov/newsevents/pressreleases/monetary20260520a.htm.

### `cpi-2026-jul` (July 2026 CPI, released 2026-08-12; `as_of` 2026-08-05T00:00:00Z)

| # | Title | Source URL | Archive URL (capture time, UTC) | `available_at` | Does not leak the print because... | Check |
|---|---|---|---|---|---|---|
| 1 | BLS news release: Consumer Price Index - June 2026 (verbatim excerpt: opening summary paragraphs) | https://www.bls.gov/news.release/archives/cpi_07142026.htm | https://web.archive.org/web/20260731115306/https://www.bls.gov/news.release/archives/cpi_07142026.htm (2026-07-31T11:53:06Z) | 2026-07-14T12:30:00Z (EDT) | It is the CPI release for an earlier month, public since 2026-07-14; it does not contain the July 2026 figure. | [x] source ok [x] capture before `as_of` [x] no leak (AI re-check) |
| 2 | Federal Reserve issues FOMC statement (July 29, 2026; full statement text) | https://www.federalreserve.gov/newsevents/pressreleases/monetary20260729a.htm | https://web.archive.org/web/20260804112654/https://www.federalreserve.gov/newsevents/pressreleases/monetary20260729a.htm (2026-08-04T11:26:54Z) | 2026-07-29T18:00:00Z (EDT) | FOMC statement released 2026-07-29, before the July 2026 CPI release; the Fed does not publish CPI figures ahead of BLS. | [x] source ok [x] capture before `as_of` [x] no leak (AI re-check) |
| 3 | Minutes of the Federal Open Market Committee, June 16-17, 2026 (verbatim excerpt: paragraphs containing 'outlook for monetary policy') | https://www.federalreserve.gov/monetarypolicy/fomcminutes20260617.htm | https://web.archive.org/web/20260724195305/https://www.federalreserve.gov/monetarypolicy/fomcminutes20260617.htm (2026-07-24T19:53:05Z) | 2026-07-08T18:00:00Z (EDT) | FOMC minutes released 2026-07-08; they summarise a meeting held weeks before the July 2026 CPI release. | [x] source ok [x] capture before `as_of` [x] no leak (AI re-check) |
| 4 | Federal Reserve Bank of Cleveland Inflation Nowcasting: month-over-month CPI nowcast for July 2026 (verbatim values from the archived data file nowcast_month.json) | https://www.clevelandfed.org/-/media/files/webcharts/inflationnowcasting/nowcast_month.json?sc_lang=en&_=1785864038436 | https://web.archive.org/web/20260804172041/https://www.clevelandfed.org/-/media/files/webcharts/inflationnowcasting/nowcast_month.json?sc_lang=en&_=1785864038436 (2026-08-04T17:20:41Z) | 2026-08-04T17:20:41Z (capture time) | A model estimate captured 2026-08-04, before the release; the capture's 'Actual CPI' values for July 2026 were empty (checked by code). | [x] source ok [x] capture before `as_of` [x] no leak (AI re-check) |

BLS release current at `as_of`, read from the last pre-`as_of` capture of the BLS current-release page: CONSUMER PRICE INDEX - JUNE 2026 (https://web.archive.org/web/20260804190103/https://www.bls.gov/news.release/cpi.nr0.htm). Minutes release time from the Fed press release https://www.federalreserve.gov/newsevents/pressreleases/monetary20260708a.htm.

### `cpi-2026-aug` (August 2026 CPI, released 2026-09-11; `as_of` 2026-09-04T00:00:00Z)

| # | Title | Source URL | Archive URL (capture time, UTC) | `available_at` | Does not leak the print because... | Check |
|---|---|---|---|---|---|---|
| 1 | BLS news release: Consumer Price Index - July 2026 (verbatim excerpt: opening summary paragraphs) | https://www.bls.gov/news.release/archives/cpi_08122026.htm | https://web.archive.org/web/20260819191816/https://www.bls.gov/news.release/archives/cpi_08122026.htm (2026-08-19T19:18:16Z) | 2026-08-12T12:30:00Z (EDT) | It is the CPI release for an earlier month, public since 2026-08-12; it does not contain the August 2026 figure. | [x] source ok [x] capture before `as_of` [x] no leak (AI re-check) |
| 2 | Federal Reserve issues FOMC statement (July 29, 2026; full statement text) | https://www.federalreserve.gov/newsevents/pressreleases/monetary20260729a.htm | https://web.archive.org/web/20260903034241/https://www.federalreserve.gov/newsevents/pressreleases/monetary20260729a.htm (2026-09-03T03:42:41Z) | 2026-07-29T18:00:00Z (EDT) | FOMC statement released 2026-07-29, before the August 2026 CPI release; the Fed does not publish CPI figures ahead of BLS. | [x] source ok [x] capture before `as_of` [x] no leak (AI re-check) |
| 3 | Minutes of the Federal Open Market Committee, July 28-29, 2026 (verbatim excerpt: paragraphs containing 'outlook for monetary policy') | https://www.federalreserve.gov/monetarypolicy/fomcminutes20260729.htm | https://web.archive.org/web/20260903123310/https://www.federalreserve.gov/monetarypolicy/fomcminutes20260729.htm (2026-09-03T12:33:10Z) | 2026-08-19T18:00:00Z (EDT) | FOMC minutes released 2026-08-19; they summarise a meeting held weeks before the August 2026 CPI release. | [x] source ok [x] capture before `as_of` [x] no leak (AI re-check) |
| 4 | Federal Reserve Bank of Cleveland Inflation Nowcasting: month-over-month CPI nowcast for August 2026 (verbatim values from the archived data file nowcast_month.json) | https://www.clevelandfed.org/-/media/files/webcharts/inflationnowcasting/nowcast_month.json?sc_lang=en&_=1788222242771 | https://web.archive.org/web/20260901002404/https://www.clevelandfed.org/-/media/files/webcharts/inflationnowcasting/nowcast_month.json?sc_lang=en&_=1788222242771 (2026-09-01T00:24:04Z) | 2026-09-01T00:24:04Z (capture time) | A model estimate captured 2026-09-01, before the release; the capture's 'Actual CPI' values for August 2026 were empty (checked by code). | [x] source ok [x] capture before `as_of` [x] no leak (AI re-check) |

BLS release current at `as_of`, read from the last pre-`as_of` capture of the BLS current-release page: CONSUMER PRICE INDEX - JULY 2026 (https://web.archive.org/web/20260903163600/https://www.bls.gov/news.release/cpi.nr0.htm). Minutes release time from the Fed press release https://www.federalreserve.gov/newsevents/pressreleases/monetary20260819a.htm.

### `cpi-2026-sep` (September 2026 CPI, released 2026-10-14; `as_of` 2026-10-07T00:00:00Z)

| # | Title | Source URL | Archive URL (capture time, UTC) | `available_at` | Does not leak the print because... | Check |
|---|---|---|---|---|---|---|
| 1 | BLS news release: Consumer Price Index - August 2026 (verbatim excerpt: opening summary paragraphs) | https://www.bls.gov/news.release/archives/cpi_09112026.htm | https://web.archive.org/web/20261004231946/https://www.bls.gov/news.release/archives/cpi_09112026.htm (2026-10-04T23:19:46Z) | 2026-09-11T12:30:00Z (EDT) | It is the CPI release for an earlier month, public since 2026-09-11; it does not contain the September 2026 figure. | [x] source ok [x] capture before `as_of` [x] no leak (AI re-check) |
| 2 | Federal Reserve issues FOMC statement (September 16, 2026; full statement text) | https://www.federalreserve.gov/newsevents/pressreleases/monetary20260916a.htm | https://web.archive.org/web/20261006042225/https://www.federalreserve.gov/newsevents/pressreleases/monetary20260916a.htm (2026-10-06T04:22:25Z) | 2026-09-16T18:00:00Z (EDT) | FOMC statement released 2026-09-16, before the September 2026 CPI release; the Fed does not publish CPI figures ahead of BLS. | [x] source ok [x] capture before `as_of` [x] no leak (AI re-check) |
| 3 | Minutes of the Federal Open Market Committee, July 28-29, 2026 (verbatim excerpt: paragraphs containing 'outlook for monetary policy') | https://www.federalreserve.gov/monetarypolicy/fomcminutes20260729.htm | https://web.archive.org/web/20260917192944/https://www.federalreserve.gov/monetarypolicy/fomcminutes20260729.htm (2026-09-17T19:29:44Z) | 2026-08-19T18:00:00Z (EDT) | FOMC minutes released 2026-08-19; they summarise a meeting held weeks before the September 2026 CPI release. | [x] source ok [x] capture before `as_of` [x] no leak (AI re-check) |
| 4 | Federal Reserve Bank of Cleveland Inflation Nowcasting: month-over-month CPI nowcast for September 2026 (verbatim values from the archived data file nowcast_month.json) | https://www.clevelandfed.org/-/media/files/webcharts/inflationnowcasting/nowcast_month.json?sc_lang=en&_=1791267976705 | https://web.archive.org/web/20261006062619/https://www.clevelandfed.org/-/media/files/webcharts/inflationnowcasting/nowcast_month.json?sc_lang=en&_=1791267976705 (2026-10-06T06:26:19Z) | 2026-10-06T06:26:19Z (capture time) | A model estimate captured 2026-10-06, before the release; the capture's 'Actual CPI' values for September 2026 were empty (checked by code). | [x] source ok [x] capture before `as_of` [x] no leak (AI re-check) |

BLS release current at `as_of`, read from the last pre-`as_of` capture of the BLS current-release page: CONSUMER PRICE INDEX - AUGUST 2026 (https://web.archive.org/web/20261006115720/https://www.bls.gov/news.release/cpi.nr0.htm). Minutes release time from the Fed press release https://www.federalreserve.gov/newsevents/pressreleases/monetary20260819a.htm.

## Sign-off

- [x] All 49 rows above passed the independent AI re-check; none failed, so no case drops under Part 4 rule 11.
- [x] **Yaseen accepts the Part 4 rule and the 13 inclusions / 10 exclusions** (his decision, 2026-11-14).
- [x] The `cpi-2026-may` market-quote point and the `cpi-2025-feb` close mismatch were checked (AI re-check, below).
- [x] All 13 sealed files (not just two) were compared with the BLS releases they cite, by code that printed only
      ok/mismatch: 13/13 ok. This was a code check run by Claude Code, independent of the build agent's own check; it
      was not a manual comparison, and no outcome was printed or recorded.

Rule accepted by: Yaseen (finance owner), 2026-11-14. Evidence rows checked by: Claude Code (independent read-only
auditor agent), at Yaseen's request. Manual human check of the rows: **not done**.

### What the independent re-check did (2026-11-14)
- **Source:** all 49 on bls.gov, federalreserve.gov or clevelandfed.org; each archived document matches its title.
- **Capture before `as_of`:** each capture fetched raw (`web.archive.org/web/<ts>id_/<url>`), no redirect to another
  capture; every excerpt paragraph (or nowcast value) found in it. `content_sha256` matches 49/49.
- **`available_at`:** equals the printed release time in UTC (EST/EDT applied correctly), 49/49.
- **No leak:** no item is the target month's release or contains its title line or opening paragraphs (compared by
  code, ok/mismatch only; a positive control confirmed the extractor finds the previous month's release in item 1,
  13/13); every nowcast capture has an empty "Actual" value for the target month (10/10).
- **Rule application:** all 23 prints match `candidate_plan_51.json` (`pairs` vs `diverging_pairs`) and the saved
  snapshots; for the 13 included, the selected quotes equal the Part 4 table and the thresholds agree (b = Kalshi
  level + 0.1).
- **Flagged points:** `cpi-2026-may`'s Kalshi quote is a real trade (06-02T06:00Z, volume 59); `cpi-2025-feb`'s
  Polymarket rule names the March 12, 2025 release (the 03-31 date is market-level only); the boxed BLS notices
  (Feb, May, Aug 2025) are methodology only.
- **Not checkable:** live bls.gov returns HTTP 403 to automated requests, so BLS text was verified through archive
  captures only; the Kalshi contract-terms PDF of 2025 was not re-read.
