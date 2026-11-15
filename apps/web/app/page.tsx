import { StepView } from "@/components/StepView";
import { HOME_STEP } from "@/lib/steps";

/**
 * `/` is the home screen: Live Explore (the engine-tool chat). Rendered directly, not redirected, so it works as a
 * static export. The Blind Replay starts at `/rewind/`.
 */
export default function Home() {
  return <StepView step={HOME_STEP} />;
}
