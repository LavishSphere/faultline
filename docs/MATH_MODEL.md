# FAULTLINE Mathematical Model

**Status:** DRAFT v0, written by the systems lead. **Pending sign-off by Yaseen (finance owner).**
**Rule:** `services/api/core/financials.py`, `optimizer.py`, `forecasting.py`, `evaluator.py`, and
`markets/normalize.py` implement *exactly* what is written here. A PR that changes a formula must update
this document in the same PR, and a finance-owner or lead review is required.

All business data is **SYNTHETIC** (a fictional company). Parameter values in §10 are `[assumed]`, set in
issue #6 with a one-line justification each. They are modelling choices, not figures from a real company.

---

## 0. Notation

| Symbol | Meaning | Unit |
|---|---|---|
| $t = 1..T$ | week index, horizon $T = 26$ | week |
| $\ell \in L$ | store location, $\lvert L\rvert = 3$ | — |
| $C_t$ | cash balance at end of week $t$, $C_0$ given | \$ |
| $S_t$ | net sales recognized in week $t$ | \$ |
| $g$ | gross margin (so COGS $= (1-g)S_t$) | fraction |
| $a$ | share of week-$t$ sales collected in week $t$ (rest collected in $t+1$) | fraction |
| $L_p$ | supplier payment lag | weeks |
| $W_t$ | payroll due in week $t$ | \$ |
| $O_t$ | fixed operating expense (rent, utilities, etc.) | \$ |
| $D_t$ | term-loan principal outstanding at start of week $t$ | \$ |
| $A_t$ | scheduled term-loan amortization paid in week $t$ | \$ |
| $r_t$ | annual borrowing rate in week $t$ (base + spread); the **rate shock** acts here | 1/yr |
| $B_t$ | revolver (credit facility) balance at end of week $t$, $B_0$ given | \$ |
| $\bar B$ | approved revolver limit | \$ |
| $s_R$ | revolver spread over $r_t$ | 1/yr |
| $K_t$ | scheduled non-critical capex | \$ |
| $E_t$, $X_t$ | expansion outflow, and expansion sales once opened | \$ |
| $I_t$ | inventory at cost, end of week $t$ | \$ |

## 1. Shocks (exogenous scenario inputs)

A scenario is a tuple of deterministic paths: no probabilities are produced by the simulator.

- **Demand shock:** $m_t \in [0, \infty)$ multiplies baseline demand. E.g. a $\delta$ contraction over weeks
  $[t_1, t_2]$ with linear recovery over $\rho$ weeks:
  $m_t = 1 - \delta$ for $t_1 \le t \le t_2$; $m_t = 1 - \delta\,(1 - (t-t_2)/\rho)$ for $t_2 < t \le t_2+\rho$; else 1.
- **Rate shock:** $r_t = r^{base}_t + \Delta r \cdot \mathbb{1}[t \ge t_r]$.
- **Supplier outage:** primary supplier availability $\kappa_t \in [0,1]$. A share $\phi$ of sales depends on the
  primary supplier. Without a backup supplier, the lost-sales fraction is $\lambda_t = \phi\,(1-\kappa_t)$.

## 2. Baseline demand and sales

$$
S^{core}_t = m_t \sum_{\ell \in L} S^{base}_{\ell,t}
\qquad\qquad
S^{dem}_t = S^{core}_t \;+\; (1-x_e)\,X_t
$$

$$
S_t = S^{core}_t\,\bigl(1 - \lambda_t\,(1 - x_b)\bigr) \;+\; (1-x_e)\,X_t
$$

where $S^{core}_t$ is base-store demand, $S^{dem}_t$ is total demand, $x_b \in \{0,1\}$ = "use backup supplier" and
$x_e \in \{0,1\}$ = "delay expansion" (§4). Lost sales are $S^{dem}_t - S_t = S^{core}_t\,\lambda_t\,(1-x_b)$.

*Decision (issue #16): the outage hits base-store sales only.* The new store's sales $X_t$ do not depend on the primary
supplier. This keeps the model linear: $m_t$ and $\lambda_t$ are scenario inputs, so the outage term contains only the
decision $x_b$, and $X_t$ is multiplied only by $x_e$. No product of two decisions appears (the earlier form contained
$(1-x_e)\,X_t\,x_b$).
*Simplification [assumed]:* inventory buffer does not cover outage SKUs; outage translates directly to lost sales unless backup is used.

## 3. Cash-flow recurrence (the core engine)

**Receipts** (card/receivable timing):
$$R_t = a\,S_t + (1-a)\,S_{t-1}$$

**Purchases** (replenish what was sold, minus a chosen purchase cut $v_t \ge 0$, plus backup premium $\pi$ on the outage share):
$$P_t = (1-g)\,S_t - v_t + \pi\,(1-g)\,S^{core}_t\,\lambda_t\,x_b$$
(the premium applies to the same base-store outage share as §2).

**Inventory:**
$$I_t = I_{t-1} + P_t - (1-g)S_t - \pi(1-g)S^{core}_t\lambda_t x_b = I_{t-1} - v_t$$
(the premium is a cost, not extra stock).

*MVP simplification [assumed] (issue #16): purchase cuts do not cause stock-outs.* Inventory has no effect on sales, so
$S_t$ does not change with $v_t$. Two parameters stand in for stock-out risk: the inventory floor $I_{min}$, which caps
total cuts at $\sum_t v_t \le I_0 - I_{min}$, and the disruption cost $c_v$ (§10).

**Interest:** term loan $\;J_t = D_t\,r_t/52$; revolver $\;J^R_t = B_{t-1}\,(r_t + s_R)/52$.

**Revolver:** $B_t = B_{t-1} + y_t - q_t$ with draw $y_t \ge 0$, repayment $q_t \ge 0$.

**Cash:**
$$
\boxed{C_t = C_{t-1} + R_t - P_{t-L_p} - (1-z_t)\,W_t - O_t - J_t - A_t - J^R_t - (1-x_c)K_t - (1-x_e)E_t - F_b\,x_b\,\mathbb{1}[t=1] + y_t - q_t}
$$

where $x_c$ = "defer non-critical capex", $z_t \in [0,\bar z]$ = payroll reduction share (§4), $F_b$ = one-time backup-supplier switching fee.
Pre-horizon values $S_0$, $P_{1-L_p},\dots,P_0$ are given as initial conditions, as are $C_0$, $I_0$, $B_0$, and
$D_1$ (term-loan principal at the start of week 1; the "$D_0$" in §10 means this value).
Principal evolves as $D_{t+1} = D_t - A_t$. In the demand shock, $\rho = 0$ means the recovery branch is empty
($m_t = 1$ immediately after $t_2$), which is how §9 Case B "week 2 only" is encoded ($t_1 = t_2 = 2$, $\rho = 0$).
Financing that cannot happen is rejected by the simulator, not simulated: a repayment above the balance ($B_t < 0$) or
amortization above the remaining principal ($D_{t+1} < 0$), with a \$$10^{-6}$ tolerance for solver round-off.
Physically impossible plans are rejected the same way: the simulator enforces $P_t \ge 0$ and $I_t \ge 0$ in every week
(same tolerance; purchases are checked before inventory), while the floor $I_t \ge I_{min}$ stays an optimizer constraint (§4.3).
Inputs must be finite (no NaN or ±∞).

**Runway:** first $t$ with $C_t < 0$ on the simulated path; reported as `> T weeks` if none. (No extrapolated burn-rate runway unless labeled.)

Every term is **linear** in the decisions $(x_b, x_c, x_e, v_t, y_t, q_t, z_t)$, given the scenario parameters. With the
§2 base-store outage, no term multiplies two decisions together, so §3 stays linear in all decisions. So the optimizer below is exact with respect to this model; there is no approximation.

## 4. Recovery optimizer (MILP, `scipy.optimize.milp`)

**Decisions:** $x_b, x_c, x_e \in \{0,1\}$; $v_t \in [0, \bar v]$; $y_t, q_t \ge 0$; $z_t \in [0,\bar z]$; auxiliary $\mu$ (minimum cash).

**Hard constraints** (for all $t$):
1. Liquidity floor: $C_t \ge C_{min}$
2. Facility limit: $0 \le B_t \le \bar B$
3. Inventory preservation: $I_t \ge I_{min}$
4. Debt service is paid in full (it is a fixed outflow; there is no "skip payment" variable)
5. **Protect payroll mode:** $z_t = 0$ for all $t$ (variable upper bound set to 0, enforced in the solver, not in a prompt).
   Outside that mode, $z_t$ is an explicit, labeled action, never implicit.
6. $\mu \le C_t$ for all $t$
7. **Terminal revolver:** $B_T \le B_0$ (issue #16). The facility must be back to its opening balance by the end of the
   horizon, so no plan can borrow and never repay, which would flatter the cash path.

**Objective** (minimize disruption, tie-break toward more cash):
$$
\min\; c_b x_b + c_c x_c + c_e x_e + c_v \sum_t v_t + c_y \sum_t y_t + c_z \sum_t z_t W_t \;-\; \varepsilon\,\mu
$$
with $\varepsilon$ small (e.g. $10^{-4}$) so cash only breaks ties. The $c_\cdot$ are **disruption costs set by the
finance owner** (non-cash harm: operational risk, lost goodwill, morale), on top of the cash effects already in §3.

**Outputs:** status ∈ {`OPTIMAL`, `NO FEASIBLE PLAN`}, the chosen actions, $C_t$ path, $\min_t C_t$, binding
constraints (slack ≈ 0), and the objective value. If infeasible, report it: no LLM may override it. Useful
diagnostic: re-solve with $C_{min}$ relaxed to find the smallest floor that *is* feasible, and show it.

## 5. Cascade graph semantics

Nodes are model quantities (Demand, Sales, Receipts, Supplier, Inventory, Purchases, Payables, Rate, Interest,
Payroll, Revolver, Cash). Edges are the dependencies in §2–§3. A node's displayed change is
$\Delta_n = \text{value}_n(\text{scenario}) - \text{value}_n(\text{baseline})$ from the simulator, and edge emphasis is
proportional to $|\Delta|$ propagated along it. **The UI never invents magnitudes.**

## 6. Forecast scoring (`evaluator.py`)

For outcome $y \in \{0,1\}$ and forecast $p \in [0,1]$:

- Brier: $\;(p-y)^2$
- Log loss: $\;-y\ln\tilde p - (1-y)\ln(1-\tilde p)$, with $\tilde p = \min(\max(p, \epsilon), 1-\epsilon)$, $\epsilon = 10^{-6}$
- Accuracy at threshold 0.5 (secondary), where $p = 0.5$ counts as predicting NO, pre-specified.

**Forecasters compared on identical (event_id, as_of) pairs:** naive $p=0.5$; market-only; agent-only; agent+market; optional hosted comparator.

**Aggregation:** one snapshot per event per horizon; if multiple horizons, average within event first (events are the unit of resampling).
**Uncertainty:** paired bootstrap over events, $B = 10{,}000$, 95% percentile CI of $\overline{\text{Brier}}_{agent} - \overline{\text{Brier}}_{market}$.

**Display rules:**
- $n < 5$: `INSUFFICIENT DATA` (still list per-event scores)
- $5 \le n < 30$: show the numbers with a `small sample` caveat
- Say "agent better than market" **only if** the CI upper bound $< 0$. Otherwise `No improvement measured`.

## 7. Market-quote normalization (`markets/normalize.py`)

- Kalshi prices are fixed-point dollar strings per \$1-notional contract (`FixedPointDollars`, e.g. `"0.5600"`): $p = x$.
  Legacy integer-cent payloads are still accepted: $p = c/100$ (a cents value in $(0,1)$ is rejected as already normalized).
  Polymarket prices are decimal: $p = x$. Normalize **once**, at ingestion. *(Updated 2026-11-13 after verifying the current Kalshi docs and real responses; see PR #12.)*
- Bid/ask midpoint $(b+a)/2$ is used only for a real two-sided book ($b > 0$, $a < 1$, $b \le a$). A Polymarket CLOB
  `/prices-history` point is recorded as `quote_kind = price_history_point`.
- Quote selection: last observation with timestamp $\le$ `as_of` and $\ge$ `as_of` − 24h. Otherwise the market baseline is `NOT AVAILABLE`.
- Preference order: bid/ask midpoint, then candle close, then last trade; record which (`quote_kind`).
- Binary markets only (MVP). Reject values outside $[0,1]$ after normalization.
- Label: "market-implied probability (price-derived; affected by fees, spread, liquidity)", never "true probability".

## 8. From forecast to decision (ACT / WAIT / HEDGE)

Each policy $a$ is a pre-declared set of actions (§4) with all fees and carrying costs. For each outcome
$y \in \{0,1\}$ the simulator gives a payoff $V(a,y) = \min_t C_t$, the lowest cash balance over the horizon.
*Frozen in issue #6:* the lowest balance measures how close the business comes to running out of cash, the same quantity
the liquidity floor $C_{min}$ and runway track. Ending cash would favour plans that dip dangerously low mid-horizon and recover.

$$
\mathbb{E}[V \mid a] = p\,V(a,1) + (1-p)\,V(a,0)
$$

Recommend the $a$ maximizing $\mathbb{E}[V]$ **among policies feasible in both states**. After reveal, realized
regret $= \max_{a'} V(a', y) - V(a, y)$. These are **SIMULATED** synthetic-business payoffs, never trading P&L.

## 9. Golden test cases (hand-checked; must be in `tests/test_financials.py`)

Common: $C_0 = 100{,}000$; $S^{base} = 50{,}000$/wk (all stores); $S_0 = 50{,}000$; $g = 0.35$; $a = 0.8$; $L_p = 1$,
$P_0 = 32{,}500$; $W = 12{,}000$; $O = 6{,}000$; $D = 600{,}000$; $A = 0$; no revolver, capex, expansion, outage.
These cases use their own inputs (note $L_p = 1$ here, versus 2 weeks in §10).
*Hand-checked 2026-11-12 (issue #6): every value in cases A–C and every scoring fixture below matches.*
*Unchanged by issue #16:* none of cases A–C has an outage, an expansion, a revolver or a purchase cut. The §2 base-store
outage, the §4 terminal revolver condition and the §10 expansion-cost note therefore leave every value below as it was.

**Case A, no shock, $r = 8\%$:** $R_t = 50{,}000$; outflow $= 32{,}500 + 12{,}000 + 6{,}000 + 923.077 = 51{,}423.077$
→ $C_1 = 98{,}576.923$, $C_2 = 97{,}153.846$, $C_3 = 95{,}730.769$.

**Case B, 20% demand drop in week 2 only, $r = 8\%$:**
week 1: $R = 50{,}000$, $C_1 = 98{,}576.923$ ·
week 2: $S_2 = 40{,}000$, $R = 42{,}000$, pay $P_1 = 32{,}500$, $C_2 = 89{,}153.846$ ·
week 3: $R = 0.8(50{,}000) + 0.2(40{,}000) = 48{,}000$, pay $P_2 = 26{,}000$, outflow $44{,}923.077$, $C_3 = 92{,}230.769$.

**Case C, rate shock 8% → 10% from week 2:** interest $923.077$ then $1{,}153.846$ →
$C_1 = 98{,}576.923$, $C_2 = 96{,}923.077$, $C_3 = 95{,}269.231$.

**Scoring fixtures:** $p=0.7, y=1$ → Brier $0.09$, log loss $0.356675$; $p=0.7, y=0$ → Brier $0.49$, log loss $1.203973$;
$p=0.5$ → Brier $0.25$, log loss $0.693147$; $p=0, y=1$ → log loss $= -\ln(10^{-6}) = 13.815511$.

## 10. Parameters `[assumed]` (set in issue #6)

The company is a SYNTHETIC 3-store regional food retailer with a fresh/deli-heavy format. Each justification is a
modelling rationale, not a citation.

| Parameter | Value | Justification |
|---|---|---|
| Horizon $T$ | 26 weeks | Half a year: long enough for a shock and a recovery, short enough for weekly cash planning. |
| Store weekly sales $S^{base}_\ell$ | 18k / 17k / 15k (50k total) | Small regional stores of unequal size, so the cascade shows store-level differences. The total matches §9. |
| Gross margin $g$ | 0.35 | Upper end for food retail, consistent with a fresh/deli mix rather than a discount grocer. |
| Same-week collection $a$ | 0.80 | Card sales settle in 1–2 days, so most cash lands the same week. The 20% lag covers weekend sales settling the next week and a few B2B accounts. |
| Supplier lag $L_p$ | 2 weeks | Net-14 terms with the main distributor. |
| Payroll $W$ | 12,000/wk | 24% of sales. That is high for a grocer but fits a service-heavy fresh/deli format. |
| Fixed opex $O$ | 6,000/wk | Rent, utilities and insurance for 3 small sites, about 2,000 per store per week. |
| Term loan $D_0$, rate $r$ | 600k at 8.0% all-in, floating, interest-only ($A_t = 0$) | All-in means base plus spread. The loan floats, so the rate shock passes straight through. Interest-only keeps §9 simple. |
| Revolver limit $\bar B$, spread $s_R$, opening balance $B_0$ | 150k, +2.0%, 0 | About 3 weeks of sales of headroom. Revolvers price above term debt. The facility is undrawn at the start. |
| Starting cash $C_0$ | 100,000 | About 2 weeks of sales. Matches §9. |
| Liquidity floor $C_{min}$ | 25,000 | About 2 weeks of payroll: the cash a CFO would not plan to go below. |
| Starting inventory $I_0$ | 65,000 | 2 weeks of cost of goods ($2 \times 0.65 \times 50{,}000$), typical for a fresh-heavy grocer. |
| Inventory floor $I_{min}$ | 40,000 | About 1.2 weeks of cost of goods: below this, shelves look empty. Together with $I_0$ this caps total purchase cuts at $\sum_t v_t \le 25{,}000$. |
| Pre-horizon values $S_0$; $P_{-1}$, $P_0$ | 50,000; 32,500 each | Steady state before week 1: purchases $= (1-g) \times 50{,}000$. |
| Purchase-cut cap $\bar v$ | 10,000/wk | About 30% of a normal week's purchases. Deeper one-week cuts are not realistic for perishables. |
| Payroll-cut cap $\bar z$ | 0.10 | Up to 10% through reduced hours and no overtime, without layoffs. Forced to 0 in protect-payroll mode (§4). |
| Outage share $\phi$ | 0.40 | 40% of sales rely on product lines from the primary distributor. |
| Backup premium $\pi$, switching fee $F_b$ | 0.12, 2,000 | Spot buying from a secondary supplier costs about 12% more. The fee covers set-up, a credit application and delivery changes. |
| Capex $K_t$, expansion $E_t$, expansion sales $X_t$ | set per demo case (placeholder) | Timing and size belong to each scenario, so they are set in the case definition, not here. **Expansion costs (issue #16):** each case's $E_t$ includes the new store's payroll and opex from the week it opens, not only fit-out spending, because §3 has no other line for the new store's running costs. |
| Tie-break $\varepsilon$ | $10^{-4}$ per \$ of minimum cash | 100× smaller than the cheapest lever ($c_y$ below), so the optimizer never draws or cuts just to raise minimum cash. |

**Baseline economics (kept on purpose).** Weekly gross profit is $0.35 \times 50{,}000 = 17{,}500$. Weekly fixed costs are
$12{,}000 + 6{,}000 + 923.08 = 18{,}923.08$, so the business loses $1{,}423.08$ a week before any shock: about 74k a year,
or −2.85% of sales. It is a thin-margin retailer already under pressure, so shocks bite quickly. With no shock, cash falls
from 100,000 to $100{,}000 - 26 \times 1{,}423.077 = 63{,}000$ by week 26 and stays above $C_{min}$. The figure is exact,
because 26 weeks of interest is $600{,}000 \times 8\% / 2 = 24{,}000$ and 26 weeks of operating shortfall is $26 \times 500 = 13{,}000$.

### Disruption costs (non-cash harm, on top of the cash effects in §3)

Units differ by action type. The three yes/no actions carry a dollar-equivalent harm per decision. The three amount actions
carry harm per dollar of action. To compare them, the "10k yardstick" column shows the harm of using each lever to raise or
save about 10,000. For a yes/no action, that is simply its fixed weight.

| Weight | Action | Value | Harm at 10k | Why it ranks here |
|---|---|---|---|---|
| $c_y$ | Revolver draw | 0.01 per \$ drawn | 100 | Covering a cash gap is what the facility is for, and its interest is already in the cash path. This is a small charge for using up headroom. |
| $c_v$ | Purchase cut | 0.05 per \$ cut | 500 | Thinner shelves and stock-out risk that the model does not capture. |
| $c_c$ | Defer non-critical capex | 1,000 per decision | 1,000 | Non-critical by definition, but maintenance risk builds up while it is deferred. |
| $c_b$ | Use backup supplier | 2,500 per decision | 2,500 | Quality, consistency and supplier-relationship risk beyond the fee and premium. |
| $c_e$ | Delay expansion | 5,000 per decision | 5,000 | Strategic cost: lost momentum and lease or landlord risk. |
| $c_z$ | Payroll cut | 5.00 per \$ of payroll cut | 50,000 | Worst lever: morale, turnover and service quality, and it hurts people. A 1,000 payroll cut counts as much harm as delaying the expansion, so cutting payroll beats delaying the expansion only for shortfalls under 1,000. |

Ranking, least to most harmful: revolver draw < purchase cut < defer capex < backup supplier < delay expansion < payroll cut.

**Sign-off:** ☑ Yaseen has reviewed §1–§4 and §8 assumptions (2026-11-12, issue #6) · ☐ Lead has reviewed §6–§7.
