import type { Step } from "@/lib/steps";
import { ScreenHeader } from "../screens/ScreenHeader";
import { ChatPanel } from "./chat/ChatPanel";
import { ExploreWorkbench } from "./ExploreWorkbench";

/**
 * Screen F: LIVE EXPLORE (issue #61), the home screen `/` and the first step, before the Blind Replay. Current web
 * research via Tavily, read by the local model, confirmed by the human, computed by the deterministic engine.
 * Separate from the Blind Replay.
 * The live engine-tool chat ("Ask the engine", #186) is the hero of the screen; the analyze flow sits below it.
 */
export function ExploreScreen({ step }: { step: Step }) {
  return (
    <div className="flex flex-col gap-8">
      <ChatPanel />
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
