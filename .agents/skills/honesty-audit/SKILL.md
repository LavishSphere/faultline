---
name: honesty-audit
description: Checklist and grep commands for catching dishonest or misleading output before it ships - hardcoded metrics, fake "live" states, fabricated data, missing provenance labels, outcome leakage, LLM arithmetic, unsupported superiority claims. Use before opening any PR, when reviewing a PR, or when the user asks "is this honest/credible" or prepares the demo.
---

# Honesty audit (SPEC §1, §6, §10)

Run on the diff (`git diff origin/main...HEAD`) and report findings as file:line.

## 1. The scanner CI runs (do this first; a hit here fails the PR anyway)
```bash
python3 scripts/ci/content_scan.py honesty origin/main HEAD
python3 scripts/ci/content_scan.py secrets origin/main HEAD
```

## 2. Greps the scanner does not cover (read each hit; a grep hit is not automatically a violation)
Path filters belong to `git diff`, before the pipe. After the pipe, `grep` would search those directories and ignore the diff.
```bash
ADDED() { git diff origin/main...HEAD -U0 "$@" | grep -E '^\+' ; }
ADDED | grep -nE '[0-9]{1,3}(\.[0-9]+)?\s?%\s*(better|win|beat)'                                        # headline metrics
ADDED | grep -niE '\blive\b|real-?time|thinking\.\.\.|setTimeout\(.*(result|answer)'                    # fake live states
ADDED -- services/api/routes services/api/agents | grep -niE 'outcome|resolution|resolved|settle'       # outcome on the agent path
ADDED -- services/api/core apps/web | grep -niE 'random\.|Math\.random'                                 # randomness in engine/UI
ADDED -- docs | grep -niE 'beat|outperform|accura|guarantee|proves?\b'                                  # claims in pitch/brief docs
```

## Checklist
- [ ] Every number shown in UI comes from an API response; no literals standing in for results
- [ ] Each data surface has a provenance label (REAL HISTORICAL / SYNTHETIC / RECORDED RUN / SIMULATED / ILLUSTRATIVE)
- [ ] Missing data renders NOT AVAILABLE / INSUFFICIENT DATA, not a default number
- [ ] LLM output is validated; arithmetic and feasibility come from Python
- [ ] No outcome fields reachable by prompts or pre-reveal endpoints; canary test still passes
- [ ] Superiority claims only with n, baselines, CI (MATH_MODEL §6). This includes pitch, demo-script and brief documents
- [ ] Recorded runs carry prompt/snapshot hashes and model id
- [ ] Market prices labeled "market-implied (price-derived)"
- [ ] No trading/betting/lending/employment action is executed by code
