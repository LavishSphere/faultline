"use client";

import { useState, type ReactNode } from "react";
import { isSyntheticRef, type RevealResponse } from "@/lib/benchmark";
import { ProvenanceBadge } from "../ProvenanceBadge";
import { DONE, progress, useClock } from "./motion";
import { RaceAxis, RaceBar, SeriesStyle } from "./series";
import { BUTTON_SECONDARY, fmt4 } from "./ui";

/**
 * The unsealing sequence (#164), played once when D.0's reveal returned a valid 2xx body. It only paces the drawing
 * of fields that response already holds: the envelope opens, the response's audit fields tick in one per line, the
 * outcome appears, then the three Brier scores of this event race to their exact values. Nothing is requested,
 * checked or computed here; a field the response lacks shows NOT AVAILABLE in its own line. Reduced motion (or Skip)
 * draws the final state at once.
 */

// Timeline (ms). Total about 2.6 s.
const OPEN_AT = 450;
const OPEN_DUR = 380;
const LINE_AT = 760;
const LINE_GAP = 190;
const OUTCOME_AT = 1780;
const RACE_AT = 2000;
const RACE_DUR = 620;
const TOTAL = RACE_AT + RACE_DUR + 40;

type LineState = "returned" | "missing" | "true" | "false";
interface Line {
  key: string;
  value: ReactNode;
  state: LineState;
  title?: string;
  testId: string;
}

function shortHash(h: string): string {
  return h.length > 28 ? `${h.slice(0, 16)}…${h.slice(-8)}` : h;
}

function hashLine(key: string, value: string | null | undefined, testId: string): Line {
  return value
    ? { key, value: <span className="num">{shortHash(value)}</span>, state: "returned", title: value, testId }
    : { key, value: "Not available", state: "missing", testId };
}

function linesFor(d: RevealResponse): Line[] {
  const p = d.prediction;
  return [
    {
      key: "forecast persisted",
      value: (
        <>
          <span className="break-all">{p.prediction_id}</span>
          <span className="text-muted"> · persist_seq </span>
          <span className="num">{d.persist_seq}</span>
        </>
      ),
      state: "returned",
      title: `${p.prediction_id} persisted ${d.persisted_at}`,
      testId: "unseal-line-persisted",
    },
    hashLine("prompt_sha256", p.prompt_sha256, "unseal-line-prompt"),
    hashLine("snapshot_sha256", p.snapshot_sha256, "unseal-line-snapshot"),
    // The case hash frozen with the prediction (#180); an older API without it shows NOT AVAILABLE in this slot.
    hashLine("case_sha256", d.case_sha256, "unseal-line-case"),
    {
      key: "persisted before outcome revealed",
      value: (
        <>
          <span className="num">{String(d.persisted_before_outcome_revealed)}</span>
          <span className="text-muted"> · event first revealed at seq </span>
          <span className="num">{d.event_first_reveal_seq}</span>
        </>
      ),
      state: d.persisted_before_outcome_revealed ? "true" : "false",
      testId: "unseal-line-before",
    },
  ];
}

const GLYPH: Record<LineState, { g: string; cls: string; sr: string }> = {
  returned: { g: "●", cls: "text-accent", sr: "returned" },
  missing: { g: "○", cls: "text-muted", sr: "not available" },
  true: { g: "✓", cls: "text-viable", sr: "true" },
  false: { g: "✗", cls: "text-fail", sr: "false" },
};

export function UnsealSequence({ data, children }: { data: RevealResponse; children?: ReactNode }) {
  const [runKey, setRunKey] = useState(0);
  const { elapsed, skip } = useClock(TOTAL, true, runKey);
  const done = elapsed === DONE;
  const open = progress(elapsed, OPEN_AT, OPEN_DUR);
  const lines = linesFor(data);
  const { sealed, scores } = data;
  const market = data.baselines.market;
  const yes = sealed.outcome === "YES";
  const showOutcome = elapsed >= OUTCOME_AT;
  const outcomeIn = progress(elapsed, OUTCOME_AT, 320);
  const showRace = elapsed >= RACE_AT;

  return (
    <div className="fl-series flex flex-col gap-5" data-testid="unseal-sequence" data-done={done ? "true" : "false"}>
      <SeriesStyle />
      <div className="flex items-center gap-4">
        <Envelope open={open} />
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <p className="kicker">Unsealing · {sealed.event_id}</p>
          <p className="flex flex-wrap items-center gap-1.5">
            <ProvenanceBadge kind={open >= 1 ? "REVEALED" : "SEALED"} />
            <span className="font-mono text-[10.5px] text-muted">from the reveal response</span>
          </p>
        </div>
        {done ? (
          <button type="button" onClick={() => setRunKey((k) => k + 1)} className={`shrink-0 ${BUTTON_SECONDARY}`}>
            Replay
          </button>
        ) : (
          <button type="button" onClick={skip} className={`shrink-0 ${BUTTON_SECONDARY}`}>
            Skip
          </button>
        )}
      </div>

      <div className="flex flex-col gap-1">
        <p className="text-xs leading-relaxed text-muted">
          The API unseals only a persisted forecast whose stored prompt, snapshot and record hashes still match (else
          409 NOT_REVEALABLE). Fields of its 2xx response:
        </p>
        <ul className="flex flex-col" aria-label="Audit fields from the reveal response">
          {lines.map((l, i) => {
            const shown = elapsed >= LINE_AT + i * LINE_GAP;
            const g = GLYPH[l.state];
            return (
              <li
                key={l.key}
                data-testid={l.testId}
                data-state={shown ? l.state : "pending"}
                className="grid min-h-8 grid-cols-[1rem_minmax(0,1fr)] items-baseline gap-x-2 border-b border-line/60 py-1.5 last:border-b-0 sm:grid-cols-[1rem_10.5rem_minmax(0,1fr)]"
              >
                {shown ? (
                  <>
                    <span className={`font-mono text-sm ${g.cls}`} aria-hidden="true">
                      {g.g}
                    </span>
                    <span className="font-mono text-[10.5px] uppercase tracking-[0.1em] text-muted">
                      {l.key}
                      <span className="sr-only"> ({g.sr})</span>
                    </span>
                    <span
                      title={l.title}
                      className={`col-start-2 min-w-0 font-mono text-[11.5px] sm:col-start-3 ${
                        l.state === "missing" ? "uppercase tracking-[0.06em] text-muted" : l.state === "false" ? "text-fail" : "text-text-2"
                      }`}
                    >
                      {l.value}
                    </span>
                  </>
                ) : (
                  <span className="col-span-full h-3 w-24 self-center rounded-sm bg-hover" aria-hidden="true" />
                )}
              </li>
            );
          })}
        </ul>
      </div>

      <div className="min-h-[6.5rem]">
        {showOutcome ? (
          <div
            className="flex flex-col gap-1.5"
            style={{ opacity: outcomeIn, transform: `translateY(${(1 - outcomeIn) * 8}px)` }}
            data-testid="unseal-outcome"
          >
            <p className="kicker">Outcome · {sealed.event_id}</p>
            <p className={`display text-[clamp(3rem,5vw,5rem)] leading-none ${yes ? "text-viable" : "text-fail"}`}>
              {sealed.outcome}
            </p>
            <p className="font-mono text-[11px] text-muted">
              y = <span className="num text-text-2">{data.y}</span> · resolved{" "}
              <span className="text-text-2">{sealed.resolved_at ?? "not stated"}</span>
            </p>
          </div>
        ) : (
          <div className="hatch flex h-[6.5rem] items-center justify-center rounded-md border border-dashed border-risk/50">
            <span className="font-mono text-sm uppercase tracking-[0.2em] text-risk">Sealed</span>
          </div>
        )}
      </div>

      <div className="flex flex-col gap-2.5" data-testid="unseal-race">
        <p className="kicker">Brier on this event · lower is better</p>
        {showRace ? (
          <>
            <RaceBar
              series="agent"
              label="This forecast"
              sublabel={`p_yes ${fmt4(data.prediction.p_yes)}`}
              value={scores.brier}
              max={1}
              elapsed={elapsed}
              at={RACE_AT}
              dur={RACE_DUR}
              testId="unseal-brier-agent"
            />
            <RaceBar
              series="market"
              label="Market-only"
              sublabel={
                market
                  ? `${isSyntheticRef(market.ref) || sealed.provenance === "SYNTHETIC" ? "SYNTHETIC · " : ""}p_yes ${fmt4(market.p_yes)}`
                  : "no baseline at this as_of"
              }
              value={market ? market.brier : null}
              max={1}
              elapsed={elapsed}
              at={RACE_AT + 60}
              dur={RACE_DUR}
              testId="unseal-brier-market"
            />
            <RaceBar
              series="naive"
              label="Naive"
              sublabel="constant p = 0.5"
              value={data.baselines.naive.brier}
              max={1}
              elapsed={elapsed}
              at={RACE_AT + 120}
              dur={RACE_DUR}
              testId="unseal-brier-naive"
            />
            <RaceAxis max={1} caption="Brier scale" />
          </>
        ) : (
          <div className="h-[7.5rem] rounded-md border border-dashed border-line" aria-hidden="true" />
        )}
      </div>

      {/* The rest of the reveal readout follows once the sequence has drawn its final frame. */}
      <div
        inert={!done}
        aria-hidden={!done}
        className="flex flex-col gap-6 transition-opacity duration-500"
        style={{ opacity: done ? 1 : 0 }}
      >
        {children}
      </div>
    </div>
  );
}

/** A sealed envelope; `open` (0..1) lifts the flap and breaks the seal. Decorative. */
function Envelope({ open }: { open: number }) {
  return (
    <svg
      width="76"
      height="56"
      viewBox="0 0 76 56"
      aria-hidden="true"
      className="shrink-0 overflow-visible"
      style={{ color: open >= 1 ? "var(--viable)" : "var(--risk)" }}
    >
      <rect x="2" y="12" width="72" height="42" rx="3" fill="var(--bg)" stroke="currentColor" strokeWidth="1.5" />
      <path d="M2 54 L38 30 L74 54" fill="none" stroke="currentColor" strokeOpacity="0.45" strokeWidth="1.2" />
      {/* Flap: hinged at the top edge (y = 12); scaleY goes 1 → −1 as it opens. */}
      <g style={{ transform: `translateY(12px) scaleY(${1 - 2 * open}) translateY(-12px)`, transformOrigin: "0 0" }}>
        <path d="M2 12 L38 38 L74 12 Z" fill="var(--bg-elevated)" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
      </g>
      <g style={{ opacity: 1 - open, transform: `scale(${1 + open * 0.6})`, transformOrigin: "38px 36px" }}>
        <circle cx="38" cy="36" r="7" fill="var(--risk)" />
        <rect x="35" y="33" width="6" height="6" fill="var(--bg)" />
      </g>
    </svg>
  );
}
