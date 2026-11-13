import { DecisionBranches } from "../DecisionBranches";
import { FinancialReadout } from "../FinancialReadout";
import { IntegrityPanel } from "../integrity/IntegrityPanel";
import { ModelStatus } from "../ModelStatus";
import { NotAvailable, Panel } from "../Panel";
import { ScreenHeader } from "./ScreenHeader";
import { PENDING_ENDPOINTS } from "@/lib/api";
import type { Step } from "@/lib/steps";

/** Screen B: THE DECISION (SPEC §2). Local-model decision, probability, citations, market-implied probability. */
export function DecisionScreen({ step }: { step: Step }) {
  return (
    <div className="flex flex-col gap-8">
      <ScreenHeader step={step} />

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-12">
        <Panel code="B.0" title="Agent decision" provenance="NOT AVAILABLE" className="xl:col-span-5">
          <ModelStatus />
          <div className="mt-6 border-t border-line pt-5">
            <p className="kicker">Chosen path</p>
            <div className="mt-2">
              <NotAvailable
                size="lg"
                endpoint="replayRun"
                note="A real local run, or a cached run labeled RECORDED RUN with prompt and snapshot hashes. Never a canned response."
              />
            </div>
          </div>
        </Panel>

        <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 xl:col-span-7">
          <Panel code="B.1" title="Agent probability" provenance="NOT AVAILABLE">
            <FinancialReadout label="P(event) · forecast" value={null} format="probability" provenance="FORECAST" />
            <p className="mt-3 font-mono text-[11px] text-muted">
              Requires {PENDING_ENDPOINTS.replayRun} (not wired)
            </p>
          </Panel>
          <Panel code="B.2" title="Market at cutoff" provenance="NOT AVAILABLE">
            <FinancialReadout
              label="Market-implied (price-derived)"
              value={null}
              format="probability"
              provenance="AS-OF"
            />
            <p className="mt-3 text-xs leading-relaxed text-muted">
              Shown only when a historical quote at the cutoff is demonstrably sourced.
            </p>
          </Panel>

          <Panel code="B.3" title="Evidence citations" provenance="NOT AVAILABLE" className="sm:col-span-2">
            <ol className="flex flex-col">
              {[1, 2, 3].map((i) => (
                <li key={i} className="flex items-baseline gap-4 border-b border-line/70 py-2.5 last:border-b-0">
                  <span className="num text-xs text-muted">[{i}]</span>
                  <span className="font-mono text-sm uppercase tracking-[0.08em] text-muted">Not available</span>
                </li>
              ))}
            </ol>
            <p className="mt-2 font-mono text-[11px] text-muted">
              Citations come from the run&apos;s point-in-time evidence (available_at ≤ as_of).
            </p>
          </Panel>
        </div>
      </div>

      <section aria-labelledby="branches-heading" className="flex flex-col gap-3">
        <h2 id="branches-heading" className="kicker">
          Alternative strategies
        </h2>
        <DecisionBranches />
      </section>

      <IntegrityPanel code="B.4" />
    </div>
  );
}
