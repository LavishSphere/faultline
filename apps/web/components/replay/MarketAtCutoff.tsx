import { FinancialReadout } from "../FinancialReadout";
import { FailureNote, InFlight } from "./ReplayParts";
import type { EvidenceState } from "./hooks";
import {
  EVIDENCE_PATH_TEMPLATE,
  REPLAY_RUN_PATH,
  formatInstantUtc,
  isSyntheticQuote,
  type MarketAtCutoff as MarketAtCutoffBody,
  type ReplayCasePublic,
  type ReplayRun,
} from "@/lib/replay";

/** Neutral kicker: what the figure is for. What the price IS comes from the API's own `label`, shown verbatim (#117). */
const KICKER = "Market baseline · P(YES)";

/** Where B.2's value comes from: the run's fixed scoring baseline when there is a run, else the evidence route. */
export function marketSource(
  run: ReplayRun | null,
  evidence: EvidenceState,
): { market: MarketAtCutoffBody; from: string } | null {
  if (run) return { market: run.market_at_cutoff, from: `POST ${REPLAY_RUN_PATH}` };
  if (evidence.kind === "done" && evidence.result.ok) {
    return { market: evidence.result.data.market_at_cutoff, from: evidence.result.request };
  }
  return null;
}

/** Panel badges for the market value: AS-OF plus the quote's served provenance; SYNTHETIC for any synthetic price. */
export function marketBadges(c: ReplayCasePublic | null, run: ReplayRun | null, evidence: EvidenceState) {
  const m = c ? marketSource(run, evidence)?.market : undefined;
  if (!m || m.status !== "AVAILABLE") return "NOT AVAILABLE" as const;
  if (isSyntheticQuote(m, c)) return ["AS-OF", "SYNTHETIC"] as const;
  return m.provenance ? (["AS-OF", m.provenance] as const) : ("AS-OF" as const);
}

/**
 * B.2: the market-implied probability at the cutoff (SPEC §2 Screen B, MATH_MODEL §7), exactly as the API's
 * `market_at_cutoff` serves it (routes/cases.py `MarketAtCutoff`, the gate's fixed rule). After a run it is the run's
 * own baseline, fixed when the forecast was saved. Price-derived and affected by fees, spread and liquidity: never
 * presented as a "true probability". NOT AVAILABLE shows the server's note verbatim.
 */
export function MarketAtCutoff({
  c,
  run,
  evidence,
}: {
  c: ReplayCasePublic | null;
  run: ReplayRun | null;
  evidence: EvidenceState;
}) {
  const empty = <FinancialReadout label={KICKER} value={null} format="probability" provenance="AS-OF" />;
  if (!c) return empty;

  const source = marketSource(run, evidence);
  if (!source) {
    return (
      <div className="flex flex-col gap-3">
        {empty}
        {evidence.kind === "checking" || evidence.kind === "loading" ? (
          <InFlight request={evidence.kind === "checking" ? "GET /openapi.json" : `GET ${EVIDENCE_PATH_TEMPLATE}`} />
        ) : evidence.kind === "absent" ? (
          <FailureNote size="sm" failure={evidence.failure} note="The market value comes from the evidence route." />
        ) : evidence.kind === "done" && !evidence.result.ok ? (
          <FailureNote size="sm" failure={evidence.result} />
        ) : null}
      </div>
    );
  }

  const { market, from } = source;
  if (market.status !== "AVAILABLE" || market.p_yes === null) {
    return (
      <div className="flex flex-col gap-3">
        {empty}
        {market.note ? <p className="text-xs leading-relaxed text-text-2">{market.note}</p> : null}
        <p className="font-mono text-[11px] text-muted">
          <code className="text-text-2">{from}</code> · market_at_cutoff.status = NOT AVAILABLE
        </p>
      </div>
    );
  }

  // A synthetic benchmark price (PR #111), or any quote on a synthetic case, is never presented as a real market:
  // SYNTHETIC badge, the server's label verbatim, and no raw payload to point to.
  const synthetic = isSyntheticQuote(market, c);
  return (
    <div className="flex flex-col gap-3" data-testid="market-at-cutoff">
      <FinancialReadout
        label={KICKER}
        value={market.p_yes}
        format="probability"
        provenance={synthetic ? "SYNTHETIC" : (market.provenance ?? "AS-OF")}
        sublabel={market.label}
      />
      {synthetic ? (
        <p className="font-mono text-[11px] uppercase tracking-[0.1em] text-risk">
          {market.venue === "synthetic"
            ? "Synthetic price written by the case author. Not a real market."
            : "Synthetic case: this quote is part of a fictional case, not a real market."}
        </p>
      ) : null}
      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 font-mono text-[11px]">
        <dt className="text-muted">{market.venue === "synthetic" ? "price id" : "market"}</dt>
        <dd className="break-all text-text-2">{market.ref}</dd>
        {market.venue === "synthetic" ? (
          <>
            <dt className="text-muted">raw payload</dt>
            <dd className="text-text-2">no raw payload (synthetic)</dd>
          </>
        ) : null}
        <dt className="text-muted">quote</dt>
        <dd className="num text-text-2">
          {market.quote_kind} · {market.ts ? formatInstantUtc(market.ts) : "NOT AVAILABLE"}
        </dd>
        <dt className="text-muted">source</dt>
        <dd className="break-all text-text-2">
          {from}
          {run ? " · baseline fixed when the forecast was saved" : ""}
        </dd>
      </dl>
    </div>
  );
}
