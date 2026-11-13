"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { PHASES, STEPS, stepFromPath, stepHref } from "@/lib/steps";

/**
 * Top presenter timeline: THEN / DECISION / REVEAL phases over the five screens.
 * This is navigation, not data: it carries no dates or values.
 */
export function ReplayTimeline() {
  const pathname = usePathname();
  const current = stepFromPath(pathname) ?? null;
  const progress = current ? (current.index / (STEPS.length - 1)) * 100 : 0;

  return (
    <nav aria-label="Presenter timeline" className="border-b border-line">
      <div className="mx-auto w-full max-w-[1760px] px-4 pb-3 pt-3 md:px-10">
        <div className="grid grid-cols-5 font-mono text-[10px] uppercase tracking-[0.18em] md:text-[11px]">
          {PHASES.map((phase) => {
            const span = STEPS.filter((s) => s.phase === phase).length;
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

        <ol className="grid grid-cols-5">
          {STEPS.map((step) => {
            const active = current?.slug === step.slug;
            const done = current ? step.index < current.index : false;
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
      </div>
    </nav>
  );
}
