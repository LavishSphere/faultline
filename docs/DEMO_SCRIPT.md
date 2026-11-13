# FAULTLINE: 2-minute demo script and finance Q&A prep

**Presenter (finance voice):** Yaseen. **Length:** about 115 seconds of talking, inside the 90–120 s target (SPEC §2).
**Status of this script:** written 2026-11-13 against `main` at commit `1190671`. Every number below came from the
API running locally on that commit (calls listed in [Where the numbers come from](#where-the-numbers-come-from)).
The web app itself was **not** run while writing this (Node.js was not installed on the writing machine), so the
click paths and on-screen labels were read from the `apps/web` code. Do the [dry-run checklist](#dry-run-checklist)
before going on stage.

Steps marked **PENDING: #N** depend on work that was not merged into `main` when this was written. If it is still not
merged on demo day, the screen shows `NOT AVAILABLE`, and you say the "if still pending" line instead. Never fill a
gap with a number from memory.

---

## The 3-sentence pitch

> **Test the decision before you live with it.** FAULTLINE rewinds to a real decision point, seals everything that
> happened afterwards, and shows how a shock would cascade through a business's cash, with every number computed by
> a deterministic engine, not by an AI. Then it scores itself against the market and a coin flip on the same
> questions, and when it has not won, or has too few cases to tell, it says so on screen.

---

## Click-by-click flow

Navigation: the **→ / ←** arrow keys (or the buttons in the bottom bar) move between the five screens
`/rewind → /decision → /cascade → /reveal → /research`. The timeline at the top groups them as THEN / DECISION / REVEAL.
The LIVE EXPLORE beat is a sixth screen (`/explore`) that only exists once #61 is merged.

### Summary table

| # | Step | What to click | Label on screen | Seconds | Status |
|---|---|---|---|---|---|
| 0 | Open | Nothing; app is on `/rewind` | (title only) | 10 | works on main |
| 1 | REWIND | Pick the real case in panel **A.1 Replay cases** | `REAL HISTORICAL`, `AS-OF`, `SEALED` | 15 | **PENDING: #54 (#20), #49, #29** |
| 2 | DECISION | **→** to `/decision` | `RECORDED RUN`, `FORECAST`, market `AS-OF` "Market-implied (price-derived)" | 15 | **PENDING: #49, #45, #55** |
| 3 | CASCADE | **→** to `/cascade`; **Preset** dropdown → "Bad quarter…"; then **Protect payroll** | `SIMULATED` + `SYNTHETIC` | 30 | preset **works on main**; Protect payroll **PENDING: #69 (#17), #47, #56** |
| 4 | REVEAL | **→** to `/reveal`; **Reveal outcome** | Scorecard `INSUFFICIENT DATA: No valid comparison`; outcome `REVEALED` | 15 | scorecard label **works on main**; reveal **PENDING: #29, #50, #54** |
| 5 | RESEARCH LENS | **→** to `/research`; type cutoff `2026-07-01T00:00:00Z`; **Apply cutoff** | `REAL HISTORICAL`, `RESEARCH CONTEXT`, `AS-OF: UTC instant` | 10 | **works on main** |
| 6 | LIVE EXPLORE | Open `/explore`; type a decision; confirm the suggested scenario | `LIVE EXPLORE`, `MODEL-SUGGESTED, HUMAN TO CONFIRM`, then `SIMULATED` + `SYNTHETIC` | 15 | **PENDING: #60, #61** |
| 7 | Close | Nothing | (none) | 5 | n/a |
| | | | **Total** | **115** | |

If you are running long, cut step 6 to one sentence (5 s) and step 2 to the probability only (10 s): that gives 100 s.

---

### Step 0. Open (10 s)

- **Click:** nothing. The app is open on `/rewind`, dark theme, full screen, header chip reads `API ONLINE`.
- **Say:** "Test the decision before you live with it. We built FAULTLINE for the CFO of a small business facing a
  big unknown, like a rate decision. Everything you'll see is labeled with where it came from."
- **On screen:** the REWIND title and the THEN / DECISION / REVEAL timeline. No data label yet.

### Step 1. REWIND (15 s): **PENDING: #54 (issue #20), #49, #29**

- **Click:** in panel **A.1 Replay cases**, pick the real FOMC case. Point at **A.3 Knowledge cutoff** and the
  hatched **Sealed future** strip.
- **Say:** "We rewind to a real decision point: a Federal Reserve rate decision. This is the knowledge cutoff, to the
  minute. On the left, only evidence that was public by then. On the right, the future is sealed: the answer is not in
  the model's input, and no screen before the reveal can see it."
- **On screen:** `REAL HISTORICAL` on the evidence, `AS-OF` on the cutoff, `SEALED` on the future.
- **If still pending, the screen shows:** `NOT AVAILABLE` on every panel and `Case: NOT AVAILABLE: No case loaded` in
  the header. When this script was written (2026-11-13) `GET /api/cases` returned `"Replay cases NOT AVAILABLE: demo_cases/ has not
  been added yet (issue #20)."`
  **Say instead:** "The real replay cases are in review, so this screen honestly says NOT AVAILABLE rather than
  showing a mock-up. Let me show you the engine underneath." Then go straight to step 3.

### Step 2. DECISION (15 s): **PENDING: #49, #45, #55** (and a local model)

- **Click:** **→**. Point at **B.1 Agent probability**, then **B.2 Market at cutoff**, then the ACT / WAIT / HEDGE cards.
- **Say:** "A local open-weight model, running on this laptop with no web access, read only that sealed evidence and gave
  a probability. Next to it is what the prediction market was pricing at the same minute: a price-derived implied
  probability, not the truth. Below are three pre-declared plans, act, wait or hedge, each one costed by the cash engine,
  not by the model."
- **On screen:** `RECORDED RUN` (a saved, reproducible run with its prompt and data hashes) or a fresh local run;
  `FORECAST` on the probability; `AS-OF` and the label "Market-implied (price-derived)" on the market figure.
- **Only one of the four candidate real cases in #54 has a market price at its cutoff.** For the other cases panel B.2
  must read `NOT AVAILABLE`. Do not say a market number unless it is on screen.
- **If still pending, the screen shows:** `NOT AVAILABLE` on B.0–B.6, and **B.0** reads `Local model unavailable` when
  Ollama isn't running (it was not running when this was written: `/api/health` returned `"model_ready": false`).
  **Say instead:** "When the model isn't running, this screen says so. It never makes up an answer."

### Step 3. CASCADE (30 s): preset **works on main**; Protect payroll **PENDING: #69 (issue #17), #47, #56**

- **Click:** **→** to `/cascade`. In panel **C.1 Scenario inputs**, open the **Preset** dropdown and choose
  **"Bad quarter: rate shock + demand drop + supplier outage"**. Wait for the readout strip **C.2** to turn solid
  (the status line reads `POST /api/simulate · 200`).
- **Say (numbers are from the running API on `main`, see below):**
  "This is a fictional three-store food retailer: synthetic data, labeled that way. With no shock it ends the half-year
  with **63,000** in cash. Now a bad quarter: rates up two points, demand down a fifth for six weeks, and the main
  supplier out for three weeks. Watch it ripple: the rate node pushes up interest, the outage and demand drop cut sales,
  receipts and purchases, and it all lands on cash. Cash falls to about **25,500 in week 7**, just above our 25,000 safety
  floor, then slips **below the floor in week 20** and ends at **13,950**: **49,050 worse** than the baseline. It never
  actually runs out, so the runway reads more than 26 weeks, but a CFO would be in trouble for the last seven weeks."
- **Then (PENDING #69 / #47 / #56) click:** the **Protect payroll** switch.
  **Say:** "Now I tell the optimizer: you may not touch payroll. It picks the least harmful set of actions, such as a
  revolver draw or deferring capex, that keeps cash above the floor every week. If nothing works, it says NO FEASIBLE
  PLAN. No AI can override that."
  Read the plan **only from panel C.3 Recovery plan**. This script deliberately gives no optimizer numbers, because the
  optimizer was not on `main` when it was written.
- **On screen:** `SIMULATED` (computed by the deterministic engine) and `SYNTHETIC` (fictional business) on C.0 and C.2.
  The dependency network shows Δ = scenario − baseline at each node's peak week.
- **If Protect payroll is still pending, the screen shows:** the switch greyed out with "Optimizer not wired yet (#17)"
  and C.3 reads `NOT AVAILABLE`.
  **Say instead:** "The recovery optimizer is in review. When it's merged, this switch forces payroll cuts to zero
  inside the solver, not through a prompt."

### Step 4. REVEAL (15 s): scorecard **works on main**; reveal **PENDING: #29, #50 (PR #64), #54**

- **Click:** **→** to `/reveal`. Click **Reveal outcome** (enabled only after the prediction was saved).
- **Say:** "Only after the model's answer is saved can we unseal what actually happened. Then we score it, with the same
  rule, against the market price and against a coin flip. And here's the honest part: the scorecard says **INSUFFICIENT
  DATA**. We have fewer than five real cases, and our rule says you can't claim anything from fewer than five. One lucky
  call is an anecdote, not evidence."
- **On screen:** panel **D.1 Scorecard** with `INSUFFICIENT DATA: No valid comparison` (this label is on `main` today)
  and the rows Agent / Market-only / Naive baseline. After a reveal, the outcome panel would read `REVEALED`.
- **Do not** read out any per-case score or any outcome from memory. Say only what is on screen.
- **If the reveal is still pending:** the button is disabled with "Disabled: no persisted prediction."
  **Say instead:** "The reveal stays locked until a prediction has been saved. That lock is the point."

### Step 5. RESEARCH LENS (10 s): **works on main**

- **Click:** **→** to `/research`. In panel **E.0 Thesis Court · cutoff** (mode **Point-in-time**), replace the cutoff
  with `2026-07-01T00:00:00Z` and click **Apply cutoff**.
- **Say:** "Four venture firms' public research: Link Ventures, a16z, Sequoia and Bessemer, as context, not predictions.
  At a July 1st 2026 cutoff the system shows **4 sources** and holds back **2** that weren't public yet, including
  Sequoia's July 23rd article. We never score ourselves against these firms."
- **On screen:** `AS-OF: UTC instant` on E.0; each firm panel `REAL HISTORICAL` with a `RESEARCH CONTEXT` tag; Sequoia's
  panel shows no source at this cutoff.

### Step 6. LIVE EXPLORE (15 s): **PENDING: #60, #61** (Tavily, our sponsor)

- **Click:** open `/explore`. Type a real decision, for example "Should a three-store grocer lock in a fixed rate on its
  term loan this month?". Read the cited evidence cards, then confirm (or edit) the suggested scenario.
- **Say:** "That was the past. Live Explore is for a decision today. Tavily searches current news, and every evidence
  card links to its source with the time it was retrieved. The model only *suggests* a stress scenario; I confirm it,
  and the same deterministic engine runs the cascade. Live search powers exploration. It never touches the blind replay:
  the replay model has no web access at all, and tests check that the replay code can't reach the search."
- **On screen:** `LIVE EXPLORE` on the search results, `MODEL-SUGGESTED, HUMAN TO CONFIRM` on the scenario, "Search
  powered by Tavily", then `SIMULATED` + `SYNTHETIC` on the cascade.
- **Optional extra line (say it only if it is true for the merged cases; ask the lead):** "We also used Tavily to *find*
  candidate sources for the real replay cases, and then a person verified each one against an archived copy from before
  the cutoff. Tavily helped us search; it never decided what the model was allowed to see."
- **If still pending:** there is no `/explore` screen. `/api/health` also reports `"TAVILY_API_KEY not set: Live Explore
  web search is disabled."` on a machine without the key. **Say instead (5 s):** "Next is Live Explore with Tavily: the
  same engine on today's news, kept completely separate from the replay."

### Step 7. Close (5 s)

- **Say:** "Test the decision before you live with it. Real computation, sealed history, and a scorecard that doesn't
  lie to you."

---

## Where the numbers come from

All figures were produced by `POST /api/simulate` on `main` at `1190671`, run locally on 2026-11-13
(`uvicorn main:app --host 127.0.0.1 --port 8046` from `services/api`). The response carries
`"provenance": "SIMULATED"` and `"business_provenance": "SYNTHETIC"`. Dollar figures are rounded to the nearest dollar
for speaking. The API returns e.g. `13949.999999999944`, which the screen shows as `$13,950`.

| Request | Field | Value from the API |
|---|---|---|
| `POST /api/simulate` `{"shock": {}}` | `result.min_cash` / `min_cash_week` | 63,000 / week 26 |
| (baseline) | `result.ending_cash`, `runway_label` | 63,000, `> 26 weeks` |
| `POST /api/simulate` `{"scenario_id": "bad-quarter", "shock": <the bad-quarter shock exactly as served by GET /api/scenarios>}` | `result.min_cash` / `min_cash_week` | 13,950 / week 26 |
| (bad quarter) | `deltas.min_cash_delta` | −49,050 |
| | `result.cash` in week 7 (lowest point during the shock) | 25,523 |
| | first week with `result.cash` < 25,000 (the §10 floor) | week 20 (weeks 20–26 are all below: 7 weeks) |
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

Other calls used in this script:

- `GET /api/scenarios` → `status: AVAILABLE`, 4 scenarios: `rate-plus-200bp`, `demand-drop-20pct-6wk`,
  `supplier-outage-3wk`, `bad-quarter`.
- `GET /api/vc-lenses?as_of=2026-07-01T00:00:00Z` → `point_in_time`, 4 items (Link Ventures 1, a16z 2, Bessemer 1),
  `excluded_not_yet_public: 2`. With no `as_of` (Live Explore mode): 6 items.
- `GET /api/cases` → `status: NOT AVAILABLE` ("demo_cases/ has not been added yet (issue #20)").
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
check the headline ones by hand. What *is* real historical data is the replay evidence, the market prices at the cutoff
(where we have them), and the four firms' public research.

**2. "Why a food retailer?"**
Thin margins and weekly cash make the cascade visible. A grocer turns over inventory every couple of weeks, pays
suppliers on short terms, carries a floating-rate loan, and lives or dies on weekly cash, so a rate move, a demand dip or
a supplier outage shows up within weeks, not years. Our business already loses about 1,400 a week before any shock
(about −2.85% of sales), which is on purpose: shocks bite quickly, the way they do for real small operators. It's also a
business everyone in the room understands without a glossary.

**3. "Did your model beat the market?"**
No, and we don't claim it did. The scorecard reads `INSUFFICIENT DATA`. Our own rule (MATH_MODEL §6) says that with fewer
than five real scored cases we show no comparison at all, and even with more, we only say "better than the market" if a
95% confidence interval on the score difference is entirely below zero. Otherwise the screen says `No improvement
measured`. We also have a market price at the cutoff for only one of our candidate real cases. What we built is the
honest measuring instrument, not a victory lap.

**4. "Why is 'No improvement measured' or 'INSUFFICIENT DATA' a good result?"**
Because it's the true one, and most AI demos skip it. A system that can say "we don't know yet" is one you can trust when
it eventually says "we do". One correct call on one Fed meeting proves nothing: a coin flip gets that right half the time.
The rule was fixed before we looked at any outcome, so we can't move the goalposts.

**5. "Doesn't the model already know what happened?" (contamination)**
It might, and we say so. Turning off the internet doesn't erase what a model learned in training. Our default local
model is Llama 3.1 8B, whose published card says its training data ends in December 2023 (released July 2024). Our real
cases are 2025–26 events, after that cutoff, which lowers the risk, but we don't call it guaranteed clean. Each case
carries a contamination flag, and we have extra controls: a version of the model that runs without the market price
(so we can see whether it is just copying the market), and a deliberately planted "future fact" in the sealed data that
tests check never reaches the model (that test arrives with the replay core, PENDING: #29).

**6. "What does the optimizer do, and what doesn't it do?"** (PENDING: #69, #47, #56)
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

**8. "Does 'Protect payroll' actually protect payroll?"** (PENDING: #69, #47, #56)
Yes, mechanically. The switch sets the payroll-cut variable's upper limit to zero inside the solver, so no plan can cut
hours. It is a hard constraint in the maths, not an instruction in a prompt. There are no layoffs in the action list at
all.

**9. "Does FAULTLINE trade, lend, or fire anyone?"**
No. It never moves money, places bets, trades securities, approves or denies loans, or changes anyone's employment. It
proposes and evaluates; people decide. The market adapters are read-only public data: no accounts, no wallets, no orders.

**10. "Is the AI doing the maths?"**
No. Every number on the cascade, the readouts and the plans comes from typed Python functions and the solver, and the
same inputs always give the same output. The model's only jobs are to read sealed evidence and give a probability, and
(in Live Explore) to *suggest* a scenario that a human confirms. A separate checker rejects any claim that doesn't cite
evidence.

**11. "Is the market price the true probability?"**
No. We label it "market-implied probability, price-derived", because fees, spreads, thin trading and risk appetite all
distort it. We only use a price that was actually recorded at or just before the cutoff (no more than 24 hours old). If
there isn't one, the screen says `NOT AVAILABLE`, never an estimate.

**12. "How do you know the evidence was public at the cutoff?"**
Every item carries the time it became publicly available, and the replay only accepts items available at or before the
cutoff, to the minute. Pages that might have been edited later are checked against archived copies. If we can't prove a
date, the item is excluded. For the research lenses this is on `main` and tested today; for the replay evidence it
arrives with the replay core and the real cases (PENDING: #29, #54).

**13. "How is live search (Tavily) kept away from the blind replay?"** (PENDING: #60, #61)
They are separate modes with a wall between them. Tavily is only used in Live Explore, for decisions today, and its
results are labeled `LIVE EXPLORE: current, not point-in-time`. The replay model has no web search, no internet and no
Tavily; the planned tests check that replay code can't even import the search client and that a search result can't
pass the point-in-time gate. For building cases, Tavily can help us *find* candidate historical sources, but a person
must verify each one against an archived copy dated before the cutoff, and the tool can't write into the replay data.
That separation is the point: live search for exploring, sealed evidence for scoring.

**14. "Are the VC lenses predictions? Did you beat the VCs?"**
Neither. They are dated public writing by Link Ventures, a16z, Sequoia and Bessemer, shown as `RESEARCH CONTEXT`. A
portfolio page or an investment announcement isn't a forecast, and public firms don't publish their rejected deals or
returns, so there's nothing honest to score against. The one quote with a number in it (Bessemer's "10x" enterprise
deployment) has no defined metric or resolution source, so we don't score it. And a source only appears at a replay
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
"thinking…" animation. "Live" in the internet sense means only Live Explore with Tavily (PENDING #60, #61).

---

## Dry-run checklist

Do this on the demo laptop before going on stage (the script author could not run the web app).

- [ ] `make setup`, then `make api` and `make web` in two terminals; the header chip reads `API ONLINE`.
- [ ] `/cascade`: with no preset, **Minimum cash** reads **$63,000**, week 26, runway "more than 26 weeks".
- [ ] Choose the preset **"Bad quarter: rate shock + demand drop + supplier outage"**: **Minimum cash $13,950**, sublabel
      "-$49,050 vs baseline $63,000", **Ending cash $13,950**, runway still more than 26 weeks. If any figure differs,
      say the on-screen figure and tell the lead (the engine or data changed after this script).
- [ ] Badges on C.0 and C.2 read `SIMULATED` and `SYNTHETIC`.
- [ ] Protect payroll: is the switch enabled (#56 merged)? If yes, toggle it and note what C.3 says. If no, use the
      "if still pending" line.
- [ ] `/research`: cutoff `2026-07-01T00:00:00Z` → Apply cutoff → 4 sources shown, 2 not yet public; Sequoia shows no source.
- [ ] `/rewind`, `/decision`, `/reveal`: is a real case listed? Is a recorded run shown? Is the Reveal button enabled?
      For each that isn't, rehearse the "if still pending" line.
- [ ] `/reveal`: the scorecard reads `INSUFFICIENT DATA`. Never read a score that isn't on screen.
- [ ] `/explore`: does the screen exist (#61)? Is `TAVILY_API_KEY` set in `.env`? If not, use the 5-second line.
- [ ] Is Ollama running with `llama3.1:8b` (`/api/health` shows `model_ready: true`)? If not, the DECISION screen must
      show a recorded run or `Local model unavailable`, never a made-up answer.
- [ ] Time a full run-through with a stopwatch: aim for 100–115 s.
- [ ] Ask the lead whether the Tavily curation line (step 6, optional) is true for the merged cases.
