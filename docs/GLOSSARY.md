# FAULTLINE finance glossary

Generated from `apps/web/lib/glossary.ts` and must match it exactly. Edit the TypeScript file first, then
update this page to match it.

Every term shown on the CASCADE, DECISION, REVEAL and RESEARCH screens, in plain words. **Short** is a tooltip
(at most 15 words); **Long** is the full explanation (at most 60 words). Formulas cite `docs/MATH_MODEL.md`,
which wins if the two ever disagree.

Example numbers are traceable: MATH_MODEL §9/§10 values, or deterministic engine runs on the **SYNTHETIC** demo
business (a fictional 3-store food retailer). Money amounts are US dollars of that fictional business.
Hand-worked or hypothetical arithmetic is marked **ILLUSTRATIVE**. Terms marked *pending* describe features
that are not on `main` yet.

81 terms.

## At a glance

| Term | In plain words | Screens | Status |
|---|---|---|---|
| Minimum cash | The lowest weekly cash balance over the 26-week horizon. | CASCADE, DECISION |  |
| Week of minimum cash | The first week in which cash reaches its lowest level. | CASCADE |  |
| Runway | The first week cash would go below zero, if it ever does. | CASCADE |  |
| Ending cash | Cash in the bank at the end of the last week, week 26. | CASCADE |  |
| Baseline | The demo business with no shock and no recovery actions. | CASCADE |  |
| Starting cash (C_0) | Cash in the bank before week 1. | CASCADE |  |
| Horizon (T) | How far ahead the plan looks: 26 weeks, about six months. | CASCADE |  |
| Scenario (preset) | A named, fixed set of shocks used to stress-test the business. | CASCADE |  |
| Bad quarter | The demo's harshest preset: rate, demand and supplier shocks in one quarter. | CASCADE |  |
| Demand shock (δ) | A temporary fall in customer demand, given as a percentage. | CASCADE |  |
| Recovery (ρ) | Weeks for demand to climb back to normal after the shock ends. | CASCADE |  |
| Rate shock (Δr) | A change in the loan interest rate from a chosen week onward. | CASCADE |  |
| Basis point (bp) | One hundredth of a percentage point: 100 bp equals 1%. | CASCADE |  |
| Supplier outage (κ_t) | Weeks when the main supplier cannot deliver. | CASCADE |  |
| Dependent share (φ) | The share of store sales that rely on the main supplier. | CASCADE |  |
| Lost sales (λ_t) | Sales that cannot happen because the products are missing. | CASCADE |  |
| Dependency network | A map of how a shock travels through the business to cash. | CASCADE |  |
| Δ (change vs baseline) | Scenario value minus baseline value for the same quantity. | CASCADE |  |
| Demand | What customers would buy in a week, before any supply problem. | CASCADE |  |
| Sales | Net sales actually made in the week. | CASCADE |  |
| Receipts | Cash actually collected from customers in the week. | CASCADE |  |
| Gross margin (g) | The share of each sales dollar left after paying for the goods sold. | CASCADE |  |
| COGS (cost of goods sold) | What the goods that were sold cost the business to buy. | CASCADE |  |
| Purchases | Spending on new stock to replace what was sold. | CASCADE |  |
| Payables (supplier lag L_p) | Supplier bills, paid a fixed number of weeks after the purchase. | CASCADE |  |
| Inventory | Stock on hand, valued at what it cost. | CASCADE |  |
| Borrowing rate (r_t) | The annual interest rate on the business's debt. | CASCADE |  |
| Interest | The weekly cost of borrowing on the term loan and the revolver. | CASCADE |  |
| Term loan | A 600,000 loan at a floating rate, interest-only in the demo. | CASCADE |  |
| Revolver | A pre-approved credit line the business can draw on and repay. | CASCADE |  |
| Payroll | Wages paid to staff each week. | CASCADE |  |
| Cash (C_t) | Money in the bank at the end of each week. | CASCADE |  |
| Backup supplier (π, F_b) | A second supplier that covers an outage at a higher price. | CASCADE |  |
| Protect payroll | A switch that forbids the optimizer from cutting payroll at all. | CASCADE | pending #17 |
| Liquidity floor (C_min) | The lowest cash any plan may reach: 25,000 in the demo. | CASCADE | pending #17 |
| Recovery plan | The least harmful set of actions that keeps every hard limit. | CASCADE | pending #17 |
| NO FEASIBLE PLAN | No allowed mix of actions keeps all the hard limits. | CASCADE | pending #17 |
| Binding constraint | A limit the chosen plan is pressed right up against. | CASCADE | pending #17 |
| Knowledge cutoff (as_of) | The moment in history the replay stands at; nothing later is used. | DECISION, RESEARCH |  |
| Evidence citations (point-in-time) | Sources the decision cites, all provably public by the cutoff. | DECISION |  |
| Local open-weight model | An AI model with public weights, run offline on our own machine. | DECISION |  |
| Agent probability (P(event)) | The local model's estimated chance that the event happens, from 0 to 1. | DECISION, REVEAL |  |
| Market-implied probability | A probability read from a prediction-market price (price-derived; affected by fees, spread, liquidity). | DECISION, REVEAL |  |
| ACT / WAIT / HEDGE | Three pre-declared strategies: commit now, hold, or limit exposure to both outcomes. | DECISION | pending #55 |
| Expected cash impact | A strategy's probability-weighted minimum cash across both outcomes. | DECISION | pending #55 |
| Worst-case min cash | A strategy's lower minimum cash of the two outcomes. | DECISION | pending #55 |
| Feasible | Keeps every hard limit, in every week, in both outcomes. | DECISION | pending #55 |
| Scorecard | Forecast scores of Agent, Market-only and Naive baseline on the same cases. | REVEAL |  |
| Brier score | Squared gap between the forecast and what happened; lower is better. | REVEAL |  |
| Log loss | A score that punishes confident wrong forecasts heavily; lower is better. | REVEAL |  |
| Cases (n) | How many events were scored; a small n means weak evidence. | REVEAL |  |
| Market-only | A forecaster that simply uses the market-implied probability at the cutoff. | REVEAL |  |
| Naive baseline | A forecaster that always says 50%, the know-nothing benchmark. | REVEAL |  |
| Δ Brier vs market | Agent's average Brier score minus the market's; negative favours the agent. | REVEAL |  |
| Paired bootstrap 95% CI | A range for the score gap, built by resampling the same events 10,000 times. | REVEAL |  |
| Exclusions by reason | Cases left out of scoring, counted by why they were dropped. | REVEAL |  |
| No improvement measured | The honest result when the agent's advantage is not clear beyond chance. | REVEAL |  |
| INSUFFICIENT DATA | Too few valid cases to compare forecasters at all. | REVEAL |  |
| SEALED | Withheld from the model until its forecast is saved. | REVEAL |  |
| REVEALED | The real historical outcome, unsealed after the forecast was saved. | REVEAL |  |
| SIMULATED | Computed by FAULTLINE's deterministic simulator or optimizer, not observed. | CASCADE |  |
| SYNTHETIC | Fictional demo data, not a real company. | CASCADE |  |
| ILLUSTRATIVE | Structure or example only, not data. | CASCADE |  |
| REAL HISTORICAL | A genuine, dated historical record. | RESEARCH |  |
| RECORDED RUN | A saved, reproducible model run, shown instead of a live one. | DECISION |  |
| FORECAST | A probability or projection, not an observed fact. | DECISION |  |
| AS-OF | A value as it was known at the stated knowledge cutoff. | DECISION, RESEARCH |  |
| NOT AVAILABLE | No data is served for this yet, so nothing is shown. | CASCADE, DECISION, REVEAL, RESEARCH |  |
| RESEARCH CONTEXT | Public venture-firm writing shown as background, never as a prediction or score. | RESEARCH |  |
| Thesis Court | Four firms' dated public theses on one decision, side by side. | RESEARCH |  |
| Point-in-time mode | Shows only sources provably public at the cutoff you enter. | RESEARCH |  |
| Live Explore | Today's view: every curated item, not filtered to any cutoff. | RESEARCH |  |
| Blind Replay | Rewind to a real past decision, hide everything later, forecast, then reveal and score. | RESEARCH |  |
| Published / Proven public by | The date on the page, and the earliest date its text is provably public. | RESEARCH |  |
| Items not yet public at this cutoff | How many curated sources are hidden because they appeared after the cutoff. | RESEARCH |  |
| Archive capture | A dated Wayback Machine copy proving what a page said at that time. | RESEARCH |  |
| Documentary fact | A statement of what the source itself says or records. | RESEARCH |  |
| Analyst interpretation | An opinion or framing; not testable as stated. | RESEARCH |  |
| Quantitative forecast | A forward-looking claim with a number and a time window. | RESEARCH |  |
| Model stance | Where the model agreed or disagreed with a firm's thesis. | RESEARCH |  |
| DSCR (debt service coverage ratio) | Cash available for debt payments divided by the debt payments due. | none yet | pending #85 |

## CASCADE screen

### Minimum cash

- **Short:** The lowest weekly cash balance over the 26-week horizon.
- **Long:** The smallest end-of-week cash balance C_t over weeks 1 to T (MATH_MODEL §3, §8). It shows how close the business comes to running out of money. FAULTLINE ranks plans on it, because a plan can end well yet dip dangerously low mid-way.
- **Example:** 63,000 with no shock; 13,950 in the Bad quarter scenario (both in week 26).
- **Source:** Engine run (core/financials.py) on the SYNTHETIC demo business: baseline per MATH_MODEL §10, Bad quarter preset from services/api/data/scenarios.json (PR #42; recomputed from the live API in PR #72).
- **Screens:** CASCADE, DECISION
- **MATH_MODEL:** §3, §8

### Week of minimum cash

- **Short:** The first week in which cash reaches its lowest level.
- **Long:** The first week t where C_t equals minimum cash (MATH_MODEL §3). A late week means cash keeps sliding to the end of the horizon; an early week means the business dips and then recovers. Shown beside the baseline week.
- **Example:** Week 26 of 26 for both the baseline and Bad quarter: cash falls all the way to the end.
- **Source:** Engine run on the SYNTHETIC demo business (baseline and scenarios.json bad-quarter).
- **Screens:** CASCADE
- **MATH_MODEL:** §3

### Runway

- **Short:** The first week cash would go below zero, if it ever does.
- **Long:** The first week t with C_t < 0 on the simulated path (MATH_MODEL §3). If cash stays at or above zero for the whole horizon it reads '> 26 weeks'. FAULTLINE never extrapolates a burn-rate runway beyond the horizon. The 25,000 liquidity floor is a separate, stricter test.
- **Example:** '> 26 weeks' in both the baseline and Bad quarter, because the lowest cash, 13,950, stays above zero.
- **Source:** Engine run on the SYNTHETIC demo business (runway_label of the baseline and scenarios.json bad-quarter).
- **Screens:** CASCADE
- **MATH_MODEL:** §3

### Ending cash

- **Short:** Cash in the bank at the end of the last week, week 26.
- **Long:** C_T, the cash balance after week T = 26 (MATH_MODEL §3). It is shown but not used to rank plans: a plan can end with plenty of cash and still breach the floor mid-horizon, which is why FAULTLINE ranks on minimum cash (§8).
- **Example:** 63,000 in the baseline versus 13,950 in Bad quarter: a difference of −49,050.
- **Source:** Engine run on the SYNTHETIC demo business (baseline and scenarios.json bad-quarter).
- **Screens:** CASCADE
- **MATH_MODEL:** §3, §8

### Baseline

- **Short:** The demo business with no shock and no recovery actions.
- **Long:** The reference path every scenario is compared with. It is already thin-margin: weekly gross profit of 17,500 does not cover weekly fixed costs of 18,923.08 (payroll, opex, interest), so it loses about 1,423 a week before any shock (MATH_MODEL §10, baseline economics).
- **Example:** Cash falls from 100,000 to 63,000 over 26 weeks: 100,000 − 26 × 1,423.077 = 63,000.
- **Source:** MATH_MODEL §10 baseline economics; the engine baseline run gives the same 63,000.
- **Screens:** CASCADE
- **MATH_MODEL:** §10

### Starting cash (C_0)

- **Short:** Cash in the bank before week 1.
- **Long:** The opening balance C_0 that the weekly cash recurrence starts from (MATH_MODEL §3). For the demo business it is about two weeks of sales.
- **Example:** 100,000, about 2 weeks of the 50,000 weekly sales.
- **Source:** MATH_MODEL §10 (C_0), SYNTHETIC demo business.
- **Screens:** CASCADE
- **MATH_MODEL:** §3, §10

### Horizon (T)

- **Short:** How far ahead the plan looks: 26 weeks, about six months.
- **Long:** The number of weekly steps simulated, T = 26 (MATH_MODEL §0, §10). Long enough for a shock and a recovery, short enough for weekly cash planning. Runway and minimum cash are measured only inside it.
- **Example:** T = 26 weeks.
- **Source:** MATH_MODEL §10.
- **Screens:** CASCADE
- **MATH_MODEL:** §0, §10

### Scenario (preset)

- **Short:** A named, fixed set of shocks used to stress-test the business.
- **Long:** A scenario is a set of deterministic shock paths for demand, the interest rate and the supplier (MATH_MODEL §1). The simulator produces no probabilities. Presets come from the API; the sliders build a custom scenario. All are SYNTHETIC stress paths, not forecasts.
- **Example:** 4 presets: +200 bp rate rise, −20% demand for 6 weeks, a 3-week supplier outage, and Bad quarter (all three at once).
- **Source:** services/api/data/scenarios.json (PR #42), served by GET /api/scenarios.
- **Screens:** CASCADE
- **MATH_MODEL:** §1

### Bad quarter

- **Short:** The demo's harshest preset: rate, demand and supplier shocks in one quarter.
- **Long:** Combines +200 bp on the loan rate from week 1, a 20% demand drop in weeks 3 to 8 with 4 recovery weeks, and a primary-supplier outage in weeks 5 to 7 with 40% of sales dependent. The shocks compound on a business that already loses about 1,423 a week.
- **Example:** Minimum cash 13,950 in week 26; cash first falls below the 25,000 floor in week 20.
- **Source:** Engine run on scenarios.json bad-quarter (PR #42; recomputed from the live API in PR #72). SYNTHETIC.
- **Screens:** CASCADE
- **MATH_MODEL:** §1

### Demand shock (δ)

- **Short:** A temporary fall in customer demand, given as a percentage.
- **Long:** Demand is multiplied by m_t = 1 − δ from start week t1 to end week t2, then climbs back in a straight line over ρ recovery weeks (MATH_MODEL §1). δ = 0.2 means demand is 20% lower.
- **Example:** δ = 20% from week 3: week-3 sales fall from 50,000 to 40,000.
- **Source:** Engine run on scenarios.json demand-drop-20pct-6wk, SYNTHETIC demo business.
- **Screens:** CASCADE
- **MATH_MODEL:** §1

### Recovery (ρ)

- **Short:** Weeks for demand to climb back to normal after the shock ends.
- **Long:** After week t2, m_t = 1 − δ(1 − (t − t2)/ρ) until it reaches 1 (MATH_MODEL §1). ρ = 0 means demand snaps straight back.
- **Example:** δ = 20% ending week 8 with ρ = 4: demand is 85% of normal in week 9 and 100% by week 12.
- **Source:** Engine run on scenarios.json demand-drop-20pct-6wk (demand multiplier 0.85 in week 9, 1.0 in week 12).
- **Screens:** CASCADE
- **MATH_MODEL:** §1

### Rate shock (Δr)

- **Short:** A change in the loan interest rate from a chosen week onward.
- **Long:** r_t = base rate + Δr from week t_r onward (MATH_MODEL §1). The term loan floats, so the change passes straight into interest on the term loan and the revolver.
- **Example:** +200 bp from week 1: weekly term-loan interest rises from 923.08 to 1,153.85 (+230.77); minimum cash falls from 63,000 to 57,000.
- **Source:** Engine run on scenarios.json rate-plus-200bp; the same weekly interest as MATH_MODEL §9 Case C.
- **Screens:** CASCADE
- **MATH_MODEL:** §1, §3

### Basis point (bp)

- **Short:** One hundredth of a percentage point: 100 bp equals 1%.
- **Long:** Rate changes are quoted in basis points to avoid mixing up percent and percentage points. A rise of 200 bp on an 8.0% rate gives 10.0%, not 8.16%.
- **Example:** 200 bp = 0.02 = 2 percentage points: 8.0% becomes 10.0%.
- **Source:** MATH_MODEL §9 Case C (8% to 10%).
- **Screens:** CASCADE

### Supplier outage (κ_t)

- **Short:** Weeks when the main supplier cannot deliver.
- **Long:** κ_t is the share of the primary supplier's deliveries that still arrive in week t: 1 means normal, 0 means nothing (MATH_MODEL §1). Sales that depend on that supplier are lost, unless the business switches to the backup supplier.
- **Example:** κ = 0 in weeks 5 to 7 of the 3-week outage preset, and 1 in every other week.
- **Source:** services/api/data/scenarios.json supplier-outage-3wk.
- **Screens:** CASCADE
- **MATH_MODEL:** §1

### Dependent share (φ)

- **Short:** The share of store sales that rely on the main supplier.
- **Long:** φ is the fraction of base-store sales whose products come from the primary distributor (MATH_MODEL §1). Only that slice is at risk in an outage. The demo value is an assumed modelling choice, not a real company's figure.
- **Example:** φ = 40%.
- **Source:** MATH_MODEL §10 (outage share), SYNTHETIC demo business.
- **Screens:** CASCADE
- **MATH_MODEL:** §1, §10

### Lost sales (λ_t)

- **Short:** Sales that cannot happen because the products are missing.
- **Long:** Lost-sales fraction λ_t = φ(1 − κ_t) (MATH_MODEL §1); lost sales are base-store demand × λ_t when no backup supplier is used (§2). Purchases fall with the lost sales, so the net cash loss is the lost gross margin, 35% of lost sales.
- **Example:** Full outage with φ = 40%: λ = 0.4, so week-5 sales drop from 50,000 to 30,000 (20,000 lost). Over 3 weeks, cash ends 21,000 lower: 35% of 60,000.
- **Source:** Engine run on scenarios.json supplier-outage-3wk (ending-cash change −21,000), SYNTHETIC demo business.
- **Screens:** CASCADE
- **MATH_MODEL:** §1, §2

### Dependency network

- **Short:** A map of how a shock travels through the business to cash.
- **Long:** Twelve nodes are model quantities and the arrows are the dependencies in MATH_MODEL §2 to §3 (§5). Each node shows its change versus the baseline, computed by the simulator, and arrows thicken with the size of the change. Before the API answers, the graph is structure only, labelled ILLUSTRATIVE.
- **Example:** 12 nodes and 15 arrows; a rate rise travels Rate → Interest → Cash.
- **Source:** CASCADE_NODE_NAMES in apps/web/lib/api.ts and the edges in apps/web/components/CascadeGraph.tsx (mirroring core/financials.py).
- **Screens:** CASCADE
- **MATH_MODEL:** §5

### Δ (change vs baseline)

- **Short:** Scenario value minus baseline value for the same quantity.
- **Long:** Δ = value under the scenario − value in the baseline, both from the simulator (MATH_MODEL §5). On a node the screen shows the week with the largest change. For cash, a negative Δ means less money. The screen never invents a magnitude.
- **Example:** Bad quarter minimum cash Δ = 13,950 − 63,000 = −49,050.
- **Source:** Engine run (cascade_deltas min_cash_delta) on scenarios.json bad-quarter, SYNTHETIC demo business.
- **Screens:** CASCADE
- **MATH_MODEL:** §5

### Demand

- **Short:** What customers would buy in a week, before any supply problem.
- **Long:** S^dem_t = m_t × the stores' base sales, plus any new-store sales (MATH_MODEL §2). It is the input node for a demand shock.
- **Example:** 50,000 a week across 3 stores: 18,000 + 17,000 + 15,000.
- **Source:** MATH_MODEL §10 (store weekly sales), SYNTHETIC demo business.
- **Screens:** CASCADE
- **MATH_MODEL:** §2

### Sales

- **Short:** Net sales actually made in the week.
- **Long:** S_t = base-store demand × (1 − lost-sales fraction, unless the backup supplier is used) + new-store sales (MATH_MODEL §2). Sales drive both receipts and purchases.
- **Example:** 40,000 in week 3 of the −20% demand preset, against 50,000 normally.
- **Source:** Engine run on scenarios.json demand-drop-20pct-6wk, SYNTHETIC demo business.
- **Screens:** CASCADE
- **MATH_MODEL:** §2

### Receipts

- **Short:** Cash actually collected from customers in the week.
- **Long:** R_t = a S_t + (1 − a) S_{t−1} (MATH_MODEL §3). With a = 80%, most of a week's sales arrive the same week as card payments settle; the other 20% arrive the next week. The graph calls this 'collection timing a'.
- **Example:** Week 3 of the −20% demand preset: 0.8 × 40,000 + 0.2 × 50,000 = 42,000.
- **Source:** Engine run on scenarios.json demand-drop-20pct-6wk; a = 0.80 from MATH_MODEL §10.
- **Screens:** CASCADE
- **MATH_MODEL:** §3

### Gross margin (g)

- **Short:** The share of each sales dollar left after paying for the goods sold.
- **Long:** g = 35% for the demo business (MATH_MODEL §10), so the cost of goods sold is (1 − g) = 65% of sales. Gross profit must then cover payroll, rent and interest.
- **Example:** 50,000 of weekly sales leaves 0.35 × 50,000 = 17,500 of gross profit.
- **Source:** MATH_MODEL §10 (gross margin and baseline economics).
- **Screens:** CASCADE
- **MATH_MODEL:** §0, §10

### COGS (cost of goods sold)

- **Short:** What the goods that were sold cost the business to buy.
- **Long:** COGS = (1 − g) S_t (MATH_MODEL §0, §3). Purchases normally replace exactly this amount of stock, which is the graph's 'replenish COGS' arrow.
- **Example:** 0.65 × 50,000 = 32,500 a week.
- **Source:** MATH_MODEL §10 (pre-horizon purchases of 32,500).
- **Screens:** CASCADE
- **MATH_MODEL:** §0, §3

### Purchases

- **Short:** Spending on new stock to replace what was sold.
- **Long:** P_t = (1 − g) S_t − v_t + backup premium (MATH_MODEL §3), where v_t is an optional purchase cut. Purchases are paid to the supplier L_p weeks later, as payables.
- **Example:** 32,500 a week normally; 26,000 in week 3 of the −20% demand preset.
- **Source:** Engine run on the baseline and scenarios.json demand-drop-20pct-6wk, SYNTHETIC demo business.
- **Screens:** CASCADE
- **MATH_MODEL:** §3

### Payables (supplier lag L_p)

- **Short:** Supplier bills, paid a fixed number of weeks after the purchase.
- **Long:** The supplier payment in week t is P_{t − L_p}, the purchases made L_p weeks earlier (MATH_MODEL §3). The demo uses net-14 terms, L_p = 2 weeks, so a sales drop lowers the supplier bill two weeks later.
- **Example:** The 26,000 bought in week 3 of the −20% demand preset is paid in week 5.
- **Source:** Engine run on scenarios.json demand-drop-20pct-6wk; L_p = 2 from MATH_MODEL §10.
- **Screens:** CASCADE
- **MATH_MODEL:** §3, §10

### Inventory

- **Short:** Stock on hand, valued at what it cost.
- **Long:** I_t = I_{t−1} − v_t (MATH_MODEL §3): it changes only through purchase cuts v_t. The optimizer keeps it at or above the floor I_min (§4). The model assumes cuts cause no stock-outs.
- **Example:** Starts at 65,000 with a 40,000 floor, so total purchase cuts are capped at 25,000.
- **Source:** MATH_MODEL §10 (starting inventory, inventory floor).
- **Screens:** CASCADE
- **MATH_MODEL:** §3, §4

### Borrowing rate (r_t)

- **Short:** The annual interest rate on the business's debt.
- **Long:** r_t is the all-in rate, base plus spread (MATH_MODEL §0, §1). The demo term loan floats at 8.0% all-in, so a rate shock passes straight through. The revolver pays r_t plus a further 2.0%.
- **Example:** 8.0% a year; 10.0% after a +200 bp shock.
- **Source:** MATH_MODEL §10 (term loan rate); engine run on scenarios.json rate-plus-200bp (rate 0.10).
- **Screens:** CASCADE
- **MATH_MODEL:** §0, §1

### Interest

- **Short:** The weekly cost of borrowing on the term loan and the revolver.
- **Long:** Term loan J_t = D_t r_t / 52; revolver Jᴿ_t = B_{t−1}(r_t + s_R) / 52 (MATH_MODEL §3). Debt service is always paid in full: there is no skip-a-payment option (§4).
- **Example:** 600,000 × 8.0% ÷ 52 = 923.08 a week, or 24,000 over 26 weeks.
- **Source:** MATH_MODEL §9 Case A and §10 baseline economics.
- **Screens:** CASCADE
- **MATH_MODEL:** §3, §4

### Term loan

- **Short:** A 600,000 loan at a floating rate, interest-only in the demo.
- **Long:** D_t is the principal outstanding. Scheduled repayments A_t are 0 in the demo, so only interest is paid (MATH_MODEL §3, §10). All-in means base rate plus spread.
- **Example:** 600,000 at 8.0% all-in: 923.08 of interest a week.
- **Source:** MATH_MODEL §10 (term loan) and §9 Case A.
- **Screens:** CASCADE
- **MATH_MODEL:** §3, §10

### Revolver

- **Short:** A pre-approved credit line the business can draw on and repay.
- **Long:** Balance B_t = B_{t−1} + draw y_t − repayment q_t (MATH_MODEL §3). It must stay between 0 and the approved limit, and be back to its opening balance by week 26, so no plan can borrow and never repay (§4). It costs the loan rate plus a 2.0% spread.
- **Example:** Limit 150,000, opening balance 0, cost 8.0% + 2.0% = 10.0% a year.
- **Source:** MATH_MODEL §10 (revolver limit, spread, opening balance).
- **Screens:** CASCADE
- **MATH_MODEL:** §3, §4

### Payroll

- **Short:** Wages paid to staff each week.
- **Long:** W_t is paid in full each week unless an explicit payroll-cut share z_t is chosen: the outflow is (1 − z_t) W_t (MATH_MODEL §3). Cuts are capped at 10% and carry the heaviest disruption weight of any action (§10).
- **Example:** 12,000 a week, 24% of sales.
- **Source:** MATH_MODEL §10 (payroll).
- **Screens:** CASCADE
- **MATH_MODEL:** §3, §10

### Cash (C_t)

- **Short:** Money in the bank at the end of each week.
- **Long:** C_t = C_{t−1} + receipts − supplier payments − payroll − opex − interest − loan repayment − capex − expansion − backup fee + revolver draws − revolver repayments (MATH_MODEL §3, the boxed equation). Every arrow in the network ends here.
- **Example:** Baseline week 1: 100,000 + 50,000 − 32,500 − 12,000 − 6,000 − 923.08 = 98,576.92.
- **Source:** MATH_MODEL §9 Case A; the engine baseline run of the demo business gives the same week-1 cash.
- **Screens:** CASCADE
- **MATH_MODEL:** §3

### Backup supplier (π, F_b)

- **Short:** A second supplier that covers an outage at a higher price.
- **Long:** Using the backup keeps the dependent sales, but those purchases cost π = 12% more, plus a one-time switching fee F_b = 2,000 in week 1 (MATH_MODEL §2, §3, §10). It is one of the optimizer's yes-or-no actions.
- **Example:** 3-week outage with the backup: sales stay 50,000; premium 1,560 a week in weeks 5 to 7; minimum cash 56,320 instead of 42,000.
- **Source:** Engine run computed for this glossary: scenarios.json supplier-outage-3wk with use_backup_supplier, SYNTHETIC demo business.
- **Screens:** CASCADE
- **MATH_MODEL:** §2, §3

### Protect payroll

- **Short:** A switch that forbids the optimizer from cutting payroll at all.
- **Long:** When on, the payroll-cut share z_t is fixed at 0 in every week, enforced inside the solver, not by a prompt (MATH_MODEL §4, constraint 5). When off, a cut of up to 10% may be chosen, but only as an explicit, labelled action. Layoffs are never modelled.
- **Example:** On: payroll stays 12,000 a week. Off: at most a 10% cut, to 12,000 × 0.9 = 10,800.
- **Source:** MATH_MODEL §10 (payroll, payroll-cut cap 0.10); hand arithmetic.
- **Screens:** CASCADE
- **MATH_MODEL:** §4
- **Status:** *pending #17 (recovery optimizer, PR #69 open); the switch is shown but disabled on main*

### Liquidity floor (C_min)

- **Short:** The lowest cash any plan may reach: 25,000 in the demo.
- **Long:** A hard optimizer constraint, C_t ≥ C_min in every week (MATH_MODEL §4, constraint 1). It is about two weeks of payroll: the cash a careful finance officer would not plan to go below. It is stricter than runway, which only checks for going below zero.
- **Example:** 25,000. With no action, Bad quarter first falls below it in week 20.
- **Source:** MATH_MODEL §10 (liquidity floor); engine run on scenarios.json bad-quarter (PR #42; PR #72).
- **Screens:** CASCADE
- **MATH_MODEL:** §4
- **Status:** *pending #17 (recovery optimizer, PR #69 open)*

### Recovery plan

- **Short:** The least harmful set of actions that keeps every hard limit.
- **Long:** A deterministic optimizer (MILP, MATH_MODEL §4) picks from: backup supplier, defer capex, delay expansion, purchase cuts, revolver draws and, only if allowed, a payroll cut. It minimizes weighted disruption cost while holding the cash floor, revolver limit and inventory floor. No LLM can override it.
- **Example:** Disruption weights run from 0.01 per dollar for a revolver draw (gentlest) to 5.00 per dollar for a payroll cut (harshest).
- **Source:** MATH_MODEL §10 disruption costs.
- **Screens:** CASCADE
- **MATH_MODEL:** §4, §10
- **Status:** *pending #17 (recovery optimizer, PR #69 open)*

### NO FEASIBLE PLAN

- **Short:** No allowed mix of actions keeps all the hard limits.
- **Long:** The optimizer's honest failure result (MATH_MODEL §4). It is shown as it is, with the binding constraint named, and no LLM may override it. A useful follow-up is to re-solve with a lower cash floor to find the smallest floor that can be met.
- **Example:** Example pending #17: no optimizer result is on main yet.
- **Source:** No FAULTLINE figure yet.
- **Screens:** CASCADE
- **MATH_MODEL:** §4
- **Status:** *pending #17 (recovery optimizer, PR #69 open)*

### Binding constraint

- **Short:** A limit the chosen plan is pressed right up against.
- **Long:** A constraint with slack of about zero at the optimum (MATH_MODEL §4), for example cash exactly at the floor in some week. Loosening it would allow a better plan, so it is the limit that matters most.
- **Example:** ILLUSTRATIVE: cash at exactly the 25,000 floor in some week would mean the floor binds. Real example pending #17.
- **Source:** MATH_MODEL §10 (liquidity floor); no optimizer result on main yet.
- **Screens:** CASCADE
- **MATH_MODEL:** §4
- **Status:** *pending #17 (recovery optimizer, PR #69 open)*

### SIMULATED

- **Short:** Computed by FAULTLINE's deterministic simulator or optimizer, not observed.
- **Long:** A figure produced by typed Python code from stated inputs and the MATH_MODEL formulas. The same inputs give the same answer every time. It is a model result, not a forecast and not a real-world record.
- **Example:** Baseline minimum cash of 63,000 is SIMULATED, on SYNTHETIC inputs.
- **Source:** Engine run on the SYNTHETIC demo business (MATH_MODEL §10).
- **Screens:** CASCADE

### SYNTHETIC

- **Short:** Fictional demo data, not a real company.
- **Long:** The demo business is an invented 3-store food retailer. Its parameters are assumed modelling choices set with the finance owner (MATH_MODEL §10), not figures from any real company.
- **Example:** 50,000 weekly sales, 100,000 starting cash and a 600,000 term loan are all SYNTHETIC.
- **Source:** MATH_MODEL §10; services/api/data/demo_business.json.
- **Screens:** CASCADE

### ILLUSTRATIVE

- **Short:** Structure or example only, not data.
- **Long:** Marks a picture or example that shows how something works without real values, such as the cascade graph before the first simulator response, or a hand-worked example in this glossary.
- **Example:** The dependency network shows 12 nodes and no values until POST /api/simulate answers.
- **Source:** apps/web/components/cascade/CascadeWorkbench.tsx (C.0 panel).
- **Screens:** CASCADE

### NOT AVAILABLE

- **Short:** No data is served for this yet, so nothing is shown.
- **Long:** FAULTLINE never fills a gap with a plausible placeholder. A panel without real data says NOT AVAILABLE and names the missing source.
- **Example:** The Recovery plan panel reads NOT AVAILABLE until POST /api/optimize exists (#17).
- **Source:** apps/web/components/cascade/CascadeWorkbench.tsx (C.3 panel); apps/web/lib/api.ts PENDING_ENDPOINTS.
- **Screens:** CASCADE, DECISION, REVEAL, RESEARCH

## DECISION screen

### Knowledge cutoff (as_of)

- **Short:** The moment in history the replay stands at; nothing later is used.
- **Long:** Evidence counts only if available_at ≤ as_of, and the market quote must be the last one at or before as_of and at most 24 hours old (MATH_MODEL §7; EVALUATION_PROTOCOL §3). It is given as an exact UTC instant with a time of day, never just a date.
- **Example:** ILLUSTRATIVE: a quote from 25 hours before as_of is too old, so the market baseline reads NOT AVAILABLE.
- **Source:** MATH_MODEL §7 (24-hour staleness rule).
- **Screens:** DECISION, RESEARCH
- **MATH_MODEL:** §7

### Evidence citations (point-in-time)

- **Short:** Sources the decision cites, all provably public by the cutoff.
- **Long:** The decision may cite only evidence whose available_at, the conservative date it is proven public, is at or before as_of. Later sources, revised pages and unverified dates are removed by the temporal gate in code, not by the model (EVALUATION_PROTOCOL §3).
- **Example:** Sequoia's article dated 2026-07-23 counts only from 2026-07-24T12:00Z.
- **Source:** docs/DATA_PROVENANCE.md (point-in-time rule).
- **Screens:** DECISION

### Local open-weight model

- **Short:** An AI model with public weights, run offline on our own machine.
- **Long:** The Blind Replay default (SPEC §1). It has no internet or tools during the replay. Being offline does not erase what it learned in training, so contamination risk is disclosed. It proposes; typed Python code and the optimizer do all authoritative arithmetic.
- **Example:** Replay runs use temperature 0 and a fixed seed, so a run can be reproduced.
- **Source:** docs/EVALUATION_PROTOCOL.md §2.
- **Screens:** DECISION

### Agent probability (P(event))

- **Short:** The local model's estimated chance that the event happens, from 0 to 1.
- **Long:** p_yes, produced by the local model from point-in-time evidence only (MATH_MODEL §6). It is a FORECAST, not a fact, and it is saved before the outcome is revealed. Two variants are scored: agent-only, with no market price, and agent plus market.
- **Example:** p = 0.7 means a 70% chance; if the event then happens, its Brier score is 0.09.
- **Source:** MATH_MODEL §9 scoring fixtures.
- **Screens:** DECISION, REVEAL
- **MATH_MODEL:** §6

### Market-implied probability

- **Short:** A probability read from a prediction-market price (price-derived; affected by fees, spread, liquidity).
- **Long:** A binary contract that pays 1 dollar if the event happens trades between 0 and 1, and that price is read as a probability (MATH_MODEL §7). It is price-derived; affected by fees, spread, liquidity. FAULTLINE uses the last quote at or before the cutoff, at most 24 hours old, otherwise NOT AVAILABLE.
- **Example:** ILLUSTRATIVE format example: a Kalshi price of '0.5600' dollars per 1-dollar contract reads as p = 0.56.
- **Source:** MATH_MODEL §7 (price format example; not a real quote).
- **Screens:** DECISION, REVEAL
- **MATH_MODEL:** §7

### ACT / WAIT / HEDGE

- **Short:** Three pre-declared strategies: commit now, hold, or limit exposure to both outcomes.
- **Long:** Each strategy is a fixed set of recovery actions, simulated under both outcomes of the forecast event: it happens (y = 1) or not (y = 0) (MATH_MODEL §8). Its payoff in each case is the SIMULATED minimum cash of the SYNTHETIC business, never trading profit.
- **Example:** Example pending #55: no strategy payoffs are served to the screen yet.
- **Source:** No FAULTLINE figure on screen yet (payoff engine core/decision.py merged in PR #35).
- **Screens:** DECISION
- **MATH_MODEL:** §8
- **Status:** *pending #55 (ACT/WAIT/HEDGE split view)*

### Expected cash impact

- **Short:** A strategy's probability-weighted minimum cash across both outcomes.
- **Long:** E[V | a] = p V(a, 1) + (1 − p) V(a, 0), where p is the forecast probability and V is minimum cash (MATH_MODEL §8). FAULTLINE recommends the strategy with the highest value among those feasible in both outcomes.
- **Example:** ILLUSTRATIVE arithmetic only: p = 0.7, V = 63,000 if yes and 13,950 if no gives 0.7 × 63,000 + 0.3 × 13,950 = 48,285.
- **Source:** Hand arithmetic reusing two SIMULATED minimum-cash figures (baseline, Bad quarter); not a FAULTLINE strategy result.
- **Screens:** DECISION
- **MATH_MODEL:** §8
- **Status:** *pending #55 (ACT/WAIT/HEDGE split view)*

### Worst-case min cash

- **Short:** A strategy's lower minimum cash of the two outcomes.
- **Long:** The smaller of V(a, 1) and V(a, 0) from MATH_MODEL §8: the cash low point if the less favourable outcome happens. It shows the downside whatever the probability.
- **Example:** ILLUSTRATIVE arithmetic only: the lower of 63,000 and 13,950 is 13,950.
- **Source:** Hand arithmetic on two SIMULATED minimum-cash figures (baseline, Bad quarter); not a FAULTLINE strategy result.
- **Screens:** DECISION
- **MATH_MODEL:** §8
- **Status:** *pending #55 (ACT/WAIT/HEDGE split view)*

### Feasible

- **Short:** Keeps every hard limit, in every week, in both outcomes.
- **Long:** A plan is feasible when the MATH_MODEL §4 constraints hold in each week: cash at or above the floor, revolver within its limit, inventory at or above its floor. Only strategies feasible under both outcomes can be recommended (§8).
- **Example:** With no action, Bad quarter breaks the 25,000 floor in week 20, so doing nothing is not feasible in that outcome.
- **Source:** Engine run on scenarios.json bad-quarter (PR #42; PR #72), SYNTHETIC demo business.
- **Screens:** DECISION
- **MATH_MODEL:** §4, §8
- **Status:** *pending #55 (ACT/WAIT/HEDGE split view)*

### RECORDED RUN

- **Short:** A saved, reproducible model run, shown instead of a live one.
- **Long:** A cached genuine run with its model id, prompt hash and snapshot hash, so anyone can check it was produced as stated. It is never a canned or hand-written response, and it is labelled as recorded, not live.
- **Example:** Each recorded run carries 2 SHA-256 hashes: one of the prompt, one of the evidence snapshot.
- **Source:** SPEC §5; docs/EVALUATION_PROTOCOL.md §3.
- **Screens:** DECISION

### FORECAST

- **Short:** A probability or projection, not an observed fact.
- **Long:** Marks a number that states a belief about the future, such as the agent's probability. It becomes scorable only once the real outcome is revealed.
- **Example:** p = 0.7 is a FORECAST until the outcome is revealed.
- **Source:** MATH_MODEL §9 scoring fixtures.
- **Screens:** DECISION

### AS-OF

- **Short:** A value as it was known at the stated knowledge cutoff.
- **Long:** Marks data fixed at the cutoff, such as the market price at that moment or the Research screen's cutoff. Nothing published later can change it.
- **Example:** Market at cutoff: the last quote at or before as_of, at most 24 hours old.
- **Source:** MATH_MODEL §7 (quote selection).
- **Screens:** DECISION, RESEARCH
- **MATH_MODEL:** §7

## REVEAL screen

### Scorecard

- **Short:** Forecast scores of Agent, Market-only and Naive baseline on the same cases.
- **Long:** Compares forecasters on identical event and cutoff pairs (MATH_MODEL §6). Lower Brier and log loss are better. It shows sample size, exclusions and one paired-bootstrap confidence interval, and never a placeholder number: with no computed benchmark it reads INSUFFICIENT DATA.
- **Example:** 3 forecasters × 3 columns (Brier score, log loss, cases n); on main today every cell is NOT AVAILABLE.
- **Source:** apps/web/components/Scorecard.tsx.
- **Screens:** REVEAL
- **MATH_MODEL:** §6

### Brier score

- **Short:** Squared gap between the forecast and what happened; lower is better.
- **Long:** Brier = (p − y)², where p is the forecast probability and y is 1 if the event happened, else 0 (MATH_MODEL §6). 0 is perfect; always saying 0.5 scores 0.25; a confident wrong forecast scores up to 1.
- **Example:** p = 0.7 and the event happened: (0.7 − 1)² = 0.09.
- **Source:** MATH_MODEL §9 scoring fixtures (also core/evaluator.py brier).
- **Screens:** REVEAL
- **MATH_MODEL:** §6

### Log loss

- **Short:** A score that punishes confident wrong forecasts heavily; lower is better.
- **Long:** Log loss = −y ln p − (1 − y) ln(1 − p), with p kept between 0.000001 and 0.999999 so a certain wrong forecast costs 13.8 rather than infinity (MATH_MODEL §6).
- **Example:** p = 0.7 and the event happened: −ln 0.7 = 0.356675.
- **Source:** MATH_MODEL §9 scoring fixtures (also core/evaluator.py log_loss).
- **Screens:** REVEAL
- **MATH_MODEL:** §6

### Cases (n)

- **Short:** How many events were scored; a small n means weak evidence.
- **Long:** n counts events, the unit of resampling; several snapshots of one event are averaged first (MATH_MODEL §6). Below 5 the scorecard reads INSUFFICIENT DATA; from 5 to 29 it adds a 'small sample' caveat.
- **Example:** n = 4 gives INSUFFICIENT DATA; n = 29 gives the small-sample caveat; n = 30 has no caveat.
- **Source:** MATH_MODEL §6 display rules; tested at n = 29 and n = 30 (EVALUATION_PROTOCOL §3).
- **Screens:** REVEAL
- **MATH_MODEL:** §6

### Market-only

- **Short:** A forecaster that simply uses the market-implied probability at the cutoff.
- **Long:** The benchmark the agent is compared with on the same event and cutoff (MATH_MODEL §6). If no quote at most 24 hours old exists, this baseline is NOT AVAILABLE (§7). Its probability is price-derived; affected by fees, spread, liquidity.
- **Example:** ILLUSTRATIVE: a market at 0.56 for an event that happens scores (0.56 − 1)² = 0.1936.
- **Source:** Hand arithmetic on the MATH_MODEL §7 price format example; not a real quote.
- **Screens:** REVEAL
- **MATH_MODEL:** §6, §7

### Naive baseline

- **Short:** A forecaster that always says 50%, the know-nothing benchmark.
- **Long:** p = 0.5 for every event (MATH_MODEL §6). Any useful forecaster should beat it. Its score does not depend on what happens.
- **Example:** Brier 0.25 and log loss 0.693147, whatever the outcome.
- **Source:** MATH_MODEL §9 scoring fixtures.
- **Screens:** REVEAL
- **MATH_MODEL:** §6

### Δ Brier vs market

- **Short:** Agent's average Brier score minus the market's; negative favours the agent.
- **Long:** Mean Brier of the agent − mean Brier of the market over the same events (MATH_MODEL §6). A negative value means the agent was more accurate, but it counts only if the whole 95% confidence interval is below zero.
- **Example:** ILLUSTRATIVE, one case: agent p = 0.7 scores 0.09, a market at 0.56 scores 0.1936, so Δ = −0.1036. One case proves nothing.
- **Source:** Hand arithmetic on MATH_MODEL §9 fixture (0.09) and the §7 price format example; not a FAULTLINE result.
- **Screens:** REVEAL
- **MATH_MODEL:** §6

### Paired bootstrap 95% CI

- **Short:** A range for the score gap, built by resampling the same events 10,000 times.
- **Long:** Events are redrawn with replacement B = 10,000 times, keeping each agent and market score paired on its event. The middle 95% of the resulting Brier gaps is the confidence interval (MATH_MODEL §6). It shows how far the gap could move by chance.
- **Example:** B = 10,000 resamples; 95% percentile interval.
- **Source:** MATH_MODEL §6.
- **Screens:** REVEAL
- **MATH_MODEL:** §6

### Exclusions by reason

- **Short:** Cases left out of scoring, counted by why they were dropped.
- **Long:** Every event is either scored or excluded with a stated reason, so poor results cannot be quietly dropped. Reasons include no saved prediction, more than one prediction, a prediction saved after the outcome was revealed, and case data changed after the run (EVALUATION_PROTOCOL §3).
- **Example:** 4 operator-controllable reasons; any one of them on a real case blocks the OFFICIAL label.
- **Source:** docs/EVALUATION_PROTOCOL.md §3.
- **Screens:** REVEAL

### No improvement measured

- **Short:** The honest result when the agent's advantage is not clear beyond chance.
- **Long:** Shown unless the upper end of the 95% confidence interval for the Brier gap is below zero (MATH_MODEL §6). A lucky case, or a small edge that could be noise, does not count as an improvement over the market.
- **Example:** ILLUSTRATIVE: an interval from −0.05 to +0.01 crosses zero, so it reads No improvement measured.
- **Source:** MATH_MODEL §6 display rule; the interval is hypothetical.
- **Screens:** REVEAL
- **MATH_MODEL:** §6

### INSUFFICIENT DATA

- **Short:** Too few valid cases to compare forecasters at all.
- **Long:** Shown when fewer than 5 events can be scored (MATH_MODEL §6). Per-event scores may still be listed, but no average comparison and no winner is claimed.
- **Example:** n < 5. Main has no real replay cases yet (#20), so the scorecard reads INSUFFICIENT DATA today.
- **Source:** MATH_MODEL §6; docs/EVALUATION_PROTOCOL.md status line; apps/web/components/Scorecard.tsx.
- **Screens:** REVEAL
- **MATH_MODEL:** §6

### SEALED

- **Short:** Withheld from the model until its forecast is saved.
- **Long:** Outcomes live in a separate sealed store that the model's input path cannot read (EVALUATION_PROTOCOL §2, §3). A future-fact canary test plants a marker only in excluded data and checks that it never reaches a prompt.
- **Example:** A canary marker planted only in excluded data must appear in 0 prompts (test_replay_seal.py).
- **Source:** docs/EVALUATION_PROTOCOL.md §3.
- **Screens:** REVEAL

### REVEALED

- **Short:** The real historical outcome, unsealed after the forecast was saved.
- **Long:** The outcome y, 1 if it happened and 0 if not, is read only after the prediction is stored with its hashes, and every reveal is logged (EVALUATION_PROTOCOL §3). Only then is the forecast scored.
- **Example:** If y = 1 and the agent said p = 0.7, its Brier score is 0.09.
- **Source:** MATH_MODEL §9 scoring fixtures.
- **Screens:** REVEAL
- **MATH_MODEL:** §6

## RESEARCH screen

### REAL HISTORICAL

- **Short:** A genuine, dated historical record.
- **Long:** Public documents or market data as they actually existed, with source and date. On the Research screen it marks the public venture-firm writing; it does not mean the content is true or audited.
- **Example:** The 6 research items from 4 venture firms are REAL HISTORICAL.
- **Source:** services/api/data/research_lenses.json; docs/DATA_PROVENANCE.md.
- **Screens:** RESEARCH

### RESEARCH CONTEXT

- **Short:** Public venture-firm writing shown as background, never as a prediction or score.
- **Long:** Labels the Research Lens. These are articles and portfolio pages by four venture firms. They are not records of the firms' investment decisions, and FAULTLINE never scores them or compares itself with them (SPEC §7).
- **Example:** 6 items: 2 Link Ventures, 2 a16z, 1 Sequoia, 1 Bessemer.
- **Source:** services/api/data/research_lenses.json; docs/DATA_PROVENANCE.md.
- **Screens:** RESEARCH

### Thesis Court

- **Short:** Four firms' dated public theses on one decision, side by side.
- **Long:** For a chosen cutoff, the Research screen shows which published theses from Link Ventures, a16z, Sequoia and Bessemer bear on the decision, and what each supports or challenges. The API decides which were public; the browser does not filter or score.
- **Example:** At as_of 2026-07-01T00:00:00Z: 4 items shown, 2 not yet public.
- **Source:** Engine run computed for this glossary: core/research.py eligible_lenses on research_lenses.json.
- **Screens:** RESEARCH

### Point-in-time mode

- **Short:** Shows only sources provably public at the cutoff you enter.
- **Long:** The default Research view. The API returns only content fields for items public by as_of and reports how many it held back; curation notes dated after the cutoff are hidden.
- **Example:** At as_of 2023-06-01T00:00:00Z: 0 items shown, 6 not yet public.
- **Source:** Engine run computed for this glossary: core/research.py eligible_lenses on research_lenses.json.
- **Screens:** RESEARCH

### Live Explore

- **Short:** Today's view: every curated item, not filtered to any cutoff.
- **Long:** Shows each item with its full sourcing: archive capture, access date and limitations. Because it ignores the cutoff, it must never be used for a Blind Replay.
- **Example:** 6 curated items, with as_of null.
- **Source:** services/api/data/research_lenses.json; apps/web/components/ThesisCourt.tsx.
- **Screens:** RESEARCH

### Blind Replay

- **Short:** Rewind to a real past decision, hide everything later, forecast, then reveal and score.
- **Long:** FAULTLINE's signature test (SPEC §0, §5). The model sees only point-in-time evidence; outcomes stay sealed until its forecast is saved, and then it is scored against the market-only and naive baselines.
- **Example:** Scored against 2 baselines: market-only and naive (p = 0.5).
- **Source:** MATH_MODEL §6.
- **Screens:** RESEARCH
- **MATH_MODEL:** §6

### Published / Proven public by

- **Short:** The date on the page, and the earliest date its text is provably public.
- **Long:** Proven public by (available_at) is conservative: the later of the page's date and any machine-readable publish timestamp, or for undated pages the earliest archive capture containing every quote. A day-only date counts from noon UTC the next day, once it has ended everywhere (DATA_PROVENANCE).
- **Example:** a16z 'Investing in Stitch': published 2026-05-13, proven public 2026-05-14, usable from 2026-05-15T12:00Z.
- **Source:** docs/DATA_PROVENANCE.md.
- **Screens:** RESEARCH

### Items not yet public at this cutoff

- **Short:** How many curated sources are hidden because they appeared after the cutoff.
- **Long:** Reported by the API in point-in-time mode, so the presenter can see that sources were held back, not lost. A count of 0 means every curated item was public by then.
- **Example:** At as_of 2025-09-01T00:00:00Z: 4 not yet public, 2 shown.
- **Source:** Engine run computed for this glossary: core/research.py eligible_lenses on research_lenses.json.
- **Screens:** RESEARCH

### Archive capture

- **Short:** A dated Wayback Machine copy proving what a page said at that time.
- **Long:** Every quote was checked word for word against an Internet Archive capture as well as the live page, because living pages change (DATA_PROVENANCE). Shown in Live Explore.
- **Example:** Bessemer 'The State of AI 2025': capture of 2025-08-13T21:24:01Z.
- **Source:** docs/DATA_PROVENANCE.md.
- **Screens:** RESEARCH

### Documentary fact

- **Short:** A statement of what the source itself says or records.
- **Long:** A fact as documented on the page, such as deal terms or a stated investment focus. Documented means the firm says it, not that FAULTLINE verified it; self-reported metrics are not audited.
- **Example:** Sequoia: leading Etched's 300 million dollar Series C at a 10 billion dollar pre-money valuation.
- **Source:** services/api/data/research_lenses.json (sequoia-partnering-with-etched).
- **Screens:** RESEARCH

### Analyst interpretation

- **Short:** An opinion or framing; not testable as stated.
- **Long:** A view, belief, risk framing or expectation without a number and a time window. Useful context, but it cannot be scored.
- **Example:** Sequoia: 'The intelligence race is fundamentally compute constrained.'
- **Source:** services/api/data/research_lenses.json (sequoia-partnering-with-etched).
- **Screens:** RESEARCH

### Quantitative forecast

- **Short:** A forward-looking claim with a number and a time window.
- **Long:** The only quote of this kind is Bessemer's. It has no defined metric, baseline or resolution source, so it cannot be scored as stated, is marked Not scorable, and FAULTLINE does not score it.
- **Example:** Bessemer: 'enterprise deployment will 10x' in 2025 to 2026.
- **Source:** services/api/data/research_lenses.json (bessemer-state-of-ai-2025); docs/DATA_PROVENANCE.md.
- **Screens:** RESEARCH

### Model stance

- **Short:** Where the model agreed or disagreed with a firm's thesis.
- **Long:** A field reserved for the model's position on each thesis. It reads NOT AVAILABLE until a replay run supplies it.
- **Example:** Shown on each of the 4 firm panels; NOT AVAILABLE on main.
- **Source:** apps/web/components/ThesisCourt.tsx.
- **Screens:** RESEARCH

## Named in issue #87, not on a screen yet

### DSCR (debt service coverage ratio)

- **Short:** Cash available for debt payments divided by the debt payments due.
- **Long:** Standard definition: net operating cash flow available for debt service ÷ debt service due in the same period (interest plus principal). Above 1 means the payments are covered; lenders often set a minimum as a loan covenant. It is not yet modelled in FAULTLINE or in MATH_MODEL.
- **Example:** Example pending #85. ILLUSTRATIVE arithmetic only: 15,000 available ÷ 10,000 due = 1.5.
- **Source:** Standard finance definition; no FAULTLINE figure.
- **Screens:** none yet
- **Status:** *pending #85 (DSCR covenant, not started); not in MATH_MODEL yet*
