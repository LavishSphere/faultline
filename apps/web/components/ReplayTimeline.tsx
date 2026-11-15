"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { SECTION_LABEL, sectionSteps, stepFromPath, stepHref } from "@/lib/steps";

/**
 * Top presenter navigation in two sections. First, highlighted: LIVE EXPLORE ("Ask the engine", the home screen).
 * Second: the Blind Replay ("the honesty proof"), five screens under THEN / DECISION / REVEAL with a progress line.
 * This is navigation, not data: it carries no dates or values.
 */
export function ReplayTimeline() {
  const pathname = usePathname();
  const current = stepFromPath(pathname) ?? null;
  const live = sectionSteps("live");
  const replay = sectionSteps("replay");
  const replayPos = current?.section === "replay" ? replay.findIndex((s) => s.slug === current.slug) : -1;
  const progress = replayPos >= 0 && replay.length > 1 ? (replayPos / (replay.length - 1)) * 100 : 0;
  const columns = { gridTemplateColumns: `repeat(${replay.length}, minmax(0, 1fr))` };
  const phases = [...new Set(replay.map((s) => s.phase))];

  return (
    <nav aria-label="Presenter timeline" className="border-b border-line">
      <div className="mx-auto flex w-full max-w-[1760px] flex-col gap-3 px-4 pb-3 pt-3 md:flex-row md:items-stretch md:gap-8 md:px-10">
        <section aria-labelledby="nav-live" className="flex shrink-0 flex-col gap-2 md:w-[260px]">
          {/* Visually hidden on phones (the chat heading below repeats it) to keep the sticky header short. */}
          <p
            id="nav-live"
            className="sr-only font-mono text-[10px] uppercase tracking-[0.18em] text-muted md:not-sr-only md:text-[11px]"
          >
            {SECTION_LABEL.live}
          </p>
          {live.map((step) => {
            const active = current?.slug === step.slug;
            return (
              <Link
                key={step.slug}
                href={stepHref(step)}
                aria-current={active ? "step" : undefined}
                data-testid="nav-live-explore"
                className={`group flex items-center justify-between gap-3 rounded-md border px-3 py-2 transition-colors ${
                  active
                    ? "border-accent bg-accent-soft text-text"
                    : "border-line-strong text-text-2 hover:border-accent hover:bg-accent-soft hover:text-text"
                }`}
              >
                <span className="flex min-w-0 items-baseline gap-2">
                  <span className="num font-mono text-[10px] text-muted">{String(step.index + 1).padStart(2, "0")}</span>
                  <span className="truncate text-sm font-medium">{step.label}</span>
                </span>
                <span className="font-mono text-[10px] uppercase tracking-[0.16em] text-accent">{step.phase}</span>
              </Link>
            );
          })}
        </section>

        <span className="hidden w-px bg-line md:block" aria-hidden="true" />

        <section aria-labelledby="nav-replay" className="min-w-0 flex-1">
          <p
            id="nav-replay"
            className="pb-2 font-mono text-[10px] uppercase tracking-[0.18em] text-muted md:text-[11px]"
          >
            {SECTION_LABEL.replay}
          </p>
          <div className="grid font-mono text-[10px] uppercase tracking-[0.18em] md:text-[11px]" style={columns}>
            {phases.map((phase) => {
              const span = replay.filter((s) => s.phase === phase).length;
              const active = current?.phase === phase;
              return (
                <div
                  key={phase}
                  style={{ gridColumn: `span ${span} / span ${span}` }}
                  className={`pb-2 ${active ? "text-text" : "text-muted"}`}
                >
                  {phase}
                  {active ? <span className="sr-only"> (current phase)</span> : null}
                </div>
              );
            })}
          </div>

          <div className="relative h-px bg-line" aria-hidden="true">
            <div
              className="absolute inset-y-0 left-0 bg-accent transition-[width] duration-500"
              style={{ width: `${progress}%` }}
            />
          </div>

          <ol className="grid" style={columns}>
            {replay.map((step, i) => {
              const active = current?.slug === step.slug;
              const done = replayPos >= 0 && i < replayPos;
              return (
                <li key={step.slug} className="relative">
                  <Link
                    href={stepHref(step)}
                    aria-current={active ? "step" : undefined}
                    className={`group flex flex-col gap-0.5 rounded-sm pr-2 pt-2.5 transition-colors ${
                      active ? "text-text" : done ? "text-text-2 hover:text-text" : "text-muted hover:text-text"
                    }`}
                  >
                    <span
                      aria-hidden="true"
                      className={`absolute -top-[3px] left-0 size-[7px] rounded-full border transition-colors ${
                        active
                          ? "border-accent bg-accent"
                          : done
                            ? "border-accent bg-bg"
                            : "border-line-strong bg-bg group-hover:border-muted"
                      }`}
                    />
                    <span className="num text-[10px] text-muted">{String(step.index + 1).padStart(2, "0")}</span>
                    <span className="text-[12px] font-medium md:text-sm">
                      <span className="md:hidden">{step.short}</span>
                      <span className="hidden md:inline">{step.label}</span>
                    </span>
                  </Link>
                </li>
              );
            })}
          </ol>
        </section>
      </div>
    </nav>
  );
}
