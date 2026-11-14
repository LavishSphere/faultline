# FAULTLINE finance glossary

Generated from `apps/web/lib/glossary.ts` and must match it exactly. Edit the TypeScript file first, then
update this page to match it.

The terms shown on the REWIND, DECISION, CASCADE, REVEAL, RESEARCH and LIVE EXPLORE screens, in plain words.
**On screen** is the exact text the screen shows (`uiLabels`, copied character for character from `apps/web`;
`apps/web/lib/glossary.test.mjs` fails if a label no longer appears there). **Short** is a tooltip (at most 15
words); **Long** is the full explanation (at most 60 words). Formulas cite `docs/MATH_MODEL.md`, which wins if
the two ever disagree.

Example numbers are traceable: MATH_MODEL §9/§10 values, or deterministic engine runs on the **SYNTHETIC** demo
business (a fictional 3-store food retailer). Money amounts are US dollars of that fictional business.
Hand-worked or hypothetical arithmetic is marked **ILLUSTRATIVE**. Terms marked *pending* describe features
that are not on `main` yet.

99 terms.

## At a glance

| Term | On screen | In plain words | Screens | Status |
|---|---|---|---|---|
| Minimum cash | `Minimum cash`, `Min cash after plan` | The lowest weekly cash balance over the 26-week horizon. | CASCADE, EXPLORE |  |
| Week of minimum cash | `Week of minimum cash` | The first week in which cash reaches its lowest level. | CASCADE, EXPLORE |  |
| Runway | `Cash goes negative`, `first week C_t < 0 (MATH_MODEL §3)` | The first week cash would go below zero, if it ever does. | CASCADE, EXPLORE |  |
| Ending cash | `Ending cash` | Cash in the bank at the end of the last week, week 26. | CASCADE, EXPLORE |  |
| Baseline | `vs baseline` | The demo business with no shock and no recovery actions. | CASCADE, EXPLORE |  |
| Starting cash (C_0) | `C_0` | Cash in the bank before week 1. | CASCADE |  |
| Horizon (T) | `> T weeks` | How far ahead the plan looks: 26 weeks, about six months. | CASCADE |  |
| Scenario (preset) | `Preset`, `Scenario inputs` | A named, fixed set of shocks used to stress-test the business. | CASCADE, EXPLORE |  |
| Demand shock (δ) | `Demand shock`, `Drop δ` | A temporary fall in customer demand, given as a percentage. | CASCADE, EXPLORE |  |
| Recovery (ρ) | `Recovery ρ` | Weeks for demand to climb back to normal after the shock ends. | CASCADE |  |
| Rate shock (Δr) | `Rate shock`, `Δr` | A change in the loan interest rate from a chosen week onward. | CASCADE, EXPLORE |  |
| Basis point (bp) | `0 bp` | One hundredth of a percentage point: 100 bp equals 1%. | CASCADE |  |
| Supplier outage (κ_t) | `Supplier outage`, `Outage`, `Supplier` | Weeks when the main supplier cannot deliver. | CASCADE, EXPLORE |  |
| Dependent share (φ) | `Dependent φ` | The share of store sales that rely on the main supplier. | CASCADE |  |
| Lost sales (λ_t) | `outage → lost sales λ_t` | Sales that cannot happen because the products are missing. | CASCADE |  |
| Dependency network | `Dependency network` | A map of how a shock travels through the business to cash. | CASCADE |  |
| Δ (change vs baseline) | `Node Δ vs baseline (from /api/simulate)` | Scenario value minus baseline value for the same quantity. | CASCADE |  |
| Demand | `Demand` | What customers would buy in a week, before any supply problem. | CASCADE |  |
| Sales | `Sales` | Net sales actually made in the week. | CASCADE |  |
| Receipts | `Receipts`, `collection timing a` | Cash actually collected from customers in the week. | CASCADE |  |
| Gross margin (g) | `(1−g)` | The share of each sales dollar left after paying for the goods sold. | CASCADE |  |
| COGS (cost of goods sold) | `replenish COGS (1−g)S_t` | What the goods that were sold cost the business to buy. | CASCADE |  |
| Purchases | `Purchases` | Spending on new stock to replace what was sold. | CASCADE |  |
| Payables (supplier lag L_p) | `Payables`, `supplier lag L_p` | Supplier bills, paid a fixed number of weeks after the purchase. | CASCADE |  |
| Inventory | `Inventory` | Stock on hand, valued at what it cost. | CASCADE |  |
| Borrowing rate (r_t) | `Rate` | The annual interest rate on the business's debt. | CASCADE |  |
| Interest | `Interest` | The weekly cost of borrowing on the term loan and the revolver. | CASCADE |  |
| Term loan | `r_t on term loan + revolver` | A 600,000 loan at a floating rate, interest-only in the demo. | CASCADE |  |
| Revolver | `Revolver`, `Revolver draw`, `Revolver repayment` | A pre-approved credit line the business can draw on and repay. | CASCADE, EXPLORE |  |
| Payroll | `Payroll`, `Payroll cut` | Wages paid to staff each week. | CASCADE, EXPLORE |  |
| Cash (C_t) | `Cash` | Money in the bank at the end of each week. | CASCADE |  |
| Backup supplier (π, F_b) | `Use backup supplier`, `backup premium π on λ_t` | A second supplier that covers an outage at a higher price. | CASCADE, EXPLORE |  |
| Protect payroll | `Protect payroll`, `On: the optimizer may not cut payroll (z_t = 0)`, `Off: payroll may be cut by up to` | A switch that forbids the optimizer from cutting payroll at all. | CASCADE |  |
| Liquidity floor (C_min) | `cash stays above the floor`, `below it in week` | The lowest cash any plan may reach: 25,000 in the demo. | CASCADE, EXPLORE |  |
| Recovery plan | `Recovery plan`, `Recovery plan · deterministic optimizer`, `Chosen actions` | The least harmful set of actions that keeps every hard limit. | CASCADE, EXPLORE |  |
| Purchase cut (v_t) | `Purchase cut` | Buying less stock in a week, drawing down inventory to save cash. | CASCADE, EXPLORE |  |
| Defer capex and delay expansion | `Defer non-critical capex`, `Delay expansion` | Yes-or-no actions: postpone planned equipment spending, or the new-store opening. | CASCADE, EXPLORE |  |
| Disruption cost (objective) | `Objective`, `disruption cost` | The optimizer's score for how harmful a plan is; lower is better. | CASCADE, EXPLORE |  |
| Binding constraint | `Binding constraints` | A limit the chosen plan is pressed right up against. | CASCADE, EXPLORE |  |
| NO FEASIBLE PLAN | `NO FEASIBLE PLAN` | No allowed mix of actions keeps all the hard limits. | CASCADE, EXPLORE |  |
| Highest feasible floor | `Highest floor a plan can hold` | The highest cash floor any plan could hold, shown when none holds 25,000. | CASCADE, EXPLORE |  |
| Knowledge cutoff (as_of) | `Knowledge cutoff`, `As-of (UTC)`, `Replay cutoff · as_of (exact instant, UTC)` | The moment in history the replay stands at; nothing later is used. | REWIND, DECISION, RESEARCH |  |
| Forecast horizon | `Horizon` | How many days after the knowledge cutoff the question is decided. | REWIND |  |
| Agent decision | `Agent decision` | The panel where the local model makes its sealed forecast for one case. | DECISION |  |
| Agent only / Agent + market | `Agent only`, `Agent + market` | The two forecast variants: without, or with, the market price in the prompt. | DECISION, REVEAL |  |
| Local open-weight model | `Local model ready`, `Local model unavailable` | An AI model with public weights, run offline on our own machine. | DECISION, EXPLORE |  |
| Chosen path | `Chosen path` | The strategy the model picked for this case: Act, Wait or Hedge. | DECISION |  |
| Agent probability (P(event)) | `Agent probability`, `P(YES) · forecast`, `p_yes (model)` | The local model's estimated chance that the event happens, from 0 to 1. | DECISION, REVEAL |  |
| Market-implied probability | `Market at cutoff`, `Market baseline · P(YES)`, `market p (market-implied, price-derived)` | A probability read from a prediction-market price (price-derived; affected by fees, spread, liquidity). | DECISION, REVEAL |  |
| Evidence citations (point-in-time) | `Evidence citations`, `Evidence at cutoff` | Sources the decision cites, all provably public by the cutoff. | DECISION |  |
| Temporal gate | `Withheld from the model by the temporal gate` | Code that removes evidence not provably public at the knowledge cutoff. | DECISION, REVEAL |  |
| Decision frame | `Decision frame (ILLUSTRATIVE policies, SYNTHETIC business)` | The business question a forecast feeds: what YES and NO mean, plus three strategies. | DECISION |  |
| ACT / WAIT / HEDGE | `ACT / WAIT / HEDGE`, `Alternative strategies · ACT / WAIT / HEDGE` | Three pre-declared strategies: commit now, hold, or limit exposure to both outcomes. | DECISION |  |
| Payoff V(a, YES) / V(a, NO) | `V(a, YES) · min cash`, `V(a, NO) · min cash` | A strategy's SIMULATED minimum cash if the event happens, and if it does not. | DECISION |  |
| Expected cash impact | `E[V] at agent p`, `E[V] at market p` | A strategy's probability-weighted minimum cash across both outcomes. | DECISION |  |
| Feasible | `Feasible in both states`, `Feasibility: not available` | Keeps every hard limit, in every week, in both outcomes. | DECISION |  |
| Recommendation | `Recommendation at agent p`, `Recommendation at market p` | The strategy with the highest E[V] among those feasible in both states. | DECISION |  |
| Break-even probability | `Break-even p*` | The probability at which the top two strategies have equal expected value. | DECISION |  |
| NO SAFE POLICY | `NO SAFE POLICY` | No strategy keeps every hard limit in both outcomes, so none is recommended. | DECISION |  |
| Integrity checks | `Integrity · what the AI could not see` | Live checks of what the model could not see: PASS, FAIL or NOT AVAILABLE. | DECISION, REVEAL |  |
| Historical outcome | `Historical outcome`, `Reveal outcome` | What really happened, y = 1 or 0, unsealed only after the forecast is saved. | REVEAL |  |
| Scorecard | `Benchmark · recorded scorecards` | Forecast scores of Agent, Market-only and Naive baseline on the same cases. | REVEAL |  |
| Brier score | `Mean Brier`, `Brier (p − y)²` | Squared gap between the forecast and what happened; lower is better. | REVEAL |  |
| Log loss | `Log loss`, `Mean log loss` | A score that punishes confident wrong forecasts heavily; lower is better. | REVEAL |  |
| Accuracy at 0.5 | `Accuracy at 0.5`, `Correct at 0.5 threshold (1 = yes)` | Whether the forecast was on the right side of 50%; a secondary score. | REVEAL |  |
| Cases (n) | `Events scored (n)`, `Sample-size caveat (from the API)` | How many events were scored; a small n means weak evidence. | REVEAL |  |
| Market-only | `Market-only` | A forecaster that simply uses the market-implied probability at the cutoff. | REVEAL |  |
| Naive baseline | `Naive baseline (p = 0.5)` | A forecaster that always says 50%, the know-nothing benchmark. | REVEAL |  |
| Δ Brier vs market | `Δ Brier vs market (paired bootstrap CI)` | Agent's average Brier score minus the market's; negative favours the agent. | REVEAL |  |
| Paired bootstrap 95% CI | `paired bootstrap CI` | A range for the score gap, built by resampling the same events 10,000 times. | REVEAL |  |
| agent better than market | `agent better than market` | Shown only if the 95% interval for agent-minus-market Brier lies entirely below zero. | REVEAL |  |
| No improvement measured | `No improvement measured` | The honest result when the agent's advantage is not clear beyond chance. | REVEAL |  |
| INSUFFICIENT DATA | `INSUFFICIENT DATA` | Too few valid cases to compare forecasters at all. | REVEAL |  |
| OFFICIAL | `Not OFFICIAL because (official_blockers, from the API)` | Label for a scorecard computed from the committed real cases in a clean run. | REVEAL |  |
| Exclusions by reason | `Exclusions by reason`, `Snapshots excluded` | Cases left out of scoring, counted by why they were dropped. | REVEAL |  |
| SEALED | `SEALED`, `Sealed future`, `Withheld until reveal` | Withheld from the model until its forecast is saved. | REWIND, REVEAL |  |
| REVEALED | `REVEALED` | The real historical outcome, unsealed after the forecast was saved. | REVEAL |  |
| SIMULATED | `SIMULATED` | Computed by FAULTLINE's deterministic simulator or optimizer, not observed. | CASCADE |  |
| SYNTHETIC | `SYNTHETIC` | Fictional demo data, not a real company. | CASCADE |  |
| ILLUSTRATIVE | `ILLUSTRATIVE` | Structure or example only, not data. | CASCADE |  |
| REAL HISTORICAL | `REAL HISTORICAL` | A genuine, dated historical record. | RESEARCH |  |
| RECORDED RUN | `RECORDED RUN` | A saved, reproducible model run, shown instead of a live one. | DECISION, REVEAL |  |
| FORECAST | `FORECAST` | A probability or projection, not an observed fact. | DECISION |  |
| AS-OF | `AS-OF` | A value as it was known at the stated knowledge cutoff. | REWIND, DECISION, RESEARCH |  |
| NOT AVAILABLE | `NOT AVAILABLE`, `Not available` | No data is served for this yet, so nothing is shown. | REWIND, DECISION, CASCADE, REVEAL, RESEARCH, EXPLORE |  |
| MODEL-SUGGESTED | `MODEL-SUGGESTED`, `Model-suggested` | A scenario input the local model proposed, for a human to confirm or edit. | EXPLORE |  |
| RESEARCH CONTEXT | `Research context` | Public venture-firm writing shown as background, never as a prediction or score. | RESEARCH |  |
| Thesis Court | `Thesis Court · cutoff` | Four firms' dated public theses on one decision, side by side. | RESEARCH |  |
| Point-in-time mode | `Point-in-time` | Shows only sources provably public at the cutoff you enter. | RESEARCH |  |
| Live Explore | `Live Explore`, `LIVE EXPLORE`, `Live Explore: current, not point-in-time` | Current, unfiltered content: not point-in-time, never used by a Blind Replay. | RESEARCH, EXPLORE |  |
| Blind Replay | `Blind Replay` | Rewind to a real past decision, hide everything later, forecast, then reveal and score. | RESEARCH, EXPLORE |  |
| Published / Proven public by | `Published`, `Proven public by` | The date on the page, and the earliest date its text is provably public. | RESEARCH |  |
| Items not yet public at this cutoff | `not yet public at this cutoff` | How many curated sources are hidden because they appeared after the cutoff. | RESEARCH |  |
| Archive capture | `Archive` | A dated Wayback Machine copy proving what a page said at that time. | RESEARCH |  |
| Documentary fact | `Documentary fact` | A statement of what the source itself says or records. | RESEARCH |  |
| Analyst interpretation | `Analyst interpretation` | An opinion or framing; not testable as stated. | RESEARCH |  |
| Quantitative forecast | `Quantitative forecast`, `Not scorable` | A forward-looking claim with a number and a time window. | RESEARCH |  |
| Model stance | `Model stance` | Where the model agreed or disagreed with a firm's thesis. | RESEARCH |  |
| Guidance range and default | `Guidance category`, `Guidance default` | The finance owner's plausible shock sizes for each kind of news. | EXPLORE |  |

## REWIND screen

### Knowledge cutoff (as_of)

- **On screen:** `Knowledge cutoff`, `As-of (UTC)`, `Replay cutoff · as_of (exact instant, UTC)`
- **Short:** The moment in history the replay stands at; nothing later is used.
- **Long:** Evidence counts only if available_at ≤ as_of, and the market quote must be the last one at or before as_of and at most 24 hours old (MATH_MODEL §7; EVALUATION_PROTOCOL §3). It is given as an exact UTC instant with a time of day, never just a date.
- **Example:** ILLUSTRATIVE: a quote from 25 hours before as_of is too old, so the market baseline reads NOT AVAILABLE.
- **Source:** MATH_MODEL §7 (24-hour staleness rule).
- **Screens:** REWIND, DECISION, RESEARCH
- **MATH_MODEL:** §7

### Forecast horizon

- **On screen:** `Horizon`
- **Short:** How many days after the knowledge cutoff the question is decided.
- **Long:** The forecast window: the question asks what happens within this many days after as_of, and the model's prompt states it ('Horizon: N days after the cutoff'). Forecasters are compared on the same event and cutoff; several horizons of one event are averaged first (MATH_MODEL §6).
- **Example:** 16 committed cases: the 15 real FOMC cases at 8 days (the window covers the statement release) and the synthetic case at 21.
- **Source:** services/api/data/demo_cases (horizon_days); core/temporal_gate.py prompt line.
- **Screens:** REWIND
- **MATH_MODEL:** §6

### SEALED

- **On screen:** `SEALED`, `Sealed future`, `Withheld until reveal`
- **Short:** Withheld from the model until its forecast is saved.
- **Long:** Outcomes live in a separate sealed store that the model's input path cannot read (EVALUATION_PROTOCOL §2, §3). A future-fact canary test plants a marker only in excluded data and checks that it never reaches a prompt.
- **Example:** A canary marker planted only in excluded data must appear in 0 prompts (test_replay_seal.py).
- **Source:** docs/EVALUATION_PROTOCOL.md §3.
- **Screens:** REWIND, REVEAL

### AS-OF

- **On screen:** `AS-OF`
- **Short:** A value as it was known at the stated knowledge cutoff.
- **Long:** Marks data fixed at the cutoff, such as the market price at that moment or the Research screen's cutoff. Nothing published later can change it.
- **Example:** Market at cutoff: the last quote at or before as_of, at most 24 hours old.
- **Source:** MATH_MODEL §7 (quote selection).
- **Screens:** REWIND, DECISION, RESEARCH
- **MATH_MODEL:** §7

### NOT AVAILABLE

- **On screen:** `NOT AVAILABLE`, `Not available`
- **Short:** No data is served for this yet, so nothing is shown.
- **Long:** FAULTLINE never fills a gap with a plausible placeholder. A panel without real data says NOT AVAILABLE and names the missing source.
- **Example:** Market baseline · P(YES) reads NOT AVAILABLE when no quote at most 24 hours old precedes the cutoff.
- **Source:** apps/web/components/replay/MarketAtCutoff.tsx; MATH_MODEL §7.
- **Screens:** REWIND, DECISION, CASCADE, REVEAL, RESEARCH, EXPLORE

## DECISION screen

### Agent decision

- **On screen:** `Agent decision`
- **Short:** The panel where the local model makes its sealed forecast for one case.
- **Long:** Pick a replay case and a variant, then run the sealed forecast. The local model reads only point-in-time evidence and returns P(YES), a chosen path and a rationale. The forecast is saved with its hashes before any outcome can be revealed; a failed run shows the failure, never a stand-in answer.
- **Example:** 2 variants to choose from: Agent only, and Agent + market.
- **Source:** apps/web/components/screens/DecisionScreen.tsx (B.0); RUN_VARIANTS in apps/web/lib/replay.ts.
- **Screens:** DECISION

### Agent only / Agent + market

- **On screen:** `Agent only`, `Agent + market`
- **Short:** The two forecast variants: without, or with, the market price in the prompt.
- **Long:** Agent only sees point-in-time evidence and no market price. Agent + market sees the same evidence plus the as-of market quote, and is refused (INSUFFICIENT_DATA) when the case has none. Each variant is scored on its own against the same two baselines (MATH_MODEL §6).
- **Example:** REVEAL shows the 2 variants' scorecards side by side.
- **Source:** RUN_VARIANTS in apps/web/lib/replay.ts; apps/web/components/Scorecard.tsx (#124).
- **Screens:** DECISION, REVEAL
- **MATH_MODEL:** §6

### Local open-weight model

- **On screen:** `Local model ready`, `Local model unavailable`
- **Short:** An AI model with public weights, run offline on our own machine.
- **Long:** The Blind Replay default (SPEC §1). It has no internet or tools during the replay. Being offline does not erase what it learned in training, so contamination risk is disclosed. It proposes; typed Python code and the optimizer do all authoritative arithmetic.
- **Example:** Replay runs use temperature 0 and a fixed seed, so a run can be reproduced.
- **Source:** docs/EVALUATION_PROTOCOL.md §2.
- **Screens:** DECISION, EXPLORE

### Chosen path

- **On screen:** `Chosen path`
- **Short:** The strategy the model picked for this case: Act, Wait or Hedge.
- **Long:** The decision field of the model's saved forecast, shown with its rationale and the skeptic's checks. It is the model's own pick, which can differ from the recommendation the engine computes from the payoffs (MATH_MODEL §8). An answer the skeptic rejects is not shown as a valid forecast.
- **Example:** In the ACT / WAIT / HEDGE cards, the strategy the model picked is marked 'Model chose'.
- **Source:** apps/web/components/screens/DecisionScreen.tsx (ChosenPath); apps/web/components/decision/SplitView.tsx.
- **Screens:** DECISION
- **MATH_MODEL:** §8

### Agent probability (P(event))

- **On screen:** `Agent probability`, `P(YES) · forecast`, `p_yes (model)`
- **Short:** The local model's estimated chance that the event happens, from 0 to 1.
- **Long:** p_yes, produced by the local model from point-in-time evidence only (MATH_MODEL §6). It is a FORECAST, not a fact, and it is saved before the outcome is revealed. Two variants are scored: agent-only, with no market price, and agent plus market.
- **Example:** p = 0.7 means a 70% chance; if the event then happens, its Brier score is 0.09.
- **Source:** MATH_MODEL §9 scoring fixtures.
- **Screens:** DECISION, REVEAL
- **MATH_MODEL:** §6

### Market-implied probability

- **On screen:** `Market at cutoff`, `Market baseline · P(YES)`, `market p (market-implied, price-derived)`
- **Short:** A probability read from a prediction-market price (price-derived; affected by fees, spread, liquidity).
- **Long:** A binary contract that pays 1 dollar if the event happens trades between 0 and 1, and that price is read as a probability (MATH_MODEL §7). It is price-derived; affected by fees, spread, liquidity. FAULTLINE uses the last quote at or before the cutoff, at most 24 hours old, otherwise NOT AVAILABLE.
- **Example:** ILLUSTRATIVE format example: a Kalshi price of '0.5600' dollars per 1-dollar contract reads as p = 0.56.
- **Source:** MATH_MODEL §7 (price format example; not a real quote).
- **Screens:** DECISION, REVEAL
- **MATH_MODEL:** §7

### Evidence citations (point-in-time)

- **On screen:** `Evidence citations`, `Evidence at cutoff`
- **Short:** Sources the decision cites, all provably public by the cutoff.
- **Long:** The decision may cite only evidence whose available_at, the conservative date it is proven public, is at or before as_of. Later sources, revised pages and unverified dates are removed by the temporal gate in code, not by the model (EVALUATION_PROTOCOL §3).
- **Example:** Sequoia's article dated 2026-07-23 counts only from 2026-07-24T12:00Z.
- **Source:** docs/DATA_PROVENANCE.md (point-in-time rule).
- **Screens:** DECISION

### Temporal gate

- **On screen:** `Withheld from the model by the temporal gate`
- **Short:** Code that removes evidence not provably public at the knowledge cutoff.
- **Long:** Evidence counts only if available_at ≤ as_of, and the market quote must be at most 24 hours old (MATH_MODEL §7; EVALUATION_PROTOCOL §3). The gate runs in code before the prompt is built, so the model never sees later items. The INTEGRITY panel counts what it withheld, by reason.
- **Example:** The same point-in-time rule on the Research screen: at as_of 2026-07-01T00:00:00Z, 2 of the 6 curated items are not yet public.
- **Source:** Engine run computed for this glossary: core/research.py eligible_lenses on research_lenses.json.
- **Screens:** DECISION, REVEAL
- **MATH_MODEL:** §7

### Decision frame

- **On screen:** `Decision frame (ILLUSTRATIVE policies, SYNTHETIC business)`
- **Short:** The business question a forecast feeds: what YES and NO mean, plus three strategies.
- **Long:** Each frame fixes the shock under YES, the path under NO, and the ACT, WAIT and HEDGE actions with every fee (MATH_MODEL §8). Frames are ILLUSTRATIVE choices on the SYNTHETIC business. If no frame matches the case, nothing is computed until the presenter picks one.
- **Example:** 3 frames: fomc-rate-decision, cpi-surprise and supply-disruption.
- **Source:** GET /api/decision/frames (services/api/data/decision_frames.json).
- **Screens:** DECISION
- **MATH_MODEL:** §8

### ACT / WAIT / HEDGE

- **On screen:** `ACT / WAIT / HEDGE`, `Alternative strategies · ACT / WAIT / HEDGE`
- **Short:** Three pre-declared strategies: commit now, hold, or limit exposure to both outcomes.
- **Long:** Each strategy is a fixed set of recovery actions, simulated under both outcomes of the forecast event: it happens (y = 1) or not (y = 0) (MATH_MODEL §8). Its payoff in each case is the SIMULATED minimum cash of the SYNTHETIC business, never trading profit.
- **Example:** Supply-disruption frame: ACT 56,320 if YES and 61,000 if NO; WAIT 42,000 and 63,000.
- **Source:** Engine run computed for this glossary: POST /api/decision on decision_frames.json supply-disruption, SIMULATED on the SYNTHETIC demo business.
- **Screens:** DECISION
- **MATH_MODEL:** §8

### Payoff V(a, YES) / V(a, NO)

- **On screen:** `V(a, YES) · min cash`, `V(a, NO) · min cash`
- **Short:** A strategy's SIMULATED minimum cash if the event happens, and if it does not.
- **Long:** V(a, y) is the lowest weekly cash balance, the minimum of C_t over the horizon, when strategy a is simulated with outcome y (MATH_MODEL §8). It measures how close the business comes to running out of cash, the same quantity as the liquidity floor. It is never trading profit.
- **Example:** Supply-disruption frame, WAIT: 42,000 if YES, 63,000 if NO.
- **Source:** Engine run computed for this glossary: POST /api/decision on decision_frames.json supply-disruption, SIMULATED on the SYNTHETIC demo business.
- **Screens:** DECISION
- **MATH_MODEL:** §8

### Expected cash impact

- **On screen:** `E[V] at agent p`, `E[V] at market p`
- **Short:** A strategy's probability-weighted minimum cash across both outcomes.
- **Long:** E[V | a] = p V(a, 1) + (1 − p) V(a, 0), where p is the forecast probability and V is minimum cash (MATH_MODEL §8). FAULTLINE recommends the strategy with the highest value among those feasible in both outcomes.
- **Example:** Supply-disruption frame at p = 0.5: ACT 0.5 × 56,320 + 0.5 × 61,000 = 58,660; WAIT 52,500.
- **Source:** Engine run computed for this glossary: POST /api/decision on decision_frames.json supply-disruption, SIMULATED on the SYNTHETIC demo business.
- **Screens:** DECISION
- **MATH_MODEL:** §8

### Feasible

- **On screen:** `Feasible in both states`, `Feasibility: not available`
- **Short:** Keeps every hard limit, in every week, in both outcomes.
- **Long:** A plan is feasible when the MATH_MODEL §4 constraints hold in each week: cash at or above the floor, revolver within its limit, inventory at or above its floor. Only strategies feasible under both outcomes can be recommended (§8).
- **Example:** With no action, Bad quarter breaks the 25,000 floor in week 20, so doing nothing is not feasible in that outcome.
- **Source:** Engine run on scenarios.json bad-quarter (PR #42; PR #72), SYNTHETIC demo business.
- **Screens:** DECISION
- **MATH_MODEL:** §4, §8

### Recommendation

- **On screen:** `Recommendation at agent p`, `Recommendation at market p`
- **Short:** The strategy with the highest E[V] among those feasible in both states.
- **Long:** Computed by the engine at the agent's forecast and, separately, at the market-implied probability (MATH_MODEL §8). If no strategy is feasible in both states it reads NO SAFE POLICY. Comparing the two shows whether the forecast changes the business decision.
- **Example:** Supply-disruption frame: ACT at p = 0.5 (58,660 against WAIT's 52,500) and at p = 0.7 (57,724 against 48,300).
- **Source:** Engine run computed for this glossary: POST /api/decision on decision_frames.json supply-disruption, SIMULATED on the SYNTHETIC demo business.
- **Screens:** DECISION
- **MATH_MODEL:** §8

### Break-even probability

- **On screen:** `Break-even p*`
- **Short:** The probability at which the top two strategies have equal expected value.
- **Long:** p-star = (V(b,0) − V(a,0)) / ((V(a,1) − V(a,0)) − (V(b,1) − V(b,0))) for the top two feasible strategies a and b (MATH_MODEL §8). On either side of it the recommendation flips. NOT AVAILABLE when the two lines are parallel, fewer than two are feasible, or it falls outside 0 to 1.
- **Example:** FOMC frame: 0.4924 (WAIT below, ACT above; HEDGE lies exactly between). CPI frame: 0.857 between WAIT and HEDGE, 0.918 between HEDGE and ACT. Supply-disruption frame: 0.1225 between ACT and WAIT.
- **Source:** Engine run computed for this glossary: POST /api/decision on all 3 frames in decision_frames.json.
- **Screens:** DECISION
- **MATH_MODEL:** §8

### NO SAFE POLICY

- **On screen:** `NO SAFE POLICY`
- **Short:** No strategy keeps every hard limit in both outcomes, so none is recommended.
- **Long:** The decision rule's honest failure (MATH_MODEL §8): a strategy is recommended only if it is feasible in both states. It differs from the optimizer's NO FEASIBLE PLAN, which searches every allowed action; NO SAFE POLICY checks only the frame's three strategies.
- **Example:** The second SYNTHETIC business's road-closure scenario, with payroll protected, reports NO SAFE POLICY.
- **Source:** MATH_MODEL §10b (protect payroll checks).
- **Screens:** DECISION
- **MATH_MODEL:** §8, §10b

### Integrity checks

- **On screen:** `Integrity · what the AI could not see`
- **Short:** Live checks of what the model could not see: PASS, FAIL or NOT AVAILABLE.
- **Long:** GET /api/integrity recomputes every check on each request from the temporal gate, the hashes, the audit log and an import scan, and names the code that enforces it. The screen never marks a check passed that the API did not report, and lists what the checks do not guarantee.
- **Example:** Checks are grouped in 3 scopes: This case, This run and The system.
- **Source:** apps/web/components/integrity/IntegrityPanel.tsx (#93).
- **Screens:** DECISION, REVEAL

### RECORDED RUN

- **On screen:** `RECORDED RUN`
- **Short:** A saved, reproducible model run, shown instead of a live one.
- **Long:** A cached genuine run with its model id, prompt hash and snapshot hash, so anyone can check it was produced as stated. It is never a canned or hand-written response, and it is labelled as recorded, not live.
- **Example:** Each recorded run carries 2 SHA-256 hashes: one of the prompt, one of the evidence snapshot.
- **Source:** SPEC §5; docs/EVALUATION_PROTOCOL.md §3.
- **Screens:** DECISION, REVEAL

### FORECAST

- **On screen:** `FORECAST`
- **Short:** A probability or projection, not an observed fact.
- **Long:** Marks a number that states a belief about the future, such as the agent's probability. It becomes scorable only once the real outcome is revealed.
- **Example:** p = 0.7 is a FORECAST until the outcome is revealed.
- **Source:** MATH_MODEL §9 scoring fixtures.
- **Screens:** DECISION

## CASCADE screen

### Minimum cash

- **On screen:** `Minimum cash`, `Min cash after plan`
- **Short:** The lowest weekly cash balance over the 26-week horizon.
- **Long:** The smallest end-of-week cash balance C_t over weeks 1 to T (MATH_MODEL §3, §8). It shows how close the business comes to running out of money. FAULTLINE ranks plans on it, because a plan can end well yet dip dangerously low mid-way.
- **Example:** 63,000 with no shock; 13,950 in the Bad quarter scenario (both in week 26).
- **Source:** Engine run (core/financials.py) on the SYNTHETIC demo business: baseline per MATH_MODEL §10, Bad quarter preset from services/api/data/scenarios.json (PR #42; recomputed from the live API in PR #72).
- **Screens:** CASCADE, EXPLORE
- **MATH_MODEL:** §3, §8

### Week of minimum cash

- **On screen:** `Week of minimum cash`
- **Short:** The first week in which cash reaches its lowest level.
- **Long:** The first week t where C_t equals minimum cash (MATH_MODEL §3). A late week means cash keeps sliding to the end of the horizon; an early week means the business dips and then recovers. Shown beside the baseline week.
- **Example:** Week 26 of 26 for both the baseline and Bad quarter: cash falls all the way to the end.
- **Source:** Engine run on the SYNTHETIC demo business (baseline and scenarios.json bad-quarter).
- **Screens:** CASCADE, EXPLORE
- **MATH_MODEL:** §3

### Runway

- **On screen:** `Cash goes negative`, `first week C_t < 0 (MATH_MODEL §3)`
- **Short:** The first week cash would go below zero, if it ever does.
- **Long:** The first week t with C_t < 0 on the simulated path (MATH_MODEL §3). If cash stays at or above zero for the whole horizon it reads 'not within 26 weeks'. It is a week, not a duration, and is never extrapolated beyond the horizon. The 25,000 liquidity floor is a separate, stricter test.
- **Example:** 'not within 26 weeks' in both the baseline and Bad quarter, because the lowest cash, 13,950, stays above zero.
- **Source:** Engine run on the SYNTHETIC demo business (runway_label of the baseline and scenarios.json bad-quarter).
- **Screens:** CASCADE, EXPLORE
- **MATH_MODEL:** §3

### Ending cash

- **On screen:** `Ending cash`
- **Short:** Cash in the bank at the end of the last week, week 26.
- **Long:** C_T, the cash balance after week T = 26 (MATH_MODEL §3). It is shown but not used to rank plans: a plan can end with plenty of cash and still breach the floor mid-horizon, which is why FAULTLINE ranks on minimum cash (§8).
- **Example:** 63,000 in the baseline versus 13,950 in Bad quarter: a difference of −49,050.
- **Source:** Engine run on the SYNTHETIC demo business (baseline and scenarios.json bad-quarter).
- **Screens:** CASCADE, EXPLORE
- **MATH_MODEL:** §3, §8

### Baseline

- **On screen:** `vs baseline`
- **Short:** The demo business with no shock and no recovery actions.
- **Long:** The reference path every scenario is compared with. It is already thin-margin: weekly gross profit of 17,500 does not cover weekly fixed costs of 18,923.08 (payroll, opex, interest), so it loses about 1,423 a week before any shock (MATH_MODEL §10, baseline economics).
- **Example:** Cash falls from 100,000 to 63,000 over 26 weeks: 100,000 − 26 × 1,423.077 = 63,000.
- **Source:** MATH_MODEL §10 baseline economics; the engine baseline run gives the same 63,000.
- **Screens:** CASCADE, EXPLORE
- **MATH_MODEL:** §10

### Starting cash (C_0)

- **On screen:** `C_0`
- **Short:** Cash in the bank before week 1.
- **Long:** The opening balance C_0 that the weekly cash recurrence starts from (MATH_MODEL §3). For the demo business it is about two weeks of sales.
- **Example:** 100,000, about 2 weeks of the 50,000 weekly sales.
- **Source:** MATH_MODEL §10 (C_0), SYNTHETIC demo business.
- **Screens:** CASCADE
- **MATH_MODEL:** §3, §10

### Horizon (T)

- **On screen:** `> T weeks`
- **Short:** How far ahead the plan looks: 26 weeks, about six months.
- **Long:** The number of weekly steps simulated, T = 26 (MATH_MODEL §0, §10). Long enough for a shock and a recovery, short enough for weekly cash planning. Runway and minimum cash are measured only inside it.
- **Example:** T = 26 weeks.
- **Source:** MATH_MODEL §10.
- **Screens:** CASCADE
- **MATH_MODEL:** §0, §10

### Scenario (preset)

- **On screen:** `Preset`, `Scenario inputs`
- **Short:** A named, fixed set of shocks used to stress-test the business.
- **Long:** A scenario is a set of deterministic shock paths for demand, the interest rate and the supplier (MATH_MODEL §1). The simulator produces no probabilities. Presets come from the API; the sliders build a custom scenario. All are SYNTHETIC stress paths, not forecasts.
- **Example:** 4 presets: +200 bp rate rise, −20% demand for 6 weeks, a 3-week supplier outage, and Bad quarter (all three at once).
- **Source:** services/api/data/scenarios.json (PR #42), served by GET /api/scenarios.
- **Screens:** CASCADE, EXPLORE
- **MATH_MODEL:** §1

### Demand shock (δ)

- **On screen:** `Demand shock`, `Drop δ`
- **Short:** A temporary fall in customer demand, given as a percentage.
- **Long:** Demand is multiplied by m_t = 1 − δ from start week t1 to end week t2, then climbs back in a straight line over ρ recovery weeks (MATH_MODEL §1). δ = 0.2 means demand is 20% lower.
- **Example:** δ = 20% from week 3: week-3 sales fall from 50,000 to 40,000.
- **Source:** Engine run on scenarios.json demand-drop-20pct-6wk, SYNTHETIC demo business.
- **Screens:** CASCADE, EXPLORE
- **MATH_MODEL:** §1

### Recovery (ρ)

- **On screen:** `Recovery ρ`
- **Short:** Weeks for demand to climb back to normal after the shock ends.
- **Long:** After week t2, m_t = 1 − δ(1 − (t − t2)/ρ) until it reaches 1 (MATH_MODEL §1). ρ = 0 means demand snaps straight back.
- **Example:** δ = 20% ending week 8 with ρ = 4: demand is 85% of normal in week 9 and 100% by week 12.
- **Source:** Engine run on scenarios.json demand-drop-20pct-6wk (demand multiplier 0.85 in week 9, 1.0 in week 12).
- **Screens:** CASCADE
- **MATH_MODEL:** §1

### Rate shock (Δr)

- **On screen:** `Rate shock`, `Δr`
- **Short:** A change in the loan interest rate from a chosen week onward.
- **Long:** r_t = base rate + Δr from week t_r onward (MATH_MODEL §1). The term loan floats, so the change passes straight into interest on the term loan and the revolver.
- **Example:** +200 bp from week 1: weekly term-loan interest rises from 923.08 to 1,153.85 (+230.77); minimum cash falls from 63,000 to 57,000.
- **Source:** Engine run on scenarios.json rate-plus-200bp; the same weekly interest as MATH_MODEL §9 Case C.
- **Screens:** CASCADE, EXPLORE
- **MATH_MODEL:** §1, §3

### Basis point (bp)

- **On screen:** `0 bp`
- **Short:** One hundredth of a percentage point: 100 bp equals 1%.
- **Long:** Rate changes are quoted in basis points to avoid mixing up percent and percentage points. A rise of 200 bp on an 8.0% rate gives 10.0%, not 8.16%.
- **Example:** 200 bp = 0.02 = 2 percentage points: 8.0% becomes 10.0%.
- **Source:** MATH_MODEL §9 Case C (8% to 10%).
- **Screens:** CASCADE

### Supplier outage (κ_t)

- **On screen:** `Supplier outage`, `Outage`, `Supplier`
- **Short:** Weeks when the main supplier cannot deliver.
- **Long:** κ_t is the share of the primary supplier's deliveries that still arrive in week t: 1 means normal, 0 means nothing (MATH_MODEL §1). Sales that depend on that supplier are lost, unless the business switches to the backup supplier.
- **Example:** κ = 0 in weeks 5 to 7 of the 3-week outage preset, and 1 in every other week.
- **Source:** services/api/data/scenarios.json supplier-outage-3wk.
- **Screens:** CASCADE, EXPLORE
- **MATH_MODEL:** §1

### Dependent share (φ)

- **On screen:** `Dependent φ`
- **Short:** The share of store sales that rely on the main supplier.
- **Long:** φ is the fraction of base-store sales whose products come from the primary distributor (MATH_MODEL §1). Only that slice is at risk in an outage. The demo value is an assumed modelling choice, not a real company's figure.
- **Example:** φ = 40%.
- **Source:** MATH_MODEL §10 (outage share), SYNTHETIC demo business.
- **Screens:** CASCADE
- **MATH_MODEL:** §1, §10

### Lost sales (λ_t)

- **On screen:** `outage → lost sales λ_t`
- **Short:** Sales that cannot happen because the products are missing.
- **Long:** Lost-sales fraction λ_t = φ(1 − κ_t) (MATH_MODEL §1); lost sales are base-store demand × λ_t when no backup supplier is used (§2). Purchases fall with the lost sales, so the net cash loss is the lost gross margin, 35% of lost sales.
- **Example:** Full outage with φ = 40%: λ = 0.4, so week-5 sales drop from 50,000 to 30,000 (20,000 lost). Over 3 weeks, cash ends 21,000 lower: 35% of 60,000.
- **Source:** Engine run on scenarios.json supplier-outage-3wk (ending-cash change −21,000), SYNTHETIC demo business.
- **Screens:** CASCADE
- **MATH_MODEL:** §1, §2

### Dependency network

- **On screen:** `Dependency network`
- **Short:** A map of how a shock travels through the business to cash.
- **Long:** Twelve nodes are model quantities and the arrows are the dependencies in MATH_MODEL §2 to §3 (§5). Each node shows its change versus the baseline, computed by the simulator, and arrows thicken with the size of the change. Before the API answers, the graph is structure only, labelled ILLUSTRATIVE.
- **Example:** 12 nodes and 15 arrows; a rate rise travels Rate → Interest → Cash.
- **Source:** CASCADE_NODE_NAMES in apps/web/lib/api.ts and the edges in apps/web/components/CascadeGraph.tsx (mirroring core/financials.py).
- **Screens:** CASCADE
- **MATH_MODEL:** §5

### Δ (change vs baseline)

- **On screen:** `Node Δ vs baseline (from /api/simulate)`
- **Short:** Scenario value minus baseline value for the same quantity.
- **Long:** Δ = value under the scenario − value in the baseline, both from the simulator (MATH_MODEL §5). On a node the screen shows the week with the largest change. For cash, a negative Δ means less money. The screen never invents a magnitude.
- **Example:** Bad quarter minimum cash Δ = 13,950 − 63,000 = −49,050.
- **Source:** Engine run (cascade_deltas min_cash_delta) on scenarios.json bad-quarter, SYNTHETIC demo business.
- **Screens:** CASCADE
- **MATH_MODEL:** §5

### Demand

- **On screen:** `Demand`
- **Short:** What customers would buy in a week, before any supply problem.
- **Long:** S^dem_t = m_t × the stores' base sales, plus any new-store sales (MATH_MODEL §2). It is the input node for a demand shock.
- **Example:** 50,000 a week across 3 stores: 18,000 + 17,000 + 15,000.
- **Source:** MATH_MODEL §10 (store weekly sales), SYNTHETIC demo business.
- **Screens:** CASCADE
- **MATH_MODEL:** §2

### Sales

- **On screen:** `Sales`
- **Short:** Net sales actually made in the week.
- **Long:** S_t = base-store demand × (1 − lost-sales fraction, unless the backup supplier is used) + new-store sales (MATH_MODEL §2). Sales drive both receipts and purchases.
- **Example:** 40,000 in week 3 of the −20% demand preset, against 50,000 normally.
- **Source:** Engine run on scenarios.json demand-drop-20pct-6wk, SYNTHETIC demo business.
- **Screens:** CASCADE
- **MATH_MODEL:** §2

### Receipts

- **On screen:** `Receipts`, `collection timing a`
- **Short:** Cash actually collected from customers in the week.
- **Long:** R_t = a S_t + (1 − a) S_{t−1} (MATH_MODEL §3). With a = 80%, most of a week's sales arrive the same week as card payments settle; the other 20% arrive the next week. The graph calls this 'collection timing a'.
- **Example:** Week 3 of the −20% demand preset: 0.8 × 40,000 + 0.2 × 50,000 = 42,000.
- **Source:** Engine run on scenarios.json demand-drop-20pct-6wk; a = 0.80 from MATH_MODEL §10.
- **Screens:** CASCADE
- **MATH_MODEL:** §3

### Gross margin (g)

- **On screen:** `(1−g)`
- **Short:** The share of each sales dollar left after paying for the goods sold.
- **Long:** g = 35% for the demo business (MATH_MODEL §10), so the cost of goods sold is (1 − g) = 65% of sales. Gross profit must then cover payroll, rent and interest.
- **Example:** 50,000 of weekly sales leaves 0.35 × 50,000 = 17,500 of gross profit.
- **Source:** MATH_MODEL §10 (gross margin and baseline economics).
- **Screens:** CASCADE
- **MATH_MODEL:** §0, §10

### COGS (cost of goods sold)

- **On screen:** `replenish COGS (1−g)S_t`
- **Short:** What the goods that were sold cost the business to buy.
- **Long:** COGS = (1 − g) S_t (MATH_MODEL §0, §3). Purchases normally replace exactly this amount of stock, which is the graph's 'replenish COGS' arrow.
- **Example:** 0.65 × 50,000 = 32,500 a week.
- **Source:** MATH_MODEL §10 (pre-horizon purchases of 32,500).
- **Screens:** CASCADE
- **MATH_MODEL:** §0, §3

### Purchases

- **On screen:** `Purchases`
- **Short:** Spending on new stock to replace what was sold.
- **Long:** P_t = (1 − g) S_t − v_t + backup premium (MATH_MODEL §3), where v_t is an optional purchase cut. Purchases are paid to the supplier L_p weeks later, as payables.
- **Example:** 32,500 a week normally; 26,000 in week 3 of the −20% demand preset.
- **Source:** Engine run on the baseline and scenarios.json demand-drop-20pct-6wk, SYNTHETIC demo business.
- **Screens:** CASCADE
- **MATH_MODEL:** §3

### Payables (supplier lag L_p)

- **On screen:** `Payables`, `supplier lag L_p`
- **Short:** Supplier bills, paid a fixed number of weeks after the purchase.
- **Long:** The supplier payment in week t is P_{t − L_p}, the purchases made L_p weeks earlier (MATH_MODEL §3). The demo uses net-14 terms, L_p = 2 weeks, so a sales drop lowers the supplier bill two weeks later.
- **Example:** The 26,000 bought in week 3 of the −20% demand preset is paid in week 5.
- **Source:** Engine run on scenarios.json demand-drop-20pct-6wk; L_p = 2 from MATH_MODEL §10.
- **Screens:** CASCADE
- **MATH_MODEL:** §3, §10

### Inventory

- **On screen:** `Inventory`
- **Short:** Stock on hand, valued at what it cost.
- **Long:** I_t = I_{t−1} − v_t (MATH_MODEL §3): it changes only through purchase cuts v_t. The optimizer keeps it at or above the floor I_min (§4). The model assumes cuts cause no stock-outs.
- **Example:** Starts at 65,000 with a 40,000 floor, so total purchase cuts are capped at 25,000.
- **Source:** MATH_MODEL §10 (starting inventory, inventory floor).
- **Screens:** CASCADE
- **MATH_MODEL:** §3, §4

### Borrowing rate (r_t)

- **On screen:** `Rate`
- **Short:** The annual interest rate on the business's debt.
- **Long:** r_t is the all-in rate, base plus spread (MATH_MODEL §0, §1). The demo term loan floats at 8.0% all-in, so a rate shock passes straight through. The revolver pays r_t plus a further 2.0%.
- **Example:** 8.0% a year; 10.0% after a +200 bp shock.
- **Source:** MATH_MODEL §10 (term loan rate); engine run on scenarios.json rate-plus-200bp (rate 0.10).
- **Screens:** CASCADE
- **MATH_MODEL:** §0, §1

### Interest

- **On screen:** `Interest`
- **Short:** The weekly cost of borrowing on the term loan and the revolver.
- **Long:** Term loan J_t = D_t r_t / 52; revolver Jᴿ_t = B_{t−1}(r_t + s_R) / 52 (MATH_MODEL §3). Debt service is always paid in full: there is no skip-a-payment option (§4).
- **Example:** 600,000 × 8.0% ÷ 52 = 923.08 a week, or 24,000 over 26 weeks.
- **Source:** MATH_MODEL §9 Case A and §10 baseline economics.
- **Screens:** CASCADE
- **MATH_MODEL:** §3, §4

### Term loan

- **On screen:** `r_t on term loan + revolver`
- **Short:** A 600,000 loan at a floating rate, interest-only in the demo.
- **Long:** D_t is the principal outstanding. Scheduled repayments A_t are 0 in the demo, so only interest is paid (MATH_MODEL §3, §10). All-in means base rate plus spread.
- **Example:** 600,000 at 8.0% all-in: 923.08 of interest a week.
- **Source:** MATH_MODEL §10 (term loan) and §9 Case A.
- **Screens:** CASCADE
- **MATH_MODEL:** §3, §10

### Revolver

- **On screen:** `Revolver`, `Revolver draw`, `Revolver repayment`
- **Short:** A pre-approved credit line the business can draw on and repay.
- **Long:** Balance B_t = B_{t−1} + draw y_t − repayment q_t (MATH_MODEL §3). It must stay between 0 and the approved limit, and be back to its opening balance by week 26, so no plan can borrow and never repay (§4). It costs the loan rate plus a 2.0% spread.
- **Example:** Limit 150,000, opening balance 0, cost 8.0% + 2.0% = 10.0% a year.
- **Source:** MATH_MODEL §10 (revolver limit, spread, opening balance).
- **Screens:** CASCADE, EXPLORE
- **MATH_MODEL:** §3, §4

### Payroll

- **On screen:** `Payroll`, `Payroll cut`
- **Short:** Wages paid to staff each week.
- **Long:** W_t is paid in full each week unless an explicit payroll-cut share z_t is chosen: the outflow is (1 − z_t) W_t (MATH_MODEL §3). Cuts are capped at 10% and carry the heaviest disruption weight of any action (§10).
- **Example:** 12,000 a week, 24% of sales.
- **Source:** MATH_MODEL §10 (payroll).
- **Screens:** CASCADE, EXPLORE
- **MATH_MODEL:** §3, §10

### Cash (C_t)

- **On screen:** `Cash`
- **Short:** Money in the bank at the end of each week.
- **Long:** C_t = C_{t−1} + receipts − supplier payments − payroll − opex − interest − loan repayment − capex − expansion − backup fee + revolver draws − revolver repayments (MATH_MODEL §3, the boxed equation). Every arrow in the network ends here.
- **Example:** Baseline week 1: 100,000 + 50,000 − 32,500 − 12,000 − 6,000 − 923.08 = 98,576.92.
- **Source:** MATH_MODEL §9 Case A; the engine baseline run of the demo business gives the same week-1 cash.
- **Screens:** CASCADE
- **MATH_MODEL:** §3

### Backup supplier (π, F_b)

- **On screen:** `Use backup supplier`, `backup premium π on λ_t`
- **Short:** A second supplier that covers an outage at a higher price.
- **Long:** Using the backup keeps the dependent sales, but those purchases cost π = 12% more, plus a one-time switching fee F_b = 2,000 in week 1 (MATH_MODEL §2, §3, §10). It is one of the optimizer's yes-or-no actions.
- **Example:** 3-week outage with the backup: sales stay 50,000; premium 1,560 a week in weeks 5 to 7; minimum cash 56,320 instead of 42,000.
- **Source:** Engine run computed for this glossary: scenarios.json supplier-outage-3wk with use_backup_supplier, SYNTHETIC demo business.
- **Screens:** CASCADE, EXPLORE
- **MATH_MODEL:** §2, §3

### Protect payroll

- **On screen:** `Protect payroll`, `On: the optimizer may not cut payroll (z_t = 0)`, `Off: payroll may be cut by up to`
- **Short:** A switch that forbids the optimizer from cutting payroll at all.
- **Long:** When on, the payroll-cut share z_t is fixed at 0 in every week, enforced inside the solver, not by a prompt (MATH_MODEL §4, constraint 5). When off, a cut of up to 10% may be chosen, but only as an explicit, labelled action. Layoffs are never modelled.
- **Example:** Judge's Challenge 'Local plant closes': on gives NO FEASIBLE PLAN; off gives a plan with payroll cuts of at most 10%, such as 1,200 in week 11.
- **Source:** Engine run computed for this glossary: POST /api/optimize on judge_challenges.json judge-plant-closure, protect payroll on and off, SYNTHETIC demo business.
- **Screens:** CASCADE
- **MATH_MODEL:** §4

### Liquidity floor (C_min)

- **On screen:** `cash stays above the floor`, `below it in week`
- **Short:** The lowest cash any plan may reach: 25,000 in the demo.
- **Long:** A hard optimizer constraint, C_t ≥ C_min in every week (MATH_MODEL §4, constraint 1). It is about two weeks of payroll: the cash a careful finance officer would not plan to go below. It is stricter than runway, which only checks for going below zero.
- **Example:** 25,000. With no action Bad quarter first falls below it in week 20; the recovery plan holds cash at exactly 25,000 from week 20.
- **Source:** MATH_MODEL §10 (liquidity floor); engine runs on scenarios.json bad-quarter: POST /api/simulate (PR #72) and POST /api/optimize (this glossary).
- **Screens:** CASCADE, EXPLORE
- **MATH_MODEL:** §4

### Recovery plan

- **On screen:** `Recovery plan`, `Recovery plan · deterministic optimizer`, `Chosen actions`
- **Short:** The least harmful set of actions that keeps every hard limit.
- **Long:** A deterministic optimizer (MILP, MATH_MODEL §4) picks from: backup supplier, defer capex, delay expansion, purchase cuts, revolver draws and, only if allowed, a payroll cut. It minimizes weighted disruption cost while holding the cash floor, revolver limit and inventory floor. No LLM can override it.
- **Example:** Bad quarter, payroll protected: purchase cuts in weeks 22 to 24 plus revolver draws in weeks 20 to 24 keep minimum cash at exactly 25,000, for a disruption cost of 1,924.71.
- **Source:** Engine run computed for this glossary: POST /api/optimize on scenarios.json bad-quarter, protect payroll on, SYNTHETIC demo business.
- **Screens:** CASCADE, EXPLORE
- **MATH_MODEL:** §4, §10

### Purchase cut (v_t)

- **On screen:** `Purchase cut`
- **Short:** Buying less stock in a week, drawing down inventory to save cash.
- **Long:** v_t lowers that week's purchases, paid L_p weeks later, and lowers inventory I_t by the same amount (MATH_MODEL §3). It is capped at 10,000 a week, and the inventory floor caps total cuts at 25,000 (§10). Disruption weight: 0.05 per dollar cut.
- **Example:** The Bad quarter plan cuts 10,000 in week 23 (the weekly cap), one of its three weeks with cuts (weeks 22 to 24).
- **Source:** Engine run computed for this glossary: POST /api/optimize on scenarios.json bad-quarter, protect payroll on, SYNTHETIC demo business.
- **Screens:** CASCADE, EXPLORE
- **MATH_MODEL:** §3, §4, §10

### Defer capex and delay expansion

- **On screen:** `Defer non-critical capex`, `Delay expansion`
- **Short:** Yes-or-no actions: postpone planned equipment spending, or the new-store opening.
- **Long:** Capex K_t is spending on equipment or fit-out; expansion E_t is the new store's costs, including its payroll and opex once it opens (MATH_MODEL §3, §10). Choosing the action removes that outflow from the horizon. Each is a single yes-or-no decision for the optimizer (§4).
- **Example:** Disruption weights: deferring capex counts as 1,000 of harm, delaying expansion as 5,000.
- **Source:** MATH_MODEL §10 disruption costs.
- **Screens:** CASCADE, EXPLORE
- **MATH_MODEL:** §3, §4, §10

### Disruption cost (objective)

- **On screen:** `Objective`, `disruption cost`
- **Short:** The optimizer's score for how harmful a plan is; lower is better.
- **Long:** Objective = weighted disruption cost of the chosen actions, minus a tiny tie-break for more cash: 0.0001 × minimum cash (MATH_MODEL §4). The weights are the finance owner's non-cash harm per action (§10), from 0.01 per dollar drawn on the revolver to 5.00 per dollar of payroll cut.
- **Example:** Bad quarter plan: disruption cost 1,924.71; objective 1,924.71 − 0.0001 × 25,000 = 1,922.21.
- **Source:** Engine run computed for this glossary: POST /api/optimize on scenarios.json bad-quarter, protect payroll on, SYNTHETIC demo business.
- **Screens:** CASCADE, EXPLORE
- **MATH_MODEL:** §4, §10

### Binding constraint

- **On screen:** `Binding constraints`
- **Short:** A limit the chosen plan is pressed right up against.
- **Long:** A constraint with slack of about zero at the optimum (MATH_MODEL §4), for example cash exactly at the floor in some week. Loosening it would allow a better plan, so it is the limit that matters most.
- **Example:** Bad quarter plan, payroll protected: 'liquidity floor, week 20' and five later weeks are binding.
- **Source:** Engine run computed for this glossary: POST /api/optimize on scenarios.json bad-quarter, protect payroll on, SYNTHETIC demo business.
- **Screens:** CASCADE, EXPLORE
- **MATH_MODEL:** §4

### NO FEASIBLE PLAN

- **On screen:** `NO FEASIBLE PLAN`
- **Short:** No allowed mix of actions keeps all the hard limits.
- **Long:** The optimizer's honest failure result (MATH_MODEL §4). It is shown as it is, with the API's diagnostic, and no LLM may override it. The screen also shows the highest floor a plan can hold, found by re-solving with the cash floor relaxed.
- **Example:** Judge's Challenge 'Local plant closes' with payroll protected: no plan keeps 25,000; the highest floor any plan can hold is 20,187.50.
- **Source:** Engine run computed for this glossary: POST /api/optimize on judge_challenges.json judge-plant-closure, protect payroll on, SYNTHETIC demo business.
- **Screens:** CASCADE, EXPLORE
- **MATH_MODEL:** §4

### Highest feasible floor

- **On screen:** `Highest floor a plan can hold`
- **Short:** The highest cash floor any plan could hold, shown when none holds 25,000.
- **Long:** A MATH_MODEL §4 diagnostic. When there is NO FEASIBLE PLAN, the optimizer re-solves with the cash floor C_min relaxed and reports the highest minimum cash any allowed plan can reach. The floor would have to be lowered to that value for a plan to exist.
- **Example:** 20,187.50 for the Judge's Challenge 'Local plant closes' with payroll protected, against the 25,000 floor.
- **Source:** Engine run computed for this glossary: POST /api/optimize on judge_challenges.json judge-plant-closure, protect payroll on, SYNTHETIC demo business.
- **Screens:** CASCADE, EXPLORE
- **MATH_MODEL:** §4

### SIMULATED

- **On screen:** `SIMULATED`
- **Short:** Computed by FAULTLINE's deterministic simulator or optimizer, not observed.
- **Long:** A figure produced by typed Python code from stated inputs and the MATH_MODEL formulas. The same inputs give the same answer every time. It is a model result, not a forecast and not a real-world record.
- **Example:** Baseline minimum cash of 63,000 is SIMULATED, on SYNTHETIC inputs.
- **Source:** Engine run on the SYNTHETIC demo business (MATH_MODEL §10).
- **Screens:** CASCADE

### SYNTHETIC

- **On screen:** `SYNTHETIC`
- **Short:** Fictional demo data, not a real company.
- **Long:** The demo business is an invented 3-store food retailer. Its parameters are assumed modelling choices set with the finance owner (MATH_MODEL §10), not figures from any real company.
- **Example:** 50,000 weekly sales, 100,000 starting cash and a 600,000 term loan are all SYNTHETIC.
- **Source:** MATH_MODEL §10; services/api/data/demo_business.json.
- **Screens:** CASCADE

### ILLUSTRATIVE

- **On screen:** `ILLUSTRATIVE`
- **Short:** Structure or example only, not data.
- **Long:** Marks a picture or example that shows how something works without real values, such as the cascade graph before the first simulator response, or a hand-worked example in this glossary.
- **Example:** The dependency network shows 12 nodes and no values until POST /api/simulate answers.
- **Source:** apps/web/components/cascade/CascadeWorkbench.tsx (C.0 panel).
- **Screens:** CASCADE

## REVEAL screen

### Historical outcome

- **On screen:** `Historical outcome`, `Reveal outcome`
- **Short:** What really happened, y = 1 or 0, unsealed only after the forecast is saved.
- **Long:** Panel D.0 reveals one saved forecast's outcome with an explicit click. The server reads the sealed outcome only after the prediction is stored with its hashes, logs the reveal, then scores that forecast and the two baselines on it (MATH_MODEL §6; EVALUATION_PROTOCOL §3).
- **Example:** If y = 1 and the agent said p = 0.7: Brier 0.09, log loss 0.356675.
- **Source:** MATH_MODEL §9 scoring fixtures.
- **Screens:** REVEAL
- **MATH_MODEL:** §6

### Scorecard

- **On screen:** `Benchmark · recorded scorecards`
- **Short:** Forecast scores of Agent, Market-only and Naive baseline on the same cases.
- **Long:** Compares forecasters on identical event and cutoff pairs (MATH_MODEL §6). Lower Brier and log loss are better. It shows sample size, exclusions and one paired-bootstrap confidence interval, and never a placeholder number: with no computed benchmark it reads INSUFFICIENT DATA.
- **Example:** Columns Mean Brier, Mean log loss and Accuracy at 0.5, for Agent, Market-only and Naive baseline (p = 0.5).
- **Source:** apps/web/components/Scorecard.tsx.
- **Screens:** REVEAL
- **MATH_MODEL:** §6

### Brier score

- **On screen:** `Mean Brier`, `Brier (p − y)²`
- **Short:** Squared gap between the forecast and what happened; lower is better.
- **Long:** Brier = (p − y)², where p is the forecast probability and y is 1 if the event happened, else 0 (MATH_MODEL §6). 0 is perfect; always saying 0.5 scores 0.25; a confident wrong forecast scores up to 1.
- **Example:** p = 0.7 and the event happened: (0.7 − 1)² = 0.09.
- **Source:** MATH_MODEL §9 scoring fixtures (also core/evaluator.py brier).
- **Screens:** REVEAL
- **MATH_MODEL:** §6

### Log loss

- **On screen:** `Log loss`, `Mean log loss`
- **Short:** A score that punishes confident wrong forecasts heavily; lower is better.
- **Long:** Log loss = −y ln p − (1 − y) ln(1 − p), with p kept between 0.000001 and 0.999999 so a certain wrong forecast costs 13.8 rather than infinity (MATH_MODEL §6).
- **Example:** p = 0.7 and the event happened: −ln 0.7 = 0.356675.
- **Source:** MATH_MODEL §9 scoring fixtures (also core/evaluator.py log_loss).
- **Screens:** REVEAL
- **MATH_MODEL:** §6

### Accuracy at 0.5

- **On screen:** `Accuracy at 0.5`, `Correct at 0.5 threshold (1 = yes)`
- **Short:** Whether the forecast was on the right side of 50%; a secondary score.
- **Long:** A forecast counts as YES when p > 0.5; p = 0.5 counts as NO, fixed in advance (MATH_MODEL §6). It ignores confidence, so Brier score and log loss are the main scores. When both forecasters say YES on almost every event it tells little (§6 statistical review).
- **Example:** p = 0.7 and the event happened: correct, scored 1; p = 0.5 and it happened: scored 0.
- **Source:** core/evaluator.py accuracy rule (p > 0.5 means YES).
- **Screens:** REVEAL
- **MATH_MODEL:** §6

### Cases (n)

- **On screen:** `Events scored (n)`, `Sample-size caveat (from the API)`
- **Short:** How many events were scored; a small n means weak evidence.
- **Long:** n counts events, the unit of resampling; several snapshots of one event are averaged first (MATH_MODEL §6). Below 5 the scorecard reads INSUFFICIENT DATA; from 5 to 29 it adds a 'small sample' caveat.
- **Example:** n = 4 gives INSUFFICIENT DATA; n = 29 gives the small-sample caveat; n = 30 has no caveat.
- **Source:** MATH_MODEL §6 display rules; tested at n = 29 and n = 30 (EVALUATION_PROTOCOL §3).
- **Screens:** REVEAL
- **MATH_MODEL:** §6

### Market-only

- **On screen:** `Market-only`
- **Short:** A forecaster that simply uses the market-implied probability at the cutoff.
- **Long:** The benchmark the agent is compared with on the same event and cutoff (MATH_MODEL §6). If no quote at most 24 hours old exists, this baseline is NOT AVAILABLE (§7). Its probability is price-derived; affected by fees, spread, liquidity.
- **Example:** ILLUSTRATIVE: a market at 0.56 for an event that happens scores (0.56 − 1)² = 0.1936.
- **Source:** Hand arithmetic on the MATH_MODEL §7 price format example; not a real quote.
- **Screens:** REVEAL
- **MATH_MODEL:** §6, §7

### Naive baseline

- **On screen:** `Naive baseline (p = 0.5)`
- **Short:** A forecaster that always says 50%, the know-nothing benchmark.
- **Long:** p = 0.5 for every event (MATH_MODEL §6). Any useful forecaster should beat it. Its score does not depend on what happens.
- **Example:** Brier 0.25 and log loss 0.693147, whatever the outcome.
- **Source:** MATH_MODEL §9 scoring fixtures.
- **Screens:** REVEAL
- **MATH_MODEL:** §6

### Δ Brier vs market

- **On screen:** `Δ Brier vs market (paired bootstrap CI)`
- **Short:** Agent's average Brier score minus the market's; negative favours the agent.
- **Long:** Mean Brier of the agent − mean Brier of the market over the same events (MATH_MODEL §6). A negative value means the agent was more accurate, but it counts only if the whole 95% confidence interval is below zero.
- **Example:** ILLUSTRATIVE, one case: agent p = 0.7 scores 0.09, a market at 0.56 scores 0.1936, so Δ = −0.1036. One case proves nothing.
- **Source:** Hand arithmetic on MATH_MODEL §9 fixture (0.09) and the §7 price format example; not a FAULTLINE result.
- **Screens:** REVEAL
- **MATH_MODEL:** §6

### Paired bootstrap 95% CI

- **On screen:** `paired bootstrap CI`
- **Short:** A range for the score gap, built by resampling the same events 10,000 times.
- **Long:** Events are redrawn with replacement B = 10,000 times, keeping each agent and market score paired on its event. The middle 95% of the resulting Brier gaps is the confidence interval (MATH_MODEL §6). It shows how far the gap could move by chance.
- **Example:** B = 10,000 resamples; 95% percentile interval.
- **Source:** MATH_MODEL §6.
- **Screens:** REVEAL
- **MATH_MODEL:** §6

### agent better than market

- **On screen:** `agent better than market`
- **Short:** Shown only if the 95% interval for agent-minus-market Brier lies entirely below zero.
- **Long:** Shown only if the whole 95% paired-bootstrap interval for mean Brier, agent minus market, is below zero, with at least 5 events (MATH_MODEL §6). Otherwise the scorecard reads No improvement measured, or INSUFFICIENT DATA below 5 events. It is the API's verdict (evaluator AGENT_BETTER), never set by the browser.
- **Example:** The screen refuses a card where the verdict and the interval disagree: an upper bound of 0.01 with this verdict is rejected; −0.001 is accepted.
- **Source:** apps/web/lib/contracts.test.mjs (AGENT_BETTER holds exactly when ci_high < 0); core/evaluator.py.
- **Screens:** REVEAL
- **MATH_MODEL:** §6

### No improvement measured

- **On screen:** `No improvement measured`
- **Short:** The honest result when the agent's advantage is not clear beyond chance.
- **Long:** Shown unless the upper end of the 95% confidence interval for the Brier gap is below zero (MATH_MODEL §6). A lucky case, or a small edge that could be noise, does not count as an improvement over the market.
- **Example:** ILLUSTRATIVE: an interval from −0.05 to +0.01 crosses zero, so it reads No improvement measured.
- **Source:** MATH_MODEL §6 display rule; the interval is hypothetical.
- **Screens:** REVEAL
- **MATH_MODEL:** §6

### INSUFFICIENT DATA

- **On screen:** `INSUFFICIENT DATA`
- **Short:** Too few valid cases to compare forecasters at all.
- **Long:** Shown when fewer than 5 events can be scored (MATH_MODEL §6). Per-event scores may still be listed, but no average comparison and no winner is claimed.
- **Example:** n < 5: a recorded scorecard with fewer than five scored events. Today no scorecard is recorded, so the screen reads NOT AVAILABLE instead.
- **Source:** MATH_MODEL §6; docs/EVALUATION_PROTOCOL.md status line; apps/web/components/Scorecard.tsx.
- **Screens:** REVEAL
- **MATH_MODEL:** §6

### OFFICIAL

- **On screen:** `Not OFFICIAL because (official_blockers, from the API)`
- **Short:** Label for a scorecard computed from the committed real cases in a clean run.
- **Long:** Given only if every condition holds: the configured case folder and sealed store, no operator-controllable exclusion on a real case, and every scored forecast saved before the first counted reveal (EVALUATION_PROTOCOL §3). Otherwise the card is ILLUSTRATIVE and lists each failed condition. Synthetic cards are never OFFICIAL.
- **Example:** 4 operator-controllable exclusion reasons block it, such as a forecast saved after the outcome was revealed.
- **Source:** docs/EVALUATION_PROTOCOL.md §3.
- **Screens:** REVEAL

### Exclusions by reason

- **On screen:** `Exclusions by reason`, `Snapshots excluded`
- **Short:** Cases left out of scoring, counted by why they were dropped.
- **Long:** Every event is either scored or excluded with a stated reason, so poor results cannot be quietly dropped. Reasons include no saved prediction, more than one prediction, a prediction saved after the outcome was revealed, and case data changed after the run (EVALUATION_PROTOCOL §3).
- **Example:** 4 operator-controllable reasons; any one of them on a real case blocks the OFFICIAL label.
- **Source:** docs/EVALUATION_PROTOCOL.md §3.
- **Screens:** REVEAL

### REVEALED

- **On screen:** `REVEALED`
- **Short:** The real historical outcome, unsealed after the forecast was saved.
- **Long:** The outcome y, 1 if it happened and 0 if not, is read only after the prediction is stored with its hashes, and every reveal is logged (EVALUATION_PROTOCOL §3). Only then is the forecast scored.
- **Example:** If y = 1 and the agent said p = 0.7, its Brier score is 0.09.
- **Source:** MATH_MODEL §9 scoring fixtures.
- **Screens:** REVEAL
- **MATH_MODEL:** §6

## RESEARCH screen

### REAL HISTORICAL

- **On screen:** `REAL HISTORICAL`
- **Short:** A genuine, dated historical record.
- **Long:** Public documents or market data as they actually existed, with source and date. On the Research screen it marks the public venture-firm writing; it does not mean the content is true or audited.
- **Example:** The 6 research items from 4 venture firms are REAL HISTORICAL.
- **Source:** services/api/data/research_lenses.json; docs/DATA_PROVENANCE.md.
- **Screens:** RESEARCH

### RESEARCH CONTEXT

- **On screen:** `Research context`
- **Short:** Public venture-firm writing shown as background, never as a prediction or score.
- **Long:** Labels the Research Lens. These are articles and portfolio pages by four venture firms. They are not records of the firms' investment decisions, and FAULTLINE never scores them or compares itself with them (SPEC §7).
- **Example:** 6 items: 2 Link Ventures, 2 a16z, 1 Sequoia, 1 Bessemer.
- **Source:** services/api/data/research_lenses.json; docs/DATA_PROVENANCE.md.
- **Screens:** RESEARCH

### Thesis Court

- **On screen:** `Thesis Court · cutoff`
- **Short:** Four firms' dated public theses on one decision, side by side.
- **Long:** For a chosen cutoff, the Research screen shows which published theses from Link Ventures, a16z, Sequoia and Bessemer bear on the decision, and what each supports or challenges. The API decides which were public; the browser does not filter or score.
- **Example:** At as_of 2026-07-01T00:00:00Z: 4 items shown, 2 not yet public.
- **Source:** Engine run computed for this glossary: core/research.py eligible_lenses on research_lenses.json.
- **Screens:** RESEARCH

### Point-in-time mode

- **On screen:** `Point-in-time`
- **Short:** Shows only sources provably public at the cutoff you enter.
- **Long:** The default Research view. The API returns only content fields for items public by as_of and reports how many it held back; curation notes dated after the cutoff are hidden.
- **Example:** At as_of 2023-06-01T00:00:00Z: 0 items shown, 6 not yet public.
- **Source:** Engine run computed for this glossary: core/research.py eligible_lenses on research_lenses.json.
- **Screens:** RESEARCH

### Live Explore

- **On screen:** `Live Explore`, `LIVE EXPLORE`, `Live Explore: current, not point-in-time`
- **Short:** Current, unfiltered content: not point-in-time, never used by a Blind Replay.
- **Long:** On the Research screen, a mode that shows every curated item with its full sourcing (archive capture, access date, limitations) and ignores the cutoff. The Live Explore screen searches today's web through Tavily. Neither is point-in-time, so neither may be used for a Blind Replay.
- **Example:** 6 curated items, with as_of null.
- **Source:** services/api/data/research_lenses.json; apps/web/components/ThesisCourt.tsx; apps/web/components/explore/LiveExplorePanel.tsx.
- **Screens:** RESEARCH, EXPLORE

### Blind Replay

- **On screen:** `Blind Replay`
- **Short:** Rewind to a real past decision, hide everything later, forecast, then reveal and score.
- **Long:** FAULTLINE's signature test (SPEC §0, §5). The model sees only point-in-time evidence; outcomes stay sealed until its forecast is saved, and then it is scored against the market-only and naive baselines.
- **Example:** Scored against 2 baselines: market-only and naive (p = 0.5).
- **Source:** MATH_MODEL §6.
- **Screens:** RESEARCH, EXPLORE
- **MATH_MODEL:** §6

### Published / Proven public by

- **On screen:** `Published`, `Proven public by`
- **Short:** The date on the page, and the earliest date its text is provably public.
- **Long:** Proven public by (available_at) is conservative: the later of the page's date and any machine-readable publish timestamp, or for undated pages the earliest archive capture containing every quote. A day-only date counts from noon UTC the next day, once it has ended everywhere (DATA_PROVENANCE).
- **Example:** a16z 'Investing in Stitch': published 2026-05-13, proven public 2026-05-14, usable from 2026-05-15T12:00Z.
- **Source:** docs/DATA_PROVENANCE.md.
- **Screens:** RESEARCH

### Items not yet public at this cutoff

- **On screen:** `not yet public at this cutoff`
- **Short:** How many curated sources are hidden because they appeared after the cutoff.
- **Long:** Reported by the API in point-in-time mode, so the presenter can see that sources were held back, not lost. A count of 0 means every curated item was public by then.
- **Example:** At as_of 2025-09-01T00:00:00Z: 4 not yet public, 2 shown.
- **Source:** Engine run computed for this glossary: core/research.py eligible_lenses on research_lenses.json.
- **Screens:** RESEARCH

### Archive capture

- **On screen:** `Archive`
- **Short:** A dated Wayback Machine copy proving what a page said at that time.
- **Long:** Every quote was checked word for word against an Internet Archive capture as well as the live page, because living pages change (DATA_PROVENANCE). Shown in Live Explore.
- **Example:** Bessemer 'The State of AI 2025': capture of 2025-08-13T21:24:01Z.
- **Source:** docs/DATA_PROVENANCE.md.
- **Screens:** RESEARCH

### Documentary fact

- **On screen:** `Documentary fact`
- **Short:** A statement of what the source itself says or records.
- **Long:** A fact as documented on the page, such as deal terms or a stated investment focus. Documented means the firm says it, not that FAULTLINE verified it; self-reported metrics are not audited.
- **Example:** Sequoia: leading Etched's 300 million dollar Series C at a 10 billion dollar pre-money valuation.
- **Source:** services/api/data/research_lenses.json (sequoia-partnering-with-etched).
- **Screens:** RESEARCH

### Analyst interpretation

- **On screen:** `Analyst interpretation`
- **Short:** An opinion or framing; not testable as stated.
- **Long:** A view, belief, risk framing or expectation without a number and a time window. Useful context, but it cannot be scored.
- **Example:** Sequoia: 'The intelligence race is fundamentally compute constrained.'
- **Source:** services/api/data/research_lenses.json (sequoia-partnering-with-etched).
- **Screens:** RESEARCH

### Quantitative forecast

- **On screen:** `Quantitative forecast`, `Not scorable`
- **Short:** A forward-looking claim with a number and a time window.
- **Long:** The only quote of this kind is Bessemer's. It has no defined metric, baseline or resolution source, so it cannot be scored as stated, is marked Not scorable, and FAULTLINE does not score it.
- **Example:** Bessemer: 'enterprise deployment will 10x' in 2025 to 2026.
- **Source:** services/api/data/research_lenses.json (bessemer-state-of-ai-2025); docs/DATA_PROVENANCE.md.
- **Screens:** RESEARCH

### Model stance

- **On screen:** `Model stance`
- **Short:** Where the model agreed or disagreed with a firm's thesis.
- **Long:** A field reserved for the model's position on each thesis. It reads NOT AVAILABLE until a replay run supplies it.
- **Example:** Shown on each of the 4 firm panels; NOT AVAILABLE on main.
- **Source:** apps/web/components/ThesisCourt.tsx.
- **Screens:** RESEARCH

## LIVE EXPLORE screen

### MODEL-SUGGESTED

- **On screen:** `MODEL-SUGGESTED`, `Model-suggested`
- **Short:** A scenario input the local model proposed, for a human to confirm or edit.
- **Long:** On Live Explore the local model reads cited news results and may propose shock sizes. Each must sit inside the finance owner's guidance range for its category, and the presenter edits and confirms before the engine runs. It is neither a forecast nor a fact.
- **Example:** The badge appears only when at least 1 number came from the model; otherwise the inputs are guidance defaults.
- **Source:** apps/web/components/explore/ExploreScenario.tsx; apps/web/lib/explore.ts.
- **Screens:** EXPLORE

### Guidance range and default

- **On screen:** `Guidance category`, `Guidance default`
- **Short:** The finance owner's plausible shock sizes for each kind of news.
- **Long:** ILLUSTRATIVE modelling choices for the SYNTHETIC business, by news category: a minimum, default and maximum for each shock field (MATH_MODEL §1, §10). They bound what the model may suggest and fill in when it gives no usable numbers. They are not forecasts of what any event will do.
- **Example:** Central-bank rate surprise: Δr from +25 bp to +100 bp, default +50 bp.
- **Source:** services/api/data/explore_shock_guidance.json (central-bank-rate-surprise).
- **Screens:** EXPLORE
- **MATH_MODEL:** §1
