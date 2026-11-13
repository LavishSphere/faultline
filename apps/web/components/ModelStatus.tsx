"use client";

import { settled, useHealth } from "./HealthProvider";

/**
 * Local-model readiness line for the DECISION screen, from `/api/health` only.
 * When the model is down this says so explicitly; it never substitutes a canned answer.
 */
export function ModelStatus() {
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
      detail = `Installed: ${modelTags.join(", ")}. Replay runs are not wired in this build.`;
    } else if (model === "unavailable") {
      tone = "text-risk";
      text = "Local model unavailable";
      detail = "No local open-weight model is reachable, so no decision is shown. The simulator and optimizer will remain usable once wired.";
    } else {
      text = "Model status not reported";
      detail = "/api/health did not report local model readiness.";
    }
  }

  return (
    <div className="flex flex-col gap-1" aria-live="polite">
      <p className={`font-mono text-sm uppercase tracking-[0.14em] ${tone}`}>{text}</p>
      <p className="text-xs leading-relaxed text-muted">{detail}</p>
    </div>
  );
}
