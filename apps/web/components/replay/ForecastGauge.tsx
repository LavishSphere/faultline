"use client";

import { ProvenanceBadge, type ProvenanceInput } from "../ProvenanceBadge";
import { useTween } from "./motion";

const CX = 120;
const CY = 118;
const R = 96;

function point(p: number): [number, number] {
  const theta = Math.PI * (1 - p);
  return [CX + R * Math.cos(theta), CY - R * Math.sin(theta)];
}

function arc(p: number): string {
  const [x, y] = point(Math.min(1, Math.max(0, p)));
  return `M ${CX - R} ${CY} A ${R} ${R} 0 0 1 ${x.toFixed(3)} ${y.toFixed(3)}`;
}

/**
 * The forecast moment (#163): a half-dial that sweeps from 0 to the run's served `p_yes`. The needle's last frame
 * is exactly `p_yes`, and the readout under it (and its screen-reader text) is `p_yes.toFixed(3)`, the same
 * display rule as every other probability on screen. The optional market notch is the served market-implied p.
 * `value === null` draws an empty dial and NOT AVAILABLE.
 */
export function ForecastGauge({
  value,
  runKey,
  provenance,
  label,
  sublabel,
  market,
}: {
  value: number | null;
  /** Changes per run, so a new run sweeps again. */
  runKey: string;
  provenance: readonly ProvenanceInput[];
  label: string;
  sublabel?: string;
  market?: { p: number; label: string } | null;
}) {
  const shown = useTween(value, 0, runKey, 1300, 150);
  const exact = value === null ? null : value.toFixed(3);
  const frame = shown === null ? null : shown === value ? exact : shown.toFixed(3);

  return (
    <div className="flex min-w-0 flex-col gap-2" data-testid="forecast-gauge">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="kicker">{label}</span>
        <span className="flex flex-wrap gap-1.5">
          {value === null ? (
            <ProvenanceBadge kind="NOT AVAILABLE" />
          ) : (
            provenance.map((k, i) => <ProvenanceBadge key={`${k}-${i}`} kind={k} />)
          )}
        </span>
      </div>
      <div className="relative mx-auto w-full max-w-[340px]">
        <svg viewBox="0 0 240 132" className="w-full" aria-hidden="true">
          <defs>
            <linearGradient id="gauge-fill" x1="0" x2="1" y1="0" y2="0">
              <stop offset="0" stopColor="var(--info)" />
              <stop offset="1" stopColor="var(--accent)" />
            </linearGradient>
          </defs>
          <path d={arc(1)} stroke="var(--border)" strokeWidth="12" fill="none" strokeLinecap="round" />
          {[0, 0.25, 0.5, 0.75, 1].map((t) => {
            const [x1, y1] = point(t);
            const [x2, y2] = [CX + (x1 - CX) * 0.8, CY + (y1 - CY) * 0.8];
            return <line key={t} x1={x1} y1={y1} x2={x2} y2={y2} stroke="var(--border-strong)" strokeWidth="1" />;
          })}
          {shown !== null && shown > 0.0005 ? (
            <path d={arc(shown)} stroke="url(#gauge-fill)" strokeWidth="12" fill="none" strokeLinecap="round" />
          ) : null}
          {market ? <MarketNotch p={market.p} /> : null}
          {shown !== null ? <Needle p={shown} /> : null}
          <text x={CX - R} y={CY + 13} textAnchor="middle" className="fill-[var(--muted)] font-mono" fontSize="8">
            0
          </text>
          <text x={CX} y={CY - R - 8} textAnchor="middle" className="fill-[var(--muted)] font-mono" fontSize="8">
            0.5
          </text>
          <text x={CX + R} y={CY + 13} textAnchor="middle" className="fill-[var(--muted)] font-mono" fontSize="8">
            1
          </text>
        </svg>
        <div className="absolute inset-x-0 bottom-0 flex flex-col items-center">
          <p
            className={`num font-medium leading-none tracking-tight ${value === null ? "pb-1 text-lg uppercase tracking-[0.08em] text-muted" : "text-5xl text-text md:text-6xl"}`}
            data-testid="forecast-gauge-value"
          >
            <span aria-hidden="true">{frame ?? "Not available"}</span>
            <span className="sr-only">{exact ?? "Not available"}</span>
          </p>
        </div>
      </div>
      {sublabel ? <p className="text-center text-xs text-muted">{sublabel}</p> : null}
      {market ? (
        <p className="text-center font-mono text-[10px] uppercase tracking-[0.1em] text-muted">
          <span aria-hidden="true" className="mr-1.5 inline-block h-2 w-0.5 bg-risk align-middle" />
          notch: {market.label} {market.p.toFixed(3)}
        </p>
      ) : null}
    </div>
  );
}

function Needle({ p }: { p: number }) {
  const [x, y] = point(Math.min(1, Math.max(0, p)));
  const [ix, iy] = [CX + (x - CX) * 0.62, CY + (y - CY) * 0.62];
  return (
    <g>
      <line x1={ix} y1={iy} x2={x} y2={y} stroke="var(--text)" strokeWidth="2" strokeLinecap="round" />
      <circle cx={x} cy={y} r="5" fill="var(--bg-elevated)" stroke="var(--text)" strokeWidth="2" />
    </g>
  );
}

function MarketNotch({ p }: { p: number }) {
  const [x, y] = point(Math.min(1, Math.max(0, p)));
  const [ox, oy] = [CX + (x - CX) * 1.12, CY + (y - CY) * 1.12];
  const [ix, iy] = [CX + (x - CX) * 0.9, CY + (y - CY) * 0.9];
  return <line x1={ix} y1={iy} x2={ox} y2={oy} stroke="var(--risk)" strokeWidth="2.5" strokeLinecap="round" />;
}
