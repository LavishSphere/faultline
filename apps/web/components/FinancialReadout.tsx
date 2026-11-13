"use client";

import { useEffect, useRef, useState } from "react";
import { ProvenanceBadge, type ProvenanceInput } from "./ProvenanceBadge";

/** Display formatters only. They never derive a figure; they render the one the API returned. */
export type ReadoutFormat = "usd" | "probability" | "weeks" | "percent";

const FORMATTERS: Record<ReadoutFormat, (n: number) => string> = {
  usd: (n) => new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(n),
  probability: (n) => n.toFixed(3),
  weeks: (n) => n.toFixed(0),
  percent: (n) => `${(n * 100).toFixed(1)}%`,
};

/**
 * A readout value exactly as the API reports it:
 * - a number;
 * - `{ above: T }` when the quantity exceeds the simulated horizon, e.g. runway with no week of
 *   negative cash renders "> 26 weeks" (MATH_MODEL §3). Never extrapolated in the browser;
 * - `null` when not available.
 */
export type ReadoutValue = number | { above: number } | null;

/**
 * Large financial figure. The value must come from an API response; `null` renders NOT AVAILABLE.
 * When a numeric value changes it counts up to it, and the final frame is exactly the formatted API value.
 * Under prefers-reduced-motion the value is shown immediately.
 */
export function FinancialReadout({
  label,
  value,
  format,
  provenance,
  unit,
  sublabel,
  size = "lg",
}: {
  label: string;
  value: ReadoutValue;
  format: ReadoutFormat;
  /** Provenance of the value when present. Ignored (NOT AVAILABLE) when value is null. */
  provenance: ProvenanceInput;
  unit?: string;
  sublabel?: string;
  size?: "md" | "lg" | "xl";
}) {
  const numeric = typeof value === "number" ? value : null;
  const shown = useCountUp(numeric);
  const fmt = FORMATTERS[format];
  const sizeClass =
    size === "xl" ? "text-5xl md:text-7xl" : size === "lg" ? "text-4xl md:text-5xl" : "text-2xl md:text-3xl";

  let body;
  if (value === null) {
    body = (
      <p
        className={`num font-medium uppercase tracking-[0.06em] text-muted ${size === "md" ? "text-xl md:text-2xl" : "text-2xl md:text-3xl"}`}
      >
        Not available
      </p>
    );
  } else {
    const exact = typeof value === "number" ? fmt(value) : `> ${fmt(value.above)}`;
    const animated = typeof value === "number" ? fmt(shown ?? value) : exact;
    body = (
      <p className={`num font-medium leading-none tracking-tight text-text ${sizeClass}`}>
        {/* Screen readers get the exact value, not intermediate animation frames. */}
        <span aria-hidden="true">{animated}</span>
        <span className="sr-only">
          {typeof value === "number" ? exact : `more than ${fmt(value.above)}`}
        </span>
        {unit ? <span className="ml-2 text-base text-muted">{unit}</span> : null}
      </p>
    );
  }

  return (
    <div className="flex min-w-0 flex-col gap-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="kicker">{label}</span>
        <ProvenanceBadge kind={value === null ? "NOT AVAILABLE" : provenance} />
      </div>
      {body}
      {sublabel ? <p className="text-xs text-muted">{sublabel}</p> : null}
    </div>
  );
}

function useCountUp(target: number | null, durationMs = 650): number | null {
  const [shown, setShown] = useState<number | null>(target);
  const fromRef = useRef<number | null>(target);

  useEffect(() => {
    if (target === null) {
      fromRef.current = null;
      return;
    }
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const from = fromRef.current;
    if (reduce || from === null || from === target) {
      fromRef.current = target;
      const id = requestAnimationFrame(() => setShown(target));
      return () => cancelAnimationFrame(id);
    }
    let raf = 0;
    const start = performance.now();
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / durationMs);
      const eased = 1 - Math.pow(1 - t, 3);
      // Final frame is exactly the target value.
      setShown(t >= 1 ? target : from + (target - from) * eased);
      if (t < 1) raf = requestAnimationFrame(tick);
      else fromRef.current = target;
    };
    raf = requestAnimationFrame(tick);
    return () => {
      cancelAnimationFrame(raf);
      fromRef.current = target;
    };
  }, [target, durationMs]);

  return shown;
}
