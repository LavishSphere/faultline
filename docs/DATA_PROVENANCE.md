# Data provenance

Where each FAULTLINE dataset comes from, how it was checked, and what it must not be used for.
Other workstreams add their own sections (market snapshots, synthetic business data, sealed outcomes).

## Research lenses (`services/api/data/research_lenses.json`)

**Label:** `RESEARCH CONTEXT`. **Provenance:** `REAL_HISTORICAL` (wire value; displayed as "REAL HISTORICAL"):
public documents as published.
These are public writing by four venture firms. They are not predictions by those firms, not records of their
investment decisions, and FAULTLINE never scores them or compares itself against them.

### Items (6; at least one per firm)

| id | Firm | Title | Published (on page) | `available_at` (used for replay) | Archive capture used |
|---|---|---|---|---|---|
| `link-ventures-home` | Link Ventures | Link Ventures \| Backing AI founders from MIT, Harvard, and beyond | NOT AVAILABLE (living page) | 2025-09-14 | 2025-09-14T18:09:05Z |
| `link-ventures-portfolio-ai-power` | Link Ventures | Portfolio \| Link Ventures (Silverton Power, Spinor Energy entries) | NOT AVAILABLE (living page; "Year Invested 2026") | 2026-10-05 | 2026-10-05T00:16:22Z |
| `a16z-fintech-thesis` | Andreessen Horowitz (a16z) | Fintech Investments, Team, & Thesis Overview \| a16z | NOT AVAILABLE as a visible date (JSON-LD datePublished 2023-04-11, dateModified 2026-11-10) | 2023-11-26 | 2023-11-26T11:16:33Z |
| `a16z-investing-in-stitch` | Andreessen Horowitz (a16z) | Investing in Stitch | 2026-05-13 ("Posted May 13, 2026"; JSON-LD 2026-05-14T05:55:55+00:00) | 2026-05-14 | 2026-05-15T01:55:15Z |
| `sequoia-partnering-with-etched` | Sequoia Capital | Partnering with Etched: Building the Inference Machine | 2026-07-23 ("Published July 23, 2026") | 2026-07-23 | 2026-07-23T19:13:59Z |
| `bessemer-state-of-ai-2025` | Bessemer Venture Partners | The State of AI 2025 | 2025-08-13 ("Published on Aug 13, 2025") | 2025-08-13 | 2025-08-13T21:24:01Z |

Full URLs, archive URLs, authors, quotes and limitations are in the JSON file.

### How the items were verified

1. **Fetched each page directly** on 2026-11-13 (03:33 UTC, recorded as `accessed_at`) as raw HTML with `curl`.
   All six URLs returned HTTP 200 with no redirect. Visible text was extracted with a small standard-library HTML
   parser (scripts/styles removed). No summarizing tool was used to produce quotes.
2. **Dates** were read from the page itself: the visible "Published/Posted" line, plus any machine-readable
   timestamps (JSON-LD `datePublished`/`dateModified`, `<time datetime>`). Both are recorded when they differ.
3. **Archive check.** For each page we used the Internet Archive Wayback Machine (CDX listing, raw `id_` captures)
   and confirmed that **every quote appears verbatim** (after collapsing whitespace) in the cited capture, as well as
   on the live page. For dated articles the earliest capture is on or after the displayed date, which corroborates it.
4. **Quotes** are copied exactly, including curly quotes and dashes. Each is classified as:
   - `documentary_fact`: a statement of a fact as documented on the page (deal terms, a stated investment focus,
     a self-reported metric). "Documented" means the firm says it, not that it was independently verified.
   - `analyst_interpretation`: a view, belief, risk framing, or non-numeric expectation.
   - `quantitative_forecast`: a forward-looking claim with a number and a time window. Only one quote has this kind
     (Bessemer: "enterprise deployment will 10x" in 2025–2026), and it has no defined metric, baseline, or resolution
     source, so it cannot be scored as stated. FAULTLINE does not score it.
5. **Thesis summaries and hypotheses are curator paraphrases**, not firm claims. Every hypothesis starts with
   "Curator-derived, not a firm claim". Every item has `thesis_review: "PENDING FINANCE REVIEW (Yaseen)"` until the
   finance owner confirms the summary is accurate.

### Point-in-time rule (`services/api/core/research.py`)

- `published_at` = date shown on the page, or `null` (shown as NOT AVAILABLE) when the page shows none.
- `available_at` = conservative date the quoted text is proven public: the later of the displayed date and the UTC date
  of any machine-readable publish timestamp; for undated living pages, the date of the earliest archive capture we
  checked that contains every quote.
- **`as_of` is the replay instant.** Callers pass a timezone-aware `datetime` (or an ISO-8601 string with an offset).
  Calendar dates, `"YYYY-MM-DD"` strings, and naive datetimes are rejected, so a cutoff can't be silently cut down
  to a day.
- **Day-only item dates are publisher-local**, and the publisher's time zone isn't known, so they are treated
  conservatively. An item dated `D` counts as public only once `D` has ended in every time zone: from
  `D+1 12:00 UTC` (the end of `D` at UTC-12). `eligible_lenses(as_of)` returns only items whose `available_at` and
  `published_at` (when present) both satisfy this.
- Consequences: Sequoia × Etched is first eligible at 2026-07-24T12:00Z; Bessemer State of AI 2025 at
  2025-08-14T12:00Z; a16z Investing in Stitch at 2026-05-15T12:00Z (its `available_at` is 2026-05-14, one day after
  the displayed date, because its JSON-LD timestamp is 2026-05-14 UTC).
- **Prompts get a projection, never the full item.** Full items carry curation metadata dated after most cutoffs
  (`accessed_at` 2026-11-13, archive capture times, page `dateModified`, basis notes). `lens_for_prompt(item, as_of)`
  returns only `id, firm, title, url, published_at` (only if public by `as_of`), `thesis`, `hypotheses`, and quotes
  as `{text, kind}`. It refuses ineligible items. A test walks the projection at every boundary instant and asserts
  that no date string later than `as_of` appears. Bare years inside verbatim quotes are exempt, since they are
  source content (e.g. Bessemer's "2025–2026" horizon).

### Caveats (apply to every item)

- **Portfolio pages are not records of rejected deals or of returns.** They list companies the firm chose to show.
  No item here reveals what a firm declined, what it paid, or how an investment performed.
- **Persuasive writing is not a calibrated forecast.** Investment announcements and thesis pages are written by
  interested parties to promote a view or a portfolio company. Metrics quoted from them (e.g. Stitch's growth
  multiples, Bessemer's benchmark averages) are self-reported and not audited.
- **Living pages change.** The a16z fintech thesis sentence changed wording between the 2023-05-09 capture
  ("…machine learning, and new data sources … reimagine the way we manage our finances") and the 2023-11-26 capture
  ("…AI and machine learning, and new data sources … reimagine the way money moves"). The Link home page wording also
  changed during 2025. Quotes must only be cited for cutoffs on or after their `available_at`.
- **Archive checks were sampled.** We checked roughly monthly captures, not every capture, so for living pages the
  true first appearance of the text may be earlier than `available_at`. This only errs toward excluding a source.
- **No competitive scoring.** FAULTLINE does not compute any score comparing its forecasts or decisions with these
  firms (SPEC §7). A matched comparison would need an explicit, dated, numeric prediction with a verifiable resolution
  source; none of these items has one.

### Sources not used

- `https://linkventures.com/news` was fetched but not used: it lists third-party press headlines about portfolio
  companies, not Link Ventures' own research or thesis.
