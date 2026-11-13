# FAULTLINE // Claude Code Build Specification

**Version:** 1.0  
**Prepared:** November 12, 2026  
**Context:** SCION / 300 Hackathon, team prototype  
**Build priority:** a working, impressive, demonstrably honest product before the Sunday deadline  
**Project name:** FAULTLINE (working title, keep brand configurable)

> **Claude Code: Your task is to implement a runnable MVP, not merely suggest an architecture.** Read this document, inspect the repository, create an implementation plan, then build incrementally. Deliver a working local demo with deterministic fixtures, tests, clear setup instructions, and a responsive frontend. If an external API or model is unavailable, preserve the functional offline path and visibly label sample data. Never simulate successful live integrations or invent benchmark wins.

---

## 0. The product in one minute

**FAULTLINE is a time-aware decision intelligence and financial stress-testing platform.** It lets a human explore a future business decision, see likely cascading operational and financial consequences, and compare recovery paths using evidence, prediction-market signals, agentic research, and mathematical optimization.

Its signature mode is **THE BLIND REPLAY**: rewind to a real historical decision point, seal all information that was not available at that time, ask an **open-weight model running locally** to choose a path, reveal what actually happened, and score the forecast against simple baselines and the prediction market available *at that time*.

The signature visualization is a living dependency network. Changes ripple through linked nodes for sales, customers, suppliers, debt, inventory, payroll, cash, and market shocks. A timeline lets judges move between **THEN**, **DECISION**, and **REVEAL**. A split-screen compares **ACT / WAIT / HEDGE** or **PLAN A / PLAN B**.

The strong pitch is **"Test the decision before you live with it."** Do not pivot this into a trading bot, AI stock-picker, automated loan-underwriter, or a dashboard of generic AI predictions.

### Primary user

Financially sophisticated small-business operators, fractional CFOs, advisors, and strategy teams facing uncertainty. A VC analyst can also use the research/benchmark lens, but venture fund investment selection is *not* the sole product.

### Why finance matters

- Quantify cash runway, downside exposure, debt costs, net operating cash flow, and constraints.
- Model how a macro event such as interest-rate changes, a supplier shock, or demand contraction changes feasible plans.
- Present probabilities and uncertainty *alongside* financial consequences, never as substitutes for them.
- Keep people in charge of decisions. No employment, lending, investment, or trading actions are automatically executed.

---

## 1. Non-negotiable principles

1. **Actual computation, not AI theater.** The frontend visualizes outputs from a typed calculation engine. LLMs do not perform authoritative arithmetic.
2. **Strict point-in-time replay.** Every item sent to the agent must have a source and an `available_at` timestamp <= the historical cutoff.
3. **Outcome sequestration.** Resolution, future market prices, future news, realized returns, and hindsight write-ups are withheld from the agent until the reveal stage.
4. **An offline open-weight model is the replay default.** A hosted LLM cannot honestly be called air-gapped. The open-weight runtime must not have network access during evaluation.
5. **Offline does not magically erase pretrained knowledge.** Models may already know historical outcomes from training. Disclose model release date / training cutoff when known, identify contamination risk, and add leakage-resistant controls.
6. **Compare apples with apples.** Benchmark the same events, cutoffs, outcome definitions, and scoring rules against a prediction-market-only baseline and simple naive forecasts. Never claim to beat markets or VCs without actual valid results.
7. **VC publications are evidence and thesis context, not private VC investment records.** Public firms do not disclose their rejected deals, all valuations, cash flows, or comparable investment return series. Do not falsely claim "we beat Link Ventures".
8. **Human-controlled.** The engine may propose and evaluate actions; it cannot move money, place bets, trade securities, modify employment, or approve/deny loans.
9. **Credible demos.** Always distinguish genuine historical records, synthetic financial company data, retrospective labels, and illustrative simulation assumptions.
10. **Reliability beats scope.** A flawless 2-minute vertical slice is better than twenty broken integrations.

---

## 2. The winning live experience (aim 90–120 seconds)

**Screen A: REWIND.** A dramatic full-viewport historical timeline. Pick one pre-verified, resolved event from the bundled case list. The right panel states `Knowledge cutoff: YYYY-MM-DD HH:MM UTC`, lists only information known by then, and displays a **SEALED FUTURE** indicator. The event's final resolution is not in agent input.

**Screen B: THE DECISION.** Show a local open-weight agent's decision, a probability estimate, three short evidence citations, and alternative strategies (for example, act now, wait, or hedge exposure). Display the prediction-market implied probability *at that cutoff*, when historical prices are demonstrably available.

**Screen C: THE CASCADE.** The business network animates: a rate decision changes financing cost; liquidity tightens; supplier/payment/cash nodes shift. A judge changes a slider or toggles `Protect payroll` and the **deterministic optimizer** recalculates feasible recovery plans.

**Screen D: REVEAL.** Unlock historical outcome and show a scoring comparison: `Agent`, `Market-only`, and `Naive baseline` over the *same* benchmark cases. If the agent did not win, say so; an honest failure is itself a strong alignment and product story. An individual anecdote is **not** evidence of general superiority.

**Screen E: RESEARCH LENS.** Four clearly dated, sourced research lenses from **Link Ventures, a16z, Sequoia Capital, and Bessemer Venture Partners**. Show which published theses would be relevant to a decision, what was known by the cutoff, and where the model agreed or disagreed. Never display a fictional numeric "VC accuracy" if no equivalent quantified forecast exists.

**Golden path for judges:** choose a case -> see point-in-time information -> run or retrieve a cached authentic local-model response -> impose a business constraint -> see the graph and cash forecasts react -> reveal the real outcome -> inspect the transparent scoreboard and the four VC research sources.

### Visual design, non-negotiable

- Premium financial-terminal aesthetic, not a generic SaaS template and **no AI-generated decorative imagery**.
- Near-black/navy canvas, warm off-white typography, restrained amber for risk, electric teal for viable paths, crimson for failed constraints.
- A substantial animated network visualization (React Flow + custom SVG/canvas, or React Three Fiber *only if performance is robust*).
- Big cinematic type and useful negative space; subtle physics, particles/edges, timeline transitions, hover evidence, and 60-fps aspirations.
- A financial readout that changes accurately in sync with the model. Numbers should be large, legible, and formatted consistently.
- Favor small labels `AS-OF`, `SEALED`, `VERIFIED`, `FORECAST`, `REVEALED`, `SIMULATED` over paragraphs.
- No false "live" loading sequences. Precomputed genuine runs are fine if marked `Recorded run` and reproducible.
- Optimize desktop projector 16:9 first; maintain workable mobile layout.
- Accessibility: keyboard focus, reduced motion support, legible contrast, and color-independent status labels.

---

## 3. The three technical pillars

### 3.1 Point-in-time event and forecast engine

Inputs:
- Resolved event with precisely defined YES/NO resolution criteria.
- `as_of` timestamp strictly before the event resolves.
- Relevant dated information available by `as_of`.
- Historical Kalshi and/or Polymarket market quote or candle recorded by `as_of`.
- Optional related historical macro data available by `as_of`.

Outputs:
- The agent's calibrated or raw `p_yes` in [0, 1], proposed action, confidence/uncertainty notes, evidence IDs, model name/revision, cutoff, prompt hash.
- Market-only forecast at the same cutoff.
- Revealed event result in {0,1}, scored **only after** the forecast is saved.

**Prediction markets are inputs AND a benchmark.** Preserve an agent-only ablation (`no_market_input`) and an agent-plus-market variant (`with_market_input`). If the agent observes the market probability, do not pretend the result is independent of the market. A better score than the market-only forecast must be reported as a genuinely measured incremental improvement.

### 3.2 Deterministic business simulation + optimizer

Create one credible synthetic demo business: a regional food/retail business with 2–3 locations, suppliers, receivables, inventory, payroll, monthly debt service, cash reserves, and operating margins. Do not represent its data as an actual company's records.

Model a constrained financial timeline (weekly or monthly). Use typed Python functions for:
- Revenue under demand shocks.
- Cash receipts and payables with timing.
- Interest expense as a function of borrowing rate and principal.
- Supplier outages and delayed replenishment.
- Cash-balance recurrence, minimum liquidity, and runway.
- Payroll, debt service, and inventory preservation constraints.

Agent suggests recovery actions, but **SciPy `optimize.milp` / `linprog` or OR-Tools** selects a feasible plan maximizing minimum cash / minimizing disruption cost subject to constraints. Define a small explicit candidate action space: defer noncritical capex, use backup supplier, reduce inventory purchases, draw approved credit facility, delay expansion. Do not allow implicit layoffs in `Protect payroll` mode. An infeasible result must be shown as `NO FEASIBLE PLAN`, not overwritten by an LLM.

**Do not fake probabilities from the simulator.** If adding 100+ stochastic runs, list distributions and assumptions; otherwise show deterministic stress cases with no misleading confidence interval.

### 3.3 Research + skeptic / verification loop

Roles, kept narrow:
- **Research agent:** retrieves point-in-time permitted evidence from a frozen bundle in Replay Mode; Tavily and current public sources are permitted *only in Live Explore Mode*.
- **Decision agent:** outputs structured scenario, forecast, proposed plan, and cited evidence IDs. Pluggable model provider (Ollama local, optional Anthropic live-mode adapter).
- **Skeptic/verifier:** checks evidence IDs, date eligibility, contradictions, source provenance, numeric ranges, constraint feasibility, and missing evidence. Reject unsupported claims before display.

LLM output is **proposed**; typed validators, date checks, financial functions, and optimization are **authoritative**.

---

## 4. Kalshi and Polymarket integrations

### Kalshi

Official docs:
- Historical data partitioning: https://docs.kalshi.com/getting_started/historical_data
- Historical market candles: https://docs.kalshi.com/api-reference/historical/get-historical-market-candlesticks
- Official base URL shown in documentation: `https://external-api.kalshi.com/trade-api/v2`.

**Important:** Kalshi partitions historical vs live data. Query `GET /historical/cutoff` and use the correct live/historical endpoint for the market at hand. For archived settled markets, documented candle endpoint: `GET /historical/markets/{ticker}/candlesticks`. Confirm exact parameters and current restrictions against the official docs at coding time. Save ticker, quote/candle timestamp, price scale, volume if present, event settlement rules, and source metadata.

### Polymarket

Official researcher-facing docs:
- https://institute.polymarket.com/data
- Gamma for events/market metadata: `https://gamma-api.polymarket.com`
- CLOB for historical prices: `https://clob.polymarket.com/prices-history`

Polymarket's public research guide describes querying the CLOB by an outcome's `token_id`, which is obtained from Gamma. Historical requests can use `startTs`, `endTs`, and `fidelity`; verify returned timestamp units and actual available history. Beware that the decentralized Polymarket and the US Polymarket product have separate data and APIs. Do not assume they can be merged.

### Integration requirements

- Make two provider adapters with shared normalized interface `EventMarketProvider`.
- Never poll live APIs during sealed historical agent inference; build an offline snapshot first.
- Use explicit `as_of` to select the **last actual quote/candle <= cutoff** within an allowed maximum staleness window (e.g. 24h). If nothing qualifies, mark the market baseline unavailable.
- Handle binary versus multi-outcome markets; implement **binary first**. Respect contract definitions and settlement ambiguities. Do not naively equate mutually exclusive markets to independent binary events.
- Normalize percentage/cents/decimal scales exactly once and test them.
- Record venue, market identifier, URL, quote kind (last trade, midpoint, candle close), timezone, timestamps, spread/liquidity when available, and data-collection time.
- Market price is a price-derived implied probability, potentially distorted by fees, spread, liquidity, incentives, or risk premium. Label it that way, not "ground truth probability".
- Market data availability can be patchy. If a price history cannot be obtained reliably, do not fabricate it. Fall back to a documented dataset or show `NOT AVAILABLE`.
- Public read-only API access only. No betting, wallets, transactions, credentials, or exchange order submission.

### Data collection workflow

1. Discover 20–50 historically resolved binary questions across finance, macro, and operations-relevant categories, with explicitly known resolution rules.
2. Select decision snapshots **without looking at the outcome** in the decision process. Aim for 7-day and/or 30-day lead horizons where possible.
3. Persist each snapshot (raw API response + normalized format + SHA256 provenance manifest).
4. Confirm the quote and evidence genuinely existed by the historical cutoff; exclude markets with unreliable timestamps or insufficient price records.
5. Store outcomes in a separate `sealed_outcomes` table/file, inaccessible to the agent runtime.
6. Freeze the dataset manifest and evaluation case list before tuning the model/prompts on the held-out group.

For the hackathon, prioritize **a few thoroughly audited real events** over a dubious leaderboard full of mismatched markets.

---

## 5. Historical Blind Replay: anti-leakage design

**Question:** “Could an agent, with only information available on the historical date, have made a better decision?”

**Strong limitation:** The absence of runtime internet does **not** remove information learned during pretraining. A model released after an event may already know the answer. We must not call a replay blind solely because the network is disabled.

Implement:

- `as_of` is required for every replay. Every source has at minimum `published_at`, `observed_at` (when collected), `available_at` (first known public availability), `source_url`, and `content_sha256`.
- If an old webpage has been revised, `published_at` alone does not prove its present text existed at that date. Use historical archives/snapshots when available; otherwise exclude from strict replay or flag `retrospective_unverified` and prohibit model access.
- The agent process sees **only pre-filtered sealed input** from `EvidenceStore.get_as_of(event, cutoff)`. Never send current Gamma event status or future market prices in metadata. Drop all resolution/outcome fields from inputs.
- No retrieval tool, Tavily, web, current system date, shell network, or arbitrary file access is available to the replay model.
- In local mode, run an open-weight quantized model via Ollama or llama.cpp; if possible isolate the replay process with disabled egress. Note the model provider/release/license and any known training cutoff. Do not claim guaranteed absence of memorization.
- Include multiple controls: (a) synthetic never-before-seen cases with sealed random outcomes, (b) post-training-cutoff events when feasible, (c) prompts with company/event names anonymized, (d) a separate no-market-input experiment, (e) a **future-fact canary** deliberately stored in excluded data; assert it never reaches the model.
- Remove identifiable titles from anonymized cases only when semantics remain intact. Masking names alone does not eliminate pretrained outcome contamination.
- Score predictions on a fixed, not cherry-picked, holdout split. Treat contamination flags and missing snapshots as evaluation exclusions with a transparent report.
- Capture exact prompts, model ID, seed/temperature, inference timestamp, snapshot hash, and forecast response **before** revealing any outcome.
- Validate in unit tests that no evidence or market observation has `available_at > as_of`, no resolved outcome reaches the model context, and the scorer cannot run until a prediction is persisted.

### Required JSON structures (implement as Pydantic models)

```json
{
  "event_id": "demo_macro_001",
  "title": "Will the specified event occur under the published settlement rule?",
  "as_of": "2025-01-15T12:00:00Z",
  "horizon_days": 30,
  "resolution_rule": "Exact quoted settlement criteria",
  "evidence_ids": ["evid_a", "evid_b"],
  "market_quote_id": "quote_001",
  "snapshot_hash": "sha256:...",
  "synthetic": false,
  "contamination_flag": "unknown"
}
```

```json
{
  "prediction_id": "pred_001",
  "event_id": "demo_macro_001",
  "as_of": "2025-01-15T12:00:00Z",
  "agent_model": "ollama/<installed-model-id>",
  "variant": "agent_only",
  "p_yes": 0.61,
  "decision": "wait",
  "rationale": "Short rationale with supported claims only",
  "evidence_ids": ["evid_a"],
  "prompt_sha256": "...",
  "snapshot_sha256": "...",
  "recorded_at": "2026-11-12T22:00:00Z"
}
```

All numbers in these JSON snippets are **schema examples**, not historical results or claims of model performance.

---

## 6. The scorecard: can we honestly beat the market?

### Binary-outcome forecast metrics

For an event with realized outcome `y ∈ {0,1}` and submitted probability `p ∈ [0,1]`:

- **Brier score** = `(p-y)^2` (lower is better).
- **Log loss** = `-y*ln(clamp(p)) - (1-y)*ln(1-clamp(p))` (lower is better).
- **Accuracy** at an explicitly pre-specified threshold of 0.5 is secondary; it ignores confidence/calibration.
- If enough cases, reliability diagram and calibration bins. Small-sample metrics need visible caveats.

Compute aggregate scores on identical `event_id + as_of` pairs for:

1. **Naive**: `p=0.50`.
2. **Market-only**: market implied YES probability at cutoff, if available.
3. **Local agent-only**: frozen documents, no market price.
4. **Local agent + market**: same evidence plus market price.
5. **Optional** hosted Claude comparator: same frozen evidence, labeled **hosted-model comparison, not air-gapped**.

Publish sample size `n`, number excluded, exclusions by reason, mean Brier/log loss, relative difference versus baselines, and uncertainty (bootstrap CI if sample size permits). **Do not label the model "better" if the measurement doesn't support it.**

For a decision-policy comparison (ACT vs WAIT vs HEDGE), define all payoffs ex ante, including carrying costs/fees and constraints, then simulate those identical policies on identical events. If robust realized decision-return data are unavailable, show only the probability-forecast comparison and synthetic financial-scenario effects. **Never report fictitious trading P&L.**

### Historical evaluation standards

- Train/develop on earlier historical events; hold out later events with a documented chronological cutoff. No test selection or prompt tweaking after examining outcomes.
- Separate prompt/design and test cases; event selection must be rule-based where possible (avoid survivorship bias).
- Avoid double counting multiple snapshots of one event as independent observations; group by event and report uncertainty accordingly.
- Market-only comparison requires exact corresponding venue/contract/question and as-of quote.
- The safe investor-facing claim is **"An auditable backtesting system that measures whether combining research agents with market probabilities adds signal."** Claim empirical outperformance *only if it occurs* on a nontrivial, documented out-of-sample evaluation.

### UI scorecard labels

- `OFFICIAL: Computed from N historical cases`
- `ILLUSTRATIVE: Synthetic demo fixtures`
- `INSUFFICIENT DATA: No valid comparison`
- `No improvement measured` when applicable

Never hardcode a made-up "87% accuracy", "beat VCs by 30%", or "AI beats Kalshi" headline.

---

## 7. Four public VC research lenses

We want actionable ideas from **four distinct firms**, with a strong link to finance and investment reasoning. These are not permission to claim access to private diligence or investment decisions.

| Firm | Public starting point | How FAULTLINE uses it | Critical caution |
|---|---|---|---|
| **Link Ventures** | https://linkventures.com/ and https://linkventures.com/portfolio | Thesis signals about technical founders, AI-first infrastructure, operational scalability, and risk of critical dependencies | A portfolio page is not a record of rejected investments or realized returns |
| **Andreessen Horowitz (a16z)** | https://a16z.com/fintech/ and https://a16z.com/announcement/investing-in-stitch/ | Fintech infrastructure, incumbents' operational bottlenecks, systems of record, thesis-to-risk mapping | Research and investment articles are persuasive writing, not calibrated numerical forecasts |
| **Sequoia Capital** | https://sequoiacap.com/article/partnering-with-etched-building-the-inference-machine | Investment narratives, infrastructure constraints, model uncertainty and capital intensity | The linked article is published **July 23, 2026**, unusable for earlier point-in-time replays |
| **Bessemer Venture Partners** | https://www.bvp.com/atlas/the-state-of-ai-2025 | System-of-action trends, infrastructure reliability, market risks, value and ROI assumptions | Published **August 13, 2025**; exclude from replay cutoffs before publication |

**Implementation:** A small `vc_research` dataset of 4–8 hand-verified public articles/portfolio announcements (minimum one per firm), retaining firm, title, permalink, published/archived timestamps, thesis, hypotheses, quoted factual evidence, and limitations. Use these as **research citations in Live Explore Mode** and in replays *only if independently established as available at the cutoff.*

Feature: **Thesis Court**. For a user-selected historical business/investment scenario, show four distinct public research perspectives and what *specific, timestamp-valid* thesis each supports or challenges. The skeptic must distinguish (1) documentary fact, (2) an analyst interpretation, and (3) a quantitative testable forecast. Use `RESEARCH CONTEXT`, not "VC prediction".

**Can our model beat four VCs?** Not from their public portfolios alone. If a particular VC publication contains an explicit dated numeric prediction with a verifiable future target, a matched scoring experiment *may* compare it. Otherwise we can demonstrate better **decision transparency, scenario coverage, responsiveness, or cost/time of analysis** against documented manual baselines, not fund performance. Show no fabricated direct competitive score against Link/a16z/Sequoia/Bessemer.

### Strong future feature, NOT for this weekend

A user could import dated, licensed institutional research, build a firm's custom thesis model, and measure decisions against the organization's own logged historical forecasts. That requires consent and a verified dataset. Not in the MVP.

---

## 8. Full-stack implementation

**Recommended stack:**

- Frontend: Next.js (App Router), TypeScript, Tailwind, Framer Motion or Motion, React Flow for graph; use three.js only for the hero visualization if development capacity permits.
- Backend: Python FastAPI, Pydantic v2, NumPy, NetworkX, SciPy (OR-Tools optional).
- Persistence: SQLite for reproducible local demo, SQLAlchemy or simple well-tested queries. Store raw source payloads and fixtures in versioned files.
- Model provider interface: `LocalOllamaProvider` first, optional `AnthropicProvider` for live mode; optional `MockProvider` only when clearly labeled test fixture.
- Tool search: Tavily only in online Live Explore Mode; no historical web research without independently timestamped archival evidence.
- Test: pytest, TypeScript checks, Vitest if present, Playwright for smoke test if time allows.
- Deploy: ideally a public, interactive preview with safe synthetic financial data, no private credentials, and cached read-only historical snapshots. Public viewers should be able to trigger sliders and recomputations, not just watch a recorded replay.

### Monorepo suggestion

```text
faultline/
  README.md
  .env.example
  apps/
    web/
      app/
      components/
        ReplayTimeline.tsx
        CascadeGraph.tsx
        DecisionBranches.tsx
        Scorecard.tsx
        ThesisCourt.tsx
        EvidenceDrawer.tsx
      lib/api.ts
  services/
    api/
      main.py
      models.py
      routes/
        cases.py
        replay.py
        simulate.py
        benchmark.py
        research.py
      core/
        provenance.py
        temporal_gate.py
        forecasting.py
        financials.py
        optimizer.py
        evaluator.py
      agents/
        provider.py
        local_ollama.py
        anthropic_live.py
        researcher.py
        skeptic.py
      markets/
        base.py
        kalshi.py
        polymarket.py
        normalize.py
      data/
        demo_cases/
        research_lenses.json
        raw/
        sealed_outcomes/
      tests/
        test_temporal_gate.py
        test_market_normalization.py
        test_scoring.py
        test_financials.py
        test_optimizer.py
        test_replay_seal.py
  scripts/
    collect_market_snapshots.py
    validate_fixtures.py
    run_benchmark.py
  docs/
    EVALUATION_PROTOCOL.md
    DATA_PROVENANCE.md
    DEMO_SCRIPT.md
```

### Suggested API contract

- `GET /api/cases`: list demo cases, metadata and `as_of`; do NOT return sealed outcomes until appropriate reveal.
- `GET /api/cases/{id}/evidence?as_of=...`: only eligible dated evidence.
- `POST /api/replay/run`: run eligible model variant using frozen snapshot; persist prediction before reveal.
- `POST /api/replay/{prediction_id}/reveal`: authorize evaluation/reveal; read outcomes from a separate scorer process/repository boundary.
- `POST /api/simulate`: deterministic business scenario computation.
- `POST /api/optimize`: feasible recommended actions given hard constraints.
- `GET /api/benchmark`: computed aggregate statistics and provenance, not display placeholders.
- `GET /api/vc-lenses`: dated, sourced four-firm research context.
- `GET /api/health`: runtime status and model readiness.

**Security note:** A simple `if revealed == false` UI toggle is *not* information isolation. Outcome files must not appear in the prompt retrieval paths, exposed document endpoints, or unrestricted agent tools. Consider separate evaluation process/permissions even for MVP. Cache authentic predictions in data fixtures only if cryptographically traceable to a completed run and marked recorded.

---

## 9. Make the demo physically possible

### Ship FIRST (Priority P0)

1. One beautiful 16:9 app with working timeline, split-network visual, sliders, and side panel.
2. A fully deterministic synthetic business shock engine and constrained optimizer with tests.
3. Two to four valid *real* history replay cases with correctly filtered data, plus **one explicitly synthetic fallback case**.
4. Local open-weight inference if available; otherwise app still works as a simulation with visible model-unavailable state (not faked inferences).
5. Market-only probabilities only where valid historical quotes are actually sourced.
6. A scorecard that computes real metrics and handles zero/insufficient cases gracefully.
7. Research lens citations from Link, a16z, Sequoia, Bessemer.
8. A publicly accessible safe demo with offline-cached input data if hosting is feasible.

### P1 (time permitting)

- Real Kalshi + Polymarket collectors with archival cache and robust normalization.
- A skeptic loop that rejects unsupported citations and infeasible strategies.
- Agent-only vs agent-plus-market side-by-side evaluation.
- Tavily current-news enrichment in separate Live Explore Mode.
- A playable "Judge's Challenge" selector with unexpected shocks.

### P2 (cut without regret)

- Generalized ingestion of arbitrary company financial statements.
- A full marketplace of hundreds of forecasts.
- Training or fine-tuning a new foundation model during the hackathon.
- Sophisticated Monte Carlo risk estimation without validated distributions.
- Actual broker or prediction-market trading, payments, loans, or employment changes.
- Any unauditable claims that FAULTLINE beats real VC returns.

### Hackathon delivery phases

**Phase 1: Working core.** Create typed fixtures, compute cash flows, expose API, render graph with slider. Write tests immediately.

**Phase 2: Replay.** Add as-of filtration, sealed outcomes, local open-weight provider, and one thoroughly audited real historical event.

**Phase 3: Scoring.** Run real probability forecasts and benchmark; surface measured results without exaggeration.

**Phase 4: Research lens + visual finish.** Add four source-backed firm lenses, polished animation, labels, and an end-to-end demo route.

**Phase 5: Reliability.** Record one authentic backup demo; save real model outputs; test without network; ensure every button does something; minimize latency and polish presenter flow.

### Team responsibilities

- **Systems/backend owner:** historical data pipeline, replay isolation, model adapters, API, event scoring, integration and deployment.
- **Finance owner (Yaseen):** financial model assumptions, economic consequences, decision constraints, case review, VC/public research accuracy, credibility of financial scenarios.
- **Frontend/visual owner:** graph, timeline, scene transitions, input interactivity, typography, responsive demo.
- **Any additional collaborator:** evaluation audit, fixture validation, QA, source attribution, pitch timing.

---

## 10. Tests and acceptance checklist

**No ship without these tests:**

```text
[ ] Replay rejects evidence published after as_of.
[ ] A future-fact canary never appears in model context.
[ ] Resolved outcome is not present in any pre-reveal endpoint or prompt.
[ ] Invalid/stale market quotes are excluded, not silently reused.
[ ] Quote normalization handles cents, decimals and missing data.
[ ] Brier score and log loss pass known numeric fixtures.
[ ] Forecast is persisted before outcome reveal.
[ ] Model settings and dataset hashes appear in audit output.
[ ] Agent-only and agent+market variants are distinct and labeled.
[ ] Cash-flow recurrence matches hand-calculated golden cases.
[ ] Payroll protection is enforced by optimizer, not a string instruction.
[ ] Solver reports infeasible constraints accurately.
[ ] VC documents with publication dates later than as_of are excluded.
[ ] Public app works without personal accounts or secret API keys.
[ ] All demo data marked real historical / synthetic / recorded inference.
[ ] An absent open-weight model causes clear fallback messaging, not fake inference.
[ ] Every scenario slider produces a correct visible update.
[ ] Running the complete demo requires no unrestricted internet dependency.
```

### Definition of done

- `README.md` gives exact install/run commands and configuration (`OLLAMA_BASE_URL`, optional `ANTHROPIC_API_KEY`, optional `TAVILY_API_KEY`, data-cache path).
- A one-command local launch and preflight check are available (Makefile or scripts).
- `pytest` and TypeScript type checking pass; no hardcoded success paths.
- At least one genuine timestamp-valid historical event can be scored end-to-end, or the README explicitly explains why genuine data were unavailable and leaves the benchmark as `INSUFFICIENT DATA`.
- Demo can run with synthetic business data and sourced historical snapshot files with external API services disabled.
- All four VC lenses show at least one real source with date and URL.
- The actual scope and caveats are described in `docs/EVALUATION_PROTOCOL.md`.

---

## 11. Implementation instructions to Claude Code

Work autonomously but keep the product honest.

1. Inspect existing repo and dependencies, report what already exists, and avoid destructive rewrites.
2. Implement **P0** from top to bottom. Do not start by building an elaborate agent framework or mock dashboard with fake final results.
3. Start the backend with golden deterministic fixtures and tests, then integrate UI. Run the app and verify behavior.
4. Implement robust model and API error handling. External API keys may be missing. The public demo must remain usable.
5. Verify source adapters against official API schemas before relying on them. Cache actual fetch results with provenance. No synthetic responses labeled as live/real.
6. Before adding any benchmark superiority claim, compute its supporting score on a locked dataset and report its sample size, baselines, and caveats.
7. Deliver a finished project with actual commands, tests and a 2-minute demo sequence. Summarize implemented vs omitted features, known limitations, and honest measured outcomes.

**Creative direction:** Make it feel as though judges are standing at a control panel for alternative financial futures. The ambitious engineering is **sealed temporal evaluation + actual constraints + measured prediction accuracy**, not a crowd of AI characters arguing on screen.

---

## 12. Research/source links for implementation

Primary sources checked when preparing this spec:

- Kalshi, *Historical Data*: https://docs.kalshi.com/getting_started/historical_data
- Kalshi, *Get Historical Market Candlesticks*: https://docs.kalshi.com/api-reference/historical/get-historical-market-candlesticks
- Polymarket Institute, *Making Polymarket Exchange Data Accessible for Research* (July 24, 2026): https://institute.polymarket.com/data
- Link Ventures, main thesis and services: https://linkventures.com/
- Link Ventures, public portfolio: https://linkventures.com/portfolio
- a16z, public fintech thesis: https://a16z.com/fintech/
- a16z, *Investing in Stitch* (May 13, 2026): https://a16z.com/announcement/investing-in-stitch/
- Sequoia, *Partnering with Etched: Building the Inference Machine* (July 23, 2026): https://sequoiacap.com/article/partnering-with-etched-building-the-inference-machine
- Bessemer, *The State of AI 2025* (August 13, 2025): https://www.bvp.com/atlas/the-state-of-ai-2025

**Freshness and evidence note:** These URLs establish documentation and research themes, not that all historical datasets remain accessible, API rate limits are unchanged, VC decisions are measurable, or any model is profitable. Verify technical details at coding time. All source availability for historical replay must be independently assessed at the chosen `as_of` timestamp.
