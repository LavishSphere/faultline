import type { Step } from "@/lib/steps";
import { ChatPanel } from "./chat/ChatPanel";
import { ExploreWorkbench } from "./ExploreWorkbench";

/**
 * Screen F: LIVE EXPLORE (issue #61), the home screen `/` and the first step, before the Blind Replay.
 * The live engine-tool chat ("Ask the engine", #186) is the hero and carries the page's h1; the headline analyzer
 * (current web via Tavily, read by the local model, confirmed by the human, computed by the engine) sits below it.
 * Separate from the Blind Replay.
 */
export function ExploreScreen({ step }: { step: Step }) {
  return (
    <div className="flex flex-col gap-8">
      <ChatPanel />
      <header className="flex flex-col gap-2 border-t border-line pt-8 lg:flex-row lg:items-end lg:justify-between lg:gap-10">
        <h2 className="display text-[clamp(2rem,3.4vw,3.25rem)] leading-none text-text">
          {step.titlePre ? <>{step.titlePre} </> : null}
          <em>{step.titleEm}</em>
        </h2>
        <div className="flex max-w-xl flex-col gap-1 lg:items-end lg:text-right">
          <p className="text-[15px] leading-relaxed text-text-2">{step.lede}</p>
          <p className="font-mono text-[11px] uppercase tracking-[0.12em] text-muted">
            Current web · not point-in-time · never given to the Blind Replay
          </p>
        </div>
      </header>
      <ExploreWorkbench />
    </div>
  );
}
