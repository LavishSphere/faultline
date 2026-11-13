# FAULTLINE Mathematical Model

**Status:** DRAFT v0, written by the systems lead. **Pending sign-off by Yaseen (finance owner).**
**Rule:** `services/api/core/financials.py`, `optimizer.py`, `forecasting.py`, `evaluator.py`, and
`markets/normalize.py` implement *exactly* what is written here. A PR that changes a formula must update
this document in the same PR, and a finance-owner or lead review is required.

All business data is **SYNTHETIC** (a fictional company). Parameter values below are placeholders marked
`[assumed]` until Yaseen sets them.

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
S^{dem}_t = m_t \sum_{\ell \in L} S^{base}_{\ell,t} \;+\; (1-x_e)\,X_t
$$

$$
S_t = S^{dem}_t\,\bigl(1 - \lambda_t\,(1 - x_b)\bigr)
$$

where $x_b \in \{0,1\}$ = "use backup supplier" and $x_e \in \{0,1\}$ = "delay expansion" (§4).
*Simplification [assumed]:* inventory buffer does not cover outage SKUs; outage translates directly to lost sales unless backup is used.

## 3. Cash-flow recurrence (the core engine)

**Receipts** (card/receivable timing):
$$R_t = a\,S_t + (1-a)\,S_{t-1}$$

**Purchases** (replenish what was sold, minus a chosen purchase cut $v_t \ge 0$, plus backup premium $\pi$ on the outage share):
$$P_t = (1-g)\,S_t - v_t + \pi\,(1-g)\,S^{dem}_t\,\lambda_t\,x_b$$

**Inventory:**
$$I_t = I_{t-1} + P_t - (1-g)S_t - \pi(1-g)S^{dem}_t\lambda_t x_b = I_{t-1} - v_t$$
(the premium is a cost, not extra stock).

**Interest:** term loan $\;J_t = D_t\,r_t/52$; revolver $\;J^R_t = B_{t-1}\,(r_t + s_R)/52$.

**Revolver:** $B_t = B_{t-1} + y_t - q_t$ with draw $y_t \ge 0$, repayment $q_t \ge 0$.

**Cash:**
$$
\boxed{C_t = C_{t-1} + R_t - P_{t-L_p} - (1-z_t)\,W_t - O_t - J_t - A_t - J^R_t - (1-x_c)K_t - (1-x_e)E_t - F_b\,x_b\,\mathbb{1}[t=1] + y_t - q_t}
$$

where $x_c$ = "defer non-critical capex", $z_t \in [0,\bar z]$ = payroll reduction share (§4), $F_b$ = one-time backup-supplier switching fee.
Pre-horizon values $S_0$, $P_{1-L_p},\dots,P_0$ are given as initial conditions.

**Runway:** first $t$ with $C_t < 0$ on the simulated path; reported as `> T weeks` if none. (No extrapolated burn-rate runway unless labeled.)

Every term is **linear** in the decisions $(x_b, x_c, x_e, v_t, y_t, q_t, z_t)$, given the scenario parameters. So the optimizer below is exact with respect to this model; there is no approximation.

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

- Kalshi prices in cents: $p = c/100$. Polymarket prices are decimal: $p = x$. Normalize **once**, at ingestion.
- Quote selection: last observation with timestamp $\le$ `as_of` and $\ge$ `as_of` − 24h. Otherwise the market baseline is `NOT AVAILABLE`.
- Preference order: bid/ask midpoint, then candle close, then last trade; record which (`quote_kind`).
- Binary markets only (MVP). Reject values outside $[0,1]$ after normalization.
- Label: "market-implied probability (price-derived; affected by fees, spread, liquidity)", never "true probability".

## 8. From forecast to decision (ACT / WAIT / HEDGE)

Each policy $a$ is a pre-declared set of actions (§4) with all fees and carrying costs. For each outcome
$y \in \{0,1\}$ the simulator gives a payoff $V(a,y)$, defined ex ante as $\min_t C_t$ (or ending cash: pick one and freeze it).

$$
\mathbb{E}[V \mid a] = p\,V(a,1) + (1-p)\,V(a,0)
$$

Recommend the $a$ maximizing $\mathbb{E}[V]$ **among policies feasible in both states**. After reveal, realized
regret $= \max_{a'} V(a', y) - V(a, y)$. These are **SIMULATED** synthetic-business payoffs, never trading P&L.

## 9. Golden test cases (hand-checked; must be in `tests/test_financials.py`)

Common: $C_0 = 100{,}000$; $S^{base} = 50{,}000$/wk (all stores); $S_0 = 50{,}000$; $g = 0.35$; $a = 0.8$; $L_p = 1$,
$P_0 = 32{,}500$; $W = 12{,}000$; $O = 6{,}000$; $D = 600{,}000$; $A = 0$; no revolver, capex, expansion, outage.

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

## 10. Parameters to be set by Yaseen `[assumed]`

| Parameter | Placeholder | Notes |
|---|---|---|
| Store weekly sales $S^{base}_\ell$ | 18k / 17k / 15k | regional food/retail, 3 locations |
| Gross margin $g$ | 0.35 | |
| Same-week collection $a$ | 0.80 | card settlement / B2B AR |
| Supplier lag $L_p$ | 2 weeks | net-14 |
| Payroll $W$ | 12,000/wk | |
| Fixed opex $O$ | 6,000/wk | |
| Term loan $D_0$, base rate | 600k, 8.0% | floating; rate shock applies |
| Revolver limit $\bar B$, spread $s_R$ | 150k, +2.0% | approved facility |
| $C_{min}$, $I_{min}$ | 25k, 40k | |
| Outage share $\phi$, backup premium $\pi$, fee $F_b$ | 0.4, 0.12, 2k | |
| Disruption costs $c_b, c_c, c_e, c_v, c_y, c_z$ | TBD | relative harm weights |

**Sign-off:** ☐ Yaseen has reviewed §1–§4 and §8 assumptions · ☐ Lead has reviewed §6–§7.
