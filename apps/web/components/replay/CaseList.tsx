"use client";

import { ProvenanceBadge } from "../ProvenanceBadge";
import { CaseBadges, FailureNote, InFlight, TextButton } from "./ReplayParts";
import type { Load } from "./hooks";
import { CASES_PATH, formatCutoffUtc, type CasesResponse, type ReplayCasePublic } from "@/lib/replay";

const CONTAMINATION: Record<ReplayCasePublic["contamination_flag"], string> = {
  likely: "Contamination risk: likely (event precedes the model's training cutoff)",
  unlikely: "Contamination risk: unlikely",
  unknown: "Contamination risk: unknown",
};

/**
 * Replay case picker from GET /api/cases. Each row shows exactly the served public fields; no outcome exists in
 * this payload (lib/replay.ts refuses one that carries an outcome-like key).
 */
export function CaseList({
  load,
  retry,
  selectedId,
  onSelect,
}: {
  load: Load<CasesResponse>;
  retry: () => void;
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  if (load.kind === "loading") return <InFlight request={`GET ${CASES_PATH}`} />;
  const { result } = load;
  if (!result.ok) {
    return (
      <FailureNote
        size="lg"
        failure={result}
        action={
          <TextButton onClick={retry}>
            Retry <span className="sr-only">loading replay cases</span>
          </TextButton>
        }
      />
    );
  }
  const { items, notes, status } = result.data;
  if (items.length === 0) {
    return (
      <div className="flex flex-col gap-2">
        <p className="font-mono text-2xl font-medium uppercase tracking-[0.08em] text-muted md:text-3xl">
          Not available
        </p>
        <p className="font-mono text-[11px] text-muted">
          <code className="text-text-2">GET {CASES_PATH}</code> → status {status}, 0 cases
        </p>
        {notes.map((n) => (
          <p key={n} className="text-xs leading-relaxed text-text-2">
            {n}
          </p>
        ))}
        <p className="text-xs leading-relaxed text-muted">
          Real resolved cases are pending #20; the explicitly synthetic fallback case is pending #48. Nothing is
          shown in their place.
        </p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      <p className="font-mono text-[11px] text-muted">
        <code className="text-text-2">GET {CASES_PATH}</code> · {items.length} {items.length === 1 ? "case" : "cases"}
      </p>
      <ul className="flex flex-col gap-2" aria-label="Replay cases">
        {items.map((c) => {
          const active = c.event_id === selectedId;
          return (
            <li key={c.event_id}>
              <button
                type="button"
                aria-pressed={active}
                onClick={() => onSelect(c.event_id)}
                className={`group flex w-full flex-col gap-2 rounded-md border px-4 py-3 text-left transition-colors ${
                  active ? "border-accent bg-accent-soft" : "border-line hover:border-line-strong hover:bg-hover"
                }`}
              >
                <span className="flex w-full flex-wrap items-start justify-between gap-2">
                  <span className="min-w-0 text-sm leading-snug text-text">{c.title}</span>
                  {active ? (
                    <span className="font-mono text-[10px] uppercase tracking-[0.14em] text-accent">Selected</span>
                  ) : null}
                </span>
                <span className="num text-xs text-text-2">
                  <span className="text-muted">Cutoff </span>
                  {formatCutoffUtc(c.as_of) ?? "not available"}
                  <span className="text-muted"> · horizon </span>
                  {c.horizon_days} d
                </span>
                <span className="flex flex-wrap items-center gap-1.5">
                  <CaseBadges c={c} />
                  <ProvenanceBadge kind="SEALED" detail="outcome" />
                </span>
                <span className="font-mono text-[10px] uppercase tracking-[0.1em] text-muted">
                  {c.event_id} · {CONTAMINATION[c.contamination_flag]}
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
