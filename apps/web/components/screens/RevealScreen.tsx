import { RevealWorkspace } from "../reveal/RevealWorkspace";
import { ScreenHeader } from "./ScreenHeader";
import type { Step } from "@/lib/steps";

/**
 * Screen D: REVEAL (SPEC §2, §6). Unseal one persisted forecast's outcome (POST /api/replay/{id}/reveal, an explicit
 * click; admin only on the public demo), next to the RECORDED RUN scorecards (GET /api/benchmark, read-only, loaded
 * on open). Every outcome, score and label is the API's.
 */
export function RevealScreen({ step }: { step: Step }) {
  return (
    <div className="flex flex-col gap-8">
      <ScreenHeader step={step} />
      <RevealWorkspace />
    </div>
  );
}
