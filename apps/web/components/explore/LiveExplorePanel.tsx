"use client";

import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { API_BASE } from "@/lib/api";
import {
  EXPLORE_DEFAULT_MAX_RESULTS,
  EXPLORE_MAX_QUERY_CHARS,
  EXPLORE_MAX_RESULTS,
  EXPLORE_SEARCH_PATH,
  TAVILY_ATTRIBUTION,
  searchLiveExplore,
  type ExploreFailure,
  type ExploreResult,
  type ExploreSearchItem,
} from "@/lib/explore";

/**
 * LIVE EXPLORE (issue #60): current web search via Tavily, shown as a separate section of the RESEARCH screen.
 *
 * - Current, NOT point-in-time. Results are never sent to the Blind Replay, its prompts or the scorecard; the API
 *   enforces that with code boundaries and tests (services/api/tests/test_explore_separation.py), not with this UI.
 * - A search runs only when the presenter submits one (each search spends Tavily credits); nothing runs on mount.
 * - Every title, link, snippet and timestamp is rendered exactly as the API returned it. Missing values render
 *   NOT AVAILABLE. Unavailable states are named honestly: no key on the server, admin only on the public demo, etc.
 */

type View = { kind: "idle" } | { kind: "loading"; q: string } | { kind: "done"; q: string; result: ExploreResult };

const RESULT_COUNTS = Array.from({ length: EXPLORE_MAX_RESULTS }, (_, i) => i + 1);

function LiveExploreBadge() {
  return (
    <span
      className="inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-sm border border-risk/60 bg-risk/10 px-1.5 py-[3px] font-mono text-[10px] font-medium uppercase leading-none tracking-[0.1em] text-risk"
      title="Current web content retrieved now. Not point-in-time; never used by the Blind Replay."
      data-provenance="LIVE EXPLORE"
    >
      <span aria-hidden="true">◎</span>
      <span>Live Explore: current, not point-in-time</span>
    </span>
  );
}

function ExternalLink({ href, children }: { href: string; children: ReactNode }) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer nofollow"
      className="break-words text-accent underline decoration-line-strong underline-offset-4 hover:text-link-hover hover:decoration-current"
    >
      {children}
      <span aria-hidden="true"> ↗</span>
      <span className="sr-only"> (opens in a new tab)</span>
    </a>
  );
}

function host(url: string): string {
  try {
    return new URL(url).host;
  } catch {
    return url;
  }
}

function Missing({ children = "Not available" }: { children?: ReactNode }) {
  return <span className="font-mono uppercase tracking-[0.08em] text-muted">{children}</span>;
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-0.5 border-b border-line/70 py-1.5 last:border-b-0">
      <dt className="text-[11px] uppercase tracking-[0.12em] text-muted">{label}</dt>
      <dd className="num text-right text-xs text-text-2">{children}</dd>
    </div>
  );
}

function ResultCard({ item, index }: { item: ExploreSearchItem; index: number }) {
  return (
    <li className="flex flex-col gap-3 border-t border-line pt-5 first:border-t-0 first:pt-0">
      <div className="flex flex-col gap-1.5">
        <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted">
          <span className="num">{index + 1}</span> · {host(item.url)}
        </p>
        <h4 className="text-[16px] font-medium leading-snug text-text">
          <ExternalLink href={item.url}>{item.title}</ExternalLink>
        </h4>
      </div>
      {item.snippet ? (
        <blockquote className="border-l border-line-strong pl-3 text-sm leading-relaxed text-text-2">
          {item.snippet}
        </blockquote>
      ) : (
        <p className="text-xs">
          <Missing>Snippet not available</Missing>
        </p>
      )}
      <dl>
        <Row label="Published (Tavily estimate)">
          {item.published_at ?? (item.published_at_raw ? `${item.published_at_raw} (as sent)` : <Missing />)}
        </Row>
        <Row label="Retrieved at">{item.retrieved_at}</Row>
      </dl>
    </li>
  );
}

function failureHeading(f: ExploreFailure): string {
  switch (f.kind) {
    case "unavailable":
      return "Live Explore unavailable";
    case "admin_only":
      return "Admin only on the public demo";
    case "rate_limited":
      return "Rate limited";
    case "timeout":
      return "Search timed out";
    case "upstream":
      return "Search provider error";
    case "validation":
      return "Query rejected by the API (422)";
    case "not_found":
      return "This API build does not serve Live Explore";
    case "network":
      return "API unreachable";
    case "aborted":
      return "Request cancelled";
    case "malformed":
      return "Response did not match the contract";
    default:
      return `API error${f.status ? ` (HTTP ${f.status})` : ""}`;
  }
}

function failureNote(f: ExploreFailure): string | null {
  switch (f.kind) {
    case "unavailable": {
      const why =
        f.reason === "not_configured"
          ? "Set a valid TAVILY_API_KEY on the API server."
          : f.reason === "auth_rejected"
            ? "Tavily rejected the key configured on the API server; check or replace it."
            : f.reason === "quota_exceeded"
              ? "The Tavily usage limit for the configured key has been reached."
              : "The API gave the reason above.";
      return `No results are shown, and none are substituted. ${why}`;
    }
    case "admin_only":
      return "Each search spends Tavily API credits, so the public server allows it only with an admin token, which this page never sends. Run FAULTLINE locally to use Live Explore.";
    case "rate_limited":
      return f.retryAfterS ? `Try again in ${f.retryAfterS} s.` : "Try again shortly.";
    case "not_found":
      return `GET ${EXPLORE_SEARCH_PATH} returned 404 from ${API_BASE}.`;
    case "malformed":
      return "Shown as NOT AVAILABLE; nothing from this response is displayed.";
    default:
      return null;
  }
}

function FailureReport({ failure }: { failure: ExploreFailure }) {
  const soft = failure.kind === "unavailable" || failure.kind === "admin_only" || failure.kind === "validation";
  const note = failureNote(failure);
  return (
    <div className="flex flex-col gap-2">
      <p className={`font-mono text-sm font-medium uppercase tracking-[0.1em] ${soft ? "text-risk" : "text-fail"}`}>
        <span aria-hidden="true">{soft ? "△ " : "✕ "}</span>
        {failureHeading(failure)}
      </p>
      <p className="whitespace-pre-line text-sm leading-relaxed text-text-2">{failure.message}</p>
      {note ? <p className="text-xs leading-relaxed text-muted">{note}</p> : null}
      {failure.code || failure.status ? (
        <p className="font-mono text-[11px] text-muted">
          {failure.code ? (
            <>
              code <span className="text-text-2">{failure.code}</span>
            </>
          ) : null}
          {failure.code && failure.status ? " · " : null}
          {failure.status ? <>HTTP {failure.status}</> : null}
        </p>
      ) : null}
    </div>
  );
}

export function LiveExplorePanel() {
  const [draft, setDraft] = useState("");
  const [maxResults, setMaxResults] = useState(EXPLORE_DEFAULT_MAX_RESULTS);
  const [view, setView] = useState<View>({ kind: "idle" });
  const inflight = useRef<AbortController | null>(null);

  useEffect(() => () => inflight.current?.abort(), []);

  async function submit(e: FormEvent) {
    e.preventDefault();
    const q = draft.trim();
    if (!q) return;
    inflight.current?.abort();
    const controller = new AbortController();
    inflight.current = controller;
    setView({ kind: "loading", q });
    const result = await searchLiveExplore(q, maxResults, controller.signal);
    if (controller.signal.aborted) return;
    setView({ kind: "done", q, result });
  }

  const result = view.kind === "done" ? view.result : null;
  const data = result && result.ok ? result.data : null;
  const status =
    view.kind === "loading"
      ? "Searching"
      : result && !result.ok
        ? failureHeading(result)
        : data
          ? `${data.items.length} Live Explore results, retrieved at ${data.retrieved_at}`
          : "";

  return (
    <section
      aria-labelledby="live-explore-title"
      className="flex min-w-0 flex-col rounded-lg border border-dashed border-risk/50 bg-elevated"
    >
      <header className="flex min-h-11 flex-wrap items-center justify-between gap-x-3 gap-y-1.5 border-b border-line px-5 py-2.5">
        <h2
          id="live-explore-title"
          className="flex items-baseline gap-2 font-mono text-[11px] uppercase tracking-[0.14em] text-text-2"
        >
          <span className="text-muted">E.5</span>
          <span>Live Explore · current web search</span>
        </h2>
        <LiveExploreBadge />
      </header>

      <div className="flex flex-col gap-6 p-5">
        <p className="max-w-3xl text-xs leading-relaxed text-muted">
          <span className="font-mono uppercase tracking-[0.08em] text-risk">Separate from the Blind Replay.</span>{" "}
          Searches today&apos;s web, so results can describe what happened after any replay cutoff. They are never sent
          to the replay model, its prompts or the scorecard; the API enforces that with code boundaries and tests, not
          with this panel.
        </p>

        <form onSubmit={submit} className="flex flex-col gap-2">
          <label htmlFor="live-explore-q" className="kicker">
            Search current news
          </label>
          <div className="flex flex-col gap-2 sm:flex-row">
            <input
              id="live-explore-q"
              type="search"
              autoComplete="off"
              spellCheck
              maxLength={EXPLORE_MAX_QUERY_CHARS}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              placeholder="e.g. regional supplier outages this month"
              aria-describedby="live-explore-help"
              className="min-w-0 flex-1 rounded-md border border-line-strong bg-bg px-3 py-2.5 text-base text-text placeholder:text-muted/70 focus:border-accent focus:outline-none"
            />
            <div className="flex gap-2">
              <label htmlFor="live-explore-n" className="sr-only">
                Number of results
              </label>
              <select
                id="live-explore-n"
                value={maxResults}
                onChange={(e) => setMaxResults(Number(e.target.value))}
                className="num rounded-md border border-line-strong bg-bg px-2 py-2.5 text-sm text-text focus:border-accent focus:outline-none"
              >
                {RESULT_COUNTS.map((n) => (
                  <option key={n} value={n}>
                    {n} {n === 1 ? "result" : "results"}
                  </option>
                ))}
              </select>
              <button
                type="submit"
                disabled={!draft.trim() || view.kind === "loading"}
                className="flex-1 rounded-md border border-accent/70 bg-accent-soft px-4 py-2.5 font-mono text-[11px] uppercase tracking-[0.14em] text-text transition-colors hover:bg-accent/20 disabled:cursor-not-allowed disabled:opacity-50 sm:flex-none"
              >
                Search
              </button>
            </div>
          </div>
          <p id="live-explore-help" className="text-xs leading-relaxed text-muted">
            Up to {EXPLORE_MAX_QUERY_CHARS} characters. Each search calls Tavily through the FAULTLINE API (
            <code className="text-text-2">GET {EXPLORE_SEARCH_PATH}</code>); repeats within 5 minutes are served from
            the API&apos;s cache.
          </p>
        </form>

        <p role="status" aria-live="polite" className="sr-only">
          {status}
        </p>

        {view.kind === "idle" ? (
          <p className="font-mono text-[11px] uppercase tracking-[0.12em] text-muted">No search yet</p>
        ) : null}
        {view.kind === "loading" ? (
          <p className="font-mono text-[11px] uppercase tracking-[0.12em] text-muted">Awaiting API response…</p>
        ) : null}
        {result && !result.ok ? <FailureReport failure={result} /> : null}

        {data ? (
          <div className="flex flex-col gap-5">
            <dl className="max-w-xl">
              <Row label="Query sent">{data.query}</Row>
              <Row label="Retrieved at">{data.retrieved_at}</Row>
              <Row label="Source">{data.cached ? "API cache (original retrieval time above)" : "Tavily, this request"}</Row>
            </dl>
            {data.items.length === 0 ? (
              <p className="text-sm">
                <Missing>No results</Missing>
              </p>
            ) : (
              <ol className="flex flex-col gap-5">
                {data.items.map((item, i) => (
                  <ResultCard key={item.url} item={item} index={i} />
                ))}
              </ol>
            )}
            {data.notes.length ? (
              <ul className="flex list-disc flex-col gap-1 pl-5 text-[11px] leading-relaxed text-muted">
                {data.notes.map((n, i) => (
                  <li key={i}>{n}</li>
                ))}
              </ul>
            ) : null}
          </div>
        ) : null}

        <p className="border-t border-line pt-3 font-mono text-[11px] tracking-[0.04em] text-muted">
          {TAVILY_ATTRIBUTION}
        </p>
      </div>
    </section>
  );
}
