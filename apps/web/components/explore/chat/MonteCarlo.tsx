"use client";

import { useId, useState, type ReactNode } from "react";
import type { ChatToolCall } from "@/lib/chat";
import {
  INTERNAL_DATA_TOOL,
  MC_CASH_TOOL,
  MC_DECISION_TOOL,
  cash,
  cell,
  ciLabel,
  count,
  groupAssumptions,
  metricValue,
  monteCarloCalls,
  paramsLabel,
  pct,
  readCash,
  readDecision,
  readInternalData,
  shortSha,
  tornadoRows,
  type McAssumption,
  type McCash,
  type McCashSide,
  type McDecision,
  type McOption,
  type McPlan,
  type McRun,
} from "@/lib/montecarlo";
import { ProvenanceBadge } from "../../ProvenanceBadge";
import { WireBadge } from "./ChatBadges";
import "./montecarlo.css";

/**
 * Monte Carlo panels in a chat reply (#210). The engine (Python, on the server) ran the paths; these panels draw its
 * response as served: a headline probability, per-option histograms on the shared bin edges, pairwise win
 * probabilities, a tornado of driver swings, the assumptions with their sources, and the run's seed / hash. The cash
 * panel draws the P5-P95 fan over the weeks against the floor. Nothing is recomputed; a missing field reads
 * NOT AVAILABLE. Motion only reveals the final drawing and is off under prefers-reduced-motion.
 */

const NA = "NOT AVAILABLE";
const na = (s: string | null | undefined): string => s ?? NA;

/** Option colours by served order. Text labels always accompany colour. */
const OPTION_COLORS = ["var(--accent)", "var(--viable)", "var(--info)", "var(--risk)", "var(--fail)"];
const colorAt = (i: number) => OPTION_COLORS[i % OPTION_COLORS.length];

function Kicker({ children }: { children: ReactNode }) {
  return <p className="kicker !text-text-2">{children}</p>;
}

function NotAvailable({ what }: { what: string }) {
  return (
    <p className="font-mono text-[11px] uppercase tracking-[0.1em] text-muted" data-testid="mc-not-available">
      {what} {NA}
    </p>
  );
}

// ---- "How these numbers were made" ---------------------------------------------------------------------------------

function CopyHash({ hash }: { hash: string }) {
  const [state, setState] = useState<"idle" | "copied" | "failed">("idle");
  return (
    <button
      type="button"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(hash);
          setState("copied");
        } catch {
          setState("failed");
        }
      }}
      className="rounded-sm border border-line-strong px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-[0.1em] text-text-2 hover:bg-hover hover:text-text"
      title={`Copy the full SHA-256: ${hash}`}
      data-testid="mc-copy-sha"
    >
      {state === "copied" ? "copied" : state === "failed" ? "copy failed" : "copy"}
    </button>
  );
}

function HowMade({ run, tool }: { run: McRun; tool: string }) {
  const items: [string, ReactNode, string][] = [
    ["paths", na(count(run.nPaths)), "mc-n-paths"],
    ["seed", run.seed === null ? NA : String(run.seed), "mc-seed"],
    [
      "input sha256",
      run.inputSha256 ? (
        <span className="inline-flex items-center gap-1.5">
          <span title={run.inputSha256}>{shortSha(run.inputSha256)}…</span>
          <CopyHash hash={run.inputSha256} />
        </span>
      ) : (
        NA
      ),
      "mc-sha",
    ],
    ["runtime", run.runtimeMs === null ? NA : `${run.runtimeMs.toLocaleString("en-US", { maximumFractionDigits: 1 })} ms`, "mc-runtime"],
  ];
  return (
    <div className="flex min-w-0 flex-col gap-2 rounded-md border border-viable/40 bg-[color-mix(in_srgb,var(--viable)_5%,transparent)] p-3" data-testid="mc-how-made">
      <p className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <span className="kicker !text-viable">How these numbers were made</span>
        <span className="font-mono text-[10px] text-muted">tool {tool}</span>
      </p>
      <dl className="grid grid-cols-2 gap-x-6 gap-y-2 @xl:grid-cols-[auto_auto_1fr_auto]">
        {items.map(([k, v, id]) => (
          <div key={k} className={`min-w-0 ${id === "mc-sha" ? "col-span-2 @xl:col-span-1" : ""}`}>
            <dt className="font-mono text-[10px] uppercase tracking-[0.12em] text-muted">{k}</dt>
            <dd className="num mt-0.5 whitespace-nowrap text-[14px] text-text" data-testid={id}>
              {v}
            </dd>
          </div>
        ))}
      </dl>
      <p className="text-[13px] font-medium text-text" data-testid="mc-computed-by">
        Computed by FAULTLINE in Python, not by the language model.{" "}
        <span className="font-normal text-text-2">Same seed and inputs give the same paths; the model only chose the inputs and wrote the words.</span>
      </p>
    </div>
  );
}

// ---- Assumptions ---------------------------------------------------------------------------------------------------

function Assumptions({ rows, optionLabel }: { rows: McAssumption[]; optionLabel?: (id: string) => string }) {
  return (
    <div className="flex min-w-0 flex-col gap-2" data-testid="mc-assumptions">
      <p className="flex flex-wrap items-center gap-2">
        <Kicker>Assumptions · drivers sampled each path</Kicker>
        <ProvenanceBadge kind="ILLUSTRATIVE" />
      </p>
      {rows.length === 0 ? (
        <NotAvailable what="Assumptions" />
      ) : (
        <div className="relative min-w-0 overflow-x-auto rounded-md border border-line">
          <table className="w-full min-w-[36rem] border-collapse text-left text-[12.5px]">
            <thead className="font-mono text-[10px] uppercase tracking-[0.12em] text-muted">
              <tr className="border-b border-line">
                <th className="px-3 py-2 font-normal">Driver</th>
                <th className="px-3 py-2 font-normal">Distribution</th>
                <th className="px-3 py-2 font-normal">Params</th>
                <th className="px-3 py-2 font-normal">P</th>
                <th className="px-3 py-2 font-normal">Source</th>
              </tr>
            </thead>
            {(optionLabel ? groupAssumptions(rows) : [{ optionId: null, rows }]).map((g, gi) => (
            <tbody key={gi} data-testid="mc-assumption-group" data-option={g.optionId ?? ""}>
              {optionLabel ? (
                <tr className="border-b border-line/60 bg-hover/40">
                  <th colSpan={5} className="px-3 py-1.5 text-left font-mono text-[10.5px] font-normal uppercase tracking-[0.12em] text-text-2">
                    {g.optionId ? optionLabel(g.optionId) : "All options"}
                  </th>
                </tr>
              ) : null}
              {g.rows.map((a, i) => (
                <tr key={i} className="border-b border-line/60 last:border-0" data-testid="mc-assumption">
                  <td className="px-3 py-2 align-top text-text">
                    {na(a.name)}
                    {a.kind ? <span className="ml-1.5 font-mono text-[10px] text-muted">{a.kind}</span> : null}
                    {a.provenance ? <span className="ml-1.5 align-middle"><WireBadge value={a.provenance} /></span> : null}
                  </td>
                  <td className="px-3 py-2 align-top font-mono text-text-2">{na(a.distribution)}</td>
                  <td className="px-3 py-2 align-top font-mono text-[11.5px] text-text-2 [overflow-wrap:anywhere]">{na(paramsLabel(a.params))}</td>
                  <td className="num px-3 py-2 align-top text-text-2">{a.probability === null ? "—" : na(pct(a.probability))}</td>
                  <td className="px-3 py-2 align-top">
                    {a.source?.url ? (
                      <a
                        href={a.source.url.href}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="break-words text-text underline decoration-line-strong underline-offset-2 [overflow-wrap:anywhere] hover:text-link-hover"
                        data-testid="mc-source-link"
                      >
                        {a.source.title ?? a.source.url.hostname}
                        <span className="sr-only"> (opens in a new tab)</span>
                      </a>
                    ) : (
                      <span className="font-mono text-[10.5px] uppercase tracking-[0.1em] text-risk" data-testid="mc-model-estimated">
                        model-estimated
                      </span>
                    )}
                    {a.source?.note ? <p className="mt-0.5 text-[11px] text-muted">{a.source.note}</p> : null}
                  </td>
                </tr>
              ))}
            </tbody>
            ))}
          </table>
        </div>
      )}
    </div>
  );
}

// ---- Decision ------------------------------------------------------------------------------------------------------

/** Percent position of `v` on [lo, hi], clamped; null when either is missing. Pixel placement only. */
function pos(v: number | null, lo: number, hi: number): number | null {
  if (v === null || hi <= lo) return null;
  return Math.min(100, Math.max(0, ((v - lo) / (hi - lo)) * 100));
}

function Histograms({ d, reduce }: { d: McDecision; reduce: boolean }) {
  const edges = d.binEdges;
  if (!edges || edges.length < 2) return <NotAvailable what="Shared histogram bins" />;
  const lo = edges[0]!;
  const hi = edges[edges.length - 1]!;
  const max = Math.max(1, ...d.options.flatMap((o) => o.counts ?? []));
  const unit = d.metric.unit;
  const zero = pos(0, lo, hi);
  const ticks = [lo, edges[Math.floor((edges.length - 1) / 2)]!, hi];
  return (
    <div className="flex min-w-0 flex-col gap-1" data-testid="mc-histograms">
      <Kicker>
        Distribution of {d.metric.name ?? "the outcome"} across paths{d.metric.higherIsBetter === null ? "" : d.metric.higherIsBetter ? " · higher is better" : " · lower is better"}
      </Kicker>
      <div className="flex min-w-0 flex-col">
        {d.options.map((o, i) => (
          <Ridge key={o.id} o={o} i={i} edges={edges} max={max} lo={lo} hi={hi} zero={zero} unit={unit} reduce={reduce} best={d.best?.id === o.id} />
        ))}
      </div>
      <div className="relative ml-0 h-5 @xl:ml-[9.75rem]" aria-hidden="true">
        {ticks.map((t, k) => (
          <span
            key={k}
            className={`num absolute top-0 text-[10.5px] text-muted ${k === 0 ? "" : k === 2 ? "-translate-x-full" : "-translate-x-1/2"}`}
            style={{ left: `${pos(t, lo, hi)}%` }}
          >
            {metricValue(t, unit)}
          </span>
        ))}
      </div>
    </div>
  );
}

function Ridge({
  o,
  i,
  edges,
  max,
  lo,
  hi,
  zero,
  unit,
  reduce,
  best,
}: {
  o: McOption;
  i: number;
  edges: number[];
  max: number;
  lo: number;
  hi: number;
  zero: number | null;
  unit: string | null;
  reduce: boolean;
  best: boolean;
}) {
  const color = colorAt(i);
  const gid = `mc-g-${useId().replace(/[^a-zA-Z0-9_-]/g, "")}`;
  const H = 100;
  const markers: [string, number | null][] = [
    ["P5", o.p5],
    ["P50", o.p50],
    ["P95", o.p95],
  ];
  return (
    <div className="flex min-w-0 flex-col gap-1 border-t border-line/60 py-2 @xl:flex-row @xl:items-end @xl:gap-3" data-testid="mc-ridge" data-option={o.id}>
      <div className="flex min-w-0 shrink-0 flex-row flex-wrap items-baseline gap-x-2 @xl:w-[9rem] @xl:flex-col @xl:items-start @xl:gap-0.5">
        <span className="flex items-center gap-1.5 text-[14px] font-medium text-text">
          <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: color }} aria-hidden="true" />
          {o.label ?? o.id}
        </span>
        <span className="num text-[11px] text-text-2">
          P50 <span className="text-text">{na(metricValue(o.p50, unit))}</span>
        </span>
        <span className="num text-[10.5px] text-muted">P(below 0) {na(pct(o.probBelowZero))}</span>
      </div>
      <div className="relative h-[4.5rem] w-full min-w-0 shrink-0 @xl:h-[5.5rem] @xl:w-auto @xl:flex-1">
        {o.counts ? (
          <svg
            viewBox={`0 0 1000 ${H}`}
            preserveAspectRatio="none"
            className="absolute inset-0 h-full w-full"
            role="img"
            aria-label={`${o.label ?? o.id}: histogram of ${o.counts.length} bins`}
          >
            <defs>
              <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={color} stopOpacity={best ? 0.95 : 0.75} />
                <stop offset="100%" stopColor={color} stopOpacity={0.15} />
              </linearGradient>
            </defs>
            <g className={reduce ? "" : "mc-grow"} style={reduce ? undefined : { animationDelay: `${i * 140}ms` }}>
              {o.counts.map((c, k) => {
                const x0 = ((edges[k]! - lo) / (hi - lo)) * 1000;
                const x1 = ((edges[k + 1]! - lo) / (hi - lo)) * 1000;
                const h = (c / max) * H;
                return <rect key={k} x={x0 + 0.6} width={Math.max(0.5, x1 - x0 - 1.2)} y={H - h} height={h} fill={`url(#${gid})`} data-count={c} />;
              })}
            </g>
            <line x1="0" x2="1000" y1={H} y2={H} stroke="var(--edge)" strokeWidth="1" vectorEffect="non-scaling-stroke" />
            {zero !== null && zero > 0 && zero < 100 ? (
              <line x1={zero * 10} x2={zero * 10} y1="0" y2={H} stroke="var(--fail)" strokeDasharray="3 3" strokeWidth="1" vectorEffect="non-scaling-stroke" />
            ) : null}
            {markers.map(([name, v]) => {
              const p = pos(v, lo, hi);
              return p === null ? null : (
                <line
                  key={name}
                  x1={p * 10}
                  x2={p * 10}
                  y1="0"
                  y2={H}
                  stroke={name === "P50" ? "var(--text)" : "var(--text-2)"}
                  strokeWidth={name === "P50" ? 2 : 1}
                  strokeDasharray={name === "P50" ? undefined : "2 3"}
                  vectorEffect="non-scaling-stroke"
                />
              );
            })}
          </svg>
        ) : (
          <div className="flex h-full items-center">
            <NotAvailable what="Histogram" />
          </div>
        )}
        {markers.map(([name, v]) => {
          const p = pos(v, lo, hi);
          return p === null ? null : (
            <span
              key={name}
              className={`num pointer-events-none absolute -top-1 -translate-x-1/2 rounded-sm px-1 text-[9.5px] uppercase tracking-[0.08em] ${name === "P50" ? "bg-bg/80 text-text" : "text-muted"}`}
              style={{ left: `${p}%` }}
              title={`${name} ${metricValue(v, unit, true)}`}
            >
              {name}
            </span>
          );
        })}
      </div>
    </div>
  );
}

function Pairwise({ d }: { d: McDecision }) {
  const label = (id: string) => d.options.find((o) => o.id === id)?.label ?? id;
  const colorOf = (id: string) => colorAt(Math.max(0, d.options.findIndex((o) => o.id === id)));
  if (d.pairwise.length === 0) return <NotAvailable what="Pairwise probabilities" />;
  return (
    <div className="flex min-w-0 flex-col gap-3" data-testid="mc-pairwise">
      <Kicker>Head to head · share of paths where one beats the other</Kicker>
      {d.pairwise.map((p, i) => {
        const w = p.probABetter === null || p.probABetter < 0 || p.probABetter > 1 ? null : p.probABetter * 100;
        return (
          <div key={i} className="flex min-w-0 flex-col gap-1.5" data-testid="mc-pair">
            <p className="flex min-w-0 flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5 text-[13px]">
              <span className="text-text">
                P({label(p.a)} better than {label(p.b)}){" "}
                <span className="num text-[15px] font-medium text-text" data-testid="mc-pair-prob">
                  {na(pct(p.probABetter))}
                </span>
              </span>
              <span className="num text-[11px] text-muted">{na(ciLabel(p.ci95))}</span>
            </p>
            <div className="relative h-3 overflow-hidden rounded-full border border-line" style={{ background: `color-mix(in srgb, ${colorOf(p.b)} 28%, transparent)` }}>
              {w !== null ? <div className="mc-fill absolute inset-y-0 left-0 rounded-full" style={{ width: `${w}%`, background: colorOf(p.a) }} /> : null}
              {p.ci95 && w !== null ? (
                <div
                  className="absolute inset-y-0 border-x-2 border-text/80"
                  style={{ left: `${p.ci95[0] * 100}%`, width: `${Math.max(0.4, (p.ci95[1] - p.ci95[0]) * 100)}%` }}
                  title={ciLabel(p.ci95) ?? undefined}
                  aria-hidden="true"
                />
              ) : null}
              <div className="absolute inset-y-0 left-1/2 w-px bg-text/40" aria-hidden="true" />
            </div>
            <p className="flex justify-between font-mono text-[10px] uppercase tracking-[0.1em] text-muted">
              <span>{label(p.a)}</span>
              <span>{label(p.b)}</span>
            </p>
          </div>
        );
      })}
    </div>
  );
}

function Tornado({ d }: { d: McDecision }) {
  const rows = tornadoRows(d.sensitivity);
  if (rows.length === 0) return <NotAvailable what="Sensitivity" />;
  const unit = d.metric.unit;
  const optionOf = (id: string | null) => d.options.find((o) => o.id === id) ?? null;
  const values = rows.flatMap((r) => [r.lowP50, r.highP50, optionOf(r.optionId)?.p50 ?? null]).filter((v): v is number => v !== null);
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  const multi = new Set(rows.map((r) => r.optionId)).size > 1;
  return (
    <div className="flex min-w-0 flex-col gap-2" data-testid="mc-tornado">
      <Kicker>What moves the answer · P50 at the driver&apos;s low and high values</Kicker>
      <ul className="flex min-w-0 flex-col gap-2">
        {rows.map((r, i) => {
          const base = optionOf(r.optionId)?.p50 ?? null;
          const pl = pos(r.lowP50, lo, hi);
          const ph = pos(r.highP50, lo, hi);
          const pb = pos(base, lo, hi);
          const seg = (a: number | null, b: number | null, color: string, test: string) =>
            a === null || b === null ? null : (
              <div
                className="mc-fill absolute inset-y-1 rounded-sm"
                data-testid={test}
                style={{ left: `${Math.min(a, b)}%`, width: `${Math.max(0.5, Math.abs(b - a))}%`, background: color, transformOrigin: a <= b ? "0 50%" : "100% 50%" }}
              />
            );
          return (
            <li key={i} className="grid min-w-0 grid-cols-1 gap-1 @xl:grid-cols-[11rem_1fr_9rem] @xl:items-center @xl:gap-3" data-testid="mc-tornado-row" data-driver={r.driver ?? ""}>
              <span className="min-w-0 break-words text-[13px] text-text">
                {na(r.driver)}
                {multi && r.optionId ? <span className="ml-1 font-mono text-[10px] text-muted">· {optionOf(r.optionId)?.label ?? r.optionId}</span> : null}
              </span>
              <div className="relative h-7 min-w-0 rounded-sm bg-hover/60">
                {pb !== null ? (
                  <>
                    {seg(pb, pl, "color-mix(in srgb, var(--info) 75%, transparent)", "mc-tornado-low")}
                    {seg(pb, ph, "color-mix(in srgb, var(--risk) 75%, transparent)", "mc-tornado-high")}
                    <div className="absolute inset-y-0 w-0.5 bg-text" style={{ left: `${pb}%` }} aria-hidden="true" />
                  </>
                ) : (
                  seg(pl, ph, "color-mix(in srgb, var(--accent) 70%, transparent)", "mc-tornado-span")
                )}
              </div>
              <span className="num flex justify-between gap-2 text-[11px] text-text-2 @xl:flex-col @xl:items-end @xl:gap-0">
                <span>
                  swing <span className="text-[13px] text-text" data-testid="mc-swing">{na(metricValue(r.swing, unit))}</span>
                </span>
                <span className="text-muted">
                  <span className="text-info">low</span> {na(metricValue(r.lowP50, unit))} · <span className="text-risk">high</span> {na(metricValue(r.highP50, unit))}
                </span>
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

/** Every option's served prob_best as one stacked bar (widths are the served shares; nothing is renormalised). */
function OddsBar({ d }: { d: McDecision }) {
  const complete = d.options.length > 0 && d.options.every((o) => o.probBest !== null && o.probBest >= 0 && o.probBest <= 1);
  if (!complete) return <NotAvailable what="Chance each option is best" />;
  return (
    <div className="flex min-w-0 flex-col gap-1.5" data-testid="mc-odds">
      <p className="font-mono text-[10.5px] uppercase tracking-[0.14em] text-muted">Chance each option is best</p>
      <div className="flex h-3 w-full min-w-0 overflow-hidden rounded-full border border-line bg-bg/40" role="img" aria-label={d.options.map((o) => `${o.label ?? o.id} ${pct(o.probBest)}`).join(", ")} data-testid="mc-odds-bar">
        {d.options.map((o, i) => (
          <span key={o.id} className="h-full" style={{ width: `${o.probBest! * 100}%`, background: colorAt(i) }} data-testid="mc-odds-seg" data-option={o.id} data-share={o.probBest!} />
        ))}
      </div>
      <ul className="flex min-w-0 flex-wrap gap-x-4 gap-y-1">
        {d.options.map((o, i) => (
          <li key={o.id} className="flex min-w-0 items-center gap-1.5 text-[12px] text-text-2" data-testid="mc-odds-legend" data-option={o.id}>
            <span className="inline-block h-2 w-2 rounded-full" style={{ background: colorAt(i) }} aria-hidden="true" />
            <span className="min-w-0 truncate">{o.label ?? o.id}</span>
            <span className="num text-text">{pct(o.probBest)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function OptionStats({ d }: { d: McDecision }) {
  const unit = d.metric.unit;
  return (
    <ul className="grid min-w-0 grid-cols-1 gap-2 @lg:grid-cols-2 @5xl:grid-cols-3" data-testid="mc-option-stats">
      {d.options.map((o, i) => (
        <li key={o.id} className={`flex min-w-0 flex-col gap-2.5 rounded-md border p-3 ${d.best?.id === o.id ? "border-accent/70 bg-accent-soft" : "border-line bg-bg/40"}`} data-testid="mc-option" data-option={o.id}>
          <p className="flex items-center gap-1.5 text-[13px] font-medium text-text">
            <span className="inline-block h-2 w-2 rounded-full" style={{ background: colorAt(i) }} aria-hidden="true" />
            {o.label ?? o.id}
          </p>
          <div className="min-w-0">
            <p className="flex min-w-0 flex-wrap items-baseline gap-x-2">
              <span className="font-mono text-[10.5px] uppercase tracking-[0.1em] text-muted">Best in</span>
              <span className="mc-odds-num text-[1.9rem] font-semibold text-text" data-testid="mc-option-best">{na(pct(o.probBest))}</span>
            </p>
            <p className="num text-[11.5px] text-muted" data-testid="mc-option-best-ci">{ciLabel(o.probBestCi95) ?? `95% CI ${NA}`}</p>
          </div>
          <div className="min-w-0 rounded-sm border border-fail/35 bg-[color-mix(in_srgb,var(--fail)_7%,transparent)] px-2.5 py-2" data-testid="mc-downside">
            <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-fail">Downside</p>
            <dl className="mt-1 grid grid-cols-2 gap-x-3 gap-y-1 font-mono text-[10px] uppercase tracking-[0.08em] text-muted">
              <div className="min-w-0">
                <dt>Chance of loss</dt>
                <dd className="mc-odds-num mt-0.5 text-[15px] normal-case tracking-normal text-fail" data-testid="mc-option-loss">{na(pct(o.probBelowZero))}</dd>
              </div>
              <div className="min-w-0">
                <dt>Worst 5% average</dt>
                <dd className="mc-odds-num mt-0.5 text-[15px] normal-case tracking-normal text-fail" data-testid="mc-option-es5">{na(metricValue(o.expectedShortfall5, unit))}</dd>
              </div>
            </dl>
          </div>
          <dl className="grid grid-cols-3 gap-x-3 gap-y-2 font-mono text-[10px] uppercase tracking-[0.08em] text-muted">
            <div>
              <dt>P5</dt>
              <dd className="num mt-0.5 whitespace-nowrap text-[12.5px] normal-case tracking-normal text-text-2">{na(metricValue(o.p5, unit))}</dd>
            </div>
            <div>
              <dt>P50</dt>
              <dd className="num mt-0.5 whitespace-nowrap text-[15px] normal-case tracking-normal text-text">{na(metricValue(o.p50, unit))}</dd>
            </div>
            <div>
              <dt>P95</dt>
              <dd className="num mt-0.5 whitespace-nowrap text-[12.5px] normal-case tracking-normal text-text-2">{na(metricValue(o.p95, unit))}</dd>
            </div>
            <div>
              <dt>Mean</dt>
              <dd className="num mt-0.5 whitespace-nowrap text-[12px] normal-case tracking-normal text-text-2">{na(metricValue(o.mean, unit))}</dd>
            </div>
            <div>
              <dt>SD</dt>
              <dd className="num mt-0.5 whitespace-nowrap text-[12px] normal-case tracking-normal text-text-2">{na(metricValue(o.sd, unit))}</dd>
            </div>
          </dl>
        </li>
      ))}
    </ul>
  );
}

function PanelHeader({ title, run, extra }: { title: string; run: McRun; extra?: ReactNode }) {
  return (
    <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1.5">
      <span className="kicker !text-accent">{title}</span>
      {run.provenance ? <WireBadge value={run.provenance} /> : <ProvenanceBadge kind="NOT AVAILABLE" />}
      {extra}
      {run.label ? <span className="min-w-0 font-mono text-[10.5px] uppercase tracking-[0.1em] text-muted">{run.label}</span> : null}
    </div>
  );
}

function DecisionPanel({ call, d, reduce }: { call: ChatToolCall; d: McDecision; reduce: boolean }) {
  const bestOption = d.best?.id ? d.options.find((o) => o.id === d.best!.id) : undefined;
  const bestLabel = bestOption?.label ?? d.best?.id ?? null;
  const optionLabel = (id: string) => d.options.find((o) => o.id === id)?.label ?? id;
  return (
    <section className={`mc-panel @container ${reduce ? "" : "mc-rise"} flex min-w-0 flex-col gap-5 rounded-xl border border-accent/40 p-4 md:p-6`} data-testid="mc-decision" aria-label="Monte Carlo decision">
      <PanelHeader title="Monte Carlo · decision" run={d} />
      {d.question ? <p className="display min-w-0 break-words text-[1.35rem] leading-tight text-text md:text-[1.7rem]">{d.question}</p> : null}

      <div className="flex min-w-0 flex-col gap-2" data-testid="mc-headline">
        <p className="font-mono text-[10.5px] uppercase tracking-[0.16em] text-text-2">Most often the best option</p>
        <p className="flex min-w-0 flex-wrap items-baseline gap-x-4 gap-y-2">
          <span className="display text-[clamp(1.9rem,6.5cqi,3.75rem)] leading-none text-text" data-testid="mc-best-label">
            {na(bestLabel)}
          </span>
          <span className="mc-headline-num text-[clamp(3rem,13cqi,7rem)] font-semibold" data-testid="mc-headline-prob">
            {na(pct(d.best?.probBest ?? null))}
          </span>
        </p>
        <p className="text-[15px] text-text-2 md:text-[17px]" data-testid="mc-headline-text">
          {bestLabel ?? NA} · best in {pct(d.best?.probBest ?? null) ?? NA} of {count(d.nPaths) ?? NA} paths
        </p>
        <p className="num text-[12.5px] text-muted" data-testid="mc-headline-ci">
          {ciLabel(d.best?.ci95 ?? null) ?? `95% CI ${NA}`}
        </p>
        <OddsBar d={d} />
      </div>

      {d.options.length ? <OptionStats d={d} /> : <NotAvailable what="Options" />}
      <Histograms d={d} reduce={reduce} />
      <div className="grid min-w-0 grid-cols-1 gap-6 @5xl:grid-cols-2">
        <Pairwise d={d} />
        <Tornado d={d} />
      </div>
      <Assumptions rows={d.assumptions} optionLabel={optionLabel} />
      <HowMade run={d} tool={call.name} />
    </section>
  );
}

// ---- Cash ----------------------------------------------------------------------------------------------------------

type CashView = "no_plan" | "with_plan" | "overlay";

function FanSide({ side, lo, hi, n, color, reduce, testId, delay = 0 }: { side: McCashSide; lo: number; hi: number; n: number; color: string; reduce: boolean; testId: string; delay?: number }) {
  const b = side.bands;
  if (!b) return null;
  const x = (k: number) => (n <= 1 ? 0 : (k / (n - 1)) * 1000);
  const y = (v: number) => 300 - ((v - lo) / (hi - lo)) * 300;
  const area = (top: number[], bot: number[]) =>
    `M${top.map((v, k) => `${x(k)},${y(v)}`).join("L")}L${bot
      .map((v, k) => `${x(k)},${y(v)}`)
      .reverse()
      .join("L")}Z`;
  return (
    <g className={reduce ? "" : "mc-wipe"} style={reduce ? undefined : { animationDelay: `${delay}ms` }} data-testid={testId}>
      <path d={area(b.p95, b.p5)} fill={color} fillOpacity={0.14} />
      <path d={area(b.p75, b.p25)} fill={color} fillOpacity={0.3} />
      <path d={`M${b.p50.map((v, k) => `${x(k)},${y(v)}`).join("L")}`} fill="none" stroke={color} strokeWidth={2.5} vectorEffect="non-scaling-stroke" />
    </g>
  );
}

function BreachTile({ title, a, b, test }: { title: string; a: { p: number | null; ci?: [number, number] | null }; b: { p: number | null; ci?: [number, number] | null } | null; test: string }) {
  return (
    <div className="min-w-0 rounded-md border border-line bg-bg/40 p-3 md:p-4" data-testid={test}>
      <p className="font-mono text-[10px] uppercase tracking-[0.12em] text-muted">{title}</p>
      <p className="mt-1 flex min-w-0 flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="num text-[2.2rem] font-semibold leading-none text-fail md:text-[3rem]" data-testid={`${test}-no-plan`}>
          {na(pct(a.p))}
        </span>
        {b ? (
          <>
            <span className="text-[1.4rem] text-muted" aria-hidden="true">
              →
            </span>
            <span className="num text-[2.2rem] font-semibold leading-none text-viable md:text-[3rem]" data-testid={`${test}-with-plan`}>
              {na(pct(b.p))}
            </span>
            <span className="text-[13px] text-text-2">with the plan</span>
          </>
        ) : null}
      </p>
      {a.ci !== undefined ? (
        <p className="num mt-1 text-[11px] text-muted">
          no plan {ciLabel(a.ci) ?? `95% CI ${NA}`}
          {b && b.ci !== undefined ? ` · with plan ${ciLabel(b.ci) ?? `95% CI ${NA}`}` : ""}
        </p>
      ) : null}
    </div>
  );
}

function HeatStrip({ label, values, test }: { label: string; values: number[] | null; test: string }) {
  return (
    <div className="flex min-w-0 flex-col gap-1" data-testid={test}>
      <p className="font-mono text-[10px] uppercase tracking-[0.12em] text-muted">{label}</p>
      {values ? (
        <div className="flex h-6 min-w-0 gap-px overflow-hidden rounded-sm border border-line">
          {values.map((p, k) => (
            <div
              key={k}
              className="min-w-0 flex-1"
              style={{ background: `color-mix(in srgb, var(--fail) ${Math.round(Math.min(1, Math.max(0, p)) * 100)}%, var(--bg-elevated))` }}
              title={`Week ${k + 1}: ${pct(p) ?? NA} of paths below the floor`}
              data-testid="mc-heat-cell"
            />
          ))}
        </div>
      ) : (
        <NotAvailable what="Per-week breach probability" />
      )}
    </div>
  );
}

function CashPanel({ call, c, reduce }: { call: ChatToolCall; c: McCash; reduce: boolean }) {
  const hasPlan = !!c.withPlan?.bands;
  const [view, setView] = useState<CashView>(hasPlan ? "overlay" : "no_plan");
  const shown: [McCashSide, string, string][] = [];
  if ((view === "no_plan" || view === "overlay") && c.noPlan) shown.push([c.noPlan, "var(--fail)", "mc-fan-no-plan"]);
  if ((view === "with_plan" || view === "overlay") && c.withPlan) shown.push([c.withPlan, "var(--viable)", "mc-fan-with-plan"]);
  const all = shown.flatMap(([s]) => (s.bands ? [...s.bands.p5, ...s.bands.p95] : []));
  if (c.floor !== null) all.push(c.floor);
  const lo0 = all.length ? Math.min(...all) : 0;
  const hi0 = all.length ? Math.max(...all) : 1;
  const pad = (hi0 - lo0) * 0.06 || 1;
  const lo = lo0 - pad;
  const hi = hi0 + pad;
  const n = shown.find(([s]) => s.bands)?.[0].bands?.p50.length ?? c.weeks ?? 0;
  const floorY = c.floor === null ? null : 100 - ((c.floor - lo) / (hi - lo)) * 100;
  const zeroY = lo < 0 && hi > 0 ? 100 - ((0 - lo) / (hi - lo)) * 100 : null;
  const views: [CashView, string, boolean][] = [
    ["no_plan", "No plan", !!c.noPlan?.bands],
    ["with_plan", "With plan", hasPlan],
    ["overlay", "Overlay", hasPlan],
  ];
  return (
    <section className={`mc-panel @container ${reduce ? "" : "mc-rise"} flex min-w-0 flex-col gap-5 rounded-xl border border-fail/40 p-4 md:p-6`} data-testid="mc-cash" aria-label="Monte Carlo cash">
      <PanelHeader
        title="Monte Carlo · cash"
        run={c}
        extra={
          <>
            {c.synthetic === true ? <ProvenanceBadge kind="SYNTHETIC" /> : null}
            <ProvenanceBadge kind="ILLUSTRATIVE" />
          </>
        }
      />
      <div className="grid min-w-0 grid-cols-1 gap-3 @4xl:grid-cols-[1.4fr_1fr]">
        <BreachTile
          title="P(cash breaches the floor at any week)"
          a={{ p: c.noPlan?.probBelowFloorAny ?? null, ci: c.noPlan?.probBelowFloorCi95 ?? null }}
          b={c.withPlan ? { p: c.withPlan.probBelowFloorAny, ci: c.withPlan.probBelowFloorCi95 } : null}
          test="mc-breach"
        />
        <BreachTile
          title="P(cash goes negative at any week)"
          a={{ p: c.noPlan?.probNegativeAny ?? null }}
          b={c.withPlan ? { p: c.withPlan.probNegativeAny } : null}
          test="mc-negative"
        />
      </div>

      <div className="flex min-w-0 flex-col gap-2">
        <div className="flex min-w-0 flex-wrap items-center justify-between gap-2">
          <Kicker>
            Cash over {c.weeks ?? NA} weeks · P5–P95 and P25–P75 bands, P50 line · floor {na(cash(c.floor))}
          </Kicker>
          <div className="flex rounded-full border border-line-strong p-0.5" role="group" aria-label="Plan view">
            {views.map(([v, label, ok]) => (
              <button
                key={v}
                type="button"
                disabled={!ok}
                onClick={() => setView(v)}
                aria-pressed={view === v}
                className={`rounded-full px-3 py-1 font-mono text-[10.5px] uppercase tracking-[0.1em] transition-colors disabled:cursor-not-allowed disabled:opacity-40 ${
                  view === v ? "bg-accent-soft text-text" : "text-text-2 hover:text-text"
                }`}
                data-testid={`mc-view-${v}`}
              >
                {label}
              </button>
            ))}
          </div>
        </div>
        {shown.some(([s]) => s.bands) && n > 1 ? (
          <div className="flex min-w-0 gap-2">
            <div className="relative w-12 shrink-0 md:w-16" aria-hidden="true">
              {/* The highest and lowest served values (bands and floor), at their own heights. */}
              <span className="num absolute right-0 -translate-y-1/2 text-[10.5px] text-muted" style={{ top: `${(pad / (hi - lo)) * 100}%` }}>
                {cash(hi0)}
              </span>
              <span className="num absolute right-0 translate-y-1/2 text-[10.5px] text-muted" style={{ bottom: `${(pad / (hi - lo)) * 100}%` }}>
                {cash(lo0)}
              </span>
            </div>
            <div className="mc-grid-bg relative h-[15rem] min-w-0 flex-1 rounded-md border border-line md:h-[20rem]" data-testid="mc-fan">
              <svg viewBox="0 0 1000 300" preserveAspectRatio="none" className="absolute inset-0 h-full w-full" role="img" aria-label="Cash fan chart by week">
                {shown.map(([s, color, id], k) => (
                  <FanSide key={id} side={s} lo={lo} hi={hi} n={n} color={color} reduce={reduce} testId={id} delay={k * 200} />
                ))}
                {zeroY !== null ? <line x1="0" x2="1000" y1={zeroY * 3} y2={zeroY * 3} stroke="var(--edge)" strokeWidth="1" vectorEffect="non-scaling-stroke" /> : null}
                {floorY !== null ? (
                  <line x1="0" x2="1000" y1={floorY * 3} y2={floorY * 3} stroke="var(--fail)" strokeWidth="1.5" strokeDasharray="6 4" vectorEffect="non-scaling-stroke" data-testid="mc-floor" />
                ) : null}
              </svg>
              {floorY !== null ? (
                <span className="num absolute right-2 -translate-y-full rounded-sm bg-bg/80 px-1 text-[10.5px] text-fail" style={{ top: `${floorY}%` }}>
                  floor {cash(c.floor)}
                </span>
              ) : null}
              <span className="absolute bottom-1 left-2 font-mono text-[10px] text-muted">wk 1</span>
              <span className="absolute bottom-1 right-2 font-mono text-[10px] text-muted">wk {n}</span>
            </div>
          </div>
        ) : (
          <NotAvailable what="Cash bands" />
        )}
        <p className="flex flex-wrap gap-x-4 gap-y-1 font-mono text-[10.5px] text-text-2">
          <span>
            <span className="text-fail">■</span> no plan
          </span>
          {c.withPlan ? (
            <span>
              <span className="text-viable">■</span> with plan
            </span>
          ) : (
            <span className="text-muted">with-plan run NOT AVAILABLE</span>
          )}
          <span>
            <span className="text-fail">- -</span> floor
          </span>
        </p>
      </div>

      <div className="flex min-w-0 flex-col gap-2">
        <Kicker>Share of paths below the floor, week by week</Kicker>
        <HeatStrip label="No plan" values={c.noPlan?.probBelowFloorByWeek ?? null} test="mc-heat-no-plan" />
        {c.withPlan ? <HeatStrip label="With plan" values={c.withPlan.probBelowFloorByWeek} test="mc-heat-with-plan" /> : null}
      </div>

      <dl className="grid min-w-0 grid-cols-1 gap-2 @xl:grid-cols-2">
        {([
          ["Lowest cash, no plan", c.noPlan?.minCash ?? null],
          ...(c.withPlan ? ([["Lowest cash, with plan", c.withPlan.minCash]] as const) : []),
        ] as const).map(([k, m]) => (
          <div key={k} className="min-w-0 rounded-md border border-line bg-bg/40 p-3">
            <dt className="font-mono text-[10px] uppercase tracking-[0.12em] text-muted">{k}</dt>
            <dd className="num mt-1 text-[13px] text-text-2">
              P50 <span className="text-[18px] text-text">{na(cash(m?.p50 ?? null))}</span> · P5 {na(cash(m?.p5 ?? null))} · P95 {na(cash(m?.p95 ?? null))}
            </dd>
          </div>
        ))}
      </dl>


      {c.plan ? <PlanTested plan={c.plan} /> : null}

      <Assumptions rows={c.assumptions} />
      {c.notes.length ? (
        <ul className="flex flex-col gap-0.5 border-l border-line-strong pl-3" data-testid="mc-notes">
          {c.notes.map((n, k) => (
            <li key={k} className="break-words font-mono text-[10.5px] text-muted [overflow-wrap:anywhere]">
              {n}
            </li>
          ))}
        </ul>
      ) : null}
      <HowMade run={c} tool={call.name} />
    </section>
  );
}

// Every ActionKind the optimizer serves (core/optimizer.py). The three yes/no decisions carry no week or amount.
const ACTION_LABEL: Record<string, string> = {
  use_backup_supplier: "Use backup supplier",
  defer_capex: "Defer capex",
  delay_expansion: "Delay expansion",
  purchase_cut: "Cut purchases",
  revolver_draw: "Draw revolver",
  revolver_repay: "Repay revolver",
  payroll_cut: "Cut payroll",
};

function PlanTested({ plan }: { plan: McPlan }) {
  const diag = plan.diagnostic === null || plan.diagnostic === undefined ? null : typeof plan.diagnostic === "string" ? plan.diagnostic : JSON.stringify(plan.diagnostic);
  return (
    <div className="flex min-w-0 flex-col gap-2" data-testid="mc-plan">
      <p className="flex min-w-0 flex-wrap items-baseline gap-x-3 gap-y-1">
        <Kicker>The plan tested · one optimizer solve on the central shock</Kicker>
        <span className={`font-mono text-[11px] uppercase tracking-[0.1em] ${plan.status === "OPTIMAL" ? "text-viable" : "text-fail"}`} data-testid="mc-plan-status">
          {na(plan.status)}
        </span>
        <span className="num text-[11px] text-text-2">
          central min cash <span className="text-text">{na(cash(plan.centralMinCash))}</span>
        </span>
      </p>
      {diag ? <p className="break-words font-mono text-[11px] text-fail [overflow-wrap:anywhere]">{diag}</p> : null}
      {plan.actions === null ? (
        <NotAvailable what="Plan actions" />
      ) : plan.actions.length === 0 ? (
        <p className="font-mono text-[11px] text-muted">The plan takes no actions.</p>
      ) : (
        <ul className="flex min-w-0 flex-wrap gap-1.5">
          {plan.actions.map((a, k) => (
            <li key={k} className="rounded-sm border border-line bg-bg/40 px-2 py-1 font-mono text-[11px] text-text-2" data-testid="mc-plan-action">
              {/* Week and amount are shown only when served: a yes/no decision has neither, so nothing reads NOT AVAILABLE. */}
              {a.week !== null ? <span className="text-muted">wk {a.week} </span> : null}
              {a.action ? (ACTION_LABEL[a.action] ?? a.action) : NA}
              {a.amount !== null ? (
                <span className="num text-text"> {cash(a.amount, true)}</span>
              ) : a.share !== null && pct(a.share) ? (
                <span className="num text-text"> {pct(a.share)}</span>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// ---- Internal data -------------------------------------------------------------------------------------------------

function InternalDataCard({ call }: { call: ChatToolCall }) {
  const t = readInternalData(call);
  const prov = t?.provenance ?? call.provenance;
  const [all, setAll] = useState(false);
  const LIMIT = 10;
  return (
    <section className="flex min-w-0 flex-col gap-2 rounded-lg border border-line bg-bg/40 p-3 md:p-4" data-testid="mc-internal-data" aria-label="Internal data">
      <p className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
        <span className="kicker !text-text-2">Internal data{t?.table ? ` · ${t.table}` : ""}</span>
        {prov.startsWith("SYNTHETIC") ? <ProvenanceBadge kind="SYNTHETIC" /> : null}
        <WireBadge value={prov} />
      </p>
      {!t ? (
        <NotAvailable what="Rows" />
      ) : (
        <>
          {t.aggregate ? (
            <dl className="flex min-w-0 flex-wrap gap-x-5 gap-y-1" data-testid="mc-internal-aggregate">
              {Object.entries(t.aggregate).map(([k, v]) => (
                <div key={k} className="min-w-0">
                  <dt className="font-mono text-[10px] uppercase tracking-[0.12em] text-muted">{k}</dt>
                  <dd className="num text-[16px] text-text">{cell(v) ?? NA}</dd>
                </div>
              ))}
            </dl>
          ) : null}
          {t.rows.length === 0 ? (
            <NotAvailable what="Rows" />
          ) : (
            <div className="relative min-w-0 overflow-x-auto rounded-md border border-line">
              <table className="w-full border-collapse text-left text-[12px]">
                <thead className="font-mono text-[10px] uppercase tracking-[0.1em] text-muted">
                  <tr className="border-b border-line">
                    {t.columns.map((c) => (
                      <th key={c} className="whitespace-nowrap px-2.5 py-1.5 font-normal">
                        {c}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {(all ? t.rows : t.rows.slice(0, LIMIT)).map((r, i) => (
                    <tr key={i} className="border-b border-line/50 last:border-0" data-testid="mc-internal-row">
                      {t.columns.map((c) => (
                        <td key={c} className={`whitespace-nowrap px-2.5 py-1.5 ${typeof r[c] === "number" ? "num text-right text-text" : "text-text-2"}`}>
                          {cell(r[c]) ?? <span className="font-mono text-[10px] text-muted">{NA}</span>}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {t.rows.length > LIMIT ? (
            <button type="button" onClick={() => setAll((v) => !v)} className="self-start font-mono text-[10.5px] uppercase tracking-[0.1em] text-text-2 hover:text-text">
              {all ? "Show fewer rows" : `Show all ${t.rows.length} rows`}
            </button>
          ) : null}
          <p className="font-mono text-[10px] text-muted">Mock internal data for the demo business, not a real company&apos;s books.</p>
        </>
      )}
    </section>
  );
}

// ---- Entry ---------------------------------------------------------------------------------------------------------

function Unreadable({ call }: { call: ChatToolCall }) {
  return (
    <section className="flex min-w-0 flex-col gap-1 rounded-lg border border-line p-3" data-testid="mc-unreadable">
      <p className="flex flex-wrap items-center gap-2">
        <span className="kicker !text-text-2">{call.name}</span>
        <ProvenanceBadge kind="NOT AVAILABLE" />
      </p>
      <p className="font-mono text-[11px] text-muted">The engine response did not match the Monte Carlo shape, so no chart is drawn. The raw result is in the steps below.</p>
    </section>
  );
}

/** The Monte Carlo and internal-data results of one reply, in the order the calls ran. Nothing when there are none. */
export function MonteCarloCards({ calls, reduce }: { calls: readonly ChatToolCall[]; reduce: boolean }) {
  const picked = monteCarloCalls(calls);
  if (picked.length === 0) return null;
  return (
    <div className="flex min-w-0 flex-col gap-4" data-testid="chat-monte-carlo">
      {picked.map((c, i) => {
        if (c.name === MC_DECISION_TOOL) {
          const d = readDecision(c);
          return d ? <DecisionPanel key={i} call={c} d={d} reduce={reduce} /> : <Unreadable key={i} call={c} />;
        }
        if (c.name === MC_CASH_TOOL) {
          const cs = readCash(c);
          return cs ? <CashPanel key={i} call={c} c={cs} reduce={reduce} /> : <Unreadable key={i} call={c} />;
        }
        if (c.name === INTERNAL_DATA_TOOL) return <InternalDataCard key={i} call={c} />;
        return null;
      })}
    </div>
  );
}
