"use client";

import { usePathname } from "next/navigation";
import { describeModelStatus } from "@/lib/api";
import { describeChatChip } from "@/lib/chat";
import { useChatPresence } from "@/lib/chatPresence";
import { stepFromPath } from "@/lib/steps";
import { settled, useHealth } from "./HealthProvider";

function Dot({ tone }: { tone: "viable" | "risk" | "fail" | "info" | "muted" }) {
  const color = {
    viable: "bg-viable",
    risk: "bg-risk",
    fail: "bg-fail",
    info: "bg-info",
    muted: "bg-muted",
  }[tone];
  return <span aria-hidden="true" className={`inline-block size-1.5 rounded-full ${color}`} />;
}

/**
 * Header status chip. The API half is `GET /api/health`. The second half depends on the page: on Explore (`/`) it is
 * the live chat's own `GET /api/explore/chat/models` + `/status` results (shared by ChatPanel, never re-fetched here,
 * #236); on the Blind Replay pages it is the replay model status from health. Click to re-check both.
 */
export function HealthChip() {
  const { state, apiBase, recheck } = useHealth();
  const chat = useChatPresence();
  const onExplore = stepFromPath(usePathname() ?? "/")?.slug === "explore";
  const last = settled(state);
  const checking = state.kind === "checking";

  let api: { tone: "viable" | "fail" | "muted"; text: string };
  let model: { tone: "viable" | "risk" | "info" | "muted"; text: string } | null = null;
  let detail: string;
  /** The health line alone, without the replay model explanation (used on Explore). */
  let healthLine: string;

  if (!last) {
    api = { tone: "muted", text: "API checking" };
    detail = healthLine = `Requesting ${apiBase}/api/health`;
  } else if (last.kind === "unreachable") {
    api = { tone: "fail", text: "API unavailable" };
    detail = healthLine = `${apiBase}/api/health: ${last.error}`;
  } else {
    api = { tone: "viable", text: "API online" };
    // Readiness is the API's own `model_ready` (lib/api.ts summarizeHealth, #163); the name is the configured model.
    // On the public server (X-Faultline-Mode: public) no model runs by design, so the chip says so instead of
    // reading as broken (#184).
    const view = describeModelStatus(last.health);
    model = { tone: view.tone, text: view.chip };
    const base = (healthLine = `${apiBase}/api/health${last.health.status ? `: status ${last.health.status}` : ""}`);
    detail = last.health.serverMode === "public" ? `${view.explain} (${base})` : base;
  }

  // On Explore the replay model status is beside the point (the chat is a separate, live route): say what the chat
  // routes said instead, and never "live" unless the models route answered with an available model.
  if (onExplore) {
    const view = describeChatChip(chat.models, chat.paused);
    model = { tone: view.tone, text: view.chip };
    detail = `${healthLine}. ${view.explain}`;
  }

  return (
    <button
      type="button"
      onClick={() => {
        recheck();
        if (onExplore) chat.recheck?.();
      }}
      title={`${detail}. Click to re-check.`}
      aria-label={`${api.text}${model ? `. ${model.text}` : ""}. Activate to re-check API status.`}
      className="group flex h-8 max-w-full items-center gap-0 overflow-hidden rounded-md border border-line bg-elevated/70 font-mono text-[10.5px] uppercase tracking-[0.1em] text-text-2 transition-colors hover:border-line-strong hover:bg-hover"
    >
      <span className="flex items-center gap-2 px-2.5 py-1.5" aria-live="polite">
        <Dot tone={api.tone} />
        <span className={api.tone === "fail" ? "text-fail" : undefined}>{api.text}</span>
      </span>
      {model ? (
        <span className="hidden items-center gap-2 border-l border-line px-2.5 py-1.5 sm:flex" data-testid="health-chip-model">
          <Dot tone={model.tone} />
          <span className={model.tone === "risk" ? "text-risk" : model.tone === "info" ? "text-info" : undefined}>
            {model.text}
          </span>
        </span>
      ) : null}
      <span
        className="border-l border-line px-2 py-1.5 text-muted group-hover:text-text"
        aria-hidden="true"
      >
        {checking ? "···" : "↻"}
      </span>
    </button>
  );
}
