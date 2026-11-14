"use client";

import { floorOf, type SimulateResponse } from "@/lib/api";
import { usd, usdDelta, weekRanges } from "@/lib/format";
import { FinancialReadout } from "./FinancialReadout";
import type { ProvenanceInput } from "./ProvenanceBadge";

/**
 * Readout pieces shared by CASCADE C.2 and LIVE EXPLORE X.4 (#157, docs/FINANCE_REVIEW.md F2, F3, F18). Every
 * figure is a field of the API response; nothing here compares cash with the floor or finds a week.
 */

/** First week C_t < 0 (MATH_MODEL §3), worded as a week, not a duration (F3). */
export const CASH_NEGATIVE_SUBLABEL = "first week C_t < 0 (MATH_MODEL §3)";

/** "Minimum cash" sublabel: Δ vs baseline, then the §4.1 floor line from the API (F2). */
export function MinCashSublabel({ data }: { data: SimulateResponse }) {
  const floor = floorOf(data);
  return (
    <>
      <span className="block">
        {usdDelta(data.deltas.min_cash_delta)} vs baseline {usd(data.baseline.min_cash)}
      </span>
      <span className="block" data-testid="floor-line">
        {floor === null ? (
          <>floor NOT AVAILABLE (this API build does not report C_min)</>
        ) : floor.firstBelow === null ? (
          <>stays above the {usd(floor.floor)} floor</>
        ) : (
          <span className="text-risk">
            floor {usd(floor.floor)} · below it in week{floor.weeksBelow.length === 1 ? "" : "s"}{" "}
            {weekRanges(floor.weeksBelow)}
          </span>
        )}
      </span>
    </>
  );
}

/** "Cash goes negative": "in week 9" or "not within 26 weeks" (F3). */
export function CashNegativeReadout({
  data,
  provenance,
  dimmed,
}: {
  data: SimulateResponse | null;
  provenance: ProvenanceInput;
  dimmed: boolean;
}) {
  const r = data?.result ?? null;
  const b = data?.baseline ?? null;
  const baseline = b ? (b.runway_week === null ? `not within ${b.horizon_weeks} weeks` : `in week ${b.runway_week}`) : null;
  return (
    <FinancialReadout
      label="Cash goes negative"
      value={r ? (r.runway_week === null ? { above: r.horizon_weeks } : r.runway_week) : null}
      format="weeks"
      prefix="in week"
      aboveText={(T) => `not within ${T} weeks`}
      provenance={provenance}
      size="fit"
      dimmed={dimmed}
      sublabel={baseline ? `${CASH_NEGATIVE_SUBLABEL} · baseline: ${baseline}` : CASH_NEGATIVE_SUBLABEL}
    />
  );
}

/** Protect payroll "off" note with the served cap z̄ (F18); NOT AVAILABLE when the API did not send it. */
export function payrollOffNote(cap: number | null): string {
  if (cap === null) return "Off: payroll may be cut by up to z̄ a week (cap NOT AVAILABLE until POST /api/optimize answers)";
  return `Off: payroll may be cut by up to ${Number((cap * 100).toFixed(2))}% a week (z̄)`;
}
