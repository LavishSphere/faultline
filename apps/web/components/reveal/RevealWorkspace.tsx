"use client";

import { useState } from "react";
import { Scorecard } from "../Scorecard";
import { RevealPanel } from "./RevealPanel";

/**
 * Client half of Screen D. Keeps two ids apart (#117):
 * - `predictionId`: the id the presenter is working with (from `?prediction_id=` or the reveal form), for panels
 *   that need it before a reveal;
 * - `revealedPredictionId`: set only when D.0's reveal succeeded. The scorecard marks "this forecast" from this one
 *   alone, so nothing about the forecast's event is highlighted while D.0 still says SEALED.
 *
 * PR #93 (IntegrityPanel, not merged) wires in with one line below the grid:
 *   <IntegrityPanel code="D.3" predictionId={predictionId} />
 */
export function RevealWorkspace() {
  // Reported by RevealPanel; read by #93's IntegrityPanel once it is merged.
  const [, setPredictionId] = useState<string | null>(null);
  const [revealedPredictionId, setRevealedPredictionId] = useState<string | null>(null);

  return (
    <div className="grid grid-cols-1 gap-6 xl:grid-cols-12">
      <div className="min-w-0 xl:col-span-4">
        <RevealPanel onPredictionId={setPredictionId} onRevealed={setRevealedPredictionId} />
      </div>
      <div className="min-w-0 xl:col-span-8">
        <Scorecard revealedPredictionId={revealedPredictionId} />
      </div>
    </div>
  );
}
