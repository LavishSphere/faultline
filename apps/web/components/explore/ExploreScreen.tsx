import type { Step } from "@/lib/steps";
import { ScreenHeader } from "../screens/ScreenHeader";
import { ExploreWorkbench } from "./ExploreWorkbench";

/**
 * Screen F: LIVE EXPLORE (issue #61), the sixth step after RESEARCH. Current web research via Tavily, read by the local
 * model, confirmed by the human, computed by the deterministic engine. Separate from the Blind Replay.
 */
export function ExploreScreen({ step }: { step: Step }) {
  return (
    <div className="flex flex-col gap-8">
      <ScreenHeader
        step={step}
        aside={
          <p className="font-mono text-[11px] uppercase tracking-[0.14em] text-muted">
            Current web · not point-in-time · never given to the Blind Replay
          </p>
        }
      />
      <ExploreWorkbench />
    </div>
  );
}
