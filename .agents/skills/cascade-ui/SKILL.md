---
name: cascade-ui
description: Frontend and visual design system for FAULTLINE - Next.js App Router + TypeScript + Tailwind + Framer Motion + React Flow; the REWIND/DECISION/CASCADE/REVEAL/RESEARCH screens, the dependency-network cascade graph, timeline, ACT/WAIT/HEDGE split view, financial readouts, provenance badges, accessibility. Use for any work in apps/web/.
---

# Cascade UI (SPEC §2, §8)

## Aesthetic (non-negotiable)
Premium financial terminal. Tokens in `apps/web/app/globals.css`:
`--bg #070B14` (near-black navy) · `--panel #0D1424` · `--text #F2EDE4` (warm off-white) · `--muted #8A93A6` ·
`--risk #F5A524` (amber) · `--viable #19D3C5` (electric teal) · `--fail #E5484D` (crimson). Numbers in a tabular mono
(`font-variant-numeric: tabular-nums`; e.g. JetBrains Mono / IBM Plex Mono via next/font), headings large and tight.
No stock/AI-generated imagery. No generic SaaS cards-with-shadows.

## Honesty in the UI
- Every number comes from the API. **No hardcoded results, no fake "thinking..." sequences.** Loading states reflect real requests.
- Provenance badge on every panel: `AS-OF` `SEALED` `VERIFIED` `FORECAST` `REVEALED` `SIMULATED` `SYNTHETIC` `RECORDED RUN` `NOT AVAILABLE` `INSUFFICIENT DATA`.
  Badges are text + color (never color alone).
- Model down → explicit "Local model unavailable" state; simulator/optimizer still interactive.

## Structure
- `lib/api.ts`: typed client mirroring the Pydantic models (keep in sync; one source: generate from FastAPI OpenAPI if time allows).
- Components: `ReplayTimeline`, `CascadeGraph` (React Flow, custom nodes; edge width/glow ∝ |Δ| from `/api/simulate`), `DecisionBranches`,
  `Scorecard`, `ThesisCourt`, `EvidenceDrawer`, `FinancialReadout` (animated count-up to the exact API value; final frame equals the value).
- Sliders/toggles (demand shock %, rate Δ, outage weeks, Protect payroll) debounce ~150 ms → `/api/simulate` + `/api/optimize`.
  `NO FEASIBLE PLAN` renders in crimson with the binding constraint named.
- 16:9 projector first (1920×1080), usable at 390 px wide. Keyboard focus visible; `prefers-reduced-motion` disables particles/springs.

## Verify
`npm run typecheck && npm run lint && npm run build` in `apps/web`. Run the dev server and click the golden path
(SPEC §2) end to end before shipping; mention in the PR what you actually clicked.
