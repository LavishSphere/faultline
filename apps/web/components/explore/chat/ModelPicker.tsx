"use client";

import { useId, useMemo } from "react";
import {
  PROVIDER_LABEL,
  PROVIDER_SHORT,
  contextLabel,
  featuredModels,
  groupModels,
  priceLabel,
  type ChatModel,
  type ChatModelsResponse,
} from "@/lib/chat";

/**
 * Model picker (#186). The server's featured models as pills (plus its default, if not featured), grouped "Open
 * models via OpenRouter", "OpenAI (direct)", "Anthropic Claude (direct)". Native radios, so arrow keys move between
 * them. Unavailable models are disabled with the server's note. Provider, context length and price per million tokens
 * are shown only when the server sends them. (A search over the full catalogue is a follow-up.)
 */

/** Pills shown when an older API build sends no `featured` list. */
const MAX_FALLBACK_PILLS = 8;

function meta(m: ChatModel): string {
  return [PROVIDER_SHORT[m.provider], contextLabel(m), priceLabel(m)].filter(Boolean).join(" · ");
}

function Pill({ m, checked, disabled, onSelect, name }: { m: ChatModel; checked: boolean; disabled: boolean; onSelect: (id: string) => void; name: string }) {
  const off = disabled || !m.available;
  return (
    <label
      className={`group relative flex min-w-0 max-w-full cursor-pointer flex-wrap items-center gap-x-2 gap-y-0.5 rounded-[1.25rem] border px-3.5 py-2 transition-colors has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-[var(--accent)] ${
        checked
          ? "border-accent bg-accent-soft text-text shadow-[0_0_0_1px_var(--accent),0_0_24px_-6px_var(--accent)]"
          : off
            ? "cursor-not-allowed border-dashed border-line text-muted"
            : "border-line-strong text-text-2 hover:border-accent/60 hover:bg-hover hover:text-text"
      }`}
      title={!m.available ? (m.note ?? "Unavailable on this server") : meta(m)}
      data-testid="chat-model-pill"
      data-model={m.id}
      data-available={m.available ? "true" : "false"}
    >
      <input
        type="radio"
        name={name}
        value={m.id}
        checked={checked}
        disabled={off}
        onChange={() => onSelect(m.id)}
        className="sr-only"
        aria-describedby={!m.available && m.note ? `${name}-${m.id}-note` : undefined}
      />
      <span aria-hidden="true" className={`size-1.5 shrink-0 rounded-full ${checked ? "bg-accent" : m.available ? "bg-viable" : "bg-line-strong"}`} />
      <span className="min-w-0 truncate text-sm font-medium">{m.label}</span>
      {!m.available ? (
        <span id={`${name}-${m.id}-note`} className="min-w-0 break-words font-mono text-[10px] uppercase tracking-[0.1em]">
          · {m.note ?? "unavailable"}
        </span>
      ) : null}
    </label>
  );
}

export function ModelPicker({
  data,
  selected,
  onSelect,
  disabled,
}: {
  data: ChatModelsResponse;
  selected: string | null;
  onSelect: (id: string) => void;
  disabled: boolean;
}) {
  const name = useId();
  const pills = useMemo(() => {
    const f = featuredModels(data);
    // An older API build sends no `featured`: the first few served models stand in, in the server's order.
    const shown = f.length ? f : data.models.slice(0, MAX_FALLBACK_PILLS);
    // The server default is always one click away, even when it is not featured.
    const def = data.models.find((m) => m.id === data.default);
    return def && !shown.some((m) => m.id === def.id) ? [...shown, def] : shown;
  }, [data]);
  const groups = groupModels(pills);
  const current = data.models.find((m) => m.id === selected) ?? null;
  const hidden = data.models.length - pills.length;

  return (
    <div className="flex min-w-0 flex-col gap-3" data-testid="chat-model-picker">
      <div role="radiogroup" aria-label="Featured models" className="flex min-w-0 flex-col gap-3 xl:flex-row xl:flex-wrap xl:gap-x-6">
        {groups.map((g) => (
          <div key={g.provider} className="flex min-w-0 flex-col gap-1.5" data-testid={`chat-provider-${g.provider}`}>
            <p className="kicker">{PROVIDER_LABEL[g.provider]}</p>
            <div className="flex min-w-0 flex-wrap gap-2">
              {g.models.map((m) => (
                <Pill key={m.id} m={m} name={name} checked={m.id === selected} disabled={disabled} onSelect={onSelect} />
              ))}
            </div>
          </div>
        ))}
      </div>
      <div className="flex min-w-0 flex-wrap items-center gap-x-4 gap-y-2">
        <p className="min-w-0 break-words font-mono text-[11px] text-muted" data-testid="chat-selected-model" aria-live="polite">
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
        {hidden > 0 ? (
          <p className="font-mono text-[10.5px] text-muted" data-testid="chat-models-count">
            {pills.length} of {data.models.length.toLocaleString("en-US")} served models shown
          </p>
        ) : null}
      </div>
    </div>
  );
}
