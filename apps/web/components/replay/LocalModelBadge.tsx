"use client";

import type { ReactNode } from "react";
import { settled, useHealth } from "../HealthProvider";
import { useModelCard } from "./useModelCard";
import m from "./motion.module.css";

/**
 * "Runs on this laptop" badge (#163). Every segment is a served value: the model is `ollama_status.required_model`
 * from GET /api/health, readiness is its `model_ready`, and the knowledge cutoff is the model card's
 * "Training data ends" fact from GET /api/integrity. When the health check says the model is not ready, the badge
 * says so instead of "runs locally".
 */
export function LocalModelBadge({ size = "md" }: { size?: "md" | "lg" }) {
  const { state } = useHealth();
  const last = settled(state);
  const card = useModelCard();

  let tone: "viable" | "risk" | "fail" | "muted" = "muted";
  let status = "Checking GET /api/health";
  let model: string | null = null;
  if (last?.kind === "unreachable") {
    tone = "fail";
    status = "API unavailable: model readiness unknown";
  } else if (last?.kind === "online") {
    const h = last.health;
    model = h.requiredModel ?? null;
    if (h.model === "available") {
      tone = "viable";
      status = "runs locally, no cloud";
    } else if (h.model === "unavailable") {
      tone = "risk";
      status = h.modelError ? "not ready: Ollama not reachable" : "not ready: model not installed in Ollama";
    } else {
      status = "readiness not reported";
    }
  }

  const facts = card.kind === "done" ? card.card : null;
  // The card fact is for the configured model; if it names another model it is not this model's cutoff.
  const cutoff = facts && model && facts.model === model ? facts.knowledgeCutoff : null;
  const cutoffText = card.kind === "loading" ? "knowledge cutoff …" : `knowledge cutoff ${cutoff ?? "NOT AVAILABLE"}`;

  const dot = { viable: "bg-viable", risk: "bg-risk", fail: "bg-fail", muted: "bg-muted" }[tone];
  const statusColor = { viable: "text-viable", risk: "text-risk", fail: "text-fail", muted: "text-muted" }[tone];
  const text = size === "lg" ? "text-[12px]" : "text-[11px]";

  return (
    <div
      className={`flex max-w-full flex-wrap items-center rounded-md border border-line bg-bg/50 font-mono uppercase tracking-[0.1em] text-text-2 ${text}`}
      data-testid="local-model-badge"
      data-ready={last?.kind === "online" ? last.health.model : "unknown"}
      aria-live="polite"
    >
      <span className="flex items-center gap-2 px-3 py-2">
        <span aria-hidden="true" className="relative flex size-2">
          {tone === "viable" ? <span className={`absolute inset-0 rounded-full bg-viable ${m.breathe}`} style={{ transform: "scale(2.2)", opacity: 0.25 }} /> : null}
          <span className={`relative inline-block size-2 rounded-full ${dot}`} />
        </span>
        <span className="text-text">Open model</span>
      </span>
      <Seg>
        <span className="normal-case tracking-normal text-text" data-testid="local-model-name">
          {model ?? (last?.kind === "online" ? "model NOT AVAILABLE" : "…")}
        </span>
      </Seg>
      <Seg>
        <span title={facts?.release ? `Public release ${facts.release} (model card)` : undefined}>{cutoffText}</span>
      </Seg>
      <Seg>
        <span className={statusColor} data-testid="local-model-status">
          {status}
        </span>
      </Seg>
    </div>
  );
}

function Seg({ children }: { children: ReactNode }) {
  return <span className="flex w-full items-center border-t border-line px-3 py-2 sm:w-auto sm:border-l sm:border-t-0">{children}</span>;
}
