# Blind Replay cases (issue #20)

Real, already-resolved yes/no events used by the Blind Replay (SPEC §4, §5; `docs/EVALUATION_PROTOCOL.md`).
Case files: `services/api/data/demo_cases/<event_id>.json`. Sealed results: `services/api/data/sealed_outcomes/<event_id>.json`
(read only by the evaluator). This document never states which way an included case resolved.

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
   less information. `horizon_days = 7`.
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

Applied on 2026-11-13, after Part 1 was committed. **Changes to the rule:** none.

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
| `fomc-2026-jun` | Will the FOMC leave the target range for the federal funds rate unchanged at its June 16-17, 2026 meeting? | 2026-06-10T00:00:00Z | `NOT AVAILABLE` (no saved snapshot) | 4 |
| `fomc-2026-jul` | ... unchanged at its July 28-29, 2026 meeting? | 2026-07-22T00:00:00Z | Kalshi `KXFEDDECISION-26JUL-H0` ("Fed maintains rate"): bid/ask midpoint **0.855** (bid 0.8500, ask 0.8600), candle ending 2026-07-22T00:00:00Z. Polymarket `1654958` ("no change"): price-history point **0.839** at 2026-07-21T23:00:22Z. Both from the saved #12 snapshots | 4 |
| `fomc-2026-sep` | ... unchanged at its September 15-16, 2026 meeting? | 2026-09-09T00:00:00Z | `NOT AVAILABLE` (no saved snapshot) | 4 |
| `fomc-2026-oct` | ... unchanged at its October 27-28, 2026 meeting? | 2026-10-21T00:00:00Z | `NOT AVAILABLE` (no saved snapshot) | 4 |

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
