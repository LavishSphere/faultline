import { NotAvailable, Panel } from "../Panel";
import { Scorecard } from "../Scorecard";
import { ScreenHeader } from "./ScreenHeader";
import type { Step } from "@/lib/steps";

/** Screen D: REVEAL (SPEC §2, §6). Unseal the outcome only after a prediction is persisted; score honestly. */
export function RevealScreen({ step }: { step: Step }) {
  return (
    <div className="flex flex-col gap-8">
      <ScreenHeader step={step} />

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-12">
        <Panel code="D.0" title="Historical outcome" provenance="NOT AVAILABLE" className="xl:col-span-4">
          <NotAvailable
            size="lg"
            endpoint="reveal"
            note="The outcome unlocks only after the agent's prediction has been persisted. Until then it stays sealed server-side."
          />
          <button
            type="button"
            disabled
            aria-describedby="reveal-disabled-reason"
            className="mt-6 w-full cursor-not-allowed rounded-md border border-dashed border-line-strong px-4 py-3 font-mono text-sm uppercase tracking-[0.18em] text-muted"
          >
            Reveal outcome
          </button>
          <p id="reveal-disabled-reason" className="mt-2 font-mono text-[11px] text-muted">
            Disabled: no persisted prediction.
          </p>
        </Panel>

        <div className="min-w-0 xl:col-span-8">
          <Scorecard />
        </div>
      </div>
    </div>
  );
}
