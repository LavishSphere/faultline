# Investability brief: who pays, how big, how it makes money, why now

**Purpose:** back the *Investability* judging criterion (docs/HACKATHON.md) with cited market facts and a transparent
business-model hypothesis. **Written:** 2026-11-13 for issue #83, against `main` at `54dc86d`.
**Provenance:** market counts are `REAL HISTORICAL` (published statistics, quoted as printed). Market-research figures
are **third-party estimates**. Everything in the pricing and unit-economics section is `ESTIMATE / HYPOTHESIS`.
Nothing here is FAULTLINE output, and there is no traction to report.
**Review:** ☐ Yaseen (finance owner) has checked every figure against its source and signed off the pricing assumptions.

## 1. Who pays

| Customer | What they need | How they buy |
|---|---|---|
| **Fractional CFOs and accounting firms with an advisory practice** (first) | Test a client's decision (rate move, demand drop, supplier loss) before the client lives with it, and show the client an audit trail of what was known and what was computed | Per advisor seat, plus per client business |
| **Owner-operators and finance leads of US employer firms with 20–499 employees** | Same, in-house: cash low point, runway, recovery options under a shock | Per business (entity) |
| Strategy teams and VC analysts (later) | The research lens and the sealed backtest | Not priced in this brief |

FAULTLINE is decision support. It does not give financial advice, lend, trade, or change anyone's employment
(SPEC §1 rule 8).

## 2. Market size (cited)

All sources were accessed **2026-11-13**. "Third-party estimate" means a market-research firm's number from a free
summary page; the full reports are paid and were not read, so their methods are not verified.

| # | Figure, as printed | Year | Publisher, page | Type |
|---|---|---|---|---|
| M1 | **6,395,635** firms (all employer firms); **6,374,594** with "<500 employees"; **5,720,093** with "<20 employees" | 2022 | US Census Bureau, Statistics of U.S. Businesses (SUSB), [S1] | `REAL HISTORICAL` |
| M2 | **654,501** firms with 20–499 employees (561,160 with 20–99 and 93,341 with 100–499) | 2022 | Derived from [S1]: the sum of the printed size bands. Check: 5,720,093 + 654,501 = 6,374,594, the printed "<500" total | Derived from `REAL HISTORICAL` |
| M3 | **120,085** firms in NAICS 5412 "Accounting, Tax Preparation, Bookkeeping, and Payroll Services", of which **50,885** are NAICS 541211 "Offices of Certified Public Accountants" | 2022 | US Census Bureau, SUSB, [S1] | `REAL HISTORICAL` |
| M4 | Client advisory services (CAS) practices "reported a median growth rate of 17%"; "median CAS net client fees per professional (NCFPP) rose to $156,250" | Calendar 2023 data | AICPA and CPA.com, [S2]. Sample: "206 CAS practices who self-selected to participate" | Survey (self-selected) |
| M5 | US fractional CFO services: "USD 2.00 billion" in 2025, "USD 3.95 billion by 2035", "CAGR of 7.00%" | 2025 | Credence Research, [S3] | Third-party estimate |
| M6 | Financial planning software: "valued at USD 5.63 billion in 2024"; "2034 Projected Market Size USD 25.16 Billion" | 2024 | Polaris Market Research, [S4] | Third-party estimate |
| M7 | Financial planning software: "will grow from $5.69 billion in 2025 to $6.69 billion in 2026" | 2025 | The Business Research Company, via GII Research, [S5] | Third-party estimate |

**How to read this.**
- **M1–M2 are the solid numbers.** The SUSB universe is "U.S. business establishments with paid employees", firm size
  is "the summed employment of all associated establishments", and employment is counted "in the pay period including
  March 12" [S1, S1a]. 2022 is the latest year on the SUSB tables page [S1a].
- **M6 and M7 are not our market.** Both define "financial planning software" broadly: their segment lists include
  wealth management, personal banking and individual users, alongside SMEs. They agree with each other (about
  $5.6–5.7 billion, global) but are context for the category, not a figure for SMB decision testing. No source read
  for this brief isolates FP&A software for small businesses, so that figure is **NOT AVAILABLE**.
- **M5 is a single third-party estimate** for the advisory spend our first customers already make. Its page prints no
  publication year ("Last Updated: Nov 11") and labels the 7.00% CAGR as both 2025–2035 and 2026–2035.

**Bottom-up revenue pool (`ESTIMATE`, arithmetic only).** If every firm in M2 paid the SMB entity price assumed in §3
($99 a month): 654,501 × $99 × 12 = **$777.5 million a year**. This is a ceiling on one segment at one price, not a
forecast. Realistic penetration is unknown, and advisor seats sell into the same firms, so the two are not added.

## 3. Pricing and unit economics: `ESTIMATE / HYPOTHESIS`

Every input below is an assumption for the finance owner to set. Where a benchmark informed it, the benchmark is cited;
otherwise it says **assumption**. No price has been tested with a customer.

**Price points (assumption)**, set against competitor list prices in §4: advisor plan **$149 per seat per month plus
$15 per client business per month**; SMB plan **$99 per business per month**.

| Input | Advisor account (1 seat, 12 clients) | SMB business (direct) | Basis |
|---|---|---|---|
| ARPA (average revenue per account), monthly | $149 + 12 × $15 = **$329** | **$99** | Assumption. Client count of 12 is an assumption |
| Gross margin | **65%** | **65%** | Bessemer: "the average gross margin for a cloud business regardless of maturity is 65-70%" [S6]. We take the low end because model and search API costs are unknown |
| Monthly logo churn | **1.5%** | **2.5%** | Assumption, informed by Bessemer gross retention of "85-90%", and "70-80%" for some SMB-focused companies [S6]: 85–90% a year is about 0.9–1.4% a month, 70–80% is about 1.8–2.9% a month (1 − r^(1/12)). Gross retention is a revenue measure, not logo churn |
| CAC (customer acquisition cost) | **$2,500** | **$600** | Assumption. No benchmark read |
| Gross profit per month = ARPA × margin | 329 × 0.65 = **$213.85** | 99 × 0.65 = **$64.35** | Arithmetic |
| CAC payback = CAC ÷ (ARPA × margin) | 2,500 ÷ 213.85 = **11.7 months** | 600 ÷ 64.35 = **9.3 months** | Bessemer target for SMB-focused accounts: "CAC payback <12 months" [S6] |
| LTV = ARPA × margin ÷ monthly churn | 213.85 ÷ 0.015 = **$14,257** | 64.35 ÷ 0.025 = **$2,574** | Arithmetic (no discounting, no expansion revenue) |
| LTV ÷ CAC | **5.7** | **4.3** | Arithmetic |

**Sensitivity.** If advisor CAC doubles to $5,000, payback becomes 5,000 ÷ 213.85 = 23.4 months, outside the SMB target.
If SMB churn is 4% a month, LTV falls to 64.35 ÷ 0.04 = $1,609 and LTV ÷ CAC to 2.7. These two inputs (advisor CAC and
SMB churn) matter most and are the least known.

## 4. Competitors and alternatives

List prices were read on each vendor's public pricing page on 2026-11-13 [S7–S11]; they may have changed since.

| Alternative | What the page says it offers | List price, as printed |
|---|---|---|
| Spreadsheets | Free-form models (our description, not a cited claim): no built-in record of what was known when | No price (already owned) |
| Float [S7] | "13-week cash flow", "36-month forecasts", "8 scenarios" (Growth); accountancy firms, bookkeepers and fractional finance leaders are told to "Talk to us about specific pricing" | Growth: $265/mo billed monthly, $215/mo billed annually |
| Fathom [S8] | "Three-way cash flow forecasting"; "Budgets, scenarios and what-ifs"; a Portfolio plan "designed for accounting firms" | Pro: "$450/ month" with "25 companies included" ("$18.00 per company") |
| LivePlan [S9] | Premium: "Auto-updating profit & cash forecasting"; "Run up to 10 versions of your forecast" | Standard $15/mo, Premium $30/mo, paid annually |
| QuickBooks Online [S10] | "Conversational forecasting": "Run "what-if" scenarios to see how a price change, a new hire, or any big decision will impact your business" (Plus, marked BETA) | Not recorded |
| Bank tools [S11] | Bank of America CashPro Forecasting: "cash forecasting in minutes, not days", for "Corporations & Institutions" | "available at no cost to CashPro users" |
| Enterprise FP&A suites | Not reviewed for this brief | Not recorded |

**Our wedge: auditable decision testing.** What-if forecasting is already sold and is being added to accounting
software (QuickBooks, above). None of the pages above describe what FAULTLINE is built around: every number from a
deterministic engine rather than an AI model, every piece of evidence time-stamped and gated to a knowledge cutoff, and
forecasts scored on sealed history against the market and a naive baseline, with an honest `INSUFFICIENT DATA` when
there are too few cases. What exists today versus in development:

| Capability | Status on `main` (2026-11-13) |
|---|---|
| Deterministic cash-flow engine, synthetic demo business, four named stress scenarios, CASCADE screen | **Merged** (#10, #42, #30) |
| Sealed blind replay core: temporal gate, provenance hashing, sealed-outcome vault, scoring | **Merged** (#29) |
| ACT / WAIT / HEDGE payoff and regret calculations | **Merged** (#35); the split-view screen is in development (#55) |
| Research lens (four VC firms' dated public writing, point-in-time cutoff) | **Merged** (#11, #41) |
| Recovery optimizer with Protect payroll as a hard constraint | **In development** (PR #69; live switch #47, #56) |
| LIVE EXPLORE: current research via Tavily, walled off from the replay | **In development** (PR #73, #61) |
| Real resolved replay cases | **In development** (PR #54) |

FAULTLINE does not claim to beat markets, VCs or competitors. Its scorecard currently reads `INSUFFICIENT DATA`.

## 5. Go-to-market: advisors as the channel (hypothesis)

1. **Design partners (next step, none yet):** a handful of fractional CFOs and CAS practices run FAULTLINE on their own
   clients' decisions, with the clients' consent.
2. **Advisor seat, per-client pricing:** one advisor brings many businesses. Fathom already prices per client company
   for accounting firms, and Float invites accountancy firms and fractional finance leaders to talk about specific
   pricing [S7, S8], so advisors are a recognized buying group in this category.
3. **Client-facing decision reports** (to build): an advisor shares a sealed, reproducible report with the client.
4. **Direct SMB plan later,** for firms that have a finance lead but no advisor.

Why advisors first: 50,885 CPA firms and 120,085 accounting-services firms (M3) already sit beside SMB clients, and the
CAS practices surveyed report 17% median growth (M4, self-selected sample).

## 6. Why now

- **Cost and rate shocks are the common complaint.** See the cited Federal Reserve survey facts in the societal-impact
  brief (docs/IMPACT.md, facts 6–8; PR #96, in review). They are not repeated here.
- **AI use is spreading, unevenly.** The Census Bureau put the national business AI use rate at 19.8% (as of May 3,
  2026), Finance and Insurance at 33.9%; "32% of firms with 100 to 249 employees" and "37% of firms with at least 250
  employees" reported using AI [S12]. As AI enters finance work, a tool that keeps the arithmetic deterministic and
  shows its audit trail answers the obvious trust question.
- **Incumbents are adding what-if features** (QuickBooks, §4), which shows demand and is also our largest risk.

## 7. Traction

None yet (hackathon MVP). No users, pilots, letters of intent, revenue, waitlist or partnerships.

## 8. Risks (candid)

- **Proof is thin.** The demo business is `SYNTHETIC`; there is no real customer data. No real replay cases are merged
  yet (PR #54), and the scorer shows `INSUFFICIENT DATA` below five scored cases. Results on a small replay set may never generalize.
- **Model contamination.** An offline model may already know historical outcomes from training (SPEC §1 rule 5); each
  case carries a contamination flag, which reduces but does not remove this.
- **Advice and liability.** A decision tool used for cash, credit or payroll choices may draw advice-liability or
  regulatory questions. FAULTLINE executes nothing and labels everything, but this is not legal clearance.
- **Data licensing.** Commercial use of prediction-market prices, news and accounting-system data needs licences and
  terms we have not reviewed.
- **Incumbents.** Accounting platforms and banks can bundle forecasting at low or no cost (§4).
- **Unit economics are untested.** Every price, churn and CAC figure in §3 is an assumption.
- **Channel dependence.** Advisors may resist a tool that their clients could later buy directly.

## 9. Three pitch-ready sentences (for the demo script, #46)

1. "The Census Bureau counted about 6.4 million US employer firms in 2022, and about 655,000 of them have 20 to 499
   employees: those operators, and the accountants and fractional CFOs who advise them, are who we sell to."
2. "We sell to advisors first, priced per advisor seat plus a fee per client business, because one advisor brings many
   businesses, and in the 2024 AICPA and CPA.com benchmark survey the advisory practices that took part reported 17%
   median growth."
3. "Forecasting apps already let you ask what-if; FAULTLINE is also built to test its own forecasts on sealed history against the
   market and a naive baseline, and today it honestly says INSUFFICIENT DATA, because a decision tool you can audit is
   one you can trust."

## Sources (all accessed 2026-11-13)

| Ref | Publisher, title | Published | URL | Archive copy |
|---|---|---|---|---|
| S1 | US Census Bureau, "2022 SUSB Annual Data Tables by Establishment Industry"; tables "U.S. and states, NAICS, detailed employment" and "U.S., NAICS sectors, larger employment sizes up to 20,000+" | Release Date: 4/10/2025 | https://www.census.gov/data/tables/2022/econ/susb/2022-susb-annual.html ; https://www2.census.gov/programs-surveys/susb/tables/2022/us_state_naics_detailedsizes_2022.xlsx ; https://www2.census.gov/programs-surveys/susb/tables/2022/us_naicssector_large_emplsize_2022.xlsx | http://web.archive.org/web/20261109202042/https://www.census.gov/data/tables/2022/econ/susb/2022-susb-annual.html ; http://web.archive.org/web/20261014063923/https://www2.census.gov/programs-surveys/susb/tables/2022/us_state_naics_detailedsizes_2022.xlsx |
| S1a | US Census Bureau, SUSB "About", "Glossary" and data-tables pages | Not shown | https://www.census.gov/programs-surveys/susb/about.html ; https://www.census.gov/programs-surveys/susb/about/glossary.html ; https://www.census.gov/programs-surveys/susb/data/tables.html | Not checked |
| S2 | AICPA and CPA.com, "AICPA and CPA.com Benchmark Survey: Client Advisory Services (CAS) Practices Report 17% Growth" | 2024-12-09 | https://www.cpa.com/news/aicpa-and-cpacom-benchmark-survey-client-advisory-services-cas-practices-report-17-growth | http://web.archive.org/web/20260719182158/https://www.cpa.com/news/aicpa-and-cpacom-benchmark-survey-client-advisory-services-cas-practices-report-17-growth |
| S3 | Credence Research, "U.S. Fractional CFO Services Market Size, Share, Growth and Forecast, 2025-2035" | Year not shown ("Last Updated: Nov 11") | https://www.credenceresearch.com/report/us-fractional-cfo-services-market | None found |
| S4 | Polaris Market Research, "Financial Planning Software Market Share, Size, Trends, Industry Analysis Report, 2025 - 2034" | September 2025 | https://www.polarismarketresearch.com/industry-analysis/financial-planning-software-market | http://web.archive.org/web/20260711051311/https://www.polarismarketresearch.com/industry-analysis/financial-planning-software-market |
| S5 | The Business Research Company (listed by GII Research), "Financial Planning Software Global Market Report 2026" | 2026-03-09 | https://www.giiresearch.com/report/tbrc1664303-financial-planning-software-global-market-report.html | Closest snapshot is 2025-09-15, before this edition: not equivalent |
| S6 | Bessemer Venture Partners (Atlas), "Scaling to $100 Million", Mary D'Onofrio, Ethan Ding & Atlas Editors | 2021-09-21 | https://www.bvp.com/atlas/scaling-to-100-million | http://web.archive.org/web/20260910094319/https://www.bvp.com/atlas/scaling-to-100-million |
| S7 | Float, pricing page | Not shown | https://floatapp.com/pricing/ | http://web.archive.org/web/20261017185709/https://floatapp.com/pricing |
| S8 | Fathom, pricing page | Not shown | https://www.fathomhq.com/pricing | http://web.archive.org/web/20261016174052/https://www.fathomhq.com/pricing |
| S9 | LivePlan, pricing page | Not shown | https://www.liveplan.com/pricing | http://web.archive.org/web/20260913143404/https://www.liveplan.com/pricing |
| S10 | Intuit QuickBooks, page served at the URL shown (title "QuickBooks® Online: All-in-One Business Solutions") | Not shown | https://quickbooks.intuit.com/cash-flow/ | Closest snapshot is from 2014: not equivalent |
| S11 | Bank of America, "Turn on the power of CashPro® Forecasting" | Not shown | https://business.bofa.com/en-us/content/cashpro-forecasting.html | http://web.archive.org/web/20261016143748/https://business.bofa.com/en-us/content/cashpro-forecasting.html |
| S12 | US Census Bureau, "Large Firms With at Least 20 Employees Biggest AI Users", Adam Grundy, Cory Breaux and Dhanapati Khatiwoda | 2026-05-26 | https://www.census.gov/library/stories/2026/05/ai-use-businesses.html | http://web.archive.org/web/20261108212155/https://www.census.gov/library/stories/2026/05/ai-use-businesses.html |

Archive links are the closest snapshots reported by the archive.org availability API on 2026-11-13; their contents
were not opened, so they are **not verified**. Census figures were read from the downloaded spreadsheets; web pages
were read through a text-extraction fetch tool.

**Tried and not used:** SBA Office of Advocacy *Frequently Asked Questions About Small Business 2025* (HTTP 403).
MarketsandMarkets and MarketResearch.com (OG Analysis) financial-planning-software pages (HTTP 403). Technavio "AI in
Financial Planning and Analysis Market" (its page prints a "$48.87 B" opportunity next to "USD 410.55 million" without
explanation, and no base-year value, so it was not used). A Client Advisory Services market report on eaglerockcfo.com
(HTTP 404). Xero FY26 results PDF on the ASX (could not extract text). Bank of America's small-business Cash Flow
Monitor (the page read names it but describes no features or price). No SUSB 2023 tables are published yet.
