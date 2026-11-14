# Finance review: every on-screen number and label (issue #88)

Prepared by Claude Code at the finance owner's request (2026-11-14). Every check below was done by the agent against the code, API and MATH_MODEL; Yaseen has not yet reviewed it by hand.

**Sign-off:** ☑ Yaseen (finance owner) has read this review and agrees with each ✓ and each suggested fix (2026-11-14).

---

## How the checks were done

- **Code:** first walked on `main` at `36e2446`; `main` then moved to `426ae5f` (optional DSCR covenant #149, off by
  default and not used by any route; pitch notes #145). Every API figure below was re-run on `426ae5f` and is
  unchanged; the web app code is identical in both. No code was changed for this review.
- **Servers (Windows, Git Bash, README "Without make"):** API on port 8088 through `scripts/demo_api.py` with
  `FAULTLINE_DEMO_STORE` pointed at a scratch SQLite file (the official prediction store was not touched); web app with
  `next dev` on port 3088 and `NEXT_PUBLIC_API_BASE=http://localhost:8088`. Both were stopped at the end.
- **Machine limits:** no Ollama (the local model) and no `TAVILY_API_KEY`. Screens that need them were checked for an
  honest unavailable state, recorded below as "✓ honest NOT AVAILABLE".
- **Screens read:** a Playwright script (kept outside the repo) clicked through REWIND → DECISION → CASCADE → REVEAL →
  RESEARCH → LIVE EXPLORE and saved the on-screen text, once with the real case `fomc-2026-jul` (the only real case
  with a market quote at its cutoff) and once with the SYNTHETIC case `synthetic_distributor-depot`. On CASCADE it chose
  the "Bad quarter" preset, flipped **Protect payroll** on and off, applied the plan, and ran all 8 Judge's Challenges.
- **Numbers checked three ways:** (1) the same request sent straight to the API (`/api/simulate`, `/api/optimize`,
  `/api/decision`, `/api/cases/{id}/evidence`, `/api/vc-lenses`); (2) hand arithmetic from MATH_MODEL §1–§3, §8 and
  the §10 parameters; (3) a separate re-implementation of the §3 cash recurrence written for this review (it does not
  import the engine). All three agree to the cent for every cash figure below, unless a row says otherwise.
- **Sealed outcomes:** `services/api/data/sealed_outcomes/` was not opened. **Reveal** was not clicked on any case (no
  forecast can be saved without the local model, so the button stays disabled). No replay outcome appears in this document.
- **Screenshots:** `docs/screenshots/finance-review/` (light theme, 1440 px wide).

Demo business used everywhere (MATH_MODEL §10, SYNTHETIC): weekly sales 50,000, margin g = 0.35, same-week collection
a = 0.8, supplier lag L_p = 2 weeks, payroll 12,000, opex 6,000, 600,000 floating loan at 8.0% (interest 923.08 a
week), C_0 = 100,000, floor C_min = 25,000, I_0 = 65,000, I_min = 40,000. It loses 1,423.08 a week before any shock,
so with no shock cash ends at 100,000 − 26 × 1,423.08 = 63,000.

## Summary

| Screen | ✓ | Issues | Most important issue |
|---|---|---|---|
| Header (every screen) | 2 | 1 | "Case: NOT AVAILABLE · No case loaded" even after a case is chosen (F1) |
| REWIND | 10 | 2 | "Historical timeline" on the SYNTHETIC case (F10) |
| DECISION | 19 | 7 | Fed frame assumes a planned cut while the market priced 0.855 for a hold (F5); break-even rule can hide the switching point (F7); supply frame's 3-week outage vs the case's 5-day trigger (F8) |
| CASCADE | 25 | 8 | Readouts never show the 25,000 floor, so "$13,950 · runway > 26 weeks" looks safe (F2); runway wording (F3); highest feasible floor rounded up (F4) |
| CASCADE · Judge's Challenge | 10 | 0 | All 8 challenges match hand arithmetic; "Local plant closes" is the one where Protect payroll visibly matters |
| REVEAL | 6 | 1 | "provenance: RECORDED_RUN" printed next to NOT AVAILABLE (F19) |
| RESEARCH LENS | 5 | 2 | Cutoff defaults to *now*, so "public at cutoff" shows 6 sources for the July case instead of 4 (F9) |
| LIVE EXPLORE | 4 | 0 | ✓ honest NOT AVAILABLE (no Tavily key); X.2–X.4 not reachable |
| **Total** | **81** | **21** | 24 fixes listed: 1 blocking for demo, 8 should-fix, 14 nits (F14 and F22 are nits on rows that are otherwise ✓), and 1 demo-script tip (F23). See [Fixes to file](#fixes-to-file) |

---

## Header (shown on every screen)

| # | Label / number on screen | What it should mean | Checked value | Result |
|---|---|---|---|---|
| H1 | `API ONLINE` | `/api/health` answered | `{"status":"ok", ...}` | ✓ |
| H2 | `LOCAL MODEL UNAVAILABLE` | Ollama not reachable | health: `"ollama": false, "model_ready": false` | ✓ honest NOT AVAILABLE |
| H3 | `CASE ∅ NOT AVAILABLE: NO CASE LOADED` | which replay case is selected | shown on REWIND, DECISION, CASCADE, … *after* `fomc-2026-jul` was selected, while the panels below show that case (screenshot `header-no-case-loaded.png`) | **Issue F1** (hard-coded in `app/layout.tsx`) |

## Screen 1: REWIND

Checked with `fomc-2026-jul` and `synthetic_distributor-depot`.

| # | Label / number on screen | What it should mean (doc) | Checked value | Result |
|---|---|---|---|---|
| R1 | `GET /api/cases · 5 cases` | count of served cases | API: 5 items (4 `REAL_HISTORICAL`, 1 `SYNTHETIC`) | ✓ |
| R2 | Cutoff `2026-07-22 00:00 UTC` (July case), `2026-09-14 12:00 UTC` (synthetic) | `as_of` of the case (SPEC §1) | API `as_of` `2026-07-22T00:00:00Z`, `2026-09-14T12:00:00Z` | ✓ |
| R3 | `Horizon 7 days after cutoff` / `7 d` (July) | days from the cutoff to the end of the question window | `horizon_days = 7` → the window ends 2026-07-29 00:00 UTC (the integrity panel prints the same instant). The FOMC statement on the meeting's second day (July 29) is released at about 2 p.m. ET, roughly 18:00 UTC, i.e. after that instant | **Issue F11** (nit) |
| R4 | `Horizon 21 d` (synthetic) | question window | criteria say "within the 21 days after the cutoff" | ✓ |
| R5 | `REAL HISTORICAL` / `SYNTHETIC` badges | provenance (AGENTS.md §4) | API `provenance` per case | ✓ |
| R6 | `Market quote kalshi:KXFEDDECISION-26JUL-H0` | the market used as baseline; `H0` = "hold", which is YES for this question | the question is "leave the target range unchanged?" | ✓ |
| R7 | `4 evidence ids` + titles (July) | items the temporal gate admits at the cutoff | API evidence route: 4 items; integrity panel: "4 of 4 … 0 dated after the cutoff" | ✓ |
| R8 | `Contamination risk: unlikely` | case opened after the model's release | model card: training data to 2023-12, release 2024-07-23; case in 2026 | ✓ |
| R9 | `Snapshot e54cf9f4312d…204bf9` | hash of the as-of snapshot | equals API `snapshot_hash` (not recomputed here) | ✓ |
| R10 | `SEALED FUTURE · Withheld until reveal` | outcome not served before reveal | the case payload has no outcome-like key | ✓ |
| R11 | `A.0 HISTORICAL TIMELINE` on the SYNTHETIC case | — | the case is fictional, so "historical" over-claims (the badge next to it correctly says SYNTHETIC) | **Issue F10** (nit) |
| R12 | `Question criteria … Settlement rule text, not the result` | rule text only | matches API `question_criteria` | ✓ |

## Screen 2: DECISION

### B.0–B.3, B.7: forecast and market

| # | Label / number on screen | What it should mean (doc) | Checked value | Result |
|---|---|---|---|---|
| D1 | `B.0 Agent decision · NOT AVAILABLE`, `Local model unavailable … No decision is invented.` | no run is possible without Ollama | health: model not ready | ✓ honest NOT AVAILABLE |
| D2 | `B.1 Agent probability · P(YES) · FORECAST · NOT AVAILABLE` | agent p from a saved run | no run | ✓ honest NOT AVAILABLE |
| D3 | `RECORDED RUN: NOT AVAILABLE` | no committed recorded run | `data/recorded_runs/` holds only a README | ✓ |
| D4 | `Market baseline · P(YES) 0.855` (July) | MATH_MODEL §7: last quote with `as_of − 24h ≤ ts ≤ as_of`, bid/ask midpoint preferred | last Kalshi quote at `2026-07-22T00:00:00Z`: bid 0.85, ask 0.86 → (0.85 + 0.86)/2 = **0.855**, `quote_kind = midpoint` | ✓ |
| D5 | Label under it: "market-implied probability (price-derived; affected by fees, spread, liquidity), not a true probability" | §7 wording | verbatim from the API | ✓ |
| D6 | `0.350` with `SYNTHETIC`, "SYNTHETIC benchmark price written by the case author; not from any market, not a true probability", "no raw payload (synthetic)" (synthetic case) | §7 synthetic benchmark (#102) | API: `venue = synthetic`, `p_yes = 0.35`, ts 11:00 UTC, 1 h before the 12:00 cutoff (inside 24 h) | ✓ |
| D7 | June / September / October cases: B.2 | §7: no quote in the 24 h window → NOT AVAILABLE | API `market_at_cutoff.status = NOT AVAILABLE`, note "no market quote within 24h before the cutoff", for all three | ✓ honest NOT AVAILABLE |
| D8 | `B.3 Evidence citations · NOT AVAILABLE`, `B.7 Run record · NOT AVAILABLE` | run-only fields | no run | ✓ honest NOT AVAILABLE |

### B.4–B.6: ACT / WAIT / HEDGE split view (MATH_MODEL §8)

V(a, y) = min_t C_t (lowest cash over 26 weeks), E[V | a] = p·V(a,1) + (1 − p)·V(a,0). All policies are evaluated with
Protect payroll on (the frames' setting); I also re-ran with it off and every number is identical (no policy cuts payroll).

**Fed case (`fomc-2026-jul` → frame `fomc-rate-decision`), p = market 0.855.**
YES (hold) = rate 25 bp above plan from week 2: 600,000 × 0.25% / 52 = 28.846 a week × 25 weeks = 721.15 less cash.
NO (cut) = the planning path (no shock). ACT trims purchases 125 a week for weeks 1–8 (1,000); HEDGE for weeks 1–4 (500).
A purchase cut is a permanent cash gain in this model (§3: I_t = I_{t−1} − v_t, sales unchanged), and every path's
lowest point is week 26, so it adds 1,000 (ACT) or 500 (HEDGE) in both states.

| Policy | V(a, YES) hand | V(a, NO) hand | E[V] at 0.855 hand | On screen | Result |
|---|---|---|---|---|---|
| ACT | 63,000 − 721.15 + 1,000 = 63,278.85 | 64,000.00 | 0.855 × 63,278.846 + 0.145 × 64,000 = 63,383.41 | $63,278.85 / $64,000.00 / $63,383.41 | ✓ |
| WAIT | 62,278.85 | 63,000.00 | 62,383.41 | $62,278.85 / $63,000.00 / $62,383.41 | ✓ |
| HEDGE | 62,778.85 | 63,500.00 | 62,883.41 | $62,778.85 / $63,500.00 / $62,883.41 | ✓ |

**Synthetic case (`synthetic_distributor-depot` → frame `supply-disruption`), p = SYNTHETIC price 0.35.**
YES = primary distributor down weeks 5–7, φ = 0.40: lost sales 0.4 × 50,000 × 3 = 60,000, cash cost 0.35 × 60,000 = 21,000.
ACT = backup supplier: fee 2,000 in both states, premium 0.12 × 0.65 × 20,000 × 3 = 4,680 if YES.
HEDGE = draw 21,000 in week 4, repay in week 12: interest 21,000 × (8% + 2%) / 52 × 8 weeks = 323.08 in both states.

| Policy | V(a, YES) hand | V(a, NO) hand | E[V] at 0.35 hand | On screen | Result |
|---|---|---|---|---|---|
| ACT | 63,000 − 2,000 − 4,680 = 56,320 | 61,000 | 0.35 × 56,320 + 0.65 × 61,000 = 59,362 | $56,320.00 / $61,000.00 / $59,362.00 | ✓ |
| WAIT | 63,000 − 21,000 = 42,000 | 63,000 | 55,650 | $42,000.00 / $63,000.00 / $55,650.00 | ✓ |
| HEDGE | 41,676.92 | 62,676.92 | 55,326.92 | $41,676.92 / $62,676.92 / $55,326.92 | ✓ |

| # | Label / number on screen | What it should mean (doc) | Checked value | Result |
|---|---|---|---|---|
| D9 | `Recommendation at market p: ACT` (both cases) | §8: largest E[V] among policies feasible in both states | Fed: ACT is largest at every p (API at p = 0, 0.35, 0.855, 1: ACT). Synthetic: ACT 59,362 > WAIT 55,650 > HEDGE 55,326.92 | ✓ |
| D10 | `market p (market-implied, price-derived) = 0.8550` / `market p (SYNTHETIC price) = 0.3500` | the p used for E[V], with its provenance | 0.855 and 0.35 | ✓ (4 decimals here, 3 on B.2: F13, nit) |
| D11 | `Break-even p* = 0.1225 between ACT and WAIT` (synthetic) | §8: p* = (V(b,0) − V(a,0)) / ((V(a,1) − V(a,0)) − (V(b,1) − V(b,0))) | (63,000 − 61,000) / ((56,320 − 61,000) − (42,000 − 63,000)) = 2,000 / 16,320 = 0.12255 | ✓ |
| D12 | Fed: "NOT AVAILABLE: ACT and HEDGE differ by the same amount in both states, so their ranking does not change with P(YES)." | §8: parallel lines → NOT AVAILABLE | ACT − HEDGE = +500 in both states | ✓ |
| D13 | Break-even rule in general | should say at which p the *recommendation* changes | API at p = 0.05 and 0.10 (synthetic frame): recommendation WAIT, break-even "NOT AVAILABLE: WAIT and HEDGE differ by the same amount … ranking does not change with P(YES)", yet WAIT switches to ACT at p = 0.1225. The §8 rule compares only the top two policies, so below p = 0.1028 (where HEDGE overtakes ACT for second place) the real switching point is hidden. Not visible today (no agent p), but it would be with a low agent forecast | **Issue F7** |
| D14 | `✓ FEASIBLE IN BOTH STATES` | §8: keeps every §4 constraint in YES and NO | API `constraints_checked`: C_t ≥ 25,000, 0 ≤ B_t ≤ 150,000, I_t ≥ 40,000, B_T ≤ B_0, simulator accepts, payroll protected; the lowest V on screen is 41,676.92 > 25,000 | ✓ (wording nit F22) |
| D15 | `Forecast does not change the call: In this model the recommendation does not depend on the forecast: purchase cuts raise cash in both states.` (Fed frame) | frame caveat | true arithmetic (D9), but the reason is the MVP simplification that cutting purchases never loses a sale (§3), and the only cost of a cut, the non-cash c_v, is not in V. Without that sentence a judge reads "the AI always says cut purchases" | **Issue F6** |
| D16 | Fed frame "NO: … shock_if_no is the 25bp cut the planning path already assumes" | frame assumption: the CFO's plan assumes a cut "as if markets expected a cut. If a real case's market priced a hold at the cutoff, the shocks must be re-anchored for that case." | the July market priced **0.855 for a hold** at the cutoff (D4), so by the frame's own rule it should be re-anchored. Re-anchored (plan = hold): WAIT 63,000 / 63,721.15, ACT 64,000 / 64,721.15, HEDGE 63,500 / 64,221.15 (YES / NO); the recommendation (ACT) does not change | **Issue F5** |
| D17 | Supply frame `YES: The disruption happens: the primary distributor cannot deliver for 3 weeks.` (synthetic case) | YES of the case question | the case's YES is "no deliveries on at least 5 consecutive calendar days within 21 days". A 5-day stop is about 1 week, not 3. Engine with a 1-week outage (week 5, φ = 0.4): V(WAIT, YES) = 56,000, V(ACT, YES) = 59,440 → p* = 2,000 / 5,440 = **0.3676**, and at p = 0.35 WAIT wins (E[V] 60,550 vs 60,454). So "ACT" on screen depends on assuming the longest outage | **Issue F8** |
| D18 | Footnote "lowest simulated cash balance, min_t C_t … SIMULATED payoffs of a SYNTHETIC business, never trading P&L." | §8 | matches the API `payoff` text | ✓ |
| D19 | Footnote ends "NOT AVAILABLE: this frame does not model a hike" (Fed frame, before any reveal) | the frame's `not_modelled_note`, meant for the reveal | reads like an error on the DECISION screen | **Issue F12** (nit) |
| D20 | `SIMULATED: PAYOFFS` + `SYNTHETIC` on B.4–B.6; frame selector "ILLUSTRATIVE policies, SYNTHETIC business" | provenance | API `provenance = SIMULATED`, `business_provenance = SYNTHETIC`, `frame_provenance = ILLUSTRATIVE` | ✓ |
| D21 | `FEES (n)` lists, e.g. "600,000 x 0.25% / 52 x 25 weeks = 721.15 (weeks 2-26, YES only, in payoff)" | every cost, in or out of V | 721.15 ✓; 4,680 ✓; 323.08 ✓; CPI frame 663.46 (28.846 × 23) ✓ and 0.35 × 20,250 = 7,087.50 ✓; the c_v, c_b, c_y lines are correctly marked "not in payoff" | ✓ (no $ signs: F14, nit) |
| D22 | V and E[V] shown to the cent (`$63,383.41`); CASCADE shows whole dollars | display precision | values are exact model outputs; cents suggest more precision than a synthetic model has | **Issue F13** (nit) |
| D23 | Frames status | `decision_frames.json` says "Proposal for finance-owner review (issue #45). Not signed off." | not shown anywhere on screen | **Issue F21** (nit) |
| D24 | `B.8 Protect payroll is a hard solver constraint · 4 probed · OFF cut payroll 4 · ON largest payroll-cut share 0` | §4.5 | my own probe: all 8 Judge's Challenges and all 4 presets with Protect payroll on → no payroll cut in any plan; "Local plant closes" → NO FEASIBLE PLAN | ✓ |
| D25 | `Training data ends (model card) 2023-12 · Public release 2024-07-23` | Llama 3.1 8B model card | matches the public model card | ✓ |
| D26 | `B.8 … 6 passed · 0 failed · 3 not available` | integrity checks; the 3 run checks need a saved run | no run | ✓ honest NOT AVAILABLE |

## Screen 3: CASCADE

### Readouts C.2, graph C.0, inputs C.1 (no shock and "Bad quarter")

Bad quarter (preset `bad-quarter`, SYNTHETIC): +200 bp from week 1; demand −20% in weeks 3–8 with a 4-week recovery;
primary distributor down in weeks 5–7, φ = 0.40.
Hand check of the total hit: interest 600,000 × 2% / 52 × 26 = 6,000. Lost demand 10,000 × 6 weeks + recovery
(7,500 + 5,000 + 2,500 + 0) = 75,000. The outage (weeks 5–7) hits the already-reduced 40,000: 0.4 × 40,000 × 3 = 48,000.
Lost sales of 123,000 cost 0.35 × 123,000 = 43,050 once settled. Total 49,050 → ending cash 63,000 − 49,050 = 13,950.

| # | Label / number on screen | What it should mean (doc) | Checked value | Result |
|---|---|---|---|---|
| C1 | No shock: `Minimum cash $63,000 · $0 vs baseline`, `Week of minimum cash week 26 of 26`, `Runway > 26 weeks`, `Ending cash $63,000` | §3, §10 baseline | 100,000 − 26 × 1,423.08 = 63,000 at week 26; never negative | ✓ |
| C2 | Status line `C_0 $100,000 · T = 26 wk · fictional demo business` | §10 | C_0 = 100,000, T = 26 | ✓ |
| C3 | Bad quarter: `Minimum cash $13,950`, sublabel `-$49,050 vs baseline $63,000` | min_t C_t and Δ (§5) | 13,950 (hand above; API 13,949.999999999944) | ✓ |
| C4 | `Week of minimum cash week 26 of 26` | argmin | week 26; the mid-horizon low is week 7 at 25,523 | ✓ |
| C5 | `Runway > 26 weeks` | §3: first t with C_t < 0, else "> T weeks" | cash never goes below 0 | ✓ (but see C6, C7) |
| C6 | No readout shows the **25,000 floor** | §4.1 liquidity floor C_min; §10 "the cash a CFO would not plan to go below" | the bad quarter is **below the floor in weeks 20–26** (first week 20; the API cash path and my recurrence agree). With "Runway > 26 weeks" next to "$13,950" the screen reads as safe (screenshot `cascade-bad-quarter-readout.png`) | **Issue F2** |
| C7 | `Runway` with the value `week 9` (supplier-insolvency challenge) or `> 26 weeks` | §3 | values correct, but one is a week number and the other a length of time; finance readers take "runway" as a duration (cash ÷ burn) | **Issue F3** |
| C8 | `Ending cash $13,950 · week 26 · -$49,050 vs baseline $63,000` | C_T and Δ | 13,950 | ✓ |
| C9 | Graph `Demand: peak Δ -$10,000 in week 3` | §5 Δ at the peak week, S^dem | 0.2 × 50,000 = 10,000 (weeks 3–8 tie; the first week is shown) | ✓ |
| C10 | `Supplier: peak Δ -100 pp in week 5` | κ_t from 1 to 0 | −100 percentage points | ✓ |
| C11 | `Rate: +200 bp in week 1, Δ at end +200 bp` | Δr | +0.02 | ✓ |
| C12 | `Sales: peak Δ -$26,000 in week 5` | S_t | −10,000 demand − 0.4 × 40,000 outage = −26,000 | ✓ |
| C13 | `Receipts: peak Δ -$26,000 in week 6` | R_t = 0.8 S_t + 0.2 S_{t−1} | week 6: 0.8 × 26,000 + 0.2 × 26,000 = 26,000 | ✓ |
| C14 | `Purchases: peak Δ -$16,900 in week 5`, `Payables: peak Δ -$16,900 in week 7` | P_t = 0.65 S_t, paid 2 weeks later | 0.65 × 26,000 = 16,900 | ✓ |
| C15 | `Interest: peak Δ +$231 in week 1` | J_t = D r_t / 52 | 600,000 × 0.02 / 52 = 230.77 | ✓ |
| C16 | `Cash: peak Δ -$64,515 in week 7, Δ at end -$49,050` | cumulative | through week 7: receipts −92,800, payables +29,900, interest −1,615.38 → −64,515.38 | ✓ |
| C17 | Inputs: `Drop δ 20% · Start t1 wk 3 · End t2 wk 8 · Recovery ρ 4 wk · Δr +200 bp · Start t_r wk 1 · Outage 3 wk · Start wk 5 · Dependent φ 40%` | the shock actually sent | equals `GET /api/scenarios` → `bad-quarter` | ✓ |
| C18 | `φ default 40% = demo business φ (MATH_MODEL §10, assumed placeholder).` | §10 φ = 0.40 `[assumed]`, signed off 2026-11-12 | value right; "placeholder" undersells a signed-off assumption | **Issue F17** (nit) |
| C19 | Other presets (via the API): rate +200 bp → 57,000; demand −20% → 36,750; outage 3 wk → 42,000; all at week 26, runway > 26 | hand: 63,000 − 6,000; 63,000 − 0.35 × 75,000; 63,000 − 0.35 × 60,000 | 57,000; 36,750; 42,000 | ✓ |

### Recovery plan C.3 and Protect payroll (`POST /api/optimize`)

| # | Label / number on screen | What it should mean (doc) | Checked value | Result |
|---|---|---|---|---|
| C20 | No shock: `Chosen actions (0) · No action needed`, `Min cash after plan $63,000 · week 26`, `Objective -6.3 · disruption cost 0` | §4 objective J = Σ c·x − ε μ, ε = 10⁻⁴ | −0.0001 × 63,000 = −6.3 | ✓ |
| C21 | Bad quarter, Protect payroll **off**: 7 purchase cuts, week 18 `$1,127`, weeks 19–24 `$1,654` each | least-harmful plan | API: 1,126.92 + 6 × 1,653.85 = 11,050.02 ≈ 25,000 − 13,950 = 11,050. 1,653.85 = weekly burn 1,423.08 + extra interest 230.77; each cut pays off 2 weeks later (L_p = 2), in weeks 20–26 | ✓ |
| C22 | `Min cash after plan $25,000 · week 20` | floor held exactly; first tied week (#147) | weeks 20–26 all at 25,000 | ✓ |
| C23 | `Objective 550 · disruption cost 552.5` | c_v Σ v − ε μ | 0.05 × 11,050 = 552.50; 552.50 − 0.0001 × 25,000 = 550.00 | ✓ |
| C24 | `Binding constraints: liquidity floor, week 20 … week 26` | slack ≈ 0 | C_t = 25,000 in weeks 20–26 | ✓ |
| C25 | Protect payroll **on**: the same 7 cuts and objective 550; note "On: the optimizer may not cut payroll (z_t = 0)" | §4.5 | API identical for on and off. Correct: a purchase cut costs c_v = 0.05 per $, a payroll cut c_z = 5.00 per $ (100× more), so payroll is never the cheapest lever here. The switch does not change this plan; DEMO_SCRIPT step 3 already says so (screenshot `cascade-bad-quarter-plan-protect-on.png`) | ✓ (demo tip: F23) |
| C26 | After **Apply plan**: `Minimum cash $25,000 · -$38,000 vs baseline`, `week 20`, `Ending cash $25,000`; graph `Inventory: Δ -$11,050`, `Payables: Δ at end -$1,654` | plan re-simulated by `/api/simulate` | 13,950 + 11,050 = 25,000; I_26 = 65,000 − 11,050 = 53,950 ≥ 40,000; the week-26 payable is week 24's purchases (cut 1,653.85) | ✓ |
| C27 | `Purchase cut · week 18 $1,127` | week the purchase is reduced | right, but the cash arrives in week 20 (L_p = 2) while the floor binds from week 20; a judge asks "why cut in week 18?" | **Issue F15** (nit) |
| C28 | `OBJECTIVE 550` | J(x) | right, but a bare number with no unit or formula | **Issue F16** (nit) |
| C29 | `Off: payroll cuts allowed up to z̄` | z̄ = 0.10 (§10) | jargon; the 10% value is not shown | **Issue F18** (nit) |
| C30 | `NO FEASIBLE PLAN · … The highest minimum cash any plan can reach is $20,187.50` and `Highest floor a plan can hold: $20,188` (plant closure, Protect payroll on) | §4 diagnostic | API `max_feasible_cash_floor = 20,187.50` (= −4,812.50 + 25,000 of purchase cuts, the I_0 − I_min cap). The whole-dollar line rounds **up**: a floor of $20,188 cannot be held (screenshot `cascade-plant-closure-protect-on.png`) | **Issue F4** |
| C31 | Plant closure: `Ending cash -$4,813`, sublabel `-$67,812 vs baseline $63,000` | C_T and Δ | exact values −4,812.50 and −67,812.50; the two roundings go opposite ways, so 63,000 − 67,812 ≠ −4,813 | **Issue F20** (nit) |
| C32 | `SIMULATED` + `SYNTHETIC` badges on C.0, C.2, C.3; `SYNTHETIC: INPUTS` on C.1 | provenance | API labels | ✓ |
| C33 | Status lines `POST /api/simulate · 200 · … ms`, `debounced 150 ms · one request in flight` | real request state | matches the network log (no failed request, no console error) | ✓ |

### Judge's Challenge (C.1, `GET /api/judge-challenges`, ILLUSTRATIVE shock, SIMULATED result)

Every row: on-screen readouts = API = my recurrence. "Plan" is C.3 with Protect payroll off / on.

| Challenge | Hand check of the hit | Min cash (week) | Ending | Runway | Plan off / on | Result |
|---|---|---|---|---|---|---|
| Key distributor's dock strike (weeks 2–5, φ 0.6) | 0.35 × 0.6 × 50,000 × 4 = 42,000 | $17,885 (wk 5) | $21,000 | > 26 | cut 4,006 in wk 3 + revolver 3,109 in wk 5, repaid wk 6; same with payroll protected | ✓ |
| Rate shock +150 bp | 600,000 × 1.5% / 2 = 4,500 | $58,500 (26) | $58,500 | > 26 | no action | ✓ |
| Surprise Fed hike +100 bp | 600,000 × 1.0% / 2 = 3,000 | $60,000 (26) | $60,000 | > 26 | no action | ✓ |
| Flood: demand halves for 3 weeks | 0.35 × (75,000 + 12,500 + 10,000) = 34,125 | $28,875 (26) | $28,875 | > 26 | no action | ✓ |
| Primary supplier goes bust (10 wk, 10% of deliveries kept, φ 0.5) | 0.35 × 0.45 × 50,000 × 10 = 78,750 | −$19,154 (wk 11) | −$15,750 | week 9 | backup supplier → min cash 43,450 (= 63,000 − 2,000 − 0.12 × 0.65 × 22,500 × 10) | ✓ |
| Deli line food-safety recall (15%, 6 wk) | 0.35 × 7,500 × 6 = 15,750 | $47,250 (26) | $47,250 | > 26 | no action | ✓ |
| Hot CPI print | interest 1,990.38 + 0.35 × 46,250 = 18,177.88 | $44,822 (26) | $44,822 | > 26 | no action | ✓ |
| Local plant closes (−25%, 12 wk, 8-wk recovery) | 0.35 × 193,750 = 67,812.50 | −$4,813 (26) | −$4,813 | week 20 | **off:** purchase cuts of 25,000 (the inventory cap) + payroll cuts of 4,812.50 in weeks 19–26 (z up to 0.10), objective 25,310; **on:** NO FEASIBLE PLAN, highest floor 20,187.50 | ✓ |

Strike plan check: the week-26 floor needs 4,000 of permanent cash plus one week of revolver interest
(3,109.40 × 10% / 52 = 5.98), so the cut is 4,005.98; the week-5 dip needs 25,000 − 17,884.62 = 7,115.38 = 4,005.98 + 3,109.40.
Disruption cost 0.05 × 4,005.98 + 0.01 × 3,109.40 = 231.39 (on screen 231.39) ✓.
The descriptions (e.g. "reprices the floating term loan and the revolver") match the engine (r_t feeds both J_t and
J^R_t), and each shows its guidance range from `explore_shock_guidance.json`. "Surprise me" is labeled as a fixed order,
not random ✓. The `ILLUSTRATIVE: SHOCK` / `SIMULATED: RESULTS` badges are ✓ (the summary counts these two rows plus the 8 challenges).

## Screen 4: REVEAL

| # | Label / number on screen | What it should mean (doc) | Checked value | Result |
|---|---|---|---|---|
| V1 | `D.0 Historical outcome · SEALED: UNTIL REVEAL`; `Reveal outcome` disabled, "no prediction id" | persist-before-reveal (SPEC §1) | no forecast saved (no model) | ✓ honest NOT AVAILABLE |
| V2 | `D.1 Benchmark … NOT AVAILABLE: no recorded scorecard yet` | `/api/benchmark` serves recorded snapshots only | API `status = NOT AVAILABLE` | ✓ honest NOT AVAILABLE |
| V3 | `STATUS: NOT AVAILABLE · PROVENANCE: RECORDED_RUN` | — | "RECORDED_RUN" beside "NOT AVAILABLE" can be read as "there is a recorded run"; the underscore spelling also differs from the badge "RECORDED RUN" | **Issue F19** (nit) |
| V4 | Scorecard columns `MEAN BRIER · MEAN LOG LOSS · ACCURACY AT 0.5`; rows Agent / Market-only / `Naive baseline (p = 0.5)`; all "not available" | §6 | matches the §6 forecasters and metrics | ✓ |
| V5 | `Δ Brier vs market (paired bootstrap CI)`, `Events scored (n)`, `Sample-size caveat` | §6 | names match §6 | ✓ |
| V6 | "Display rules (MATH_MODEL §6) … fewer than 5 events → INSUFFICIENT DATA … 5 to 29 → small-sample caveat; 'agent better than market' only when the whole interval is below zero, otherwise 'No improvement measured'." | §6 display rules | matches §6 | ✓ |
| V7 | Lede "If the agent did not win, this screen says so." | §6 | consistent with the "No improvement measured" rule | ✓ |

Realized regret (§8) and the outcome card were not checked: they need a saved forecast and a reveal.

## Screen 5: RESEARCH LENS

| # | Label / number on screen | What it should mean (doc) | Checked value | Result |
|---|---|---|---|---|
| E1 | `Replay cutoff · as_of` field and the count `6 shown, 0 not yet public at 2026-11-14T20:00:47Z`; each firm card "`n` SOURCES PUBLIC AT CUTOFF" | the screen's lede: "what was known by the cutoff" | the field defaults to **now**, not to the selected case's cutoff. With the July case selected (cutoff 2026-07-22) it shows 6 sources, including Sequoia's article published 2026-07-23, under "public at cutoff" | **Issue F9** |
| E2 | The same with the cutoff `2026-07-22T00:00:00Z` typed in | point-in-time filter | `4 shown, 2 not yet public`; Sequoia card "0 sources … no source provably public at 2026-07-22T00:00:00Z" (the API agrees) | ✓ |
| E3 | `REAL HISTORICAL` + `RESEARCH CONTEXT`; header "Research context · not VC predictions · no competitive score" | SPEC §7 | labels present on every card | ✓ |
| E4 | Quote kinds: "$300 Million Series C at a $10 Billion pre-money valuation" as DOCUMENTARY FACT; "Traction figures are reported by a16z, not independently verified" | fact vs interpretation | the dollar figures are what the firm states; the summary says traction is self-reported | ✓ |
| E5 | Bessemer "enterprise deployment will 10x" as `QUANTITATIVE FORECAST · NOT SCORABLE` | never scored | labeled, not scored | ✓ |
| E6 | `PUBLISHED NOT AVAILABLE` on undated pages that are still counted "public at cutoff" | availability basis | the basis is an archive capture (e.g. the Link Ventures home page, captured 2025-09-14), which the point-in-time card does not show | **Issue F24** (nit) |
| E7 | `MODEL STANCE · NOT AVAILABLE · No agreement is inferred.` | needs a run | no run | ✓ honest NOT AVAILABLE |

## Screen 6: LIVE EXPLORE (`/explore`, plus panel E.5 on RESEARCH)

| # | Label / number on screen | What it should mean (doc) | Checked value | Result |
|---|---|---|---|---|
| X1 | "CURRENT WEB · NOT POINT-IN-TIME · NEVER GIVEN TO THE BLIND REPLAY"; `LIVE EXPLORE: CURRENT, NOT POINT-IN-TIME` | SPEC §3.3 | labels present | ✓ |
| X2 | After typing a decision and clicking **Research and analyze**: "Live Explore unavailable: TAVILY_API_KEY is not set on this API server. No results are shown, and none are substituted. … code LIVE_EXPLORE_UNAVAILABLE · HTTP 503" | no stand-in answer | API 503 `LIVE_EXPLORE_UNAVAILABLE` | ✓ honest NOT AVAILABLE |
| X3 | E.5 search on RESEARCH (same route) | same | the same 503 | ✓ honest NOT AVAILABLE |
| X4 | "Admin only on the public demo", "Search powered by Tavily" | public-mode gate, sponsor credit | matches `routes/explore.py` | ✓ |

X.2 (evidence cards), X.3 (model-suggested inputs) and X.4 (cascade) could not be reached without Tavily and the model.
From the code, X.4 uses the same readout labels as CASCADE C.2 ("Minimum cash", "Runway", "Week of minimum cash",
"Ending cash"), so fixes F2 and F3 apply there too.

---

## Decision frames: points for Yaseen's sign-off (lead's comment on #88)

The lead asked Yaseen to confirm each frame's levers and amounts in `services/api/data/decision_frames.json` and the
§8 break-even formula, then mark the file signed off in a new PR. What the agent checked, so that Yaseen can decide:

- **Arithmetic:** every fee amount and shock rationale in all three frames is correct (rows D9–D21; CPI frame: rate
  663.46, lost demand 20,250, lost margin 7,087.50, total 7,750.96; API V(WAIT, YES) = 55,249.04 = 63,000 − 7,750.96).
- **Levers:** only §4 actions are used; no payroll cut; purchase cuts stay under I_0 − I_min = 25,000 (the largest
  total is 8,000, in the CPI frame); the revolver draw (21,000) is inside the 150,000 limit and repaid by week 26 (B_T ≤ B_0).
- **Break-even formula (§8):** setting p·V(a,1) + (1 − p)·V(a,0) = p·V(b,1) + (1 − p)·V(b,0) and solving for p gives
  p* = (V(b,0) − V(a,0)) / ((V(a,1) − V(a,0)) − (V(b,1) − V(b,0))), the formula in §8 and in `routes/decision.py`.
  The algebra is right; the choice of *which two policies* to compare is the issue (F7).
- **Open questions only Yaseen can answer** (economic judgement, not code):
  1. Fed frame: keep the "plan assumes a cut" anchor, or re-anchor to what the market priced at each real cutoff (F5)?
  2. Fed and CPI frames: ACT wins at every p because a purchase cut is free cash in the MVP model. Is that acceptable for
     the demo with a clearer caveat (F6), or should V net out the non-cash disruption costs c (a §8 formula change)?
  3. Supply frame: should YES mean a 3-week outage when the synthetic case's YES starts at 5 consecutive days (F8)?
- **Status: signed off.** On 2026-11-14 Yaseen signed off `decision_frames.json`: every frame's levers, fees and amounts,
  and the §8 break-even formula, plus the payroll convention (no policy cuts payroll). The file's `status` now says so (this PR). The sign-off also
  covers the stock-out version of the frames in PR #141 (#103), whose approach Yaseen chose on #103 (stock-out cost,
  plus a 1% demand effect in the Fed frame's YES state), with its parameters σ = 1, θ = 0.20, c_u = 0.01 and
  restaurant σ = 0.5. If #141 merges, question 2 (F6) is answered by it: purchase cuts are no longer free cash.
  Questions 1 (F5) and 3 (F8), and the break-even scope (F7), stay open as known, non-blocking points.

## Wording that could mislead a judge (consolidated)

1. **"No case loaded"** in the header while a case is plainly loaded (F1).
2. **"Runway > 26 weeks"** next to a minimum cash below the CFO floor, with the floor never shown (F2, F3). Say "cash
   stays above zero for all 26 weeks; below the 25,000 floor from week 20".
3. **"Runway: week 9"**: say "cash goes negative in week 9" (F3).
4. **"Recommendation: ACT"** on the Fed case, where ACT wins whatever the forecast (F6): the reason must be on screen.
5. **"the 25bp cut the planning path already assumes"** next to a market price of 0.855 for a hold (F5).
6. **"public at cutoff"** on RESEARCH when the cutoff is today, not the case's (F9).
7. **"Highest floor a plan can hold: $20,188"** rounds a hard limit up (F4).
8. **"Historical timeline"** on a fictional case (F10).
9. **"placeholder"** for φ, a signed-off assumption (F17).
10. Already correct and worth keeping: B.2's "market-implied probability (price-derived; affected by fees, spread,
    liquidity), not a true probability"; the SYNTHETIC benchmark label; "SIMULATED payoffs of a SYNTHETIC business,
    never trading P&L"; every NOT AVAILABLE state checked above.

## Fixes to file

Severity: **blocking for demo** (a judge will see it on the main demo path), **should-fix**, **nit**.
Line numbers are at `426ae5f`.

| ID | Severity | File:line | Current text | Suggested text / change | Why |
|---|---|---|---|---|---|
| F1 | blocking for demo | `apps/web/app/layout.tsx:80-84` | `<ProvenanceBadge kind="NOT AVAILABLE" detail="No case loaded" />` (hard-coded) | Show the selected case from the shared selection (`useSelectedCase`): event id + `REAL HISTORICAL`/`SYNTHETIC` badge; NOT AVAILABLE only when nothing is selected. Also update `docs/DEMO_SCRIPT.md` step 1, which treats this chip as the "cases did not load" signal | The header contradicts the screen on every step of the demo |
| F2 | should-fix | `apps/web/components/cascade/CascadeWorkbench.tsx:388-396` (+ `apps/web/components/explore/ExploreScenario.tsx:452-458`; the API needs a field in `services/api/routes/simulate.py`) | `Minimum cash $13,950` · `-$49,050 vs baseline $63,000` | Add the floor from the API, e.g. sublabel `floor $25,000 · below it in weeks 20–26` (or `stays above the $25,000 floor`). Needs `min_cash_floor` and `first_week_below_floor` in the simulate response | The §4.1/§10 floor is the CFO's real limit; without it the bad quarter looks safe |
| F3 | should-fix | `CascadeWorkbench.tsx:408-422`, `ExploreScenario.tsx:461-469` | `Runway` · `week 9` / `> 26 weeks` | Label `Cash goes negative`; values `in week 9` / `not within 26 weeks`; sublabel `first week C_t < 0 (MATH_MODEL §3)` | "Runway" usually means a duration; the value is a week number |
| F4 | should-fix | `CascadeWorkbench.tsx:782` | `Highest floor a plan can hold: {usd(max_feasible_cash_floor)}` → `$20,188` | Show cents (`$20,187.50`) or round down (`Math.floor`) on this line | A floor rounded up is not feasible; the sentence above it says $20,187.50 |
| F5 | should-fix | `services/api/data/decision_frames.json:49` (assumption) and `:39` (`no_means`) | "the CFO's planning path … already assumes a 25bp cut … If a real case's market priced a hold at the cutoff, the shocks must be re-anchored for that case." | Either re-anchor (plan = hold; YES = no shock; NO = −25 bp from week 2, +721.15) or add to `no_means`: "The market priced a hold at 0.855 at the July 2026 cutoff; this frame keeps the cut-anchored plan for illustration." Yaseen to choose | The frame's own rule is triggered by the only real case with a market price |
| F6 | should-fix | `decision_frames.json:47` and `:115` (`caveat`) | "In this model the recommendation does not depend on the forecast: purchase cuts raise cash in both states." | "In this model the recommendation does not depend on the forecast: the MVP model assumes cutting purchases never loses a sale (MATH_MODEL §3), so a cut raises cash in both states; its only cost, the non-cash disruption cost, is not in V." | Otherwise "the AI always says cut purchases" looks like a finding, not an assumption |
| F7 | should-fix | `docs/MATH_MODEL.md:446-452`, `services/api/routes/decision.py:182-205` | p* only between the top two policies at p; otherwise "NOT AVAILABLE … ranking does not change with P(YES)" | Report the nearest p′ in [0, 1] where the recommended policy changes: the nearest kink of the upper envelope max_a E[V \| a](p) over the policies feasible in both states (cross the recommended policy with each other one, keep the crossings in [0, 1], take the one closest to p). A formula change → MATH_MODEL §8 + finance sign-off | At p = 0.05 or 0.10 (synthetic frame) the screen would say the call never depends on p, while it flips to ACT at 0.1225 |
| F8 | should-fix | `decision_frames.json:183` (`yes_means`) and its `assumptions`; or the synthetic case's criteria (ws:replay) | YES = "cannot deliver for 3 weeks"; the case's YES = "at least 5 consecutive days within 21 days" | Make them match: either the case asks about 15+ consecutive days, or the frame says "assumes a 3-week outage, the long end of a YES; a 1-week outage gives p* = 0.368 and WAIT at p = 0.35" | The ACT recommendation at the SYNTHETIC price depends on the longest outage. The outage window (weeks 5–7) also sits outside the 21-day horizon; V is unaffected (the lowest cash is in week 26), the timing text is not |
| F9 | should-fix | `apps/web/components/ThesisCourt.tsx:431-437` (default), `:350` (label); `docs/DEMO_SCRIPT.md:131-133` | default as_of = now; "`n` sources public at cutoff" | Default the cutoff to the selected case's `as_of`; label "`n` sources public at `<as_of>`". In the demo script use the case cutoff `2026-07-22T00:00:00Z` (the same 4 shown / 2 held back as `2026-07-01`) | The lede promises "what was known by the cutoff" |
| F10 | nit | `apps/web/components/screens/RewindScreen.tsx:118` | `A.0 Historical timeline` | `A.0 Case timeline` (or `Fictional timeline` when `c.synthetic`) | "Historical" over-claims for the SYNTHETIC case |
| F11 | nit | case data `horizon_days` of the FOMC cases (ws:replay) | `Horizon 7 days after cutoff` → ends 2026-07-29 00:00 UTC | 8 days, or show the end instant and "statement on July 29, about 18:00 UTC" | The window ends before the decision is announced |
| F12 | nit | `apps/web/components/decision/SplitView.tsx:225` | the footnote ends "NOT AVAILABLE: this frame does not model a hike" | "If NO turns out to be a hike: NOT AVAILABLE, this frame does not model a hike." | Reads like an error before any reveal |
| F13 | nit | `SplitView.tsx:39` (USD with cents), `:42` (p to 4 decimals) | `$63,383.41`, `0.8550` | Whole dollars as on CASCADE, and 3 decimals for p as on B.2 (or say why the precision differs) | The same quantities appear at different precision on adjacent panels |
| F14 | nit | `decision_frames.json` `policies[].summary` and `fees[].amount` | "Trim purchases by 125 a week", "600,000 x 0.25% / 52 x 25 weeks = 721.15" | "$125 a week", "$600,000 × 0.25% / 52 × 25 weeks = $721.15" | Units |
| F15 | nit | `CascadeWorkbench.tsx:822-825` | `Purchase cut · week 18` | `Purchase cut · week 18 (cash in week 20, supplier lag 2 wk)` | Explains why the cuts start before the floor binds |
| F16 | nit | `CascadeWorkbench.tsx:842-846` | `Objective 550 · disruption cost 552.5` | `Disruption cost 552.50 (non-cash) · objective 550 = cost − 0.0001 × min cash` | A bare objective number confuses non-specialists |
| F17 | nit | `CascadeWorkbench.tsx:315` | "(MATH_MODEL §10, assumed placeholder)" | "(MATH_MODEL §10, assumed; signed off 2026-11-12)" | φ is a signed-off assumption |
| F18 | nit | `CascadeWorkbench.tsx:662` | "Off: payroll cuts allowed up to z̄" | "Off: payroll may be cut by up to 10% a week (z̄)" (value served by the API) | Jargon; the cap is not shown |
| F19 | nit | `apps/web/components/Scorecard.tsx:104` | `status: NOT AVAILABLE · provenance: RECORDED_RUN` | When the status is NOT AVAILABLE: `provenance: RECORDED RUN (none recorded yet)` | Avoids implying that a recorded run exists |
| F20 | nit | `CascadeWorkbench.tsx:73` (`usd`) | ending `-$4,813` and Δ `-$67,812` for the exact −4,812.50 / −67,812.50 | Round the delta as (rounded scenario − rounded baseline), or show cents when a value ends in .50 | The two displayed figures should add up |
| F21 | nit | `SplitView.tsx` (frame selector, around line 116) | the frames' status is not shown | Show `GET /api/decision/frames` `status` ("Proposal … Not signed off") until Yaseen signs off | Honest status of the assumptions on screen |
| F22 | nit | `SplitView.tsx:271` | `Feasible in both states` | Add a title or sublabel: "cash ≥ $25,000, inventory ≥ $40,000, revolver within limit, in both outcomes" | "Feasible" is solver jargon |
| F23 | demo tip (not a defect) | `docs/DEMO_SCRIPT.md:92-101` | Protect payroll is shown on the bad quarter, where it changes nothing | Optional: after the bad quarter, pick the Judge's Challenge "Local plant closes": off → a plan with $4,812.50 of payroll cuts; on → NO FEASIBLE PLAN, highest floor $20,187.50 | Shows the guarantee biting, with numbers from the API |
| F24 | nit | `ThesisCourt.tsx` (point-in-time cards) | `PUBLISHED NOT AVAILABLE` on a card counted "public at cutoff" | Add "public from archive capture `<available_at>`" | Explains why an undated page passes the filter |

Not counted above (not a finance label, noted for the lead): the REVEAL D.3 integrity panel says "no case selected"
while a case is selected (DECISION B.8 uses it).

## What could not be checked

- **Anything that needs a forecast** (no Ollama on this machine): B.0 chosen path, B.1 agent probability, B.3 citations,
  B.7 run record, "E[V] at agent p", "Recommendation at agent p", the "Model chose" marker, and every REVEAL number
  (outcome, realized regret, scorecards). These showed honest NOT AVAILABLE states only.
- **Recorded scorecards and calibration** (§6): none is recorded on `main`.
- **LIVE EXPLORE X.2–X.4** (no `TAVILY_API_KEY`): only the unavailable state and the shared readout code were checked.
- **The restaurant business (§10b)** and the **optional DSCR covenant (#149)** appear on no screen and are not used by
  any route, so they were out of scope here.
- **Dark theme and the 1920 × 1080 projector layout:** text was read at 1600 × 1000 and screenshots were taken at
  1440 px in the light theme.
- **Hashes** (snapshot, raw quote `raw_sha256`) were compared with the API, not recomputed.
