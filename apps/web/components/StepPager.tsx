import Link from "next/link";
import { STEPS, stepHref, type Step } from "@/lib/steps";

/** Bottom bar: previous / next screen with key hints. Mirrors the ← / → shortcuts. */
export function StepPager({ step }: { step: Step }) {
  const prev = STEPS[step.index - 1];
  const next = STEPS[step.index + 1];
  const linkClass =
    "group flex min-w-0 items-center gap-3 rounded-md border border-line px-3 py-2 font-mono text-[11px] uppercase tracking-[0.14em] transition-colors hover:border-line-strong hover:bg-hover";

  return (
    <nav aria-label="Screen navigation" className="mt-auto border-t border-line">
      <div className="mx-auto flex w-full max-w-[1760px] items-center justify-between gap-3 px-4 py-3 md:px-10">
        {prev ? (
          <Link href={stepHref(prev)} className={linkClass}>
            <kbd className="text-muted group-hover:text-text">←</kbd>
            <span className="truncate">{prev.label}</span>
          </Link>
        ) : (
          <span />
        )}
        <p className="num hidden text-[11px] uppercase tracking-[0.16em] text-muted md:block">
          Screen {String(step.index + 1).padStart(2, "0")} / {String(STEPS.length).padStart(2, "0")} · use ← → to navigate
        </p>
        {next ? (
          <Link href={stepHref(next)} className={`${linkClass} justify-end`}>
            <span className="truncate">{next.label}</span>
            <kbd className="text-muted group-hover:text-text">→</kbd>
          </Link>
        ) : (
          <span />
        )}
      </div>
    </nav>
  );
}
