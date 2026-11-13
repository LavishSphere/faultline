"use client";

import { settled, useHealth } from "./HealthProvider";

function Dot({ tone }: { tone: "viable" | "risk" | "fail" | "muted" }) {
  const color = {
    viable: "bg-viable",
    risk: "bg-risk",
    fail: "bg-fail",
    muted: "bg-muted",
  }[tone];
  return <span aria-hidden="true" className={`inline-block size-1.5 rounded-full ${color}`} />;
}

/** Header status chip driven only by `GET /api/health`. Click to re-check. */
export function HealthChip() {
  const { state, apiBase, recheck } = useHealth();
  const last = settled(state);
  const checking = state.kind === "checking";

  let api: { tone: "viable" | "fail" | "muted"; text: string };
  let model: { tone: "viable" | "risk" | "muted"; text: string } | null = null;
  let detail: string;

  if (!last) {
    api = { tone: "muted", text: "API checking" };
    detail = `Requesting ${apiBase}/api/health`;
  } else if (last.kind === "unreachable") {
    api = { tone: "fail", text: "API unavailable" };
    detail = `${apiBase}/api/health: ${last.error}`;
  } else {
    api = { tone: "viable", text: "API online" };
    const tags = last.health.modelTags;
    if (last.health.model === "available") {
      model = { tone: "viable", text: `Local model ready${tags[0] ? ` · ${tags[0]}` : ""}` };
    } else if (last.health.model === "unavailable") {
      model = { tone: "risk", text: "Local model unavailable" };
    } else {
      model = { tone: "muted", text: "Model status not reported" };
    }
    detail = `${apiBase}/api/health${last.health.status ? `: status ${last.health.status}` : ""}`;
  }

  return (
    <button
      type="button"
      onClick={recheck}
      title={`${detail}. Click to re-check.`}
      aria-label={`${api.text}${model ? `. ${model.text}` : ""}. Activate to re-check API status.`}
      className="group flex h-8 max-w-full items-center gap-0 overflow-hidden rounded-md border border-line bg-elevated/70 font-mono text-[10.5px] uppercase tracking-[0.1em] text-text-2 transition-colors hover:border-line-strong hover:bg-hover"
    >
      <span className="flex items-center gap-2 px-2.5 py-1.5" aria-live="polite">
        <Dot tone={api.tone} />
        <span className={api.tone === "fail" ? "text-fail" : undefined}>{api.text}</span>
      </span>
      {model ? (
        <span className="hidden items-center gap-2 border-l border-line px-2.5 py-1.5 sm:flex">
          <Dot tone={model.tone} />
          <span className={model.tone === "risk" ? "text-risk" : undefined}>{model.text}</span>
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
