# Blind Replay cases (issues #20, #48, #67)

Real, already-resolved yes/no events used by the Blind Replay (SPEC §4, §5; `docs/EVALUATION_PROTOCOL.md`).
Case files: `services/api/data/demo_cases/<event_id>.json`. Sealed results: `services/api/data/sealed_outcomes/<event_id>.json`
(read only by the evaluator). This document never states which way an included case resolved.

Parts 1 and 2 cover the first four real cases (#20). Part 3 (#67) extends the set with one rule to every eligible
FOMC meeting from January 2025 to October 2026 (15 cases, the first four included). The one synthetic fallback case
(issue #48) is not a real event; it has its own section at the end and is never pooled with the real cases.

## Part 1: Selection rule (pre-registered)

This part is committed on its own, **before** the rule was applied, before any evidence was gathered, and
before any result of the selected events was looked up, so the order can be audited in git history. Any later
change to Part 1 is listed under "Changes to the rule" with its reason.

### Why a mechanical rule

The curator is an AI model (Claude) whose training data runs to roughly mid-2026. It may already know how
some 2026 events turned out. If it hand-picked "interesting" events, that knowledge could steer which cases
are chosen (for example, picking events where the market was wrong). The rule below is mechanical: it takes
**every** event in a fixed window, so the curator's knowledge cannot decide which events are included.
The curator does not choose events; it only applies the rule and records any exclusion with its reason.

### Rule

1. **Event family:** decisions on the target range for the federal funds rate announced at **scheduled**
   meetings of the Federal Open Market Committee (FOMC), as listed on the Federal Reserve's FOMC meeting
   calendar (`https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm`). Unscheduled meetings,
   notation votes and conference calls are not cases.
2. **Window:** the **four most recent** scheduled FOMC meetings whose policy statement was released before
   2026-11-13T00:00:00Z (the date this rule was written). All four are taken. None are dropped for being
   "uninteresting".
3. **One binary question per meeting.** The cut / hold / hike outcomes of a meeting are mutually exclusive,
   so they are **not** treated as several independent events. Each meeting becomes exactly one question:
   *"Will the FOMC leave the target range for the federal funds rate unchanged at this meeting?"*
   - YES: the policy statement released at the end of the meeting keeps both the lower and the upper bound
     of the target range equal to the range in effect immediately before the meeting.
   - NO: either bound is changed (a cut or a hike, of any size).
   - Source used to settle the question: the FOMC policy statement on federalreserve.gov.
   - "Hold = YES" was fixed here, before any result was looked up, because it matches the binary markets
     already saved by #12 (Kalshi "Fed maintains rate", Polymarket "no change").
4. **Cutoff (`as_of`):** 00:00:00 UTC on the calendar date exactly **7 days before** the statement release
   date. This is earlier than "7 × 24 hours before the 2:00 p.m. ET announcement", so it errs on the side of
   less information. `horizon_days = 8` (amended by #158; it was 7, see "Question horizon" below): the question
   window `as_of + horizon_days` then ends at 00:00 UTC on the day **after** the statement, so it contains the
   2:00 p.m. ET (18:00Z or 19:00Z) release. With 7 it ended at 00:00 UTC on statement day, before the decision.
5. **Evidence (fixed list, not hand-picked):** for each case, these public documents, taking for each type the
   most recent one whose official release time is at or before `as_of`:
   1. the policy statement of the previous scheduled FOMC meeting (full statement text);
   2. the minutes of the previous scheduled FOMC meeting (verbatim excerpt: the paragraph(s) in which
      participants discuss the outlook for monetary policy);
   3. the U.S. Bureau of Labor Statistics (BLS) Consumer Price Index news release (verbatim excerpt: the
      opening summary paragraphs);
   4. the BLS Employment Situation news release (verbatim excerpt: the opening summary paragraphs).

   Every excerpt is copied exactly from the fetched page (no paraphrase presented as a quote). Each item records
   `published_at` and `available_at` (the official release time stated in the document or its release
   schedule), the source URL, and an Internet Archive (Wayback Machine) capture taken before `as_of` when one
   exists. If a listed document does not exist or cannot be verified for a case, that is recorded; if fewer than
   3 items can be verified, the case is excluded (rule 7).
6. **Market baseline:** market quotes come **only** from snapshots already saved by the #12 adapters under
   `services/api/data/raw/` (this issue may not add new raw files). Benchmark venue: Kalshi (series
   `KXFEDDECISION`, the "maintains rate" market). Polymarket's "no change" market is recorded alongside it when a
   saved snapshot exists. A quote is used only if `as_of − 24h ≤ ts ≤ as_of` (MATH_MODEL §7). If no saved snapshot
   covers a case's `as_of`, the case **stays in** with market baseline `NOT AVAILABLE` (agent-only and naive
   comparisons only), and collecting that snapshot is listed as a follow-up. No price is ever typed by hand,
   interpolated or estimated.
7. **Exclusions (only these reasons):** (a) the meeting's statement cannot be verified on federalreserve.gov;
   (b) fewer than 3 evidence items can be verified with release time ≤ `as_of`; (c) the meeting was not a
   scheduled meeting. Every exclusion is listed below with its reason.
8. **Contamination:** each case records the default replay model's knowledge cutoff (`llama3.1:8b`: December 2023
   per Meta's model card). Events in 2026 are after that cutoff, so `contamination_flag = "unlikely"`, never
   "none". Any other model must be checked against its own card before use.
9. **No tuning on these cases.** All selected cases are held-out test cases. No prompt or template change is
   made after looking at their results (EVALUATION_PROTOCOL §8).

### What this rule cannot fix

- Four events is a small sample. With `n < 5` the scoreboard must show `INSUFFICIENT DATA` (MATH_MODEL §6).
  These cases make the pipeline auditable. They do not support any claim of beating the market.
- All four events come from one family (FOMC decisions), so they are not independent draws from "all macro
  events", and consecutive meetings are correlated.
- The curator's own possible knowledge of 2026 results cannot be removed. The rule only stops it from
  steering *which* cases are included and *which* evidence is shown.

## Part 2: Application of the rule

Applied on 2026-11-13, after Part 1 was committed. **Changes to the rule:** one, on 2026-11-14 (#158): rule 4's
`horizon_days` went from 7 to 8 so the question window contains the announcement (finance review F11). It changes
no selection, cutoff, evidence item or quote; see "Question horizon" after Part 3.

### Step 1: which meetings qualify (rules 1, 2, 7c)

The FOMC calendar (fetched 2026-11-13) lists eight scheduled 2026 meetings: January 27-28, March 17-18,
April 28-29, June 16-17, July 28-29, September 15-16, October 27-28 and December 8-9. It lists no unscheduled
2026 meeting. The four most recent with a statement released before 2026-11-13 are June, July, September and
October. All four are included. December 8-9 has not happened yet. January, March and April fall outside the
"four most recent" window.

**Exclusions: none.** No selected meeting failed rule 7 (a), (b) or (c).

**Considered and not used (outside the rule, not exclusions):** CPI-print or payroll-print events (rule 1 limits
the family to FOMC decisions), the December 2026 meeting (not yet held), January to April 2026 meetings (outside
the window).

### Included cases

| `event_id` | Question (one binary per meeting) | `as_of` (UTC) | Market quote at `as_of` | Evidence items |
|---|---|---|---|---|
| `fomc-2026-jun` | Will the FOMC leave the target range for the federal funds rate unchanged at its June 16-17, 2026 meeting? | 2026-06-10T00:00:00Z | `NOT AVAILABLE` when Part 2 was built (no saved snapshot); quotes added by #153 from the #66 snapshots (Part 3 market table) | 4 |
| `fomc-2026-jul` | ... unchanged at its July 28-29, 2026 meeting? | 2026-07-22T00:00:00Z | Kalshi `KXFEDDECISION-26JUL-H0` ("Fed maintains rate"): bid/ask midpoint **0.855** (bid 0.8500, ask 0.8600), candle ending 2026-07-22T00:00:00Z. Polymarket `1654958` ("no change"): price-history point **0.839** at 2026-07-21T23:00:22Z. Both from the saved #12 snapshots | 4 |
| `fomc-2026-sep` | ... unchanged at its September 15-16, 2026 meeting? | 2026-09-09T00:00:00Z | `NOT AVAILABLE` when Part 2 was built (no saved snapshot); quotes added by #153 (Part 3) | 4 |
| `fomc-2026-oct` | ... unchanged at its October 27-28, 2026 meeting? | 2026-10-21T00:00:00Z | `NOT AVAILABLE` when Part 2 was built (no saved snapshot); quotes added by #153 (Part 3) | 4 |

Market prices are a **market-implied probability (price-derived; affected by fees, spread, liquidity), not a
true probability**. The July quotes were produced by the #12 parsers and normalizer (`parse_candlesticks`,
`parse_prices_history`, `normalize_quotes`) from the exact committed bytes of
`services/api/data/raw/kalshi/KXFEDDECISION-26JUL-H0/20261113T034149253625Z.json` (sha256 `4d0096f8…5461`) and
`services/api/data/raw/polymarket/1654958/20261113T034149701466Z.json` (sha256 `3c53fe2a…e7e7`). The case file holds
every saved quote with `as_of − 24h ≤ ts ≤ as_of` (25 Kalshi, 24 Polymarket). The gate selects the last one per
market. Nothing was typed by hand. Kalshi is the pre-registered benchmark (rule 6). The scored market baseline
comes from the case's `market_quote_id` (`kalshi:KXFEDDECISION-26JUL-H0`, format `venue:market_id`,
EVALUATION_PROTOCOL §7); it is fixed in the case file and never chosen by the caller.

The exact settlement wording is in each case file (`case.resolution_rule`). It is the same for all four cases
apart from the meeting date. It does not name the range in effect before the meeting (see "Cross-case
visibility" below).

**Venue rules vs our rule (July market metadata, read through the #12 adapters on 2026-11-13; it was not
stored).** Kalshi resolves YES on "a Hike of 0bps", and it also counts a cancelled scheduled meeting as "Fed
maintains rate". Polymarket measures the change in the **upper bound** only. Our rule needs **both** bounds
unchanged. The FOMC moves both bounds together, so the three only differ if one bound moves alone or a meeting is
cancelled.

### Step 2: evidence (rule 5)

Each case has exactly the four documents of rule 5. Every item has `published_at = available_at` = the official
release time printed on the document, which is before `as_of` in every case:

| Case | Previous FOMC statement | Previous FOMC minutes | BLS CPI release | BLS Employment Situation |
|---|---|---|---|---|
| `fomc-2026-jun` | Apr 29, 18:00Z | May 20, 18:00Z (Apr 28-29 minutes) | May 12, 12:30Z (April CPI) | Jun 5, 12:30Z (May) |
| `fomc-2026-jul` | Jun 17, 18:00Z | Jul 8, 18:00Z (Jun 16-17 minutes) | Jul 14, 12:30Z (June CPI) | Jul 2, 12:30Z (June) |
| `fomc-2026-sep` | Jul 29, 18:00Z | Aug 19, 18:00Z (Jul 28-29 minutes) | Aug 12, 12:30Z (July CPI) | Sep 4, 12:30Z (August) |
| `fomc-2026-oct` | Sep 16, 18:00Z | Oct 7, 18:00Z (Sep 15-16 minutes) | Oct 14, 12:30Z (September CPI) | Oct 2, 12:30Z (September) |

(All times are 2026, UTC. FOMC: "For release at 2:00 p.m. EDT". BLS: "embargoed until 8:30 a.m. (ET)".)

How the rule was read, mechanically (no judgment calls on content):
- **Statement:** every paragraph between the "For release at 2:00 p.m. EDT" line and "For media inquiries". The
  statement format changed from June 2026 (a shorter statement opening with the vote count). The rule takes it as
  published.
- **Minutes:** every paragraph containing the exact phrase "outlook for monetary policy" (2 paragraphs in the
  April minutes, 1 in each of the others).
- **CPI:** the release's title line plus every paragraph before "Table A.".
- **Employment Situation:** the release's title line plus its first paragraph.
- **"Most recent at or before `as_of`":** for FOMC documents, from the calendar dates. For BLS, the latest Internet
  Archive capture before `as_of` of BLS's "current release" page (`cpi.nr0.htm`, `empsit.nr0.htm`) shows which
  release was current at the cutoff. For example, the last capture before the June case cutoff still shows the April CPI release, so the May CPI was not yet out.

How each item was checked:
- **Federal Reserve pages** were fetched live on 2026-11-13. Each excerpt paragraph was also found word for word
  (after whitespace normalization) in an Internet Archive capture of the same URL taken **before** `as_of`
  (`archive_url`).
- **BLS pages refuse automated requests (HTTP 403)**, so BLS text comes from a pre-`as_of` Internet Archive capture
  of the permanent BLS archive URL (`source_url`, e.g. `bls.gov/news.release/archives/cpi_05122026.htm`). Each
  paragraph was also found in a second pre-`as_of` capture of the BLS current-release page.
- Text is verbatim. HTML tags were removed, entities decoded and whitespace collapsed. Line breaks in BLS's
  preformatted text were joined with spaces. `content_sha256` is the SHA-256 of `content` (UTF-8).
- Classification (kept in each file's `curation_notes.evidence_classification`): statements are official records
  of the policy action (documentary fact) plus the Committee's own guidance (official interpretation, not a numeric
  forecast). Minutes are the Secretariat's summary of participants' views (interpretation). CPI and payroll releases
  are official statistics as first published (documentary fact, subject to revision).
- `retrospective_unverified = false` for all 16 items, because each has a pre-`as_of` archive capture containing the text.

`snapshot_hash` = `sha256:` + SHA-256 of the canonical JSON of the gated payload at `as_of` (evidence plus the
selected quotes, or evidence plus `[]` when the market is `NOT AVAILABLE`), computed with PR #29's
`core.temporal_gate` / `core.provenance` and checked by reloading.

### Step 3: sealed outcomes

Each `services/api/data/sealed_outcomes/<event_id>.json` was written last, from the meeting's own FOMC
statement. It compares that statement's target range with the range in the previous scheduled meeting's statement
(rule 3). It records the statement URL, the verbatim decision sentences and the release time. Case files and this
document contain no outcome.

### Contamination notes (rule 8)

| Case | Event date | `llama3.1:8b` (knowledge cutoff Dec 2023, Meta model card) | `contamination_flag` |
|---|---|---|---|
| `fomc-2026-jun` | June 2026 | after cutoff (about 2.5 years) | `unlikely` |
| `fomc-2026-jul` | July 2026 | after cutoff | `unlikely` |
| `fomc-2026-sep` | September 2026 | after cutoff | `unlikely` |
| `fomc-2026-oct` | October 2026 | after cutoff | `unlikely` |

`unlikely` is not "none". A different replay model (for example a `gemma4` tag) must be checked against its
own model card before these flags are reused. The **curator** (Claude, training data to about mid-2026) may
know some of these results, the June meeting in particular. The mechanical rule stops that from steering
which cases or evidence were picked. It does not make the curator blind.

### Known limits of this case set

- **n = 4 < 5:** the scoreboard must show `INSUFFICIENT DATA` (MATH_MODEL §6). Only one case (July) has a market
  baseline, so a market-only comparison has n = 1.
- **Cross-case visibility.** Consecutive meetings are linked. Each case's evidence includes the previous meeting's
  statement, and that statement *is* the previous case's result (for example, the October case's evidence contains
  the September statement). The temporal gate isolates each case, so a model replaying September never sees it.
  But anyone reading the October case file, or replaying cases in one model session, learns the September
  result. Run each case in a fresh model call, and do not show later cases' evidence in the UI before earlier
  cases are revealed. Because later cases' evidence includes earlier meetings' statements, OFFICIAL runs forecast
  every case before any reveal.
- **The curator read some of this while applying the rule.** Building a later case's evidence meant reading the
  previous meeting's statement and minutes, so the curator saw earlier cases' results before writing the sealed
  files. Selection was already fixed by then (Part 1).
- **One event family, one central bank:** four correlated FOMC decisions are not a broad macro sample.

## Part 3: Every eligible 2025-2026 FOMC meeting (issue #67)

Part 1 took the four most recent meetings, so `n = 4` and the scoreboard can only say `INSUFFICIENT DATA`. Issue #67
widens the window with one rule. It takes every meeting the rule yields and lists any meeting it drops, with the reason.

### Rule

1. **Event family:** the same as Part 1 rule 1 (decisions on the federal funds target range at **scheduled** FOMC
   meetings on the Federal Reserve's FOMC calendar). Unscheduled meetings, notation votes and conference calls are
   not cases.
2. **Window:** every scheduled meeting whose policy statement release date is between 2025-01-01 and 2026-10-31
   (January 2025 to October 2026), inclusive.
3. **Eligibility: priced on both Kalshi and Polymarket 7 days before** (issue #67). A saved snapshot under
   `services/api/data/raw/` (from #12 or #66) must hold at least one priced quote with `as_of − 24h ≤ ts ≤ as_of`
   for **both** (a) the Kalshi "no change" leg `KXFEDDECISION-<meeting>-H0` and (b) the Polymarket "no change"
   market of the same meeting. Both legs come from the pairing in `services/api/data/raw/candidate_plan_51.json`
   (see `docs/CANDIDATE_MARKETS.md`). A meeting that fails this is listed as excluded: "not priced on both venues at
   T−7".
4. **Everything else is unchanged from Part 1:** the one binary question (rule 3, hold = YES), `as_of` (rule 4),
   the fixed four-document evidence list and excerpt method (rule 5), the Kalshi benchmark fixed by
   `market_quote_id` (rule 6), the only allowed exclusion reasons (rule 7), contamination (rule 8) and no tuning
   (rule 9). In rule 6, "#12 snapshots" now means "#12 or #66 snapshots". This issue collected no new raw files.
5. **The four Part 2 cases are reused unchanged.** They are not rebuilt or duplicated.

**Order of work, stated plainly.** The window and the eligibility test are copied from issue #67, which a lead wrote
on 2026-11-13 before this part was applied. The curator (Claude) did not choose them. The curator did write this
part after #66 (market snapshots) and #90 (evidence drafts) were merged, and after reading the Part 2 cases. So it
is not pre-registered in the strict sense that Part 1 is. What limits the curator's influence is that the rule takes
every meeting in a fixed window and has a single mechanical test.

### Step 1: which meetings qualify (rules 1-3, 7)

The FOMC calendar (fetched 2026-11-14) lists eight scheduled meetings in 2025 (January 28-29, March 18-19, May 6-7,
June 17-18, July 29-30, September 16-17, October 28-29, December 9-10) and eight in 2026, of which seven fall in the
window (January 27-28, March 17-18, April 28-29, June 16-17, July 28-29, September 15-16, October 27-28). That makes
15 meetings. The eligibility test was run on the saved snapshots with the #12/#66 parsers, `normalize_quotes` and
`select_quote` (raw bytes taken from git, each checked against its manifest SHA-256).

| Meeting | `event_id` | `as_of` (UTC) | Priced on both venues at T−7 (rule 3) | Status | Market baseline in the case file | Evidence items |
|---|---|---|---|---|---|---|
| Jan 28-29, 2025 | `fomc-2025-jan` | 2025-01-22T00:00:00Z | yes | included (new) | available | 4 |
| Mar 18-19, 2025 | `fomc-2025-mar` | 2025-03-12T00:00:00Z | yes | included (new) | available | 4 |
| May 6-7, 2025 | `fomc-2025-may` | 2025-04-30T00:00:00Z | yes | included (new) | available | 4 |
| Jun 17-18, 2025 | `fomc-2025-jun` | 2025-06-11T00:00:00Z | yes | included (new) | available | 4 |
| Jul 29-30, 2025 | `fomc-2025-jul` | 2025-07-23T00:00:00Z | yes | included (new) | available | 4 |
| Sep 16-17, 2025 | `fomc-2025-sep` | 2025-09-10T00:00:00Z | yes | included (new) | available | 4 |
| Oct 28-29, 2025 | `fomc-2025-oct` | 2025-10-22T00:00:00Z | yes | included (new) | available | 4 |
| Dec 9-10, 2025 | `fomc-2025-dec` | 2025-12-03T00:00:00Z | yes | included (new) | available | 4 |
| Jan 27-28, 2026 | `fomc-2026-jan` | 2026-01-21T00:00:00Z | yes | included (new) | available | 4 |
| Mar 17-18, 2026 | `fomc-2026-mar` | 2026-03-11T00:00:00Z | yes | included (new) | available | 4 |
| Apr 28-29, 2026 | `fomc-2026-apr` | 2026-04-22T00:00:00Z | yes | included (new) | available | 4 |
| Jun 16-17, 2026 | `fomc-2026-jun` | 2026-06-10T00:00:00Z | yes (#66 snapshots) | included (Part 2; quotes added by #153) | available | 4 |
| Jul 28-29, 2026 | `fomc-2026-jul` | 2026-07-22T00:00:00Z | yes | included (Part 2, unchanged) | available | 4 |
| Sep 15-16, 2026 | `fomc-2026-sep` | 2026-09-09T00:00:00Z | yes (#66 snapshots) | included (Part 2; quotes added by #153) | available | 4 |
| Oct 27-28, 2026 | `fomc-2026-oct` | 2026-10-21T00:00:00Z | yes (#66 snapshots) | included (Part 2; quotes added by #153) | available | 4 |

**Exclusions: none.** All 15 meetings pass rule 3, and none fails rule 7 (a), (b) or (c).

**Considered, not cases:** the August 22, 2025 notation vote (rule 1: it approved the Statement on Longer-Run Goals
and Monetary Policy Strategy and was not a scheduled rate meeting); December 8-9, 2026 (outside the window and not
held yet); December 17-18, 2024 (outside the window; its statement and minutes are evidence for `fomc-2025-jan`).

**June, September and October 2026.** #66 saved T−7 snapshots for these meetings on both venues (Kalshi
`KXFEDDECISION-26JUN-H0`, `-26SEP-H0`, `-26OCT-H0`; Polymarket `906974`, `2252244`, `2589812`), so they pass rule 3. Their
case files were built under Part 2 before those snapshots existed, and #67 reused them unchanged with
`market_quotes: []`. **Issue #153 added their quotes** with exactly the procedure used for the 11 new files (below):
the #66 raw bytes, each checked against its manifest SHA-256 and against `origin/main`, re-parsed with
`parse_candlesticks` / `parse_prices_history` and `normalize_quotes`, keeping every quote with
`as_of − 24h ≤ ts ≤ as_of`. Before writing anything, the same code rebuilt the committed quotes of all 12 cases that
already had them (the 11 new files and `fomc-2026-jul`) and matched every one exactly. All three new quote sets fall
inside the 24-hour window, so each file now sets `market_quote_id = kalshi:KXFEDDECISION-26{JUN,SEP,OCT}-H0`. This
changed their `snapshot_hash` (now the `agent_plus_market` payload) and `case_sha256`; no recorded run had been
committed for them, so nothing recorded is invalidated. `data/raw` was not modified.

### Market quotes in the case files

Each of these 14 files (the 11 new ones, plus June, September and October 2026 since #153) holds every saved quote with `as_of − 24h ≤ ts ≤ as_of` for both markets (Kalshi first, then
Polymarket). The gate selects the last quote per market. The scored baseline is the Kalshi market named in
`market_quote_id` (`kalshi:<market_id>`), fixed in the file. Prices are a **market-implied probability (price-derived;
affected by fees, spread, liquidity), not a true probability**. Nothing was typed by hand, interpolated or estimated.

| Case | Kalshi quote selected at `as_of` (benchmark) | Polymarket quote selected at `as_of` | Quotes in file (Kalshi / Polymarket) |
|---|---|---|---|
| `fomc-2025-jan` | `KXFEDDECISION-25JAN-H0` ("No change"): midpoint **0.985** (bid 0.9800, ask 0.9900), candle ending 2025-01-21T23:00:00Z | `512324`: price-history point **0.978** at 2025-01-21T23:00:04Z | 3 / 24 |
| `fomc-2025-mar` | `KXFEDDECISION-25MAR-H0` ("No change"): midpoint **0.975** (bid 0.9700, ask 0.9800), candle ending 2025-03-11T17:00:00Z | `516010`: price-history point **0.9655** at 2025-03-11T23:00:05Z | 10 / 24 |
| `fomc-2025-may` | `KXFEDDECISION-25MAY-H0` ("No change"): midpoint **0.865** (bid 0.8600, ask 0.8700), candle ending 2025-04-30T00:00:00Z | `519778`: price-history point **0.895** at 2025-04-29T23:00:06Z | 21 / 24 |
| `fomc-2025-jun` | `KXFEDDECISION-25JUN-H0` ("No change"): midpoint **0.97** (bid 0.9600, ask 0.9800), candle ending 2025-06-11T00:00:00Z | `521836`: price-history point **0.9735** at 2025-06-10T23:00:07Z | 21 / 24 |
| `fomc-2025-jul` | `KXFEDDECISION-25JUL-H0` ("Fed maintains rate"): midpoint **0.945** (bid 0.9400, ask 0.9500), candle ending 2025-07-23T00:00:00Z | `528974`: price-history point **0.9555** at 2025-07-22T23:00:09Z | 22 / 24 |
| `fomc-2025-sep` | `KXFEDDECISION-25SEP-H0` ("Fed maintains rate"): midpoint **0.055** (bid 0.0500, ask 0.0600), candle ending 2025-09-10T00:00:00Z | `542539`: price-history point **0.04** at 2025-09-09T23:00:10Z | 25 / 24 |
| `fomc-2025-oct` | `KXFEDDECISION-25OCT-H0` ("Fed maintains rate"): midpoint **0.025** (bid 0.0200, ask 0.0300), candle ending 2025-10-22T00:00:00Z | `553812`: price-history point **0.0225** at 2025-10-21T23:00:17Z | 25 / 24 |
| `fomc-2025-dec` | `KXFEDDECISION-25DEC-H0` ("Fed maintains rate"): midpoint **0.085** (bid 0.0800, ask 0.0900), candle ending 2025-12-03T00:00:00Z | `570362`: price-history point **0.075** at 2025-12-02T23:00:28Z | 25 / 24 |
| `fomc-2026-jan` | `KXFEDDECISION-26JAN-H0` ("Fed maintains rate"): midpoint **0.965** (bid 0.9600, ask 0.9700), candle ending 2026-01-21T00:00:00Z | `601699`: price-history point **0.972** at 2026-01-20T23:00:18Z | 25 / 24 |
| `fomc-2026-mar` | `KXFEDDECISION-26MAR-H0` ("Fed maintains rate"): midpoint **0.985** (bid 0.9800, ask 0.9900), candle ending 2026-03-11T00:00:00Z | `654414`: price-history point **0.9885** at 2026-03-10T23:00:30Z | 25 / 24 |
| `fomc-2026-apr` | `KXFEDDECISION-26APR-H0` ("Fed maintains rate"): midpoint **0.985** (bid 0.9800, ask 0.9900), candle ending 2026-04-22T00:00:00Z | `669662`: price-history point **0.9935** at 2026-04-21T23:00:43Z | 25 / 11 |
| `fomc-2026-jun` (#153) | `KXFEDDECISION-26JUN-H0` ("Fed maintains rate"): midpoint **0.985** (bid 0.9800, ask 0.9900), candle ending 2026-06-10T00:00:00Z | `906974`: price-history point **0.9905** at 2026-06-09T23:00:05Z | 25 / 24 |
| `fomc-2026-sep` (#153) | `KXFEDDECISION-26SEP-H0` ("Fed maintains rate"): midpoint **0.455** (bid 0.4500, ask 0.4600), candle ending 2026-09-09T00:00:00Z | `2252244`: price-history point **0.455** at 2026-09-08T23:00:18Z | 25 / 24 |
| `fomc-2026-oct` (#153) | `KXFEDDECISION-26OCT-H0` ("Fed maintains rate"): midpoint **0.875** (bid 0.8700, ask 0.8800), candle ending 2026-10-21T00:00:00Z | `2589812`: price-history point **0.855** at 2026-10-20T23:00:22Z | 25 / 24 |

The #153 raw files are `services/api/data/raw/kalshi/KXFEDDECISION-26JUN-H0/20261113T175759977809Z.json`
(sha256 `48cefbd1…c1d1`), `…/KXFEDDECISION-26SEP-H0/20261113T175808560430Z.json` (`6b27563e…d8b9`),
`…/KXFEDDECISION-26OCT-H0/20261113T175816953742Z.json` (`42559c0f…39dc`), `polymarket/906974/20261113T175800502149Z.json`
(`734abff4…2f49`), `polymarket/2252244/20261113T175808962655Z.json` (`b248f4c4…d454`) and
`polymarket/2589812/20261113T175817475345Z.json` (`5cba1add…403c`), each matching its `manifest.json`.

Venue rules compared with ours: Kalshi YES means "a Hike of 0bps", and Polymarket measures the change in the upper
bound only. Our rule needs **both** bounds unchanged. The three agree unless one bound moves alone. A cancelled meeting
is treated differently: for the January to June 2025 Kalshi markets every strike resolves No, later Kalshi markets
resolve "Fed maintains rate" Yes, and Polymarket resolves "No change" if no statement is released by the end of the
next meeting (`docs/CANDIDATE_MARKETS.md`, "FOMC rule edge cases"; #66 read the rule text and it was not re-read
here). Kalshi markets are thin in early 2025: `fomc-2025-jan` has only 3 Kalshi quotes in the 24-hour window, and the
`fomc-2025-mar` quote is from 17:00Z the day before `as_of`. Both are inside the 24-hour staleness limit.

### Step 2: evidence (rule 5, same method as Part 2)

Each new case has exactly the four documents of rule 5. The excerpts were made by the same extraction code as Part 2,
which was first checked to reproduce all 16 Part 2 excerpts byte for byte (same `content_sha256`). Release times
are the ones printed on the documents. The Fed prints "For release at 2:00 p.m. EST" or "EDT" (19:00Z or 18:00Z).
BLS prints "8:30 a.m. (ET)", converted with US daylight-saving dates (13:30Z or 12:30Z).

| Case | Previous FOMC statement | Previous FOMC minutes | BLS CPI release | BLS Employment Situation |
|---|---|---|---|---|
| `fomc-2025-jan` | Dec 18 2024, 19:00Z | Jan 8 2025, 19:00Z (December 17-18, 2024 minutes) | Jan 15 2025, 13:30Z (December 2024 CPI) | Jan 10 2025, 13:30Z (December 2024) |
| `fomc-2025-mar` | Jan 29 2025, 19:00Z | Feb 19 2025, 19:00Z (January 28-29, 2025 minutes) | Feb 12 2025, 13:30Z (January 2025 CPI) | Mar 7 2025, 13:30Z (February 2025) |
| `fomc-2025-may` | Mar 19 2025, 18:00Z | Apr 9 2025, 18:00Z (March 18-19, 2025 minutes) | Apr 10 2025, 12:30Z (March 2025 CPI) | Apr 4 2025, 12:30Z (March 2025) |
| `fomc-2025-jun` | May 7 2025, 18:00Z | May 28 2025, 18:00Z (May 6-7, 2025 minutes) | May 13 2025, 12:30Z (April 2025 CPI) | Jun 6 2025, 12:30Z (May 2025) |
| `fomc-2025-jul` | Jun 18 2025, 18:00Z | Jul 9 2025, 18:00Z (June 17-18, 2025 minutes) | Jul 15 2025, 12:30Z (June 2025 CPI) | Jul 3 2025, 12:30Z (June 2025) |
| `fomc-2025-sep` | Jul 30 2025, 18:00Z | Aug 20 2025, 18:00Z (July 29-30, 2025 minutes) | Aug 12 2025, 12:30Z (July 2025 CPI) | Sep 5 2025, 12:30Z (August 2025) |
| `fomc-2025-oct` | Sep 17 2025, 18:00Z | Oct 8 2025, 18:00Z (September 16-17, 2025 minutes) | Sep 11 2025, 12:30Z (August 2025 CPI) | Sep 5 2025, 12:30Z (August 2025) |
| `fomc-2025-dec` | Oct 29 2025, 18:00Z | Nov 19 2025, 19:00Z (October 28-29, 2025 minutes) | Oct 24 2025, 12:30Z (September 2025 CPI) | Nov 20 2025, 13:30Z (September 2025) |
| `fomc-2026-jan` | Dec 10 2025, 19:00Z | Dec 30 2025, 19:00Z (December 9-10, 2025 minutes) | Jan 13 2026, 13:30Z (December 2025 CPI) | Jan 9 2026, 13:30Z (December 2025) |
| `fomc-2026-mar` | Jan 28 2026, 19:00Z | Feb 18 2026, 19:00Z (January 27-28, 2026 minutes) | Feb 13 2026, 13:30Z (January 2026 CPI) | Mar 6 2026, 13:30Z (February 2026) |
| `fomc-2026-apr` | Mar 18 2026, 18:00Z | Apr 8 2026, 18:00Z (March 17-18, 2026 minutes) | Apr 10 2026, 12:30Z (March 2026 CPI) | Apr 3 2026, 12:30Z (March 2026) |

How each item was checked (automated; the human check is below):
- **Federal Reserve pages** (statements, minutes, and the minutes press releases for the release time) were fetched
  live on 2026-11-14 (`observed_at`). Each excerpt paragraph was also found word for word (after whitespace
  normalization) in the latest Internet Archive capture of the same URL taken **before** `as_of` (`archive_url`).
- **BLS pages refuse automated requests (HTTP 403, rechecked 2026-11-14).** BLS text therefore comes from the
  latest pre-`as_of` capture of the permanent BLS archive URL, and each paragraph was also found in the latest
  pre-`as_of` capture of BLS's current-release page (`cpi.nr0.htm`, `empsit.nr0.htm`). That second capture also
  decides which release was current at `as_of`. All 22 choices match the #90 drafts.
- **CPI excerpts with a boxed notice.** Rule 5 takes every paragraph before "Table A.". In the releases used by
  `fomc-2025-mar`, `fomc-2025-jun` and `fomc-2025-sep`, BLS printed a boxed methodology notice (annual weight
  update, discontinued series, data-collection changes) before Table A, so those excerpts include it verbatim,
  dashed border lines included. Those notices are about methodology and say nothing about policy.
- **Late-2025 shutdown period.** For `fomc-2025-oct` the last pre-`as_of` current-release captures still show the
  August CPI (September 11) and August jobs report (September 5). Each capture names a later scheduled date that
  had already passed, so no newer release was on the page. For `fomc-2025-dec` they show the September CPI
  (October 24) and the September jobs report (November 20). The curator added no explanation from memory.
- `retrospective_unverified = false` for all 44 new items. This records the automated check: each item has a
  pre-`as_of` archive capture that contains its text.
- **Confirmation (issue #67).** Each item's source, capture before `as_of` and no-leak status is recorded in
  `docs/curation/VERIFY_67.md`. At the finance owner's request this was done by an independent AI re-check (a separate
  read-only auditor agent; all 44 items passed), **not** by a manual human check. The lead decides whether that is
  enough for admission; any row can be re-checked by hand with the steps in that file.
- **Draft candidates not used.** The #90 drafts (`docs/curation/fomc-*.md`) also proposed up to four Board
  speeches per meeting. Rule 5 is a fixed four-document list, the same for all 15 cases, so the speeches are not
  part of any case. `VERIFY_67.md` lists them, and adding them would need a rule change recorded here.

`snapshot_hash` was computed exactly as in Part 2 (`agent_plus_market` payload when a quote is selected) and checked
by reloading every case through `EvidenceStore`. The four Part 2 hashes still match. After #153 added the June,
September and October 2026 quotes, their `snapshot_hash` was recomputed the same way (`agent_plus_market` payload)
with the loader on `main` at `6698a5f`, and all 16 committed case hashes (15 FOMC plus the synthetic case) were
re-checked to match.

### Step 3: sealed outcomes

Each new `services/api/data/sealed_outcomes/<event_id>.json` was written last, from the meeting's own FOMC statement.
Like Part 2, it compares that statement's target range with the range in the previous scheduled meeting's statement
(rule 3). It records the statement URL, the verbatim decision sentence and the release time. As a second check
from an independent source, the range was also read from the FOMC's directive in the Implementation Note issued with
each of the two statements. For all 11 cases the directive's range matched its statement, and the two sources gave
the same result. Case files, this document and `VERIFY_67.md` contain no outcome.

### Contamination notes (rule 8)

All 15 events (January 2025 to October 2026) come after the `llama3.1:8b` knowledge cutoff (December 2023, Meta
model card), so `contamination_flag = "unlikely"` (never "none"). Any other replay model must be checked against its
own card first. The **curator** (Claude, training data to about mid-2026) very likely knows the 2025 results. The
mechanical rule keeps that knowledge from choosing which meetings or evidence go in. It does not make the curator
blind.

### Known limits of the extended set

- **Scored n = 15 real cases** in each variant. Since #153 all 15 committed files have a Kalshi market baseline at
  `as_of`, so neither `agent_only` nor `agent_plus_market` excludes any case as `market_not_available`, and the
  agent-vs-market comparison also has n = 15 (provided each case has exactly one forecast per variant persisted
  before any reveal; otherwise the scorecard lists the exclusion and its reason). MATH_MODEL §6: n ≥ 5, so the
  scoreboard does not show `INSUFFICIENT DATA`; n < 30, so the small-sample caveat must be shown; and a forecaster may
  be called "better" only if the bootstrap CI of the score difference excludes 0.
- **Correlated draws.** 15 consecutive decisions of one committee are not independent, and the market priced
  several of them close to 0 or 1. A small CI computed on them still overstates how much they tell us.
- **Cross-case visibility now runs through 15 meetings.** Each case's first evidence item is the previous meeting's
  statement, which is the previous case's result (for example `fomc-2025-mar` contains the statement that settles
  `fomc-2025-jan`, and `fomc-2026-jun` contains the one that settles `fomc-2026-apr`). Run every case in a fresh
  model call. OFFICIAL runs forecast **all** cases before **any** reveal (the evaluator enforces this). For live
  demos: **reveal cases in date order on stage**, so the audience is not shown a later case's evidence (which
  contains the earlier result) before the earlier case is revealed. This is presentation advice; the UI does not
  enforce it in code.
- **The curator read earlier results while building later cases**, as in Part 2. The selection was already fixed by
  rules 1-3.

### Question horizon (issue #158, finance review F11)

The finance review (`docs/FINANCE_REVIEW.md`, item R3 and issue F11) found that `horizon_days = 7` ended the
question window at 00:00 UTC on statement day: `as_of` is 00:00 UTC seven calendar days before the statement, and the
statement comes out at 2:00 p.m. ET (18:00Z or 19:00Z) that day. The prompt line "Horizon: 7 days after the cutoff",
the integrity panel's "Question horizon ends" and the contamination check (model card vs. `as_of + horizon_days`,
`scripts/record_runs.py` and `/api/integrity`) all used that too-early end.

**Rule now:** `horizon_days = 8` for all 15 FOMC cases, so the window ends at 00:00 UTC on the day after the
statement and contains the release. 8 days was chosen over an exact end instant because the case schema has only
`horizon_days`, and adding a field for this was not worth it. The `title` and `resolution_rule` texts name the
meeting, not a number of days, so they did not change. The synthetic case (21 days, "within the 21 days after the
cutoff") already covers its resolution time and is unchanged.

**How it was checked (no outcome value read or printed):**
`tests/test_replay_seal.py::test_repo_case_horizon_covers_the_sealed_resolution_time` persists a forecast for every
committed case into the scratch test store, reveals it through `OutcomeVault.reveal` (the only sealed-folder reader)
and keeps only booleans: `resolved_at` is present, later than `as_of`, and no later than `as_of + horizon_days`. Only
case ids reach the assertion. Run on `origin/main` before this change, it failed for all 15 FOMC cases and passed for
the synthetic case; with 8 days it passes for all 16.

**Hashes.** `snapshot_hash` covers the gated evidence and quotes only, so it did not change; all 16 were recomputed
(`agent_plus_market` payload) with the loader and still match. `case_sha256` covers the whole case record, so it
changed for the 15 FOMC cases, and every prompt's `prompt_sha256` changes with the horizon line. No recorded run or
forecast had been committed for the old content, so nothing recorded is invalidated. The synthetic case's
`case_sha256` stays `51623d9b…`.

| Case | `as_of` (UTC) | Window ends (`as_of` + 8 d) | `snapshot_hash` (unchanged) | `case_sha256` before | `case_sha256` now |
|---|---|---|---|---|---|
| `fomc-2025-jan` | 2025-01-22T00:00:00Z | 2025-01-30T00:00:00Z | `14f56855…3e34` | `03bda4da…` | `8c92f17f6029381a51b6e0cad45660be116fae5360bd81eefb23d5b8d147853d` |
| `fomc-2025-mar` | 2025-03-12T00:00:00Z | 2025-03-20T00:00:00Z | `c6fc4e00…c6b7` | `c4af6ed0…` | `20750f087abf5640b9696353a55dae60e8c000c387e0b3a3b4621e119c4b690d` |
| `fomc-2025-may` | 2025-04-30T00:00:00Z | 2025-05-08T00:00:00Z | `a6fd5248…2a4f` | `afc8b4a8…` | `a0984c6ea9eb2761956dd66cf8745e6eaf10249354e7632b92644ea17450382b` |
| `fomc-2025-jun` | 2025-06-11T00:00:00Z | 2025-06-19T00:00:00Z | `4b49ade4…0639` | `909fe261…` | `e2d6f7d6fb23df3c41dc1659f723c3e9e67c17a96dba1b5df0764d96b3c5512f` |
| `fomc-2025-jul` | 2025-07-23T00:00:00Z | 2025-07-31T00:00:00Z | `4a836200…1075` | `c5b02866…` | `6ca7cb6f97f9526d4703d55d9ce76304b301101cf69ac37d479977f508919a28` |
| `fomc-2025-sep` | 2025-09-10T00:00:00Z | 2025-09-18T00:00:00Z | `b9a76428…cea8` | `cbdb65ce…` | `3b91ecf60b4d937983faee7006d7c9eb35509d5d50c94c483cb81baf07e38b08` |
| `fomc-2025-oct` | 2025-10-22T00:00:00Z | 2025-10-30T00:00:00Z | `53be0774…223c` | `ae4fe23b…` | `817d551f64bb8fbbba030397bbe51dee0203c4a49720bfd1d6c8193c810e478f` |
| `fomc-2025-dec` | 2025-12-03T00:00:00Z | 2025-12-11T00:00:00Z | `1c3cb864…5227` | `635ad6b4…` | `019238ad3b27562c7260a382dcc9ec189aae1d2518f399ef316a1be5b78e9c23` |
| `fomc-2026-jan` | 2026-01-21T00:00:00Z | 2026-01-29T00:00:00Z | `88bbcd74…ba0d` | `5216aab9…` | `0abcd61e1eb516e85cd84d0db090c437eabc6576f70e28a8bd1547262497cadf` |
| `fomc-2026-mar` | 2026-03-11T00:00:00Z | 2026-03-19T00:00:00Z | `e0ec861b…e316` | `10330979…` | `1f91068a77741980c15ed3f87f8886616d071ade63b44212c67dc11406f36b5c` |
| `fomc-2026-apr` | 2026-04-22T00:00:00Z | 2026-04-30T00:00:00Z | `c47067b0…7e43` | `22942fc4…` | `464cfebf37c34be555486155bd79f44a86787a596d4dd6f22b5acaa12d2079b4` |
| `fomc-2026-jun` | 2026-06-10T00:00:00Z | 2026-06-18T00:00:00Z | `38a4a962…88ac` | `c342557b…` | `7ed1c7d2924a312a0c93fc0c6307e1e8aec7d3e59cd941e67035563c444ee6ef` |
| `fomc-2026-jul` | 2026-07-22T00:00:00Z | 2026-07-30T00:00:00Z | `e54cf9f4…4bf9` | `d65e55c7…` | `d2ca9b2d2a17097ffb4e5137c2173cd8e9b11ab237ceb5501f3e09cfa569c54a` |
| `fomc-2026-sep` | 2026-09-09T00:00:00Z | 2026-09-17T00:00:00Z | `dd201a12…340d` | `444c9d35…` | `da9eba97e5145c46a8de5bfe5f6b4e3ced31105e3265c40242eebe2aefd59917` |
| `fomc-2026-oct` | 2026-10-21T00:00:00Z | 2026-10-29T00:00:00Z | `488bafc5…65de` | `48d445d7…` | `795cba2e2c075be9f6a5a89b6562076f5796cf029a6eb986bc97e9b325c54ffc` |

## Synthetic fallback case (issue #48)

SPEC §9 P0 item 3 asks for "one explicitly synthetic fallback case", and SPEC §5 control (a) asks for
"synthetic never-before-seen cases with sealed random outcomes". This case lets the replay run end to end
without any real case, and no model can have seen its answer in pretraining, because the answer is a fresh
random draw.

| Field | Value |
|---|---|
| `event_id` | `synthetic_distributor-depot` |
| Provenance | `SYNTHETIC` everywhere (`synthetic: true`, case and every evidence item) |
| Question | SYNTHETIC: Will the demo grocer's primary distributor (the fictional Brindlewick Provisions) stop deliveries from its North depot for 5 or more consecutive days within 21 days after the cutoff? |
| `as_of` | `2026-09-14T12:00:00Z` (a synthetic timeline, not a real event) |
| `horizon_days` | 21 |
| Evidence | 5 invented documents, all with `published_at = available_at <= as_of` |
| Market price | SYNTHETIC 0.35 on the `synthetic` venue (see below) |
| `contamination_flag` | `unlikely` (never "none") |

### What the case is about

The "demo grocer" is FAULTLINE's fictional three-store food retailer (`data/demo_business.json`). The question
matches the `supplier-outage-3wk` scenario: if the primary distributor stops, the lines behind 40% of base-store
sales are lost unless the grocer pays the backup supplier's 12% premium and 2,000 switching fee (the same
`backup_premium` and `backup_switch_fee` as the demo business). The decision is act (switch those lines now),
hedge (arrange a partial response now) or wait. The model's backup-supplier choice is yes/no (MATH_MODEL §4), so
"partial" means some other partial step, not switching a share of the lines.

Every name is invented: Brindlewick Provisions, the Brindlewick North Depot Workers' Association, Corran Valley
Foods, Harrowmere, The Harrowmere Ledger, Mill Lane. Each evidence text starts with "SYNTHETIC DOCUMENT:
fictional, written for the FAULTLINE demo". `source_url` values use the reserved `.invalid` domain
(RFC 2606), which cannot resolve, so no real website is presented as a source. `archive_url` is empty.

| Evidence id (`synthetic_distributor-depot.` + ...) | Title | `available_at` |
|---|---|---|
| `contract-bulletin` | SYNTHETIC: Brindlewick Provisions customer bulletin - North depot labour contract talks | 2026-08-25T15:00:00Z |
| `account-manager-letter` | SYNTHETIC: Letter from Brindlewick account manager to the demo grocer on contingency plans | 2026-09-04T14:00:00Z |
| `local-paper-vote` | SYNTHETIC: The Harrowmere Ledger - depot workers vote to authorise strike if no deal | 2026-09-10T18:30:00Z |
| `road-notice` | SYNTHETIC: Harrowmere County roads notice - Mill Lane resurfacing near North depot | 2026-09-12T09:00:00Z |
| `backup-supplier-quote` | SYNTHETIC: Corran Valley Foods quote to the demo grocer for backup supply | 2026-09-13T16:00:00Z |

### How the answer was fixed: a committed fair draw

The answer was not chosen by anyone. It comes from a random seed and a fixed rule:

1. **The rule** (written down before the seed was generated; that is the author's statement, see the honest
   timeline below):
   - seed = 32 random bytes from Python `secrets.token_bytes(32)` (the operating system's cryptographic random
     generator);
   - commitment = SHA-256 of the 32 raw seed bytes;
   - h = SHA-256 of (the 32 seed bytes followed by the ASCII text `faultline-synthetic-draw:synthetic_distributor-depot`),
     read as a 256-bit whole number;
   - **YES if 100 × h < 35 × 2^256, otherwise NO.** Since h is uniform on [0, 2^256), P(YES) = 0.35 exactly.
     The comparison uses whole numbers only, so there is no rounding.
2. **The seed was generated** at 2026-11-13T20:00:29Z on the author's machine.
3. **Only the commitment is in the case file** (`curation_notes.fair_draw.commitment_sha256`
   = `583b87ea7ab1261948541f56ca5a38703efb6cdeef6307a254ab7d3d40d60f38`), together with the rule above. The case
   file has no key that looks like an answer, and the gate never puts `curation_notes` into a prompt.
4. **The seed and the drawn answer are only in the sealed file** (`notes` holds `seed_hex=...`, because the
   sealed-file format allows no other extra field). Only `OutcomeVault.reveal` reads that file, and only after
   a forecast is saved.

**Why p_draw = 0.35.** 0.35 is part of the rule in step 1, written down before the seed was generated (the author's
statement). The documents describe a real but minority risk
(a strike was authorised, but both sides call the talks constructive and a mediator is booked). The draw does not
depend on the text, so the best possible forecast for this case is 0.35, and no forecaster can beat that in
expectation. The case's SYNTHETIC market price (added in #105, see below) is therefore 0.35, which makes the
synthetic "market" calibrated by construction.

**Honest timeline.** The seed was generated at 2026-11-13T20:00:29Z. The case file (with the commitment and the
rule) was committed at 20:38:53Z and the sealed file at 20:38:56Z, in a later commit of the same PR. Git commit
times are set by the author, so this order is documentation, not proof, and git cannot prove that the rule was
written down before the seed was generated. The case file, evidence included, was committed about 38 minutes after
the seed was generated, so this scheme does not prove the evidence was frozen before the draw.
What does hold: the commitment is in the reviewed PR before any forecast is run, and the store's
persist-before-reveal ledger stops anyone revealing the answer for a forecast that was not saved first.

**What the commitment does and does not prove.**
- It proves the answer was fixed before any forecast was made and cannot be changed afterwards: a different seed
  would not match the published SHA-256.
- It does **not** prove the seed was drawn only once. The person who ran the script saw the answer at that
  moment, and could in principle have re-run it until they liked the answer. The only mitigations are
  that the author states it was run once and that this is a synthetic demo case that is never pooled with real
  cases. A stronger scheme (mixing in a public randomness beacon published after the
  commitment) is a possible follow-up.

### How to verify it (from the repository root)

Running this reads the sealed file but prints only two checks, not the answer:

```bash
python -c "import hashlib,json,re;c=json.load(open('services/api/data/demo_cases/synthetic_distributor-depot.json',encoding='utf-8'))['curation_notes']['fair_draw'];s=json.load(open('services/api/data/sealed_outcomes/synthetic_distributor-depot.json',encoding='utf-8'));seed=bytes.fromhex(re.search(r'seed_hex=([0-9a-f]{64})',s['notes']).group(1));h=int(hashlib.sha256(seed+b'faultline-synthetic-draw:synthetic_distributor-depot').hexdigest(),16);print('commitment ok:',hashlib.sha256(seed).hexdigest()==c['commitment_sha256'],'| draw ok:',('YES' if 100*h<35*2**256 else 'NO')==s['outcome'])"
```

Expected output: `commitment ok: True | draw ok: True`.

### Market price: SYNTHETIC 0.35

The case carries one SYNTHETIC quote (issue #105), on the `synthetic` venue added in #111:

| Field | Value |
|---|---|
| `market_quote_id` | `synthetic:FAULTLINE-SYN-DEPOT` |
| Price | 0.35 (`raw_price` "0.35", decimal) |
| `ts` | 2026-09-14T11:00:00Z, 1 hour before `as_of`, inside the gate's 24 h window |
| Labels | `provenance = SYNTHETIC`, `quote_kind = synthetic`, SYNTHETIC quote label, URLs on `synthetic.invalid` |
| `collected_at` | 2026-11-14T15:00:00Z: when the price was written into the file (nothing was fetched) |

**Why 0.35, and when it was fixed.** 0.35 is `p_draw`, the probability in the published draw rule
(YES if 100 × h < 35 × 2^256). The case file proposed in #92, merged via #128 (squash commit `0f8407d`), already stated it before any
forecast: `services/api/data/demo_cases/synthetic_distributor-depot.json`, line 110,
`curation_notes.market.intended_synthetic_price`: "the intended SYNTHETIC price is p_draw = 0.35 (calibrated by
construction). No price was typed into this file." The price was **written** into the file later (2026-11-14), and
git cannot prove its order relative to the seed (see the honest timeline above). It cannot leak the answer either
way: the draw does not depend on anything a market could know, so 0.35 is the calibrated price whatever was drawn.

What changes:
- the gate reports a SYNTHETIC market baseline of 0.35 for this case;
- the `agent_plus_market` variant now runs; `agent_only` is unchanged and never sees the price (its payload hash is
  unchanged). The case's `snapshot_hash` now covers the evidence plus the selected quote, as for the July FOMC case:
  `sha256:ae1d59bb…`;
- `build_scorecard` gives the case a row with a SYNTHETIC market baseline. Alone (n = 1) it reads
  `INSUFFICIENT DATA` (MATH_MODEL §6, n < 5); it is never OFFICIAL and never pooled with the real cases;
- `case_sha256` changed (now `51623d9b…`). No forecast or recorded run had been saved for the old content.

### Never pooled with real cases

Synthetic results are reported separately from real historical cases and never count toward the real-case `n`.

**Run order.** Save the forecasts for all real cases **before** revealing the synthetic case, or reveal it only in a
separate scratch store. Reveals of real cases block OFFICIAL for forecasts saved after them. Since #119 a reveal of
this committed synthetic case, logged as SYNTHETIC, does not, but saving real-case forecasts first is still the safe
order.

`core/evaluator.py` enforces this. `build_scorecard` fixes the population before anything is revealed: if the
forecasts to be scored mix synthetic and real cases, it stops with an error telling the caller to pass `case_set`
(`"real"` or `"synthetic"`), and nothing is revealed. It also checks that each forecast's `synthetic` flag (fixed by the gate when the forecast was saved) agrees with
the sealed file's `provenance` (`SYNTHETIC` here). A scorecard made only of synthetic cases is labelled
`ILLUSTRATIVE: Synthetic demo fixtures` once it has 5 or more events (below 5 it reads `INSUFFICIENT DATA`). A committed synthetic case without a forecast does not block the OFFICIAL
label for the real cases (`test_synthetic_committed_cases_without_forecasts_do_not_block_official`).
