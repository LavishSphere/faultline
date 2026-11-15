"use client";

import { useId, useMemo } from "react";
import {
  PROVIDER_LABEL,
  PROVIDER_SHORT,
  contextLabel,
  featuredModels,
  pickerGroups,
  priceLabel,
  type ChatModel,
  type ChatModelsResponse,
} from "@/lib/chat";
import "./galaxy.css";

/**
 * Model galaxy (stage 2): the server's featured models drawn as provider constellations. Each provider is a core
 * (its text label, no logos) with its models as stars on one orbit line: open models via OpenRouter, OpenAI
 * (direct), Anthropic Claude (direct). Native radios keep arrow-key selection; unavailable models are dimmed,
 * dashed and disabled, with the server's note. Context length and price are shown only when the server sends them.
 * "Browse all N" opens the full catalogue palette (ModelPalette); N is the served model count.
 */

/** Stars shown when an older API build sends no `featured` list. */
const MAX_FALLBACK_STARS = 8;

function meta(m: ChatModel): string {
  return [PROVIDER_SHORT[m.provider], contextLabel(m), priceLabel(m)].filter(Boolean).join(" · ");
}

function Star({
  m,
  checked,
  disabled,
  onSelect,
  name,
  index,
}: {
  m: ChatModel;
  checked: boolean;
  disabled: boolean;
  onSelect: (id: string) => void;
  name: string;
  index: number;
}) {
  const off = disabled || !m.available;
  const noteId = `${name}-${m.id}-note`;
  return (
    <label
      className={`galaxy-star group relative flex min-w-0 max-w-full cursor-pointer flex-wrap items-center gap-x-2 gap-y-0.5 rounded-[1.25rem] border px-3.5 py-2 has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-[var(--accent)] ${
        checked
          ? "border-accent bg-accent-soft text-text"
          : !m.available
            ? "cursor-not-allowed border-dashed border-line bg-bg/60 text-muted"
            : off
              ? "cursor-not-allowed border-line-strong bg-bg/80 text-muted"
              : "border-line-strong bg-bg/80 text-text-2 hover:border-accent/60 hover:bg-hover hover:text-text"
      }`}
      title={!m.available ? (m.note ?? "Unavailable on this server") : meta(m)}
      data-testid="chat-model-pill"
      data-model={m.id}
      data-available={m.available ? "true" : "false"}
      data-checked={checked ? "true" : "false"}
      data-off={off ? "true" : "false"}
    >
      <input
        type="radio"
        name={name}
        value={m.id}
        checked={checked}
        disabled={off}
        onChange={() => onSelect(m.id)}
        className="sr-only"
        aria-describedby={!m.available && m.note ? noteId : undefined}
      />
      <span
        aria-hidden="true"
        className={`galaxy-dot size-2 shrink-0 rounded-full ${
          checked ? "bg-accent" : m.available ? "bg-viable" : "border border-dashed border-muted bg-transparent"
        }`}
        data-on={checked ? "true" : "false"}
        data-twinkle={m.available && !checked ? "true" : "false"}
        style={m.available && !checked ? { animationDelay: `${(index * 0.73) % 4.8}s` } : undefined}
      />
      <span className="min-w-0 truncate text-sm font-medium">{m.label}</span>
      {!m.available ? (
        <span id={noteId} className="min-w-0 break-words font-mono text-[10px] uppercase tracking-[0.1em]">
          · {m.note ?? "unavailable"}
        </span>
      ) : null}
    </label>
  );
}

export function ModelGalaxy({
  data,
  selected,
  onSelect,
  disabled,
  onBrowse,
}: {
  data: ChatModelsResponse;
  selected: string | null;
  onSelect: (id: string) => void;
  disabled: boolean;
  onBrowse: () => void;
}) {
  const name = useId();
  const stars = useMemo(() => {
    const f = featuredModels(data);
    const shown = f.length ? f : data.models.slice(0, MAX_FALLBACK_STARS);
    // The server default is always one click away, even when it is not featured.
    const def = data.models.find((m) => m.id === data.default);
    return def && !shown.some((m) => m.id === def.id) ? [...shown, def] : shown;
  }, [data]);
  const groups = pickerGroups(stars);
  const byOpenness = groups.some((g) => g.key === "open" || g.key === "closed");
  const current = data.models.find((m) => m.id === selected) ?? null;
  const total = data.models.length;
  let starIndex = 0;

  return (
    <div className="flex min-w-0 flex-col gap-3" data-testid="chat-model-picker">
      <div
        role="radiogroup"
        aria-label="Featured models"
        className="galaxy-field grid min-w-0 grid-cols-1 gap-4 rounded-lg border border-line px-3 py-4 md:px-4 xl:grid-cols-3 xl:gap-6"
      >
        {groups.map((g) => {
          const live = g.models.filter((m) => m.available).length;
          return (
            <div key={g.key} className="galaxy-cluster flex min-w-0 flex-col gap-2" data-testid={byOpenness ? `chat-group-${g.key}` : `chat-provider-${g.key}`}>
              <div className="flex min-w-0 items-center gap-2">
                <span
                  aria-hidden="true"
                  className={`galaxy-core size-2.5 shrink-0 rounded-full ${live ? "bg-accent" : "border border-dashed border-muted bg-transparent"}`}
                />
                <p className="kicker min-w-0 truncate">{g.label}</p>
                <span className="num ml-auto shrink-0 font-mono text-[10px] text-muted">
                  {live}/{g.models.length} available
                </span>
              </div>
              <div className="galaxy-orbit flex min-w-0 flex-wrap gap-2 pl-1">
                {g.models.map((m) => (
                  <Star
                    key={m.id}
                    m={m}
                    name={name}
                    index={starIndex++}
                    checked={m.id === selected}
                    disabled={disabled}
                    onSelect={onSelect}
                  />
                ))}
              </div>
            </div>
          );
        })}
      </div>
      <div className="flex min-w-0 flex-wrap items-center gap-x-4 gap-y-2">
        <p className="min-w-0 flex-1 break-words font-mono text-[11px] text-muted" data-testid="chat-selected-model" aria-live="polite">
          {current ? (
            <>
              Selected: <span className="text-text">{current.label}</span> · {PROVIDER_LABEL[current.provider]}
              {contextLabel(current) ? ` · ${contextLabel(current)}` : ""}
              {priceLabel(current) ? ` · ${priceLabel(current)}` : ""}
            </>
          ) : (
            "No model selected: pick one to start."
          )}
        </p>
        <button
          type="button"
          onClick={onBrowse}
          disabled={disabled || total === 0}
          className="flex shrink-0 items-center gap-2 rounded-md border border-line-strong px-3 py-1.5 font-mono text-[11px] uppercase tracking-[0.12em] text-text-2 hover:border-accent/60 hover:bg-hover hover:text-text disabled:cursor-not-allowed disabled:opacity-50"
          data-testid="chat-browse-models"
          aria-keyshortcuts="Meta+K Control+K"
        >
          <span>
            Browse all <span className="num">{total.toLocaleString("en-US")}</span> models
          </span>
          <kbd className="rounded-sm border border-line px-1 py-px text-[10px] text-muted">⌘K</kbd>
        </button>
      </div>
    </div>
  );
}
