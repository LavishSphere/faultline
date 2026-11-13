import { ThesisCourt } from "../ThesisCourt";
import { ScreenHeader } from "./ScreenHeader";
import type { Step } from "@/lib/steps";

/** Screen E: RESEARCH LENS (SPEC §2, §7). Dated public research as context, not VC predictions. */
export function ResearchScreen({ step }: { step: Step }) {
  return (
    <div className="flex flex-col gap-8">
      <ScreenHeader
        step={step}
        aside={
          <p className="font-mono text-[11px] uppercase tracking-[0.14em] text-muted">
            Research context · not VC predictions · no competitive score
          </p>
        }
      />
      <ThesisCourt />
      <p className="max-w-3xl text-xs leading-relaxed text-muted">
        Public articles and portfolio pages are evidence and thesis context, not records of private investment
        decisions or returns. In point-in-time mode the API returns only sources provably public at the cutoff you
        enter; the browser does not filter, rank or score them. Quote kinds separate documentary fact, analyst
        interpretation and quantitative forecast; none is scored against the firms.
      </p>
    </div>
  );
}
