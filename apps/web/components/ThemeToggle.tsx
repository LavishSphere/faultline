"use client";

import { useSyncExternalStore } from "react";
import { THEME_EVENT, THEME_STORAGE_KEY } from "@/lib/theme";

/**
 * Light/dark toggle. Default follows prefers-color-scheme; choosing a theme sets [data-theme] on <html>
 * and remembers it per browser (localStorage, best effort). The pre-paint script in layout.tsx applies
 * the stored choice before first render to avoid a flash.
 */
type Theme = "light" | "dark";

function effectiveTheme(): Theme {
  const forced = document.documentElement.getAttribute("data-theme");
  if (forced === "light" || forced === "dark") return forced;
  return window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
}

function subscribe(onChange: () => void) {
  const mq = window.matchMedia("(prefers-color-scheme: light)");
  mq.addEventListener("change", onChange);
  window.addEventListener(THEME_EVENT, onChange);
  return () => {
    mq.removeEventListener("change", onChange);
    window.removeEventListener(THEME_EVENT, onChange);
  };
}

export function ThemeToggle() {
  const theme = useSyncExternalStore<Theme | null>(subscribe, effectiveTheme, () => null);
  const next: Theme = theme === "light" ? "dark" : "light";

  function toggle() {
    document.documentElement.setAttribute("data-theme", next);
    try {
      localStorage.setItem(THEME_STORAGE_KEY, next);
    } catch {
      // Storage may be unavailable (private mode); the toggle still works for this page view.
    }
    window.dispatchEvent(new Event(THEME_EVENT));
  }

  return (
    <button
      type="button"
      onClick={toggle}
      aria-label={theme ? `Switch to ${next} theme` : "Toggle color theme"}
      title={theme ? `Switch to ${next} theme` : "Toggle color theme"}
      className="flex h-8 items-center gap-2 rounded-md border border-line bg-elevated/70 px-2.5 font-mono text-[10.5px] uppercase tracking-[0.12em] text-text-2 transition-colors hover:border-line-strong hover:bg-hover hover:text-text"
    >
      <span aria-hidden="true" className="relative inline-block size-3 overflow-hidden rounded-full border border-current">
        <span className="absolute inset-y-0 right-0 w-1/2 bg-current" />
      </span>
      <span className="hidden sm:inline">{theme ?? "Theme"}</span>
    </button>
  );
}
