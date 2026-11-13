# FAULTLINE Evaluation Protocol (Blind Replay)

**Status:** Wave 1 (issue #24). The integrity core exists: temporal gate, provenance hashes, SQLite prediction
store, sealed-outcome vault, scoring. **Not built yet:** the model provider and the replay run/reveal routes
(Wave 2). **Real cases:** none on `main` yet (issue #20), so any benchmark today must report `INSUFFICIENT DATA`.

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
                                         PredictionStore.save(prediction, prompt, snapshot_json)  [SQLite]
                                                                                             │
data/sealed_outcomes/<event_id>.json ─────────────► OutcomeVault.reveal(prediction_id) ──► RevealedOutcome
                                                                                             │
                                                                               build_scorecard(...)
```

| Module | Reads | Never reads |
|---|---|---|
| `core/temporal_gate.py` | `data/demo_cases/*.json` | `data/sealed_outcomes/` (refused by path check) |
| `core/provenance.py` | nothing (pure functions) | any file |
| `core/store.py` | `services/api/var/predictions.sqlite3` | `data/sealed_outcomes/` |
| `core/evaluator.py` | the SQLite store, then `data/sealed_outcomes/<event_id>.json` inside `reveal()` only | — |

## 3. What is guaranteed (enforced by code, checked by tests)

| Guarantee | Where | Test |
|---|---|---|
| Evidence reaches a prompt only if `available_at <= as_of`, `published_at <= as_of`, same `event_id`, and `retrospective_unverified == False` (boundary inclusive) | `EvidenceStore.get_as_of` | `test_temporal_gate.py::test_evidence_after_as_of_is_rejected_and_boundary_is_included` and neighbours |
| A replay may only look *earlier* than the case cutoff (`as_of > case.as_of` raises); naive / date-only `as_of` raises | `get_as_of` | `test_as_of_after_case_cutoff_is_refused`, `test_naive_or_date_only_as_of_is_refused` |
| Market quote per (venue, market_id) = last quote with `as_of − 24h <= ts <= as_of` (`markets.normalize.select_quote`); none → market baseline `NOT AVAILABLE`, and the `agent_plus_market` variant raises `MarketNotAvailable` instead of running without a price | `get_as_of`, `GatedSnapshot.payload` | `test_stale_quote_means_market_not_available`, `test_quote_exactly_24h_old_is_still_usable` |
| Keys matching `models.OUTCOME_FIELD_PATTERN` are stripped from evidence and quotes; the only allowlisted key is the quote side marker `outcome == "YES"` at the top level of a quote projection | `strip_outcome_keys`, `_project_quote` | `test_strip_outcome_keys_recursive`, `test_market_outcome_yes_is_allowlisted_only_for_quotes` |
| A case file with an outcome-like top-level or case key, or a quote whose `outcome` is not `"YES"`, fails to load (`SealedDataError`), instead of being silently cleaned | `_load_case_file` | `test_case_file_with_outcome_section_is_refused` and neighbours |
| Prompts get **projections** only: post-cutoff curation metadata (`observed_at`, `collected_at`, archive capture URLs, API endpoint URLs, raw payload hashes) is dropped; no current date is in the prompt, only `as_of` | `_project_evidence`, `_project_quote`, `_render` | `test_prompt_projection_drops_post_cutoff_curation_metadata`, `test_prompt_has_as_of_but_no_current_date` |
| **Future-fact canary:** a `CANARY-<uuid>` placed only in excluded data (future / unverified / wrong-event evidence, an outcome-like key, a stale and a future quote, an archive URL, an API URL, curation notes, the sealed outcome file) never appears in any rendered prompt, snapshot JSON, snapshot repr or public case; a `VISIBLE-<uuid>` positive control in admissible evidence does appear | whole gate | `test_replay_seal.py::test_canary_never_reaches_any_prompt_or_snapshot` |
| The gate does not open or list anything in `data/sealed_outcomes/` (checked with a `sys.audit` hook, which also sees C-level opens), and refuses that directory and symlinks into it | `_refuse_sealed` | `test_gate_never_reads_sealed_outcomes`, `test_from_dir_refuses_*` |
| Prompt-path modules (`temporal_gate`, `provenance`, `store`, `agents/*`) never import the evaluator | module structure | `test_prompt_path_modules_never_import_the_evaluator` |
| A `GatedSnapshot` can only be built by the store; `render_prompt` accepts nothing else. A `RevealedOutcome` can only be built by the vault; `build_scorecard` accepts nothing else | private construction tokens | `test_gated_snapshot_cannot_be_built_outside_the_store`, `test_revealed_outcome_cannot_be_forged`, `test_scorecard_requires_vault_reveals` |
| `agent_only` and `agent_plus_market` are distinct: different prompts, different snapshot hashes, the variant is printed in the prompt, and `agent_only` contains no market price | `model_input` | `test_variants_are_distinct_and_labeled` |
| **Persist before reveal:** `reveal(prediction_id)` raises `NotRevealable` (`NOT_REVEALABLE`) unless the prediction is in SQLite and its stored prompt and snapshot still hash to the stored values; it does not touch the sealed directory before that check; the event is taken from the stored prediction, not the caller; each reveal is logged with a time not earlier than `persisted_at` | `OutcomeVault.reveal` | `test_reveal_before_persist_raises_and_does_not_touch_sealed_dir`, `test_reveal_refuses_when_stored_audit_was_tampered` |
| `save` recomputes both hashes and refuses mismatches; the snapshot must be canonical; variant must match the snapshot (no quote for `agent_only`, at least one for `agent_plus_market`); cited `evidence_ids` must be in the snapshot; rows are append-only (SQLite triggers abort UPDATE/DELETE; duplicate ids raise) | `PredictionStore.save` | `test_save_rejects_*`, `test_predictions_are_append_only` |
| Scoring matches MATH_MODEL §9 fixtures exactly; bootstrap is deterministic for a seed; display rules of MATH_MODEL §6 | `core/evaluator.py` | `test_scoring.py` |

The guarantees above were also checked by mutation: disabling each check (date filter, unverified filter,
key stripping, metadata projection, hash checks, the CI rule, the n < 5 rule, ε, the 0.5 tie rule) makes at
least one test fail.

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
  by file permissions or a separate process. Anyone with shell access can read it. Network egress for the
  replay process is not enforced in Wave 1 (the Wave 2 provider must take no tools and no retrieval).
- **Tamper-proof storage.** SQLite triggers and hashes make edits *evident* (reveal refuses a row whose
  text no longer matches its hashes), not impossible: someone with file access can rewrite a row and its
  hashes together. Committed recorded runs and their hashes in git are the stronger record.
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
- **`prompt_sha256`** = SHA-256 (hex) of the final rendered prompt string, UTF-8.
- Stored with each prediction: model id, Ollama digest when available, variant, temperature, seed,
  `recorded_at` (caller), `persisted_at` (store clock), the exact prompt text and snapshot JSON.
  `PredictionStore.verify(prediction_id)` recomputes both hashes.
- Prompt template version: `replay-v1` (printed in every prompt). Changing the template changes every
  `prompt_sha256`, which is intended.

## 6. Scoring (MATH_MODEL §6)

- Brier $(p-y)^2$; log loss with $\tilde p = \min(\max(p, 10^{-6}), 1 - 10^{-6})$; accuracy at the
  pre-specified threshold 0.5 (secondary; $p = 0.5$ counts as NO).
- Forecasters on identical `(event_id, as_of)` pairs: naive $p = 0.5$, market-only (the selected quote),
  and one agent variant per scorecard (`agent_only` or `agent_plus_market`, scored separately). The optional
  hosted comparator is not implemented.
- Multiple horizons of one event are averaged within the event first; **events are the unit**.
- Uncertainty: paired bootstrap over events, $B = 10{,}000$, seed `20261115` (fixed before any reveal),
  95% percentile CI of $\overline{\text{Brier}}_{agent} - \overline{\text{Brier}}_{market}$. Algorithm:
  `idx = numpy.random.default_rng(seed).integers(0, n, size=(B, n))`, mean of the paired differences per
  resample, numpy linear-interpolation percentiles 2.5 and 97.5.
- Exclusions, reported by reason with the event ids: `no_persisted_prediction`, `contamination_likely`,
  `market_not_available`. Two persisted predictions for the same `(event_id, as_of, variant)` are refused
  rather than one being picked.
- Synthetic and real historical cases are never pooled (refused).

**Display rules:**

| Condition | Label | Verdict |
|---|---|---|
| $n < 5$ | `INSUFFICIENT DATA: No valid comparison` | `INSUFFICIENT DATA` (per-event scores still listed; no means, no CI) |
| $5 \le n < 30$ | as below, plus caveat `small sample: n = N events (< 30)` | as below |
| synthetic cases | `ILLUSTRATIVE: Synthetic demo fixtures` | as below |
| real historical cases | `OFFICIAL: Computed from N historical cases` | as below |
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
- Recorded demo runs are labeled `RECORDED RUN` and carry model id, digest, temperature, seed and both hashes.
