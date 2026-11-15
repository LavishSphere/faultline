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
| $\sigma$ | service level: the stock the business aims to hold, as a share of $I_0$ at planned demand (issue #103) | fraction |
| $I^{svc}_t$ | service-level inventory $\sigma\,I_0\,m_t$ | \$ |
| $u_t$ | inventory shortfall below the service level, $\max(0,\,I^{svc}_t - I_t)$ | \$ |
| $\theta$ | stock-out lost sales per \$ of shortfall per week | 1/week |
| $\ell_t$ | stock-out lost sales $\theta\,u_t$ | \$ |

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
S_t = S^{core}_t\,\bigl(1 - \lambda_t\,(1 - x_b)\bigr) \;+\; (1-x_e)\,X_t \;-\; \ell_t
$$

where $S^{core}_t$ is base-store demand, $S^{dem}_t$ is total demand, $x_b \in \{0,1\}$ = "use backup supplier" and
$x_e \in \{0,1\}$ = "delay expansion" (§4), and $\ell_t = \theta\,u_t$ are the stock-out lost sales of §3 (issue #103).
Lost sales are $S^{dem}_t - S_t = S^{core}_t\,\lambda_t\,(1-x_b) + \ell_t$.

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

**Stock-out cost** (issue #103; replaces the issue #16 simplification "purchase cuts do not cause stock-outs").
*Signed off by the finance owner, 2026-11-14 (#141).* The business aims to hold the share $\sigma$ of its opening stock
$I_0$ at planned demand, scaled with the demand shock $m_t$ (§1). Inventory below that level loses sales:
$$
I^{svc}_t = \sigma\,I_0\,m_t, \qquad u_t = \max\bigl(0,\; I^{svc}_t - I_t\bigr), \qquad \ell_t = \theta\,u_t ,
$$
and $\ell_t$ is subtracted from $S_t$ (§2), so it flows through receipts and purchases like every other lost sale: a lost
sales dollar costs $a$ of receipts in week $t$ and $1-a$ in $t+1$, and the purchase that would have replaced it,
$(1-g)$, is not made, so once settled it costs the gross margin $g$. $I_t = I_{t-1} - v_t$ does not depend on $S_t$, so
there is no circularity. $I^{svc}_t$ follows the base-store demand multiplier $m_t$ (scenario data, not a decision):
when demand falls, the stock the business needs falls with it, which is what lets a purchase cut pay off in one state
and cost in the other (§8). For the §10 grocer $\sigma = 1$, so $I^{svc}_t = 65{,}000\,m_t$, which is 2 weeks of cost of
goods of base-store demand, $2\,(1-g)\,S^{core}_t$. Two choices keep the cost from appearing where nothing was cut:
the target is anchored to $I_0$ (so a sensitivity run that changes $g$ or baseline sales without restating $I_0$ does not
create a stock-out), and it ignores the outage $\lambda_t$ (stock cannot be bought for lines the supplier cannot deliver)
and the new store's $X_t$ (its stock is not modelled, as for the outage, §2). It does not follow seasonal changes in
$S^{base}_{\ell,t}$; no fixture uses them.
*Why it matters:* without it a purchase cut raised cash in every state with no downside except the non-cash $c_v$, so
the optimizer treated cuts as free cash and ACT won the FOMC and CPI frames at every $p$ (review of #71).
*Golden cases and baselines:* with no purchase cut $I_t = I_0$, and $I^{svc}_t = \sigma I_0 m_t \le I_0$ whenever
$\sigma \le 1$ and $m_t \le 1$, so $u_t = 0$ and nothing changes unless purchases are cut (or demand rises above plan). A cut is permanent in this model ($v_t \ge 0$; there is no restocking action), so stock cut
below $I^{svc}_t$ stays short until the horizon ends. The inventory floor $I_{min}$ remains a hard constraint (§4.3) that
caps total cuts at $\sum_t v_t \le I_0 - I_{min}$; the disruption costs $c_v$ and $c_u$ (§10) add the non-cash harm.

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
Physically impossible plans are rejected the same way: the simulator enforces $S_t \ge 0$, $P_t \ge 0$ and $I_t \ge 0$ in
every week (same tolerance; sales, then purchases, then inventory), while the floor $I_t \ge I_{min}$ stays an optimizer
constraint (§4.3). ($S_t \ge 0$ can only fail if $\ell_t$ exceeds the week's other sales. Since $I_t \ge 0$,
$\ell_t \le \theta\,I^{svc}_t$; for the §10 grocer that is $0.2 \times 65{,}000\,m_t = 13{,}000\,m_t$, 26% of base-store demand.)
Inputs must be finite (no NaN or ±∞).

**Runway:** first $t$ with $C_t < 0$ on the simulated path; reported as `> T weeks` if none. (No extrapolated burn-rate runway unless labeled.)

Every term is **linear** in the decisions $(x_b, x_c, x_e, v_t, y_t, q_t, z_t)$, given the scenario parameters, except
the $\max$ in $u_t$. With the §2 base-store outage, no term multiplies two decisions together. The $\max$ is convex and
only ever costs the business, so the optimizer represents it exactly with two linear inequalities and a positive cost
(§4.10). So the optimizer below is exact with respect to this model; there is no approximation.

## 4. Recovery optimizer (MILP, `scipy.optimize.milp`)

**Decisions:** $x_b, x_c, x_e \in \{0,1\}$; $v_t \in [0, \bar v]$; $y_t, q_t \ge 0$; $z_t \in [0,\bar z]$; auxiliary $\mu$ (minimum cash)
and $u_t \ge 0$ (inventory shortfall, issue #103).

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
8. **Purchases non-negative:** $P_t \ge 0$ for all $t$, i.e. $v_t \le (1-g)S_t + \pi(1-g)S^{core}_t\lambda_t x_b$.
9. **Debt covenant (optional, issue #85):** $\text{DSCR}_{a,b} \ge \text{DSCR}_{min}$ on every rolling $w$-week window
   (defined below). **Off by default**; switched on by passing `covenant_dscr_min`.
10. **Service-level shortfall (issue #103):** $u_t \ge I^{svc}_t - I_t$ and $u_t \ge 0$ for all $t$, with
   $S_t$ in the §3 recurrence reduced by $\theta\,u_t$.
11. **Sales non-negative:** $S_t \ge 0$ for all $t$ (the §3 physical rule).

**Objective** (minimize disruption, tie-break toward more cash):
$$
\min\; c_b x_b + c_c x_c + c_e x_e + c_v \sum_t v_t + c_y \sum_t y_t + c_z \sum_t z_t W_t + c_u \sum_t u_t \;-\; \varepsilon\,\mu
$$
with $\varepsilon$ small (e.g. $10^{-4}$) so cash only breaks ties. The $c_\cdot$ are **disruption costs set by the
finance owner** (non-cash harm: operational risk, lost goodwill, morale), on top of the cash effects already in §3.
*Why constraint 10 is exact:* $c_u > 0$, and a larger $u_t$ lowers $S_t$, which lowers cash in week $t$ and every later
week (by $a\,\theta$, then $\theta$, then $g\,\theta$ per \$) and never relaxes a constraint. So at the optimum
$u_t = \max(0, I^{svc}_t - I_t)$, the same value `simulate()` computes, and the solver's cash path matches the simulator's.

Call this objective $J(x)$.

**Tie-break between equally cheap plans (issue #104). *Proposal, pending finance-owner sign-off.*** Several plans can
reach the same minimal $J$: with $L_p = 2$, a purchase cut in week 3, 4 or 5 is paid out two weeks later and so raises
week-7 cash by the same amount, at the same $c_v$ per dollar. The solver then returns whichever it meets first, so flipping *Protect payroll* could move
the cuts even when payroll is never cut. *Preference:* among plans that are exactly as cheap, act as late as possible
and borrow for as short a time as possible, so that options stay open. It is applied lexicographically, in two stages:

1. Solve the MILP above. Infeasible → `NO FEASIBLE PLAN` (stage 2 never runs). Otherwise $J^* = J(x^{(1)})$.
2. Re-solve over the same constraints (the yes/no decisions free again), plus $J(x) \le J^*$, minimizing
   $$
   TB(x) = \sum_t \Bigl[\tfrac{T+1-t}{T}\,\bigl(v_t + y_t + z_t W_t\bigr) + \tfrac{t}{2T}\,q_t\Bigr].
   $$
   A dollar of purchase cut, revolver draw or payroll cut weighs more the earlier it happens; a dollar of repayment
   weighs more the later it happens. Repayments use half the slope, so moving a whole draw-and-repay pair one week later
   lowers $TB$ by $\tfrac{1}{2T}$ per dollar instead of tying.

*Guarantee.* Stage 2 can only choose among plans that are optimal on cost: $J(\text{reported plan}) \le J^* + \delta$
with $\delta = \max(10^{-9}\,\lvert J^*\rvert,\ 10^{-7})$, i.e. solver round-off only. The stage-2 row is $J(x) \le J^*$
with no allowance on purpose: any positive allowance would let $TB$ buy sub-cent changes in the plan (e.g. a
\$0.0000001 payroll cut, which would then be listed as an action). After stage 2 the code recomputes $J$ for the
plan; if it exceeds $J^* + \delta$, or stage 2 fails, or the stage-2 plan does not reproduce in `simulate()` (cash paths differ by more than the
agreement tolerance), the stage-1 plan is reported (still optimal on cost) and the
solver message says the tie-break was not applied. A single objective $J + \eta\,TB$ was not used: it keeps cost
first only if $\eta$ is below the smallest cost gap between two distinct candidate plans, a data-dependent number we
cannot bound in advance for every scenario. The two-stage solve needs no such bound.
*Uniqueness.* Distinct weights per week make a remaining tie need an exact coincidence of the weights with the
constraints. It is not impossible in principle; if it happens, HiGHS still returns the same plan for the same inputs.
Worked example (70% demand drop, weeks 5-8): stage 1 alone gave cost $677.34$ in both modes but cut
$v_3 = 10{,}000,\ v_5 = 1{,}024.73$ with payroll protected and $v_4 = 461.54,\ v_5 = 9{,}750,\ v_6 = 813.19$ without.
With the tie-break both modes give the second plan, at the same cost.

**Optional DSCR debt covenant, constraint 9 (issue #85). *Proposal for finance-owner review (issue #85). Not signed
off.*** A lender's debt-service coverage covenant asks whether the business earns enough operating cash to pay its
lenders. A plan that keeps cash above $C_{min}$ but breaks the covenant puts the loan in default, so with the covenant
switched on such a plan counts as infeasible.

*Operating cash flow* (cash basis, built only from §3 terms):
$$
OCF_t = R_t - P_{t-L_p} - (1-z_t)\,W_t - O_t - F_b\,x_b\,\mathbb{1}[t=1].
$$
It counts what the business collects and pays in order to trade: customer receipts, supplier bills when they are paid,
payroll actually paid, fixed opex, and the backup-supplier switching fee. The fee is an operating cost; a bank might
agree to add back a one-off cost, but we do not, which is the conservative choice. It leaves out:
- debt service $J_t, A_t, J^R_t$: this is what is being covered;
- revolver draws and repayments $y_t, q_t$: these are financing, so a business cannot borrow its way into compliance;
- capex $(1-x_c)K_t$ and expansion $(1-x_e)E_t$: these are investing flows. The usual DSCR numerator is operating cash
  before capex, close to EBITDA.

Two caveats for the finance owner. (i) The measure is cash-based, so working-capital moves count. A purchase cut $v_t$
raises $OCF_{t+L_p}$ dollar for dollar by running down stock, which a bank testing on EBITDA would not credit.
(ii) §10 puts the new store's payroll and opex inside $E_t$ (issue #16), while its sales $X_t$ are in $R_t$. In a case
with an expansion, $OCF_t$ would therefore include the new store's sales but not its running costs, and would be
overstated. Both SYNTHETIC businesses have $E_t = X_t = 0$, so this changes no current number.

*Debt service:* $DS_t = J_t + A_t + J^R_t$: term-loan interest, scheduled amortization, and revolver interest. Revolver
interest is included because a lender counts all interest. As a result, drawing on the revolver *lowers* DSCR.
Revolver repayments $q_t$ are not included, because they are voluntary, not scheduled.

*Covenant.* Take a window of $w$ weeks (default $w = 4$, about a month; `covenant_window_weeks`). For every window
$a..b$ inside the horizon, with $b = w..T$ and $a = b - w + 1$ (23 windows when $T = 26$):
$$
\text{DSCR}_{a,b} = \frac{\sum_{t=a}^{b} OCF_t}{\sum_{t=a}^{b} DS_t} \;\ge\; \text{DSCR}_{min}.
$$
No pre-horizon history is used, and a window with zero term-loan debt service ($\sum_{t=a}^{b} (J_t + A_t) = 0$) is not
tested: a drawn revolver could still make $DS > 0$ there, but the multiplied-out row would then demand
$OCF \ge \text{DSCR}_{min} \cdot J^R$ (coverage of revolver interest alone), which is a different covenant.

*Why it is linear (exact, no approximation).* In every tested window the denominator is positive: $J_t + A_t$ sums to
more than 0 by the rule above, and $J^R_t \ge 0$ because $B_{t-1} \ge 0$ (constraint 2). Multiplying both sides by the
denominator therefore keeps the inequality the same:
$$
\sum_{t=a}^{b} OCF_t \;-\; \text{DSCR}_{min} \sum_{t=a}^{b} DS_t \;\ge\; 0 .
$$
$OCF_t$ is made of §3 terms, which are already linear in the decisions. $J_t + A_t$ does not depend on any decision.
$J^R_t = B_{t-1}(r_t + s_R)/52$ is linear in the balance $B_{t-1}$, and $\text{DSCR}_{min}$ is a constant, so
$\text{DSCR}_{min}\cdot J^R_t$ is still linear. Each window is one linear row. It belongs to the shared constraint set,
so it holds in both stages of the tie-break. When it is tight (slack $< 10^{-6}$) it is reported as
"DSCR covenant, weeks $a$–$b$". If the covenant makes a scenario infeasible, the `NO FEASIBLE PLAN` diagnostic keeps
it, and also says whether a plan would exist without it.

*Proposed value.* $\text{DSCR}_{min} = 1.20$ when switched on. Bank covenants are typically in the 1.20–1.25×
range. This range is an `[assumed]` figure from general lending practice: no source was fetched. Real covenants are
usually tested quarterly on trailing-twelve-month figures. A rolling 4-week test is much stricter, because it catches
short shocks that a twelve-month test would average out.

*Worked numbers (baseline, no shock, no action; $R_t$ and $P_{t-L_p}$ at steady state):*

| Business | $OCF_t$ per week | $DS_t$ per week | 4-week $\text{DSCR}$ |
|---|---|---|---|
| Grocer (§10) | $50{,}000 - 32{,}500 - 12{,}000 - 6{,}000 = -500$ | $600{,}000 \times 8\%/52 = 923.08$ | $-2{,}000 / 3{,}692.31 = -0.54$ |
| Restaurant (§10b) | $20{,}000 - 6{,}800 - 7{,}300 - 5{,}400 = 500$ | $156{,}000 \times 10\%/52 = 300$ | $2{,}000 / 1{,}200 = 1.67$ |

*The grocer already breaches any bank covenant, before any shock.* Its operating cash flow is negative ($-500$ a
week: the 1,423.08 weekly loss in §10 is this $-500$ plus 923.08 of interest). With *Protect payroll*, the only lever
that raises OCF is a purchase cut, and total cuts are capped at $I_0 - I_{min} = 25{,}000$. The six windows 3–6, 7–10,
…, 23–26 do not overlap. Each starts at $-2{,}000$, so
$6\,(2{,}000 + 3{,}692.31\,\text{DSCR}_{min}) \le 25{,}000$ if a cut raised OCF by its full amount, which would give
$\text{DSCR}_{min} \le 0.587$. With the stock-out cost (§3, #103) it does not: a cut raises OCF once, in the week it is
paid out, and then loses $\theta = 0.20$ of sales per \$ short in every later week (about $0.35 \times 0.20 = 0.07$ of
OCF per \$ per week once settled). Cuts that repair the early windows deepen the later ones, so with *Protect payroll*
the grocer reaches **no positive** DSCR at all (`NO FEASIBLE PLAN` even at 0.01). With payroll cuts allowed, the
optimizer certifies a plan at 0.73 and none at 0.90 or above. A 1.20 covenant is therefore `NO FEASIBLE PLAN` in both
modes, for **every** grocer scenario including the no-shock baseline. **So the covenant is off by default (`None`),
and the demo grocer runs without it.** The parameters were not changed to hide this. A lender would not have lent on
these terms, and the honest output is that the grocer breaches.

*Known limitation when the covenant is combined with the stock-out cost (§4.10).* Constraint 10 is exact only
because a larger $u_t$ never helps: it costs $c_u$ and lowers cash. Under the covenant a larger $u_t$ can help, since
lower sales cut receipts in weeks $t, t{+}1$ but cut purchases paid in week $t{+}L_p$, which shifts OCF from one
window into the next. The solver can then report a shortfall bigger than the true $\max(0, I^{svc}_t - I_t)$. The
re-simulation check catches this: such a plan disagrees with `simulate()` and is withheld as `SOLVER ERROR`, never
shown (grocer, payroll allowed: DSCR_min 0.74 to 0.80, gaps of \$2.79 to \$91). The covenant is off in the product and
in the demo. The exact fix, a follow-up, is a yes/no variable per week with big-$M$ rows that force
$u_t = \max(0, I^{svc}_t - I_t)$.

*Restaurant (§10b), $\text{DSCR}_{min} = 1.20$, both payroll modes* (in `tests/test_optimizer.py`, hand-checked there):
- `distributor-loss-4wk`: **the plan changes.** Without the covenant, the plan draws 2,760 on the revolver in week 9 and
  repays it in week 10 (cost 27.60). A draw cannot help DSCR, so with the covenant the plan uses the backup supplier,
  plus purchase cuts $v_6 = 52$ and $v_7 = v_8 = v_9 = 612$. These exactly offset the 612 weekly premium paid in weeks
  7–10 against the $1.20 \times 1{,}200 = 1{,}440$ each window needs. Cost: $2{,}500 + 0.05 \times 1{,}888 = 2{,}594.40$.
  The binding constraints are "DSCR covenant, weeks 4–7", "5–8", "6–9" and "7–10".
- `slow-season-plus-300bp`: **feasible without the covenant, `NO FEASIBLE PLAN` with it.** In weeks 4–7 each week has
  $OCF = 14{,}000 - 4{,}760 - 7{,}300 - 5{,}400 = -3{,}460$, so the window has $-13{,}840$ against the $1.20 \times 1{,}560
  = 1{,}872$ it needs. All the levers together add at most $2{,}800 + 2{,}920 = 5{,}720$.

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

### Calibration: reliability bins and Brier decomposition (`calibration.py`, issue #86)

*Descriptive only; it ranks no forecaster.* Computed per forecaster (naive, market, agent) from the scorecard's
per-event scores, after the reveal. Same display rules: $n < 5$ events gives `INSUFFICIENT DATA` and no table;
$5 \le n < 30$ carries the `small sample` caveat. Real-historical and synthetic events are never pooled.

**Bins.** $K = 5$ equal-width bins: bin $k = [k/K, (k+1)/K)$ for $k < K-1$, last bin $[(K-1)/K, 1]$
(so $0.2 \to$ bin 2 of 5 and $p = 1 \to$ bin 5). For bin $k$ with $n_k$ forecasts: mean forecast $\bar p_k$, observed
frequency $\bar o_k = (\#\text{YES})/n_k$, and the Wilson 95% interval ($z = 1.96$) on $\bar o_k$:

$$
\frac{\bar o_k + \frac{z^2}{2n_k}}{1 + \frac{z^2}{n_k}} \;\pm\; \frac{z}{1 + \frac{z^2}{n_k}}\sqrt{\frac{\bar o_k(1-\bar o_k)}{n_k} + \frac{z^2}{4n_k^2}},
\quad\text{clamped to } [0, 1].
$$

Bins with $n_k < 3$ are listed but flagged "too few to read"; empty bins show count 0 and no values.

**Decomposition** (Murphy 1973), $N$ events, base rate $\bar o = \frac1N\sum_i y_i$:

$$
\text{BS} = \tfrac1N\textstyle\sum_i (p_i - y_i)^2,\quad
\text{REL} = \tfrac1N\sum_k n_k(\bar p_k - \bar o_k)^2,\quad
\text{RES} = \tfrac1N\sum_k n_k(\bar o_k - \bar o)^2,\quad
\text{UNC} = \bar o(1 - \bar o).
$$

With binning, $\text{BS} = \text{REL} - \text{RES} + \text{UNC}$ holds exactly **only if the forecasts within each bin are
equal**. In general (Stephenson et al. 2008)
$\text{BS} = \text{REL} - \text{RES} + \text{UNC} + (\text{WBV} - 2\,\text{WBC})$, with
$\text{WBV} = \frac1N\sum_k\sum_{i\in k}(p_i - \bar p_k)^2$ and $\text{WBC} = \frac1N\sum_k\sum_{i\in k}(p_i - \bar p_k)(y_i - \bar o_k)$;
the within-bin term $\text{WBV} - 2\,\text{WBC}$ is reported so the numbers reconcile exactly.

**Forecasts from a scorecard.** The scorecard stores per-event Brier $b$, not $p$. With one snapshot,
$p = \sqrt b$ if $y = 0$ and $p = 1 - \sqrt b$ if $y = 1$ (exact; rounded to 12 decimals so a price on a bin edge stays
in its bin). An event averaged over several snapshots has no single $p$: it is excluded and listed.

**Hand-worked example** (SYNTHETIC; reproduced in `tests/test_calibration.py`). Six $(p, y)$: (0.1, 0), (0.3, 0),
(0.3, 1), (0.7, 1), (0.8, 0), (0.9, 1). $\bar o = 0.5$, $\text{UNC} = 0.25$,
$\text{BS} = (0.01 + 0.09 + 0.49 + 0.09 + 0.64 + 0.01)/6 = 1.33/6 = 0.221667$.

| bin | $n_k$ | $\bar p_k$ | $\bar o_k$ | $n_k(\bar p_k-\bar o_k)^2$ | $n_k(\bar o_k-\bar o)^2$ | Wilson 95% |
|---|---|---|---|---|---|---|
| [0, 0.2) | 1 | 0.1 | 0 | 0.01 | 0.25 | [0, 0.793457] ($= z^2/(1+z^2)$) |
| [0.2, 0.4) | 2 | 0.3 | 0.5 | 0.08 | 0 | [0.094529, 0.905471] |
| [0.4, 0.6) | 0 | | | | | empty |
| [0.6, 0.8) | 1 | 0.7 | 1 | 0.09 | 0.25 | [0.206543, 1] |
| [0.8, 1.0] | 2 | 0.85 | 0.5 | 0.245 | 0 | [0.094529, 0.905471] |

(Every bin has $n_k < 3$, so all are flagged "too few to read". For $n_k = 2$, one YES: centre
$(0.5 + 0.9604)/2.9208 = 0.5$, half-width $(1.96/2.9208)\sqrt{0.125 + 0.2401} = 0.405471$.)
$\text{REL} = 0.425/6 = 0.070833$, $\text{RES} = 0.5/6 = 0.083333$, so $\text{REL} - \text{RES} + \text{UNC} = 1.425/6 = 0.2375 \ne \text{BS}$.
Only bin [0.8, 1.0] mixes forecasts (0.8 with NO, 0.9 with YES; $\bar p = 0.85$, $\bar o = 0.5$):
$\text{WBV} = 0.005/6$, $\text{WBC} = (0.025 + 0.025)/6 = 0.05/6$, within-bin term $= (0.005 - 0.1)/6 = -0.095/6 = -0.015833$,
and $0.2375 - 0.015833 = 0.221667 = \text{BS}$.

### What n ≈ 15 can and can't tell us (statistical review, issue #80)

*Explanatory only: no formula or rule above changes. The model below is `[assumed]` and every number in this
subsection is SYNTHETIC or derived from that assumption; no real case or sealed outcome was used. The
simulations are in `services/api/tests/test_power.py`. Recommendations are proposals for the lead.*

**Per-event difference.** With agent forecast $p_i$, market $q_i$, outcome $y_i$ (after averaging within the event):

$$
d_i = (p_i - y_i)^2 - (q_i - y_i)^2 = (p_i - q_i)(p_i + q_i - 2y_i).
$$

If $y_i \sim \text{Bernoulli}(\pi_i)$ and $\delta_i = p_i - q_i$, then $\mathbb{E}[d_i] = \delta_i(p_i + q_i - 2\pi_i)$ and
$\text{Var}(d_i) = 4\delta_i^2\,\pi_i(1-\pi_i)$. Example, $p = 0.95$, $q = 0.85$: YES gives $0.0025 - 0.0225 = -0.02$,
NO gives $0.9025 - 0.7225 = +0.18$. Differences are usually small and occasionally large.

**Assumed spread $\sigma_d$** `[assumed]`. Outcomes drawn at $\pi \approx 0.85$ (about a T−7 "hold" price), agent and
market differing by a typical $|\delta| = 0.05$ to $0.15$: $\sigma_d = 2|\delta|\sqrt{0.85 \cdot 0.15} = 0.714\,|\delta|$,
so $\sigma_d \approx 0.036$, $0.071$ (central: $2 \times 0.10 \times 0.357$), $0.107$. Near $\pi = 0.5$ it would be up to $|\delta|$;
near $\pi = 0.95$, $0.44\,|\delta|$.

**Minimum detectable difference.** "CI upper bound $< 0$" is a one-sided test at the 2.5% level, with standard error
$\approx \sigma_d/\sqrt n$. A true mean improvement (agent − market, in Brier) is detected

- half the time if it is at least $\text{MDE}_{50} = z_{0.975}\,\sigma_d/\sqrt n = 1.96\,\sigma_d/\sqrt n$ (this is also the typical CI half-width);
- 80% of the time if it is at least $\text{MDE}_{80} = (z_{0.975} + z_{0.80})\,\sigma_d/\sqrt n \approx 2.80\,\sigma_d/\sqrt n$.

Both are a normal approximation; the real $d$ is two-valued and skewed, so true power at $n \approx 15$ may differ.

| $n$ | $\sigma_d = 0.036$: MDE$_{50}$ / MDE$_{80}$ | $\sigma_d = 0.071$ (central) | $\sigma_d = 0.107$ |
|---|---|---|---|
| 4 (shown as `INSUFFICIENT DATA`) | 0.035 / 0.050 | 0.070 / 0.100 | 0.105 / 0.150 |
| 7 | 0.026 / 0.038 | 0.053 / 0.076 | 0.079 / 0.113 |
| 15 | 0.018 / 0.026 | 0.036 / 0.052 | 0.054 / 0.077 |
| 30 | 0.013 / 0.018 | 0.026 / 0.037 | 0.038 / 0.055 |

For scale, a calibrated market at 0.85 has expected Brier $0.85 \times 0.15 = 0.1275$, so the central MDE$_{80}$ at $n = 15$
(0.052) is about 40% of the market's whole Brier score. A realistic edge is far smaller: an agent that is exactly right
($p = \pi$) where the market is off by $|\delta|$ gains only $\mathbb{E}[d] = -\delta^2$, i.e. $-0.01$ for $|\delta| = 0.10$.
80% power for that needs $n = \big(2.80\,\sigma_d/\delta^2\big)^2 \approx 400$ events (178 at $|\delta| = 0.15$, 1,600 at $0.05$);
at $n = 15$ the power is about 8%. **With n ≈ 15 only a very large difference is detectable, so `No improvement measured`
is the expected honest result unless the agent is much better than the market.** It means "not measured", not "no edge".

**Review findings.**
1. *Sound:* pairing on identical events, averaging within an event, events as the resampling unit, Brier as the
   verdict metric, $B = 10{,}000$ (Monte Carlo error is small next to sampling error), a seed fixed before any
   reveal, `INSUFFICIENT DATA` below 5 events (at $n = 4$ there are only 35 distinct resamples).
2. *Exact ties are decided by rounding.* With few events and rounded forecasts the bootstrap means take few distinct
   values, and the 97.5th percentile can be exactly 0. Example (SYNTHETIC, scorecard B and seed): 15 events, one NO,
   agent 0.85 vs market 0.75 everywhere; the exact upper bound is 0, the computed one is $-8 \times 10^{-18}$, so
   `ci_high < 0` reads "agent better than market". *Proposal:* decide on `ci_high < -1e-12` (or round $d_i$ first).
3. *One-sided samples.* If every scored outcome is YES, the bootstrap never sees a surprise. An agent that always says
   0.95 against a calibrated 0.85 market is worse on average ($\mathbb{E}[d] = +0.01$), yet is labelled better whenever no
   NO occurs: probability $0.85^n$ = 44% at $n = 5$, 32% at 7, 8.7% at 15, 0.8% at 30, against the nominal 2.5%
   (simulated in `test_power.py`). *Proposal:* allow "agent better than market" only if both outcomes occur among the
   scored events, otherwise `No improvement measured` with the caveat "all N outcomes were the same; the sample cannot test surprises".
4. *The percentile CI is too narrow at small n.* It is close to $\bar d \pm 1.96\, s_n/\sqrt n$ with $s_n$ dividing by $n$ and
   $z$ in place of Student's $t$. For normal $d_i$ its coverage is about 85% at $n = 5$, 88% at 7, 92% at 15, 94% at 30.
   Simulated mean half-width ÷ formula: 0.74 ($n = 4$), 0.83 (7), 0.92 (15), 0.98 (30). *Proposal:* also report
   $\bar d \pm t_{n-1,0.975}\, s/\sqrt n$ ($t$ = 2.78, 2.45, 2.14, 2.05 at $n$ = 5, 7, 15, 30) and require both bounds below 0.
5. *Multiple comparisons.* Each variant compared with the market is a separate 2.5% chance of a false "better";
   two variants give up to 5%. *Proposal:* name one primary variant before the reveal and call the others exploratory,
   or use a 97.5% CI (percentiles 1.25 and 98.75) for each of two comparisons.
6. *Asymmetry.* A CI entirely above 0 (agent measurably worse) also shows `No improvement measured`. True, but it hides
   the direction; the CI should always be shown next to the verdict.
7. *Log loss is fragile at small n.* One confident miss costs $-\ln(10^{-6}) = 13.8$ (Brier is at most 1), adding 0.92 to
   a 15-event mean. Keep Brier as the only verdict metric; log loss stays secondary, without a CI.
8. *Accuracy at 0.5* is uninformative here: near $p \approx 0.85$ both forecasters say YES on almost every event.

**Exact wording.** The verdict, label and caveat at the start of each line are the strings in `evaluator.py`; the text
after them is the context to show with them. $N$, $\Delta$, $a$, $b$ are the computed values, never typed in.
- $n < 5$: "INSUFFICIENT DATA: No valid comparison (n = N events; at least 5 are needed). Per-event scores are listed below."
- Otherwise: "No improvement measured (n = N events; mean Brier difference, agent − market: Δ; 95% CI: [a, b])."
- Only when $b < 0$: "agent better than market (n = N events; mean Brier difference, agent − market: Δ; 95% CI: [a, b], entirely below 0)."
- For $5 \le n < 30$ add: "small sample: n = N events (< 30)." *Proposed second sentence (not yet in the code):*
  "The 95% CI is approximate and may be too narrow."
- Spoken: "With N events we could only have detected a large edge. We did not measure one; that is not proof that there is none."
- Never: "the agent matches the market", "no difference", or "95% likely to be better".

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
- **Synthetic benchmark price (SYNTHETIC cases only, #102).** Venue `synthetic`, `quote_kind = synthetic`,
  `provenance = SYNTHETIC`, decimal scale ($p = x$, normalized once like any quote), URLs on a `.invalid` host,
  `raw_sha256` = SHA-256 of the canonical JSON of `{market_id, raw_price, ts, venue}`, `collected_at` = when the
  case author wrote it. Label: "SYNTHETIC benchmark price written by the case author; not from any market, not a
  true probability". It is not price-derived: no venue, trades or fees exist. The 24 h selection rule and the
  `venue:market_id` reference apply unchanged. A real case can never load one. Any quote on a SYNTHETIC case is shown
  with provenance SYNTHETIC. Scoring uses it as the "market" forecaster only in the synthetic case set, which is never
  OFFICIAL and never pooled with real cases (EVALUATION_PROTOCOL §3). No formula in this section changed.

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

*Break-even (issue #55, `routes/decision.py`).* For the top two policies $a, b$ by $\mathbb{E}[V]$ at $p$ among those
feasible in both states, $\mathbb{E}[V \mid a] = \mathbb{E}[V \mid b]$ at
$$
p^* = \frac{V(b,0) - V(a,0)}{\big(V(a,1) - V(a,0)\big) - \big(V(b,1) - V(b,0)\big)}.
$$
$p^*$ is NOT AVAILABLE when fewer than two policies are feasible in both states, when the denominator is $0$ (within
$10^{-6}$ dollars: the two lines are parallel, so the ranking never depends on $p$), or when $p^* \notin [0,1]$.

*When can a break-even exist? (issue #103).* $p^*$ exists only if $V(a,1) - V(b,1) \ne V(a,0) - V(b,0)$: some policy's
cash effect must depend on the outcome. A shock that only raises the term-loan rate changes $J_t$, which no §4 action
touches (the revolver is undrawn in the frames), and the stock-out cost depends on $I^{svc}_t$, which moves with demand,
not with rates. So for a rate-only YES state every pair of policies differs by the same amount in both states and
$p^*$ is NOT AVAILABLE, with or without the stock-out cost. The stock-out cost creates the dependence through demand: if
the YES state lowers demand, $I^{svc}_t$ falls, and a purchase cut that is surplus stock in YES is a shortfall in NO.
That is why the FOMC frame (`decision_frames.json`) now also carries a small demand effect in its YES state
(*proposal for finance-owner review, issue #103*). Worked values: FOMC $p^* = 630.50 / 1{,}280.50 = 0.4924$; CPI
WAIT → HEDGE at $6/7 = 0.857$ and HEDGE → ACT at $45/49 = 0.918$ (hand arithmetic in `tests/test_decision_frames.py`).

## 9. Golden test cases (hand-checked; must be in `tests/test_financials.py`)

Common: $C_0 = 100{,}000$; $S^{base} = 50{,}000$/wk (all stores); $S_0 = 50{,}000$; $g = 0.35$; $a = 0.8$; $L_p = 1$,
$P_0 = 32{,}500$; $W = 12{,}000$; $O = 6{,}000$; $D = 600{,}000$; $A = 0$; no revolver, capex, expansion, outage.
These cases use their own inputs (note $L_p = 1$ here, versus 2 weeks in §10).
*Hand-checked 2026-11-12 (issue #6): every value in cases A–C and every scoring fixture below matches.*
*Unchanged by issue #16:* none of cases A–C has an outage, an expansion, a revolver or a purchase cut. The §2 base-store
outage, the §4 terminal revolver condition and the §10 expansion-cost note therefore leave every value below as it was.
*Unchanged by issue #103:* none of cases A–C cuts purchases, so $I_t = I_0$ in every week. With the §10 stock-out
parameters ($\sigma = 1$, $\theta = 0.20$) and $I_0 = 65{,}000$, $I^{svc}_t = 65{,}000\,m_t$: 65,000 in cases A and C,
and $65{,}000 \times 0.8 = 52{,}000$ in week 2 of case B. So $u_t = 0$ and the values below hold. (The test file's
default uses $I_0 = 60{,}000$, which §9 does not use, with the stock-out cost off; a separate test re-runs A–C with
$I_0 = 65{,}000$ and the §10 stock-out parameters and gets the same values.)

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
| Service level $\sigma$ | 1.0 of $I_0$ ($I^{svc}_t = 65{,}000\,m_t$, i.e. 2 weeks of cost of goods of base-store demand) | *Signed off by the finance owner, 2026-11-14 (#141).* The service level is the starting stock: §10 already calls 2 weeks of cost of goods typical for a fresh-heavy grocer, so any cut below it thins the shelves. See the justification below. |
| Stock-out lost sales $\theta$ | 0.20 of sales per \$ of shortfall per week | *Signed off by the finance owner, 2026-11-14 (#141).* A cut of 10% of the service level (6,500 at cost) loses $0.20 \times 6{,}500 = 1{,}300$ of sales a week, 2.6% of sales; at the floor (25,000 short) it loses 5,000 a week, 10% of sales. |
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

**Stock-out cost: justification (issue #103, proposal for finance-owner review).** The finance owner's decision was a
stock-out / lost-margin cost, with a service level of about 1.5 weeks of cost of goods ($1.5 \times 0.65 \times 50{,}000 =
48{,}750$) suggested as the starting point. Checked against $I_0 = 65{,}000$ and $I_{min} = 40{,}000$, 48,750 would leave
$65{,}000 - 48{,}750 = 16{,}250$ of stock that the model treats as worthless. Every frame cut (at most 8,000 before this
issue) and most optimizer cuts fit inside that, so purchase cuts would have stayed free cash, which is the flaw this issue
fixes. $\sigma = 1$ puts the service level at $I_0$ = 2 weeks of cost of goods, which §10 already calls typical for a
fresh-heavy grocer. The business is then running at its target stock, and any cut below it costs sales. Below the
target, safety stock and shoppers switching to another item absorb most gaps, so not every missing dollar of stock is a
lost sale. $\theta = 0.20$ means the share of sales lost is $\theta\,I^{svc}/S^{core} = 0.2 \times 65{,}000 / 50{,}000 =
0.26$ times the share of cover that is missing: 10% short of cover loses 2.6% of sales, and at the hard floor $I_{min}$ ($1.23$ weeks of cover, "shelves look empty") 10% of sales. Once settled, each
dollar of stock held below the service level costs $g\,\theta = 0.07$ of cash a week. So a permanent cut pays for itself
only if the stock is not needed for more than about $1/0.07 \approx 14$ weeks, or if demand falls so that the service level
falls with it. Golden cases A–C and every scenario without a purchase cut are unchanged (§9), because then $I_t = I_0 \ge I^{svc}_t$.
*Known limits:* (1) a cut is permanent because the model has no restocking action, so a cut made for a temporary demand dip
is short again once demand recovers (this matters for the CPI frame); (2) lost sales after week 26 are not counted, so a cut
in the last weeks of the horizon looks cheaper than it is. The optimizer uses this end-of-horizon effect (it times cuts
late, see `tests/test_optimizer.py`).

### Disruption costs (non-cash harm, on top of the cash effects in §3)

Units differ by action type. The three yes/no actions carry a dollar-equivalent harm per decision. The three amount actions
carry harm per dollar of action. To compare them, the "10k yardstick" column shows the harm of using each lever to raise or
save about 10,000. For a yes/no action, that is simply its fixed weight.

| Weight | Action | Value | Harm at 10k | Why it ranks here |
|---|---|---|---|---|
| $c_y$ | Revolver draw | 0.01 per \$ drawn | 100 | Covering a cash gap is what the facility is for, and its interest is already in the cash path. This is a small charge for using up headroom. |
| $c_v$ | Purchase cut | 0.05 per \$ cut | 500 | Thinner shelves and stock-out risk that the model does not capture. (Issue #103: the lost margin of stock below the service level is now in the cash path, and $c_u$ covers its goodwill harm; $c_v$ is kept unchanged as the harm of the order change itself.) |
| $c_c$ | Defer non-critical capex | 1,000 per decision | 1,000 | Non-critical by definition, but maintenance risk builds up while it is deferred. |
| $c_b$ | Use backup supplier | 2,500 per decision | 2,500 | Quality, consistency and supplier-relationship risk beyond the fee and premium. |
| $c_e$ | Delay expansion | 5,000 per decision | 5,000 | Strategic cost: lost momentum and lease or landlord risk. |
| $c_u$ | Stock below the service level | 0.01 per \$ of shortfall per week | 100 a week (1,000 for 10 weeks) | *Signed off by the finance owner, 2026-11-14 (#141).* Goodwill: shoppers who find gaps may shop elsewhere next time. The lost margin itself is already in the cash path ($g\,\theta = 0.07$ per \$ a week). It must be above 0 so the optimizer's shortfall $u_t$ equals the simulator's (§4.9). |
| $c_z$ | Payroll cut | 5.00 per \$ of payroll cut | 50,000 | Worst lever: morale, turnover and service quality, and it hurts people. A 1,000 payroll cut counts as much harm as delaying the expansion, so cutting payroll beats delaying the expansion only for shortfalls under 1,000. |

Ranking, least to most harmful: revolver draw < purchase cut < defer capex < backup supplier < delay expansion < payroll cut.
$c_u$ is charged per week, so where a cut falls in this ranking depends on how long the stock stays short: a 10,000
cut held 10 weeks costs $500 + 1{,}000 = 1{,}500$ of harm, more than deferring capex.

**Sign-off:** ☑ Yaseen has reviewed §1–§4 and §8 assumptions (2026-11-12, issue #6) · ☐ Lead has reviewed §6–§7.

## 10b. Second SYNTHETIC business: a full-service restaurant (issue #109)

**Proposal for finance-owner review (issue #109). Not signed off.**

This is a second fictional business, "Demo Bistro": a 12-person, single-location, full-service restaurant. It is
**SYNTHETIC** (fixture `services/api/data/restaurant_business.json`, scenarios `services/api/data/scenarios_restaurant.json`).
**No formula changed** for this business (issue #103 added the §3 stock-out cost; the §10b values below keep it inactive
for the restaurant, so every number in this section is unchanged): it runs through the same §1–§3 engine and §8 decision rule as the §10 grocer. Only the parameter
values are different. They give the business a different shape: payroll is a large share of sales, there is about one
week of perishable stock, card receipts settle in 1–2 days, suppliers are paid weekly, and the margin is thin. Public
industry ratios are used only to make that shape realistic. The values are illustrative and describe no real company.

Sources actually fetched and read (2026-11-13). The quoted figure is what the page states.

- **[NRA-labor]** National Restaurant Association, "Elevated labor costs had a significant impact on restaurant
  profitability in 2024", 2025-10-08,
  <https://restaurant.org/research-and-media/research/restaurant-economic-insights/analysis-commentary/elevated-labor-costs-had-a-significant-impact-on-restaurant-profitability-in-2024/>.
  Full-service: "salaries and wages (including benefits) represented a median of 36.5% of sales in 2024".
- **[NRA-food]** National Restaurant Association, "Higher volume restaurants reported lower food-cost ratios in 2024",
  2025-10-16,
  <https://restaurant.org/research-and-media/research/restaurant-economic-insights/analysis-commentary/higher-volume-restaurants-reported-lower-food-cost-ratios-in-2024/>.
  For full-service respondents with sales below \$2 million, food and non-alcohol beverage costs "were a median of 33.7% of
  sales", and income before taxes "was a median of 1.1% of sales".
- **[NRA-occupancy]** National Restaurant Association, "Restaurant occupancy costs were more than 5% of sales in 2024",
  2025-09-03,
  <https://restaurant.org/research-and-media/research/restaurant-economic-insights/analysis-commentary/restaurant-occupancy-costs-were-more-than-5-of-sales-in-2024/>.
  Full-service occupancy costs: "a median of 5.7% of sales in 2024".
- **[JPMCI]** JPMorgan Chase Institute, "Cash is King: Flows, Balances, and Buffer Days", 2016-09-01,
  <https://www.jpmorganchase.com/institute/all-topics/business-growth-and-entrepreneurship/report-cash-flows-balances-and-buffer-days>.
  "Cash buffer days are the number of days of cash outflows a business could pay out of its cash balance were its inflows
  to stop." The median-by-industry table lists Restaurants at 16 days, the lowest industry; the all-business median is
  27. The data cover February–October 2015, so the figure is dated.
- **[Toast]** Toast support, "Deposit Schedules Overview" (US standard schedule, page last updated 2026-11-13),
  <https://support.toasttab.com/en/article/When-are-deposits-made-to-my-bank-account?lang=en_US>. For card batches closed
  before the 9:30 p.m. ET cutoff, "Deposit arrives next business day"; for batches closed after it, "Deposit arrives two
  business days later".
- **[MarketMan]** MarketMan (inventory-software vendor blog), "How Much Inventory Should a Restaurant Carry?",
  2023-09-13, <https://marketman.com/blog/how-much-inventory-should-restaurant-carry>.
  "Food: 4-6 times per month (5-7 days worth of product on hand)".

The NRA figures are survey medians from its 2025 Restaurant Operations Data Abstract, which covers 2024. Only the public
summaries above were read, not the paid abstract. A median for each cost line separately does not add up to a
consistent median restaurant, so the opex value below is calibrated, not copied.

| Symbol | Fixture field | Value | Unit | Justification | Source |
|---|---|---|---|---|---|
| $T$ | `business.horizon_weeks` | 26 | weeks | Same half-year horizon as the grocer (§10), so the two businesses are comparable. | assumption: kept equal to §10 |
| $S^{base}$ | `business.stores[0].base_sales` | 20,000 | \$/week | About 1.04M a year for 12 staff, which puts it in the NRA's "full-service, sales below \$2 million" group used for $g$ below. | assumption: size chosen for a 12-person restaurant |
| $S_0$ | `business.sales_0` | 20,000 | \$ | Steady state before week 1: equal to base sales. | assumption: steady state |
| $g$ | `business.gross_margin` | 0.66 | fraction | Food and beverage cost is 34% of sales, so $g = 1 - 0.34$. Rounded from the 33.7% median. | [NRA-food]: 33.7% median, full-service under \$2M |
| $a$ | `business.same_week_collection` | 0.90 | fraction | Card batches deposit 1–2 business days after close, so most of a week's sales land in the same cash week. The 10% spill-over is an assumption; it depends on which day the cash week closes (see open questions). | [Toast] for the 1–2 business-day lag; the 0.90 split is an assumption |
| $L_p$ | `business.supplier_lag_weeks` | 1 | weeks | Perishables are invoiced weekly and paid the following week (short terms, about net-7). | assumption: no fetched source states restaurant distributor terms |
| $P_0$ | `business.prior_purchases[0]` | 6,800 | \$ | Steady state: $(1-g) \times S_0 = 0.34 \times 20{,}000$. One value because $L_p = 1$. | assumption: steady state |
| $W$ | `business.payroll` | 7,300 | \$/week | 36.5% of sales, wages including benefits. That is about 608 a week per person for 12 staff, a full-time and part-time mix; servers' tips are not payroll. | [NRA-labor]: 36.5% full-service median |
| $O$ | `business.opex` | 5,400 | \$/week | 27% of sales. Occupancy is about 5.7% (1,140); the other 21.3% covers utilities, supplies, card fees, repairs, marketing, insurance and admin. The total is set so that weekly profit is 1.0% of sales (hand check below), close to the 1.1% median pre-tax income for full-service restaurants under \$2M. | [NRA-occupancy] 5.7% for occupancy; [NRA-food] 1.1% pre-tax median used to calibrate; the split of the rest is an assumption |
| $K_t$ | `business.capex` | 0 | \$/week | No scheduled non-critical capex in the base business, as for the grocer. | assumption: set per demo case |
| $E_t$ | `business.expansion_outflow` | 0 | \$/week | No expansion: a single location. | assumption: single site |
| $X_t$ | `business.expansion_sales` | 0 | \$/week | No expansion. | assumption: single site |
| $D_1$ | `business.term_loan_principal_1` | 156,000 | \$ | Fit-out and equipment loan. It is set to 156,000 so that interest is exactly $156{,}000 \times 10\% / 52 = 300$ a week, which keeps the hand checks round. | assumption: size picked for round arithmetic |
| $r$ | `business.base_rate` | 0.10 | 1/yr | All-in floating small-business rate. It floats, so the rate shock passes through. | assumption: no rate source fetched |
| $A_t$ | `business.amortization` | 0 | \$/week | Interest-only over the horizon, as for the grocer, so the hand checks stay simple. | assumption: kept equal to §10 |
| $B_0$ | `business.revolver_balance_0` | 0 | \$ | Undrawn at the start. | assumption |
| $\bar B$ | `business.revolver_limit` | 30,000 | \$ | 1.5 weeks of sales of headroom. | assumption |
| $s_R$ | `business.revolver_spread` | 0.02 | 1/yr | Revolvers price above term debt; same spread as the grocer. | assumption: kept equal to §10 |
| $C_0$ | `business.cash_0` | 45,000 | \$ | 16 cash buffer days: weekly outflows are $6{,}800 + 7{,}300 + 5{,}400 + 300 = 19{,}800$, or 2,828.57 a day, and $16 \times 2{,}828.57 = 45{,}257$, rounded to 45,000 (15.9 days). | [JPMCI]: restaurants 16 median cash buffer days (2015 data) |
| $C_{min}$ | `business.min_cash` | 15,000 | \$ | About 2 weeks of payroll ($2 \times 7{,}300 = 14{,}600$), the same rule as the grocer. | assumption: §10 rule applied |
| $I_0$ | `business.inventory_0` | 6,800 | \$ at cost | One week (7 days) of food cost, $0.34 \times 20{,}000$, the top of the 5–7 days range. | [MarketMan]: "5-7 days worth of product on hand" |
| $I_{min}$ | `business.min_inventory` | 4,000 | \$ at cost | About 4 days of food cost; below this the full menu cannot be served. It caps total purchase cuts at $I_0 - I_{min} = 2{,}800$. | assumption |
| $\sigma$ | `business.service_level_share` | 0.5 | fraction of $I_0$ | *Signed off by the finance owner, 2026-11-14 (#141).* $I^{svc} = 0.5 \times 6{,}800 = 3{,}400$ at planned demand (3.5 days of food cost), below the hard floor $I_{min} = 4{,}000$. For this restaurant $I_{min}$ already marks where the menu breaks, so the floor binds before any stock-out cost: no feasible plan has $u_t > 0$ and every #109 number below is unchanged. Open question: a restaurant on one week of stock may lose covers before it reaches 4 days. | assumption: chosen to keep #109 unchanged |
| $\theta$ | `business.stockout_lost_sales_rate` | 0.2 | 1/week | *Signed off by the finance owner, 2026-11-14 (#141).* Same as the grocer (§10); inactive here because of $\sigma$. | assumption: reused from §10 |
| $\pi$ | `business.backup_premium` | 0.15 | fraction | Buying from a cash-and-carry or specialty supplier costs about 15% more than contract prices. | assumption |
| $F_b$ | `business.backup_switch_fee` | 500 | \$ | Account set-up and delivery changes for a small single site. | assumption |
| $\phi$ | `scenario_parameters.supplier_outage_dependent_share` | 0.60 | fraction | 60% of menu sales need proteins and produce that only the main broadline distributor delivers. | assumption |
| $\bar v$ | `optimizer_parameters.purchase_cut_cap_per_week` | 1,400 | \$/week | About 20% of a normal week's purchases (6,800). Deeper cuts empty the walk-in. | assumption (for the optimizer, PR #69) |
| $\bar z$ | `optimizer_parameters.payroll_cut_cap` | 0.10 | fraction | Up to 10% through fewer shifts and no overtime, without layoffs. Forced to 0 in protect-payroll mode. | assumption: kept equal to §10 |
| $\varepsilon$ | `optimizer_parameters.tie_break_epsilon` | 0.0001 | per \$ | Same tie-break as §10. | assumption: kept equal to §10 |
| $c_y$ | `optimizer_parameters.disruption_costs.revolver_draw_per_dollar` | 0.01 | per \$ | Reused from §10 unchanged; the ranking of levers is the same for a restaurant. | assumption: reused from §10 |
| $c_v$ | `optimizer_parameters.disruption_costs.purchase_cut_per_dollar` | 0.05 | per \$ | Reused from §10 unchanged. | assumption: reused from §10 |
| $c_c$ | `optimizer_parameters.disruption_costs.defer_capex_per_decision` | 1,000 | \$ | Reused from §10 unchanged. | assumption: reused from §10 |
| $c_b$ | `optimizer_parameters.disruption_costs.backup_supplier_per_decision` | 2,500 | \$ | Reused from §10 unchanged. | assumption: reused from §10 |
| $c_e$ | `optimizer_parameters.disruption_costs.delay_expansion_per_decision` | 5,000 | \$ | Reused from §10 unchanged (no expansion here). | assumption: reused from §10 |
| $c_z$ | `optimizer_parameters.disruption_costs.payroll_cut_per_dollar` | 5.00 | per \$ | Reused from §10 unchanged: payroll is still the worst lever. | assumption: reused from §10 |
| $c_u$ | `optimizer_parameters.disruption_costs.stock_shortfall_per_dollar_week` | 0.01 | per \$ per week | *Signed off by the finance owner, 2026-11-14 (#141).* Reused from §10. | assumption: reused from §10 |

`tests/test_restaurant_business.py` parses this table and checks every value against the fixture, so the document and the
data cannot drift apart.

**Baseline economics.** Weekly gross profit is $0.66 \times 20{,}000 = 13{,}200$. Fixed costs are
$7{,}300 + 5{,}400 + 300 = 13{,}000$, so the restaurant makes 200 a week before any shock: 1.0% of sales. Its prime cost
(food plus labor) is $34\% + 36.5\% = 70.5\%$ of sales. In steady state $R_t = 20{,}000$ and $P_{t-1} = 6{,}800$, so
$C_t - C_{t-1} = 20{,}000 - 6{,}800 - 7{,}300 - 5{,}400 - 300 = 200$. With no shock, $C_1 = 45{,}200$ (the minimum) and
$C_{26} = 45{,}000 + 26 \times 200 = 50{,}200$. Cash never goes below $C_{min}$.
Compared with the grocer: each lost sales dollar costs $g = 0.66$ of cash here, against 0.35 there. The loan is a quarter
of the size, so a +300bp rate rise costs only 90 a week. This business is hit by demand, not by rates.

**Hand-check shortcut (follows from §3; no new formula).** With no action, suppose sales fall $\Delta S_t$ below baseline.
Receipts then lose $a\,\Delta S_t + (1-a)\,\Delta S_{t-1}$, and with $L_p = 1$ the bill paid in week $t$ falls by
$(1-g)\,\Delta S_{t-1}$. So the week's cash change is the baseline 200 plus
$$\Delta C_t = -0.9\,\Delta S_t + (0.34 - 0.10)\,\Delta S_{t-1} = -0.9\,\Delta S_t + 0.24\,\Delta S_{t-1}.$$
Once a shock has fully settled, each lost sales dollar has cost $g = 0.66$.

**Scenarios** (`scenarios_restaurant.json`; shock sizes are assumptions chosen to stress the business, not forecasts):

| Scenario | Shock (§1 channels only) | $C_T$ | First week $C_t < C_{min}$ | Lowest cash $\min_t C_t$ |
|---|---|---|---|---|
| `road-closure-9wk` | demand $\delta = 0.30$, weeks 4–12, $\rho = 3$ | 10,600 | week 11 (stays below to week 26) | 7,720 (week 14) |
| `distributor-loss-4wk` | outage $\kappa_t = 0$ in weeks 6–9, $\phi = 0.60$ | 18,520 | week 9 (week 9 only) | 12,240 (week 9) |
| `slow-season-plus-300bp` | rate $+3\%$ from week 1; demand $\delta = 0.30$, weeks 2–9, $\rho = 0$ | 16,180 | week 9 (weeks 9–15) | 12,870 (week 9) |

Cash never goes negative in any of them: runway is "> 26 weeks". Every value was worked out by hand first and then matches
`simulate()` to 0.01.

*Road closure.* Lost sales are 6,000 a week in weeks 4–12. In week 13, $m = 1 - 0.3\,(1 - 1/3) = 0.8$, so 4,000 is
lost. In week 14, $m = 0.9$, so 2,000. The total is $9 \times 6{,}000 + 4{,}000 + 2{,}000 = 60{,}000$.
Weeks 1–3: $+200$ each, so $C_3 = 45{,}600$. Week 4: $200 - 5{,}400 = -5{,}200$, so $C_4 = 40{,}400$.
Weeks 5–12: $200 - 5{,}400 + 1{,}440 = -3{,}760$ each, so $C_{10} = 17{,}840$, **$C_{11} = 14{,}080 < 15{,}000$**, and $C_{12} = 10{,}320$.
Week 13: $200 - 3{,}600 + 1{,}440 = -1{,}960$, so $C_{13} = 8{,}360$. Week 14: $200 - 1{,}800 + 960 = -640$, so $C_{14} = 7{,}720$ (the minimum).
Week 15: $200 + 480$, so $C_{15} = 8{,}400$. Then $+200$ a week, so $C_{26} = 8{,}400 + 11 \times 200 = 10{,}600$.
Cross-check: $50{,}200 - 0.66 \times 60{,}000 = 10{,}600$.

*Distributor loss.* Lost sales are $0.6 \times 20{,}000 = 12{,}000$ a week in weeks 6–9, 48,000 in total. $C_5 = 46{,}000$.
Week 6: $200 - 10{,}800$, so $C_6 = 35{,}400$. Weeks 7–9: $200 - 10{,}800 + 2{,}880 = -7{,}720$ each, so $C_7 = 27{,}680$,
$C_8 = 19{,}960$ and **$C_9 = 12{,}240$**. Week 10: $200 + 2{,}880$, so $C_{10} = 15{,}320$. Then $C_{26} = 15{,}320 + 16 \times 200 = 18{,}520$.
Cross-check: $50{,}200 - 0.66 \times 48{,}000 = 18{,}520$.
*With the backup supplier* ($x_b = 1$): no sales are lost. The premium is $0.15 \times 0.34 \times 20{,}000 \times 0.6 = 612$ a
week, bought in weeks 6–9 and paid in weeks 7–10, plus the 500 fee in week 1. So
$C_{26} = 50{,}200 - 500 - 4 \times 612 = 47{,}252$, and the lowest cash is $C_{10} = 44{,}052$.

*Slow season + rate rise.* At 13%, interest is $156{,}000 \times 0.13 / 52 = 390$, so the base week makes 110. Lost sales
are 6,000 a week in weeks 2–9, 48,000 in total. $C_1 = 45{,}110$. Week 2: $110 - 5{,}400$, so $C_2 = 39{,}820$.
Weeks 3–9: $110 - 3{,}960 = -3{,}850$ each, so $C_8 = 16{,}720$ and **$C_9 = 12{,}870$** (the minimum). Week 10: $110 + 1{,}440$, so
$C_{10} = 14{,}420$. Then $+110$ a week: $C_{15} = 14{,}970$ (still below the floor), $C_{16} = 15{,}080$, and
$C_{26} = 14{,}420 + 16 \times 110 = 16{,}180$. Cross-check: $45{,}000 + 26 \times 110 - 0.66 \times 48{,}000 = 16{,}180$.

**Protect payroll (§4.5, checked with the §8 decision rule in `core/decision.py`).** Each scenario is evaluated with its
shock in the YES state and the baseline in the NO state, $p = 0.5$. Six policies are tested: WAIT; CUT PURCHASES (1,400 in
weeks 2 and 3, the full $I_0 - I_{min}$); REVOLVER BRIDGE (draw 5,000 in week 8, repay it in week 26); BACKUP SUPPLIER; ALL
NON-PAYROLL LEVERS (the last three together); and TRIM PAYROLL 10% ($z_t = 0.10$ in weeks 4–26).

- *Road closure: no safe plan with payroll protected.* With $z_t = 0$, no plan in the whole §4 action space can keep
  $C_{26} \ge C_{min}$. The backup supplier only costs money when there is no outage. $K_t = E_t = X_t = 0$, so deferring
  capex or delaying expansion changes nothing. Total purchase cuts are capped at $I_0 - I_{min} = 2{,}800$. Revolver flows
  add up to $B_T - B_0 \le 0$, minus interest. So $C_{26} \le 10{,}600 + 2{,}800 = 13{,}400 < 15{,}000$. The decision rule
  reports `NO SAFE POLICY`. This is a bound argument, not the optimizer: the optimizer's `NO FEASIBLE PLAN` test needs
  PR #69. With protect-payroll off, TRIM PAYROLL 10% saves $730 \times 23 = 16{,}790$ and is feasible. Its lowest cash is
  $C_{13} = 8{,}360 + 10 \times 730 = 15{,}660$, and $C_{26} = 27{,}390$.
- *Distributor loss: payroll stays whole.* The backup supplier keeps cash above the floor (lowest 44,052). Cutting
  purchases (lowest $12{,}240 + 2{,}800 = 15{,}040$) or bridging on the revolver also works.
- *Slow season + rate rise: payroll stays whole.* The dip is temporary relative to the floor, so bridging on the revolver
  works. It costs $5{,}000 \times 0.15 / 52 \times 18 = 259.62$ of interest, giving $C_{26} = 15{,}920.38$. Cutting purchases also
  works (lowest $12{,}870 + 2{,}800 = 15{,}670$). The backup supplier alone does not: there is no outage, and the 500 fee
  makes things worse.

**Sign-off:** ☐ Yaseen has reviewed the §10b parameters and scenarios (issue #109).
