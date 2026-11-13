import { NotAvailable, Panel } from "../Panel";
import { ProvenanceBadge } from "../ProvenanceBadge";
import { ScreenHeader } from "./ScreenHeader";
import type { Step } from "@/lib/steps";

/** Screen A: REWIND (SPEC §2). Case list, knowledge cutoff, point-in-time evidence, sealed future. */
export function RewindScreen({ step }: { step: Step }) {
  return (
    <div className="flex flex-col gap-8">
      <ScreenHeader step={step} />

      {/* Historical timeline strip: structure only until a case supplies dates. */}
      <section aria-labelledby="rewind-timeline" className="overflow-hidden rounded-lg border border-line bg-elevated">
        <div className="flex min-h-11 flex-wrap items-center justify-between gap-2 border-b border-line px-5 py-2.5">
          <h2 id="rewind-timeline" className="font-mono text-[11px] uppercase tracking-[0.14em] text-text-2">
            <span className="text-muted">A.0</span> Historical timeline
          </h2>
          <ProvenanceBadge kind="NOT AVAILABLE" detail="No case loaded" />
        </div>
        <div className="grid grid-cols-[3fr_2fr] md:grid-cols-[2fr_1fr]">
          <div className="relative px-5 py-6">
            <p className="kicker">Known by cutoff</p>
            <div className="mt-4 h-px bg-line-strong" aria-hidden="true" />
            <p className="mt-3 font-mono text-[11px] uppercase tracking-[0.12em] text-muted">Dates not available</p>
          </div>
          <div className="hatch relative border-l border-risk/70 px-5 py-6">
            <span
              aria-hidden="true"
              className="absolute -left-[4.5px] top-[2.9rem] size-2 rounded-full border border-risk bg-bg"
            />
            <p className="kicker text-risk">Sealed future</p>
            <div className="mt-4 h-px bg-risk/40" aria-hidden="true" />
            <p className="mt-3 font-mono text-[11px] uppercase tracking-[0.12em] text-risk">Withheld until reveal</p>
          </div>
        </div>
      </section>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-12">
        <Panel code="A.1" title="Replay cases" provenance="NOT AVAILABLE" className="xl:col-span-4">
          <NotAvailable
            size="lg"
            endpoint="cases"
            note="Pre-verified, resolved historical cases plus one explicitly synthetic fallback will be listed here. Pre-reveal case data never includes the outcome."
          />
        </Panel>

        <Panel code="A.2" title="Known by cutoff" provenance="NOT AVAILABLE" className="xl:col-span-5">
          <NotAvailable
            size="lg"
            endpoint="evidence"
            note="Only evidence with available_at ≤ as_of is listed, each with its source and timestamp."
          />
        </Panel>

        <div className="flex flex-col gap-6 xl:col-span-3">
          <Panel code="A.3" title="Knowledge cutoff" provenance="NOT AVAILABLE">
            <p className="kicker">As-of (UTC)</p>
            <p className="num mt-2 text-2xl font-medium uppercase tracking-[0.04em] text-muted md:text-3xl">
              Not available
            </p>
            <p className="mt-2 text-xs text-muted">Set by the selected case.</p>
          </Panel>

          <Panel code="A.4" title="Sealed future" provenance="NOT AVAILABLE" bodyClassName="hatch">
            <div className="flex items-center gap-3">
              <span aria-hidden="true" className="inline-block size-3 rounded-sm border border-risk bg-risk/30" />
              <p className="font-mono text-lg uppercase tracking-[0.14em] text-risk">Sealed future</p>
            </div>
            <p className="mt-3 text-xs leading-relaxed text-text-2">
              The outcome is withheld from agent input and from every pre-reveal endpoint. Seal status for a case is
              reported by the API.
            </p>
            <p className="mt-2 font-mono text-[11px] uppercase tracking-[0.12em] text-muted">
              Seal status: not available (no case loaded)
            </p>
          </Panel>
        </div>
      </div>
    </div>
  );
}
