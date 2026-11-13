import { StepView } from "@/components/StepView";
import { STEPS } from "@/lib/steps";

/** `/` is the first presenter screen (Rewind). Rendered directly, not redirected, so it works as a static export. */
export default function Home() {
  return <StepView step={STEPS[0]!} />;
}
