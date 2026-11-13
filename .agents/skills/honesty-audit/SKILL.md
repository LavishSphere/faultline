---
name: honesty-audit
description: Checklist and grep commands for catching dishonest or misleading output before it ships - hardcoded metrics, fake "live" states, fabricated data, missing provenance labels, outcome leakage, LLM arithmetic, unsupported superiority claims. Use before opening any PR, when reviewing a PR, or when the user asks "is this honest/credible" or prepares the demo.
---

# Honesty audit (SPEC §1, §6, §10)

Run on the diff (`git diff origin/main...HEAD`) and report findings as file:line.

## Greps (then read each hit, since a grep hit is not automatically a violation)
```bash
git diff origin/main...HEAD -U0 | grep -nE '[0-9]{1,3}(\.[0-9]+)?\s?%\s*(accuracy|better|win|beat)'   # headline metrics
git diff origin/main...HEAD -U0 | grep -niE 'beat(s)? (the )?(market|kalshi|polymarket|vc|a16z|sequoia|bessemer|link)'
git diff origin/main...HEAD -U0 | grep -niE '\blive\b|real-?time|thinking\.\.\.|setTimeout\(.*(result|answer)'
git diff origin/main...HEAD -U0 | grep -niE 'outcome|resolution|resolved|settle' -- services/api/routes services/api/agents
git diff origin/main...HEAD -U0 | grep -niE 'random\.|Math\.random' -- services/api/core apps/web
```

## Checklist
- [ ] Every number shown in UI comes from an API response; no literals standing in for results
- [ ] Each data surface has a provenance label (REAL HISTORICAL / SYNTHETIC / RECORDED RUN / SIMULATED / ILLUSTRATIVE)
- [ ] Missing data renders NOT AVAILABLE / INSUFFICIENT DATA, not a default number
- [ ] LLM output is validated; arithmetic and feasibility come from Python
- [ ] No outcome fields reachable by prompts or pre-reveal endpoints; canary test still passes
- [ ] Superiority claims only with n, baselines, CI (MATH_MODEL §6)
- [ ] Recorded runs carry prompt/snapshot hashes and model id
- [ ] Market prices labeled "market-implied (price-derived)"
- [ ] No trading/betting/lending/employment action is executed by code
