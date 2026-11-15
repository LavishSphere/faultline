"use client";

import { useEffect, useRef, useState, type ReactNode, type Ref } from "react";
import { ProvenanceBadge } from "../ProvenanceBadge";
import { CaseBadges } from "./ReplayParts";
import { Vault } from "./Vault";
import type { EvidenceState } from "./hooks";
import { useReducedMotion, useStagger, useTween } from "./motion";
import m from "./motion.module.css";
import { formatCutoffUtc, type EvidenceItem, type ReplayCasePublic } from "@/lib/replay";

/** Share of the track left of the cutoff ("known"); the rest is the sealed horizon. Layout only. */
const KNOWN = 72;
const SCRUB_MS = 1500;
/** Long enough for the scroll back up to the time machine to finish before the scrub starts. */
const SCRUB_DELAY_MS = 450;

/**
 * A.0 time machine (#163). Choosing a case scrubs a playhead from this browser's clock back to the case's served
 * `as_of`; the date readout's last frame is exactly the served cutoff, and screen readers only ever get that value.
 * Ticks left of the cutoff are the admitted documents from GET /api/cases/{case_id}/evidence, placed by their served
 * `available_at` (layout only). Right of the cutoff is sealed: the API serves no outcome, so nothing is drawn there
 * but the horizon length the case states.
 *
 * Mount with `key={event_id}` so every pick replays the scrub.
 */
export function TimeMachine({ c, evidence }: { c: ReplayCasePublic | null; evidence: EvidenceState }) {
  if (!c) {
    return (
      <Shell title="Time machine" badges={<ProvenanceBadge kind="NOT AVAILABLE" detail="No case loaded" />}>
        <div className="px-5 py-8">
          <p className="kicker">Knowledge cutoff</p>
          <p className="mt-3 font-mono text-2xl font-medium uppercase tracking-[0.06em] text-muted md:text-3xl">
            Not available
          </p>
          <p className="mt-2 text-xs text-muted">Pick a replay case to rewind to its cutoff.</p>
        </div>
      </Shell>
    );
  }
  return <Machine c={c} evidence={evidence} />;
}

function Shell({
  title,
  badges,
  children,
  sectionRef,
}: {
  title: string;
  badges: ReactNode;
  children: ReactNode;
  sectionRef?: Ref<HTMLElement>;
}) {
  return (
    <section
      aria-labelledby="rewind-timeline"
      ref={sectionRef}
      className="relative scroll-mt-44 overflow-hidden rounded-lg border border-line bg-elevated"
      data-testid="time-machine"
    >
      <div className="flex min-h-11 flex-wrap items-center justify-between gap-2 border-b border-line px-5 py-2.5">
        <h2 id="rewind-timeline" className="font-mono text-[11px] uppercase tracking-[0.14em] text-text-2">
          <span className="text-muted">A.0</span> {title}
        </h2>
        {badges}
      </div>
      {children}
    </section>
  );
}

function Machine({ c, evidence }: { c: ReplayCasePublic; evidence: EvidenceState }) {
  const reduce = useReducedMotion();
  const cutoffMs = Date.parse(c.as_of);
  // The scrub starts from this browser's clock at the moment the case was picked (an animation start, not data).
  const [startMs] = useState(() => Date.now());
  const valid = Number.isFinite(cutoffMs);
  const scrubs = valid && startMs > cutoffMs;
  const key = `${c.event_id}|${c.as_of}`;

  const clock = useTween(valid ? cutoffMs : null, scrubs ? startMs : cutoffMs, key, SCRUB_MS, SCRUB_DELAY_MS);
  const head = useTween(KNOWN, scrubs ? 100 : KNOWN, key, SCRUB_MS, SCRUB_DELAY_MS);
  const landed = reduce || !scrubs || clock === cutoffMs;

  const exact = formatCutoffUtc(c.as_of);
  const frame = clock === null ? null : clock === cutoffMs ? exact : formatCutoffUtc(new Date(clock).toISOString());

  const items: EvidenceItem[] = evidence.kind === "done" && evidence.result.ok ? evidence.result.data.items : [];
  const ticks = placeTicks(items, cutoffMs);
  const shownTicks = useStagger(landed ? ticks.length : 0, `${key}|${ticks.length}`, 110, 80);

  // A pick made further down the case list brings the time machine back into view, so the rewind is seen.
  const ref = useRef<HTMLElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const top = el.getBoundingClientRect().top;
    if (top < 0 || top > window.innerHeight * 0.6) el.scrollIntoView({ block: "start", behavior: reduce ? "auto" : "smooth" });
    // Once per pick (the component is keyed by case), not on every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <Shell
      sectionRef={ref}
      title={c.synthetic ? "Time machine · fictional timeline" : "Time machine"}
      badges={<CaseBadges c={c} />}
    >
      <div className="grid grid-cols-1 gap-6 px-5 pb-6 pt-5 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-end lg:gap-10">
        <div className="min-w-0">
          <p className="kicker">{landed ? "Rewound to the knowledge cutoff" : "Rewinding…"}</p>
          <p className="display mt-3 text-3xl leading-tight text-text md:text-4xl">{c.title}</p>
        </div>
        <div className="min-w-0 lg:text-right">
          <p className="kicker">As-of · knowledge cutoff</p>
          <p
            className={`num mt-2 whitespace-nowrap text-[1.6rem] font-medium leading-none tracking-tight sm:text-3xl md:text-5xl ${landed ? "text-text" : "text-text-2"}`}
            data-testid="time-machine-cutoff"
          >
            <span aria-hidden="true">{frame ?? "Not available"}</span>
            <span className="sr-only">{exact ?? "Not available"}</span>
          </p>
          <p className="mt-2 font-mono text-[10px] uppercase tracking-[0.12em] text-muted">
            {scrubs ? "from this browser's clock back to the served as_of" : "served as_of"}
          </p>
        </div>
      </div>

      {/* The track. Everything on it is layout of served dates; the sealed side holds no data at all. */}
      <div className="relative mx-5 mb-9 h-24 sm:h-28" aria-hidden="true">
        <div className="absolute inset-y-0 left-0 rounded-l-md border border-r-0 border-line bg-bg/40" style={{ width: `${KNOWN}%` }} />
        <div
          className={`absolute inset-y-0 right-0 flex items-center justify-center rounded-r-md border border-risk/50 ${m.shutter}`}
          style={{ width: `${100 - KNOWN}%` }}
        >
          <Vault className="size-9 shrink-0 text-risk sm:size-11" locked={landed} />
          <span className="ml-3 hidden font-mono text-[10px] uppercase leading-snug tracking-[0.14em] text-risk md:block">
            Sealed: the outcome is
            <br />
            locked until reveal
          </span>
        </div>
        <div className="absolute left-0 right-0 top-1/2 h-px bg-line-strong" style={{ width: `${KNOWN}%` }} />
        {ticks.slice(0, shownTicks).map((t, i) => (
          <span
            key={t.id}
            className={`absolute top-1/2 flex -translate-x-1/2 -translate-y-1/2 flex-col items-center gap-1 ${m.popIn}`}
            style={{ left: `${t.x}%` }}
          >
            <span className="size-2.5 rounded-full border border-accent bg-accent shadow-[0_0_0_4px_var(--accent-soft)]" />
            <span className="num absolute top-4 text-[10px] text-muted">[{i + 1}]</span>
          </span>
        ))}
        {/* The playhead: scrubs from "now" (right edge) to the cutoff. */}
        <div className="absolute inset-y-[-6px] w-0" style={{ left: `${head ?? KNOWN}%` }}>
          <div className={`absolute inset-y-0 -left-px w-0.5 rounded-full bg-accent ${landed ? m.glow : ""}`} />
          <div className="absolute -left-[5px] -top-1 size-2.5 rotate-45 bg-accent" />
          <span
            className={`absolute -bottom-5 -translate-x-1/2 whitespace-nowrap font-mono text-[9px] uppercase tracking-[0.14em] ${landed ? "text-accent" : "text-muted"}`}
          >
            {landed ? "cutoff" : "rewinding"}
          </span>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4 border-t border-line px-5 py-3 font-mono text-[10px] uppercase tracking-[0.12em] sm:grid-cols-[72fr_28fr]">
        <p className="text-muted">
          <span className="text-text-2">Known by cutoff</span> ·{" "}
          {evidence.kind === "done" && evidence.result.ok
            ? `${items.length} ${items.length === 1 ? "document" : "documents"} admitted by the gate`
            : `${c.evidence_ids.length} evidence ${c.evidence_ids.length === 1 ? "id" : "ids"} on the case record`}
        </p>
        <p className="text-risk">
          Sealed · horizon {c.horizon_days} d after cutoff
        </p>
      </div>
    </Shell>
  );
}

/** x position (percent of the track) per admitted document, by served available_at. Layout only. */
function placeTicks(items: EvidenceItem[], cutoffMs: number): { id: string; x: number }[] {
  const times = items.map((e) => Date.parse(e.available_at));
  const finite = times.filter(Number.isFinite);
  if (!finite.length || !Number.isFinite(cutoffMs)) return [];
  const first = Math.min(...finite);
  const span = cutoffMs - first;
  return items.map((e, i) => {
    const t = times[i]!;
    const share = !Number.isFinite(t) || span <= 0 ? 0.5 : (t - first) / span;
    return { id: e.evidence_id, x: 4 + share * (KNOWN - 10) };
  });
}
