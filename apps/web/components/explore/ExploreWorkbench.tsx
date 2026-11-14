"use client";

import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import {
  EXPLORE_ANALYZE_PATH,
  EXPLORE_MAX_DECISION_CHARS,
  TAVILY_ATTRIBUTION,
  analyzeLiveExplore,
  type AnalysisStatus,
  type AnalyzeResult,
  type ExploreAnalysis,
  type ExploreEvidenceCard,
} from "@/lib/explore";
import { Panel } from "../Panel";
import { ExploreScenario } from "./ExploreScenario";
import { ExternalLink, FailureReport, failureHeading, host } from "./LiveExplorePanel";

/**
 * LIVE EXPLORE (issue #61): "test a decision today".
 *
 * Decision text -> POST /api/explore/analyze (Tavily search, then the local model with those results as its only
 * evidence) -> cited evidence cards and MODEL-SUGGESTED scenario inputs -> the human edits and confirms -> POST
 * /api/simulate. The request runs only when the presenter submits (it spends Tavily credits); nothing runs on mount.
 * Every claim, link, snippet, timestamp and number is rendered as the API returned it; missing values say so.
 * Current web content, never point-in-time, and never given to the Blind Replay (enforced in the API by tests).
 */

type View = { kind: "idle" } | { kind: "loading"; text: string } | { kind: "done"; text: string; result: AnalyzeResult };

const STATUS_HEADING: Record<Exclude<AnalysisStatus, "ok">, string> = {
  no_sources: "No Tavily results",
  no_cited_evidence: "No cited evidence: suggestion withheld",
  model_unavailable: "Local model unavailable",
  model_output_invalid: "Local model answer rejected",
  model_input_refused: "Local model input refused",
};

function Missing({ children = "Not available" }: { children?: ReactNode }) {
  return <span className="font-mono uppercase tracking-[0.08em] text-muted">{children}</span>;
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-0.5 border-b border-line/70 py-1.5 last:border-b-0">
      <dt className="text-[11px] uppercase tracking-[0.12em] text-muted">{label}</dt>
      <dd className="num min-w-0 break-words text-right text-xs text-text-2">{children}</dd>
    </div>
  );
}

function EvidenceCard({ card }: { card: ExploreEvidenceCard }) {
  return (
    <li className="flex min-w-0 flex-col gap-3 rounded-md border border-line p-4">
      <div className="flex flex-col gap-1">
        <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted">
          {card.source_id} · {host(card.source_url)} · claim written by the local model
        </p>
        <p className="text-[15px] leading-snug text-text">{card.claim}</p>
      </div>
      <div className="flex flex-col gap-1.5">
        <p className="text-sm font-medium leading-snug">
          <ExternalLink href={card.source_url}>{card.source_title}</ExternalLink>
        </p>
        {card.snippet ? (
          <blockquote className="border-l border-line-strong pl-3 text-[13px] leading-relaxed text-text-2">
            <span className="sr-only">Tavily snippet: </span>
            {card.snippet}
          </blockquote>
        ) : (
          <p className="text-xs">
            <Missing>Snippet not available</Missing>
          </p>
        )}
      </div>
      <dl>
        <Row label="Retrieved at">{card.retrieved_at}</Row>
        <Row label="Published (Tavily estimate)">
          {card.published_at ?? (card.published_at_raw ? `${card.published_at_raw} (as sent)` : <Missing />)}
        </Row>
      </dl>
    </li>
  );
}

function Analysis({ data }: { data: ExploreAnalysis }) {
  const failed = data.status !== "ok";
  return (
    <>
      <Panel
        code="X.2"
        title="Evidence · cited Tavily results"
        provenance="LIVE EXPLORE"
        provenanceDetail="current, not point-in-time"
        className="xl:col-span-12"
        bodyClassName="flex flex-col gap-5"
      >
        <dl className="max-w-2xl">
          <Row label="Decision sent">{data.decision_text}</Row>
          <Row label="Retrieved at">{data.retrieved_at}</Row>
          <Row label="Search">{data.cached ? "API cache (original retrieval time above)" : "Tavily, this request"}</Row>
          <Row label="Local model">
            {data.model ? `${data.model.agent_model} · temperature ${data.model.temperature} · ${data.model.attempts} attempt${data.model.attempts === 1 ? "" : "s"} · ${data.model.latency_ms} ms` : <Missing />}
          </Row>
        </dl>

        {failed ? (
          <div className="flex flex-col gap-1.5 rounded-md border border-dashed border-risk/50 p-4">
            <p className="font-mono text-sm font-medium uppercase tracking-[0.1em] text-risk">
              <span aria-hidden="true">△ </span>
              {STATUS_HEADING[data.status as Exclude<AnalysisStatus, "ok">]}
            </p>
            <p className="text-sm leading-relaxed text-text-2">{data.status_message ?? "No reason was given."}</p>
            <p className="text-xs leading-relaxed text-muted">
              Nothing is substituted: no evidence cards and no suggested numbers are shown for this request.
            </p>
          </div>
        ) : null}

        {data.evidence.length ? (
          <ol className="grid grid-cols-1 gap-4 lg:grid-cols-2 2xl:grid-cols-3">
            {data.evidence.map((c, i) => (
              <EvidenceCard key={`${c.source_url}-${i}`} card={c} />
            ))}
          </ol>
        ) : (
          <p className="text-sm">
            <Missing>No evidence cards</Missing>
          </p>
        )}

        {data.rejected_claims.length ? (
          <details className="rounded-md border border-line p-3">
            <summary className="cursor-pointer font-mono text-[11px] uppercase tracking-[0.12em] text-text-2">
              {data.rejected_claims.length} model claim{data.rejected_claims.length === 1 ? "" : "s"} rejected by the
              citation check
            </summary>
            <ul className="mt-3 flex flex-col gap-3">
              {data.rejected_claims.map((r, i) => (
                <li key={i} className="flex min-w-0 flex-col gap-0.5 text-xs leading-relaxed">
                  <span className="break-words text-text-2 line-through decoration-muted">{r.claim || "(empty)"}</span>
                  <span className="text-fail">{r.message}</span>
                  {/* An unverified URL is shown as text, never as a link. */}
                  <span className="break-all font-mono text-[10px] text-muted">
                    cited: {r.source_url ?? "nothing"}
                  </span>
                </li>
              ))}
            </ul>
          </details>
        ) : null}

        {data.sources.length ? (
          <details className="rounded-md border border-line p-3">
            <summary className="cursor-pointer font-mono text-[11px] uppercase tracking-[0.12em] text-text-2">
              All {data.sources.length} Tavily result{data.sources.length === 1 ? "" : "s"} given to the model
            </summary>
            <ol className="mt-3 flex flex-col gap-3">
              {data.sources.map((s) => (
                <li key={s.source_id} className="flex min-w-0 flex-col gap-1 text-xs leading-relaxed">
                  <span className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted">
                    {s.source_id} · {host(s.url)} · retrieved {s.retrieved_at}
                  </span>
                  <ExternalLink href={s.url}>{s.title}</ExternalLink>
                  {s.snippet ? <span className="text-text-2">{s.snippet}</span> : <Missing>Snippet not available</Missing>}
                </li>
              ))}
            </ol>
          </details>
        ) : null}

        <ul className="flex list-disc flex-col gap-1 pl-5 text-[11px] leading-relaxed text-muted">
          {data.notes.map((n, i) => (
            <li key={i}>{n}</li>
          ))}
          {data.model ? (
            <li className="break-all">
              Model run (not saved): prompt sha256 {data.model.prompt_sha256} · sources sha256{" "}
              {data.model.sources_sha256} · digest {data.model.model_digest ?? "not reported"}
            </li>
          ) : null}
        </ul>
      </Panel>

      <ExploreScenario key={`${data.retrieved_at}|${data.decision_text}|${data.model?.raw_output_sha256 ?? ""}`} analysis={data} />
    </>
  );
}

export function ExploreWorkbench() {
  const [draft, setDraft] = useState("");
  const [view, setView] = useState<View>({ kind: "idle" });
  const inflight = useRef<AbortController | null>(null);

  useEffect(() => () => inflight.current?.abort(), []);

  async function submit(e: FormEvent) {
    e.preventDefault();
    const text = draft.trim();
    if (!text) return;
    inflight.current?.abort();
    const controller = new AbortController();
    inflight.current = controller;
    setView({ kind: "loading", text });
    const result = await analyzeLiveExplore(text, controller.signal);
    if (controller.signal.aborted) return;
    setView({ kind: "done", text, result });
  }

  function cancel() {
    inflight.current?.abort();
    setView({ kind: "idle" });
  }

  const result = view.kind === "done" ? view.result : null;
  const data = result && result.ok ? result.data : null;
  const status =
    view.kind === "loading"
      ? "Analyzing: Tavily search, then the local model"
      : result && !result.ok
        ? failureHeading(result)
        : data
          ? `${data.evidence.length} cited evidence cards from ${data.sources.length} Tavily results`
          : "";

  // overflow-wrap inherits: long URLs, hashes and model text wrap instead of widening the page (audit S4).
  return (
    <div className="grid grid-cols-1 gap-5 [overflow-wrap:anywhere] xl:grid-cols-12">
      <Panel
        code="X.1"
        title="Decision · test it against today's news"
        provenance="LIVE EXPLORE"
        provenanceDetail="current, not point-in-time"
        className="xl:col-span-12"
        bodyClassName="flex flex-col gap-4"
      >
        <p className="max-w-3xl text-xs leading-relaxed text-muted">
          <span className="font-mono uppercase tracking-[0.08em] text-risk">Separate from the Blind Replay.</span> Tavily
          searches today&apos;s web; the local model reads only those results. Nothing here is point-in-time, saved,
          scored, or given to the replay model; the API enforces that with code boundaries and tests.
        </p>
        <form onSubmit={submit} className="flex flex-col gap-2">
          <label htmlFor="explore-decision" className="kicker">
            Your decision
          </label>
          <textarea
            id="explore-decision"
            rows={3}
            maxLength={EXPLORE_MAX_DECISION_CHARS}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder="e.g. Should we sign a lease for a third store while our floating-rate loan is about to reset?"
            aria-describedby="explore-decision-help"
            className="min-w-0 resize-y rounded-md border border-line-strong bg-bg px-3 py-2.5 text-base text-text placeholder:text-muted/70 focus:border-accent focus:outline-none"
          />
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="submit"
              disabled={!draft.trim() || view.kind === "loading"}
              className="rounded-md border border-accent/70 bg-accent-soft px-4 py-2.5 font-mono text-[11px] uppercase tracking-[0.14em] text-text transition-colors hover:bg-accent/20 disabled:cursor-not-allowed disabled:opacity-50"
            >
              Research and analyze
            </button>
            {view.kind === "loading" ? (
              <button
                type="button"
                onClick={cancel}
                className="rounded-md border border-line-strong px-3 py-2.5 font-mono text-[11px] uppercase tracking-[0.12em] text-text-2 hover:bg-hover hover:text-text"
              >
                Cancel
              </button>
            ) : null}
            <span className="num ml-auto font-mono text-[10px] text-muted">
              {draft.length} / {EXPLORE_MAX_DECISION_CHARS}
            </span>
          </div>
          <p id="explore-decision-help" className="text-xs leading-relaxed text-muted">
            Sent to <code className="text-text-2">POST {EXPLORE_ANALYZE_PATH}</code>: one Tavily search (repeats within 5
            minutes come from the API&apos;s cache), then the local model. Admin only on the public demo.
          </p>
        </form>

        <p role="status" aria-live="polite" className="sr-only">
          {status}
        </p>
        {view.kind === "idle" ? (
          <p className="font-mono text-[11px] uppercase tracking-[0.12em] text-muted">No decision analyzed yet</p>
        ) : null}
        {view.kind === "loading" ? (
          <p className="font-mono text-[11px] uppercase tracking-[0.12em] text-muted">
            Awaiting API response (Tavily search, then the local model; this can take a minute)…
          </p>
        ) : null}
        {result && !result.ok ? <FailureReport failure={result} /> : null}
      </Panel>

      {data ? <Analysis data={data} /> : null}

      <p className="font-mono text-[11px] tracking-[0.04em] text-muted xl:col-span-12">{TAVILY_ATTRIBUTION}</p>
    </div>
  );
}
