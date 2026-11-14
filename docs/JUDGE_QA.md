# Judge question bank: 30 hard questions with honest answers

For practice demos (Sat Nov 14, 1pm) and Demo Day (Sun Nov 15, 1pm); see `docs/HACKATHON.md`. Six questions per
judging criterion: Demo and pitch, Investability, Product, Societal impact, and the +2 AI-alignment bonus.

How to use it:
- Each **Say** answer is at most 40 spoken words. Say it, then stop. If a judge wants more, open the file in **Backed by**.
- **Backed by** points to the code, test or doc on `main` (commit `4a1f2c2`, 2026-11-14) that makes the answer true.
- Anything not merged when this was written is marked **PENDING: #N**. If it is still pending on the day, say "that is
  in review" and do not describe it as working.
- Finance questions about the demo business and the bad quarter are in `docs/DEMO_SCRIPT.md` (on `main` via #72).
- Never answer with a number that is not on screen or in a file below.

---

## 1. Demo and pitch

### 1. "What does FAULTLINE do, in one sentence?"
**Say:** "It stress-tests a small business's cash against a real-world shock before the owner commits, using a
deterministic engine, and scores its own forecasts against the market on sealed historical questions."
**Backed by:** `docs/SPEC.md` §1–§2; `services/api/core/financials.py` (`simulate`); `services/api/core/evaluator.py`.
Real historical cases: `services/api/data/demo_cases/` (4 FOMC 2026 meetings, merged in #54).

### 2. "Which numbers on screen are real?"
**Say:** "Every datum carries a label. The business is SYNTHETIC: invented, and labeled that way. Cash paths are
SIMULATED by our engine. Real-case evidence and research sources are REAL HISTORICAL, dated, and shown only if public
by the cutoff."
**Backed by:** `AGENTS.md` §4 (labels); `apps/web/components/ProvenanceBadge.tsx`; `services/api/data/demo_business.json`
(`"provenance": "SYNTHETIC"`); `services/api/tests/test_financials.py::test_demo_business_fixture_loads_and_is_synthetic`.
Real historical cases: `services/api/data/demo_cases/` (#54); the one SYNTHETIC replay case is labeled so (#128).

### 3. "Is the cascade pre-recorded?"
**Say:** "No. Every preset or slider change calls the engine again, and the API returns the engine's result exactly.
A test checks that the response equals a direct engine call, number for number."
**Backed by:** `services/api/routes/simulate.py` (`POST /api/simulate`);
`services/api/tests/test_routes_simulate.py::test_result_and_deltas_equal_the_engine_exactly`.

### 4. "What happens if the local model crashes on stage?"
**Say:** "The screen says 'Local model unavailable', never a made-up answer. The script that records saved runs,
labeled RECORDED RUN with prompt and data hashes, is merged, but no recorded run is committed yet."
**Backed by:** `apps/web/components/ModelStatus.tsx`, `apps/web/components/HealthChip.tsx`;
`services/api/routes/health.py` (`model_ready`); `services/api/tests/test_agents_local_ollama.py::test_ollama_down_real_transport_closed_loopback_port`.
Recorded-run script: `scripts/record_runs.py`;
`services/api/tests/test_record_runs.py::test_every_case_and_variant_is_forecast_and_saved_before_any_reveal`.
`services/api/data/recorded_runs/` holds only its README: no recorded run is committed yet.

### 5. "Why a food retailer?"
**Say:** "Thin margins and weekly cash make shocks visible within weeks: a floating-rate loan, short supplier terms,
fast inventory. Everyone understands a grocer. And the same engine is not tied to it."
**Backed by:** `docs/MATH_MODEL.md` §10 (parameters and why). Second business in another industry:
`services/api/data/restaurant_business.json`, `docs/MATH_MODEL.md` §10b (#113).

### 6. "What isn't built yet?"
**Say:** "We show the gaps instead of hiding them. All six screens are merged, but no official recorded run or
scorecard is committed yet, so the benchmark says NOT AVAILABLE. Importing a real customer's books is future work."
**Backed by:** merged on `main`: REWIND and DECISION wired (#65), REVEAL (#64), the ACT/WAIT/HEDGE split view
(`apps/web/components/decision/SplitView.tsx`, #134), the optimizer and Protect payroll (`services/api/routes/optimize.py`,
#69, #127), the Live Explore search API (#73: `services/api/routes/explore.py`,
`services/api/tests/test_explore_separation.py`) and screen (#135: `apps/web/components/explore/ExploreScreen.tsx`),
the INTEGRITY panel (#93: `apps/web/components/integrity/IntegrityPanel.tsx`). Not there yet:
`services/api/data/recorded_runs/` holds only its README. Re-check this list on the day.

---

## 2. Investability

### 7. "Who pays for this?"
**Say:** "Owner-operators who manage weekly cash, fractional CFOs who serve several such businesses, and the advisors
who help them plan. Our pricing is a hypothesis to test, not a result."
**Backed by:** `docs/HACKATHON.md` (Investability). Pricing and unit economics: `docs/INVESTABILITY.md` §3 (labeled `ESTIMATE / HYPOTHESIS`, #99).

### 8. "Why not just use the market price?"
**Say:** "We do use it, as a baseline we must beat, and we label it price-derived, not truth. But a price isn't a
decision: FAULTLINE turns a probability into what it means for this business's cash."
**Backed by:** `docs/MATH_MODEL.md` §6 (market baseline) and §8 (forecast to decision); `services/api/core/decision.py`
(`evaluate_policies`); `services/api/markets/normalize.py` (`select_quote`, 24 h staleness).

### 9. "What's defensible here? Anyone can call an LLM."
**Say:** "The part that's hard to copy is the audit trail: sealed outcomes, point-in-time evidence, hashed snapshots,
and a save-before-reveal ledger. That lets anyone check a forecast was made blind."
**Backed by:** `services/api/core/temporal_gate.py`; `services/api/core/provenance.py`; `services/api/core/store.py`;
`services/api/tests/test_replay_seal.py`.

### 10. "Does it only work for one made-up business?"
**Say:** "The engine takes any business as typed inputs: stores, margins, payment terms, debt. The demo grocer is
SYNTHETIC, and a second SYNTHETIC business, a full-service restaurant, runs on the same engine."
**Backed by:** `services/api/core/financials.py` (`BusinessParams`); `docs/MATH_MODEL.md` §10. Second business:
`services/api/data/restaurant_business.json`, `docs/MATH_MODEL.md` §10b,
`services/api/tests/test_restaurant_business.py::test_section_10b_table_matches_fixture`.

### 11. "How would a real customer get their data in?"
**Say:** "Honestly, not yet. Today the business is a parameter file. Importing from accounting software is future work,
and we'd show it labeled, never guessed."
**Backed by:** `services/api/data/demo_business.json`; `services/api/routes/simulate.py` (`load_business`). No import code
exists on `main`.

### 12. "Has the model beaten the market?"
**Say:** "We don't claim that. With fewer than five scored cases the scorecard reads INSUFFICIENT DATA. We'd say
'better' only if a 95% confidence interval on the score difference sits entirely below zero."
**Backed by:** `docs/MATH_MODEL.md` §6; `services/api/core/evaluator.py` (`LABEL_INSUFFICIENT`, `NO_IMPROVEMENT`);
`services/api/tests/test_scoring.py::test_fewer_than_five_events_is_insufficient_data_but_lists_per_event`.

---

## 3. Product

### 13. "Is the AI doing the maths?"
**Say:** "No. Every cash number comes from typed Python functions; the same inputs always give the same output. The
model only reads evidence and gives a probability."
**Backed by:** `AGENTS.md` §4; `services/api/core/financials.py`; `services/api/tests/test_financials.py` (golden cases);
`services/api/core/decision.py`.

### 14. "How do you know the engine is right?"
**Say:** "Hand-checked golden cases in our math spec must match the engine exactly, and the code must follow the spec
formula by formula. An independent spreadsheet model of the bad quarter, built without the code, matches too."
**Backed by:** `docs/MATH_MODEL.md` §9; `services/api/tests/test_financials.py::test_golden_case_a_no_shock` and the
other §9 cases. Independent spreadsheet check: `services/api/tests/test_golden_independent.py::test_cash_matches_independent_model`
(golden file from `docs/finance/bad_quarter_independent.xlsx`, #112).

### 15. "How do you know the evidence was public at the cutoff?"
**Say:** "Every item carries the time it became public. The gate only passes items available at or before the cutoff,
and tests check the boundary. Unprovable dates are excluded."
**Backed by:** `services/api/core/temporal_gate.py`;
`services/api/tests/test_temporal_gate.py::test_evidence_after_as_of_is_rejected_and_boundary_is_included`,
`::test_every_included_item_satisfies_available_at_le_as_of`.

### 16. "What does the optimizer do, and what if nothing works?"
**Say:** "It picks the least harmful mix from a fixed list of actions that keeps cash above the floor every week. If
none does, it says NO FEASIBLE PLAN, and nothing overwrites that."
**Backed by:** `docs/MATH_MODEL.md` §4; `services/api/core/optimizer.py` (#69); `services/api/routes/optimize.py` and the
live switch in `apps/web/components/cascade/CascadeWorkbench.tsx` (#127);
`services/api/tests/test_routes_optimize.py::test_severe_drop_with_protect_payroll_is_no_feasible_plan_with_smallest_floor`.

### 17. "What does Tavily do, and what is it walled off from?"
**Say:** "Tavily powers Live Explore: current, cited news for a decision today. It never touches the blind replay. The
replay model gets only the gated evidence: no web, no tools."
**Backed by:** Live Explore search API (#73): `services/api/routes/explore.py`;
`services/api/tests/test_explore_separation.py::test_replay_modules_do_not_load_tavily_transitively`,
`::test_forged_evidence_from_tavily_is_refused_by_the_gate`. Live Explore screen (#135):
`apps/web/components/explore/ExploreScreen.tsx`. Replay model:
`services/api/tests/test_agents_local_ollama.py::test_request_carries_only_the_given_prompt_no_system_no_tools_no_date`.

### 18. "Does ACT/WAIT/HEDGE actually depend on the forecast?"
**Say:** "In the supply frame, yes: there's a break-even probability. In the rate and inflation frames, not yet, and
the screen says so. A fix is being built."
**Backed by:** `services/api/data/decision_frames.json` (#71: `forecast_sensitive` and `caveat`);
`services/api/tests/test_decision_frames.py::test_supply_disruption_break_even_probability` (p* = 2,000 / 16,320 =
0.1225), `::test_rate_and_cpi_frames_have_no_break_even`; the caveat is shown by
`apps/web/components/decision/SplitView.tsx`. Fix: **PENDING: #103**.

---

## 4. Societal impact

### 19. "What stops the AI from cutting payroll?"
**Say:** "The AI never chooses actions. With Protect payroll on, any plan that cuts payroll is rejected by a hard
check. And payroll is our costliest lever, at 5 per dollar cut. Protecting jobs is a hard limit in the maths."
**Backed by:** `services/api/tests/test_decision.py::test_protect_payroll_mode`; `docs/MATH_MODEL.md` §10 (`c_z` = 5.00
per $). In the optimizer: `services/api/tests/test_optimizer.py::test_protect_payroll_sets_every_payroll_cut_to_zero`.

### 20. "Does FAULTLINE trade, lend, or fire anyone?"
**Say:** "No. It never moves money, places orders or changes employment. The market adapters use public read-only
endpoints, with no accounts, wallets or orders. It proposes; people decide."
**Backed by:** `services/api/markets/README.md` ("Public, unauthenticated GET endpoints only. No credentials, wallets,
orders or trading code"); `docs/HACKATHON.md` (alignment).

### 21. "Who is actually helped?"
**Say:** "Small businesses without a full-time CFO, and their staff: seeing a cash crunch weeks ahead leaves time to
act without layoffs. We make no claim about measured impact yet."
**Backed by:** `docs/HACKATHON.md` (Societal impact). Cited impact brief: `docs/IMPACT.md` (#96).

### 22. "What if the owner follows your advice and the forecast is wrong?"
**Say:** "We show that up front. Each option is costed in both outcomes, and after the reveal we show the regret:
how much worse the choice was than the best one in hindsight."
**Backed by:** `services/api/core/decision.py` (`evaluate_policies`, `regret`); `docs/MATH_MODEL.md` §8. On the
DECISION screen: `apps/web/components/decision/SplitView.tsx` (#134).

### 23. "Could this push owners into harmful cuts?"
**Say:** "Every action has a stated harm cost, and cutting payroll is the costliest. The tool never executes anything.
It shows the trade-off and keeps cash above a stated floor."
**Backed by:** `docs/MATH_MODEL.md` §10 (disruption costs `c_y` … `c_z`); `services/api/core/financials.py` (`ActionPlan`
defaults are all "no action").

### 24. "Isn't using prediction markets just gambling?"
**Say:** "We only read public prices, as one input, labeled market-implied. We never place bets, and we use a price only
if it was recorded within 24 hours before the cutoff; otherwise it says NOT AVAILABLE."
**Backed by:** `services/api/markets/README.md`; `services/api/markets/normalize.py` (`select_quote`);
`services/api/tests/test_temporal_gate.py::test_only_future_quotes_means_market_not_available`.

---

## 5. AI alignment (+2)

### 25. "n is tiny, so what does this prove?"
**Say:** "On its own, almost nothing, and we say so. Under five cases: INSUFFICIENT DATA. Under thirty: a small-sample
warning. The rule was fixed before any outcome was seen."
**Backed by:** `docs/MATH_MODEL.md` §6; `services/api/core/evaluator.py` (small-sample caveat);
`services/api/tests/test_scoring.py` (n = 10 and n = 29 caveats,
`::test_bootstrap_defaults_are_pre_specified`). What n ≈ 15 can detect: `docs/MATH_MODEL.md` §6, "What n ≈ 15 can and can't tell us" (#100).

### 26. "Couldn't the model have memorised 2026?"
**Say:** "Every run carries a contamination flag from the model's published card. Llama 3.1's data ends December 2023,
so 2026 events are flagged unlikely, never 'none': going offline doesn't erase training."
**Backed by:** `services/api/agents/model_cards.py` (`contamination_flag`, Llama card);
`services/api/tests/test_agents_model_cards.py::test_llama_cutoff_is_december_2023`.

### 27. "Can the real answer leak into the model's input?"
**Say:** "We test for it. A planted 'future fact' sits in the sealed data, and a test checks it never reaches any
prompt. On screen, the INTEGRITY panel re-checks live that the sealed folder wasn't touched."
**Backed by:** `services/api/tests/test_replay_seal.py::test_canary_never_reaches_any_prompt_or_snapshot`;
`services/api/core/temporal_gate.py`; INTEGRITY panel (B.8 / D.3, #93): `apps/web/components/integrity/IntegrityPanel.tsx`,
`services/api/routes/integrity.py`,
`services/api/tests/test_routes_integrity.py::test_a_sealed_folder_read_during_the_report_flips_the_sealed_check`;
`docs/ALIGNMENT.md` §1.

### 28. "Could someone peek at the answer, then forecast?"
**Say:** "The store refuses to reveal any answer before the forecast is saved, and every forecast freezes a hash of the
exact case it saw. A reveal before the save raises an error."
**Backed by:** `services/api/tests/test_replay_seal.py::test_reveal_before_persist_raises_and_does_not_touch_sealed_dir`;
`services/api/core/store.py` (`case_sha256` column); `services/api/core/temporal_gate.py` (`case_sha256`). The INTEGRITY
panel shows these checks per run (#93):
`services/api/tests/test_routes_integrity.py::test_forecast_saved_after_a_reveal_flips_the_order_check`,
`::test_tampered_record_flips_the_hash_check`; `docs/ALIGNMENT.md` §1.

### 29. "Who checks the model's reasoning?"
**Say:** "A separate checker rejects any citation of evidence the model wasn't shown, and flags every sentence that
cites nothing for a human to look at. It lists problems; it never edits the answer."
**Backed by:** `services/api/agents/skeptic.py` (module docstring: error vs warning);
`services/api/tests/test_agents_skeptic.py::test_uncited_claim_flagged_not_rejected`; `docs/ALIGNMENT.md` §3
(scalable oversight). What the model could not see, per case and run: the INTEGRITY panel,
`apps/web/components/integrity/IntegrityPanel.tsx` (#93).

### 30. "What if the model just copies the market?"
**Say:** "The model can run two ways, with and without the market price, and each way is scored separately against the
market, so copying shows up. Synthetic test cases are never pooled with real ones."
**Backed by:** `services/api/core/store.py` (variants `agent_only` / `agent_plus_market`); `services/api/core/evaluator.py`
("synthetic and real historical cases must be scored separately").
