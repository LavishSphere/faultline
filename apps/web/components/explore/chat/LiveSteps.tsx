"use client";

import type { LiveStep } from "@/lib/chat";

/**
 * The live tool steps of a chat turn in flight (#222), from POST /api/explore/chat/stream. Each line is the server's
 * own preview of the tool call and, when it finishes, of its result; the browser computes nothing. The reply text is
 * not shown here: it arrives with the final response, after the server checks every figure in it.
 */
export function LiveSteps({ steps, fallback, reduce }: { steps: readonly LiveStep[]; fallback: string | null; reduce: boolean }) {
  return (
    <div className="flex min-w-0 flex-col gap-2" data-testid="chat-live-steps">
      <p className="font-mono text-[10.5px] uppercase tracking-[0.12em] text-muted">
        {fallback ? "steps arrive with the reply" : "live steps · the reply is checked before it's shown"}
      </p>
      {fallback ? (
        <p className="font-mono text-[10.5px] text-muted" data-testid="chat-live-fallback">
          Not streamed ({fallback}): the reply arrives in one piece.
        </p>
      ) : steps.length === 0 ? (
        <p className="text-[13px] text-text-2" data-testid="chat-live-empty">
          Waiting for the model’s first step…
        </p>
      ) : (
        <ol className="flex min-w-0 flex-col gap-1.5" aria-live="polite">
          {steps.map((s) => (
            <li key={s.id} className="flex min-w-0 items-start gap-2 text-[13px]" data-testid="chat-live-step" data-status={s.status} data-tool={s.name}>
              <StepIcon status={s.status} reduce={reduce} />
              <span className="flex min-w-0 flex-col">
                <span className="break-words text-text [overflow-wrap:anywhere]">{s.input}</span>
                {s.preview ? (
                  <span className={`break-words font-mono text-[11px] [overflow-wrap:anywhere] ${s.status === "error" ? "text-fail" : "text-text-2"}`} data-testid="chat-live-preview">
                    {s.preview}
                  </span>
                ) : null}
              </span>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

function StepIcon({ status, reduce }: { status: LiveStep["status"]; reduce: boolean }) {
  if (status === "running") {
    return (
      <span
        role="img"
        aria-label="running"
        className={`mt-0.5 inline-block size-3.5 shrink-0 rounded-full border-2 border-accent/30 border-t-accent ${reduce ? "" : "animate-spin motion-reduce:animate-none"}`}
      />
    );
  }
  if (status === "note") {
    return (
      <span role="img" aria-label="note" className="mt-px w-3.5 shrink-0 text-center font-mono text-[13px] text-info">
        ↻
      </span>
    );
  }
  return (
    <span role="img" aria-label={status === "ok" ? "done" : "failed"} className={`mt-px w-3.5 shrink-0 text-center font-mono text-[13px] ${status === "ok" ? "text-accent" : "text-fail"}`}>
      {status === "ok" ? "✓" : "✗"}
    </span>
  );
}
