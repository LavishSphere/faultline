# Release checklist (SPEC §10)

Status of every SPEC §10 item, with the evidence for it. **DONE** means a named test or file covers the item and the
backend suite passed when this file was last updated. It does not mean someone re-checked it by hand.
**PARTIAL** means some of it is covered and the gap is written down. **PENDING** means it is not done yet, and the
issue that tracks it is named. Test paths are relative to `services/api/tests/` unless they say otherwise.

Run `make preflight ARGS=--tests` to re-check the environment, data, recorded runs and tests in one go.

## Tests that must pass before shipping

| SPEC §10 item | Status | Evidence |
|---|---|---|
| Replay rejects evidence published after `as_of` | DONE | `test_temporal_gate.py::test_evidence_after_as_of_is_rejected_and_boundary_is_included`, `::test_as_of_after_case_cutoff_is_refused` |
| A future-fact canary never appears in model context | DONE | `test_replay_seal.py::test_canary_never_reaches_any_prompt_or_snapshot` |
| Resolved outcome not present in any pre-reveal endpoint or prompt | DONE | `test_replay_seal.py::test_repo_cases_have_no_outcome_keys_or_future_evidence`, `test_routes_cases.py`, `test_routes_replay_evidence.py`, `test_routes_integrity.py` |
| Invalid/stale market quotes excluded, not silently reused | DONE | `test_temporal_gate.py::test_stale_quote_means_market_not_available`, `::test_only_future_quotes_means_market_not_available`, `test_routes_replay.py::test_agent_plus_market_without_fresh_quote_is_insufficient_data` |
| Quote normalization handles cents, decimals and missing data | DONE | `test_market_normalization.py::test_kalshi_cents_63_to_0_63`, `::test_polymarket_decimal_string_and_float`, `::test_missing_price_is_none` |
| Brier score and log loss pass known numeric fixtures | DONE | `test_scoring.py` (MATH_MODEL §9 fixtures, e.g. `::test_log_loss_clamps_with_epsilon_1e_6`) |
| Forecast persisted before outcome reveal | DONE | `test_replay_seal.py::test_reveal_before_persist_raises_and_does_not_touch_sealed_dir`, `::test_reveal_clock_before_persist_time_is_refused` |
| Model settings and dataset hashes appear in audit output | DONE | `test_routes_replay_audit.py::test_run_audit_fields_are_stored_and_verified`, `::test_edits_to_the_run_audit_record_are_evident` |
| Agent-only and agent+market variants distinct and labeled | DONE | `test_routes_replay.py::test_agent_plus_market_sees_only_the_as_of_quote_and_is_distinct` |
| Cash-flow recurrence matches hand-calculated golden cases | DONE | `test_financials.py::test_golden_case_a_no_shock`, `::test_golden_case_b_demand_drop_week_2_only`, `test_golden_independent.py` |
| Payroll protection enforced by the optimizer, not a string instruction | DONE | `test_optimizer.py::test_protect_payroll_sets_every_payroll_cut_to_zero`, `::test_severe_drop_feasible_only_with_payroll_cuts` |
| Solver reports infeasible constraints accurately | DONE | `test_optimizer.py::test_infeasible_without_any_floor_reports_not_available` |
| VC documents dated after `as_of` excluded | DONE | `test_routes_research.py::test_sequoia_excluded_before_its_publication_and_bessemer_included`, `test_research_lenses.py::test_prompt_projection_has_no_date_after_as_of_at_every_boundary` |
| Public app works without personal accounts or secret API keys | PARTIAL | `test_health.py` (optional keys reported as booleans only); `.env.example` (every variable optional). Not yet checked on a clean machine with no keys, which is part of the offline check, **PENDING #67** |
| All demo data marked real historical / synthetic / recorded inference | PARTIAL | `test_contracts.py::test_provenance_enum_exact_members_and_labels`, `test_synthetic_venue.py`, `test_financials.py::test_provenance_only_fictional_labels`. The whole-app final honesty audit (every displayed number traced to a labeled API field) is **PENDING #57** |
| An absent open-weight model gives clear fallback messaging, not fake inference | DONE | `test_agents_local_ollama.py::test_ollama_down_raises_model_unavailable_without_answer`, `test_health.py::test_health_ollama_down_real_transport_closed_port`; `scripts/preflight.py` prints the fallback as a WARN |
| Every scenario slider produces a correct visible update | PARTIAL | `apps/web/components/cascade/scenarioInputs.test.mjs` (each input maps to exactly its own field); `apps/web/e2e/smoke.spec.ts` checks one slider move end to end. Not every slider is checked in the browser |
| Running the complete demo needs no unrestricted internet dependency | PENDING #67 | Offline golden-path check (network disabled after install) has not been run yet |

## Definition of done

| Item | Status | Evidence |
|---|---|---|
| README gives exact install/run commands and configuration | DONE | `README.md` "Run locally" and "Release demo" sections; `.env.example` |
| One-command local launch and preflight | DONE | `make demo`, `make demo-scratch`, `make preflight` (`scripts/preflight.py`, `scripts/demo_api.py`) |
| `pytest` and TypeScript type checking pass; no hardcoded success paths | DONE | CI on every PR (`make test`, `make check`) |
| At least one genuine timestamp-valid historical event scored end to end | PENDING #67 | Real cases are committed (`services/api/data/demo_cases/`, sealed outcomes present, preflight hashes them). The official RECORDED RUN (`scripts/record_runs.py`) has not been made, so `services/api/data/recorded_runs/` is empty and the benchmark shows INSUFFICIENT DATA |
| Demo runs with synthetic business data and sourced snapshots, external APIs disabled | PENDING #67 | Same offline check as above |
| All four VC lenses show at least one real source with date and URL | DONE | `services/api/data/research_lenses.json`, `test_research_lenses.py` |
| Scope and caveats described in `docs/EVALUATION_PROTOCOL.md` | DONE | `docs/EVALUATION_PROTOCOL.md` |

## Release-day order (lead policy, #57)

1. `make preflight ARGS=--tests`: no FAIL lines.
2. The lead makes the official RECORDED RUN with `scripts/record_runs.py` against the **official** store, commits it,
   and preflight shows `recorded run ... PASS` (**PENDING #67**).
3. Every stage or practice demo after that runs with `make demo-scratch` (it sets the `FAULTLINE_PREDICTIONS_DB`
   setting to `services/api/var/scratch/predictions.sqlite3`; #130). Preflight run as
   `FAULTLINE_PREDICTIONS_DB=<scratch path> make preflight` (or `FAULTLINE_DEMO_STORE=<scratch path>`) should print
   `prediction store: scratch ...` as PASS. With the setting unset (the official store) it prints a WARN.
