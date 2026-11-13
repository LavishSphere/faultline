import { CascadeWorkbench } from "../cascade/CascadeWorkbench";
import { ScreenHeader } from "./ScreenHeader";
import type { Step } from "@/lib/steps";

/**
 * Screen C: THE CASCADE (SPEC §2). Scenario inputs → POST /api/simulate → dependency network and cash readouts.
 * Every figure on this screen is read from the API response; the optimizer plan stays NOT AVAILABLE until #17.
 */
export function CascadeScreen({ step }: { step: Step }) {
  return (
    <div className="flex flex-col gap-8">
      <ScreenHeader step={step} />
      <CascadeWorkbench />
    </div>
  );
}
