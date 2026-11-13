# FAULTLINE web

Next.js (App Router) + TypeScript + Tailwind v4 + React Flow. Presenter flow for SPEC §2.

```bash
cd apps/web
npm ci
npm run dev        # http://localhost:3000 (/ is the Rewind screen)
npm run typecheck  # tsc --noEmit
npm run lint       # eslint (flat config, eslint-config-next)
npm run build
FAULTLINE_STATIC_EXPORT=1 npm run build   # static export to out/ (no server needed)
```

`NEXT_PUBLIC_API_BASE` (default `http://localhost:8000`; an empty value also falls back) points at `services/api`.
It is read at build/dev start. The browser calls it directly, so:

- the API must allow CORS from the web origin;
- **mixed content:** a site served over `https://` (e.g. GitHub Pages) cannot call an `http://` API. Browsers block
  the request and the header shows "API unavailable". Use an `https://` API base for hosted builds, or run both
  locally over `http://`.

The app has no API routes or server actions.

## Screens

`/rewind` → `/decision` → `/cascade` → `/reveal` → `/research`, grouped under THEN / DECISION / REVEAL.
`←` / `→` move between screens (ignored while focus is in an input or slider).

## Design

Tokens live in `app/globals.css` as CSS variables (`--bg`, `--bg-elevated`, `--border`, `--text`, `--accent`, …),
dark by default, light via `prefers-color-scheme` or the header toggle (`[data-theme]`). Semantics: viable = cyan,
fail/infeasible = magenta, risk = amber, info = blue. The light theme darkens those four hues so text labels meet
WCAG AA on the light background. `--edge` (graph strokes, arrowheads, handles) is at least 3:1 on both backgrounds
in both themes. Fonts are self-hosted and a clean build needs no network: Geist + Geist Mono (`geist` package) and
Instrument Serif, vendored under `app/fonts/instrument-serif/` (SIL OFL 1.1, license alongside) and loaded with
`next/font/local`.

`ProvenanceBadge` accepts the backend's wire values (`REAL_HISTORICAL`, `SYNTHETIC`, `RECORDED_RUN`, `SIMULATED`,
`ILLUSTRATIVE`) and displays the spaced labels.

## Honesty rules in code

- Only `GET /api/health` is wired (`lib/api.ts`). Every other panel renders **NOT AVAILABLE** and names the endpoint
  it needs (`PENDING_ENDPOINTS`).
- Every panel takes a required `provenance` prop, so there is no way to render a data surface without a label.
- The cascade network is **ILLUSTRATIVE**: structure from MATH_MODEL §2–§3, no values and no flow animation.
- `FinancialReadout` takes `value: number | null`; `null` renders NOT AVAILABLE, and a count-up always ends exactly
  on the API value.
- `prefers-reduced-motion` disables animations and transitions globally (`app/globals.css`).
