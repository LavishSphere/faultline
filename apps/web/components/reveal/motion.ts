"use client";

import { useEffect, useRef, useState, type RefObject } from "react";

/**
 * Presentation clock for the REVEAL screen's animations (#164). It only decides WHEN an already received API value
 * is drawn; it never produces, delays or alters a value. Every count-up ends on exactly the API number, and under
 * prefers-reduced-motion the clock starts at its end, so the final state shows at once.
 */

export const DONE = Number.POSITIVE_INFINITY;

export function prefersReducedMotion(): boolean {
  try {
    return typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  } catch {
    return false;
  }
}

/**
 * Milliseconds since `start` became true, as a rAF clock; DONE once `totalMs` has passed, under reduced motion, or
 * when skipped. Changing `runKey` replays from 0.
 */
export function useClock(totalMs: number, start: boolean, runKey: number = 0): { elapsed: number; skip: () => void } {
  const [elapsed, setElapsed] = useState<number>(() => (prefersReducedMotion() ? DONE : 0));
  const skipped = useRef(false);

  useEffect(() => {
    if (!start) return;
    skipped.current = false;
    if (prefersReducedMotion()) {
      const id = requestAnimationFrame(() => setElapsed(DONE));
      return () => cancelAnimationFrame(id);
    }
    let raf = 0;
    const t0 = performance.now();
    const tick = (now: number) => {
      const t = now - t0;
      if (skipped.current || t >= totalMs) {
        setElapsed(DONE);
        return;
      }
      setElapsed(t);
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [start, totalMs, runKey]);

  return {
    elapsed,
    skip: () => {
      skipped.current = true;
      setElapsed(DONE);
    },
  };
}

/** 0..1 eased progress (cubic out) of a step that starts at `at` ms and lasts `dur` ms; exactly 1 once done. */
export function progress(elapsed: number, at: number, dur: number): number {
  if (elapsed >= at + dur) return 1;
  if (elapsed <= at) return 0;
  const t = (elapsed - at) / dur;
  return 1 - Math.pow(1 - t, 3);
}

/** A frame of a count-up from 0 to `target`. The last frame is `target` itself, not a product that may round off. */
export function countTo(target: number, elapsed: number, at: number, dur: number): number {
  const p = progress(elapsed, at, dur);
  return p >= 1 ? target : target * p;
}

/** True once the element has been on screen (or at once where IntersectionObserver is missing). */
export function useInView<T extends Element>(ref: RefObject<T | null>): boolean {
  const [seen, setSeen] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el || seen) return;
    if (typeof IntersectionObserver === "undefined") {
      const id = requestAnimationFrame(() => setSeen(true));
      return () => cancelAnimationFrame(id);
    }
    const io = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) {
          setSeen(true);
          io.disconnect();
        }
      },
      { threshold: 0.25 },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [ref, seen]);
  return seen;
}

/**
 * A nice upper bound for a bar or axis scale (display geometry only, never shown as a result): the smallest of
 * 1, 2, 2.5, 5 × 10^k that is at least `max`.
 */
export function niceCeil(max: number): number {
  if (!(max > 0) || !Number.isFinite(max)) return 1;
  const k = Math.pow(10, Math.floor(Math.log10(max)));
  for (const m of [1, 2, 2.5, 5, 10]) if (m * k >= max) return m * k;
  return 10 * k;
}

/**
 * Series colors for agent vs market (validated with the dataviz palette script against both panel surfaces: dark
 * #7c84f2 / #cf7f3c on #11161f, light #6366f1 / #b45f1c on #ffffff). Naive p = 0.5 is a neutral reference, not a
 * series. Identity is never color alone: markers differ (agent ●, market ◆) and every series is labeled.
 */
export const SERIES_CSS = `
.fl-series{--s-agent:#7c84f2;--s-market:#cf7f3c;--s-naive:var(--muted)}
@media (prefers-color-scheme: light){:root:not([data-theme="dark"]) .fl-series{--s-agent:#6366f1;--s-market:#b45f1c}}
:root[data-theme="light"] .fl-series{--s-agent:#6366f1;--s-market:#b45f1c}
`;
