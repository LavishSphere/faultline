"use client";

import { useEffect, useMemo, useRef, useState, type RefObject } from "react";
import {
  SCORABLE_VARIANTS,
  type EventScore,
  type ScorableVariant,
  type VariantCard,
} from "@/lib/benchmark";
import { getCases } from "@/lib/replay";
import { Panel } from "../Panel";
import { ProvenanceBadge } from "../ProvenanceBadge";
import { progress, useClock, useInView } from "../reveal/motion";
import { SERIES_VAR, SeriesMark, SeriesStyle } from "../reveal/series";
import { Missing, fmt4 } from "../reveal/ui";
import { cardBadges } from "./badges";

/**
 * D.2 Results by event (#164): every event a COMMITTED recorded scorecard scored (GET /api/benchmark `per_event`),
 * on one timeline, in two plots that share the event axis (one measure each):
 *   1. the agent's forecast p_yes and the market baseline p per event and, only after an explicit click, the outcome
 *      y (#117: the y of every scored event never shows by accident of layout);
 *   2. each event's Brier for the agent and the market-only baseline, with the naive p = 0.5 line as reference.
 * Hover or focus an event for its id, cutoff date, p's and Brier.
 *
 * - p (model) and p (market) are the row's own `agent_p_yes` / `market_p_yes` (#180): the persisted forecast and the
 *   market baseline the gate froze, i.e. the inputs of that row's Brier. The API refuses a card whose p disagrees with
 *   its Brier and checks a committed card's p against the run's rows. A row without them (a multi-snapshot row) shows
 *   NOT AVAILABLE. Nothing is back-solved from a Brier score.
 * - Dates are the case cutoffs (`as_of`) that GET /api/cases serves for the same event_id; an event it does not
 *   list has date NOT AVAILABLE, and then events keep the API's order.
 * - Only `origin: "committed"` cards (data/recorded_runs, the official run script) are plotted. With none, the
 *   panel says NOT AVAILABLE.
 * - The label and caveat are the card's, verbatim. Provenance: RECORDED RUN plus the card's own.
 */

type CaseDates = { kind: "loading" } | { kind: "done"; byId: Map<string, string> | null };

/** The row's served p (#180), or null = NOT AVAILABLE. Read as served; never derived from a score. */
const agentP = (e: EventScore): number | null => (typeof e.agent_p_yes === "number" ? e.agent_p_yes : null);
const marketP = (e: EventScore): number | null => (typeof e.market_p_yes === "number" ? e.market_p_yes : null);

// Geometry in CSS pixels: the SVG's width follows its container (ResizeObserver), so text keeps its size.
const MIN_W = 620;
const LEFT = 56;
const RIGHT = 20;
const TOP = 26;
const STRIP_H = 28;
const TICKS = [0, 0.25, 0.5, 0.75, 1];

function layout(width: number) {
  const W = Math.max(MIN_W, Math.round(width));
  const P_H = W >= 1200 ? 150 : 120;
  const B_TOP = TOP + P_H + 52;
  const PLOT_H = W >= 1200 ? 220 : W >= 900 ? 190 : 160;
  const STRIP_Y = B_TOP + PLOT_H + 22;
  const LABEL_Y = STRIP_Y + STRIP_H + 22;
  return { W, P_H, B_TOP, PLOT_H, STRIP_Y, LABEL_Y, H: LABEL_Y + 14 };
}

/** Width of an element in CSS pixels, kept current. */
function useWidth(ref: RefObject<HTMLDivElement | null>): number {
  const [w, setW] = useState(1000);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver((entries) => {
      const cw = entries[0]?.contentRect.width;
      if (cw) setW(cw);
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, [ref]);
  return w;
}

export function ResultsChart({
  cards,
  loading,
  revealedPredictionId,
}: {
  /** The first served card per variant (firstPerVariant); only committed ones are plotted. */
  cards: Partial<Record<ScorableVariant, VariantCard>>;
  loading: boolean;
  revealedPredictionId: string | null;
}) {
  const committed = SCORABLE_VARIANTS.map((v) => cards[v]).filter(
    (c): c is VariantCard => !!c && c.record.origin === "committed",
  );
  const computedOnly = !committed.length && SCORABLE_VARIANTS.some((v) => cards[v]);
  const [variant, setVariant] = useState<ScorableVariant | null>(null);
  const entry = committed.find((c) => c.variant === variant) ?? committed[0] ?? null;

  if (!entry) {
    return (
      <Panel code="D.2" title="Results by event" provenance={loading ? [] : "NOT AVAILABLE"}>
        <div className="flex flex-col gap-4" data-testid="results-chart-empty">
          <div className="relative overflow-hidden rounded-md border border-dashed border-line-strong">
            <svg viewBox="0 0 1000 150" className="block h-28 w-full md:h-36" aria-hidden="true" preserveAspectRatio="none">
              {[0, 1, 2, 3].map((k) => (
                <line key={k} x1="0" x2="1000" y1={20 + k * 36} y2={20 + k * 36} stroke="var(--border)" strokeDasharray="3 6" />
              ))}
            </svg>
            <div className="absolute inset-0 flex flex-col items-center justify-center gap-1.5 px-4 text-center">
              <p className="font-mono text-2xl font-medium uppercase tracking-[0.1em] text-muted md:text-3xl">
                {loading ? "Requesting" : "Not available"}
              </p>
              {!loading ? (
                <p className="text-sm text-text-2" data-testid="results-chart-empty-note">
                  Appears after the official recorded run.
                </p>
              ) : null}
            </div>
          </div>
          <p className="text-xs leading-relaxed text-muted">
            {loading
              ? "Waiting for GET /api/benchmark; nothing is drawn until it answers."
              : computedOnly
                ? "The API served only computed scorecards (var/scorecards on that server). This chart plots committed runs only (data/recorded_runs, written by the official run script)."
                : "No committed recorded scorecard was served, so no event is plotted and no number is shown in its place."}
          </p>
        </div>
      </Panel>
    );
  }

  return (
    <Panel code="D.2" title="Results by event" provenance={cardBadges(entry.card)}>
      <ChartBody
        key={`${entry.variant}-${entry.record.scorecard_sha256}`}
        entry={entry}
        variants={committed.map((c) => c.variant)}
        onVariant={setVariant}
        revealedPredictionId={revealedPredictionId}
      />
    </Panel>
  );
}

function ChartBody({
  entry,
  variants,
  onVariant,
  revealedPredictionId,
}: {
  entry: VariantCard;
  variants: ScorableVariant[];
  onVariant: (v: ScorableVariant) => void;
  revealedPredictionId: string | null;
}) {
  const { card, record } = entry;
  const agentKey = card.agent_variant;
  const [dates, setDates] = useState<CaseDates>({ kind: "loading" });
  const [showY, setShowY] = useState(false);
  const [active, setActive] = useState<number | null>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const seen = useInView(wrapRef);
  const n = card.per_event.length;
  const { elapsed } = useClock(900 + n * 45, seen);

  useEffect(() => {
    const controller = new AbortController();
    void getCases(controller.signal).then((res) => {
      if (controller.signal.aborted) return;
      setDates({
        kind: "done",
        byId: res.ok ? new Map(res.data.items.map((c) => [c.event_id, c.as_of])) : null,
      });
    });
    return () => controller.abort();
  }, []);

  const byId = dates.kind === "done" ? dates.byId : null;
  // Order only: by the served case cutoff when every event has one, else the API's own order.
  const rows = useMemo(() => {
    const withDate = card.per_event.map((e, i) => ({ e, i, asOf: byId?.get(e.event_id) ?? null }));
    if (withDate.every((r) => r.asOf !== null)) {
      withDate.sort((a, b) => Date.parse(a.asOf as string) - Date.parse(b.asOf as string) || a.i - b.i);
    }
    return withDate;
  }, [card.per_event, byId]);

  const sizeRef = useRef<HTMLDivElement>(null);
  const { W, P_H, B_TOP, PLOT_H, STRIP_Y, LABEL_Y, H } = layout(useWidth(sizeRef));
  const step = n ? (W - LEFT - RIGHT) / n : 0;
  const cx = (i: number) => LEFT + (i + 0.5) * step;
  const cy = (b: number) => B_TOP + (1 - Math.max(0, Math.min(1, b))) * PLOT_H;
  const py = (v: number) => TOP + (1 - Math.max(0, Math.min(1, v))) * P_H;
  const val = (e: EventScore, f: string) => (typeof e.brier[f] === "number" ? e.brier[f] : null);
  const mine = (e: EventScore) => !!revealedPredictionId && e.prediction_ids.includes(revealedPredictionId);

  const path = (f: string) => {
    let d = "";
    let pen = false;
    rows.forEach((r, i) => {
      const b = val(r.e, f);
      if (b === null) {
        pen = false;
        return;
      }
      d += `${pen ? "L" : "M"}${cx(i).toFixed(1)} ${cy(b).toFixed(1)} `;
      pen = true;
    });
    return d.trim();
  };

  const draw = progress(elapsed, 80, 700);
  const markerIn = (i: number) => progress(elapsed, 160 + i * 45, 260);
  const labelEvery = n > 20 ? Math.ceil(n / 12) : 1;
  const act = active !== null ? rows[active] : null;

  return (
    <div className="fl-series flex flex-col gap-4" data-testid="results-chart">
      <SeriesStyle />
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div className="flex min-w-0 flex-col gap-1.5">
          <p className="font-mono text-[13px] tracking-[0.04em] text-text-2" data-testid="results-chart-label">
            {card.label}
          </p>
          <p className="text-xs leading-relaxed text-muted">
            <span className="num text-text-2">{n}</span> scored events · committed run{" "}
            <span className="break-all text-text-2">{record.run_id ?? "none"}</span> · recorded {record.recorded_at}
          </p>
          {card.caveat ? (
            <p
              className="flex w-fit max-w-full items-baseline gap-1.5 rounded-sm border border-risk/60 px-1.5 py-[3px] font-mono text-[11px] leading-snug text-risk"
              title="Sample-size caveat from the API"
            >
              <span aria-hidden="true">!</span>
              <span data-testid="results-chart-caveat">{card.caveat}</span>
            </p>
          ) : null}
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-2">
          {variants.length > 1 ? (
            <div className="flex flex-wrap gap-1" role="group" aria-label="Scorecard variant">
              {variants.map((v) => (
                <button
                  key={v}
                  type="button"
                  aria-pressed={v === entry.variant}
                  onClick={() => onVariant(v)}
                  className={`rounded-md border px-2.5 py-1.5 font-mono text-[11px] tracking-[0.06em] transition-colors ${
                    v === entry.variant ? "border-accent/70 bg-accent-soft text-text" : "border-line text-text-2 hover:bg-hover"
                  }`}
                >
                  {v}
                </button>
              ))}
            </div>
          ) : null}
          <button
            type="button"
            aria-pressed={showY}
            onClick={() => setShowY((s) => !s)}
            data-testid="results-chart-toggle-y"
            className={`rounded-md border px-2.5 py-1.5 font-mono text-[11px] uppercase tracking-[0.1em] transition-colors ${
              showY ? "border-line-strong text-text-2 hover:bg-hover" : "border-risk/60 text-risk hover:bg-risk/10"
            }`}
          >
            {showY ? "Hide outcomes" : "Show outcomes (y of every scored event)"}
          </button>
        </div>
      </div>

      <ul className="flex flex-wrap gap-x-5 gap-y-1.5 text-xs text-text-2" aria-label="Legend">
        <li className="flex items-center gap-1.5">
          <SeriesMark series="agent" /> Agent <span className="font-mono text-[10.5px] text-muted">{agentKey}</span>
        </li>
        <li className="flex items-center gap-1.5">
          <SeriesMark series="market" /> Market-only <span className="font-mono text-[10.5px] text-muted">p (market-implied, price-derived) and Brier</span>
        </li>
        <li className="flex items-center gap-1.5">
          <SeriesMark series="naive" /> Naive <span className="font-mono text-[10.5px] text-muted">p = 0.5</span>
        </li>
        <li className="flex items-center gap-1.5">
          <span className="inline-block h-2.5 w-3.5 rounded-[2px] border border-line-strong" aria-hidden="true" /> Outcome y
          <span className="font-mono text-[10.5px] text-muted">{showY ? "shown" : "sealed on this chart"}</span>
        </li>
      </ul>

      <p className="-mt-2 font-mono text-[10.5px] leading-snug text-muted" data-testid="results-chart-market-label">
        Market-only uses the {card.market_label}.
      </p>

      <EventList rows={rows} agentKey={agentKey} showY={showY} mine={mine} />

      <div ref={wrapRef} className="relative hidden overflow-x-auto sm:block" onMouseLeave={() => setActive(null)}>
        <div ref={sizeRef} className="relative min-w-[620px]">
          <svg
            viewBox={`0 0 ${W} ${H}`}
            width={W}
            height={H}
            className="block"
            role="img"
            aria-label={`${n} scored events: the agent's forecast p_yes and the market baseline p per event, then Brier per event for ${agentKey} and the market-only baseline. Hover or focus an event for its values.`}
          >
            {/* plot 1: forecast p_yes (model), market baseline p and, when shown, outcome y */}
            <text x={LEFT} y={TOP - 12} fontSize="12" fill="var(--muted)" className="font-mono" letterSpacing="1.2">
              {showY ? "P_YES · MODEL AND MARKET · OUTCOME Y" : "P_YES · MODEL AND MARKET"}
            </text>
            {[0, 0.5, 1].map((t) => (
              <g key={`pt-${t}`}>
                <line
                  x1={LEFT}
                  x2={W - RIGHT}
                  y1={py(t)}
                  y2={py(t)}
                  stroke="var(--border)"
                  strokeDasharray={t === 0.5 ? "4 4" : undefined}
                />
                <text x={LEFT - 10} y={py(t) + 4} textAnchor="end" className="num" fontSize="12.5" fill="var(--muted)">
                  {t}
                </text>
              </g>
            ))}

            {/* plot 2: grid + y axis */}
            {TICKS.map((t) => (
              <g key={t}>
                <line x1={LEFT} x2={W - RIGHT} y1={cy(t)} y2={cy(t)} stroke="var(--border)" strokeWidth="1" />
                <text x={LEFT - 10} y={cy(t) + 4} textAnchor="end" className="num" fontSize="12.5" fill="var(--muted)">
                  {t}
                </text>
              </g>
            ))}
            <text x={LEFT} y={B_TOP - 12} fontSize="12" fill="var(--muted)" className="font-mono" letterSpacing="1.2">
              BRIER PER EVENT · LOWER IS BETTER
            </text>

            {act ? (
              <rect
                x={cx(active as number) - step / 2}
                y={TOP}
                width={step}
                height={LABEL_Y - TOP + 4}
                fill="var(--bg-hover)"
                opacity="0.9"
              />
            ) : null}
            {rows.map((r, i) =>
              mine(r.e) ? (
                <rect key={`m-${i}`} x={cx(i) - step / 2} y={TOP} width={step} height={B_TOP + PLOT_H - TOP} fill="var(--accent-soft)" />
              ) : null,
            )}

            {/* p markers (agent circle, market diamond); with y shown, a stick from the agent's p to y and a ring at y */}
            {rows.map((r, i) => {
              const a = agentP(r.e);
              const ps = a === null ? [] : [a];
              const mp = marketP(r.e);
              const k = markerIn(i);
              const yes = r.e.y === 1;
              return (
                <g key={`pp-${r.e.event_id}`} style={{ opacity: k }} data-testid="results-chart-p">
                  {showY
                    ? ps.map((v, j) => (
                        <line
                          key={`s-${j}`}
                          x1={cx(i)}
                          x2={cx(i)}
                          y1={py(v)}
                          y2={py(r.e.y)}
                          stroke={yes ? "var(--viable)" : "var(--fail)"}
                          strokeOpacity="0.55"
                          strokeWidth="2"
                        />
                      ))
                    : null}
                  {showY ? (
                    <circle
                      cx={cx(i)}
                      cy={py(r.e.y)}
                      r="6"
                      fill="var(--bg-elevated)"
                      stroke={yes ? "var(--viable)" : "var(--fail)"}
                      strokeWidth="2"
                    />
                  ) : null}
                  {ps.map((v, j) => (
                    <circle
                      key={`c-${j}`}
                      cx={cx(i)}
                      cy={py(v)}
                      r={6 * (0.5 + 0.5 * k)}
                      fill={SERIES_VAR.agent}
                      stroke="var(--bg-elevated)"
                      strokeWidth="2"
                    />
                  ))}
                  {mp !== null ? (
                    <rect
                      x={cx(i) - 4.5}
                      y={py(mp) - 4.5}
                      width="9"
                      height="9"
                      transform={`rotate(45 ${cx(i)} ${py(mp)})`}
                      fill={SERIES_VAR.market}
                      stroke="var(--bg-elevated)"
                      strokeWidth="2"
                      data-testid="results-chart-p-market"
                    />
                  ) : null}
                  {ps.length === 0 ? (
                    <text x={cx(i)} y={py(0.5) + 4} textAnchor="middle" fontSize="10" fill="var(--muted)" className="font-mono">
                      n/a
                    </text>
                  ) : null}
                </g>
              );
            })}

            {/* series lines */}
            {(["naive", "market", agentKey] as const).map((f) => {
              const s = f === "naive" ? "naive" : f === "market" ? "market" : "agent";
              const d = path(f);
              return d ? (
                <path
                  key={f}
                  d={d}
                  pathLength={1}
                  fill="none"
                  stroke={SERIES_VAR[s]}
                  strokeWidth={s === "naive" ? 1.5 : 2}
                  strokeLinejoin="round"
                  strokeLinecap="round"
                  strokeDasharray={s === "naive" ? "0.004 0.006" : "1"}
                  strokeDashoffset={s === "naive" ? 0 : 1 - draw}
                  opacity={s === "naive" ? 0.8 * draw : 1}
                />
              ) : null;
            })}

            {/* markers */}
            {rows.map((r, i) => {
              const k = markerIn(i);
              const a = val(r.e, agentKey);
              const m = val(r.e, "market");
              return (
                <g key={`p-${r.e.event_id}`} style={{ opacity: k }}>
                  {m !== null ? (
                    <rect
                      x={cx(i) - 5}
                      y={cy(m) - 5}
                      width="10"
                      height="10"
                      transform={`rotate(45 ${cx(i)} ${cy(m)})`}
                      fill={SERIES_VAR.market}
                      stroke="var(--bg-elevated)"
                      strokeWidth="2"
                    />
                  ) : null}
                  {a !== null ? (
                    <circle cx={cx(i)} cy={cy(a)} r={5.5 * (0.5 + 0.5 * k)} fill={SERIES_VAR.agent} stroke="var(--bg-elevated)" strokeWidth="2" />
                  ) : null}
                </g>
              );
            })}

            {/* outcome strip */}
            <text x={LEFT - 10} y={STRIP_Y + STRIP_H / 2 + 4} textAnchor="end" fontSize="12.5" fill="var(--muted)" className="font-mono">
              y
            </text>
            {rows.map((r, i) => {
              const x = cx(i) - step / 2 + 2;
              const w = Math.max(2, step - 4);
              if (!showY) {
                return (
                  <g key={`y-${i}`}>
                    <rect x={x} y={STRIP_Y} width={w} height={STRIP_H} rx="3" fill="none" stroke="var(--border-strong)" strokeDasharray="3 3" />
                    <text x={cx(i)} y={STRIP_Y + STRIP_H / 2 + 4} textAnchor="middle" fontSize="10" fill="var(--muted)">
                      ■
                    </text>
                  </g>
                );
              }
              const yes = r.e.y === 1;
              return (
                <g key={`y-${i}`} data-testid="results-chart-y">
                  <rect
                    x={x}
                    y={STRIP_Y}
                    width={w}
                    height={STRIP_H}
                    rx="3"
                    fill={yes ? "var(--viable)" : "var(--fail)"}
                    fillOpacity="0.16"
                    stroke={yes ? "var(--viable)" : "var(--fail)"}
                    strokeOpacity="0.7"
                  />
                  <text x={cx(i)} y={STRIP_Y + STRIP_H / 2 + 4} textAnchor="middle" fontSize="13" className="num" fill="var(--text)">
                    {r.e.y}
                  </text>
                </g>
              );
            })}

            {/* x labels */}
            {rows.map((r, i) =>
              i % labelEvery === 0 ? (
                <text key={`x-${i}`} x={cx(i)} y={LABEL_Y} textAnchor="middle" fontSize="12" className="num" fill="var(--muted)">
                  {r.asOf ? r.asOf.slice(0, 7) : `#${i + 1}`}
                </text>
              ) : null,
            )}

            {/* hit targets: a full-height column per event, focusable */}
            {rows.map((r, i) => (
              <rect
                key={`h-${i}`}
                x={cx(i) - step / 2}
                y={0}
                width={step}
                height={H}
                fill="transparent"
                tabIndex={0}
                role="button"
                aria-label={`${r.e.event_id}: agent Brier ${fmtOr(val(r.e, agentKey))}, market Brier ${fmtOr(val(r.e, "market"))}`}
                data-testid="results-chart-event"
                onMouseEnter={() => setActive(i)}
                onFocus={() => setActive(i)}
                onBlur={() => setActive(null)}
                style={{ outline: "none" }}
              />
            ))}
          </svg>

          {act ? (
            <Tooltip
              left={(cx(active as number) / W) * 100}
              e={act.e}
              asOf={act.asOf}
              datesLoading={dates.kind === "loading"}
              p={agentP(act.e)}
              mp={marketP(act.e)}
              agentKey={agentKey}
              showY={showY}
              mine={mine(act.e)}
            />
          ) : null}
        </div>
      </div>

      <div className="flex flex-col gap-1 text-xs leading-relaxed text-muted">
        <p>
          p (model) and p (market) are each row&apos;s agent_p_yes and market_p_yes as GET /api/benchmark serves them: the
          persisted forecast and the market-implied (price-derived) baseline frozen before reveal, the exact inputs of
          that row&apos;s Brier (&ldquo;n/a&rdquo; where the row carries none). Nothing is back-solved from a Brier score.
        </p>
        <p>
          Dates are each case&apos;s forecast cutoff (as_of) from GET /api/cases
          {byId === null && dates.kind === "done" ? " (not available: the cases request failed, so events keep the API's order)" : ""}
          . Brier per event is averaged over that event&apos;s snapshots by the API.
        </p>
      </div>
    </div>
  );
}

/**
 * Below 640 px the timeline becomes a list (same rows, same order, same values): one line per event with the agent
 * and market Brier as short bars on a 0 to 1 scale, and y only when shown.
 */
function EventList({
  rows,
  agentKey,
  showY,
  mine,
}: {
  rows: { e: EventScore; asOf: string | null }[];
  agentKey: string;
  showY: boolean;
  mine: (e: EventScore) => boolean;
}) {
  const bar = (v: number | undefined, s: "agent" | "market") =>
    typeof v === "number" ? (
      <span className="flex items-center gap-2">
        <span className="relative h-1.5 flex-1 overflow-hidden rounded-full bg-hover" aria-hidden="true">
          <span
            className="absolute inset-y-0 left-0 rounded-full"
            style={{ width: `${Math.max(0, Math.min(1, v)) * 100}%`, background: SERIES_VAR[s] }}
          />
        </span>
        <span className="num w-[3.6rem] text-right text-xs text-text">{fmt4(v)}</span>
      </span>
    ) : (
      <Missing />
    );
  return (
    <div className="flex flex-col gap-1 sm:hidden">
    <p className="kicker">Brier per event · scale 0 to 1 · lower is better</p>
    <ol className="flex flex-col" aria-label="Scored events">
      {rows.map((r, i) => (
        <li
          key={r.e.event_id}
          data-testid="results-chart-row"
          className={`grid grid-cols-[minmax(0,1fr)_2.25rem] gap-x-3 border-b border-line/70 py-2.5 last:border-b-0 ${mine(r.e) ? "bg-accent-soft" : ""}`}
        >
          <div className="flex min-w-0 flex-col gap-1">
            <p className="flex items-baseline gap-2 font-mono text-[11px] text-text-2">
              <span className="num text-muted">{r.asOf ? r.asOf.slice(0, 10) : `#${i + 1}`}</span>
              <span className="truncate">{r.e.event_id}</span>
              {mine(r.e) ? <span className="shrink-0 text-accent">← this forecast</span> : null}
            </p>
            <p className="font-mono text-[11px] text-muted">
              p (model) <PVal p={agentP(r.e)} /> · p (market) <PVal p={marketP(r.e)} />
            </p>
            <div className="grid grid-cols-[auto_minmax(0,1fr)] items-center gap-x-2 gap-y-1">
              <SeriesMark series="agent" size={8} />
              {bar(r.e.brier[agentKey], "agent")}
              <SeriesMark series="market" size={8} />
              {bar(r.e.brier.market, "market")}
            </div>
          </div>
          <span
            className={`flex items-center justify-center self-center rounded-sm border py-1 font-mono text-xs ${
              showY
                ? r.e.y === 1
                  ? "border-viable/60 bg-viable/10 text-text"
                  : "border-fail/60 bg-fail/10 text-text"
                : "border-dashed border-line-strong text-muted"
            }`}
          >
            {showY ? <span className="num">{r.e.y}</span> : <span aria-label="outcome sealed on this chart">■</span>}
          </span>
        </li>
      ))}
    </ol>
    </div>
  );
}

/** A served p (4 decimals), else NOT AVAILABLE. */
function PVal({ p }: { p: number | null }) {
  return p === null ? <Missing /> : <span className="num text-text">{fmt4(p)}</span>;
}

function fmtOr(v: number | null): string {
  return v === null ? "not available" : fmt4(v);
}

function Tooltip({
  left,
  e,
  asOf,
  datesLoading,
  p,
  mp,
  agentKey,
  showY,
  mine,
}: {
  left: number;
  e: EventScore;
  asOf: string | null;
  datesLoading: boolean;
  p: number | null;
  mp: number | null;
  agentKey: string;
  showY: boolean;
  mine: boolean;
}) {
  const b = (f: string) => (typeof e.brier[f] === "number" ? <span className="num text-text">{fmt4(e.brier[f])}</span> : <Missing />);
  const flip = left > 62;
  return (
    <div
      role="tooltip"
      data-testid="results-chart-tooltip"
      className="pointer-events-none absolute top-2 z-10 w-[17.5rem] rounded-lg border border-line-strong bg-elevated/90 p-3 shadow-[var(--shadow-panel)] backdrop-blur-[12px]"
      style={flip ? { right: `${100 - left + 2}%` } : { left: `${left + 2}%` }}
    >
      <p className="break-all font-mono text-xs text-text" data-testid="results-chart-tooltip-id">
        {e.event_id}
        {mine ? <span className="ml-2 text-accent">← this forecast</span> : null}
      </p>
      <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 font-mono text-[11px] text-muted">
        <dt>as_of</dt>
        <dd className="text-right text-text-2">{asOf ?? (datesLoading ? "requesting" : <Missing />)}</dd>
        <dt className="flex items-center gap-1.5">
          <SeriesMark series="agent" size={8} /> p (model)
        </dt>
        <dd className="text-right" data-testid="results-chart-tooltip-p">
          <PVal p={p} />
        </dd>
        <dt className="flex items-center gap-1.5">
          <SeriesMark series="market" size={8} /> p (market)
        </dt>
        <dd className="text-right" data-testid="results-chart-tooltip-p-market">
          <PVal p={mp} />
        </dd>
        <dt className="flex items-center gap-1.5">
          <SeriesMark series="agent" size={8} /> Brier agent
        </dt>
        <dd className="text-right">{b(agentKey)}</dd>
        <dt className="flex items-center gap-1.5">
          <SeriesMark series="market" size={8} /> Brier market
        </dt>
        <dd className="text-right">{b("market")}</dd>
        <dt className="flex items-center gap-1.5">
          <SeriesMark series="naive" size={8} /> Brier naive
        </dt>
        <dd className="text-right">{b("naive")}</dd>
        <dt>y</dt>
        <dd className="text-right">
          {showY ? <span className="num text-text">{e.y}</span> : <span className="uppercase tracking-[0.08em] text-risk">sealed here</span>}
        </dd>
        <dt>snapshots</dt>
        <dd className="num text-right text-text-2">{e.n_snapshots}</dd>
      </dl>
      {e.market_refs.length ? <p className="mt-1.5 break-all font-mono text-[10px] text-muted">market: {e.market_refs.join(", ")}</p> : null}
      <div className="mt-2 flex flex-wrap gap-1">
        <ProvenanceBadge kind="RECORDED RUN" />
      </div>
    </div>
  );
}
