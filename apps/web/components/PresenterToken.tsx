"use client";

import { useState, useSyncExternalStore, type FormEvent } from "react";
import {
  PRESENTER_EVENT,
  PRESENTER_TOKEN_PATTERN,
  clearPresenterToken,
  getPresenterToken,
  setPresenterToken,
} from "@/lib/presenter";

/**
 * Presenter mode (docs/DEPLOY.md "Presenter mode"). Hidden for every visitor: it renders only when the URL has
 * `?presenter=1`, or while a presenter token is already stored in this tab (so the PRESENTER badge never disappears
 * while requests still carry the token). The token lives in sessionStorage only (lib/presenter.ts); this component
 * never shows it back, never puts it in the URL and clears the input after saving.
 */

function subscribe(onChange: () => void) {
  window.addEventListener(PRESENTER_EVENT, onChange);
  window.addEventListener("popstate", onChange);
  return () => {
    window.removeEventListener(PRESENTER_EVENT, onChange);
    window.removeEventListener("popstate", onChange);
  };
}

function requested(): boolean {
  try {
    return new URLSearchParams(window.location.search).get("presenter") === "1";
  } catch {
    return false;
  }
}

export function PresenterToken() {
  const active = useSyncExternalStore(subscribe, () => getPresenterToken() !== null, () => false);
  const asked = useSyncExternalStore(subscribe, requested, () => false);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | null>(null);

  if (!asked && !active) return null;

  function save(e: FormEvent) {
    e.preventDefault();
    if (!PRESENTER_TOKEN_PATTERN.test(draft.trim())) {
      setError("Not a token: expected 64 lower-case hex characters (openssl rand -hex 32).");
      return;
    }
    if (!setPresenterToken(draft)) {
      setError("This browser refused session storage; the token was not kept.");
      return;
    }
    setDraft("");
    setError(null);
  }

  return (
    <aside
      aria-label="Presenter mode"
      data-testid="presenter-token"
      className="fixed bottom-3 left-3 z-50 flex max-w-[calc(100vw-24px)] flex-wrap items-center gap-2 rounded-md border border-line bg-elevated/95 px-2.5 py-2 font-mono text-[10.5px] uppercase tracking-[0.12em] text-text-2 shadow-lg"
    >
      {active ? (
        <>
          <span
            data-testid="presenter-badge"
            className="rounded-sm border border-accent px-1.5 py-0.5 text-accent"
            title="Run and reveal requests from this tab carry the admin token (sessionStorage, this tab only)."
          >
            PRESENTER
          </span>
          <button
            type="button"
            onClick={() => clearPresenterToken()}
            className="rounded-sm border border-line px-1.5 py-0.5 hover:border-line-strong hover:text-text"
          >
            clear
          </button>
        </>
      ) : (
        <form onSubmit={save} className="flex flex-wrap items-center gap-2">
          <label htmlFor="presenter-token-input">Presenter token</label>
          <input
            id="presenter-token-input"
            type="password"
            autoComplete="off"
            spellCheck={false}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            className="w-44 rounded-sm border border-line bg-bg px-1.5 py-0.5 normal-case tracking-normal text-text"
          />
          <button
            type="submit"
            className="rounded-sm border border-line px-1.5 py-0.5 hover:border-line-strong hover:text-text"
          >
            save
          </button>
          {error ? (
            <span role="alert" className="normal-case tracking-normal text-text">
              {error}
            </span>
          ) : null}
        </form>
      )}
    </aside>
  );
}
