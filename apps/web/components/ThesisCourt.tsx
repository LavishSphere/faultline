"use client";

import { useCallback, useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { API_BASE, PENDING_ENDPOINTS } from "@/lib/api";
import {
  VC_LENSES_PATH,
  getVcLenses,
  type LensLiveExplore,
  type LensPointInTime,
  type LensQuote,
  type QuoteKind,
  type VcLensesResponse,
  type VcLensesResult,
} from "@/lib/vcLenses";
import { Field, NotAvailable, Panel } from "./Panel";
import { ProvenanceBadge } from "./ProvenanceBadge";

/**
 * Thesis Court (SPEC §2 Screen E, §7): four firms' dated public research from GET /api/vc-lenses.
 *
 * - Point-in-time: the presenter types an exact UTC instant; the API alone decides which lenses were provably
 *   public then (and reports how many it held back). The browser does not filter, sort by date, or score.
 * - Live Explore: every curated item with its sourcing, explicitly not filtered to any cutoff.
 *
 * Everything here is RESEARCH CONTEXT: public writing by the firms, not forecasts attributed to them and never scored.
 * Firm names are fixed by SPEC §7 (layout only); every title, date, link, thesis and quote comes from the response.
 */

type Mode = "point_in_time" | "live_explore";

/** SPEC §7 firms, spelled exactly as the API's `firm` field (core/research.py FIRMS). */
const FIRMS = [
  { code: "E.1", name: "Link Ventures" },
  { code: "E.2", name: "Andreessen Horowitz (a16z)" },
  { code: "E.3", name: "Sequoia Capital" },
  { code: "E.4", name: "Bessemer Venture Partners" },
] as const;

const KIND_META: Record<QuoteKind, { label: string; glyph: string; className: string; description: string }> = {
  documentary_fact: {
    label: "Documentary fact",
    glyph: "¶",
    className: "border-info/60 text-info",
    description: "documentary_fact: a statement of what the source says or records",
  },
  analyst_interpretation: {
    label: "Analyst interpretation",
    glyph: "≈",
    className: "border-accent/60 text-accent-hover",
    description: "analyst_interpretation: opinion or characterization; not testable as stated",
  },
  quantitative_forecast: {
    label: "Quantitative forecast",
    glyph: "◇",
    className: "border-risk/60 text-risk",
    description: "quantitative_forecast: contains a number and a horizon; FAULTLINE does not score it",
  },
};

type View =
  | { kind: "idle" }
  | { kind: "loading"; mode: Mode; asOf: string | undefined }
  | { kind: "done"; mode: Mode; asOf: string | undefined; result: VcLensesResult };

/** Current instant as `YYYY-MM-DDTHH:MM:SSZ`: only a suggested input; the API validates and normalizes it. */
function nowUtcInstant(): string {
  return new Date().toISOString().replace(/\.\d{3}Z$/, "Z");
}

function requestUrl(asOf: string | undefined): string {
  return `${API_BASE}${VC_LENSES_PATH}${asOf === undefined ? "" : `?as_of=${encodeURIComponent(asOf)}`}`;
}

function displayHref(url: string): string {
  try {
    const u = new URL(url);
    return `${u.host}${u.pathname === "/" ? "" : u.pathname}`;
  } catch {
    return url;
  }
}

function Tag({ children, className = "", title }: { children: ReactNode; className?: string; title?: string }) {
  return (
    <span
      title={title}
      className={`inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-sm border px-1.5 py-[3px] font-mono text-[10px] font-medium uppercase leading-none tracking-[0.1em] ${className}`}
    >
      {children}
    </span>
  );
}

function ResearchContextTag() {
  return (
    <Tag
      className="border-line-strong text-text-2"
      title="Public writing by the firm, shown as context. Not a prediction by the firm and never scored."
    >
      <span aria-hidden="true">§</span>
      <span>Research context</span>
    </Tag>
  );
}

function ExternalLink({ href, children, className = "" }: { href: string; children: ReactNode; className?: string }) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className={`break-all text-accent underline decoration-line-strong underline-offset-4 hover:text-link-hover hover:decoration-current ${className}`}
    >
      {children}
      <span aria-hidden="true"> ↗</span>
      <span className="sr-only"> (opens in a new tab)</span>
    </a>
  );
}

function Missing({ children = "Not available" }: { children?: ReactNode }) {
  return <span className="font-mono uppercase tracking-[0.08em] text-muted">{children}</span>;
}

function QuoteKindBadge({ quote }: { quote: LensQuote }) {
  const meta = KIND_META[quote.kind];
  return (
    <span className="flex flex-wrap items-center gap-1.5">
      <Tag className={meta.className} title={meta.description}>
        <span aria-hidden="true">{meta.glyph}</span>
        <span>{meta.label}</span>
      </Tag>
      {quote.kind === "quantitative_forecast" ? (
        quote.scorable === false ? (
          <Tag className="border-fail/60 text-fail" title="The API marks this forecast scorable: false">
            <span aria-hidden="true">⊘</span>
            <span>Not scorable</span>
          </Tag>
        ) : quote.scorable === true ? (
          <Tag className="border-line-strong text-text-2" title="The API marks this forecast scorable: true">
            <span>Scorable · not scored here</span>
          </Tag>
        ) : (
          <Tag
            className="border-dashed border-line-strong text-muted"
            title="The API response carries no `scorable` field for this quote"
          >
            <span aria-hidden="true">∅</span>
            <span>Scorability not available</span>
          </Tag>
        )
      ) : null}
    </span>
  );
}

function isLive(item: LensPointInTime | LensLiveExplore): item is LensLiveExplore {
  return "limitations" in item && Array.isArray((item as LensLiveExplore).limitations);
}

function LensCard({ item, mode }: { item: LensPointInTime | LensLiveExplore; mode: Mode }) {
  // Curation fields render only for a Live Explore response; a point-in-time body never shows them.
  const live = mode === "live_explore" && isLive(item) ? item : null;
  return (
    <article className="flex flex-col gap-4 border-t border-line pt-5 first:border-t-0 first:pt-0" aria-label={item.title}>
      <header className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center gap-1.5">
          <ResearchContextTag />
          {live?.source_type ? (
            <span className="font-mono text-[10px] uppercase tracking-[0.12em] text-muted">
              {live.source_type.replaceAll("_", " ")}
            </span>
          ) : null}
        </div>
        <h4 className="text-[17px] font-medium leading-snug text-text">{item.title}</h4>
        <p className="font-mono text-[11px] leading-relaxed">
          <ExternalLink href={item.url}>{displayHref(item.url)}</ExternalLink>
        </p>
      </header>

      <dl>
        <Field label="Published" value={item.published_at ?? undefined} />
        {live ? (
          <>
            {live.published_at === null && live.published_at_basis ? (
              <p className="pb-2 text-[11px] leading-relaxed text-muted">{live.published_at_basis}</p>
            ) : null}
            <Field label="Proven public by" value={live.available_at} />
            <p className="pb-2 text-[11px] leading-relaxed text-muted">{live.available_at_basis}</p>
            <Field
              label="Archive"
              value={
                live.archived_url ? (
                  <ExternalLink href={live.archived_url} className="font-mono text-[11px]">
                    {live.archived_at ?? "capture"}
                  </ExternalLink>
                ) : undefined
              }
            />
            <Field label="Accessed" value={live.accessed_at} />
          </>
        ) : null}
      </dl>

      <section>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="kicker">Thesis summary</p>
          {live?.thesis_review ? (
            <Tag className="border-dashed border-risk/60 text-risk" title="thesis_review, as served by the API">
              {live.thesis_review}
            </Tag>
          ) : null}
        </div>
        <p className="mt-2 text-sm leading-relaxed text-text-2">{item.thesis}</p>
      </section>

      <section>
        <p className="kicker">
          Quoted evidence <span className="num text-text-2">({item.quotes.length})</span>
        </p>
        {item.quotes.length === 0 ? (
          <p className="mt-2 text-xs">
            <Missing />
          </p>
        ) : (
          <ul className="mt-3 flex flex-col gap-4">
            {item.quotes.map((q, i) => (
              <li key={i} className="flex flex-col gap-2">
                <QuoteKindBadge quote={q} />
                <blockquote className="border-l border-line-strong pl-3 text-sm leading-relaxed text-text">
                  “{q.text}”
                </blockquote>
                {live && q.note ? <p className="pl-3 text-[11px] leading-relaxed text-muted">Curator note: {q.note}</p> : null}
              </li>
            ))}
          </ul>
        )}
      </section>

      {item.hypotheses.length > 0 ? (
        <details className="group rounded-md border border-line px-3 py-2">
          <summary className="cursor-pointer list-none font-mono text-[11px] uppercase tracking-[0.12em] text-text-2 marker:hidden">
            <span aria-hidden="true" className="mr-2 inline-block transition-transform group-open:rotate-90">
              ›
            </span>
            Hypotheses <span className="num text-muted">({item.hypotheses.length})</span>
          </summary>
          <ul className="mt-2 flex list-disc flex-col gap-2 pl-5 text-xs leading-relaxed text-text-2">
            {item.hypotheses.map((h, i) => (
              <li key={i}>{h}</li>
            ))}
          </ul>
        </details>
      ) : null}

      <section>
        <p className="kicker">Limitations</p>
        {live ? (
          live.limitations.length ? (
            <ul className="mt-2 flex list-disc flex-col gap-1.5 pl-5 text-xs leading-relaxed text-text-2">
              {live.limitations.map((l, i) => (
                <li key={i}>{l}</li>
              ))}
            </ul>
          ) : (
            <p className="mt-2 text-xs">
              <Missing />
            </p>
          )
        ) : (
          <p className="mt-2 text-xs leading-relaxed text-muted">
            <Missing>Not available at a cutoff.</Missing>{" "}
            {mode === "point_in_time"
              ? "The point-in-time response carries content fields only (curation notes are dated after most cutoffs). Switch to Live Explore to read them."
              : null}
          </p>
        )}
      </section>
    </article>
  );
}

function FirmColumn({
  code,
  name,
  view,
}: {
  code: string;
  name: string;
  view: View;
}) {
  const result = view.kind === "done" ? view.result : null;
  const data: VcLensesResponse | null = result && result.ok ? result.data : null;
  const items = data ? (data.items as (LensPointInTime | LensLiveExplore)[]).filter((it) => it.firm === name) : [];
  // Dataset missing = nothing to count from. A point-in-time cutoff with zero eligible items but a real
  // excluded count (e.g. 2023: "6 not yet public") is NOT a missing dataset.
  const datasetMissing =
    data !== null &&
    data.status !== "AVAILABLE" &&
    data.items.length === 0 &&
    (data.mode === "live_explore" || data.excluded_not_yet_public === null);

  let body: ReactNode;
  if (view.kind === "idle" || view.kind === "loading") {
    body = (
      <p className="font-mono text-[11px] uppercase tracking-[0.12em] text-muted">
        {view.kind === "loading" ? "Awaiting API response" : "No request yet"}
      </p>
    );
  } else if (!data) {
    body = <NotAvailable size="sm" note="No research lens data: see the request status above." />;
  } else if (datasetMissing) {
    body = <NotAvailable size="sm" note="The API reports the research lens dataset NOT AVAILABLE (see its notes above)." />;
  } else if (items.length === 0) {
    body = (
      <NotAvailable
        size="sm"
        note={
          data.mode === "point_in_time"
            ? `The API returned no ${name} source provably public at ${data.as_of}.`
            : `The API returned no ${name} source.`
        }
      />
    );
  } else {
    body = (
      <div className="flex flex-col gap-6">
        {items.map((item) => (
          <LensCard key={item.id} item={item} mode={data.mode} />
        ))}
      </div>
    );
  }

  return (
    <Panel
      code={code}
      title="Research context"
      provenance={data && items.length > 0 ? data.provenance : "NOT AVAILABLE"}
      className="h-full"
    >
      <div className="flex h-full flex-col gap-5">
        <div className="flex flex-col gap-2">
          <h3 className="display text-3xl text-text md:text-[2.5rem]">{name}</h3>
          <p className="font-mono text-[11px] uppercase tracking-[0.12em] text-muted">
            {data && !datasetMissing ? (
              <>
                <span className="num text-text-2">{items.length}</span>{" "}
                {items.length === 1 ? "source" : "sources"}
                {data.mode === "point_in_time" ? " public at cutoff" : " · unfiltered"}
              </>
            ) : (
              "Sources: not available"
            )}
          </p>
        </div>
        {body}
        <dl className="mt-auto border-t border-line pt-3">
          <Field label="Model stance" />
          <p className="pt-1 font-mono text-[10.5px] leading-relaxed text-muted">
            Requires a recorded replay run ({PENDING_ENDPOINTS.replayRun}, not wired). No agreement is inferred.
          </p>
        </dl>
      </div>
    </Panel>
  );
}

function errorHeading(result: Extract<VcLensesResult, { ok: false }>): string {
  return result.kind === "network" || result.kind === "timeout"
      ? "API unreachable"
      : result.kind === "validation"
        ? "Cutoff rejected by the API (422)"
        : result.kind === "not_found"
          ? "This API build does not serve /api/vc-lenses"
          : result.kind === "malformed"
            ? "Response did not match the contract"
            : result.kind === "aborted"
              ? "Request cancelled"
              : `API error${result.status ? ` (HTTP ${result.status})` : ""}`;
}

function ErrorReport({ result }: { result: Extract<VcLensesResult, { ok: false }> }) {
  const heading = errorHeading(result);
  const tone = result.kind === "validation" ? "text-risk" : "text-fail";
  return (
    <div className="flex flex-col gap-2">
      <p className={`font-mono text-sm font-medium uppercase tracking-[0.1em] ${tone}`}>
        <span aria-hidden="true">{result.kind === "validation" ? "△ " : "✕ "}</span>
        {heading}
      </p>
      <p className="whitespace-pre-line text-sm leading-relaxed text-text-2">{result.message}</p>
      {result.code ? (
        <p className="font-mono text-[11px] text-muted">
          code <span className="text-text-2">{result.code}</span>
          {result.status ? <> · HTTP {result.status}</> : null}
        </p>
      ) : null}
      {result.errors.length ? (
        <ul className="flex flex-col gap-1 font-mono text-[11px] text-text-2">
          {result.errors.map((e, i) => (
            <li key={i}>
              <span className="text-muted">{e.loc.join(".")}:</span> {e.msg}
            </li>
          ))}
        </ul>
      ) : null}
      {result.kind === "malformed" ? (
        <p className="text-xs text-muted">Shown as NOT AVAILABLE; nothing from this response is displayed.</p>
      ) : null}
    </div>
  );
}

export function ThesisCourt() {
  const [mode, setMode] = useState<Mode>("point_in_time");
  const [draft, setDraft] = useState("");
  const [view, setView] = useState<View>({ kind: "idle" });
  const inflight = useRef<AbortController | null>(null);

  const run = useCallback(async (nextMode: Mode, asOf: string | undefined) => {
    inflight.current?.abort();
    const controller = new AbortController();
    inflight.current = controller;
    setView({ kind: "loading", mode: nextMode, asOf });
    const result = await getVcLenses(asOf, controller.signal);
    if (controller.signal.aborted) return;
    setView({ kind: "done", mode: nextMode, asOf, result });
  }, []);

  useEffect(() => {
    // First request after mount: point-in-time at the current instant (a suggested cutoff the presenter can edit).
    const first = setTimeout(() => {
      const now = nowUtcInstant();
      setDraft(now);
      void run("point_in_time", now);
    }, 0);
    return () => {
      clearTimeout(first);
      inflight.current?.abort();
    };
  }, [run]);

  function submit(e: FormEvent) {
    e.preventDefault();
    setMode("point_in_time");
    void run("point_in_time", draft);
  }

  function switchMode(next: Mode) {
    setMode(next);
    void run(next, next === "point_in_time" ? draft : undefined);
  }

  const result = view.kind === "done" ? view.result : null;
  const data = result && result.ok ? result.data : null;
  const loading = view.kind === "loading";
  const pending = view.kind === "idle" ? null : requestUrl(view.asOf);
  /** Dataset missing on the server: no count is shown, only NOT AVAILABLE. */
  // Dataset missing = nothing to count from. A point-in-time cutoff with zero eligible items but a real
  // excluded count (e.g. 2023: "6 not yet public") is NOT a missing dataset.
  const datasetMissing =
    data !== null &&
    data.status !== "AVAILABLE" &&
    data.items.length === 0 &&
    (data.mode === "live_explore" || data.excluded_not_yet_public === null);
  const liveMessage =
    view.kind === "loading"
      ? "Requesting research lenses"
      : result && !result.ok
        ? errorHeading(result)
        : data && datasetMissing
          ? "Research lens dataset not available"
          : data?.mode === "point_in_time"
            ? `${data.items.length} shown, ${data.excluded_not_yet_public} not yet public at ${data.as_of}`
            : data
              ? `Live Explore, not filtered to any cutoff: ${data.items.length} items`
              : "";
  const knownFirms = new Set<string>(FIRMS.map((f) => f.name));
  const otherFirms = data
    ? Array.from(new Set((data.items as { firm: string }[]).map((i) => i.firm))).filter((f) => !knownFirms.has(f))
    : [];

  const segment =
    "flex-1 rounded-[5px] px-3 py-2 font-mono text-[11px] uppercase tracking-[0.12em] transition-colors sm:flex-none";

  return (
    <div className="flex flex-col gap-6">
      <Panel
        code="E.0"
        title="Thesis Court · cutoff"
        provenance={mode === "point_in_time" ? "AS-OF" : "NOT AVAILABLE"}
        provenanceDetail={mode === "point_in_time" ? "UTC instant" : "No cutoff (Live Explore)"}
      >
        <div className="grid grid-cols-1 gap-6 xl:grid-cols-12 xl:gap-10">
          <div className="flex flex-col gap-4 xl:col-span-7">
            <div
              role="group"
              aria-label="Research lens mode"
              className="flex w-full gap-1 rounded-md border border-line bg-bg/60 p-1 sm:w-fit"
            >
              <button
                type="button"
                aria-pressed={mode === "point_in_time"}
                onClick={() => switchMode("point_in_time")}
                className={`${segment} ${mode === "point_in_time" ? "bg-accent-soft text-text" : "text-muted hover:bg-hover hover:text-text"}`}
              >
                Point-in-time
              </button>
              <button
                type="button"
                aria-pressed={mode === "live_explore"}
                onClick={() => switchMode("live_explore")}
                className={`${segment} ${mode === "live_explore" ? "bg-accent-soft text-text" : "text-muted hover:bg-hover hover:text-text"}`}
              >
                Live Explore
              </button>
            </div>

            <form onSubmit={submit} className="flex flex-col gap-2">
              <label htmlFor="thesis-as-of" className="kicker">
                Replay cutoff · as_of (exact instant, UTC)
              </label>
              <div className="flex flex-col gap-2 sm:flex-row">
                <input
                  id="thesis-as-of"
                  type="text"
                  inputMode="text"
                  autoComplete="off"
                  spellCheck={false}
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  placeholder="2026-07-01T00:00:00Z"
                  aria-describedby="thesis-as-of-help"
                  className={`num min-w-0 flex-1 rounded-md border border-line-strong bg-bg px-3 py-2.5 text-lg text-text placeholder:text-muted/70 focus:border-accent focus:outline-none md:text-xl ${mode === "live_explore" ? "opacity-50" : ""}`}
                />
                <div className="flex gap-2">
                  <button
                    type="submit"
                    className="flex-1 rounded-md border border-accent/70 bg-accent-soft px-4 py-2.5 font-mono text-[11px] uppercase tracking-[0.14em] text-text transition-colors hover:bg-accent/20 sm:flex-none"
                  >
                    Apply cutoff
                  </button>
                  <button
                    type="button"
                    onClick={() => setDraft(nowUtcInstant())}
                    className="flex-1 rounded-md border border-line px-4 py-2.5 font-mono text-[11px] uppercase tracking-[0.14em] text-text-2 transition-colors hover:border-line-strong hover:bg-hover sm:flex-none"
                  >
                    Now
                  </button>
                </div>
              </div>
              <p id="thesis-as-of-help" className="text-xs leading-relaxed text-muted">
                {mode === "live_explore" ? (
                  <>
                    <span className="font-mono uppercase tracking-[0.08em] text-risk">
                      Live Explore: not filtered to any cutoff.
                    </span>{" "}
                    Every curated item is shown with its full sourcing. Never use this view for a Blind Replay. Apply a
                    cutoff to return to point-in-time.
                  </>
                ) : (
                  <>
                    ISO-8601 with an offset, e.g. <code className="text-text-2">2025-09-01T00:00:00Z</code>. Sent to
                    the API as typed; the API validates it, normalizes it to UTC and decides what was public.
                  </>
                )}
              </p>
            </form>
          </div>

          <div className="flex flex-col gap-3 xl:col-span-5">
            <p role="status" aria-live="polite" className="sr-only">
              {liveMessage}
            </p>
            <div className="flex flex-wrap items-center gap-2">
              <ResearchContextTag />
              {data && data.items.length > 0 ? <ProvenanceBadge kind={data.provenance} /> : null}
              {data?.mode === "live_explore" ? (
                <Tag className="border-risk/60 text-risk">Not filtered to any cutoff</Tag>
              ) : null}
            </div>

            {data && datasetMissing ? (
              <NotAvailable size="lg" note="The API has no research lens dataset to serve; no count is shown." />
            ) : data?.mode === "point_in_time" ? (
              <div className="flex flex-col gap-1">
                <p className="num text-[clamp(2.25rem,3.4vw,3.25rem)] font-medium leading-none text-text">
                  {data.excluded_not_yet_public}
                </p>
                <p className="font-mono text-[11px] uppercase tracking-[0.12em] text-text-2">
                  {data.excluded_not_yet_public === 1 ? "item" : "items"} not yet public at this cutoff
                </p>
                <p className="font-mono text-[11px] text-muted">
                  API as_of <span className="text-text-2">{data.as_of}</span> ·{" "}
                  <span className="text-text-2">{data.items.length}</span> shown
                </p>
              </div>
            ) : data?.mode === "live_explore" ? (
              <p className="font-mono text-[11px] text-muted">
                <span className="text-text-2">{data.items.length}</span> curated items · as_of{" "}
                <span className="text-text-2">null</span>
              </p>
            ) : null}

            {loading ? (
              <p className="font-mono text-[11px] uppercase tracking-[0.12em] text-muted">Requesting…</p>
            ) : null}
            {result && !result.ok ? <ErrorReport result={result} /> : null}

            {data ? (
              <div className="flex flex-col gap-1.5">
                <p className="font-mono text-[10.5px] uppercase tracking-[0.1em] text-text-2">{data.mode_label}</p>
                {data.status !== "AVAILABLE" ? (
                  <ProvenanceBadge kind="NOT AVAILABLE" detail="status from API" className="w-fit" />
                ) : null}
                {data.notes.map((n, i) => (
                  <p key={i} className="text-xs leading-relaxed text-muted">
                    {n}
                  </p>
                ))}
              </div>
            ) : null}

            {pending ? (
              <p className="break-all font-mono text-[10.5px] text-muted">
                GET <span className="text-text-2">{pending}</span>
              </p>
            ) : null}
            {result && !result.ok && result.kind !== "aborted" ? (
              <button
                type="button"
                onClick={() => {
                  if (view.kind !== "done") return;
                  setMode(view.mode);
                  void run(view.mode, view.asOf);
                }}
                className="w-fit rounded-md border border-line px-3 py-1.5 font-mono text-[11px] uppercase tracking-[0.12em] text-text-2 transition-colors hover:border-line-strong hover:bg-hover"
              >
                Retry request
              </button>
            ) : null}
          </div>
        </div>
      </Panel>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 2xl:grid-cols-4">
        {FIRMS.map((f) => (
          <FirmColumn key={f.name} code={f.code} name={f.name} view={view} />
        ))}
        {otherFirms.map((name, i) => (
          <FirmColumn key={name} code={`E.${FIRMS.length + i + 1}`} name={name} view={view} />
        ))}
      </div>
    </div>
  );
}
