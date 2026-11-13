"use client";

import { useEffect, useRef } from "react";
import { ProvenanceBadge } from "./ProvenanceBadge";
import { CaseBadges, CutoffLine, FailureNote, Hash, InFlight } from "./replay/ReplayParts";
import type { EvidenceState } from "./replay/hooks";
import { formatInstantUtc, type EvidenceItem, type ReplayCasePublic } from "@/lib/replay";

/**
 * Side drawer with the point-in-time evidence for one case (SPEC §2 "hover evidence", §5).
 *
 * Lists the case's `evidence_ids` as served by GET /api/cases. Full documents (source, timestamps, text, hash) come
 * only from GET /api/cases/{id}/evidence?as_of=<cutoff>; until that route exists each document is NOT AVAILABLE.
 * The browser never filters by date: a body with anything after the cutoff is refused whole (lib/replay.ts).
 *
 * Native <dialog>: Escape closes it, focus is contained while open and returns to the opener on close.
 */
export function EvidenceDrawer({
  open,
  onClose,
  replayCase,
  evidence,
  focusId,
}: {
  open: boolean;
  onClose: () => void;
  replayCase: ReplayCasePublic;
  evidence: EvidenceState;
  /** Evidence id to scroll to (e.g. a clicked citation). */
  focusId?: string | null;
}) {
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);

  useEffect(() => {
    if (!open || !focusId) return;
    const el = ref.current?.querySelector<HTMLElement>(`[data-evidence-id="${CSS.escape(focusId)}"]`);
    el?.scrollIntoView({ block: "start" });
  }, [open, focusId, evidence]);

  const served = evidence.kind === "done" && evidence.result.ok ? evidence.result.data : null;
  const byId = new Map<string, EvidenceItem>((served?.items ?? []).map((e) => [e.evidence_id, e]));
  // Ids the evidence route admitted that the case list did not name are shown too, flagged.
  const extraIds = (served?.items ?? []).map((e) => e.evidence_id).filter((id) => !replayCase.evidence_ids.includes(id));
  const ids = [...replayCase.evidence_ids, ...extraIds];

  return (
    <dialog
      ref={ref}
      onClose={onClose}
      onClick={(e) => {
        if (e.target === ref.current) onClose();
      }}
      aria-labelledby="evidence-drawer-title"
      className="fixed inset-y-0 left-auto right-0 m-0 h-dvh max-h-none w-full max-w-[640px] border-l border-line bg-elevated/95 p-0 text-text backdrop-blur-[12px] backdrop:bg-bg/60 backdrop:backdrop-blur-[2px]"
    >
      <div className="flex h-full flex-col">
        <header className="flex items-start justify-between gap-4 border-b border-line px-5 py-4">
          <div className="min-w-0">
            <p className="kicker">Evidence at cutoff</p>
            <h2 id="evidence-drawer-title" className="mt-1 text-base leading-snug text-text">
              {replayCase.title}
            </h2>
            <CutoffLine asOf={replayCase.as_of} className="mt-1 text-xs" />
            <div className="mt-2">
              <CaseBadges c={replayCase} />
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            autoFocus
            className="shrink-0 rounded-md border border-line-strong px-2.5 py-1.5 font-mono text-[11px] uppercase tracking-[0.14em] text-text-2 hover:border-accent hover:text-text"
          >
            Close <span className="sr-only">evidence drawer</span>
            <span aria-hidden="true"> · Esc</span>
          </button>
        </header>

        <div className="flex-1 overflow-y-auto px-5 py-4">
          <EvidenceSource evidence={evidence} />

          {ids.length === 0 ? (
            <p className="mt-4 font-mono text-sm uppercase tracking-[0.08em] text-muted">
              The case lists no evidence ids.
            </p>
          ) : (
            <ol className="mt-4 flex flex-col gap-3">
              {ids.map((id, i) => {
                const item = byId.get(id);
                const highlighted = id === focusId;
                return (
                  <li
                    key={id}
                    data-evidence-id={id}
                    className={`scroll-mt-4 rounded-md border px-4 py-3 ${highlighted ? "border-accent" : "border-line"}`}
                  >
                    <div className="flex flex-wrap items-baseline justify-between gap-2">
                      <p className="num text-xs text-text-2">
                        <span className="text-muted">[{i + 1}]</span> {id}
                      </p>
                      {item ? (
                        <span className="flex flex-wrap gap-1.5">
                          <ProvenanceBadge kind="AS-OF" />
                          <ProvenanceBadge kind={item.provenance} />
                        </span>
                      ) : (
                        <ProvenanceBadge kind="NOT AVAILABLE" />
                      )}
                    </div>
                    {extraIds.includes(id) ? (
                      <p className="mt-1 font-mono text-[11px] text-risk">
                        Served by the evidence route but not listed in the case record.
                      </p>
                    ) : null}
                    {item ? (
                      <EvidenceBody item={item} />
                    ) : (
                      <p className="mt-2 font-mono text-[11px] uppercase tracking-[0.1em] text-muted">
                        Document not available
                      </p>
                    )}
                  </li>
                );
              })}
            </ol>
          )}
        </div>
      </div>
    </dialog>
  );
}

function EvidenceSource({ evidence }: { evidence: EvidenceState }) {
  if (evidence.kind === "checking" || evidence.kind === "loading") {
    return <InFlight request={evidence.kind === "checking" ? "GET /openapi.json" : "GET /api/cases/{id}/evidence"} />;
  }
  if (evidence.kind === "absent") {
    return (
      <FailureNote
        size="sm"
        failure={evidence.failure}
        pendingIssue="SPEC §8; no issue yet"
        note="Ids below are from GET /api/cases. Titles, sources, timestamps and text need the evidence route."
      />
    );
  }
  if (evidence.kind === "done" && !evidence.result.ok) {
    return (
      <FailureNote
        size="sm"
        failure={evidence.result}
        pendingIssue="SPEC §8; no issue yet"
        note="Ids below are from GET /api/cases."
      />
    );
  }
  if (evidence.kind === "done" && evidence.result.ok) {
    const { notes, items } = evidence.result.data;
    return (
      <div className="flex flex-col gap-1">
        <p className="font-mono text-[11px] text-muted">
          <code className="text-text-2">{evidence.result.request}</code> · {items.length} admitted at the cutoff
        </p>
        {notes.map((n) => (
          <p key={n} className="text-xs text-muted">
            {n}
          </p>
        ))}
      </div>
    );
  }
  return null;
}

function EvidenceBody({ item }: { item: EvidenceItem }) {
  return (
    <div className="mt-2 flex flex-col gap-2">
      <a
        href={item.source_url}
        target="_blank"
        rel="noreferrer noopener"
        className="text-sm leading-snug text-text underline decoration-line-strong underline-offset-4 hover:text-link-hover"
      >
        {item.title}
      </a>
      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 font-mono text-[11px]">
        <dt className="text-muted">published</dt>
        <dd className="num text-text-2">{formatInstantUtc(item.published_at)}</dd>
        <dt className="text-muted">available</dt>
        <dd className="num text-text-2">{formatInstantUtc(item.available_at)}</dd>
        <dt className="text-muted">sha256</dt>
        <dd>
          <Hash value={item.content_sha256} />
        </dd>
        {item.archive_url ? (
          <>
            <dt className="text-muted">archive</dt>
            <dd className="min-w-0 truncate">
              <a href={item.archive_url} target="_blank" rel="noreferrer noopener" className="text-text-2 hover:text-link-hover">
                {item.archive_url}
              </a>
            </dd>
          </>
        ) : null}
      </dl>
      <p className="whitespace-pre-line text-xs leading-relaxed text-text-2">{item.content}</p>
    </div>
  );
}
