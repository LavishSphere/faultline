import type { ReactNode } from "react";
import { SERIES_CSS, countTo, progress } from "./motion";
import { fmt4 } from "./ui";

/** Scoped series colors (see SERIES_CSS); React hoists and dedupes this <style> by href. */
export function SeriesStyle() {
  return (
    <style href="fl-series-colors" precedence="default">
      {SERIES_CSS}
    </style>
  );
}

export type SeriesKey = "agent" | "market" | "naive";

export const SERIES_VAR: Record<SeriesKey, string> = {
  agent: "var(--s-agent)",
  market: "var(--s-market)",
  naive: "var(--s-naive)",
};

/** Marker glyph per series, so identity never rests on color alone (agent ●, market ◆, naive ┄). */
export function SeriesMark({ series, size = 10 }: { series: SeriesKey; size?: number }) {
  const c = SERIES_VAR[series];
  return (
    <svg width={size} height={size} viewBox="0 0 10 10" aria-hidden="true" className="shrink-0">
      {series === "agent" ? <circle cx="5" cy="5" r="4" fill={c} /> : null}
      {series === "market" ? <rect x="1.6" y="1.6" width="6.8" height="6.8" transform="rotate(45 5 5)" fill={c} /> : null}
      {series === "naive" ? <line x1="0" y1="5" x2="10" y2="5" stroke={c} strokeWidth="2" strokeDasharray="2 2" /> : null}
    </svg>
  );
}

/**
 * One row of a score race: a bar that grows to the API value on a shared scale while its number counts up. The final
 * frame is exactly `fmt4(value)`, the same formatting as the tables. `value === null` renders NOT AVAILABLE in the
 * row, never a zero-length bar. `max` is display geometry (the axis end), not a result.
 */
export function RaceBar({
  series,
  label,
  sublabel,
  value,
  max,
  elapsed,
  at,
  dur = 650,
  testId,
  missing = "Not available",
}: {
  series: SeriesKey;
  label: ReactNode;
  sublabel?: ReactNode;
  value: number | null;
  max: number;
  elapsed: number;
  at: number;
  dur?: number;
  testId?: string;
  missing?: ReactNode;
}) {
  const shown = value === null ? null : countTo(value, elapsed, at, dur);
  const width = value === null ? 0 : Math.max(0, Math.min(1, value / max)) * progress(elapsed, at, dur) * 100;
  return (
    <div className="grid grid-cols-[minmax(0,6.5rem)_minmax(3rem,1fr)_auto] items-center gap-x-3 gap-y-0.5 sm:grid-cols-[minmax(0,8.5rem)_minmax(3rem,1fr)_auto]">
      <div className="flex min-w-0 items-center gap-2">
        <SeriesMark series={series} />
        <span className="min-w-0">
          <span className="block truncate text-sm font-medium text-text">{label}</span>
          {sublabel ? <span className="block truncate font-mono text-[10px] text-muted">{sublabel}</span> : null}
        </span>
      </div>
      <div className="relative h-2.5 min-w-0 overflow-hidden rounded-full bg-hover" aria-hidden="true">
        {value === null ? (
          <div className="hatch absolute inset-0" />
        ) : (
          <div
            className="absolute inset-y-0 left-0 rounded-full"
            style={{
              width: `${width}%`,
              background: SERIES_VAR[series],
              opacity: series === "naive" ? 0.55 : 1,
            }}
          />
        )}
      </div>
      <span className="min-w-[4.75rem] text-right text-base leading-none text-text sm:min-w-[5.5rem] sm:text-lg">
        {value === null ? (
          <span className="font-mono text-[11px] uppercase tracking-[0.08em] text-muted" data-testid={testId}>
            {missing}
          </span>
        ) : (
          <>
            {/* Before its step starts the row shows a dash, never a stand-in number. */}
            <span aria-hidden="true" className="num" data-testid={testId} title={String(value)}>
              {progress(elapsed, at, dur) === 0 ? <span className="text-muted">—</span> : fmt4(shown ?? value)}
            </span>
            <span className="sr-only">{fmt4(value)}</span>
          </>
        )}
      </span>
    </div>
  );
}

/** Axis ticks under a race: 0 and the scale end, labeled so bar length is never read without a scale. */
export function RaceAxis({ max, caption }: { max: number; caption: ReactNode }) {
  return (
    <div className="grid grid-cols-[minmax(0,6.5rem)_minmax(3rem,1fr)_auto] gap-x-3 sm:grid-cols-[minmax(0,8.5rem)_minmax(3rem,1fr)_auto]">
      <span className="font-mono text-[10px] uppercase tracking-[0.12em] text-muted">{caption}</span>
      <span className="flex justify-between font-mono text-[10px] text-muted">
        <span className="num">0</span>
        <span className="num">{max}</span>
      </span>
      <span className="min-w-[4.75rem] sm:min-w-[5.5rem]" />
    </div>
  );
}
