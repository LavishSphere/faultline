# FAULTLINE: 2-minute demo script and finance Q&A prep

**Presenter (finance voice):** Yaseen. **Length:** 280 spoken words on the main path (the **Say** lines of steps 0–7), about 112 s at 150 words a minute, inside the 90–120 s target (SPEC §2). **Measured with a stopwatch:** NOT YET TIMED. Write the time of the first full run-through here.
**Status of this script:** written 2026-11-13 against `main` at commit `1190671` and updated on 2026-11-14 against `4a1f2c2` (after the DECISION screen #134, the optimizer endpoint and Protect payroll switch #127, and the LIVE EXPLORE screen #135 merged); the recovery-plan numbers (step 3) were re-run against `80deee2`, after the optimizer tie-break #136. On-screen labels
in steps 1, 3, 4 and 5 were updated for the finance-review fixes (#157), and the case, research-lens and integrity
counts re-checked against `c675c6e` with this branch's API; the case counts again against `d29820f` (after #160, 13 CPI cases). Every number below came from the API running locally (calls listed in [Where the numbers come from](#where-the-numbers-come-from)).
The web app itself was **not** run while writing this (Node.js was not installed on the writing machine), so the
click paths and on-screen labels were read from the `apps/web` code. Do the [dry-run checklist](#dry-run-checklist)
before going on stage.

Every step below is on `main` at `4a1f2c2`; nothing in the flow is still PENDING. Steps 2 and 6 need a running local
model, and step 6 also needs `TAVILY_API_KEY`. If one is missing, the screen shows `NOT AVAILABLE` (or `Local model
unavailable`), and you say the "Say instead" line. Never fill a gap with a number from memory. Everything else that a judge might ask about is in the [hard questions](#hard-questions-plain-language-answers).

---

## The pitch

> **Test the decision before you live with it.** FAULTLINE rewinds to a real decision point, seals everything that
> happened afterwards, and shows how a shock would cascade through a business's cash, with every number computed by
> a deterministic engine, not by an AI. Then it scores itself against the market and a coin flip on the same
> questions, and when it has not won, or has too few cases to tell, it says so on screen. The AI never does the
> arithmetic and never takes an action: that is our alignment design.

---

## Click-by-click flow

Navigation: the **→ / ←** arrow keys (or the buttons in the bottom bar) move between the six screens
`/rewind → /decision → /cascade → /reveal → /research → /explore`. The timeline at the top groups them as
THEN / DECISION / REVEAL / NOW; LIVE EXPLORE (`/explore`) is the NOW screen.

### Summary table

| # | Step | What to click | Label on screen | Words (≈ s) | Status |
|---|---|---|---|---|---|
| 0 | Open | Nothing; app is on `/rewind` | (title only) | 17 (≈ 7 s) | works on main |
| 1 | REWIND | Pick `fomc-2026-jul` in panel **A.1 Replay cases** | `REAL HISTORICAL`, `AS-OF`, `SEALED`; header `Case fomc-2026-jul` | 32 (≈ 13 s) | **works on main** (28 real cases: 15 FOMC, 13 CPI; #54, #67, #160) |
| 2 | DECISION | **→** to `/decision` | `RECORDED RUN` or a fresh run, `FORECAST`, market `AS-OF` "market-implied probability (price-derived…)" | 30 (≈ 12 s) | **on main** (#55, #71); needs the local model running |
| 3 | CASCADE | **→** to `/cascade`; **Preset** dropdown → "Bad quarter…"; then **Protect payroll** | `SIMULATED` + `SYNTHETIC` | 74 (≈ 30 s) | preset and Protect payroll **work on main** (#69, #127) |
| 4 | REVEAL | **→** to `/reveal`; **Reveal outcome** | Benchmark and both scorecards `NOT AVAILABLE`; outcome `REVEALED` | 41 (≈ 16 s) | **on main** (#76, #64, #91); no recorded scorecard yet |
| 5 | RESEARCH LENS | **→** to `/research`; the cutoff already reads the case's `2026-07-22T00:00:00Z`; **Apply cutoff** only if you changed it | `REAL HISTORICAL`, `RESEARCH CONTEXT`, `AS-OF: UTC instant` | 26 (≈ 10 s) | **works on main** |
| 6 | LIVE EXPLORE | **→** to `/explore`; type a decision; **Research and analyze**; confirm the suggested inputs | `LIVE EXPLORE`, `MODEL-SUGGESTED, HUMAN TO CONFIRM`, then `SIMULATED` + `SYNTHETIC` | 29 (≈ 12 s) | **on main** (#135); needs `TAVILY_API_KEY` and the local model |
| 7 | Close | Nothing | (none) | 31 (≈ 12 s) | n/a |
| | | | **Total** | **280 (≈ 112 s)** | |

Seconds are estimates at 150 spoken words a minute, plus pauses for clicks. If you are running long, use step 6's
5-second line instead of the full one (saves 11 words) and drop the second sentence of step 5 (saves 17 words).

---

### Step 0. Open

- **Click:** nothing. The app is open on `/rewind`, dark theme, full screen, header chip reads `API online`.
- **Say:** "Test the decision before you live with it. FAULTLINE stress-tests a small business's cash against real shocks."
- **On screen:** the REWIND title and the THEN / DECISION / REVEAL timeline. No data label yet.

### Step 1. REWIND: **works on main** (#54)

- **Click:** in panel **A.1 Replay cases**, pick the real FOMC case `fomc-2026-jul` (July 2026 meeting, cutoff
  2026-07-22 00:00 UTC; steps 2 and 5 assume it). Point at **A.3 Knowledge cutoff** and the hatched **Sealed future** strip.
- **Say:** "We rewind to a real Federal Reserve decision. This is the knowledge cutoff. On the left, only evidence public by then. On the right, the answer is sealed away from the model."
- **On screen:** `REAL HISTORICAL` on the evidence, `AS-OF` on the cutoff, `SEALED` on the future. The header now
  reads `Case fomc-2026-jul` with a `REAL HISTORICAL` badge, on every screen, until you pick another case (#157).
- **The list also holds one `SYNTHETIC` case (#128).** Don't pick it on the main path. If you do, say instead: "This
  is an invented case whose answer was fixed by a committed random draw, so no model can know it." Its screens are
  labeled `SYNTHETIC`, never `REAL HISTORICAL`.
- **If no case is listed:** the screen shows `NOT AVAILABLE` on every panel and the header chip reads
  `Case NOT AVAILABLE: Cases did not load` (request failed) or `Case NOT AVAILABLE: No case served` (empty list).
  `Case NOT AVAILABLE: No case selected` only means you have not picked one yet: pick it. On 2026-11-14 (after #160)
  `GET /api/cases` returned 29 cases (28 `REAL_HISTORICAL`: 15 FOMC meetings and 13 US CPI prints of 2025 and 2026,
  plus 1 `SYNTHETIC`), so an empty or failed list means the API did not load its data.
  **Say instead:** "The replay cases didn't load, so this screen honestly says NOT AVAILABLE." Then go straight
  to step 3.

### Step 2. DECISION: **on main** (#55, #71); needs a local model

- **Click:** **→**. Point at **B.1 Agent probability**, then **B.2 Market at cutoff**, then the ACT / WAIT / HEDGE cards.
- **Say:** "A local model, offline, read only that evidence and gave a probability. Beside it, the market price at the cutoff. Below: act, wait or hedge, each costed by the engine."
- **On screen:** `RECORDED RUN` (a saved, reproducible run with its prompt and data hashes) or a fresh local run;
  `FORECAST` on the probability; on **B.2** (kicker "Market baseline · P(YES)") `AS-OF` and the API's own label,
  which starts "market-implied probability (price-derived…".
- **Not every real case has a market price at its cutoff.** Where it doesn't, panel B.2 must read `NOT AVAILABLE`. Do
  not say a market number unless it is on screen.
- **If the local model isn't running:** **B.0** reads `Local model unavailable` and the run panels read
  `NOT AVAILABLE` (Ollama was not running when this was written: `/api/health` returned `"model_ready": false`).
  No recorded run is committed on `main` yet (`services/api/data/recorded_runs/` holds only a README), so there is
  no saved run to fall back on.
  **Say instead:** "When the model isn't running, this screen says so. It never makes up an answer."

### Step 3. CASCADE: preset and Protect payroll **work on main** (#69, #127)

- **Click:** **→** to `/cascade`. In panel **C.1 Scenario inputs**, open the **Preset** dropdown and choose
  **"Bad quarter: rate shock + demand drop + supplier outage"**. Wait for the readout strip **C.2** to turn solid
  (the status line reads `POST /api/simulate · 200`).
- **Say (numbers are from the running API on `main`, see below):** "A fictional three-store grocer, labeled synthetic. No shock: it ends the half-year at 63,000. A bad quarter: rates up two points, demand down a fifth, main supplier out three weeks. Cash falls below our 25,000 floor in week 20 and ends at 13,950: 49,050 worse."
- **Then click:** the **Protect payroll** switch in C.1 (off by default).
  **Say:** "Now, Protect payroll. The optimizer must keep cash above the floor without cutting wages, or say NO FEASIBLE PLAN. Protecting people's jobs is a hard limit in the maths."
  Then read the plan **only from panel C.3 Recovery plan**. On 2026-11-14 (after the tie-break #136 and the
  stock-out cost #103) the API gave, for the bad quarter with Protect payroll on: **Chosen actions (10)**: purchase
  cuts in weeks 22 ($1,006.36), 23 and 24 ($10,000 each, the weekly cap), together $21,006.36, bridged by revolver
  draws in weeks 20–24 (together $12,406.96) repaid in weeks 25–26; **Min cash after plan $25,000 · week 20**
  (exactly the floor); objective 1,922.21; no payroll cut (see
  [Where the numbers come from](#where-the-numbers-come-from)). The cuts come late because a purchase cut now costs
  lost sales for every week stock stays below its service level (MATH_MODEL §3, #103). With the switch off the API
  returns the **same plan**: the same 10 actions in the same weeks, objective 1,922.21. Payroll
  is the costliest lever, so the optimizer doesn't use it here anyway. So don't say the switch changed this plan;
  its point is the guarantee. (Capex is 0 in the demo
  business and the revolver must be repaid by week 26, so neither fixes the bad quarter on its own.)
- **On screen:** `SIMULATED` (computed by the deterministic engine) and `SYNTHETIC` (fictional business) on C.0 and C.2.
  Under **Minimum cash** the second line reads `floor $25,000 · below it in weeks 20–26` (from the API's
  `weeks_below_floor`, #157); that is the "week 20" you say. **Cash goes negative** reads `not within 26 weeks`.
  The dependency network shows Δ = scenario − baseline at each node's peak week.
- **If C.3 reads `NOT AVAILABLE` or shows an error** (the API did not answer `POST /api/optimize`):
  **Say instead:** "The solver didn't answer, so this panel says NOT AVAILABLE instead of guessing."
- **Moved to Q&A** (don't say on the main path): the week-7 low of 25,523, the 48,000 of lost sales, and why the three
  shocks don't add up (question 16).

### Step 4. REVEAL: **on main** (#76, #64, #91); no recorded scorecard yet

- **Click:** **→** to `/reveal`. In panel **D.0 Historical outcome**, click **Reveal outcome** (it needs the
  `prediction_id` of the saved DECISION run).
- **Say:** "The outcome unseals only after the answer is saved, then is scored against the market and a coin flip. Nothing has been officially scored yet, so the benchmark says NOT AVAILABLE; with fewer than five cases our rule shows INSUFFICIENT DATA."
- **On screen:** panel **D.1 Benchmark · recorded scorecards** badged `NOT AVAILABLE` (on 2026-11-14 `GET
  /api/benchmark` said "Benchmark NOT AVAILABLE: no recorded scorecard yet."), and both **D.2** scorecards
  (`agent_only`, `agent_plus_market`) read `NOT AVAILABLE`. `INSUFFICIENT DATA` appears only on a recorded scorecard
  with fewer than five cases. After a reveal, D.0 reads `REVEALED`.
- **If a recorded scorecard is shown:** read only what is on screen, and drop "Nothing has been officially scored
  yet".
- **Do not** read out any per-case score or any outcome from memory. Say only what is on screen.
- **If there is no saved prediction:** the button is disabled and the line under it reads "Disabled: no prediction
  id. The outcome stays sealed server-side until a persisted forecast is named."
  **Say instead:** "The reveal stays locked until a prediction has been saved. That lock is the point."
- **Optional, for the +2 AI-alignment criterion (not counted in the timing):** point at panel **D.3 Integrity · what
  the AI could not see** (also **B.8** on DECISION, #93) and say: "This panel re-checks on each request (cached up to
  60 s) what the AI was not allowed to see." Read only the ✓ / ✗ / NOT AVAILABLE marks it shows. D.3 now checks the case selected on REWIND
  (#157): on 2026-11-14 `GET /api/integrity?case_id=fomc-2026-jul` with no run gave 6 passed, 0 failed,
  3 NOT AVAILABLE; with no case selected it gives 3 passed, 0 failed, 6 NOT AVAILABLE.

### Step 5. RESEARCH LENS: **works on main**

- **Click:** **→** to `/research`. In panel **E.0 Thesis Court · cutoff** (mode **Point-in-time**) the cutoff already
  holds the selected case's cutoff, `2026-07-22T00:00:00Z` (#157; the help line ends "Default: the selected case's
  cutoff (fomc-2026-jul)"). If it shows another instant, type `2026-07-22T00:00:00Z` and click **Apply cutoff**.
  On 2026-11-14 `GET /api/vc-lenses?as_of=2026-07-22T00:00:00Z` returned 4 sources (Link Ventures 1, a16z 2,
  Bessemer 1) and 2 not yet public; each firm panel reads "`n` sources public at 2026-07-22T00:00:00Z".
- **Say:** "Four venture firms' public research, as context, not predictions. At a July 2026 cutoff we show four sources and hold back two that weren't public yet."
- **On screen:** `AS-OF: UTC instant` on E.0; each firm panel `REAL HISTORICAL` with a `RESEARCH CONTEXT` tag; Sequoia's
  panel shows no source at this cutoff (its July 23rd article was not public yet).

### Step 6. LIVE EXPLORE: **on main** (#135) (Tavily, our sponsor); needs `TAVILY_API_KEY` and the local model

- **Click:** **→** to `/explore`. In panel **X.1**, type a real decision, for example "Should a three-store grocer lock
  in a fixed rate on its term loan this month?", and click **Research and analyze**. Read the cited evidence cards in
  **X.2**, check (or edit) the suggested inputs in **X.3**, and click **Confirm inputs and run the engine**.
- **Say:** "Live Explore is for today. Tavily finds current news, with sources; the model suggests a scenario, I confirm it, the same engine runs. The replay never touches the web."
- **On screen:** `LIVE EXPLORE` on X.1 and X.2, "Search powered by Tavily", `MODEL-SUGGESTED, HUMAN TO CONFIRM` on X.3
  when the model supplied numbers (if it gave none, X.3 shows `ILLUSTRATIVE` guidance defaults and says so), then
  `SIMULATED` + `SYNTHETIC` on **X.4 Cascade · deterministic engine**.
- **Optional extra line, not counted in the timing (say it only if it is true for the merged cases; ask the lead):**
  "We also used Tavily to *find* candidate sources for the real replay cases, and then a person verified each one
  against an archived copy from before the cutoff. Tavily helped us search; it never decided what the model was
  allowed to see."
- **If Live Explore can't run:** without the key `/api/health` reports `"TAVILY_API_KEY not set: Live Explore web
  search is disabled."` (true on the writing machine on 2026-11-14), and without the local model the screen says
  `Local model unavailable`. **Say instead (5 s):** "Next is Live Explore with Tavily: the
  same engine on today's news, kept completely separate from the replay."

### Step 7. Close

- **Say:** "The AI never does the arithmetic and never takes an action: that is our alignment design. Built with Claude Code, Anthropic's coding agent. Test the decision before you live with it."

---

## Where the numbers come from

All figures were produced by `POST /api/simulate` on `main` at `1190671`, run locally on 2026-11-13
(`uvicorn main:app --host 127.0.0.1 --port 8046` from `services/api`). The response carries
`"provenance": "SIMULATED"` and `"business_provenance": "SYNTHETIC"`. Dollar figures are rounded to the nearest dollar
for speaking. The API returns e.g. `13949.999999999944`, which the screen shows as `$13,950`. Re-checked on 2026-11-14
against `38c595a` (port 8072; `main` then moved to `4a1f2c2` with docs-only changes): baseline 63,000, bad quarter
13,950 (week 26), `min_cash_delta` −49,050, and the research-lens counts below are unchanged.

| Request | Field | Value from the API |
|---|---|---|
| `POST /api/simulate` `{"shock": {}}` | `result.min_cash` / `min_cash_week` | 63,000 / week 26 |
| (baseline) | `result.ending_cash`, `runway_label` | 63,000, `> 26 weeks` |
| `POST /api/simulate` `{"scenario_id": "bad-quarter", "shock": <the bad-quarter shock exactly as served by GET /api/scenarios>}` | `result.min_cash` / `min_cash_week` | 13,950 / week 26 |
| (bad quarter) | `deltas.min_cash_delta` | −49,050 |
| | `result.cash` in week 7 (lowest point during the shock) | 25,523 |
| | first week with `result.cash` < 25,000 (the §10 floor) | week 20 (weeks 20–26 are all below: 7 weeks) |
| | `min_cash_floor`, `first_week_below_floor`, `weeks_below_floor` (#157, re-checked on this branch) | 25,000, 20, [20, …, 26] |
| | `result.runway_label` | `> 26 weeks` (cash never goes negative) |
| | `result.total_interest`, week 1, baseline → bad quarter | 923.08 → 1,153.85 a week |
| | sum of `result.lost_sales` (outage) | 48,000 |
| | sum of `result.sales` minus baseline | −123,000 |
| | largest weekly cash gap vs baseline (`deltas.nodes.Cash.max_abs`) | 64,515 (week 7) |

The other three named scenarios, each sent the same way (`scenario_id` + the served shock):

| Scenario id | `result.min_cash` (week) | vs baseline |
|---|---|---|
| `rate-plus-200bp` | 57,000 (26) | −6,000 |
| `demand-drop-20pct-6wk` | 36,750 (26) | −26,250 |
| `supplier-outage-3wk` | 42,000 (26) | −21,000 |
| `bad-quarter` | 13,950 (26) | −49,050 |

The recovery plan (step 3), from the optimizer on 2026-11-14 on the #103 branch (after the optimizer tie-break
#136 and the stock-out cost #103; `core.optimizer.optimize`, which `POST /api/optimize` calls), body `{"scenario_id": "bad-quarter", "shock": <the served
bad-quarter shock>, "protect_payroll": true | false}`. Both answers have `"status": "OPTIMAL"`,
`"provenance": "SIMULATED"`, `"business_provenance": "SYNTHETIC"`, and the two plans are identical (same actions,
weeks and amounts):

| Field | `protect_payroll: true` | `protect_payroll: false` |
|---|---|---|
| `actions` | purchase cuts week 22 (1,006.36), weeks 23–24 (10,000 each); revolver draws weeks 20–24 (1,126.92, 1,656.45, 1,821.29, 3,465.74, 4,336.55), repaid week 25 (5,547.08) and week 26 (6,859.88) | the same 10 actions |
| sum of purchase cuts | 21,006.36 | 21,006.36 |
| payroll cut, backup supplier, capex, expansion | none | none |
| `min_cash` / `min_cash_week` | 25,000 / week 20 | 25,000 / week 20 |
| `objective` (`disruption_cost`) | 1,922.21 (1,924.71) | 1,922.21 (1,924.71) |
| `binding_constraints` | liquidity floor, weeks 20–26; purchase-cut cap, weeks 23–24; terminal revolver | the same |

Other calls used in this script:

- `GET /api/scenarios` → `status: AVAILABLE`, 4 scenarios: `rate-plus-200bp`, `demand-drop-20pct-6wk`,
  `supplier-outage-3wk`, `bad-quarter`.
- `GET /api/vc-lenses?as_of=2026-07-22T00:00:00Z` (the `fomc-2026-jul` cutoff, step 5; re-checked 2026-11-14 on
  this branch) → `point_in_time`, 4 items (Link Ventures 1, a16z 2, Bessemer 1), `excluded_not_yet_public: 2`.
  `as_of=2026-07-01T00:00:00Z` gives the same 4 and 2. With no `as_of` (Live Explore mode): 6 items.
- `GET /api/cases` (2026-11-14, after #160, `d29820f`) → `status: AVAILABLE`, 29 cases: 28 `REAL_HISTORICAL`
  (15 FOMC meetings and 13 US CPI prints of 2025 and 2026, all `horizon_days` 8) and 1 `SYNTHETIC` (21 days).
  `fomc-2026-jul`: `as_of` `2026-07-22T00:00:00Z`.
- `GET /api/benchmark` (2026-11-14) → `status: NOT AVAILABLE`, "no recorded scorecard yet".
- `GET /api/health` → `model_ready: false` (Ollama not running on the writing machine), `tavily_api_key: false`.

**Hand check (MATH_MODEL §10), useful if a judge asks:**
- Baseline: the business loses 1,423.08 a week before any shock (17,500 gross profit − 12,000 payroll − 6,000 opex −
  923.08 interest), so 100,000 − 26 × 1,423.08 = **63,000**.
- Rate shock: 600,000 × 2% × 26/52 = **6,000** more interest.
- Demand drop: lost sales 6 × 10,000 + 7,500 + 5,000 + 2,500 = 75,000, times the 35% margin = **26,250**.
- Outage alone: 40% × 50,000 × 3 weeks = 60,000 lost sales × 35% = **21,000**.
- Bad quarter: the outage weeks (5–7) fall inside the demand drop, so the outage removes 40% of 40,000, not of 50,000:
  48,000 lost sales × 35% = 16,800. Total 6,000 + 26,250 + 16,800 = **49,050**. That is why the three shocks don't
  simply add up to 53,250.

---

## Hard questions (plain-language answers)

**1. "Are these real numbers?"**
The business is not real. It is a SYNTHETIC three-store food retailer, labeled `SYNTHETIC` on every screen. Its
assumptions are written down in our math model (MATH_MODEL §10): stores selling 18k, 17k and 15k a week, a 35% gross
margin, 80% of sales collected the same week, suppliers paid after 2 weeks, 12,000 a week payroll, 6,000 a week fixed
costs, a 600k floating term loan at 8%, an undrawn 150k revolver, 100k starting cash and a 25k cash floor. The
*calculations* are real: every figure on screen is computed by a tested Python engine from those inputs, and you can
check the headline ones by hand. What *is* real historical data is the replay evidence for the real cases (the fallback case is labeled `SYNTHETIC`),
the market prices at the cutoff (where we have them), and the four firms' public research.

**2. "Why a food retailer?"**
Thin margins and weekly cash make the cascade visible. A grocer turns over inventory every couple of weeks, pays
suppliers on short terms, carries a floating-rate loan, and lives or dies on weekly cash, so a rate move, a demand dip or
a supplier outage shows up within weeks, not years. Our business already loses about 1,400 a week before any shock
(about −2.85% of sales), which is on purpose: shocks bite quickly, the way they do for real small operators. It's also a
business everyone in the room understands without a glossary.

**3. "Did your model beat the market?"**
No, and we don't claim it did. Nothing has been officially scored yet, so the benchmark reads `NOT AVAILABLE`. Our own
rule (MATH_MODEL §6) says that with fewer than five real scored cases the scorecard shows `INSUFFICIENT DATA` and no
comparison at all, and even with more, we only say "better than the market" if a
95% confidence interval on the score difference is entirely below zero. Otherwise the screen says `No improvement
measured`. Not every real case has a market price at its cutoff; where one doesn't, the screen says `NOT AVAILABLE`. What we built is the
honest measuring instrument, not a victory lap.

**4. "Why is 'No improvement measured' or 'INSUFFICIENT DATA' a good result?"**
Because it's the true one, and most AI demos skip it. A system that can say "we don't know yet" is one you can trust when
it eventually says "we do". One correct call on one Fed meeting proves nothing: a coin flip gets that right half the time.
The rule was fixed before we looked at any outcome, so we can't move the goalposts.

**5. "Doesn't the model already know what happened?" (contamination)**
It might, and we say so. Turning off the internet doesn't erase what a model learned in training. Our default local
model is Llama 3.1 8B, whose published card says its training data ends in December 2023 (released July 2024). Our real
cases are 2026 events, after that cutoff, which lowers the risk, but we don't call it guaranteed clean. Each case
carries a contamination flag, and we have extra controls: a version of the model that runs without the market price
(so we can see whether it is just copying the market), and a deliberately planted "future fact" in the sealed data that
tests check never reaches the model (the canary test is on `main`).

**6. "What does the optimizer do, and what doesn't it do?"**
It chooses the least harmful combination of a short, fixed list of actions (draw on the approved credit line, cut
inventory purchases, defer non-critical capex, switch to the backup supplier, delay the expansion, or, only when allowed,
trim payroll hours by up to 10%) so that cash stays above the 25k floor every week, the credit line is within its 150k limit and
repaid by the end, and inventory stays above 40k (MATH_MODEL §4). "Least harmful" uses disruption costs I signed off
(MATH_MODEL §10): drawing the credit line is the mildest, cutting payroll the worst. It doesn't invent new actions, it
doesn't forecast, and it doesn't execute anything. It's a mathematical solver (a mixed-integer linear program), not an
AI, so it gives the same answer every time.

**7. "What if nothing works?"**
Then it says `NO FEASIBLE PLAN`, and the screen keeps saying it. No language model is allowed to overwrite that with
something reassuring. The useful follow-up is "how low would the floor have to be for a plan to exist", which tells a CFO
how big the hole really is.

**8. "Does 'Protect payroll' actually protect payroll?"**
Yes, mechanically. The switch sets the payroll-cut variable's upper limit to zero inside the solver, so no plan can cut
hours. It is a hard constraint in the maths, not an instruction in a prompt. There are no layoffs in the action list at
all.

**9. "Does FAULTLINE trade, lend, or fire anyone?"**
No. It never moves money, places bets, trades securities, approves or denies loans, or changes anyone's employment. It
proposes and evaluates; people decide. The market adapters are read-only public data: no accounts, no wallets, no orders.

**10. "Is the AI doing the maths?"**
No. Every number on the cascade, the readouts and the plans comes from typed Python functions and the solver, and the
same inputs always give the same output. The model's only jobs are to read sealed evidence and give a probability, and
(in Live Explore) to *suggest* a scenario that a human confirms. A separate checker rejects any citation of evidence the
model wasn't shown, and flags every sentence that cites nothing for a human to look at.

**11. "Is the market price the true probability?"**
No. We label it "market-implied probability, price-derived", because fees, spreads, thin trading and risk appetite all
distort it. We only use a price that was actually recorded at or just before the cutoff (no more than 24 hours old). If
there isn't one, the screen says `NOT AVAILABLE`, never an estimate.

**12. "How do you know the evidence was public at the cutoff?"**
Every item carries the time it became publicly available, and the replay only accepts items available at or before the
cutoff, to the minute. Pages that might have been edited later are checked against archived copies. If we can't prove a
date, the item is excluded. This point-in-time gate is on `main` and tested today, for the research lenses and the replay
evidence, including all 28 real cases (15 FOMC, 13 CPI).

**13. "How is live search (Tavily) kept away from the blind replay?"**
They are separate modes with a wall between them. Tavily is only used in Live Explore, for decisions today, and its
results are labeled `LIVE EXPLORE: current, not point-in-time`. The replay model has no web search, no internet and no
Tavily; tests on `main` (`services/api/tests/test_explore_separation.py`) check that replay code can't even import the search client and that a search result can't
pass the point-in-time gate. For building cases, Tavily can help us *find* candidate historical sources, but a person
must verify each one against an archived copy dated before the cutoff, and the tool can't write into the replay data.
That separation is the point: live search for exploring, sealed evidence for scoring.

**14. "Are the VC lenses predictions? Did you beat the VCs?"**
Neither. They are dated public writing by Link Ventures, a16z, Sequoia and Bessemer, shown as `RESEARCH CONTEXT`. A
portfolio page or an investment announcement isn't a forecast, and public firms don't publish their rejected deals or
returns, so there's nothing honest to score against. The one forward-looking claim with a number (Bessemer's "10x"
enterprise deployment) has no defined metric or resolution source, so we don't score it. And a source only appears at a replay
cutoff if it was provably public by then.

**15. "Why no probability or confidence band on the cash forecast?"**
Because we'd have to invent the distributions. The cash engine runs deterministic stress cases: "if this happens, here
is the cash path". The only probabilities in FAULTLINE are the model's and the market's forecasts of a yes/no event, and
we score those. Putting a confidence interval on the cash path would imply a precision we don't have.

**16. "Why does the bad quarter hurt less than the three shocks added up?"**
Because they overlap. The supplier outage hits in weeks 5–7, while demand is already down 20%, so it removes 40% of a
smaller sales base: 48,000 of lost sales instead of 60,000. At a 35% margin that's 4,200 less damage, so 53,250 becomes
49,050. The engine computes the interaction; we didn't hard-code it.

**17. "Is anything here live?"**
The cascade really recomputes: move a slider and the engine reruns on the spot (`SIMULATED`). A model answer is either a
fresh local run or a `RECORDED RUN` with its prompt and data hashes, and it's labeled as such. We never show a fake
"thinking…" animation. "Live" in the internet sense means only Live Explore with Tavily (`/explore`).

**18. "Who pays for this?"**
The people who carry a small business's cash decisions: owner-operators who run weekly cash, the fractional CFOs who
serve several such businesses at once, and the advisors who help them plan. Pricing and unit economics are hypotheses,
not results (`docs/INVESTABILITY.md` §3, labeled `ESTIMATE / HYPOTHESIS`).

**19. "Why does the dock strike in weeks 2–5 get a purchase cut in week 24?"**
Lost sales after week 26 aren't in the model, so the optimizer times cuts late. A terminal shortfall charge is the next
refinement. In the Judge's Challenge "Key distributor's dock strike", the plan (the same with Protect payroll on or off)
covers the strike with a revolver draw of 7,115.38 in week 5 and makes its only purchase cut, 7,409.81, in week 24. A
purchase cut costs lost sales for every remaining week the stock sits below its service level, and only weeks up to 26
are counted, so the latest cut looks cheapest (MATH_MODEL §10, "Known limits").

---

## Dry-run checklist

Do this on the demo laptop before going on stage (the script author could not run the web app).

- [ ] `make setup`, then `make api` and `make web` in two terminals; the header chip reads `API online`.
- [ ] **Reset the scratch store right before the stage demo:** stop the rehearsal and start `make demo-scratch` again.
      Each launch prints `[demo] scratch prediction store for this launch: …/var/scratch/<UTC stamp>/…` and starts
      empty, so a case revealed in rehearsal cannot show `SAVED AFTER A REVEAL` or an integrity ✗ on stage.
- [ ] `/rewind`: pick `fomc-2026-jul`; the header reads `Case fomc-2026-jul` + `REAL HISTORICAL` on every screen.
- [ ] `/cascade`: with no preset, **Minimum cash** reads **$63,000** ("stays above the $25,000 floor"), week 26,
      **Cash goes negative** "not within 26 weeks".
- [ ] Choose the preset **"Bad quarter: rate shock + demand drop + supplier outage"**: **Minimum cash $13,950**, sublabel
      "-$49,050 vs baseline $63,000" and "floor $25,000 · below it in weeks 20–26", **Ending cash $13,950**, Cash goes
      negative still "not within 26 weeks". If any figure differs, say the on-screen figure and tell the lead (the
      engine or data changed after this script). (Checked in the browser on 2026-11-14 for #157 at 1920 and 390 px.)
- [ ] Badges on C.0 and C.2 read `SIMULATED` and `SYNTHETIC`.
- [ ] Protect payroll: toggle it. C.3 should list purchase cuts in weeks 22–24 (together $21,006.36) and revolver
      draws in weeks 20–24, with **Min cash after plan $25,000 · week 20**; with the switch off, the same plan. If C.3
      differs, read the screen and tell the lead.
- [ ] `/research`: the cutoff reads `2026-07-22T00:00:00Z` (the selected case's) → 4 sources shown, 2 not yet public; Sequoia shows no source.
- [ ] `/rewind`, `/decision`, `/reveal`: are the 28 real cases (15 FOMC, 13 CPI) and the 1 synthetic case listed? Does the DECISION run complete? Is the Reveal button enabled?
      For each that isn't, rehearse that step's "Say instead" line.
- [ ] `/reveal`: the benchmark and both scorecards read `NOT AVAILABLE` (nothing officially scored yet). Never read a score that isn't on screen.
- [ ] `/explore`: is `TAVILY_API_KEY` set in `.env` and the local model running? If not, use the 5-second line.
- [ ] Is Ollama running with `llama3.1:8b` (`/api/health` shows `model_ready: true`)? If not, the DECISION screen must
      show a recorded run or `Local model unavailable`, never a made-up answer.
- [ ] Time a full run-through with a stopwatch: aim for 100–115 s, and write the measured time on line 3.
- [ ] Ask the lead whether the Tavily curation line (step 6, optional) is true for the merged cases.
