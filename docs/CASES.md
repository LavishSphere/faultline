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

Added in a later commit, after this rule was committed.
