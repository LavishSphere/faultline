"use client";

import { useEffect } from "react";
import { usePathname, useRouter } from "next/navigation";
import { STEPS, stepFromPath, stepHref } from "@/lib/steps";

function isEditable(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (target.isContentEditable) return true;
  // Inputs (incl. range sliders), selects and sliders use the arrow keys themselves; never steal them.
  const tag = target.tagName;
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return true;
  return target.getAttribute("role") === "slider";
}

/** ← / → move between presenter screens. Ignored while typing or adjusting a control. */
export function KeyNav() {
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    const current = stepFromPath(pathname);
    if (!current) return;
    const prev = STEPS[current.index - 1];
    const next = STEPS[current.index + 1];
    if (prev) router.prefetch(stepHref(prev));
    if (next) router.prefetch(stepHref(next));

    function onKey(e: KeyboardEvent) {
      if (e.defaultPrevented || e.altKey || e.ctrlKey || e.metaKey || e.shiftKey) return;
      if (isEditable(e.target)) return;
      if (e.key === "ArrowRight" && next) {
        e.preventDefault();
        router.push(stepHref(next));
      } else if (e.key === "ArrowLeft" && prev) {
        e.preventDefault();
        router.push(stepHref(prev));
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [pathname, router]);

  return null;
}
