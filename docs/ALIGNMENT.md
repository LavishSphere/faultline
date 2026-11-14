# How FAULTLINE keeps its AI honest

*For judges. One page. Every claim points at the code that enforces it and the test that checks it. In the app,
the **INTEGRITY** panel (`GET /api/integrity`) recomputes these checks for the case and run on screen: on DECISION
(B.8) the selected case and the run just made, on REVEAL (D.3) the forecast being revealed. With nothing selected
the panel offers its own case and run picker. Case and run checks run on every request; the two code-level checks
are cached for up to 60 s. A check that cannot run shows NOT AVAILABLE, never a tick.*

FAULTLINE asks an AI for decisions under uncertainty, then grades it. Five design choices make sure the AI can
neither cheat the grading nor make a decision a human did not approve.

## 1. An honest evaluation harness: the AI cannot see the future or the answer
A "blind replay" rewinds to a real past decision point. The model gets only evidence that was public at that
moment. The real answer is sealed until the forecast has been saved with fingerprints (SHA-256 hashes).
- **Only one path to the prompt.** `EvidenceStore.get_as_of` drops anything published or first available after the
  cutoff, anything we cannot prove existed then, and any field whose name looks like an answer (outcome,
  resolution, result, settle, winner, final_price). The panel also searches the rendered prompt text for every
  withheld item and every dropped value.
  Code: `services/api/core/temporal_gate.py`. Tests: `tests/test_temporal_gate.py`; a secret "canary" string placed only
  in excluded data never reaches a prompt (`tests/test_replay_seal.py::test_canary_never_reaches_any_prompt_or_snapshot`).
- **Save before reveal.** The answer folder is read only by `OutcomeVault.reveal`, and only for a forecast already
  saved in an append-only log. Peeking first and predicting after is detected by log order and excluded.
  Code: `core/store.py`, `core/evaluator.py`. Tests: `test_reveal_before_persist_raises_and_does_not_touch_sealed_dir`,
  `test_peek_then_predict_is_excluded`, `test_cherry_picking_runs_is_impossible`.
- **No live web.** The replay modules do not import or name the Tavily web-search client (Live Explore). This rests
  on a static scan of imports, strings and names (run by the panel) plus PR #73's separation tests, which also
  import the replay modules and drive the routes under a tripwire. A static scan cannot see a name assembled at
  run time from variables. Tests: `test_import_scan_flips_when_a_replay_module_reaches_live_web_code`,
  `test_reference_scan_flags_each_known_evasion`.
- **The panel is checked against sabotage.** Breaking the gate's date filter, leaking an answer field or a withheld
  item into the prompt, disabling the stripping, reading the sealed folder (also through a symlink or a relative
  path), editing a saved record or saving after a reveal each flips that panel check to ✗
  (`tests/test_routes_integrity.py`). The sealed-folder monitor sees only reads made through Python in the API
  process, by path as resolved; a read relative to a directory handle (`dir_fd`) or through a hard link is not
  attributed.

## 2. Values as hard constraints, not prompts
"Protect payroll" is a rule in code, not an instruction an AI could talk its way around. Today the decision engine
marks any plan with a payroll cut infeasible in Protect-payroll mode (`core/decision.py`,
`tests/test_decision.py::test_protect_payroll_mode`). The recovery optimizer is merged (#69) with its live Protect
payroll switch (#127): Protect payroll is a hard bound in its maths (payroll cut ≤ 0;
`tests/test_optimizer.py::test_protect_payroll_sets_every_payroll_cut_to_zero`), and if no plan works without
cutting pay, the solver says **NO FEASIBLE PLAN** (`tests/test_routes_optimize.py`). The integrity panel probes it
with payroll cuts made free: with Protect payroll off it cuts pay, with it on it must cut none
(`test_payroll_check_flips_when_the_solver_cuts_payroll`). On 2026-11-14 `GET /api/integrity` returned
`payroll_hard_constraint: PASS`; read the panel, not this line.
**Humans stay in control:** the engine only proposes and evaluates; the codebase has no integration that moves
money, trades, lends, or changes anyone's job (SPEC §1.8; a design rule, reviewed per PR, not a runtime check).

## 3. Scalable oversight: a skeptic checks the AI, and code does the maths
The LLM never does authoritative arithmetic: cash flows, runway and payoffs come from typed Python
(`core/financials.py`, `tests/test_decision.py::test_payoffs_come_from_simulate`). Every model answer is validated
(`agents/provider.py`) and re-checked by an independent skeptic that rejects invented evidence ids or impossible
probabilities before anything is shown (`agents/skeptic.py`, `tests/test_agents_skeptic.py`).

## 4. Anti-sycophancy: the scorecard can say "no"
The benchmark compares the AI with the prediction market and a naive 50/50 forecast on the same cases. Under 5
cases it says **INSUFFICIENT DATA**; it says "better" only if a bootstrap confidence interval excludes zero,
otherwise **No improvement measured** (`core/evaluator.py`, `tests/test_scoring.py`). Scoring rules and the
random seed were fixed before any answer was seen (`test_scorecard_cannot_override_bootstrap_settings`).

## 5. Epistemic hygiene: label everything, invent nothing
Every number carries a provenance label (REAL HISTORICAL, SYNTHETIC, RECORDED RUN, SIMULATED, ILLUSTRATIVE).
Missing data is shown as NOT AVAILABLE, never as a plausible placeholder. If the local model is down the app says
so; it never substitutes a canned answer (`tests/test_agents_local_ollama.py::test_ollama_down_raises_model_unavailable_without_answer`).
Each model's training cutoff is recorded (`agents/model_cards.py`); cases the model may already know are flagged
"likely contaminated" and excluded from scoring. The panel checks that flag against the model card.

## Honest limits
- **Tamper-evident, not tamper-proof.** Edits to saved runs are detected by their hashes, but someone with write
  access to the database can rewrite rows and hashes together. Recorded runs committed to git are the stronger record.
- **Pretraining contamination.** Switching off the network does not erase what a model learned in training. We
  disclose it and exclude likely cases; we never call a replay "blind" on the strength of the gate alone.
- **In-process guarantees.** The isolation is enforced by Python code structure, tests and an audit hook inside the
  API process, not by operating-system permissions or a separate sandbox. A restart resets the panel's read counter,
  and the static scans cannot see names built at run time.
- **Curated dates are trusted.** The gate enforces the dates curators recorded; archive snapshots are the
  mitigation for pages revised later.

Details: `docs/EVALUATION_PROTOCOL.md` (§3 what is guaranteed, §4 what is not), `docs/SPEC.md` §1 and §5.
