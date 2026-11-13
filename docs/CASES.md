# Blind Replay cases

Case files: `services/api/data/demo_cases/<event_id>.json`. Sealed answers: `services/api/data/sealed_outcomes/<event_id>.json`
(read only by `core/evaluator.py`). This document never states which way a case resolved.

The selection rule for the **real** historical cases (issue #20) is in its own section, added by PR #54. This
section covers only the synthetic fallback case (issue #48).

## Synthetic fallback case

SPEC §9 P0 item 3 asks for "one explicitly synthetic fallback case", and SPEC §5 control (a) asks for
"synthetic never-before-seen cases with sealed random outcomes". This case lets the replay run end to end
without any real case, and no model can have seen its answer in pretraining, because the answer is a fresh
random draw.

| Field | Value |
|---|---|
| `event_id` | `synthetic_distributor-depot` |
| Provenance | `SYNTHETIC` everywhere (`synthetic: true`, case and every evidence item) |
| Question | SYNTHETIC: Will the demo grocer's primary distributor (the fictional Brindlewick Provisions) stop deliveries from its North depot for 5 or more consecutive days within 21 days after the cutoff? |
| `as_of` | `2026-09-14T12:00:00Z` (a synthetic timeline, not a real event) |
| `horizon_days` | 21 |
| Evidence | 5 invented documents, all with `published_at = available_at <= as_of` |
| Market price | `NOT AVAILABLE` (see below) |
| `contamination_flag` | `unlikely` (never "none") |

### What the case is about

The "demo grocer" is FAULTLINE's fictional three-store food retailer (`data/demo_business.json`). The question
matches the `supplier-outage-3wk` scenario: if the primary distributor stops, the lines behind 40% of base-store
sales are lost unless the grocer pays the backup supplier's 12% premium and 2,000 switching fee (the same
`backup_premium` and `backup_switch_fee` as the demo business). The decision is act (switch those lines now),
hedge (switch part of them) or wait.

Every name is invented: Brindlewick Provisions, the Brindlewick North Depot Workers' Association, Corran Valley
Foods, Harrowmere, The Harrowmere Ledger, Mill Lane. Each evidence text starts with "SYNTHETIC DOCUMENT:
fictional, written for the FAULTLINE demo". `source_url` values use the reserved `.invalid` domain
(RFC 2606), which cannot resolve, so no real website is presented as a source. `archive_url` is empty.

| Evidence id (`synthetic_distributor-depot.` + ...) | Title | `available_at` |
|---|---|---|
| `contract-bulletin` | SYNTHETIC: Brindlewick Provisions customer bulletin - North depot labour contract talks | 2026-08-25T15:00:00Z |
| `account-manager-letter` | SYNTHETIC: Letter from Brindlewick account manager to the demo grocer on contingency plans | 2026-09-04T14:00:00Z |
| `local-paper-vote` | SYNTHETIC: The Harrowmere Ledger - depot workers vote to authorise strike if no deal | 2026-09-10T18:30:00Z |
| `road-notice` | SYNTHETIC: Harrowmere County roads notice - Mill Lane resurfacing near North depot | 2026-09-12T09:00:00Z |
| `backup-supplier-quote` | SYNTHETIC: Corran Valley Foods quote to the demo grocer for backup supply | 2026-09-13T16:00:00Z |

### How the answer was fixed: a committed fair draw

The answer was not chosen by anyone. It comes from a random seed and a rule that were fixed in this order:

1. **The rule was written down first** (before any seed existed):
   - seed = 32 random bytes from Python `secrets.token_bytes(32)` (the operating system's cryptographic random
     generator);
   - commitment = SHA-256 of the 32 raw seed bytes;
   - h = SHA-256 of (the 32 seed bytes followed by the ASCII text `faultline-synthetic-draw:synthetic_distributor-depot`),
     read as a 256-bit whole number;
   - **YES if 100 × h < 35 × 2^256, otherwise NO.** Since h is uniform on [0, 2^256), P(YES) = 0.35 exactly.
     The comparison uses whole numbers only, so there is no rounding.
2. **The seed was generated once**, by a script that refuses to run a second time.
3. **Only the commitment is in the case file** (`curation_notes.fair_draw.commitment_sha256`
   = `583b87ea7ab1261948541f56ca5a38703efb6cdeef6307a254ab7d3d40d60f38`), together with the rule above. The case
   file has no key that looks like an answer, and the gate never puts `curation_notes` into a prompt.
4. **The seed and the drawn answer are only in the sealed file** (`notes` holds `seed_hex=...`, because the
   sealed-file format allows no other extra field). Only `OutcomeVault.reveal` reads that file, and only after
   a forecast is saved.

**Why p_draw = 0.35.** It was fixed before the seed was drawn. The documents describe a real but minority risk
(a strike was authorised, but both sides call the talks constructive and a mediator is booked). The draw does not
depend on the text, so the best possible forecast for this case is 0.35, and no forecaster can beat that in
expectation. If a synthetic market price is added later (see below), it should be 0.35, which makes the
synthetic "market" calibrated by construction.

**Commit order.** The case file (with the commitment and the rule) is committed first and the sealed file in a
later commit of the same PR. Git commit times are set by the author, so this order is documentation, not proof.
What does hold: the commitment is in the reviewed PR before any forecast is run, and the store's
persist-before-reveal ledger stops anyone revealing the answer for a forecast that was not saved first.

**What the commitment does and does not prove.**
- It proves the answer was fixed before any forecast was made and cannot be changed afterwards: a different seed
  would not match the published SHA-256.
- It does **not** prove the seed was drawn only once. The person who ran the script saw the answer at that
  moment, and could in principle have re-run it until they liked the answer. The mitigation is process: the
  script refuses to overwrite its output, it was run once, and this is a synthetic demo case that is never
  pooled with real cases. A stronger scheme (mixing in a public randomness beacon published after the
  commitment) is a possible follow-up.

### How to verify it (from the repository root)

Running this reads the sealed file but prints only two checks, not the answer:

```bash
python -c "import hashlib,json,re;c=json.load(open('services/api/data/demo_cases/synthetic_distributor-depot.json',encoding='utf-8'))['curation_notes']['fair_draw'];s=json.load(open('services/api/data/sealed_outcomes/synthetic_distributor-depot.json',encoding='utf-8'));seed=bytes.fromhex(re.search(r'seed_hex=([0-9a-f]{64})',s['notes']).group(1));h=int(hashlib.sha256(seed+b'faultline-synthetic-draw:synthetic_distributor-depot').hexdigest(),16);print('commitment ok:',hashlib.sha256(seed).hexdigest()==c['commitment_sha256'],'| draw ok:',('YES' if 100*h<35*2**256 else 'NO')==s['outcome'])"
```

Expected output: `commitment ok: True | draw ok: True`.

### Market price: NOT AVAILABLE

The case file has `market_quotes: []`. The quote contract (`markets.base.NormalizedQuote`) accepts only
`venue` = `kalshi` or `polymarket` and a fixed "market-implied probability" label, and has no provenance field.
An invented price in that shape would be shown as a real Kalshi or Polymarket price, which the honesty rules
forbid. So, for this case:
- the gate reports the market baseline `NOT AVAILABLE`;
- the `agent_plus_market` variant does not run (`MarketNotAvailable`); `agent_only` runs;
- `build_scorecard` excludes the case with reason `market_not_available` (a data reason, not an operator
  reason, so it never blocks the OFFICIAL label of the real cases).

Adding a synthetic price needs a contract change outside this case's files (a `synthetic` venue and a SYNTHETIC
label on quotes). Until then no price is typed into the file.

### Never pooled with real cases

Synthetic results are reported separately from real historical cases and never count toward the real-case `n`.
`core/evaluator.py` enforces this:

```python
if len(real_flags) > 1:
    raise ValueError("synthetic and real historical cases must be scored separately")
```

It also checks that each forecast's `synthetic` flag (fixed by the gate when the forecast was saved) agrees with
the sealed file's `provenance` (`SYNTHETIC` here). A scorecard made only of synthetic cases is labelled
`ILLUSTRATIVE: Synthetic demo fixtures`. A committed synthetic case without a forecast does not block the OFFICIAL
label for the real cases (`test_synthetic_committed_cases_without_forecasts_do_not_block_official`).
