"use client";

import { useEffect, useMemo, useRef, useState, type KeyboardEvent, type PointerEvent } from "react";
import { usd, weekRanges } from "@/lib/format";
import "./cascade-fx.css";

/**
 * 26-week cash path (#165): C_t for the baseline, the scenario and the recovery plan, the C_min floor line, and the
 * weeks below it shaded. Every point is an entry of an API array (`baseline.cash` / `result.cash` from
 * POST /api/simulate, `cash` from POST /api/optimize); the weeks below the floor are the API's `weeks_below_floor`.
 * The browser only maps them to pixels (display scaling) and picks round axis ticks.
 */

export interface TimelineSeries {
  id: "baseline" | "scenario" | "plan";
  label: string;
  /** C_t for weeks 1..T, exactly as served; null = NOT AVAILABLE for this request. */
  values: number[] | null;
  /** Where the line comes from, for the legend. */
  source: string;
}

export interface TimelineFloor {
  floor: number;
  firstBelow: number | null;
  weeksBelow: number[];
  /** Which line `weeksBelow` describes (the simulated result the readouts show). */
  of: string;
}

const STYLE: Record<TimelineSeries["id"], { stroke: string; dash?: string; width: number }> = {
  baseline: { stroke: "var(--edge)", dash: "5 4", width: 2 },
  scenario: { stroke: "var(--risk)", width: 2.5 },
  plan: { stroke: "var(--viable)", width: 2.5 },
};

const TICK = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", notation: "compact", maximumFractionDigits: 1 });

/** Round tick step (1, 2, 2.5 or 5 × 10^k) for an axis label; display only. */
function niceStep(span: number, count: number): number {
  const raw = span / Math.max(1, count);
  const mag = Math.pow(10, Math.floor(Math.log10(raw || 1)));
  for (const m of [1, 2, 2.5, 5, 10]) if (raw <= m * mag) return m * mag;
  return 10 * mag;
}

function useWidth<T extends HTMLElement>(): [React.RefObject<T | null>, number] {
  const ref = useRef<T | null>(null);
  const [w, setW] = useState(0);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => {
      const cr = entries[0]?.contentRect;
      if (cr) setW(Math.round(cr.width));
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, w];
}

export function CashTimeline({
  weeks,
  series,
  floor,
  stale,
  reduce,
  drawKey,
}: {
  /** `result.weeks` (1..T) from the API. */
  weeks: number[];
  series: TimelineSeries[];
  /** null = this API build does not report C_min. */
  floor: TimelineFloor | null;
  stale: boolean;
  reduce: boolean;
  /** Changes with each new response, so the lines draw in again. */
  drawKey: string;
}) {
  const [wrapRef, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const H = width < 640 ? 220 : 280;
  const pad = { l: width < 640 ? 46 : 58, r: width < 640 ? 70 : 92, t: 18, b: 28 };
  const T = weeks.length;

  const shown = series.filter((s): s is TimelineSeries & { values: number[] } => s.values !== null && s.values.length === T);

  const scale = useMemo(() => {
    const all: number[] = shown.flatMap((s) => s.values);
    if (floor) all.push(floor.floor);
    if (all.length === 0) return null;
    let lo = Math.min(...all);
    let hi = Math.max(...all);
    if (hi === lo) hi = lo + 1;
    const step = niceStep(hi - lo, 4);
    lo = Math.floor(lo / step) * step;
    hi = Math.ceil(hi / step) * step;
    const ticks: number[] = [];
    for (let v = lo; v <= hi + step / 2; v += step) ticks.push(v);
    return { lo, hi, ticks };
  }, [shown, floor]);

  const innerW = Math.max(1, width - pad.l - pad.r);
  const innerH = H - pad.t - pad.b;
  const x = (i: number) => pad.l + (T <= 1 ? 0 : (i / (T - 1)) * innerW);
  const y = (v: number) => (scale ? pad.t + (1 - (v - scale.lo) / (scale.hi - scale.lo)) * innerH : 0);
  const bandW = T <= 1 ? innerW : innerW / (T - 1);

  const pathOf = (vals: number[]) => vals.map((v, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join("");

  // End labels, nudged apart so they never collide (display only).
  const endLabels = useMemo(() => {
    const items: { id: string; label: string; y: number; fill: string }[] = shown.map((s) => ({
      id: s.id,
      label: s.id === "plan" ? "with plan" : s.label,
      y: y(s.values[T - 1] ?? 0),
      fill: "var(--text-2)",
    }));
    if (floor) items.push({ id: "floor", label: "floor", y: y(floor.floor), fill: floor.firstBelow !== null ? "var(--fail)" : "var(--muted)" });
    items.sort((a, b) => a.y - b.y);
    for (let i = 1; i < items.length; i += 1) {
      const prev = items[i - 1]!;
      if (items[i]!.y - prev.y < 14) items[i]!.y = prev.y + 14;
    }
    return items;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [shown, scale, width]);

  const breached = !!floor && floor.firstBelow !== null;
  const below = new Set(floor?.weeksBelow ?? []);

  const onMove = (e: PointerEvent<SVGSVGElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    const px = e.clientX - r.left;
    const i = Math.round(((px - pad.l) / innerW) * (T - 1));
    setHover(i < 0 || i >= T ? null : i);
  };
  const onKey = (e: KeyboardEvent<SVGSVGElement>) => {
    if (e.key === "ArrowRight") setHover((h) => Math.min(T - 1, (h ?? -1) + 1));
    else if (e.key === "ArrowLeft") setHover((h) => Math.max(0, (h ?? T) - 1));
    else if (e.key === "Escape") setHover(null);
    else return;
    e.preventDefault();
  };

  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1.5 font-mono text-[10.5px] text-text-2">
        <ul className="flex flex-wrap items-center gap-x-4 gap-y-1" aria-label="Legend">
          {series.map((s) => (
            <li key={s.id} className="flex items-center gap-1.5">
              <svg width="22" height="8" aria-hidden="true">
                <line x1="1" x2="21" y1="4" y2="4" stroke={STYLE[s.id].stroke} strokeWidth={STYLE[s.id].width} strokeDasharray={STYLE[s.id].dash} strokeLinecap="round" />
              </svg>
              <span>{s.label}</span>
              <span className="text-muted">
                {s.values === null ? "· NOT AVAILABLE" : `· ${s.source}`}
              </span>
            </li>
          ))}
          <li className="flex items-center gap-1.5">
            <svg width="22" height="8" aria-hidden="true">
              <line x1="1" x2="21" y1="4" y2="4" stroke={breached ? "var(--fail)" : "var(--muted)"} strokeWidth="1.5" strokeDasharray="2 3" />
            </svg>
            <span>{floor ? `floor C_min ${usd(floor.floor)}` : "floor NOT AVAILABLE"}</span>
          </li>
        </ul>
        {floor && floor.firstBelow !== null ? (
          <span
            className="rounded-sm bg-fail px-2 py-0.5 font-semibold uppercase tracking-[0.1em] text-bg"
            data-testid="timeline-floor-callout"
          >
            ▼ below floor from week {floor.firstBelow}
          </span>
        ) : floor ? (
          <span className="uppercase tracking-[0.1em] text-viable" data-testid="timeline-floor-callout">
            ▲ stays above the floor
          </span>
        ) : null}
      </div>

      <div ref={wrapRef} className={`relative w-full transition-opacity duration-300 ${stale ? "opacity-60" : ""}`} style={{ height: H }}>
        {width > 0 && scale ? (
          <svg
            width={width}
            height={H}
            role="img"
            aria-label={`Weekly cash C_t over ${T} weeks. Exact values in the table below.`}
            tabIndex={0}
            onPointerMove={onMove}
            onPointerLeave={() => setHover(null)}
            onKeyDown={onKey}
            onBlur={() => setHover(null)}
            className="block touch-pan-y outline-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent)]"
            data-testid="cash-timeline"
          >
            {/* Weeks below the floor (API weeks_below_floor), as week-wide bands. */}
            {weeks.map((w, i) =>
              below.has(w) ? (
                <rect
                  key={`b${w}`}
                  x={Math.max(pad.l, x(i) - bandW / 2)}
                  width={Math.min(x(i) + bandW / 2, pad.l + innerW) - Math.max(pad.l, x(i) - bandW / 2)}
                  y={pad.t}
                  height={innerH}
                  fill="color-mix(in srgb, var(--fail) 13%, transparent)"
                  data-testid="below-floor-band"
                />
              ) : null,
            )}
            {scale.ticks.map((v) => (
              <g key={v}>
                <line x1={pad.l} x2={pad.l + innerW} y1={y(v)} y2={y(v)} stroke="var(--border)" strokeWidth="1" />
                <text x={pad.l - 8} y={y(v) + 3.5} textAnchor="end" className="num" fontSize="10" fill="var(--muted)">
                  {TICK.format(v)}
                </text>
              </g>
            ))}
            {weeks.map((w, i) =>
              w === 1 || w % (width < 640 ? 5 : 2) === 0 ? (
                <text key={`x${w}`} x={x(i)} y={H - 8} textAnchor="middle" className="num" fontSize="10" fill="var(--muted)">
                  {w === 1 ? "wk 1" : w}
                </text>
              ) : null,
            )}
            {floor ? (
              <g>
                <line
                  x1={pad.l}
                  x2={pad.l + innerW}
                  y1={y(floor.floor)}
                  y2={y(floor.floor)}
                  stroke={breached ? "var(--fail)" : "var(--muted)"}
                  strokeWidth={breached ? 2 : 1.5}
                  strokeDasharray="2 3"
                  data-testid="timeline-floor-line"
                  data-breached={breached ? "true" : "false"}
                />
              </g>
            ) : null}
            {shown.map((s) => (
              <path
                key={`${s.id}-${drawKey}`}
                d={pathOf(s.values)}
                fill="none"
                stroke={STYLE[s.id].stroke}
                strokeWidth={STYLE[s.id].width}
                strokeDasharray={reduce ? STYLE[s.id].dash : undefined}
                strokeLinejoin="round"
                strokeLinecap="round"
                pathLength={reduce || STYLE[s.id].dash ? undefined : 1}
                className={reduce || STYLE[s.id].dash ? undefined : "fx-draw"}
                style={
                  s.id === "plan"
                    ? { filter: "drop-shadow(0 0 4px color-mix(in srgb, var(--viable) 55%, transparent))" }
                    : undefined
                }
                data-series={s.id}
              />
            ))}
            {endLabels.map((l) => (
              <text key={l.id} x={pad.l + innerW + 8} y={l.y + 3.5} fontSize="10.5" fill={l.fill} className="font-mono">
                {l.label}
              </text>
            ))}
            {hover !== null ? (
              <g pointerEvents="none">
                <line x1={x(hover)} x2={x(hover)} y1={pad.t} y2={pad.t + innerH} stroke="var(--text-2)" strokeWidth="1" opacity="0.5" />
                {shown.map((s) => (
                  <circle
                    key={s.id}
                    cx={x(hover)}
                    cy={y(s.values[hover] ?? 0)}
                    r="4.5"
                    fill={STYLE[s.id].stroke}
                    stroke="var(--bg-elevated)"
                    strokeWidth="2"
                  />
                ))}
              </g>
            ) : null}
          </svg>
        ) : (
          <div className="flex h-full items-center justify-center font-mono text-xs uppercase tracking-[0.12em] text-muted">
            Cash path NOT AVAILABLE until POST /api/simulate answers
          </div>
        )}
        {hover !== null && scale ? (
          <div
            className="pointer-events-none absolute top-2 z-10 min-w-44 rounded-md border border-line-strong bg-elevated/95 px-3 py-2 font-mono text-[11px] shadow-[var(--shadow-panel)] backdrop-blur-[12px]"
            style={x(hover) > width / 2 ? { right: width - x(hover) + 12 } : { left: x(hover) + 12 }}
            role="status"
          >
            <p className="mb-1 uppercase tracking-[0.12em] text-muted">
              week {weeks[hover]}
              {below.has(weeks[hover] ?? -1) ? <span className="text-fail"> · below floor</span> : null}
            </p>
            {shown.map((s) => (
              <p key={s.id} className="flex justify-between gap-4">
                <span className="text-text-2">{s.label}</span>
                <span className="num text-text">{usd(s.values[hover] ?? 0)}</span>
              </p>
            ))}
          </div>
        ) : null}
      </div>

      <p className="font-mono text-[10px] leading-snug text-muted">
        {floor
          ? floor.weeksBelow.length
            ? `Shaded: weeks ${weekRanges(floor.weeksBelow)} below the floor for ${floor.of} (API weeks_below_floor).`
            : `No week below the floor for ${floor.of} (API weeks_below_floor is empty).`
          : "Floor NOT AVAILABLE: this API build does not report C_min."}{" "}
        Hover or use ← → for exact weekly values.
      </p>

      <table className="sr-only">
        <caption>Weekly cash C_t from the API</caption>
        <thead>
          <tr>
            <th scope="col">Week</th>
            {shown.map((s) => (
              <th key={s.id} scope="col">
                {s.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {weeks.map((w, i) => (
            <tr key={w}>
              <th scope="row">{w}</th>
              {shown.map((s) => (
                <td key={s.id}>{usd(s.values[i] ?? 0)}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
