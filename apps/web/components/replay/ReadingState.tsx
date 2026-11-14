"use client";

import { useElapsedSeconds } from "./motion";
import m from "./motion.module.css";

/**
 * While POST /api/replay/run is in flight (#163). Honest by construction: the document count is the case's served
 * `evidence_ids` (what the gate admits into the prompt), the elapsed time is this browser's clock since the click,
 * and the browser's own time limit is shown. There is no progress amount: the local model reports nothing until it
 * answers, so the scan line is motion only.
 */
export function ReadingState({
  documents,
  startedAt,
  limitSeconds,
  request,
  model,
}: {
  documents: number;
  startedAt: number;
  limitSeconds: number;
  request: string;
  model: string | null;
}) {
  const elapsed = useElapsedSeconds(startedAt) ?? 0;
  const mm = Math.floor(elapsed / 60);
  const ss = String(elapsed % 60).padStart(2, "0");
  const stack = Math.min(Math.max(documents, 1), 5);

  return (
    <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:gap-6" aria-live="polite" data-testid="reading-state">
      <div className="relative h-28 w-24 shrink-0 self-center" aria-hidden="true" style={{ ["--scan-travel" as string]: "112px" }}>
        {Array.from({ length: stack }, (_, i) => (
          <div
            key={i}
            className="absolute flex h-24 w-[4.5rem] flex-col gap-1.5 rounded-sm border border-line-strong bg-elevated p-2"
            style={{ left: `${i * 5}px`, top: `${(stack - 1 - i) * 4}px`, zIndex: i }}
          >
            {i === stack - 1
              ? [80, 60, 90, 50, 70, 40].map((w, j) => (
                  <span key={j} className="h-0.5 rounded-full bg-line-strong" style={{ width: `${w}%` }} />
                ))
              : null}
          </div>
        ))}
        <div className="absolute inset-x-0 top-0 overflow-hidden" style={{ height: "112px", zIndex: 10 }}>
          <div className={`h-6 w-full bg-gradient-to-b from-transparent via-accent/40 to-transparent ${m.scan}`} />
        </div>
      </div>
      <div className="flex min-w-0 flex-col gap-1.5">
        <p className="display text-2xl leading-tight text-text md:text-3xl">
          The local model is reading {documents} {documents === 1 ? "document" : "documents"}
          <span className={m.breathe}>…</span>
        </p>
        <p className="num text-sm text-text-2">
          <span className="text-muted">Elapsed </span>
          <span data-testid="reading-elapsed">
            {mm}:{ss}
          </span>
          <span className="text-muted"> · this browser stops waiting at {Math.round(limitSeconds / 60)} min</span>
        </p>
        <p className="font-mono text-[11px] text-muted">
          <code className="text-text-2">{request}</code>
          {model ? ` · ${model}` : ""} · no progress estimate: the model reports nothing until it answers
        </p>
      </div>
    </div>
  );
}
