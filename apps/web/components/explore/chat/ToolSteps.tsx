"use client";

import { useId, useState } from "react";
import type { ChatToolCall } from "@/lib/chat";
import { WireBadge } from "./ChatBadges";

/**
 * "Steps the model took": one chip per tool call, in the order the server ran them, revealed one after another once
 * the reply has landed. It is a record of what happened, not a live feed (the API is not streaming), and says so.
 * Each chip expands to the exact input the model sent and the server's result summary.
 */
export function ToolSteps({ calls, reduce }: { calls: readonly ChatToolCall[]; reduce: boolean }) {
  const [open, setOpen] = useState<number | null>(null);
  const panelId = useId();
  if (calls.length === 0) {
    return (
      <p className="font-mono text-[11px] uppercase tracking-[0.12em] text-muted" data-testid="chat-no-tools">
        No engine tools used in this reply: it contains no engine numbers.
      </p>
    );
  }
  const current = open !== null ? calls[open] : undefined;
  return (
    <div className="flex min-w-0 flex-col gap-2.5" data-testid="chat-tools">
      <p className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="kicker !text-text-2">Tools used · steps the model took</span>
        <span className="font-mono text-[10.5px] text-muted">
          {calls.length} call{calls.length === 1 ? "" : "s"} · listed after the reply arrived, not live
        </span>
      </p>
      <ol className="flex min-w-0 flex-wrap items-center gap-y-2">
        {calls.map((c, i) => {
          const ok = c.result_status === "ok";
          const delay = reduce ? undefined : { animationDelay: `${120 + i * 170}ms` };
          return (
            <li key={`${c.name}-${i}`} className="flex min-w-0 max-w-full items-center">
              {i > 0 ? (
                <span
                  aria-hidden="true"
                  className={`mx-1.5 h-px w-5 bg-line-strong md:w-8 ${reduce ? "" : "chat-step-link"}`}
                  style={delay}
                />
              ) : null}
              <button
                type="button"
                onClick={() => setOpen(open === i ? null : i)}
                aria-expanded={open === i}
                aria-controls={panelId}
                data-testid="chat-tool-chip"
                data-tool={c.name}
                data-status={c.result_status}
                className={`group flex min-w-0 max-w-full flex-wrap items-center gap-x-2 gap-y-1 rounded-md border px-2.5 py-1.5 text-left transition-colors hover:bg-hover ${
                  open === i ? "border-accent bg-accent-soft" : ok ? "border-line-strong" : "border-fail/60"
                } ${reduce ? "" : "chat-step-in"}`}
                style={delay}
              >
                <span className="num text-[10px] text-muted">{String(i + 1).padStart(2, "0")}</span>
                <span className="min-w-0 break-all font-mono text-[12.5px] font-medium text-text">{c.name}</span>
                <span className={`font-mono text-[10px] uppercase tracking-[0.12em] ${ok ? "text-viable" : "text-fail"}`}>
                  <span aria-hidden="true">{ok ? "✓ " : "✕ "}</span>
                  {c.result_status}
                </span>
                <WireBadge value={c.provenance} />
                <span aria-hidden="true" className="font-mono text-[10px] text-muted group-hover:text-text-2">
                  {open === i ? "▴" : "▾"}
                </span>
              </button>
            </li>
          );
        })}
      </ol>
      <div id={panelId} role="region" aria-label="Tool call details" hidden={current === undefined}>
        {current ? (
          <div className="grid min-w-0 grid-cols-1 gap-3 rounded-md border border-line bg-bg/60 p-3 lg:grid-cols-2" data-testid="chat-tool-detail">
            <div className="min-w-0">
              <p className="kicker mb-1">Input the model sent to {current.name}</p>
              <pre className="max-h-64 overflow-auto whitespace-pre-wrap break-all font-mono text-[11px] leading-relaxed text-text-2">
                {JSON.stringify(current.input, null, 2)}
              </pre>
            </div>
            <div className="min-w-0">
              <p className="kicker mb-1">Result summary from the server</p>
              {typeof current.result_summary === "string" && current.result_summary ? (
                <p className="whitespace-pre-wrap break-words text-[13px] leading-relaxed text-text-2 [overflow-wrap:anywhere]">
                  {current.result_summary}
                </p>
              ) : current.result_summary && typeof current.result_summary === "object" ? (
                // The engine's numbers exactly as the server sent them; shown verbatim, never recomputed.
                <pre className="max-h-64 overflow-auto whitespace-pre-wrap break-all font-mono text-[11px] leading-relaxed text-text-2">
                  {JSON.stringify(current.result_summary, null, 2)}
                </pre>
              ) : (
                <p className="font-mono text-[11px] uppercase tracking-[0.12em] text-muted">Not available</p>
              )}
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}
