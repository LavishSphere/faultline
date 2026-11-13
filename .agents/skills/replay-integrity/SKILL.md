---
name: replay-integrity
description: Rules and implementation guide for the Blind Replay pipeline - point-in-time evidence filtering (available_at <= as_of), sealed outcomes, future-fact canaries, prompt/snapshot hashing, persist-before-reveal, the local Ollama provider with no network, contamination flags, and forecast scoring (Brier/log loss/bootstrap). Use for any work on temporal_gate.py, provenance.py, forecasting.py, evaluator.py, agents/, replay or benchmark routes, demo case fixtures, or sealed_outcomes.
---

# Replay integrity (SPEC §3.1, §5, §6; MATH_MODEL §6)

A UI toggle is not isolation. Information isolation is a **code boundary + tests**.

## Boundaries
- `EvidenceStore.get_as_of(event_id, as_of)` is the **only** path from data to a prompt. It returns items with
  `available_at <= as_of` and `retrospective_unverified == False`, strips any field named like
  `outcome|resolution|resolved|settle|result|winner|final_price`, and never touches `data/sealed_outcomes/`.
- `data/sealed_outcomes/` is read only by `evaluator.py` through `OutcomeVault.reveal(prediction_id)`, which raises
  unless a `Prediction` with that id is already persisted (SQLite) with `prompt_sha256` and `snapshot_sha256`.
- Pre-reveal API responses are built from models that **have no outcome field at all** (separate Pydantic classes), so leakage is a type error, not a forgotten `if`.
- Market quotes passed to the agent must also satisfy `ts <= as_of` and staleness ≤ 24h (MATH_MODEL §7).

## Hashing & audit
- `snapshot_sha256` = SHA256 of canonical JSON (sorted keys, UTF-8, no whitespace) of the exact evidence + quote list given to the model.
- `prompt_sha256` = SHA256 of the final rendered prompt string. Store model id/tag, Ollama digest, temperature, seed, `recorded_at`.
- Recorded demo runs are stored with those hashes and labeled `RECORDED RUN`; a test recomputes the hashes.

## Model provider
- `LocalOllamaProvider` (default, `OLLAMA_BASE_URL`), JSON-mode output validated by Pydantic; temperature 0, fixed seed.
  If Ollama is down → return `ModelUnavailable` and the UI shows it. **Never** substitute a canned answer as if live.
- No tools, no retrieval, no current date in the prompt (pass only `as_of`). Replay must work with outbound network disabled.
- Record model release / training cutoff in a `MODEL_CARDS` table. Installed locally: `llama3.1:8b` (knowledge cutoff
  Dec 2023 per Meta), `gemma4:*` (check the model card). Prefer replay events **after** the model's cutoff; otherwise set `contamination_flag="likely"`.
- Variants: `agent_only` (no market price in prompt) and `agent_plus_market`. Distinct ids, distinct labels.

## Required tests (tests/test_temporal_gate.py, tests/test_replay_seal.py, tests/test_scoring.py)
- Evidence with `available_at > as_of` rejected; unverified retrospective items rejected.
- **Canary:** a fixture item `CANARY-<uuid>` stored only in excluded data; render the full prompt for every case and assert the string is absent.
- No pre-reveal endpoint JSON contains any sealed outcome value or outcome key (walk the JSON).
- `reveal()` raises before a prediction is persisted; scoring fixtures from MATH_MODEL §9.
- Stale quote (> 24h before as_of) → market baseline `NOT AVAILABLE`.

## Scoring display (MATH_MODEL §6)
n < 5 → `INSUFFICIENT DATA`; small-sample caveat under 30; "better" only if the bootstrap CI excludes 0. Show exclusions by reason.
