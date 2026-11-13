---
name: finance-engine
description: How to build and change FAULTLINE's deterministic business simulation (cash-flow recurrence, demand/rate/supplier shocks, runway) and the MILP recovery optimizer (scipy.optimize.milp, payroll protection, NO FEASIBLE PLAN). Use for any work on services/api/core/financials.py, core/optimizer.py, their tests, the synthetic demo business fixture, ACT/WAIT/HEDGE payoffs, or when the finance owner (Yaseen) asks about formulas, assumptions, or numbers.
---

# Finance engine + optimizer

**Contract:** `docs/MATH_MODEL.md` §1–§5, §8–§10. Code implements it exactly. If you must change a formula, change the
doc in the same PR and say so in the PR body. The finance owner (Yaseen) has final say on economic assumptions.

## Implementation rules
- Pure, typed functions. Inputs are Pydantic models (`BusinessParams`, `ScenarioShock`, `ActionPlan`); outputs are
  `SimulationResult` with per-week arrays for every node in §5 (sales, receipts, purchases, inventory, interest,
  payroll, revolver, cash) so the cascade UI can diff them.
- No randomness, no LLM calls, no I/O in `financials.py`/`optimizer.py`. Use `float` dollars; round **only** for display.
- Weekly grid `t = 1..T`; initial conditions (`S_0`, prior purchases) are explicit fields, never implicit zeros.
- The simulator and the optimizer must agree: after `optimize()` returns a plan, re-simulate it with `simulate()` and assert
  the cash paths match within 1e-6. Put that assertion in a test.

## Optimizer (scipy `milp`)
- Build one variable vector: binaries `x_b, x_c, x_e`; per-week continuous `v_t, y_t, q_t, z_t, B_t, C_t, I_t`; scalar `mu`.
  Express §3 as equality rows (`C_t - C_{t-1} - ... = known_t`) and §4 as bounds/inequalities via `LinearConstraint` and `Bounds`.
- `integrality` = 1 for binaries. Check `res.status`: 0 → OPTIMAL; 2 → `NO FEASIBLE PLAN`; anything else → surface the solver message.
- **Protect payroll** = upper bound of every `z_t` set to 0. Test: with protect_payroll on, a scenario that is only feasible via payroll cuts must return `NO FEASIBLE PLAN`.
- Report binding constraints (slack < 1e-6) by name so the UI can say *why* ("liquidity floor binds in week 9").
- Diagnostic for infeasible: bisection or a second LP maximizing `mu` without the floor → "smallest feasible floor = $X".

## Tests required (tests/test_financials.py, tests/test_optimizer.py)
- Golden cases A, B, C from MATH_MODEL §9, to 1e-3.
- Shock monotonicity: bigger demand drop → lower or equal min cash; higher rate → higher interest.
- Optimizer: feasible baseline picks no costly actions; facility limit respected; inventory floor respected;
  payroll protection enforced; infeasible case reported; simulator/optimizer agreement.

## Talking with Yaseen
He is the finance authority, not a programmer. Show formulas in MATH_MODEL notation, show worked numbers in a small table,
and explain code as "this function computes R_t = a·S_t + (1−a)·S_{t−1}". When he proposes an assumption change,
restate it as a formula diff and the golden-case numbers it would change, then implement.
