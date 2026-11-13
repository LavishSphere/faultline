# FAULTLINE Evaluation Protocol (Blind Replay)

**Status:** Wave 2. The integrity core (issue #24: temporal gate, provenance hashes, SQLite prediction store,
sealed-outcome vault, scoring), the local model provider (#36) and the HTTP routes `GET /api/cases`,
`GET /api/cases/{case_id}/evidence`, `POST /api/replay/run` and `POST /api/replay/{prediction_id}/reveal`
(#44 part A, §9) exist. **Not built yet:** the benchmark compute/read routes and committed recorded runs (#44 part B). **Real cases:** none on `main` yet (issue #20), so any benchmark today must report `INSUFFICIENT DATA`.

Sources of truth: SPEC §3.1, §5, §6, §10 and MATH_MODEL §6, §7, §9. If this document and MATH_MODEL disagree,
MATH_MODEL wins and this document is the bug.

---

## 1. The question, and the honest claim

"Could an agent, with only information available on the historical date, have made a better forecast than
the market price at that date?"

The safe claim is: **an auditable backtesting system that measures whether combining research agents with
market probabilities adds signal.** We claim measured improvement only when §6 below says so, on a locked
case set, with `n`, baselines and a CI.

## 2. Data flow and boundaries

```
data/demo_cases/<event_id>.json ──► EvidenceStore.from_dir ──► get_as_of(case_id, as_of) ──► GatedSnapshot
   (case + candidate evidence +        (refuses any path in          (filters, selects quote,       │
    candidate market quotes)            the sealed directory)         projects, strips keys)       ▼
                                                                                    model_input(variant)
                                                                       prompt + snapshot JSON + both SHA-256
                                                                                             │
                                               (Wave 2: model provider, temperature 0, fixed seed)
                                                                                             ▼
                                         PredictionStore.save(prediction, model_input)   [SQLite, audit_log]
                                                                                             │
data/sealed_outcomes/<event_id>.json ─────────────► OutcomeVault.reveal(prediction_id) ──► RevealedOutcome
                                                                                             │
                                  build_scorecard(vault)  (population + baselines come from the store)
```

| Module | Reads | Never reads |
|---|---|---|
| `core/temporal_gate.py` | `data/demo_cases/*.json` | `data/sealed_outcomes/` (refused by name in any letter case and by inode; hard-linked case files refused) |
| `core/provenance.py` | nothing (pure functions) | any file |
| `core/store.py` | `services/api/var/predictions.sqlite3` | `data/sealed_outcomes/` |
| `core/evaluator.py` | the SQLite store, then `data/sealed_outcomes/<event_id>.json` inside `reveal()` only | — |

## 3. What is guaranteed (enforced by code, checked by tests)

| Guarantee | Where | Test |
|---|---|---|
| Evidence reaches a prompt only if `available_at <= as_of`, `published_at <= as_of`, same `event_id`, and `retrospective_unverified == False` (boundary inclusive) | `EvidenceStore.get_as_of` | `test_temporal_gate.py::test_evidence_after_as_of_is_rejected_and_boundary_is_included` and neighbours |
| A replay may only look *earlier* than the case cutoff (`as_of > case.as_of` raises); naive / date-only `as_of` raises (an ISO string must carry a time of day) | `get_as_of` | `test_as_of_after_case_cutoff_is_refused`, `test_naive_or_date_only_as_of_is_refused` |
| The pre-reveal case view lists only the `evidence_ids` the gate admits at that `as_of` (ids of excluded items are not exposed) | `get_as_of`, `public_case` | `test_public_case_lists_only_admissible_evidence_ids` |
| Market quote per (venue, market_id) = last quote with `as_of − 24h <= ts <= as_of` (`markets.normalize.select_quote`); none → market baseline `NOT AVAILABLE`, and the `agent_plus_market` variant raises `MarketNotAvailable` instead of running without a price | `get_as_of`, `GatedSnapshot.payload` | `test_stale_quote_means_market_not_available`, `test_quote_exactly_24h_old_is_still_usable` |
| Keys matching `models.OUTCOME_FIELD_PATTERN` are stripped from evidence and quotes; the only allowlisted key is the quote side marker `outcome == "YES"` at the top level of a quote projection | `strip_outcome_keys`, `_project_quote` | `test_strip_outcome_keys_recursive`, `test_market_outcome_yes_is_allowlisted_only_for_quotes` |
| A case file with an outcome-like top-level or case key (any letter case), or a quote with any `outcome` key (any letter case) other than exactly `"outcome": "YES"`, fails to load (`SealedDataError`), instead of being silently cleaned | `_load_case_file` | `test_case_file_with_outcome_section_is_refused`, `test_quote_file_with_non_yes_outcome_is_refused` |
| Prompts get **projections** only: post-cutoff curation metadata (`observed_at`, `collected_at`, archive capture URLs, API endpoint URLs, raw payload hashes) is dropped; no current date is in the prompt, only `as_of` | `_project_evidence`, `_project_quote`, `_render` | `test_prompt_projection_drops_post_cutoff_curation_metadata`, `test_prompt_has_as_of_but_no_current_date` |
| **Future-fact canary:** a `CANARY-<uuid>` placed only in excluded data (future / unverified / wrong-event evidence, an outcome-like key, a stale and a future quote, an archive URL, an API URL, curation notes, the sealed outcome file) never appears in any rendered prompt, snapshot JSON, snapshot repr or public case; a `VISIBLE-<uuid>` positive control in admissible evidence does appear | whole gate | `test_replay_seal.py::test_canary_never_reaches_any_prompt_or_snapshot` |
| The gate does not open or list anything in `data/sealed_outcomes/` (checked with a `sys.audit` hook, which also sees C-level opens). It refuses that directory by name in any letter case (`SEALED_OUTCOMES` on a case-insensitive file system), by `(st_dev, st_ino)` of every ancestor against the configured sealed directory, and through symlinks. It also refuses hard-linked case files (`st_nlink > 1`) | `_refuse_sealed`, `_refuse_linked_file` | `test_gate_never_reads_sealed_outcomes`, `test_from_dir_refuses_*` |
| Prompt-path modules (`temporal_gate`, `provenance`, `store`, `agents/*`) never import the evaluator | module structure | `test_prompt_path_modules_never_import_the_evaluator` |
| `GatedSnapshot` (built only by the store), `ModelInput` (only by `GatedSnapshot.model_input`) and `RevealedOutcome` (only by the vault) refuse direct construction and `dataclasses.replace` | construction guard in `__post_init__` | `test_gated_snapshot_cannot_be_*`, `test_save_requires_the_gate_model_input`, `test_revealed_outcome_cannot_be_forged` |
| `agent_only` and `agent_plus_market` are distinct: different prompts, different snapshot hashes, the variant is printed in the prompt, and `agent_only` contains no market price | `model_input` | `test_variants_are_distinct_and_labeled` |
| **Persist before reveal (per prediction):** `reveal(prediction_id)` raises `NotRevealable` (`NOT_REVEALABLE`) unless the prediction is in SQLite and its stored prompt, snapshot and forecast record (`record_sha256`) still match; it does not touch the sealed directory before that check; the event is taken from the stored prediction, not the caller; a reveal clock earlier than `persisted_at` is refused; each reveal is appended to `audit_log`. The configured sealed folder can only be revealed into the configured prediction store (`services/api/var/predictions.sqlite3`); a vault pairing it with any other store is refused, so a scratch store cannot read real outcomes without leaving a reveal in the official ledger | `OutcomeVault.reveal`, `OutcomeVault.__init__` | `test_reveal_before_persist_raises_and_does_not_touch_sealed_dir`, `test_reveal_refuses_when_stored_record_was_tampered`, `test_reveal_clock_before_persist_time_is_refused`, `test_configured_sealed_folder_only_reveals_into_the_configured_store` |
| **Forecast before outcome (per event):** a prediction counts only if it was persisted before the FIRST reveal of any prediction for the same event (any `as_of`, any variant). This is compared by position in the append-only `audit_log`, not by clock. `RevealedOutcome` carries `persist_seq`, `persisted_at`, `event_first_reveal_seq` and `event_first_revealed_at` | `build_scorecard`, `RevealedOutcome.persisted_before_outcome_revealed` | `test_peek_then_predict_is_excluded`, `test_peek_through_another_variant_is_excluded` |
| **No caller choice of runs or of the comparison:** `build_scorecard(vault, *, agent_variant, cases=None)` takes no contexts and no reveals. The population is every `(event_id, as_of)` with a persisted prediction of any variant (plus, if `cases` is given, every case at its cutoff, which can only add `no_persisted_prediction` rows). Each forecast's market baseline, contamination flag and synthetic flag are the ones the gate fixed in its `ModelInput` and the store persisted with the forecast, before any reveal. So after outcomes are known a caller cannot drop events, invent a market price or relabel losers as contaminated. More than one pre-reveal prediction for a key is excluded (`multiple_predictions`), never chosen | `build_scorecard`, `ModelInput`, `PredictionStore.save` | `test_cherry_picking_runs_is_impossible`, `test_duplicate_predictions_for_one_snapshot_are_excluded_not_chosen`, `test_post_hoc_context_manipulation_has_no_effect`, `test_scorecard_takes_no_caller_contexts` |
| **Market baseline rule (fixed, pre-reveal):** if the case's `market_quote_id` is `"<venue>:<market_id>"`, the baseline is that market's selected quote (absent or stale → NOT AVAILABLE, no fallback); otherwise the only selected quote when exactly one market has one; otherwise NOT AVAILABLE. Contamination and synthetic flags come from the case definition | `GatedSnapshot.market_baseline` | `test_market_baseline_follows_the_fixed_rule`, `test_single_market_is_the_baseline_and_context_comes_from_the_case` |
| **OFFICIAL requires the committed cases and a clean run.** The label `OFFICIAL: Computed from N historical cases` is given only if ALL hold, otherwise the label is `ILLUSTRATIVE: Historical cases, not an official run` and `official_blockers` lists every failed condition: (1) `cases` is `EvidenceStore.from_dir()` of the configured case directory; (2) the vault uses the configured sealed folder (hence the configured store); (3) no exclusion for an operator-controllable reason (`no_persisted_prediction`, `multiple_predictions`, `persisted_after_outcome_revealed`, `context_mismatch`) on any real or uncommitted case, so every committed real case at its cutoff has exactly one forecast and skipping, re-running or peeking at a loser cannot drop it; (4) no ignored post-reveal forecast on a real case; (5) every scored forecast was persisted before the FIRST reveal anywhere in the store (no cross-event leakage) | `build_scorecard` | `test_real_cases_without_committed_cases_are_not_official`, `test_in_memory_case_store_is_not_official`, `test_saving_only_winners_is_not_official`, `test_dropping_a_loser_by_rerun_or_peek_is_not_official`, `test_forecast_saved_after_another_events_reveal_is_not_official`, `test_synthetic_committed_cases_without_forecasts_do_not_block_official` |
| **Frozen case data:** every `ModelInput` carries `case_sha256` (canonical JSON of the validated case record: case, evidence, quotes). With `cases`, each remaining forecast is re-derived via `cases.get_as_of(event_id, as_of).model_input(variant)`; its prompt and snapshot hashes and every frozen context field (market baseline and ref, contamination, synthetic, `case_sha256`) must match, else the key is excluded `context_mismatch` (not revealed). Any edit to a committed case file after the run, even to an item the model never saw, or a forecast made from script-built case data, is caught | `build_scorecard`, `case_sha256` | `test_forecast_made_from_other_case_data_is_context_mismatch`, `test_editing_a_committed_case_after_the_run_is_context_mismatch`, `test_any_change_to_a_committed_case_file_after_the_run_is_context_mismatch`, `test_case_content_hash_is_frozen_into_the_model_input` |
| `save(prediction, model_input, final_prompt=...)` takes the gate's `ModelInput` and requires `event_id`, `as_of`, `variant`, the gated prompt hash (`gated_prompt_sha256`, or `prompt_sha256` on records without run-audit fields) and `snapshot_sha256` to match it (both are recomputed from its text); `prompt_sha256` and `transcript_sha256` must hash `final_prompt`, the exact message the model answered, which must be the gated prompt (`attempts == 1`) or the gated prompt, unchanged, followed by exactly the provider's repair instruction (`attempts == 2`: `agents.local_ollama.is_repair_instruction`, the fixed header and footer of `REPAIR_INSTRUCTION` with only `- ...` problem lines between them). `attempts` must be 1 or 2 (also a table CHECK constraint). It accepts only `agent_only` / `agent_plus_market`; the snapshot's quotes must agree with the variant; cited `evidence_ids` must be in the snapshot | `PredictionStore.save` | `test_save_rejects_*`, `test_save_requires_the_gate_model_input`, `test_save_refuses_a_model_prompt_that_does_not_match_its_hashes`, `test_attempts_other_than_1_or_2_are_refused`, `test_forged_repair_suffix_with_recomputed_hashes_is_caught_by_verify_and_reveal`, `test_repair_attempt_recomputes_every_hash` |
| Rows are append-only and edits are **evident**. Triggers abort UPDATE and DELETE on `predictions` and `audit_log`; an INSERT that reuses a prediction id (this blocks `INSERT OR REPLACE`); any `audit_log` row whose `seq` is chosen by the caller or is not greater than every existing `seq` (no backdating a persist, no early fake reveal); a reveal entry naming a prediction that does not exist; and a prediction whose `persist_seq` is not the newest `audit_log` entry and its own persist entry (so a low `seq` reserved before a reveal cannot be used for a forecast saved after it). `record_sha256` covers the whole forecast, its scoring context, `persisted_at` and `persist_seq`, so an edit made after dropping the triggers is caught by `verify` and refused by `reveal` | `core/store.py` | `test_predictions_and_audit_log_are_append_only`, `test_reveal_refuses_when_stored_record_was_tampered`, `test_reserved_low_seq_cannot_backdate_a_later_prediction`, `test_replacing_a_prediction_with_a_fresh_persist_entry_is_refused` |
| Scoring matches MATH_MODEL §9 fixtures exactly; bootstrap is deterministic for a seed; B and the seed cannot be overridden through `build_scorecard`; display rules of MATH_MODEL §6 (caveat at n = 29, none at n = 30) | `core/evaluator.py` | `test_scoring.py` |

The guarantees above were also checked by mutation. Disabling each check makes at least one test fail. That
covers the date, unverified and wrong-event filters, the staleness window, key stripping, metadata
projection, every hash check, the per-event reveal order, `multiple_predictions`, case-insensitive and inode
sealed-dir refusal, hard links, the append-only and seq triggers, the persisted scoring context, the market baseline rule, the vault-to-store binding, the as_of format rule, every OFFICIAL condition, the case content hash, the committed `market_quote_id` checks, the CI rule, the n < 5 and n < 30 rules, ε, the 0.5
tie rule, B and the bootstrap pairing.

## 4. What is NOT guaranteed

- **Pretraining contamination.** Disabling the network does not remove what a model learned in training.
  A model trained after an event may already know the answer, so a replay is never called "blind" on the
  strength of the gate alone. Every case carries `contamination_flag` (`unknown` / `likely` / `unlikely`,
  never "none"); `likely` cases are excluded from scoring with reason `contamination_likely`. Prefer events
  after the model's stated training cutoff (the default `llama3.1:8b` states a December 2023 knowledge
  cutoff on Meta's model card; record the card for any other model). Name anonymization does not remove
  contamination either.
- **Correctness of curated dates.** The gate trusts `available_at` and `retrospective_unverified` as curated.
  If a page was revised after `as_of` and the curator did not flag it, revised text can pass. Archive
  snapshots are the mitigation (issue #20 / `docs/DATA_PROVENANCE.md`).
- **`content_sha256` is not recomputed** by the gate (its exact input bytes are a curation choice); the
  snapshot hash covers the text actually given to the model.
- **OS-level isolation.** The sealed directory is protected by code structure, path checks and tests, not
  by file permissions or a separate process. Anyone with shell access can read it. The gate's inode check
  knows only the configured sealed folder; another sealed folder (e.g. a test fixture) is refused by name
  only. Likewise the vault-to-store binding applies to the configured sealed folder: a vault over some other
  folder (tests, a copied folder) can be paired with any store. **The binding is a speed bump, not a
  control:** changing `FAULTLINE_DATA_DIR` at runtime, or copying or renaming the data directory, lets a scratch
  store read outcomes without a trace in the official ledger. What it does guarantee is narrower: a scorecard is
  OFFICIAL only on the configured folder and store, and only if no scored forecast was saved after any reveal
  recorded in that store. Peeks made elsewhere are not visible to it. Network egress for the
  replay process is not enforced in Wave 1 (the Wave 2 provider must take no tools and no retrieval).
- **Tamper-proof storage.** The store is tamper-*evident* only. Triggers and `record_sha256` catch edits
  that do not also recompute the hashes, but someone with write access to the SQLite file can drop the
  triggers and rewrite rows, the audit log and the hashes together. Without dropping triggers, rows can only be
  appended, with SQLite-assigned increasing `seq`, which never makes a forecast look earlier than it was.
  Committed recorded runs and their hashes in git are the stronger record.
- **Curator levers (governance, not code).** Whoever writes the case files chooses the events, evidence,
  `market_quote_id` and `contamination_flag`. These choices are protected by process: case files are committed
  and PR-reviewed BEFORE any official run, and frozen for it (`case_sha256` in every forecast; any later edit
  is `context_mismatch` and blocks OFFICIAL). Every published scorecard includes the exclusions by reason with
  event ids and the `official_blockers`. At load, a committed case whose `market_quote_id` names no market in
  the file, or that has quotes for 2+ markets without one, is refused.
- **Contamination flags are hand-set.** TODO (follow-up now that PR #40 is merged): derive the case's
  `contamination_flag` from `agents.model_cards.contamination_flag(model, event_resolved_at)` (model training
  cutoff vs event date) when the forecast is made, instead of curating it by hand.
- **Pre-reveal data integrity.** The scoring context is fixed when the forecast is saved, before any reveal.
  If the case data itself was wrong at that time (a bad quote, a wrong contamination flag), it is scored as
  recorded. Fix the data, re-run the forecasts and record the re-run; never edit stored context.
- **Private-API bypass.** The construction guards stop direct calls and `dataclasses.replace`, but Python
  cannot stop code that sets private module state or calls `object.__setattr__`. `save` recomputes hashes from
  the model input's text, so a tampered object cannot change what is stored without the hashes changing too.
- **Semantic leaks in curated text.** The gate filters by dates and keys. It cannot tell that a case title
  or an evidence text written after the fact states the result. Curators and reviewers must check this.
- **Market prices are not true probabilities:** "market-implied probability (price-derived; affected by
  fees, spread, liquidity)". A quote may be thin or one-sided; the gate only enforces time and staleness.
- **The canary proves the tested paths.** New code paths to a prompt must route through `GatedSnapshot`
  and get their own canary coverage.
- **The sealed outcome file is trusted** as the settlement record; its `source_url` must be checked by a
  human reviewer.

## 5. Hash definitions

- **Canonical JSON:** keys sorted, separators `,` and `:` (no whitespace), UTF-8 text with non-ASCII kept
  literally, NaN/Infinity refused, only plain JSON types (timestamps are written as ISO-8601 UTC `...Z`
  strings before hashing).
- **`snapshot_sha256`** = SHA-256 (hex) of the canonical JSON of exactly
  `{"evidence": [...], "market_quotes": [...]}`, the projected items given to the model for that variant.
  `market_quotes` is `[]` for `agent_only`.
- **`prompt_sha256`** = SHA-256 (hex), UTF-8, of the exact message the model answered on the attempt that
  validated (#44): the gated prompt itself when `attempts == 1`; the gated prompt, unchanged, followed by
  exactly `agents.local_ollama.repair_instruction(problems)` when `attempts == 2` (the fixed header and footer of
  `REPAIR_INSTRUCTION`, only `- <problem>` lines between them; any other suffix, and any other `attempts` value,
  is refused by `save` and flagged by `verify`). **`gated_prompt_sha256`** = SHA-256 of the gate's
  rendered prompt (`ModelInput.prompt_sha256`). **`transcript_sha256`** = SHA-256 of the canonical JSON of the
  chat messages of that call (`[{"role": "user", "content": <that message>}]`). Records saved without a model
  provider (core tests) have no run-audit fields and their model prompt is the gated prompt.
- **`record_sha256`** = SHA-256 (hex) of the canonical JSON of
  `{"prediction": <Prediction as JSON, timestamps in UTC>, "context": {"market_baseline_p_yes",
  "market_baseline_ref", "contamination_flag", "synthetic", "case_sha256"}, "persisted_at": <ISO UTC>, "persist_seq": <int>}`.
  The prediction includes `prompt_sha256` and `snapshot_sha256`, so this one hash covers the forecast, both
  input hashes and the pre-reveal scoring context.
- Stored with each prediction: model id, Ollama digest when available, variant, temperature, seed,
  `recorded_at` (caller), `persisted_at` (store clock), `persist_seq` (position in `audit_log`), the scoring
  context from the `ModelInput` (never shown to the model), the gated prompt text, the exact message the model
  answered, the snapshot JSON, and the run's `attempts`, `num_ctx` and `num_predict`.
  `PredictionStore.verify(prediction_id)` recomputes every hash (prompt, gated prompt, transcript, snapshot,
  record), checks that a repair prompt is the gated prompt plus exactly the provider's repair instruction, and
  checks the `audit_log` persist entry.
- Prompt template version: `replay-v1` (printed in every prompt). Changing the template changes every
  `prompt_sha256`, which is intended.

## 6. Scoring (MATH_MODEL §6)

- Brier $(p-y)^2$; log loss with $\tilde p = \min(\max(p, 10^{-6}), 1 - 10^{-6})$; accuracy at the
  pre-specified threshold 0.5 (secondary; $p = 0.5$ counts as NO).
- Forecasters on identical `(event_id, as_of)` pairs: naive $p = 0.5$, market-only (the selected quote),
  and one agent variant per scorecard (`agent_only` or `agent_plus_market`, scored separately).
- Multiple horizons of one event are averaged within the event first; **events are the unit**.
- Uncertainty: paired bootstrap over events, $B = 10{,}000$, seed `20261115` (fixed before any reveal),
  95% percentile CI of $\overline{\text{Brier}}_{agent} - \overline{\text{Brier}}_{market}$. Algorithm:
  `idx = numpy.random.default_rng(seed).integers(0, n, size=(B, n))`, mean of the paired differences per
  resample, numpy linear-interpolation percentiles 2.5 and 97.5.
- **Which predictions count.** `build_scorecard(vault, *, agent_variant=..., cases=None)` takes the vault,
  not contexts or reveals. The keys are every `(event_id, as_of)` with a persisted prediction of any variant,
  plus (with `cases`) every case at its cutoff. For each key it reads every persisted prediction for
  `(event_id, as_of, agent_variant)` from the store. Let $s_0$ be the `audit_log` position of the first reveal
  of any prediction for that event, read once before scoring starts. The market baseline, contamination flag
  and synthetic flag used below are the persisted pre-reveal context of the chosen prediction. Each key is then
  decided in this order:
  1. No persisted prediction → excluded, `no_persisted_prediction`.
  2. Predictions persisted at a position $> s_0$ are listed in `ignored_predictions` with reason
     `persisted_after_outcome_revealed`. If none persisted before $s_0$ remain, the key is excluded with
     that reason.
  3. More than one remaining prediction → excluded, `multiple_predictions` (ids listed; none is chosen).
  3a. With `cases`: the forecast's input cannot be re-derived from `cases` with identical hashes and frozen
     context (incl. `case_sha256`) → excluded, `context_mismatch` (not revealed).
  4. `contamination_flag == "likely"` → excluded, `contamination_likely`.
  5. No market quote → excluded, `market_not_available`.
  6. Otherwise the single prediction is revealed through the vault (the reveal is logged) and scored. A
     missing sealed file → excluded, `sealed_outcome_not_available`.

  A persisted but not yet revealed prediction is revealed and scored here. It is never reported as
  `no_persisted_prediction`. Excluded keys are not revealed by scoring.
- Exclusions are reported by reason, with event id, `as_of` and prediction ids.
- B and the seed are fixed: `build_scorecard` has no parameter for them, and the scorecard records both.
  Only `agent_only` and `agent_plus_market` can be scored. `hosted_comparator` is refused until its
  "hosted-model comparison, not air-gapped" path exists.
- Synthetic and real historical cases are never pooled (refused). The context's `synthetic` flag must
  agree with the sealed file's provenance.

**Display rules:**

| Condition | Label | Verdict |
|---|---|---|
| $n < 5$ | `INSUFFICIENT DATA: No valid comparison` | `INSUFFICIENT DATA` (per-event scores still listed; no means, no CI) |
| $5 \le n < 30$ | as below, plus caveat `small sample: n = N events (< 30)` | as below |
| synthetic cases | `ILLUSTRATIVE: Synthetic demo fixtures` | as below |
| real historical cases, all OFFICIAL conditions met (§3) | `OFFICIAL: Computed from N historical cases` | as below |
| real historical cases, any OFFICIAL condition failed | `ILLUSTRATIVE: Historical cases, not an official run (see official_blockers)` | as below |
| CI upper bound $< 0$ | | `agent better than market` |
| otherwise (including a lower mean whose CI reaches 0) | | `No improvement measured` |

## 7. File formats

`services/api/data/demo_cases/<event_id>.json` (agent-readable; must contain **no** outcome):

```json
{
  "case": { "...": "models.ReplayCase fields (resolution_rule is the rule text, never the result)" },
  "evidence": [ { "...": "models.EvidenceItem fields" } ],
  "market_quotes": [ { "...": "markets.base.NormalizedQuote fields, outcome = \"YES\"" } ],
  "curation_notes": "optional; any other non-outcome key is ignored and never reaches a prompt"
}
```

If a case has quotes for more than one market, set `case.market_quote_id` to `"<venue>:<market_id>"` of the
benchmark market (e.g. `"kalshi:KXFEDDECISION-26JUL-H0"`). Without it the market baseline is NOT AVAILABLE
for that case; a committed file with 2+ markets and no `market_quote_id`, or one naming a market not in the
file, is refused at load. Case files must not be hard links.

`services/api/data/sealed_outcomes/<event_id>.json` (read only by `OutcomeVault.reveal`):

```json
{
  "event_id": "<event_id>",
  "outcome": "YES or NO",
  "resolved_at": "ISO-8601 with offset, optional",
  "source_url": "settlement source",
  "provenance": "REAL_HISTORICAL or SYNTHETIC",
  "notes": "optional"
}
```

## 8. Pre-registration rules

- The case selection rule is written down before results are seen (`docs/CASES.md`, issue #20), with a
  chronological holdout. No prompt or template change after looking at outcomes; a template change gets a
  new version and a fresh run on all cases.
- Threshold 0.5, ε = 1e-6, B = 10,000 and the bootstrap seed are fixed in code before any reveal.
- **Official run procedure:** (1) merge the reviewed case files and sealed outcomes; (2) save exactly one
  forecast per committed case and variant with `EvidenceStore.from_dir()` and the configured store, revealing
  nothing; (3) call `build_scorecard(vault, cases=EvidenceStore.from_dir())` once, which reveals and scores;
  (4) publish the scorecard with its exclusions and `official_blockers`.
- Recorded demo runs are labeled `RECORDED RUN` and carry model id, digest, temperature, seed and both hashes.

---

## 9. HTTP routes (#44 part A)

| Route | Boundary | What it does |
|---|---|---|
| `GET /api/cases` | pre-reveal | `EvidenceStore.public_case` per case file: `evidence_ids` lists only items the gate admits at the cutoff |
| `GET /api/cases/{case_id}/evidence?as_of=` | pre-reveal | `EvidenceStore.get_as_of`: the prompt projection of admitted evidence, the selected as-of quote per market, the market baseline at the cutoff (or NOT AVAILABLE), exclusion counts by reason (no ids). `as_of` defaults to, and may not be later than, the case cutoff (422) |
| `POST /api/replay/run` `{case_id, variant}` | pre-reveal; admin-only in public mode | gate, provider, skeptic, then `PredictionStore.save(..., final_prompt=...)`; nothing is saved on any provider error or skeptic rejection. A run saved after a reveal is not refused but flagged from `audit_log`: `event_first_reveal_seq` / `persisted_after_event_reveal` (this event) and `store_first_reveal_seq` / `persisted_after_any_reveal` (anywhere), plus an `audit_note` |
| `POST /api/replay/{prediction_id}/reveal` | post-reveal; admin-only in public mode | `OutcomeVault.reveal`, per-prediction Brier / log loss / accuracy at 0.5, naive and market baselines from the stored pre-reveal context |

**Public mode:** run and reveal both change state, so with `FAULTLINE_MODE` anything but unset/`local` they need
`Authorization: Bearer <FAULTLINE_ADMIN_TOKEN>` (at least 32 characters), checked by a route dependency so it holds
with or without the edge middleware of #28. No bearer token: 401; wrong or unconfigured token: 403; body
`{code: "ADMIN_TOKEN_REQUIRED", message}`. An early public reveal would otherwise mark the event revealed and
disqualify every later admin run on it (`tests/test_routes_replay_admin.py`). The case routes stay public.

Both pre-reveal case routes run a strict pre-scan before the gate loads anything: a case file with an
outcome-like key anywhere (except `case.resolution_rule` and a quote's `outcome: "YES"`) is refused, not
stripped; top-level keys are allow-listed; the file name must be `<event_id>.json`; files resolving outside
`demo_cases/` are refused unread. `tests/test_routes_replay.py` requires every `/api/cases*` and `/api/replay*`
route to be classified pre- or post-reveal, walks every pre-reveal response schema and body (before and after a
reveal) for outcome keys, the canary and sealed values, and checks that no pre-reveal request opens a file under
`sealed_outcomes/`.
