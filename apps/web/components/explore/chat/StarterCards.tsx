"use client";

import { useEffect, useState } from "react";
import { getChatStarters, httpUrl, newsDate, type NewsStarter, type StarterTag } from "@/lib/starters";
import { WireBadge } from "./ChatBadges";
import "./flight.css";

/**
 * Starter prompts: management decisions only (leadership, M&A, strategy, governance, workforce). They carry questions,
 * never results. When GET /api/explore/chat/starters answers, each card is a current-events question with the news
 * item it came from ("In the news: …", http(s) links only) under the server's REAL (web) provenance. On 404 / 503 /
 * network failure the four static questions below are shown, with no news line.
 */

interface Starter {
  tag: StarterTag;
  title: string;
  prompt: string;
  news?: NewsStarter;
}

export const STATIC_STARTERS: Starter[] = [
  { tag: "Leadership", title: "Should Meta keep Mark Zuckerberg as CEO?", prompt: "Should Meta keep Mark Zuckerberg as CEO? Give me the odds." },
  { tag: "Leadership", title: "Should Nvidia keep Jensen Huang as CEO?", prompt: "Should Nvidia keep Jensen Huang as CEO? Give me the odds." },
  { tag: "M&A", title: "Should Disney sell ABC?", prompt: "Should Disney sell ABC? Give me the odds and the main risks." },
  {
    tag: "Governance",
    title: "A CEO is hit by a scandal. Keep, suspend or replace?",
    prompt: "A CEO is hit by a scandal. Should the board keep, suspend or replace them? Give me the odds.",
  },
];

const TONE: Record<StarterTag, { card: string; text: string }> = {
  Leadership: { card: "starter-tone-accent", text: "text-accent" },
  "M&A": { card: "starter-tone-info", text: "text-info" },
  Strategy: { card: "starter-tone-viable", text: "text-viable" },
  Governance: { card: "starter-tone-risk", text: "text-risk" },
  Workforce: { card: "starter-tone-info", text: "text-info" },
};

type Load = { kind: "loading" } | { kind: "news"; provenance: string; starters: Starter[] } | { kind: "static" };

const MAX_CARDS = 4;

export function StarterCards({ onPick, disabled }: { onPick: (prompt: string) => void; disabled: boolean }) {
  const [load, setLoad] = useState<Load>({ kind: "loading" });
  useEffect(() => {
    const ctrl = new AbortController();
    void getChatStarters(ctrl.signal).then((r) => {
      if (ctrl.signal.aborted) return;
      if (!r.ok) return setLoad({ kind: "static" });
      setLoad({
        kind: "news",
        provenance: r.data.provenance,
        starters: r.data.starters.slice(0, MAX_CARDS).map((s) => ({ tag: s.tag, title: s.question, prompt: s.question, news: s })),
      });
    });
    return () => ctrl.abort();
  }, []);

  const starters = load.kind === "news" ? load.starters : STATIC_STARTERS;
  return (
    <div className="flex min-w-0 flex-col gap-2" data-testid="chat-starters" data-source={load.kind}>
      {load.kind === "news" ? (
        <p className="flex min-w-0 flex-wrap items-center gap-2 font-mono text-[10.5px] text-muted">
          <span>In the news</span>
          <WireBadge value={load.provenance} />
        </p>
      ) : null}
      <ul className="grid grid-cols-1 gap-3 md:grid-cols-2" aria-label="Starter questions" aria-busy={load.kind === "loading"}>
        {starters.map((s) => {
          const tone = TONE[s.tag];
          const link = s.news ? httpUrl(s.news.source_url) : null;
          const date = s.news ? newsDate(s.news.published_date) : null;
          return (
            <li key={s.title} className={`starter-card ${tone.card} relative isolate flex min-w-0 flex-col overflow-hidden rounded-xl border border-line`}>
              <button
                type="button"
                onClick={() => onPick(s.prompt)}
                disabled={disabled}
                title={s.prompt}
                data-testid="chat-starter"
                className="group flex min-h-[5.5rem] w-full min-w-0 flex-1 flex-col gap-2 p-4 text-left disabled:cursor-not-allowed disabled:opacity-50 md:p-5"
              >
                <span className={`font-mono text-[10.5px] uppercase tracking-[0.16em] ${tone.text}`}>{s.tag}</span>
                <span className="display min-w-0 break-words text-[1.35rem] leading-[1.1] text-text md:text-[1.55rem] 2xl:text-[1.7rem]">{s.title}</span>
              </button>
              {s.news ? (
                <p className="min-w-0 break-words px-4 pb-3 font-mono text-[10.5px] leading-snug text-muted [overflow-wrap:anywhere] md:px-5" data-testid="starter-news">
                  In the news:{" "}
                  {link ? (
                    <a href={link.href} target="_blank" rel="noopener noreferrer" className="text-text-2 underline decoration-line-strong underline-offset-2 hover:text-link-hover">
                      {s.news.headline}
                    </a>
                  ) : (
                    <span className="text-text-2">{s.news.headline}</span>
                  )}{" "}
                  · {s.news.domain} · {date ?? "date not available"}
                </p>
              ) : null}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
