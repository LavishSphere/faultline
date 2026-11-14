"use client";

import { settled, useHealth } from "../HealthProvider";

/**
 * Local-model readiness for the run controls, from GET /api/health only. Advisory: the run route itself is the
 * authority (it answers 503 MODEL_UNAVAILABLE when Ollama is down, never a canned answer).
 */
export function ModelReadiness() {
  const { state } = useHealth();
  const last = settled(state);

  let tone = "text-muted";
  let text = "Checking API status";
  let detail = "Waiting for GET /api/health.";

  if (last?.kind === "unreachable") {
    tone = "text-fail";
    text = "API unavailable";
    detail = "Model readiness cannot be determined while the API is unreachable.";
  } else if (last?.kind === "online") {
    const { model, modelTags } = last.health;
    if (model === "available") {
      tone = "text-viable";
      text = "Local model ready";
      detail = `Installed: ${modelTags.join(", ")}.`;
    } else if (model === "unavailable") {
      tone = "text-risk";
      text = "Local model unavailable";
      detail = "No local open-weight model is reachable, so a run will be refused by the API. No decision is invented.";
    } else {
      text = "Model status not reported";
      detail = "GET /api/health did not report local model readiness.";
    }
  }

  return (
    <div className="flex flex-col gap-1" aria-live="polite">
      <p className={`font-mono text-sm uppercase tracking-[0.14em] ${tone}`}>{text}</p>
      <p className="text-xs leading-relaxed text-muted">{detail}</p>
    </div>
  );
}
