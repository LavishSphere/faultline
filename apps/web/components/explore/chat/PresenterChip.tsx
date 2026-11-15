"use client";

import { useEffect, useRef, useState, useSyncExternalStore, type FormEvent } from "react";
import { PRESENTER_HASH, clearPresenterToken, getPresenterToken, setPresenterToken } from "@/lib/presenter";

/**
 * Presenter mode (#222, lib/presenter.ts). /explore/#presenter opens a small prompt for the admin token; once saved,
 * a "PRESENTER" chip with "exit" shows. The token is never rendered: the input is uncontrolled (no value attribute),
 * cleared after saving, and the hash is removed from the URL. `onChange` lets the panel reload the model list.
 */
const CHANGED = "faultline:presenter";
const subscribe = (cb: () => void) => {
  window.addEventListener(CHANGED, cb);
  window.addEventListener("storage", cb);
  return () => {
    window.removeEventListener(CHANGED, cb);
    window.removeEventListener("storage", cb);
  };
};

export function PresenterChip({ onChange }: { onChange?: () => void }) {
  const on = useSyncExternalStore(subscribe, () => getPresenterToken() !== null, () => false);
  const [asking, setAsking] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const setOn = () => window.dispatchEvent(new Event(CHANGED));

  useEffect(() => {
    const check = () => {
      if (window.location.hash === PRESENTER_HASH) {
        setAsking(true);
        history.replaceState(null, "", window.location.pathname + window.location.search);
      }
    };
    check();
    window.addEventListener("hashchange", check);
    return () => window.removeEventListener("hashchange", check);
  }, []);

  const save = (e: FormEvent) => {
    e.preventDefault();
    const el = input.current;
    const ok = !!el && setPresenterToken(el.value);
    if (el) el.value = "";
    if (!ok) {
      setNote("Not saved: type the token, and allow site data in this browser.");
      return;
    }
    setNote(null);
    setAsking(false);
    setOn();
    onChange?.();
  };
  const exit = () => {
    clearPresenterToken();
    setOn();
    onChange?.();
  };

  if (asking) {
    return (
      <form onSubmit={save} className="flex flex-wrap items-center gap-2 rounded-md border border-line-strong px-2 py-1" data-testid="presenter-prompt">
        <label className="font-mono text-[10.5px] uppercase tracking-[0.12em] text-muted" htmlFor="presenter-token">
          Presenter token
        </label>
        <input
          id="presenter-token"
          ref={input}
          type="password"
          autoComplete="off"
          spellCheck={false}
          className="w-48 rounded border border-line bg-bg px-2 py-0.5 font-mono text-[12px] text-text"
          data-testid="presenter-input"
        />
        <button type="submit" className="rounded border border-accent/60 px-2 py-0.5 font-mono text-[10.5px] uppercase text-text hover:bg-accent-soft">
          Save
        </button>
        <button type="button" onClick={() => setAsking(false)} className="font-mono text-[10.5px] uppercase text-muted hover:text-text">
          Cancel
        </button>
        {note ? <span className="font-mono text-[10.5px] text-fail">{note}</span> : null}
      </form>
    );
  }
  if (!on) return null;
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-accent/60 px-2 py-0.5 font-mono text-[10px] uppercase tracking-[0.12em] text-text" data-testid="presenter-chip">
      Presenter
      <button type="button" onClick={exit} className="normal-case tracking-normal text-muted underline hover:text-text" data-testid="presenter-exit">
        exit
      </button>
    </span>
  );
}
