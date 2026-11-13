import { PENDING_ENDPOINTS } from "@/lib/api";
import { Field, Panel } from "./Panel";

/**
 * Forecast scorecard (SPEC §6, MATH_MODEL §6): Agent vs Market-only vs Naive baseline on identical
 * (event_id, as_of) pairs. Per-forecaster means come from GET /api/benchmark; uncertainty is ONE paired
 * bootstrap CI of mean Brier(agent) − mean Brier(market), not a per-row interval.
 * Display rules (MATH_MODEL §6): n < 5 → INSUFFICIENT DATA; 5 ≤ n < 30 → "small sample" caveat;
 * "agent better than market" only if the CI upper bound < 0, otherwise "No improvement measured".
 * With no computed benchmark, every slot is empty. No placeholder metrics, ever.
 */
const ROWS = ["Agent", "Market-only", "Naive baseline"] as const;
const COLS = ["Brier score", "Log loss", "Cases (n)"] as const;

export function Scorecard() {
  return (
    <Panel
      code="D.1"
      title="Scorecard"
      provenance="INSUFFICIENT DATA"
      provenanceDetail="No valid comparison"
      bodyClassName="p-0"
    >
      <div className="relative overflow-x-auto">
        <table className="w-full min-w-[440px] border-collapse text-left">
          <caption className="sr-only">
            Mean forecast scores for agent, market-only and naive baseline on the same cases. No benchmark has been
            computed, so every cell is not available.
          </caption>
          <thead>
            <tr className="border-b border-line">
              <th scope="col" className="px-5 py-3 font-mono text-[10.5px] font-normal uppercase tracking-[0.16em] text-muted">
                Forecaster
              </th>
              {COLS.map((c) => (
                <th
                  key={c}
                  scope="col"
                  className="px-5 py-3 text-right font-mono text-[10.5px] font-normal uppercase tracking-[0.16em] text-muted"
                >
                  {c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {ROWS.map((r) => (
              <tr key={r} className="border-b border-line/70 last:border-b-0">
                <th scope="row" className="px-5 py-4 text-base font-medium text-text">
                  {r}
                </th>
                {COLS.map((c) => (
                  <td key={c} className="num px-5 py-4 text-right text-lg text-muted">
                    <span aria-hidden="true">—</span>
                    <span className="sr-only">not available</span>
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <dl className="border-t border-line px-5 py-2">
        <Field label="Δ Brier vs market (paired bootstrap, 95% CI)" preserveCase />
        <Field label="Sample-size caveat (small sample if 5 ≤ n < 30)" preserveCase />
        <Field label="Exclusions by reason" preserveCase />
      </dl>

      <div className="flex flex-col gap-1 border-t border-line px-5 py-3 text-xs leading-relaxed text-muted">
        <p>
          Requires <code className="font-mono text-text-2">{PENDING_ENDPOINTS.benchmark}</code> (not wired). Lower Brier
          and log loss are better. Δ &lt; 0 favors the agent only if the whole interval is below zero; otherwise this
          reads &ldquo;No improvement measured&rdquo;.
        </p>
        <p>A single case is not evidence of general superiority.</p>
      </div>
    </Panel>
  );
}
