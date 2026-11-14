import type { EvidenceState } from "./hooks";
import m from "./motion.module.css";

/** core/temporal_gate.py exclusion reasons that mean "published or first available after the cutoff". */
const NOT_YET_PUBLIC = new Set(["available_after_as_of", "published_after_as_of"]);

const REASON_TEXT: Record<string, string> = {
  available_after_as_of: "first available after the cutoff",
  published_after_as_of: "published after the cutoff",
  retrospective_unverified: "no proof it existed by the cutoff",
  wrong_event: "belongs to another event",
  no_quote_within_24h_before_as_of: "no market quote in the 24 h before the cutoff",
};

/** At most this many sealed placeholders are drawn; the count itself is always the served number. */
const MAX_PLACEHOLDERS = 8;

/**
 * What the temporal gate withheld for this case, from the evidence route's `excluded_by_reason` counts. Counts only:
 * the API serves no id, title or text for an excluded item, and none is drawn. Each placeholder is a blank sealed
 * card. With no evidence response the counts are NOT AVAILABLE, never zero.
 */
export function NotYetPublic({ evidence, delayMs = 0 }: { evidence: EvidenceState; delayMs?: number }) {
  if (evidence.kind !== "done" || !evidence.result.ok) {
    return (
      <div className="flex flex-col gap-1" data-testid="not-yet-public">
        <p className="kicker">Not yet public at the cutoff</p>
        <p className="font-mono text-sm uppercase tracking-[0.08em] text-muted" data-testid="not-yet-public-count">
          Not available
        </p>
        <p className="font-mono text-[10px] text-muted">Counts come from GET /api/cases/{"{case_id}"}/evidence.</p>
      </div>
    );
  }
  const byReason = Object.entries(evidence.result.data.excluded_by_reason);
  const notYet = byReason.filter(([r]) => NOT_YET_PUBLIC.has(r)).reduce((n, [, k]) => n + k, 0);
  const other = byReason.filter(([r]) => !NOT_YET_PUBLIC.has(r));
  const placeholders = Math.min(notYet, MAX_PLACEHOLDERS);

  return (
    <div className="flex flex-col gap-3" data-testid="not-yet-public">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="kicker">Not yet public at the cutoff</p>
        <p className="font-mono text-[10px] uppercase tracking-[0.12em] text-muted">counts only · content not served</p>
      </div>
      <div className="flex items-baseline gap-3">
        <p className="num text-3xl font-medium leading-none text-text" data-testid="not-yet-public-count">
          {notYet}
        </p>
        <p className="text-xs leading-snug text-text-2">
          {notYet === 1 ? "item" : "items"} withheld by the temporal gate
          {notYet === 0 ? " (the case file holds nothing dated after its cutoff)" : ""}
        </p>
      </div>
      {placeholders > 0 ? (
        <ul className="grid grid-cols-2 gap-2 sm:grid-cols-4" aria-label="Sealed placeholders, one per withheld item">
          {Array.from({ length: placeholders }, (_, i) => (
            <li
              key={i}
              className={`hatch flex h-14 flex-col justify-between rounded-md border border-dashed border-risk/50 px-2.5 py-2 ${m.fadeUp}`}
              style={{ animationDelay: `${delayMs + i * 70}ms` }}
            >
              <span aria-hidden="true" className="font-mono text-[11px] text-risk">
                ■
              </span>
              <span className="font-mono text-[9px] uppercase tracking-[0.12em] text-risk">Sealed item</span>
            </li>
          ))}
        </ul>
      ) : null}
      {notYet > MAX_PLACEHOLDERS ? (
        <p className="font-mono text-[10px] text-muted">
          {MAX_PLACEHOLDERS} placeholders drawn for {notYet} withheld items.
        </p>
      ) : null}
      {byReason.length > 0 ? (
        <ul className="flex flex-col gap-0.5 font-mono text-[10px] text-muted" data-testid="excluded-by-reason">
          {byReason.map(([reason, n]) => (
            <li key={reason}>
              <span className="num text-text-2">{n}</span> · <code>{reason}</code>
              {REASON_TEXT[reason] ? ` (${REASON_TEXT[reason]})` : ""}
            </li>
          ))}
        </ul>
      ) : (
        <p className="font-mono text-[10px] text-muted">excluded_by_reason: empty (served)</p>
      )}
      {other.length > 0 ? (
        <p className="text-[11px] leading-relaxed text-muted">
          Other exclusions are listed by reason above and are not counted as &quot;not yet public&quot;.
        </p>
      ) : null}
    </div>
  );
}
