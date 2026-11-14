import type { ReactNode } from "react";
import { StepPager } from "./StepPager";
import { ExploreScreen } from "./explore/ExploreScreen";
import { CascadeScreen } from "./screens/CascadeScreen";
import { DecisionScreen } from "./screens/DecisionScreen";
import { ResearchScreen } from "./screens/ResearchScreen";
import { RevealScreen } from "./screens/RevealScreen";
import { RewindScreen } from "./screens/RewindScreen";
import type { Step, StepSlug } from "@/lib/steps";

const SCREENS: Record<StepSlug, (props: { step: Step }) => ReactNode> = {
  rewind: RewindScreen,
  decision: DecisionScreen,
  cascade: CascadeScreen,
  reveal: RevealScreen,
  research: ResearchScreen,
  explore: ExploreScreen,
};

/** One presenter screen plus the bottom pager. Shared by `/` (Rewind) and `/[step]`. */
export function StepView({ step }: { step: Step }) {
  const Screen = SCREENS[step.slug];
  return (
    <>
      <div key={step.slug} className="screen-enter mx-auto w-full max-w-[1760px] flex-1 px-4 py-10 md:px-10 md:py-14">
        <Screen step={step} />
      </div>
      <StepPager step={step} />
    </>
  );
}
