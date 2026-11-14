"use client";

import { useEffect, useRef, useState, useSyncExternalStore } from "react";

const QUERY = "(prefers-reduced-motion: reduce)";

function subscribe(onChange: () => void) {
  const mq = window.matchMedia(QUERY);
  mq.addEventListener("change", onChange);
  return () => mq.removeEventListener("change", onChange);
}

/** True when the viewer asked for reduced motion. Server render assumes reduced (no motion before hydration). */
export function useReducedMotion(): boolean {
  return useSyncExternalStore(
    subscribe,
    () => window.matchMedia(QUERY).matches,
    () => true,
  );
}

const easeOut = (t: number) => 1 - Math.pow(1 - t, 3);

/**
 * Tween from `from` to `target` once per `key`. The final frame is exactly `target` (never a rounded neighbour), and
 * with reduced motion, or no `target`, it is `target` at once. Display only: `target` is always an API value.
 */
export function useTween(target: number | null, from: number, key: string, durationMs: number, delayMs = 0): number | null {
  const reduce = useReducedMotion();
  const [frame, setFrame] = useState<{ key: string; value: number } | null>(null);
  const raf = useRef(0);

  useEffect(() => {
    if (target === null || reduce) return;
    const start = performance.now() + delayMs;
    const tick = (now: number) => {
      const t = Math.min(1, Math.max(0, (now - start) / durationMs));
      setFrame({ key, value: t >= 1 ? target : from + (target - from) * easeOut(t) });
      if (t < 1) raf.current = requestAnimationFrame(tick);
    };
    raf.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf.current);
  }, [target, from, key, durationMs, delayMs, reduce]);

  if (target === null) return null;
  if (reduce) return target;
  return frame && frame.key === key ? frame.value : from;
}

/** Seconds since `startedAt` (epoch ms), ticking once a second from the real clock; null when not running. */
export function useElapsedSeconds(startedAt: number | null): number | null {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (startedAt === null) return;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [startedAt]);
  if (startedAt === null) return null;
  return Math.max(0, Math.floor((Math.max(now, startedAt) - startedAt) / 1000));
}

/**
 * Reveal `count` already-returned items one by one (`stepMs` apart). Returns how many are shown. Reduced motion
 * shows all of them at once. Nothing is revealed that is not already in hand: `count` is the length of a response.
 */
export function useStagger(count: number, key: string, stepMs: number, delayMs = 0): number {
  const reduce = useReducedMotion();
  const [shown, setShown] = useState<{ key: string; n: number }>({ key: "", n: 0 });
  useEffect(() => {
    if (reduce || count === 0) return;
    const timers: ReturnType<typeof setTimeout>[] = [];
    for (let i = 1; i <= count; i++) {
      timers.push(setTimeout(() => setShown({ key, n: i }), delayMs + i * stepMs));
    }
    return () => timers.forEach(clearTimeout);
  }, [count, key, stepMs, delayMs, reduce]);
  if (reduce) return count;
  return shown.key === key ? Math.min(shown.n, count) : 0;
}
