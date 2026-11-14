# VERIFY_67: finance owner's check of the #67 evidence

**Status: admitted on an independent AI re-check that the finance owner requested, NOT a manual human check.**
On 2026-11-14 Yaseen (finance owner, #67) asked Claude Code to complete this check for him. A separate read-only
auditor agent, which did not build these cases, re-checked all 44 rows from scratch with its own code (method below)
and every row passed. The boxes below record that AI re-check. They are **not** a statement that Yaseen opened each
page himself. The lead decides whether this satisfies #67's "YOU confirm" requirement; if not, a person can redo
any row with the "How to check one row" steps.

The 11 new cases are `services/api/data/demo_cases/fomc-2025-{jan,mar,may,jun,jul,sep,oct,dec}.json` and
`fomc-2026-{jan,mar,apr}.json`. The rule that picked them, and every meeting it yields, is in `docs/CASES.md` Part 3.
The four 2026 cases from #54 (`fomc-2026-jun/jul/sep/oct`) are reused unchanged and are not part of this check.

This file contains no meeting outcome. Please keep it that way: write no decision, vote, new rate or after-the-fact
coverage here, in a commit message or in a PR comment.

## What the agent already checked (by code, 2026-11-14)

For every one of the 44 items below:
- the excerpt is taken mechanically by `docs/CASES.md` rule 5 (the same code as #54; it reproduces all 16 #54
  excerpts byte for byte);
- `available_at` is the release time printed on the document (Fed: "For release at 2:00 p.m. EST/EDT"; BLS:
  "embargoed until 8:30 a.m. (ET)", converted with US daylight-saving dates) and is before `as_of`;
- the archive capture listed was taken before `as_of`, it was downloaded, and every excerpt paragraph was found in it
  word for word (after whitespace normalization);
- Federal Reserve pages were also fetched live (HTTP 200). Live BLS pages return HTTP 403 to automated requests, so
  BLS text comes only from archive captures: the permanent archive URL, corroborated by the BLS current-release page
  captured before `as_of`;
- the BLS release used is the one the last pre-`as_of` capture of the BLS current-release page showed (that capture
  is linked under each table);
- no paragraph that appears only in the meeting's own statement (that is, not already in the previous statement) is
  in its case file.

This AI re-check is not the manual human check that #67 asks for; the lead accepted it on 2026-11-14 together with an independent lead-side audit (15 Wayback items, all 22 BLS release choices and all sealed outcomes re-derived from primary sources; all passed).

## How to check one row (about 2 minutes each)

1. **Source ok:** open the source URL. Confirm the title matches the document and that it is the official page
   (federalreserve.gov or bls.gov). BLS may block the live page; if it does, use the archive link.
2. **Capture before `as_of`:** open the archive URL. The 14-digit number after `/web/` is the capture time in UTC
   (YYYYMMDDhhmmss). Confirm it is earlier than the case's `as_of` and that the page shows the same document.
3. **No leak:** read the excerpt in the case file (`evidence[].content`). Confirm it says nothing about how *this*
   meeting was decided. A previous meeting's statement is allowed: it was public before `as_of`.

Tick the three boxes in the row. If any box fails, write the problem next to the row and do not tick it. Under rule
7(b) a case with fewer than 3 confirmed items is excluded, and that must be recorded in `docs/CASES.md`.

## Points that need a closer look

- **Late-2025 shutdown (`fomc-2025-oct`, `fomc-2025-dec`).** Please confirm on the BLS archive pages
  (https://www.bls.gov/bls/news-release/cpi.htm and https://www.bls.gov/bls/news-release/empsit.htm) that no newer
  CPI or Employment Situation release came out before `as_of`. For `fomc-2025-oct` that means no September 2025 CPI
  or September jobs report before 2025-10-22. For `fomc-2025-dec` it means no newer CPI than September 2025 and no
  newer jobs report than September 2025 before 2025-12-03.
- **CPI excerpts with a boxed notice (`fomc-2025-mar`, `fomc-2025-jun`, `fomc-2025-sep`).** Rule 5 takes every
  paragraph before "Table A.", so these excerpts include BLS's methodology box verbatim, dashed borders included.
  Please confirm the box says nothing about monetary policy.
- **EST vs EDT.** Items released between early November and early March use 19:00Z (Fed) or 13:30Z (BLS). Spot-check
  one: `fomc-2025-dec` mixes both (Oct 29 statement in EDT, Nov 19 minutes in EST).
- **Cross-case visibility.** Item 1 of each case is the previous meeting's statement, which settles the previous
  case. That is allowed, but it means all forecasts must be run before any reveal (see `docs/CASES.md` Part 3).

## Items to confirm (44)

### `fomc-2025-jan` (meeting Jan 28-29, 2025; `as_of` 2025-01-22T00:00:00Z)

| # | Title | Source URL | Archive URL (capture time, UTC) | `available_at` | Does not leak the decision because... | Check |
|---|---|---|---|---|---|---|
| 1 | Federal Reserve issues FOMC statement (December 18, 2024; full statement text) | https://www.federalreserve.gov/newsevents/pressreleases/monetary20241218a.htm | https://web.archive.org/web/20250116225427/https://www.federalreserve.gov/newsevents/pressreleases/monetary20241218a.htm (2025-01-16T22:54:27Z) | 2024-12-18T19:00:00Z (EST) | It is the previous meeting's statement, public since 2024-12-18; it records that earlier decision and says nothing about this meeting's decision. | [x] source ok [x] capture before `as_of` [x] no leak (AI re-check) |
| 2 | Minutes of the Federal Open Market Committee, December 17-18, 2024 (verbatim excerpt: paragraphs containing 'outlook for monetary policy') | https://www.federalreserve.gov/monetarypolicy/fomcminutes20241218.htm | https://web.archive.org/web/20250116225434/https://www.federalreserve.gov/monetarypolicy/fomcminutes20241218.htm (2025-01-16T22:54:34Z) | 2025-01-08T19:00:00Z (EST) | Minutes of the previous meeting, released 2025-01-08; they summarise views held at that meeting and contain no record of this meeting. | [x] source ok [x] capture before `as_of` [x] no leak (AI re-check) |
| 3 | BLS news release: Consumer Price Index - December 2024 (verbatim excerpt: opening summary paragraphs) | https://www.bls.gov/news.release/archives/cpi_01152025.htm | https://web.archive.org/web/20250120140851/https://www.bls.gov/news.release/archives/cpi_01152025.htm (2025-01-20T14:08:51Z) | 2025-01-15T13:30:00Z (EST) | Official price statistics, first published 2025-01-15; a BLS release contains no FOMC decision. | [x] source ok [x] capture before `as_of` [x] no leak (AI re-check) |
| 4 | BLS news release: The Employment Situation -- December 2024 (verbatim excerpt: opening summary paragraph) | https://www.bls.gov/news.release/archives/empsit_01102025.htm | https://web.archive.org/web/20250119071454/https://www.bls.gov/news.release/archives/empsit_01102025.htm (2025-01-19T07:14:54Z) | 2025-01-10T13:30:00Z (EST) | Official labour statistics, first published 2025-01-10; a BLS release contains no FOMC decision. | [x] source ok [x] capture before `as_of` [x] no leak (AI re-check) |

BLS release current at `as_of`, read from the last pre-`as_of` capture of the BLS current-release page: CPI CONSUMER PRICE INDEX - DECEMBER 2024 (https://web.archive.org/web/20250121210942/https://www.bls.gov/news.release/cpi.nr0.htm); jobs THE EMPLOYMENT SITUATION -- DECEMBER 2024 (https://web.archive.org/web/20250121081937/https://www.bls.gov/news.release/empsit.nr0.htm). Minutes release time from the Fed press release https://www.federalreserve.gov/newsevents/pressreleases/monetary20250108a.htm.

### `fomc-2025-mar` (meeting Mar 18-19, 2025; `as_of` 2025-03-12T00:00:00Z)

| # | Title | Source URL | Archive URL (capture time, UTC) | `available_at` | Does not leak the decision because... | Check |
|---|---|---|---|---|---|---|
| 1 | Federal Reserve issues FOMC statement (January 29, 2025; full statement text) | https://www.federalreserve.gov/newsevents/pressreleases/monetary20250129a.htm | https://web.archive.org/web/20250306225325/https://www.federalreserve.gov/newsevents/pressreleases/monetary20250129a.htm (2025-03-06T22:53:25Z) | 2025-01-29T19:00:00Z (EST) | It is the previous meeting's statement, public since 2025-01-29; it records that earlier decision and says nothing about this meeting's decision. | [x] source ok [x] capture before `as_of` [x] no leak (AI re-check) |
| 2 | Minutes of the Federal Open Market Committee, January 28-29, 2025 (verbatim excerpt: paragraphs containing 'outlook for monetary policy') | https://www.federalreserve.gov/monetarypolicy/fomcminutes20250129.htm | https://web.archive.org/web/20250305130625/https://www.federalreserve.gov/monetarypolicy/fomcminutes20250129.htm (2025-03-05T13:06:25Z) | 2025-02-19T19:00:00Z (EST) | Minutes of the previous meeting, released 2025-02-19; they summarise views held at that meeting and contain no record of this meeting. | [x] source ok [x] capture before `as_of` [x] no leak (AI re-check) |
| 3 | BLS news release: Consumer Price Index - January 2025 (verbatim excerpt: opening summary paragraphs) | https://www.bls.gov/news.release/archives/cpi_02122025.htm | https://web.archive.org/web/20250304113507/https://www.bls.gov/news.release/archives/cpi_02122025.htm (2025-03-04T11:35:07Z) | 2025-02-12T13:30:00Z (EST) | Official price statistics, first published 2025-02-12; a BLS release contains no FOMC decision. | [x] source ok [x] capture before `as_of` [x] no leak (AI re-check) |
| 4 | BLS news release: The Employment Situation -- February 2025 (verbatim excerpt: opening summary paragraph) | https://www.bls.gov/news.release/archives/empsit_03072025.htm | https://web.archive.org/web/20250307233113/https://www.bls.gov/news.release/archives/empsit_03072025.htm (2025-03-07T23:31:13Z) | 2025-03-07T13:30:00Z (EST) | Official labour statistics, first published 2025-03-07; a BLS release contains no FOMC decision. | [x] source ok [x] capture before `as_of` [x] no leak (AI re-check) |

BLS release current at `as_of`, read from the last pre-`as_of` capture of the BLS current-release page: CPI CONSUMER PRICE INDEX - JANUARY 2025 (https://web.archive.org/web/20250311231829/https://www.bls.gov/news.release/cpi.nr0.htm); jobs THE EMPLOYMENT SITUATION -- FEBRUARY 2025 (https://web.archive.org/web/20250311193011/https://www.bls.gov/news.release/empsit.nr0.htm). Minutes release time from the Fed press release https://www.federalreserve.gov/newsevents/pressreleases/monetary20250219a.htm.

### `fomc-2025-may` (meeting May 6-7, 2025; `as_of` 2025-04-30T00:00:00Z)

| # | Title | Source URL | Archive URL (capture time, UTC) | `available_at` | Does not leak the decision because... | Check |
|---|---|---|---|---|---|---|
| 1 | Federal Reserve issues FOMC statement (March 19, 2025; full statement text) | https://www.federalreserve.gov/newsevents/pressreleases/monetary20250319a.htm | https://web.archive.org/web/20250429055323/https://www.federalreserve.gov/newsevents/pressreleases/monetary20250319a.htm (2025-04-29T05:53:23Z) | 2025-03-19T18:00:00Z (EDT) | It is the previous meeting's statement, public since 2025-03-19; it records that earlier decision and says nothing about this meeting's decision. | [x] source ok [x] capture before `as_of` [x] no leak (AI re-check) |
| 2 | Minutes of the Federal Open Market Committee, March 18-19, 2025 (verbatim excerpt: paragraphs containing 'outlook for monetary policy') | https://www.federalreserve.gov/monetarypolicy/fomcminutes20250319.htm | https://web.archive.org/web/20250422131304/https://www.federalreserve.gov/monetarypolicy/fomcminutes20250319.htm (2025-04-22T13:13:04Z) | 2025-04-09T18:00:00Z (EDT) | Minutes of the previous meeting, released 2025-04-09; they summarise views held at that meeting and contain no record of this meeting. | [x] source ok [x] capture before `as_of` [x] no leak (AI re-check) |
| 3 | BLS news release: Consumer Price Index - March 2025 (verbatim excerpt: opening summary paragraphs) | https://www.bls.gov/news.release/archives/cpi_04102025.htm | https://web.archive.org/web/20250428021424/https://www.bls.gov/news.release/archives/cpi_04102025.htm (2025-04-28T02:14:24Z) | 2025-04-10T12:30:00Z (EDT) | Official price statistics, first published 2025-04-10; a BLS release contains no FOMC decision. | [x] source ok [x] capture before `as_of` [x] no leak (AI re-check) |
| 4 | BLS news release: The Employment Situation -- March 2025 (verbatim excerpt: opening summary paragraph) | https://www.bls.gov/news.release/archives/empsit_04042025.htm | https://web.archive.org/web/20250429174138/https://www.bls.gov/news.release/archives/empsit_04042025.htm (2025-04-29T17:41:38Z) | 2025-04-04T12:30:00Z (EDT) | Official labour statistics, first published 2025-04-04; a BLS release contains no FOMC decision. | [x] source ok [x] capture before `as_of` [x] no leak (AI re-check) |

BLS release current at `as_of`, read from the last pre-`as_of` capture of the BLS current-release page: CPI CONSUMER PRICE INDEX - MARCH 2025 (https://web.archive.org/web/20250429232400/https://www.bls.gov/news.release/cpi.nr0.htm); jobs THE EMPLOYMENT SITUATION -- MARCH 2025 (https://web.archive.org/web/20250428165042/https://www.bls.gov/news.release/empsit.nr0.htm). Minutes release time from the Fed press release https://www.federalreserve.gov/newsevents/pressreleases/monetary20250409a.htm.

### `fomc-2025-jun` (meeting Jun 17-18, 2025; `as_of` 2025-06-11T00:00:00Z)

| # | Title | Source URL | Archive URL (capture time, UTC) | `available_at` | Does not leak the decision because... | Check |
|---|---|---|---|---|---|---|
| 1 | Federal Reserve issues FOMC statement (May 7, 2025; full statement text) | https://www.federalreserve.gov/newsevents/pressreleases/monetary20250507a.htm | https://web.archive.org/web/20250524072655/https://www.federalreserve.gov/newsevents/pressreleases/monetary20250507a.htm (2025-05-24T07:26:55Z) | 2025-05-07T18:00:00Z (EDT) | It is the previous meeting's statement, public since 2025-05-07; it records that earlier decision and says nothing about this meeting's decision. | [x] source ok [x] capture before `as_of` [x] no leak (AI re-check) |
| 2 | Minutes of the Federal Open Market Committee, May 6-7, 2025 (verbatim excerpt: paragraphs containing 'outlook for monetary policy') | https://www.federalreserve.gov/monetarypolicy/fomcminutes20250507.htm | https://web.archive.org/web/20250607221925/https://www.federalreserve.gov/monetarypolicy/fomcminutes20250507.htm (2025-06-07T22:19:25Z) | 2025-05-28T18:00:00Z (EDT) | Minutes of the previous meeting, released 2025-05-28; they summarise views held at that meeting and contain no record of this meeting. | [x] source ok [x] capture before `as_of` [x] no leak (AI re-check) |
| 3 | BLS news release: Consumer Price Index - April 2025 (verbatim excerpt: opening summary paragraphs) | https://www.bls.gov/news.release/archives/cpi_05132025.htm | https://web.archive.org/web/20250522021145/https://www.bls.gov/news.release/archives/cpi_05132025.htm (2025-05-22T02:11:45Z) | 2025-05-13T12:30:00Z (EDT) | Official price statistics, first published 2025-05-13; a BLS release contains no FOMC decision. | [x] source ok [x] capture before `as_of` [x] no leak (AI re-check) |
| 4 | BLS news release: The Employment Situation -- May 2025 (verbatim excerpt: opening summary paragraph) | https://www.bls.gov/news.release/archives/empsit_06062025.htm | https://web.archive.org/web/20250606173223/https://www.bls.gov/news.release/archives/empsit_06062025.htm (2025-06-06T17:32:23Z) | 2025-06-06T12:30:00Z (EDT) | Official labour statistics, first published 2025-06-06; a BLS release contains no FOMC decision. | [x] source ok [x] capture before `as_of` [x] no leak (AI re-check) |

BLS release current at `as_of`, read from the last pre-`as_of` capture of the BLS current-release page: CPI CONSUMER PRICE INDEX - APRIL 2025 (https://web.archive.org/web/20250609024142/https://www.bls.gov/news.release/cpi.nr0.htm); jobs THE EMPLOYMENT SITUATION -- MAY 2025 (https://web.archive.org/web/20250609224108/https://www.bls.gov/news.release/empsit.nr0.htm). Minutes release time from the Fed press release https://www.federalreserve.gov/newsevents/pressreleases/monetary20250528a.htm.

### `fomc-2025-jul` (meeting Jul 29-30, 2025; `as_of` 2025-07-23T00:00:00Z)

| # | Title | Source URL | Archive URL (capture time, UTC) | `available_at` | Does not leak the decision because... | Check |
|---|---|---|---|---|---|---|
| 1 | Federal Reserve issues FOMC statement (June 18, 2025; full statement text) | https://www.federalreserve.gov/newsevents/pressreleases/monetary20250618a.htm | https://web.archive.org/web/20250722125212/https://www.federalreserve.gov/newsevents/pressreleases/monetary20250618a.htm (2025-07-22T12:52:12Z) | 2025-06-18T18:00:00Z (EDT) | It is the previous meeting's statement, public since 2025-06-18; it records that earlier decision and says nothing about this meeting's decision. | [x] source ok [x] capture before `as_of` [x] no leak (AI re-check) |
| 2 | Minutes of the Federal Open Market Committee, June 17-18, 2025 (verbatim excerpt: paragraphs containing 'outlook for monetary policy') | https://www.federalreserve.gov/monetarypolicy/fomcminutes20250618.htm | https://web.archive.org/web/20250720011442/https://www.federalreserve.gov/monetarypolicy/fomcminutes20250618.htm (2025-07-20T01:14:42Z) | 2025-07-09T18:00:00Z (EDT) | Minutes of the previous meeting, released 2025-07-09; they summarise views held at that meeting and contain no record of this meeting. | [x] source ok [x] capture before `as_of` [x] no leak (AI re-check) |
| 3 | BLS news release: Consumer Price Index - June 2025 (verbatim excerpt: opening summary paragraphs) | https://www.bls.gov/news.release/archives/cpi_07152025.htm | https://web.archive.org/web/20250719120429/https://www.bls.gov/news.release/archives/cpi_07152025.htm (2025-07-19T12:04:29Z) | 2025-07-15T12:30:00Z (EDT) | Official price statistics, first published 2025-07-15; a BLS release contains no FOMC decision. | [x] source ok [x] capture before `as_of` [x] no leak (AI re-check) |
| 4 | BLS news release: The Employment Situation -- June 2025 (verbatim excerpt: opening summary paragraph) | https://www.bls.gov/news.release/archives/empsit_07032025.htm | https://web.archive.org/web/20250709124512/https://www.bls.gov/news.release/archives/empsit_07032025.htm (2025-07-09T12:45:12Z) | 2025-07-03T12:30:00Z (EDT) | Official labour statistics, first published 2025-07-03; a BLS release contains no FOMC decision. | [x] source ok [x] capture before `as_of` [x] no leak (AI re-check) |

BLS release current at `as_of`, read from the last pre-`as_of` capture of the BLS current-release page: CPI CONSUMER PRICE INDEX - JUNE 2025 (https://web.archive.org/web/20250722101519/https://www.bls.gov/news.release/cpi.nr0.htm); jobs THE EMPLOYMENT SITUATION -- JUNE 2025 (https://web.archive.org/web/20250722200506/https://www.bls.gov/news.release/empsit.nr0.htm). Minutes release time from the Fed press release https://www.federalreserve.gov/newsevents/pressreleases/monetary20250709a.htm.

### `fomc-2025-sep` (meeting Sep 16-17, 2025; `as_of` 2025-09-10T00:00:00Z)

| # | Title | Source URL | Archive URL (capture time, UTC) | `available_at` | Does not leak the decision because... | Check |
|---|---|---|---|---|---|---|
| 1 | Federal Reserve issues FOMC statement (July 30, 2025; full statement text) | https://www.federalreserve.gov/newsevents/pressreleases/monetary20250730a.htm | https://web.archive.org/web/20250902071352/https://www.federalreserve.gov/newsevents/pressreleases/monetary20250730a.htm (2025-09-02T07:13:52Z) | 2025-07-30T18:00:00Z (EDT) | It is the previous meeting's statement, public since 2025-07-30; it records that earlier decision and says nothing about this meeting's decision. | [x] source ok [x] capture before `as_of` [x] no leak (AI re-check) |
| 2 | Minutes of the Federal Open Market Committee, July 29-30, 2025 (verbatim excerpt: paragraphs containing 'outlook for monetary policy') | https://www.federalreserve.gov/monetarypolicy/fomcminutes20250730.htm | https://web.archive.org/web/20250907151145/https://www.federalreserve.gov/monetarypolicy/fomcminutes20250730.htm (2025-09-07T15:11:45Z) | 2025-08-20T18:00:00Z (EDT) | Minutes of the previous meeting, released 2025-08-20; they summarise views held at that meeting and contain no record of this meeting. | [x] source ok [x] capture before `as_of` [x] no leak (AI re-check) |
| 3 | BLS news release: Consumer Price Index - July 2025 (verbatim excerpt: opening summary paragraphs) | https://www.bls.gov/news.release/archives/cpi_08122025.htm | https://web.archive.org/web/20250907181119/https://www.bls.gov/news.release/archives/cpi_08122025.htm (2025-09-07T18:11:19Z) | 2025-08-12T12:30:00Z (EDT) | Official price statistics, first published 2025-08-12; a BLS release contains no FOMC decision. | [x] source ok [x] capture before `as_of` [x] no leak (AI re-check) |
| 4 | BLS news release: The Employment Situation -- August 2025 (verbatim excerpt: opening summary paragraph) | https://www.bls.gov/news.release/archives/empsit_09052025.htm | https://web.archive.org/web/20250906150734/https://www.bls.gov/news.release/archives/empsit_09052025.htm (2025-09-06T15:07:34Z) | 2025-09-05T12:30:00Z (EDT) | Official labour statistics, first published 2025-09-05; a BLS release contains no FOMC decision. | [x] source ok [x] capture before `as_of` [x] no leak (AI re-check) |

BLS release current at `as_of`, read from the last pre-`as_of` capture of the BLS current-release page: CPI CONSUMER PRICE INDEX - JULY 2025 (https://web.archive.org/web/20250909235552/https://www.bls.gov/news.release/cpi.nr0.htm); jobs THE EMPLOYMENT SITUATION -- AUGUST 2025 (https://web.archive.org/web/20250909124036/https://www.bls.gov/news.release/empsit.nr0.htm). Minutes release time from the Fed press release https://www.federalreserve.gov/newsevents/pressreleases/monetary20250820a.htm.

### `fomc-2025-oct` (meeting Oct 28-29, 2025; `as_of` 2025-10-22T00:00:00Z)

| # | Title | Source URL | Archive URL (capture time, UTC) | `available_at` | Does not leak the decision because... | Check |
|---|---|---|---|---|---|---|
| 1 | Federal Reserve issues FOMC statement (September 17, 2025; full statement text) | https://www.federalreserve.gov/newsevents/pressreleases/monetary20250917a.htm | https://web.archive.org/web/20251021133808/https://www.federalreserve.gov/newsevents/pressreleases/monetary20250917a.htm (2025-10-21T13:38:08Z) | 2025-09-17T18:00:00Z (EDT) | It is the previous meeting's statement, public since 2025-09-17; it records that earlier decision and says nothing about this meeting's decision. | [x] source ok [x] capture before `as_of` [x] no leak (AI re-check) |
| 2 | Minutes of the Federal Open Market Committee, September 16-17, 2025 (verbatim excerpt: paragraphs containing 'outlook for monetary policy') | https://www.federalreserve.gov/monetarypolicy/fomcminutes20250917.htm | https://web.archive.org/web/20251011231122/https://www.federalreserve.gov/monetarypolicy/fomcminutes20250917.htm (2025-10-11T23:11:22Z) | 2025-10-08T18:00:00Z (EDT) | Minutes of the previous meeting, released 2025-10-08; they summarise views held at that meeting and contain no record of this meeting. | [x] source ok [x] capture before `as_of` [x] no leak (AI re-check) |
| 3 | BLS news release: Consumer Price Index - August 2025 (verbatim excerpt: opening summary paragraphs) | https://www.bls.gov/news.release/archives/cpi_09112025.htm | https://web.archive.org/web/20251015060958/https://www.bls.gov/news.release/archives/cpi_09112025.htm (2025-10-15T06:09:58Z) | 2025-09-11T12:30:00Z (EDT) | Official price statistics, first published 2025-09-11; a BLS release contains no FOMC decision. | [x] source ok [x] capture before `as_of` [x] no leak (AI re-check) |
| 4 | BLS news release: The Employment Situation -- August 2025 (verbatim excerpt: opening summary paragraph) | https://www.bls.gov/news.release/archives/empsit_09052025.htm | https://web.archive.org/web/20251014015516/https://www.bls.gov/news.release/archives/empsit_09052025.htm (2025-10-14T01:55:16Z) | 2025-09-05T12:30:00Z (EDT) | Official labour statistics, first published 2025-09-05; a BLS release contains no FOMC decision. | [x] source ok [x] capture before `as_of` [x] no leak (AI re-check) |

BLS release current at `as_of`, read from the last pre-`as_of` capture of the BLS current-release page: CPI CONSUMER PRICE INDEX - AUGUST 2025 (https://web.archive.org/web/20251021215237/https://www.bls.gov/news.release/cpi.nr0.htm); jobs THE EMPLOYMENT SITUATION -- AUGUST 2025 (https://web.archive.org/web/20251020062919/https://www.bls.gov/news.release/empsit.nr0.htm). Minutes release time from the Fed press release https://www.federalreserve.gov/newsevents/pressreleases/monetary20251008a.htm.

### `fomc-2025-dec` (meeting Dec 9-10, 2025; `as_of` 2025-12-03T00:00:00Z)

| # | Title | Source URL | Archive URL (capture time, UTC) | `available_at` | Does not leak the decision because... | Check |
|---|---|---|---|---|---|---|
| 1 | Federal Reserve issues FOMC statement (October 29, 2025; full statement text) | https://www.federalreserve.gov/newsevents/pressreleases/monetary20251029a.htm | https://web.archive.org/web/20251202170955/https://www.federalreserve.gov/newsevents/pressreleases/monetary20251029a.htm (2025-12-02T17:09:55Z) | 2025-10-29T18:00:00Z (EDT) | It is the previous meeting's statement, public since 2025-10-29; it records that earlier decision and says nothing about this meeting's decision. | [x] source ok [x] capture before `as_of` [x] no leak (AI re-check) |
| 2 | Minutes of the Federal Open Market Committee, October 28-29, 2025 (verbatim excerpt: paragraphs containing 'outlook for monetary policy') | https://www.federalreserve.gov/monetarypolicy/fomcminutes20251029.htm | https://web.archive.org/web/20251121205427/https://www.federalreserve.gov/monetarypolicy/fomcminutes20251029.htm (2025-11-21T20:54:27Z) | 2025-11-19T19:00:00Z (EST) | Minutes of the previous meeting, released 2025-11-19; they summarise views held at that meeting and contain no record of this meeting. | [x] source ok [x] capture before `as_of` [x] no leak (AI re-check) |
| 3 | BLS news release: Consumer Price Index - September 2025 (verbatim excerpt: opening summary paragraphs) | https://www.bls.gov/news.release/archives/cpi_10242025.htm | https://web.archive.org/web/20251124102414/https://www.bls.gov/news.release/archives/cpi_10242025.htm (2025-11-24T10:24:14Z) | 2025-10-24T12:30:00Z (EDT) | Official price statistics, first published 2025-10-24; a BLS release contains no FOMC decision. | [x] source ok [x] capture before `as_of` [x] no leak (AI re-check) |
| 4 | BLS news release: The Employment Situation -- September 2025 (verbatim excerpt: opening summary paragraph) | https://www.bls.gov/news.release/archives/empsit_11202025.htm | https://web.archive.org/web/20251130230804/https://www.bls.gov/news.release/archives/empsit_11202025.htm (2025-11-30T23:08:04Z) | 2025-11-20T13:30:00Z (EST) | Official labour statistics, first published 2025-11-20; a BLS release contains no FOMC decision. | [x] source ok [x] capture before `as_of` [x] no leak (AI re-check) |

BLS release current at `as_of`, read from the last pre-`as_of` capture of the BLS current-release page: CPI CONSUMER PRICE INDEX - SEPTEMBER 2025 (https://web.archive.org/web/20251202214622/https://www.bls.gov/news.release/cpi.nr0.htm); jobs THE EMPLOYMENT SITUATION -- SEPTEMBER 2025 (https://web.archive.org/web/20251202212501/https://www.bls.gov/news.release/empsit.nr0.htm). Minutes release time from the Fed press release https://www.federalreserve.gov/newsevents/pressreleases/monetary20251119a.htm.

### `fomc-2026-jan` (meeting Jan 27-28, 2026; `as_of` 2026-01-21T00:00:00Z)

| # | Title | Source URL | Archive URL (capture time, UTC) | `available_at` | Does not leak the decision because... | Check |
|---|---|---|---|---|---|---|
| 1 | Federal Reserve issues FOMC statement (December 10, 2025; full statement text) | https://www.federalreserve.gov/newsevents/pressreleases/monetary20251210a.htm | https://web.archive.org/web/20260119010902/https://www.federalreserve.gov/newsevents/pressreleases/monetary20251210a.htm (2026-01-19T01:09:02Z) | 2025-12-10T19:00:00Z (EST) | It is the previous meeting's statement, public since 2025-12-10; it records that earlier decision and says nothing about this meeting's decision. | [x] source ok [x] capture before `as_of` [x] no leak (AI re-check) |
| 2 | Minutes of the Federal Open Market Committee, December 9-10, 2025 (verbatim excerpt: paragraphs containing 'outlook for monetary policy') | https://www.federalreserve.gov/monetarypolicy/fomcminutes20251210.htm | https://web.archive.org/web/20260111215448/https://www.federalreserve.gov/monetarypolicy/fomcminutes20251210.htm (2026-01-11T21:54:48Z) | 2025-12-30T19:00:00Z (EST) | Minutes of the previous meeting, released 2025-12-30; they summarise views held at that meeting and contain no record of this meeting. | [x] source ok [x] capture before `as_of` [x] no leak (AI re-check) |
| 3 | BLS news release: Consumer Price Index - December 2025 (verbatim excerpt: opening summary paragraphs) | https://www.bls.gov/news.release/archives/cpi_01132026.htm | https://web.archive.org/web/20260114150110/https://www.bls.gov/news.release/archives/cpi_01132026.htm (2026-01-14T15:01:10Z) | 2026-01-13T13:30:00Z (EST) | Official price statistics, first published 2026-01-13; a BLS release contains no FOMC decision. | [x] source ok [x] capture before `as_of` [x] no leak (AI re-check) |
| 4 | BLS news release: The Employment Situation -- December 2025 (verbatim excerpt: opening summary paragraph) | https://www.bls.gov/news.release/archives/empsit_01092026.htm | https://web.archive.org/web/20260120204354/https://www.bls.gov/news.release/archives/empsit_01092026.htm (2026-01-20T20:43:54Z) | 2026-01-09T13:30:00Z (EST) | Official labour statistics, first published 2026-01-09; a BLS release contains no FOMC decision. | [x] source ok [x] capture before `as_of` [x] no leak (AI re-check) |

BLS release current at `as_of`, read from the last pre-`as_of` capture of the BLS current-release page: CPI CONSUMER PRICE INDEX - DECEMBER 2025 (https://web.archive.org/web/20260120084402/https://www.bls.gov/news.release/cpi.nr0.htm); jobs THE EMPLOYMENT SITUATION -- DECEMBER 2025 (https://web.archive.org/web/20260120221245/https://www.bls.gov/news.release/empsit.nr0.htm). Minutes release time from the Fed press release https://www.federalreserve.gov/newsevents/pressreleases/monetary20251230a.htm.

### `fomc-2026-mar` (meeting Mar 17-18, 2026; `as_of` 2026-03-11T00:00:00Z)

| # | Title | Source URL | Archive URL (capture time, UTC) | `available_at` | Does not leak the decision because... | Check |
|---|---|---|---|---|---|---|
| 1 | Federal Reserve issues FOMC statement (January 28, 2026; full statement text) | https://www.federalreserve.gov/newsevents/pressreleases/monetary20260128a.htm | https://web.archive.org/web/20260308231320/https://www.federalreserve.gov/newsevents/pressreleases/monetary20260128a.htm (2026-03-08T23:13:20Z) | 2026-01-28T19:00:00Z (EST) | It is the previous meeting's statement, public since 2026-01-28; it records that earlier decision and says nothing about this meeting's decision. | [x] source ok [x] capture before `as_of` [x] no leak (AI re-check) |
| 2 | Minutes of the Federal Open Market Committee, January 27-28, 2026 (verbatim excerpt: paragraphs containing 'outlook for monetary policy') | https://www.federalreserve.gov/monetarypolicy/fomcminutes20260128.htm | https://web.archive.org/web/20260226005222/https://www.federalreserve.gov/monetarypolicy/fomcminutes20260128.htm (2026-02-26T00:52:22Z) | 2026-02-18T19:00:00Z (EST) | Minutes of the previous meeting, released 2026-02-18; they summarise views held at that meeting and contain no record of this meeting. | [x] source ok [x] capture before `as_of` [x] no leak (AI re-check) |
| 3 | BLS news release: Consumer Price Index - January 2026 (verbatim excerpt: opening summary paragraphs) | https://www.bls.gov/news.release/archives/cpi_02132026.htm | https://web.archive.org/web/20260310223821/https://www.bls.gov/news.release/archives/cpi_02132026.htm (2026-03-10T22:38:21Z) | 2026-02-13T13:30:00Z (EST) | Official price statistics, first published 2026-02-13; a BLS release contains no FOMC decision. | [x] source ok [x] capture before `as_of` [x] no leak (AI re-check) |
| 4 | BLS news release: The Employment Situation -- February 2026 (verbatim excerpt: opening summary paragraph) | https://www.bls.gov/news.release/archives/empsit_03062026.htm | https://web.archive.org/web/20260309041200/https://www.bls.gov/news.release/archives/empsit_03062026.htm (2026-03-09T04:12:00Z) | 2026-03-06T13:30:00Z (EST) | Official labour statistics, first published 2026-03-06; a BLS release contains no FOMC decision. | [x] source ok [x] capture before `as_of` [x] no leak (AI re-check) |

BLS release current at `as_of`, read from the last pre-`as_of` capture of the BLS current-release page: CPI CONSUMER PRICE INDEX - JANUARY 2026 (https://web.archive.org/web/20260309014924/https://www.bls.gov/news.release/cpi.nr0.htm); jobs THE EMPLOYMENT SITUATION -- FEBRUARY 2026 (https://web.archive.org/web/20260310154419/https://www.bls.gov/news.release/empsit.nr0.htm). Minutes release time from the Fed press release https://www.federalreserve.gov/newsevents/pressreleases/monetary20260218a.htm.

### `fomc-2026-apr` (meeting Apr 28-29, 2026; `as_of` 2026-04-22T00:00:00Z)

| # | Title | Source URL | Archive URL (capture time, UTC) | `available_at` | Does not leak the decision because... | Check |
|---|---|---|---|---|---|---|
| 1 | Federal Reserve issues FOMC statement (March 18, 2026; full statement text) | https://www.federalreserve.gov/newsevents/pressreleases/monetary20260318a.htm | https://web.archive.org/web/20260420000921/https://www.federalreserve.gov/newsevents/pressreleases/monetary20260318a.htm (2026-04-20T00:09:21Z) | 2026-03-18T18:00:00Z (EDT) | It is the previous meeting's statement, public since 2026-03-18; it records that earlier decision and says nothing about this meeting's decision. | [x] source ok [x] capture before `as_of` [x] no leak (AI re-check) |
| 2 | Minutes of the Federal Open Market Committee, March 17-18, 2026 (verbatim excerpt: paragraphs containing 'outlook for monetary policy') | https://www.federalreserve.gov/monetarypolicy/fomcminutes20260318.htm | https://web.archive.org/web/20260421224321/https://www.federalreserve.gov/monetarypolicy/fomcminutes20260318.htm (2026-04-21T22:43:21Z) | 2026-04-08T18:00:00Z (EDT) | Minutes of the previous meeting, released 2026-04-08; they summarise views held at that meeting and contain no record of this meeting. | [x] source ok [x] capture before `as_of` [x] no leak (AI re-check) |
| 3 | BLS news release: Consumer Price Index - March 2026 (verbatim excerpt: opening summary paragraphs) | https://www.bls.gov/news.release/archives/cpi_04102026.htm | https://web.archive.org/web/20260412034547/https://www.bls.gov/news.release/archives/cpi_04102026.htm (2026-04-12T03:45:47Z) | 2026-04-10T12:30:00Z (EDT) | Official price statistics, first published 2026-04-10; a BLS release contains no FOMC decision. | [x] source ok [x] capture before `as_of` [x] no leak (AI re-check) |
| 4 | BLS news release: The Employment Situation -- March 2026 (verbatim excerpt: opening summary paragraph) | https://www.bls.gov/news.release/archives/empsit_04032026.htm | https://web.archive.org/web/20260418094655/https://www.bls.gov/news.release/archives/empsit_04032026.htm (2026-04-18T09:46:55Z) | 2026-04-03T12:30:00Z (EDT) | Official labour statistics, first published 2026-04-03; a BLS release contains no FOMC decision. | [x] source ok [x] capture before `as_of` [x] no leak (AI re-check) |

BLS release current at `as_of`, read from the last pre-`as_of` capture of the BLS current-release page: CPI CONSUMER PRICE INDEX - MARCH 2026 (https://web.archive.org/web/20260421214548/https://www.bls.gov/news.release/cpi.nr0.htm); jobs THE EMPLOYMENT SITUATION -- March 2026 (https://web.archive.org/web/20260421212726/https://www.bls.gov/news.release/empsit.nr0.htm). Minutes release time from the Fed press release https://www.federalreserve.gov/newsevents/pressreleases/monetary20260408a.htm.

## Draft candidates not used (not part of any case)

The #90 drafts (`docs/curation/fomc-*.md`, items 5 and later) also proposed Board speeches. They are **not** in any case file:
`docs/CASES.md` rule 5 is a fixed four-document list that all 15 cases share, and the #54 cases have no speeches. Adding
speeches to only the 11 new cases would make the cases differ, and choosing which views to add for "balance" (the
drafting agent's note about action-leaning titles) is a judgment call the mechanical rule is meant to avoid. If you want
them, that is a rule change: record it in `docs/CASES.md`, apply it to all 15 cases, and check each speech here the same way.
Nothing to tick in this table.

| Case | Speech (as titled in the draft) | URL |
|---|---|---|
| `fomc-2025-jan` | Reflections on 2024: Monetary Policy, Economic Performance, and Lessons for Banking Regulation (Governor Michelle W. Bowman) | https://www.federalreserve.gov/newsevents/speech/bowman20250109a.htm |
| `fomc-2025-jan` | Challenges Facing Central Bankers (Governor Christopher J. Waller) | https://www.federalreserve.gov/newsevents/speech/waller20250108a.htm |
| `fomc-2025-jan` | An Assessment of the Economy and Financial Stability (Governor Lisa D. Cook) | https://www.federalreserve.gov/newsevents/speech/cook20250106a.htm |
| `fomc-2025-mar` | Economic Outlook (Chair Jerome H. Powell) | https://www.federalreserve.gov/newsevents/speech/powell20250307a.htm |
| `fomc-2025-mar` | The Rebalancing of Labor Markets across the World (Governor Adriana D. Kugler) | https://www.federalreserve.gov/newsevents/speech/kugler20250307a.htm |
| `fomc-2025-mar` | Remarks on "Monetary Policy Transmission to Real Activity" and the Recent Experience (Governor Michelle W. Bowman) | https://www.federalreserve.gov/newsevents/speech/bowman20250307a.htm |
| `fomc-2025-mar` | Managing Financial Crises (Vice Chair for Supervision Michael S. Barr) | https://www.federalreserve.gov/newsevents/speech/barr20250225a.htm |
| `fomc-2025-may` | Welcoming Remarks (Governor Christopher J. Waller) | https://www.federalreserve.gov/newsevents/speech/waller20250423a.htm |
| `fomc-2025-may` | Transmission of Monetary Policy (Governor Adriana D. Kugler) | https://www.federalreserve.gov/newsevents/speech/kugler20250422a.htm |
| `fomc-2025-may` | Economic Mobility and the Dual Mandate (Vice Chair Philip N. Jefferson) | https://www.federalreserve.gov/newsevents/speech/jefferson20250422a.htm |
| `fomc-2025-may` | Economic Outlook (Chair Jerome H. Powell) | https://www.federalreserve.gov/newsevents/speech/powell20250404a.htm |
| `fomc-2025-jun` | The Economic Outlook and Appropriate Monetary Policy (Governor Adriana D. Kugler) | https://www.federalreserve.gov/newsevents/speech/kugler20250605a.htm |
| `fomc-2025-jun` | Economic Outlook (Governor Lisa D. Cook) | https://www.federalreserve.gov/newsevents/speech/cook20250603a.htm |
| `fomc-2025-jun` | The Effects of Tariffs on the Three I’s: Inflation, Inflation Persistence, and Inflation Expectations (Governor Christopher J. Waller) | https://www.federalreserve.gov/newsevents/speech/waller20250601a.htm |
| `fomc-2025-jun` | Liquidity Facilities: Purposes and Functions (Vice Chair Philip N. Jefferson) | https://www.federalreserve.gov/newsevents/speech/jefferson20250519a.htm |
| `fomc-2025-jul` | The Case for Cutting Now (Governor Christopher J. Waller) | https://www.federalreserve.gov/newsevents/speech/waller20250717a.htm |
| `fomc-2025-jul` | AI: A Fed Policymaker's View (Governor Lisa D. Cook) | https://www.federalreserve.gov/newsevents/speech/cook20250717a.htm |
| `fomc-2025-jul` | A View of the Housing Market and U.S. Economic Outlook (Governor Adriana D. Kugler) | https://www.federalreserve.gov/newsevents/speech/kugler20250717a.htm |
| `fomc-2025-jul` | Community Development at the Federal Reserve (Governor Michael S. Barr) | https://www.federalreserve.gov/newsevents/speech/barr20250626a.htm |
| `fomc-2025-sep` | Let’s Get On with It (Governor Christopher J. Waller) | https://www.federalreserve.gov/newsevents/speech/waller20250828a.htm |
| `fomc-2025-sep` | Monetary Policy and the Fed’s Framework Review (Chair Jerome H. Powell) | https://www.federalreserve.gov/newsevents/speech/powell20250822a.htm |
| `fomc-2025-sep` | Thoughts on the Economy and Community Bank Capital (Vice Chair for Supervision Michelle W. Bowman) | https://www.federalreserve.gov/newsevents/speech/bowman20250809a.htm |
| `fomc-2025-oct` | Cutting Rates in the Face of Conflicting Data (Governor Christopher J. Waller) | https://www.federalreserve.gov/newsevents/speech/waller20251016a.htm |
| `fomc-2025-oct` | Understanding the Fed’s Balance Sheet (Chair Jerome H. Powell) | https://www.federalreserve.gov/newsevents/speech/powell20251014a.htm |
| `fomc-2025-oct` | The Economic Outlook and Monetary Policy (Governor Michael S. Barr) | https://www.federalreserve.gov/newsevents/speech/barr20251009a.htm |
| `fomc-2025-oct` | Economic Outlook and the Fed’s Monetary Policy Framework (Vice Chair Philip N. Jefferson) | https://www.federalreserve.gov/newsevents/speech/jefferson20251003a.htm |
| `fomc-2025-dec` | Welcoming Remarks (Governor Michael S. Barr) | https://www.federalreserve.gov/newsevents/speech/barr20251121a.htm |
| `fomc-2025-dec` | Regulatory Dominance of the Federal Reserve’s Balance Sheet (Governor Stephen I. Miran) | https://www.federalreserve.gov/newsevents/speech/miran20251119a.htm |
| `fomc-2025-dec` | The Case for Continuing Rate Cuts (Governor Christopher J. Waller) | https://www.federalreserve.gov/newsevents/speech/waller20251117a.htm |
| `fomc-2025-dec` | Economic Outlook and Monetary Policy (Vice Chair Philip N. Jefferson) | https://www.federalreserve.gov/newsevents/speech/jefferson20251117a.htm |
| `fomc-2026-jan` | Economic Outlook and Monetary Policy Implementation (Vice Chair Philip N. Jefferson) | https://www.federalreserve.gov/newsevents/speech/jefferson20260116a.htm |
| `fomc-2026-jan` | Outlook for the Economy and Monetary Policy (Vice Chair for Supervision Michelle W. Bowman) | https://www.federalreserve.gov/newsevents/speech/bowman20260116a.htm |
| `fomc-2026-jan` | Regulations, the Supply Side, and Monetary Policy (Governor Stephen I. Miran) | https://www.federalreserve.gov/newsevents/speech/miran20260114a.htm |
| `fomc-2026-mar` | Labor Market Data: Signal or Noise? (Governor Christopher J. Waller) | https://www.federalreserve.gov/newsevents/speech/waller20260223a.htm |
| `fomc-2026-mar` | What Will Artificial Intelligence Mean for the Labor Market and the Economy? (Governor Michael S. Barr) | https://www.federalreserve.gov/newsevents/speech/barr20260217a.htm |
| `fomc-2026-mar` | Economic Outlook and Supply-Side (Dis)Inflation Dynamics (Vice Chair Philip N. Jefferson) | https://www.federalreserve.gov/newsevents/speech/jefferson20260206a.htm |
| `fomc-2026-mar` | Economic Outlook (Governor Lisa D. Cook) | https://www.federalreserve.gov/newsevents/speech/cook20260204a.htm |
| `fomc-2026-apr` | Modernizing Federal Reserve Operations in the 21st Century (Governor Christopher J. Waller) | https://www.federalreserve.gov/newsevents/speech/waller20260421a.htm |
| `fomc-2026-apr` | Economic Outlook and the Labor Market (Vice Chair Philip N. Jefferson) | https://www.federalreserve.gov/newsevents/speech/jefferson20260407a.htm |
| `fomc-2026-apr` | Prospects for Shrinking the Fed’s Balance Sheet (Governor Stephen I. Miran) | https://www.federalreserve.gov/newsevents/speech/miran20260326a.htm |

## Sign-off

- [x] All 44 rows above passed the independent AI re-check; none failed, so no case drops under rule 7b.
- [x] The two shutdown-period cases were checked on the BLS archive pages (AI re-check, details below).

Checked by: Claude Code (independent read-only auditor agent), at the request of Yaseen (finance owner).
Date (UTC): 2026-11-14. Manual human check: **not done**.

### What the independent re-check did (2026-11-14)
- **Source:** host is `www.federalreserve.gov` or `www.bls.gov` in all 44; each archive link wraps the same `source_url`;
  titles match the archived document (statement date, minutes meeting dates, BLS release name and month).
- **Capture before `as_of`:** each capture fetched raw (`web.archive.org/web/<ts>id_/<url>`), with no redirect to a
  later capture in any of the 44; all 133 excerpt paragraphs found word for word after whitespace normalization;
  `content_sha256` matches the content in all 44.
- **`available_at`:** equals the printed release time converted to UTC with US daylight-saving dates, in all 44
  (spot check `fomc-2025-dec`, which mixes EDT and EST: 18:00Z / 19:00Z / 12:30Z / 13:30Z, all correct). Each
  `as_of` is 00:00Z seven days before the statement, and item 1 is always the previous scheduled statement.
- **No leak:** for each case the meeting's own statement and the previous one were compared programmatically
  (paragraph, sentence and reverse-sentence tests): nothing that appears only in the own statement is in any case
  file. No excerpt mentions the meeting's own dates. Outcomes were never printed or recorded.
- **Shutdown cases:** the last pre-`as_of` BLS captures show August 2025 CPI and jobs as newest for `fomc-2025-oct`
  and September 2025 for `fomc-2025-dec`; the published schedules put the next releases after `as_of`.
- **CPI boxed notices** (`fomc-2025-mar`, `-jun`, `-sep`): methodology only (seasonal factors; leased cars and
  trucks; wireless telephone services); 0 hits for policy terms (FOMC, federal funds, monetary, rate, Powell, ...).
- **Not checkable:** live bls.gov returns HTTP 403 to automated requests, so BLS text was verified only through
  archive captures; minutes release times came from the live federalreserve.gov press releases.
