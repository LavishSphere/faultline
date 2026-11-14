# Blind Replay cases (issues #20, #48)

Real, already-resolved yes/no events used by the Blind Replay (SPEC §4, §5; `docs/EVALUATION_PROTOCOL.md`).
Case files: `services/api/data/demo_cases/<event_id>.json`. Sealed results: `services/api/data/sealed_outcomes/<event_id>.json`
(read only by the evaluator). This document never states which way an included case resolved.

Parts 1 and 2 cover the real cases. The one synthetic fallback case (issue #48) is not a real event; it has its
own section at the end and is never pooled with the real cases.

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
