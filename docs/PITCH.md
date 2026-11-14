# FAULTLINE: pitch slide content

**Presenter:** Yaseen (finance owner). **For:** Demo Day, Sun Nov 15 (docs/HACKATHON.md). **Issue:** #84.
**Written:** 2026-11-14 against `main` at `4a1f2c2`; updated against `80deee2`.

How to use this file: each `## Slide` heading is one slide. The quoted block under **On the slide** is the slide text
(30 words or fewer, counted by script, labels included). **Speaker notes** are for the presenter, not the slide.
**Sources** names the repo doc and section behind every figure. Nothing here is new: every number is copied from a
repo doc, with its label.

The demo script `docs/DEMO_SCRIPT.md` is on `main` (#46, PR #72). Slide 3 and parts of slides 4 and 6 depend on it;
if it changes, re-check those slides.

---

## Slide 1. The problem: small businesses run on thin cash

**On the slide:**
> Small firms provide slightly less than half of US private-sector jobs. The median one holds cash for 27 days of
> outflows. REAL HISTORICAL: BLS; JPMorgan Chase Institute, 2016.

**Speaker notes:**
- "According to the Bureau of Labor Statistics, firms with fewer than 250 employees account for slightly less than
  half of America's private-sector jobs. In JPMorgan Chase Institute's 2016 study, the median small business held
  enough cash to cover only 27 days of its typical outflows if money stopped coming in."
- If there is time: "A quarter of them had fewer than 13 days." And from the Federal Reserve's 2025 survey: rising
  costs were the most common financial challenge, and 77% of firms reported rising costs, tariff-related costs, or
  both.
- So the *week* a shock hits cash matters as much as its size. That is the gap FAULTLINE is built for.
- Do not say how many businesses fail *because of* a shock: none of these sources says that (IMPACT, "What the facts
  do not say"). "Small" is defined differently by each source; all facts are US-only.

**Sources:** docs/IMPACT.md, "Eight facts" table: fact 1 (BLS [S1], slightly less than half of private-sector
employment, firms under 250 employees), fact 4 (JPMorgan Chase Institute [S3], 27 cash buffer days median, 25% under
13 days, 2015 data, published 2016), fact 6 (Federal Reserve SBCS [S5], 77%); "Three pitch-ready sentences" no. 1.
Label: `REAL HISTORICAL` (IMPACT header).

---

## Slide 2. The product: test the decision before you live with it

**On the slide:**
> Test the decision before you live with it. Run rate shocks, demand drops or supplier outages through the business;
> see the week cash falls below the floor. No AI arithmetic.

**Speaker notes:**
- "FAULTLINE lets an operator run a rate shock, a demand drop or a supplier outage through the business before it
  happens, and see the exact week cash hits its low point."
- Every number comes from a deterministic engine (typed Python and a solver), never from an AI. Same inputs, same
  answer, every time.
- When no recovery plan keeps cash above the floor, the optimizer says **NO FEASIBLE PLAN** instead of a comforting
  answer. With **Protect payroll** on, it is not allowed to cut payroll at all: that is a hard limit in the solver
  (optimizer merged in #69, live switch in #127).
- Who it is for: owner-operators, and the fractional CFOs and accountants who advise them (slide 5).
- It is decision support: it does not give financial advice, lend, trade, or change anyone's employment.

**Sources:** docs/IMPACT.md, "Why FAULTLINE helps (and what it does not do)" and "Three pitch-ready sentences"
nos. 2–3; docs/HACKATHON.md, "Judging criteria" (tagline under Investability); docs/MATH_MODEL.md §3 (cash
recurrence) and §4 (optimizer, Protect payroll bound). No figures on this slide.

---

## Slide 3. Live demo

**On the slide:**
> LIVE DEMO. Fictional three-store grocer, bad quarter: cash ends at $13,950, not $63,000 (−$49,050), below the
> $25,000 floor from week 20. SIMULATED, SYNTHETIC.

**Speaker notes:**
- Switch to the app now and follow `docs/DEMO_SCRIPT.md` step by step: REWIND →
  DECISION → CASCADE → REVEAL → RESEARCH LENS → LIVE EXPLORE → close. About 112 s of spoken words; the script has not
  been timed with a stopwatch yet.
- The headline numbers, as the script says them on the CASCADE screen: "No shock: it ends the half-year at 63,000.
  A bad quarter: rates up two points, demand down a fifth, main supplier out three weeks. Cash falls below our 25,000
  floor in week 20 and ends at 13,950: 49,050 worse."
- **Read the screen, not this slide.** If the on-screen figure differs, say the on-screen figure and tell the lead.
- The business is `SYNTHETIC` (invented, assumptions in MATH_MODEL §10). The calculations are real and can be
  checked by hand: 6,000 (rates) + 26,250 (demand) + 16,800 (outage) = 49,050.
- Two merged features worth showing if a judge asks, both from the demo flow, not extra spoken words:
  - **Judge's Challenge on CASCADE** (#135): a judge picks a named surprise shock (ILLUSTRATIVE inputs, from
    `GET /api/judge-challenges`) or presses "Surprise me"; the engine reruns it on the spot (SIMULATED), and Protect
    payroll still applies. "Surprise me" follows a fixed order: no hidden randomness.
  - **ACT / WAIT / HEDGE split view on DECISION** (#134): each pre-declared plan costed by the engine in both outcomes,
    V(a, YES) and V(a, NO), with the recommendation at the model's probability.
- If a screen shows `NOT AVAILABLE` or `Local model unavailable`, use the "Say instead" line from the demo script.
  Never fill a gap with a number from memory.

**Sources:** docs/DEMO_SCRIPT.md, "Step 3. CASCADE" and
"Where the numbers come from" (baseline `min_cash` 63,000; bad quarter 13,950; `min_cash_delta` −49,050; first week
below the 25,000 floor: week 20; hand check); docs/MATH_MODEL.md §10 (25,000 cash floor, demo business parameters).
Labels: `SIMULATED` (engine output), `SYNTHETIC` (fictional business).

---

## Slide 4. Why you can trust it: alignment by design

**On the slide:**
> The AI sees only evidence public at the cutoff; answers stay sealed until its forecast is saved. Code does every
> calculation. Protect payroll is a hard limit. Humans decide.

**Speaker notes:**
- "FAULTLINE asks an AI for decisions under uncertainty, then grades it. Five design choices make sure the AI can
  neither cheat the grading nor make a decision a human did not approve."
  1. **It cannot see the future.** A blind replay rewinds to a real past decision; the model gets only evidence that
     was public then. A secret "canary" string placed only in excluded data is tested never to reach a prompt.
  2. **Values are code, not prompts.** Protect payroll sets the payroll cut to zero inside the solver. If no plan
     works without cutting pay, it says NO FEASIBLE PLAN.
  3. **A skeptic checks the AI, and code does the maths.** Invented evidence ids or impossible probabilities are
     rejected before anything is shown.
  4. **The scorecard can say "no"** (slide 6).
  5. **Everything is labeled; nothing is invented.** Missing data shows `NOT AVAILABLE`.
- Point at the **INTEGRITY** panel (DECISION panel B.8, REVEAL panel D.3). It re-checks, on each request, what the
  AI was not allowed to see. Read only the ✓ / ✗ / NOT AVAILABLE marks it shows; a check that cannot run shows
  NOT AVAILABLE, never a tick.
- Say the honest limits if asked: tamper-evident, not tamper-proof; a model may remember outcomes from training, so
  likely-contaminated cases are flagged and excluded from scoring; the isolation is enforced in code inside the API
  process, not by a separate sandbox.

**Sources:** docs/ALIGNMENT.md, intro and §1–§5, "Honest limits"; docs/HACKATHON.md, "Judging criteria" (AI
alignment +2 framing); docs/DEMO_SCRIPT.md step 4, optional INTEGRITY line. No figures
on this slide.

---

## Slide 5. Market and business model

**On the slide:**
> Who pays: fractional CFOs and accountants first; then 654,501 US firms with 20–499 employees (Census 2022). Price:
> $149/seat + $15/client; $99/business (HYPOTHESIS). Traction: none yet.

**Speaker notes:**
- "The Census Bureau counted about 6.4 million US employer firms in 2022, and about 655,000 of them have 20 to 499
  employees: those operators, and the accountants and fractional CFOs who advise them, are who we sell to."
- Why advisors first: 50,885 CPA firms and 120,085 accounting-services firms already sit beside small-business
  clients, and in the 2024 AICPA and CPA.com benchmark survey the advisory practices that took part reported 17%
  median growth (a self-selected sample of 206 practices).
- Pricing is an `ESTIMATE / HYPOTHESIS`, not tested with any customer: advisor plan $149 per seat a month plus $15 per
  client business; SMB plan $99 per business a month. On those assumptions, LTV ÷ CAC is 5.7 (advisor) and 4.3 (SMB),
  and CAC payback is 11.7 and 9.3 months. The two least-known inputs are advisor CAC and SMB churn: if SMB churn is 4%
  a month, LTV ÷ CAC falls to 2.7.
- Ceiling, not forecast (`ESTIMATE`): if every one of the 654,501 firms paid $99 a month, that is $777.5 million a
  year. Realistic penetration is unknown.
- Third-party estimate for context only: US fractional CFO services "USD 2.00 billion" in 2025 (Credence Research;
  methods not verified). A figure for small-business FP&A software is **NOT AVAILABLE**.
- **Traction: none yet** (hackathon MVP). No users, pilots, letters of intent, revenue, waitlist or partnerships.
- Biggest risk: accounting platforms and banks are adding what-if forecasting at low or no cost. Our wedge is
  auditable decision testing.

**Sources:** docs/INVESTABILITY.md §1 (who pays), §2 (M1 6,395,635 employer firms; M2 654,501 firms with 20–499
employees, derived from Census SUSB 2022; M3 50,885 and 120,085; M4 17% and 206 practices; M5 USD 2.00 billion,
third-party estimate; bottom-up pool $777.5 million, `ESTIMATE`), §3 (prices, LTV ÷ CAC, payback, sensitivity,
`ESTIMATE / HYPOTHESIS`), §4 (competitors, wedge), §7 (traction: "None yet"), §8 (risks).
Labels: M1–M3 `REAL HISTORICAL` (or derived from it); M5 third-party estimate; §3 `ESTIMATE / HYPOTHESIS`.

---

## Slide 6. What we measured, honestly

**On the slide:**
> Our scorecard compares the AI with the market and a coin flip on the same sealed questions. Nothing has been
> officially scored yet. Under 5 cases: INSUFFICIENT DATA.

**Speaker notes:**
- "The outcome unseals only after the answer is saved, then is scored against the market and a coin flip. Nothing
  has been officially scored yet, so the benchmark says NOT AVAILABLE; with fewer than five cases our rule shows
  INSUFFICIENT DATA."
- What is on `main` today: 29 replay cases, 28 `REAL HISTORICAL` (15 Federal Reserve (FOMC) meetings and 13 US CPI
  prints, 2025 and 2026) and 1 `SYNTHETIC` fallback case. No recorded run or scorecard is committed yet:
  `services/api/data/recorded_runs/` holds only its README, which says it is "empty on purpose until the lead runs
  it". So the benchmark on the REVEAL screen reads `NOT AVAILABLE`.
- The rule was fixed before any answer was seen. It uses the Brier score (squared error of a probability):
  - fewer than 5 cases: "INSUFFICIENT DATA: No valid comparison";
  - otherwise: "No improvement measured", with the 95% confidence interval;
  - "agent better than market" only if the whole 95% confidence interval of the score difference is below zero;
  - from 5 to 29 cases, a "small sample" caveat is added.
- What a small sample can and can't tell us: with 28 real cases (still under 30), only a very large difference is
  detectable, so "No improvement measured" is the expected honest result unless the agent is much better than the
  market. It means "not measured", not "no edge".
- If a scorecard has been recorded by demo time, read only what the screen shows, and drop "Nothing has been
  officially scored yet". If n is shown, say: "With N events we could only have detected a large edge. We did not
  measure one; that is not proof that there is none."
- Never say: "the agent matches the market", "no difference", or "95% likely to be better". We make no claim of
  doing better than the market or the VCs.

**Sources:** docs/MATH_MODEL.md §6 (display rules; "What n ≈ 15 can and can't tell us", issue #80 / PR #100,
"Exact wording"); docs/ALIGNMENT.md §4; `services/api/core/evaluator.py` labels (`INSUFFICIENT DATA`,
`No improvement measured`, `INSUFFICIENT DATA: No valid comparison`); `services/api/data/recorded_runs/README.md`
(no recorded run committed); docs/DEMO_SCRIPT.md step 4 and hard question 3; the 29 case files in
`services/api/data/demo_cases/` (15 FOMC 2025–2026, #54 and #67; 13 CPI, #160; 1 synthetic, #128), counted with
`GET /api/cases` on 2026-11-14.

---

## Slide 7. The ask and next steps

**On the slide:**
> Ask: fractional CFOs and accounting firms as design partners, testing FAULTLINE on real client decisions. Next:
> officially score the replay cases, test pricing with customers, build client reports.

**Speaker notes:**
- **The ask:** "We are looking for a handful of fractional CFOs and accounting firms with an advisory practice to be
  design partners: run FAULTLINE on their own clients' decisions, with the clients' consent." We have none yet.
- **Next steps, in order:**
  1. Run the official blind replay on the real, reviewed cases and commit the recorded runs, so the scorecard shows
     a real result, whatever it says.
  2. Test the pricing hypothesis with real advisors: every price, churn and CAC figure is an assumption today.
  3. Build client-facing decision reports: a sealed, reproducible report an advisor can share with a client.
  4. Later, a direct plan for small businesses that have a finance lead but no advisor.
- Close with the line from the demo script: "The AI never does the arithmetic and never takes an action: that is our
  alignment design. Built with Claude Code, Anthropic's coding agent. Test the decision before you live with it."

**Sources:** docs/INVESTABILITY.md §5 (go-to-market: design partners "next step, none yet", client-facing decision
reports, direct SMB plan later), §8 ("Unit economics are untested"); `services/api/data/recorded_runs/README.md`
(official run not yet done); docs/DEMO_SCRIPT.md step 7. No figures on this slide.

---

## Sponsors (one line, where true)

Built with **Anthropic**'s Claude Code; **Tavily** powers LIVE EXPLORE, walled off from the blind replay; **Link
Ventures** is one of our four research lenses.

**Sources:** docs/HACKATHON.md, "Sponsors"; Live Explore merged in #73 and #135; research lens data
`services/api/data/research_lenses.json` (Link Ventures entry).

## Judging criteria map

| Criterion (docs/HACKATHON.md) | Where the pitch answers it |
|---|---|
| Demo and pitch | Slide 2 (one-line product), slide 3 (live demo, docs/DEMO_SCRIPT.md), slide 7 (ask) |
| Investability | Slide 5 (who pays, market counts, pricing hypothesis, no traction yet), slide 7 (design partners) |
| Product | Slides 2 and 3: CASCADE stress test, Protect payroll, Judge's Challenge on CASCADE (ILLUSTRATIVE shocks, #135), ACT/WAIT/HEDGE split view on DECISION (#134), blind replay, research lens, LIVE EXPLORE |
| Societal impact | Slide 1 (cited small-business facts), slide 2 (Protect payroll is a hard solver constraint) |
| +2 AI alignment | Slide 4 (sealed evidence, code does the maths, humans decide, INTEGRITY panel), slide 6 (a scorecard that can say "no") |

## Before going on stage

- [ ] Re-check slides 3, 4 and 6 against docs/DEMO_SCRIPT.md on the demo laptop.
- [ ] On the demo laptop, check that the CASCADE screen still shows $63,000, $13,950 and −$49,050 (demo script
      dry-run checklist). If not, change slide 3 to the on-screen figures and tell the lead.
- [ ] Check whether a recorded scorecard has been committed (`services/api/data/recorded_runs/`). If it has, rewrite
      slide 6 from what the REVEAL screen shows.
- [ ] INVESTABILITY still has an unticked finance-owner review box: tick only after checking each figure used on
      slide 5 against its source. (IMPACT's box, behind slide 1, was ticked on 2026-11-14 in #137.)
