# 300 AI Hackathon: facts every agent and teammate should know

Source: https://scion.events/300-hackathon (read 2026-11-13). Presented by Northeastern University and SCION Events,
in person at 300 Mass Ave, Boston. The timezone is not stated on the page; **assume US Eastern** (Boston) and confirm with the organizers.

## Deadlines (this is what we plan against)
| When | What |
|---|---|
| Thu Nov 12, 9pm | The clock started |
| **Sat Nov 14, 1pm** | **Practice demos**. Aim to have the golden path working end to end by now |
| **Sun Nov 15, 11am** | **The clock stops**. Hard code freeze; merge nothing after this |
| Sun Nov 15, 1pm | Demo Day 1.0 |
| Sun Nov 15, 4pm | Wrap-up |
| Thu Nov 19, 4:30pm | Finals: the top five pitch again (300 Launch Week) |

Not on the page: submission format (repo, video, deck, forms), demo length, judge assignments. Ask the organizers; the
demo script (#46) assumes the 90–120 s golden path from SPEC §2.

## Judging criteria (no weights published)
1. **Demo and pitch**
2. **Investability**
3. **Product**
4. **Societal impact**
5. **+2 bonus: AI alignment**

How FAULTLINE maps to them (use this framing in the pitch, PRs, and docs):
- **AI alignment (+2):** the core design *is* alignment: the LLM never does authoritative arithmetic; a deterministic
  engine and optimizer decide; humans stay in control (no money, trades, loans, or payroll actions are executed);
  sealed point-in-time evaluation; honest "No improvement measured / INSUFFICIENT DATA" results; four independent audit
  rounds on the integrity core. Never trade honesty for a flashier claim. That would cost this bonus.
- **Investability:** decision intelligence for small-business operators, fractional CFOs and advisors ("Test the decision
  before you live with it"); an auditable backtest of whether research agents + market probabilities add signal.
- **Societal impact:** protects jobs (Protect payroll is a hard solver constraint), small-business resilience to rate,
  demand and supply shocks.
- **Product / demo:** the live CASCADE stress test, the Blind Replay on real FOMC decisions, the Research Lens, and LIVE EXPLORE.

## Sponsors (use them visibly, honestly)
| Sponsor | Where we use them |
|---|---|
| **Anthropic** | Claude (Claude Code built this repo; optional hosted-Claude comparator in replay, always labeled "hosted-model comparison, not air-gapped") |
| **Link Ventures** | One of the four VC Research Lenses (SPEC §7), with verified, dated sources |
| **Tavily** | LIVE EXPLORE (#60, #61): live research for "test a decision today", plus Tavily-assisted evidence curation; never inside the sealed replay |

Paper-plate awards (voted by everyone) include Best pitch, Crowd favorite, Most investable, Most impactful, Most tokens spent.

## Rules of thumb for agents
- Everything should be demo-able by **Sat 1pm** practice demos; polish after that.
- After **Sun 11am**, nothing merges.
- Prefer finishing and hardening the golden path over new scope (SPEC §1 rule 10: "Reliability beats scope").
