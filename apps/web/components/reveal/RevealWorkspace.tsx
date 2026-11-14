"use client";

import { useState } from "react";
import { Scorecard } from "../Scorecard";
import { RevealPanel } from "./RevealPanel";

/**
 * Client half of Screen D. Holds the prediction_id the presenter is working with (from `?prediction_id=` or the
 * reveal form) so sibling panels get the same id. The scorecard uses it only to mark that forecast's row.
 *
 * PR #93 (IntegrityPanel, not merged) wires in with one line below the grid:
 *   <IntegrityPanel code="D.3" predictionId={predictionId} />
 */
export function RevealWorkspace() {
  const [predictionId, setPredictionId] = useState<string | null>(null);

  return (
    <div className="grid grid-cols-1 gap-6 xl:grid-cols-12">
      <div className="min-w-0 xl:col-span-4">
        <RevealPanel onPredictionId={setPredictionId} />
      </div>
      <div className="min-w-0 xl:col-span-8">
        <Scorecard predictionId={predictionId} />
      </div>
    </div>
  );
}
