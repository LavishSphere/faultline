---
name: cascade-ui
description: Frontend and visual design system for FAULTLINE - Next.js App Router + TypeScript + Tailwind + Framer Motion + React Flow; the REWIND/DECISION/CASCADE/REVEAL/RESEARCH screens, the dependency-network cascade graph, timeline, ACT/WAIT/HEDGE split view, financial readouts, provenance badges, accessibility. Use for any work in apps/web/.
---

# Cascade UI (SPEC §2, §8)

## Aesthetic (non-negotiable)
Match the lead's sites (https://khayrul.com, https://vitra.khayrul.com), simplified: calm, editorial, thin borders, panels not heavy cards, light + dark theme toggle.
Tokens in `apps/web/app/globals.css` (dark / light): bg `#0a0e17`/`#f8fafc` · panel `#11161f`/`#ffffff` · hover `#171d29`/`#f1f5f9` · border `#232b3a`/`#e2e8f0` · text `#f1f5f9`/`#0f172a` · text-2 `#cbd5e1`/`#334155` · muted `#7c8aa5`/`#64748b` · accent `#818cf8`/`#6366f1` · link-hover `#f472b6`/`#db2777` · `--edge` ≥ 3:1 contrast for graph lines.
Status: viable cyan `#42e8d3` · fail magenta `#f16c91` · risk amber `#f5a524` · info blue `#66b8ff` (light theme uses darker AA variants). Fonts: Geist, Geist Mono (all numbers, `tabular-nums`), Instrument Serif (display), self-hosted via `geist` + `next/font/local`. Radii 0.25–0.75rem; backdrop-blur(12px) on floating panels; easing cubic-bezier(.22,1,.36,1), ~150ms. Static export only (GitHub Pages): no API routes or server actions.
No stock/AI-generated imagery. No 3D.

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
