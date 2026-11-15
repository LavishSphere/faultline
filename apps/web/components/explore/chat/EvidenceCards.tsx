"use client";

import type { ChatToolCall } from "@/lib/chat";
import { WireBadge } from "./ChatBadges";

/**
 * Evidence the model fetched in a turn (#197): web_search results as source cards and prediction_markets results as
 * quote cards, each with the provenance label the server sent. Every field is shown as served; a missing field reads
 * NOT AVAILABLE, never a placeholder. Links open only for http(s) URLs. Market prices are the venue's quote, shown as
 * served and labelled market-implied (price-derived); nothing is converted, averaged or ranked here.
 */

const isObj = (v: unknown): v is Record<string, unknown> => !!v && typeof v === "object" && !Array.isArray(v);
const str = (v: unknown): string | null => (typeof v === "string" && v.trim() ? v.trim() : null);
const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);

function safeUrl(v: unknown): URL | null {
  const s = str(v);
  if (!s) return null;
  try {
    const u = new URL(s);
    return u.protocol === "https:" || u.protocol === "http:" ? u : null;
  } catch {
    return null;
  }
}

const DATE = new Intl.DateTimeFormat("en-US", { year: "numeric", month: "short", day: "numeric", timeZone: "UTC" });
const STAMP = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "UTC" });

/** An ISO date as "Nov 14, 2026"; an unparseable string is shown verbatim; nothing → null. */
function dateLabel(v: unknown, fmt = DATE): string | null {
  const s = str(v);
  if (!s) return null;
  const t = Date.parse(s);
  return Number.isNaN(t) ? s : `${fmt.format(t)}${fmt === STAMP ? " UTC" : ""}`;
}

const NA = <span className="font-mono text-[10px] uppercase tracking-[0.1em] text-muted">not available</span>;

interface Source {
  title: string | null;
  url: URL | null;
  domain: string | null;
  date: string | null;
  snippet: string | null;
}

/** Accepts the stage-2 shape ({results: [{title, url, domain, published_date, snippet}]}) and the #193 one ({items}). */
function sourcesOf(summary: unknown): Source[] | null {
  if (!isObj(summary)) return null;
  const list = Array.isArray(summary.results) ? summary.results : Array.isArray(summary.items) ? summary.items : null;
  if (!list) return null;
  return list.filter(isObj).map((r) => {
    const url = safeUrl(r.url);
    return {
      title: str(r.title),
      url,
      domain: str(r.domain) ?? (url ? url.hostname.replace(/^www\./, "") : null),
      date: dateLabel(r.published_date ?? r.published_at),
      snippet: str(r.snippet),
    };
  });
}

interface Quote {
  venue: string | null;
  question: string | null;
  price: number | null;
  volume: number | null;
  url: URL | null;
  marketId: string | null;
}

function quotesOf(summary: unknown): Quote[] | null {
  if (!isObj(summary) || !Array.isArray(summary.markets)) return null;
  return summary.markets.filter(isObj).map((m) => ({
    venue: str(m.venue),
    question: str(m.question),
    price: num(m.price),
    volume: num(m.volume),
    url: safeUrl(m.url),
    marketId: str(m.market_id),
  }));
}

function Header({ title, badge, stamp }: { title: string; badge: string; stamp: string | null }) {
  return (
    <p className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
      <span className="kicker !text-text-2">{title}</span>
      <WireBadge value={badge} />
      <span className="font-mono text-[10.5px] text-muted">{stamp ?? "retrieval time not available"}</span>
    </p>
  );
}

function WebSources({ call }: { call: ChatToolCall }) {
  const s = isObj(call.result_summary) ? call.result_summary : null;
  const sources = sourcesOf(s);
  const badge = str(s?.provenance) ?? call.provenance;
  const query = str(s?.query) ?? str(call.input.query);
  const at = dateLabel(s?.retrieved_at, STAMP);
  return (
    <div className="flex min-w-0 flex-col gap-2" data-testid="chat-web-sources">
      <Header title={`Sources${query ? ` · “${query}”` : ""}`} badge={badge} stamp={at ? `retrieved ${at}` : null} />
      {!sources || sources.length === 0 ? (
        <p className="font-mono text-[11px] uppercase tracking-[0.1em] text-muted">Search results NOT AVAILABLE</p>
      ) : (
        <ul className="grid min-w-0 grid-cols-1 gap-2 md:grid-cols-2">
          {sources.map((r, i) => (
            <li key={i} className="min-w-0">
              <article className="flex h-full min-w-0 flex-col gap-1.5 rounded-md border border-line bg-bg/50 p-3 transition-colors hover:border-accent/50" data-testid="chat-source-card">
                <p className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 font-mono text-[10.5px] text-muted">
                  <span className="min-w-0 break-all text-text-2" data-testid="source-domain">{r.domain ?? "domain not available"}</span>
                  <span aria-hidden="true">·</span>
                  <span data-testid="source-date">{r.date ?? "date not available"}</span>
                  <WireBadge value={badge} />
                </p>
                {r.url ? (
                  <a
                    href={r.url.href}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="min-w-0 break-words text-[14px] font-medium leading-snug text-text underline-offset-2 [overflow-wrap:anywhere] hover:text-link-hover hover:underline"
                    data-testid="source-link"
                  >
                    {r.title ?? r.url.href}
                    <span className="sr-only"> (opens in a new tab)</span>
                  </a>
                ) : (
                  <p className="min-w-0 break-words text-[14px] font-medium text-text [overflow-wrap:anywhere]">{r.title ?? "Title not available"}</p>
                )}
                {r.snippet ? <p className="line-clamp-3 min-w-0 break-words text-[12.5px] leading-relaxed text-text-2 [overflow-wrap:anywhere]">{r.snippet}</p> : null}
              </article>
            </li>
          ))}
        </ul>
      )}
      {str(s?.attribution) ? <p className="font-mono text-[10px] text-muted">{str(s?.attribution)}</p> : null}
    </div>
  );
}

const VENUE: Record<string, string> = { kalshi: "Kalshi", polymarket: "Polymarket" };

function MarketQuotes({ call }: { call: ChatToolCall }) {
  const s = isObj(call.result_summary) ? call.result_summary : null;
  const quotes = quotesOf(s);
  const badge = str(s?.provenance) ?? "LIVE MARKET QUOTE";
  const at = dateLabel(s?.fetched_at, STAMP);
  return (
    <div className="flex min-w-0 flex-col gap-2" data-testid="chat-market-quotes">
      <Header title="Prediction markets" badge={badge} stamp={at ? `fetched ${at}` : null} />
      {!quotes || quotes.length === 0 ? (
        <p className="font-mono text-[11px] uppercase tracking-[0.1em] text-muted">Market quotes NOT AVAILABLE</p>
      ) : (
        <ul className="grid min-w-0 grid-cols-1 gap-2 md:grid-cols-2">
          {quotes.map((q, i) => (
            <li key={i} className="min-w-0">
              <article className="flex h-full min-w-0 flex-col gap-2 rounded-md border border-info/40 bg-bg/50 p-3" data-testid="chat-quote-card">
                <p className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 font-mono text-[10.5px] text-muted">
                  <span className="text-text-2">{q.venue ? (VENUE[q.venue] ?? q.venue) : "venue not available"}</span>
                  {q.marketId ? <span className="min-w-0 break-all">{q.marketId}</span> : null}
                  <WireBadge value={badge} />
                </p>
                <p className="min-w-0 break-words text-[14px] font-medium leading-snug text-text [overflow-wrap:anywhere]">{q.question ?? "Question not available"}</p>
                <dl className="grid grid-cols-2 gap-2 font-mono text-[11px]">
                  <div className="min-w-0">
                    <dt className="text-[10px] uppercase tracking-[0.1em] text-muted">Price (YES)</dt>
                    <dd className="num mt-0.5 text-lg text-text" data-testid="quote-price">
                      {q.price === null ? NA : q.price.toString()}
                    </dd>
                  </div>
                  <div className="min-w-0">
                    <dt className="text-[10px] uppercase tracking-[0.1em] text-muted">Volume</dt>
                    <dd className="num mt-0.5 break-words text-lg text-text" data-testid="quote-volume">
                      {q.volume === null ? NA : q.volume.toLocaleString("en-US")}
                    </dd>
                  </div>
                </dl>
                <p className="flex min-w-0 flex-wrap items-center justify-between gap-2 font-mono text-[10px] text-muted">
                  <span>market-implied (price-derived) · not a forecast by FAULTLINE</span>
                  {q.url ? (
                    <a href={q.url.href} target="_blank" rel="noopener noreferrer" className="text-text-2 underline-offset-2 hover:text-link-hover hover:underline">
                      Open market<span className="sr-only"> (opens in a new tab)</span>
                    </a>
                  ) : null}
                </p>
              </article>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** The web sources and market quotes of one reply, in the order the calls ran. Nothing for a turn without them. */
export function EvidenceCards({ calls }: { calls: readonly ChatToolCall[] }) {
  const picked = calls.filter((c) => c.result_status === "ok" && (c.name === "web_search" || c.name === "prediction_markets"));
  if (picked.length === 0) return null;
  return (
    <div className="flex min-w-0 flex-col gap-4" data-testid="chat-evidence">
      {picked.map((c, i) => (c.name === "web_search" ? <WebSources key={i} call={c} /> : <MarketQuotes key={i} call={c} />))}
    </div>
  );
}
