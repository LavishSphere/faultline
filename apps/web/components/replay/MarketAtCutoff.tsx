import { FinancialReadout } from "../FinancialReadout";
import { FailureNote, Hash, InFlight } from "./ReplayParts";
import type { EvidenceState } from "./hooks";
import { formatInstantUtc, type ReplayCasePublic } from "@/lib/replay";

/**
 * B.2: the market-implied probability at the cutoff (SPEC §2 Screen B, MATH_MODEL §7). Shown only when the API
 * serves the case's as-of quote (`MarketQuoteRef`, stamped at or before the cutoff). It is price-derived and affected
 * by fees, spread and liquidity: never presented as a "true probability".
 */
export function MarketAtCutoff({ c, evidence }: { c: ReplayCasePublic | null; evidence: EvidenceState }) {
  if (!c) {
    return <FinancialReadout label="Market-implied (price-derived)" value={null} format="probability" provenance="AS-OF" />;
  }
  if (c.market_quote_id === null) {
    return (
      <div className="flex flex-col gap-3">
        <FinancialReadout label="Market-implied (price-derived)" value={null} format="probability" provenance="AS-OF" />
        <p className="text-xs leading-relaxed text-muted">
          This case has no market quote demonstrably available at the cutoff (<code>market_quote_id</code> is null),
          so none is shown.
        </p>
      </div>
    );
  }

  const quote =
    evidence.kind === "done" && evidence.result.ok
      ? (evidence.result.data.market_quotes.find((q) => q.quote_id === c.market_quote_id) ?? null)
      : null;

  if (!quote) {
    return (
      <div className="flex flex-col gap-3">
        <FinancialReadout label="Market-implied (price-derived)" value={null} format="probability" provenance="AS-OF" />
        <p className="num break-all text-[11px] text-text-2">
          <span className="text-muted">Quote id </span>
          {c.market_quote_id}
        </p>
        {evidence.kind === "checking" || evidence.kind === "loading" ? (
          <InFlight request="GET /api/cases/{id}/evidence" />
        ) : evidence.kind === "absent" ? (
          <FailureNote
            size="sm"
            failure={evidence.failure}
            pendingIssue="SPEC §8; no issue yet"
            note="The quote value is not in GET /api/cases; it needs the evidence route's market_quotes."
          />
        ) : evidence.kind === "done" && !evidence.result.ok ? (
          <FailureNote size="sm" failure={evidence.result} pendingIssue="SPEC §8; no issue yet" />
        ) : (
          <p className="text-xs text-muted">The evidence route did not include this quote id.</p>
        )}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <FinancialReadout
        label="Market-implied (price-derived)"
        value={quote.p_yes}
        format="probability"
        provenance={quote.provenance}
        sublabel={quote.label}
      />
      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 font-mono text-[11px]">
        <dt className="text-muted">venue</dt>
        <dd className="text-text-2">
          {quote.venue} · {quote.market_id}
        </dd>
        <dt className="text-muted">quote</dt>
        <dd className="num text-text-2">
          {quote.quote_kind} · {formatInstantUtc(quote.ts)}
        </dd>
        <dt className="text-muted">raw sha256</dt>
        <dd>
          <Hash value={quote.raw_payload_sha256} />
        </dd>
      </dl>
      <p className="text-[11px] leading-relaxed text-muted">Not a true probability.</p>
    </div>
  );
}
