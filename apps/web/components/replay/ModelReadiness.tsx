"use client";

import { describeModelStatus } from "@/lib/api";
import { settled, useHealth } from "../HealthProvider";
import { LocalModelBadge } from "./LocalModelBadge";
import { useModelCard } from "./useModelCard";

/**
 * Local-model readiness for the run controls, from GET /api/health only. Advisory: the run route itself is the
 * authority (it answers 503 MODEL_UNAVAILABLE when Ollama is down, never a canned answer).
 */
export function ModelReadiness() {
  const { state } = useHealth();
  const last = settled(state);
  const card = useModelCard();

  let tone = "text-muted";
  let text = "Checking API status";
  let detail = "Waiting for GET /api/health.";

  if (last?.kind === "unreachable") {
    tone = "text-fail";
    text = "API unavailable";
    detail = "Model readiness cannot be determined while the API is unreachable.";
  } else if (last?.kind === "online") {
    const { model, modelTags, requiredModel, modelError, serverMode } = last.health;
    if (serverMode === "public") {
      // #184: the public server runs no model by design (inference is admin-only there). Say that, not "unavailable".
      // Run stays admin-gated by the API; the RECORDED RUN panel is the primary forecast.
      const view = describeModelStatus(last.health, card.kind === "done" ? (card.card?.model ?? null) : null);
      tone = "text-info";
      text = view.chip;
      detail = `${view.explain} Run is admin-only on this server; the RECORDED RUN panel is the forecast shown.`;
    } else if (model === "available") {
      tone = "text-viable";
      text = "Local model ready";
      detail = `GET /api/health: model_ready true for ${requiredModel ?? "the configured model"}. Installed in Ollama: ${modelTags.join(", ") || "not listed"}.`;
    } else if (model === "unavailable") {
      tone = "text-risk";
      text = "Local model unavailable";
      detail = `${modelError ?? `GET /api/health: model_ready false${requiredModel ? ` (${requiredModel} not installed)` : ""}.`} A run will be refused by the API. No decision is invented.`;
    } else {
      text = "Model status not reported";
      detail = "GET /api/health did not report local model readiness.";
    }
  }

  return (
    <div className="flex flex-col gap-2.5" aria-live="polite">
      <p className={`font-mono text-sm uppercase tracking-[0.14em] ${tone}`}>{text}</p>
      <LocalModelBadge />
      <p className="text-xs leading-relaxed text-muted">{detail}</p>
    </div>
  );
}
