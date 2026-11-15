"use client";

import { useEffect, useId, useMemo, useRef, useState, type KeyboardEvent } from "react";
import {
  CHAT_PROVIDERS,
  PROVIDER_LABEL,
  PROVIDER_SHORT,
  contextLabel,
  priceLabel,
  type ChatModel,
} from "@/lib/chat";
import "./galaxy.css";

/**
 * "Browse all models" command palette (stage 2). The full served catalogue (GET /api/explore/chat/models), searchable
 * by label, id and provider. Context length and price per million tokens are the server's, formatted by lib/chat;
 * "n/a" when the server does not send them, never a guess. Only available models can be picked.
 * The ⌘K / Ctrl+K shortcut that opens it lives in ChatPanel.
 */

/** Rows rendered at once; the match count is always exact. */
const MAX_ROWS = 80;

const PROVIDER_ORDER = new Map<string, number>(CHAT_PROVIDERS.map((p, i) => [p, i]));

function matches(m: ChatModel, q: string): boolean {
  if (!q) return true;
  return (
    m.label.toLowerCase().includes(q) ||
    m.id.toLowerCase().includes(q) ||
    PROVIDER_LABEL[m.provider].toLowerCase().includes(q) ||
    PROVIDER_SHORT[m.provider].toLowerCase().includes(q)
  );
}

export function ModelPalette({
  open,
  onClose,
  models,
  selected,
  onSelect,
  title = "Browse all models",
}: {
  open: boolean;
  onClose: () => void;
  models: readonly ChatModel[];
  selected: string | null;
  onSelect: (id: string) => void;
  title?: string;
}) {
  if (!open) return null;
  return <PaletteBody onClose={onClose} models={models} selected={selected} onSelect={onSelect} title={title} />;
}

function PaletteBody({
  onClose,
  models,
  selected,
  onSelect,
  title,
}: {
  onClose: () => void;
  models: readonly ChatModel[];
  selected: string | null;
  onSelect: (id: string) => void;
  title: string;
}) {
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const listRef = useRef<HTMLUListElement | null>(null);
  const returnFocus = useRef<Element | null>(null);
  const titleId = useId();
  const listId = useId();

  const sorted = useMemo(
    () =>
      models
        .map((m, i) => ({ m, i }))
        .sort((a, b) => (PROVIDER_ORDER.get(a.m.provider) ?? 9) - (PROVIDER_ORDER.get(b.m.provider) ?? 9) || a.i - b.i)
        .map((x) => x.m),
    [models],
  );
  const q = query.trim().toLowerCase();
  const found = useMemo(() => sorted.filter((m) => matches(m, q)), [sorted, q]);
  const rows = found.slice(0, MAX_ROWS);
  const activeIdx = rows.length ? Math.min(active, rows.length - 1) : -1;

  useEffect(() => {
    returnFocus.current = document.activeElement;
    inputRef.current?.focus();
    return () => {
      const el = returnFocus.current;
      if (el instanceof HTMLElement) el.focus();
    };
  }, []);

  useEffect(() => {
    if (activeIdx < 0) return;
    const el = listRef.current?.querySelector<HTMLElement>(`[data-index="${activeIdx}"]`);
    el?.scrollIntoView?.({ block: "nearest" });
  }, [activeIdx]);

  const pick = (m: ChatModel | undefined) => {
    if (!m || !m.available) return;
    onSelect(m.id);
    onClose();
  };

  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key === "Escape") {
      e.preventDefault();
      onClose();
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      if (rows.length) setActive((activeIdx + 1) % rows.length);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      if (rows.length) setActive((activeIdx - 1 + rows.length) % rows.length);
    } else if (e.key === "Enter") {
      e.preventDefault();
      pick(rows[activeIdx]);
    } else if (e.key === "Tab") {
      // Focus stays on the search box; the rows are reached with the arrow keys.
      e.preventDefault();
      inputRef.current?.focus();
    }
  };

  const activeId = activeIdx >= 0 ? `${listId}-row-${activeIdx}` : undefined;

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-bg/70 px-4 pt-[8vh] backdrop-blur-[12px]"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        data-testid="chat-palette"
        onKeyDown={onKey}
        className="palette-in flex max-h-[80vh] w-full min-w-0 max-w-3xl flex-col overflow-hidden rounded-xl border border-line-strong bg-elevated shadow-[var(--shadow-panel)]"
      >
        <div className="flex min-w-0 flex-col gap-2 border-b border-line px-4 pb-3 pt-4">
          <div className="flex min-w-0 items-baseline justify-between gap-3">
            <p id={titleId} className="kicker !text-text-2">
              {title}
            </p>
            <p className="num shrink-0 font-mono text-[10.5px] text-muted" data-testid="chat-palette-count" aria-live="polite">
              {found.length.toLocaleString("en-US")} of {models.length.toLocaleString("en-US")} match
            </p>
          </div>
          <input
            ref={inputRef}
            type="search"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setActive(0);
            }}
            placeholder="Search by name, id or provider…"
            aria-label="Search models"
            aria-controls={listId}
            aria-activedescendant={activeId}
            role="combobox"
            aria-expanded="true"
            aria-autocomplete="list"
            autoFocus
            autoComplete="off"
            spellCheck={false}
            data-testid="chat-palette-search"
            className="w-full min-w-0 rounded-lg border border-line-strong bg-bg px-3 py-2.5 text-base text-text placeholder:text-muted focus:border-accent focus:outline-none"
          />
        </div>

        <ul ref={listRef} id={listId} role="listbox" aria-label="Models" className="min-h-0 flex-1 overflow-y-auto py-1">
          {rows.length === 0 ? (
            <li className="px-4 py-6 text-center font-mono text-[11px] uppercase tracking-[0.12em] text-muted" role="presentation">
              No served model matches “{query.trim()}”
            </li>
          ) : null}
          {rows.map((m, i) => {
            const isActive = i === activeIdx;
            const isSel = m.id === selected;
            const ctx = contextLabel(m);
            const price = priceLabel(m);
            return (
              <li
                key={m.id}
                id={`${listId}-row-${i}`}
                role="option"
                aria-selected={isActive}
                aria-disabled={!m.available}
                data-index={i}
                data-testid="chat-palette-item"
                data-model={m.id}
                data-available={m.available ? "true" : "false"}
                onMouseMove={() => {
                  if (active !== i) setActive(i);
                }}
                onClick={() => pick(m)}
                className={`mx-1 flex min-w-0 cursor-pointer flex-col gap-0.5 rounded-md border px-3 py-2 sm:flex-row sm:items-center sm:gap-3 ${
                  isActive ? "border-accent/60 bg-accent-soft" : "border-transparent"
                } ${m.available ? "" : "cursor-not-allowed opacity-60"}`}
              >
                <div className="flex min-w-0 flex-1 flex-col">
                  <span className="flex min-w-0 items-center gap-2">
                    <span
                      aria-hidden="true"
                      className={`size-1.5 shrink-0 rounded-full ${isSel ? "bg-accent" : m.available ? "bg-viable" : "border border-dashed border-muted"}`}
                    />
                    <span className="min-w-0 truncate text-sm font-medium text-text">{m.label}</span>
                    {isSel ? <span className="shrink-0 font-mono text-[9.5px] uppercase tracking-[0.12em] text-accent">selected</span> : null}
                  </span>
                  <span className="min-w-0 truncate pl-3.5 font-mono text-[11px] text-muted">{m.id}</span>
                  {!m.available ? (
                    <span className="min-w-0 break-words pl-3.5 font-mono text-[10px] uppercase tracking-[0.1em] text-muted">
                      {m.note ?? "unavailable"}
                    </span>
                  ) : null}
                </div>
                <div className="flex min-w-0 shrink-0 flex-wrap items-center gap-x-3 gap-y-0.5 pl-3.5 font-mono text-[10.5px] text-text-2 sm:justify-end sm:pl-0">
                  <span className="text-muted">{PROVIDER_SHORT[m.provider]}</span>
                  <span className="num">{ctx ?? "ctx n/a"}</span>
                  <span className="num">{price ?? "price n/a"}</span>
                </div>
              </li>
            );
          })}
        </ul>

        <div className="flex min-w-0 flex-wrap items-center justify-between gap-x-4 gap-y-1 border-t border-line px-4 py-2 font-mono text-[10.5px] text-muted">
          <span>↑↓ move · Enter select · Esc close</span>
          {found.length > MAX_ROWS ? (
            <span className="num" data-testid="chat-palette-more">
              Showing {MAX_ROWS} of {found.length.toLocaleString("en-US")} — refine the search
            </span>
          ) : (
            <span>Prices and context as the server publishes them</span>
          )}
        </div>
      </div>
    </div>
  );
}
