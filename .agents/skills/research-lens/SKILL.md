---
name: research-lens
description: Curating the four public VC research lenses (Link Ventures, a16z, Sequoia, Bessemer) into data/research_lenses.json with dates, permalinks, theses, quoted evidence, and limitations, and the Thesis Court feature that filters them by as_of. Use for work on research_lenses.json, the /api/vc-lenses route, ThesisCourt, or DATA_PROVENANCE.md.
---

# Research lenses (SPEC §7)

- Minimum one hand-verified public source per firm; 4–8 total. Starting points are listed in SPEC §7/§12.
  **Fetch each page and confirm title, date, and quotes yourself.** Do not write a quote you did not read on the page.
- Record per item: `firm, title, url, published_at, archived_url (if any), accessed_at, thesis, hypotheses[],
  quotes[{text, kind}]` where kind ∈ `documentary_fact | analyst_interpretation | quantitative_forecast`, and `limitations`.
- Known dates: Sequoia × Etched **2026-07-23**; Bessemer State of AI 2025 **2025-08-13**; a16z Investing in Stitch **2026-05-13**.
  A lens is eligible for a replay only if `published_at <= as_of` (filter in code + test).
- Labels: `RESEARCH CONTEXT`, never "VC prediction". Never compute or display a "VC accuracy" or a "we beat <firm>" score.
- Portfolio pages are not records of rejected deals or returns; say so in `limitations`.
- Yaseen (finance) reviews the accuracy of thesis summaries; flag items for his review in the PR.
