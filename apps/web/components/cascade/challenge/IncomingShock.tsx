"use client";

import { useEffect } from "react";
import { ProvenanceBadge } from "../../ProvenanceBadge";
import "../cascade-fx.css";

/** What the card shows: fields of one GET /api/judge-challenges item, verbatim. */
export interface IncomingShockInfo {
  /** Increments on every pick, so picking the same challenge twice still replays the card. */
  seq: number;
  id: string;
  name: string;
  description: string;
  rangeCitation: string;
  surprisePick: number | null;
}

/** How long the card stays before the shockwave has the stage to itself. */
export const INCOMING_SHOCK_MS = 3600;

/**
 * "Incoming shock" card (#165): shown over the dependency network when a Judge's Challenge is picked, then the
 * shockwave follows (the network waits for it). Text only, all from the API; it carries no figure of its own.
 * Under reduced motion it appears and leaves without animation; Escape or the close button dismisses it.
 */
export function IncomingShock({ info, reduce, onDone }: { info: IncomingShockInfo; reduce: boolean; onDone: () => void }) {
  useEffect(() => {
    const t = setTimeout(onDone, INCOMING_SHOCK_MS);
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onDone();
    };
    window.addEventListener("keydown", onKey);
    return () => {
      clearTimeout(t);
      window.removeEventListener("keydown", onKey);
    };
  }, [info.seq, onDone]);

  return (
    <div
      role="status"
      aria-live="assertive"
      data-testid="incoming-shock"
      className={`${reduce ? "" : "fx-incoming"} absolute left-3 right-3 top-3 z-20 overflow-hidden rounded-lg border border-risk/70 bg-elevated/90 backdrop-blur-[12px] sm:right-auto sm:max-w-[30rem]`}
      style={{ boxShadow: "0 0 0 1px color-mix(in srgb, var(--risk) 30%, transparent), 0 18px 48px -12px color-mix(in srgb, var(--risk) 45%, transparent)" }}
    >
      <div className="flex flex-col gap-1.5 px-4 py-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="flex items-center gap-2 font-mono text-[10.5px] font-semibold uppercase tracking-[0.2em] text-risk">
            <span aria-hidden="true">▲</span> Incoming shock
            {info.surprisePick !== null ? <span className="font-normal text-muted">· surprise pick {info.surprisePick}</span> : null}
          </p>
          <span className="flex items-center gap-1.5">
            <ProvenanceBadge kind="ILLUSTRATIVE" detail="shock" />
            <button
              type="button"
              onClick={onDone}
              aria-label="Dismiss incoming shock card"
              className="rounded-sm px-1.5 font-mono text-xs text-muted hover:bg-hover hover:text-text"
            >
              ×
            </button>
          </span>
        </div>
        <p className="display text-3xl text-text md:text-4xl">{info.name}</p>
        <p className="text-sm leading-snug text-text-2">{info.description}</p>
        <p className="break-words font-mono text-[10px] leading-snug text-muted">Range: {info.rangeCitation}</p>
        <p className="font-mono text-[10px] uppercase tracking-[0.12em] text-muted">
          Sent unchanged to POST /api/simulate · results below are SIMULATED
        </p>
      </div>
      {reduce ? null : (
        <div className="h-[2px] w-full bg-line" aria-hidden="true">
          <div className="fx-incoming-timer h-full bg-risk" style={{ animationDuration: `${INCOMING_SHOCK_MS}ms` }} />
        </div>
      )}
    </div>
  );
}
