import { CascadeGraph } from "../CascadeGraph";
import { FinancialReadout } from "../FinancialReadout";
import { NotAvailable, Panel } from "../Panel";
import { ScreenHeader } from "./ScreenHeader";
import type { Step } from "@/lib/steps";

const CONTROLS = [
  { name: "Demand shock", unit: "%", note: "δ, MATH_MODEL §1" },
  { name: "Rate change", unit: "bp", note: "Δr, MATH_MODEL §1" },
  { name: "Supplier outage", unit: "weeks", note: "κ_t, MATH_MODEL §1" },
  { name: "Protect payroll", unit: "toggle", note: "z_t = 0, enforced in solver" },
] as const;

/** Screen C: THE CASCADE (SPEC §2). Dependency network, scenario controls, readouts, optimizer plan. */
export function CascadeScreen({ step }: { step: Step }) {
  return (
    <div className="flex flex-col gap-8">
      <ScreenHeader step={step} />

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-12">
        <Panel
          code="C.0"
          title="Dependency network"
          provenance="ILLUSTRATIVE"
          provenanceDetail="Structure only, no values"
          className="xl:col-span-8"
          bodyClassName="flex flex-col p-0"
        >
          <CascadeGraph className="flex-1" />
          <p className="border-t border-line px-4 py-2.5 text-xs leading-relaxed text-muted">
            Nodes and edges follow MATH_MODEL §2–§3. No magnitudes are shown: node Δ and edge emphasis (∝ |Δ|) will
            come only from <code className="font-mono text-text-2">POST /api/simulate</code>.
          </p>
        </Panel>

        <div className="flex flex-col gap-6 xl:col-span-4">
          <Panel code="C.1" title="Scenario inputs" provenance="NOT AVAILABLE">
            <ul className="flex flex-col">
              {CONTROLS.map((c) => (
                <li
                  key={c.name}
                  className="flex items-baseline justify-between gap-3 border-b border-line/70 py-2.5 last:border-b-0"
                >
                  <span className="text-sm font-medium uppercase tracking-[0.08em] text-text">{c.name}</span>
                  <span className="text-right font-mono text-[10.5px] tracking-[0.06em] text-muted">
                    {c.unit} · {c.note}
                  </span>
                </li>
              ))}
            </ul>
            <div className="mt-3">
              <NotAvailable
                size="sm"
                endpoint="simulate"
                note="Input controls are not built yet. Once /api/simulate is wired they will debounce (~150 ms) into /api/simulate and /api/optimize."
              />
            </div>
          </Panel>

          <Panel code="C.2" title="Financial readout" provenance="NOT AVAILABLE">
            <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 xl:grid-cols-1 2xl:grid-cols-2">
              <FinancialReadout
                label="Runway"
                value={null}
                format="weeks"
                unit="weeks"
                provenance="SIMULATED"
                size="md"
                sublabel="Reported as > T weeks if cash stays ≥ 0 over the horizon."
              />
              <FinancialReadout label="Minimum cash" value={null} format="usd" provenance="SIMULATED" size="md" />
              <FinancialReadout label="Interest cost" value={null} format="usd" provenance="SIMULATED" size="md" />
              <FinancialReadout label="Revolver peak" value={null} format="usd" provenance="SIMULATED" size="md" />
            </div>
          </Panel>

          <Panel code="C.3" title="Recovery plan" provenance="NOT AVAILABLE">
            <NotAvailable
              endpoint="optimize"
              note="Feasible actions from the deterministic MILP. An infeasible scenario will read NO FEASIBLE PLAN with the binding constraint named."
            />
          </Panel>
        </div>
      </div>
    </div>
  );
}
