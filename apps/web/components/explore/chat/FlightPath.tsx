"use client";

import { useId, useState } from "react";
import type { ChatToolCall } from "@/lib/chat";
import { WireBadge } from "./ChatBadges";
import "./flight.css";

/**
 * "Flight path" (stage 2): the steps the model took, as waypoints on a path drawn from one tool call to the next, in
 * the order the server ran them. It is revealed once the reply has landed: a record of what happened, not a live feed
 * (POST /api/explore/chat is not streaming), and the caption says so. Each waypoint expands to the exact input the
 * model sent and the server's result summary, shown verbatim. The narrative is built only from the tool names and
 * their inputs; nothing here reads, derives or rounds a number.
 */

const LIST_PHRASES: Record<string, string> = {
  list_scenarios: "listed scenarios",
  list_judge_challenges: "listed judge challenges",
  list_decision_frames: "listed decision frames",
  prediction_markets: "checked prediction markets",
  monte_carlo_decision: "ran a Monte Carlo of the decision",
  monte_carlo_cash: "ran a Monte Carlo of cash",
  query_internal_data: "queried the mock internal data",
};

/** A scalar input value as given (strings trimmed and shortened for the sentence only), or null. */
function given(v: unknown, max = 60): string | null {
  if (typeof v === "string") {
    const s = v.trim();
    if (!s) return null;
    return s.length > max ? `${s.slice(0, max - 1)}…` : s;
  }
  if (typeof v === "number" && Number.isFinite(v)) return String(v);
  if (typeof v === "boolean") return String(v);
  return null;
}

function shockPhrase(input: Record<string, unknown>): string {
  const sid = given(input.scenario_id);
  if (sid) return ` for ${sid}`;
  const shock = input.shock;
  if (shock && typeof shock === "object" && !Array.isArray(shock)) {
    const name = given((shock as Record<string, unknown>).name);
    return name ? ` for ${name}` : " for a custom shock";
  }
  return "";
}

/** Plain-language label for one step, from its name and input only. */
export function stepPhrase(call: ChatToolCall): string {
  const input = call.input ?? {};
  let phrase: string;
  switch (call.name) {
    case "simulate":
      phrase = `asked simulate${shockPhrase(input)}`;
      break;
    case "optimize": {
      const p = input.protect_payroll;
      const protect = p === true ? " with payroll protected" : p === false ? " without payroll protection" : "";
      phrase = `asked optimize${shockPhrase(input)}${protect}`;
      break;
    }
    case "decision": {
      const frame = given(input.frame_id);
      const p = given(input.p_yes);
      phrase = `asked decision${frame ? ` for ${frame}` : ""}${p ? ` at p_yes ${p}` : ""}`;
      break;
    }
    case "web_search": {
      const q = given(input.query, 48);
      phrase = `searched the web${q ? ` for “${q}”` : ""}`;
      break;
    }
    case "vc_lenses": {
      const asOf = given(input.as_of);
      phrase = `read the VC research lenses${asOf ? ` as of ${asOf}` : ""}`;
      break;
    }
    default:
      phrase = LIST_PHRASES[call.name] ?? `asked ${call.name}`;
  }
  return call.result_status === "ok" ? phrase : `${phrase} (failed)`;
}

/** "asked simulate → asked optimize with payroll protected". */
export function flightNarrative(calls: readonly ChatToolCall[]): string {
  return calls.map(stepPhrase).join(" → ");
}

function Summary({ value }: { value: ChatToolCall["result_summary"] }) {
  if (typeof value === "string" && value.trim()) {
    return (
      <p className="whitespace-pre-wrap break-words text-[13px] leading-relaxed text-text-2 [overflow-wrap:anywhere]">{value}</p>
    );
  }
  if (value && typeof value === "object" && Object.keys(value).length > 0) {
    // The engine's numbers exactly as the server sent them; shown verbatim, never recomputed.
    return (
      <pre className="max-h-72 overflow-auto whitespace-pre-wrap break-all font-mono text-[11px] leading-relaxed text-text-2">
        {JSON.stringify(value, null, 2)}
      </pre>
    );
  }
  return <p className="font-mono text-[11px] uppercase tracking-[0.12em] text-muted">Not available</p>;
}

export function FlightPath({ calls, reduce }: { calls: readonly ChatToolCall[]; reduce: boolean }) {
  const [open, setOpen] = useState<number | null>(null);
  const panelId = useId();
  if (calls.length === 0) {
    return (
      <p className="font-mono text-[11px] uppercase tracking-[0.12em] text-muted" data-testid="chat-no-tools">
        No engine tools used in this reply: it contains no engine numbers.
      </p>
    );
  }
  const current = open !== null ? calls[open] : undefined;
  const failed = calls.filter((c) => c.result_status !== "ok").length;
  return (
    <div className="flight flex min-w-0 flex-col gap-3" data-testid="chat-tools">
      <div className="flex min-w-0 flex-col gap-1">
        <p className="flex min-w-0 flex-wrap items-baseline gap-x-3 gap-y-1">
          <span className="kicker !text-text-2">Flight path · steps the model took</span>
          <span className="font-mono text-[10.5px] text-muted">
            {calls.length} step{calls.length === 1 ? "" : "s"}
            {failed ? ` · ${failed} failed` : ""} · shown after the reply, not live
          </span>
        </p>
        <p
          className={`min-w-0 break-words text-[14px] leading-snug text-text [overflow-wrap:anywhere] md:text-[15px] ${reduce ? "" : "flight-fade"}`}
          data-testid="chat-flight-narrative"
        >
          {flightNarrative(calls)}
        </p>
      </div>

      <ol className="flight-path flex min-w-0 flex-col md:flex-row md:flex-wrap md:items-stretch md:gap-y-3" aria-label="Steps the model took, in order">
        {calls.map((c, i) => {
          const ok = c.result_status === "ok";
          const isOpen = open === i;
          const delay = reduce ? undefined : { animationDelay: `${140 + i * 220}ms` };
          return (
            <li key={`${c.name}-${i}`} className="flex min-w-0 max-w-full flex-col md:flex-row md:items-center">
              {i > 0 ? (
                <span aria-hidden="true" className="flight-link-wrap">
                  <span
                    className={`flight-link ${ok ? "" : "flight-link-fail"} ${reduce ? "" : "flight-link-draw"}`}
                    style={reduce ? undefined : { animationDelay: `${i * 220}ms` }}
                  />
                </span>
              ) : null}
              <button
                type="button"
                onClick={() => setOpen(isOpen ? null : i)}
                aria-expanded={isOpen}
                aria-controls={panelId}
                data-testid="chat-tool-chip"
                data-tool={c.name}
                data-status={c.result_status}
                className={`flight-waypoint group flex min-w-0 max-w-full items-start gap-2.5 rounded-lg border px-3 py-2 text-left transition-[border-color,background-color] duration-150 hover:bg-hover md:max-w-[22rem] ${
                  isOpen ? "border-accent bg-accent-soft" : ok ? "border-line-strong bg-bg/40" : "border-fail/60 bg-bg/40"
                } ${reduce ? "" : "flight-in"}`}
                style={delay}
              >
                <span
                  aria-hidden="true"
                  className={`flight-dot mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-full border font-mono text-[10px] ${
                    ok ? "border-viable/70 text-viable" : "border-fail/70 text-fail"
                  } ${reduce ? "" : "flight-dot-pulse"}`}
                  style={delay}
                >
                  {String(i + 1).padStart(2, "0")}
                </span>
                <span className="flex min-w-0 flex-col gap-1">
                  <span className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
                    <span className="sr-only">Step {i + 1}:</span>
                    <span className="min-w-0 break-all font-mono text-[12.5px] font-medium text-text">{c.name}</span>
                    <span className={`font-mono text-[10px] uppercase tracking-[0.12em] ${ok ? "text-viable" : "text-fail"}`}>
                      <span aria-hidden="true">{ok ? "✓ " : "✕ "}</span>
                      {c.result_status}
                    </span>
                    <WireBadge value={c.provenance} />
                  </span>
                  <span className="min-w-0 break-words text-[12.5px] leading-snug text-text-2 [overflow-wrap:anywhere]">
                    {stepPhrase(c)}
                  </span>
                </span>
                <span aria-hidden="true" className="ml-auto self-center font-mono text-[10px] text-muted group-hover:text-text-2">
                  {isOpen ? "▴" : "▾"}
                </span>
              </button>
            </li>
          );
        })}
      </ol>

      <div id={panelId} role="region" aria-label="Tool call details" hidden={current === undefined}>
        {current ? (
          <div
            className={`grid min-w-0 grid-cols-1 gap-3 rounded-lg border border-line bg-bg/60 p-3 lg:grid-cols-2 ${reduce ? "" : "flight-fade"}`}
            data-testid="chat-tool-detail"
          >
            <div className="min-w-0">
              <p className="kicker mb-1 [overflow-wrap:anywhere]">Input the model sent to {current.name}</p>
              <pre className="max-h-72 overflow-auto whitespace-pre-wrap break-all font-mono text-[11px] leading-relaxed text-text-2">
                {JSON.stringify(current.input, null, 2)}
              </pre>
            </div>
            <div className="min-w-0">
              <p className="kicker mb-1">Result summary from the server</p>
              <Summary value={current.result_summary} />
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}
