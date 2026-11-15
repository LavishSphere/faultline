"use client";

import { useRef } from "react";
import type { Comparison, Scorecard } from "@/lib/benchmark";
import { niceCeil, progress, useClock, useInView } from "../reveal/motion";
import { RaceAxis, RaceBar, SeriesStyle } from "../reveal/series";
import { fmtPrecise } from "../reveal/ui";

/**
 * Score race (#164) on one recorded scorecard: agent / market-only / naive bars for mean Brier and mean log loss,
 * then Δ Brier with its paired-bootstrap interval drawn against zero. Every bar ends on the API's value (count-ups
 * land on `fmt4`, the table's formatting); scales are display geometry with their end labeled. No verdict is drawn
 * from the interval here: the card's verdict text is the API's, above. Plays when first scrolled into view; reduced
 * motion shows the final state.
 */

const RACE_DUR = 700;
const DELTA_AT = 520;
const TOTAL = DELTA_AT + 800;

export function ScoreRace({ card }: { card: Scorecard }) {
  const ref = useRef<HTMLDivElement>(null);
  const seen = useInView(ref);
  const { elapsed } = useClock(TOTAL, seen);
  const agentKey = card.agent_variant;
  const s = card.summary;
  const metric = (key: "mean_brier" | "mean_log_loss") => {
    const v = (f: string) => (s && s[f] ? s[f][key] : null);
    const values = { agent: v(agentKey), market: v("market"), naive: v("naive") };
    const present = Object.values(values).filter((x): x is number => typeof x === "number");
    return { values, max: niceCeil(present.length ? Math.max(...present) : 1) };
  };
  const brier = metric("mean_brier");
  const logLoss = metric("mean_log_loss");

  return (
    <div ref={ref} className="fl-series flex flex-col gap-5 border-b border-line px-5 py-5" data-testid="score-race">
      <SeriesStyle />
      <div className="grid grid-cols-1 gap-6">
        {(
          [
            ["Mean Brier", brier, "brier"],
            ["Mean log loss", logLoss, "logloss"],
          ] as const
        ).map(([title, m, id], gi) => (
          <div key={id} className="flex min-w-0 flex-col gap-2.5">
            <p className="kicker">{title} · lower is better</p>
            <RaceBar series="agent" label="Agent" sublabel={agentKey} value={m.values.agent} max={m.max} elapsed={elapsed} at={gi * 90} dur={RACE_DUR} testId={`race-${id}-agent`} />
            <RaceBar series="market" label="Market-only" sublabel="market" value={m.values.market} max={m.max} elapsed={elapsed} at={gi * 90 + 60} dur={RACE_DUR} testId={`race-${id}-market`} />
            <RaceBar series="naive" label="Naive" sublabel="p = 0.5" value={m.values.naive} max={m.max} elapsed={elapsed} at={gi * 90 + 120} dur={RACE_DUR} testId={`race-${id}-naive`} />
            <RaceAxis max={m.max} caption="scale" />
          </div>
        ))}
      </div>
      <DeltaInterval cmp={card.comparison} elapsed={elapsed} />
    </div>
  );
}

/**
 * Δ Brier (agent − market) and its interval on a symmetric axis around zero. Left of zero = agent's mean Brier was
 * lower. `cmp === null` (the API sent no comparison) renders NOT AVAILABLE.
 */
function DeltaInterval({ cmp, elapsed }: { cmp: Comparison | null; elapsed: number }) {
  if (!cmp) {
    return (
      <div className="flex flex-col gap-1.5" data-testid="race-delta">
        <p className="kicker">Δ Brier vs market · paired bootstrap interval</p>
        <p className="font-mono text-sm uppercase tracking-[0.08em] text-muted">Not available · the API sent no comparison</p>
      </div>
    );
  }
  const { mean_delta_brier: mean, ci_low: lo, ci_high: hi } = cmp;
  const ext = niceCeil(Math.max(Math.abs(lo), Math.abs(hi), Math.abs(mean)) * 1.1);
  const x = (v: number) => 50 + (v / ext) * 50; // % across the track
  const grow = progress(elapsed, DELTA_AT, 650);
  const dot = progress(elapsed, DELTA_AT + 350, 300);
  const l = x(mean) + (x(lo) - x(mean)) * grow;
  const r = x(mean) + (x(hi) - x(mean)) * grow;
  return (
    <div className="flex flex-col gap-2" data-testid="race-delta">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <p className="kicker">Δ Brier vs market · {cmp.agent_variant} − market · paired bootstrap interval</p>
        <p className="font-mono text-sm text-text">
          <span className="num" data-testid="race-delta-mean" title={String(mean)}>{fmtPrecise(mean)}</span>{" "}
          <span className="text-text-2">
            [<span className="num" title={String(lo)}>{fmtPrecise(lo)}</span>,{" "}
            <span className="num" title={String(hi)}>{fmtPrecise(hi)}</span>]
          </span>{" "}
          <span className="text-[10.5px] text-muted">
            confidence <span className="num">{cmp.confidence}</span>
          </span>
        </p>
      </div>
      <div className="relative h-9" aria-hidden="true">
        <div className="absolute inset-x-0 top-1/2 h-px -translate-y-1/2 bg-line-strong" />
        {/* zero: no difference */}
        <div className="absolute top-0 bottom-0 w-px bg-text-2" style={{ left: "50%" }} />
        <div
          className="absolute top-1/2 h-2.5 -translate-y-1/2 rounded-full bg-accent/35 ring-1 ring-accent"
          style={{ left: `${Math.min(l, r)}%`, width: `${Math.abs(r - l)}%` }}
        />
        <div
          className="absolute top-1/2 h-3.5 w-3.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-elevated bg-accent"
          style={{ left: `${x(mean)}%`, opacity: dot, transform: `translate(-50%, -50%) scale(${0.4 + 0.6 * dot})` }}
        />
      </div>
      <div className="grid grid-cols-3 font-mono text-[10px] text-muted">
        <span className="num">−{ext}</span>
        <span className="text-center">0 · no difference</span>
        <span className="num text-right">+{ext}</span>
      </div>
      <div className="flex justify-between gap-4 font-mono text-[10px] uppercase tracking-[0.1em] text-muted">
        <span>← agent lower Brier</span>
        <span className="text-right">market lower Brier →</span>
      </div>
    </div>
  );
}
