"use client";

import { ProvenanceBadge } from "./ProvenanceBadge";
import { useReplayCases, useSelectedCase } from "./replay/hooks";

/**
 * Header "Case" chip (#157, FINANCE_REVIEW F1): the case selected on REWIND / DECISION (shared selection), read
 * from GET /api/cases. Shows the served event id and the case's own provenance (REAL HISTORICAL or SYNTHETIC);
 * NOT AVAILABLE only when no case is selected, or the case list did not load.
 */
export function HeaderCase() {
  const { load } = useReplayCases();
  const { selected, cases } = useSelectedCase(load);

  let body;
  if (load.kind === "loading") {
    body = <span className="font-mono text-[11px] text-muted">GET /api/cases…</span>;
  } else if (!load.result.ok) {
    body = <ProvenanceBadge kind="NOT AVAILABLE" detail="Cases did not load" />;
  } else if (cases.length === 0) {
    body = <ProvenanceBadge kind="NOT AVAILABLE" detail="No case served" />;
  } else if (!selected) {
    body = <ProvenanceBadge kind="NOT AVAILABLE" detail="No case selected" />;
  } else {
    body = (
      <>
        <span className="num truncate font-mono text-[11px] text-text-2" data-testid="header-case-id" title={selected.title}>
          {selected.event_id}
        </span>
        <ProvenanceBadge kind={selected.provenance} />
      </>
    );
  }
  return (
    <div className="hidden min-w-0 items-center gap-2 md:flex" data-testid="header-case">
      <span className="kicker">Case</span>
      {body}
    </div>
  );
}
