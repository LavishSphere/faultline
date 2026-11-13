import { RevealPanel } from "../reveal/RevealPanel";
import { Scorecard } from "../Scorecard";
import { ScreenHeader } from "./ScreenHeader";
import type { Step } from "@/lib/steps";

/**
 * Screen D: REVEAL (SPEC §2, §6). Unseal one persisted forecast's outcome (POST /api/replay/{id}/reveal), then the
 * honest scorecard (GET /api/benchmark). Both are explicit clicks; every outcome, score and label is the API's.
 */
export function RevealScreen({ step }: { step: Step }) {
  return (
    <div className="flex flex-col gap-8">
      <ScreenHeader step={step} />

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-12">
        <div className="min-w-0 xl:col-span-4">
          <RevealPanel />
        </div>
        <div className="min-w-0 xl:col-span-8">
          <Scorecard />
        </div>
      </div>
    </div>
  );
}
