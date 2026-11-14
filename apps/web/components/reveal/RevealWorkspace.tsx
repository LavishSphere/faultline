"use client";

import { useState } from "react";
import { IntegrityPanel } from "../integrity/IntegrityPanel";
import { Scorecard } from "../Scorecard";
import { RevealPanel } from "./RevealPanel";

/**
 * Client half of Screen D. Keeps two ids apart (#117):
 * - `predictionId`: the id the presenter is working with (from `?prediction_id=` or the reveal form), for panels
 *   that need it before a reveal;
 * - `revealedPredictionId`: set only when D.0's reveal succeeded. The scorecard marks "this forecast" from this one
 *   alone, so nothing about the forecast's event is highlighted while D.0 still says SEALED.
 *
 * D.3 is the INTEGRITY panel (#81) for `predictionId`; with none it offers its own case/run picker.
 */
export function RevealWorkspace() {
  // Reported by RevealPanel; read by the INTEGRITY panel (D.3).
  const [predictionId, setPredictionId] = useState<string | null>(null);
  const [revealedPredictionId, setRevealedPredictionId] = useState<string | null>(null);

  return (
    <div className="flex flex-col gap-6">
      <div className="grid grid-cols-1 gap-6 xl:grid-cols-12">
        <div className="min-w-0 xl:col-span-4">
          <RevealPanel onPredictionId={setPredictionId} onRevealed={setRevealedPredictionId} />
        </div>
        <div className="min-w-0 xl:col-span-8">
          <Scorecard revealedPredictionId={revealedPredictionId} />
        </div>
      </div>
      <IntegrityPanel code="D.3" predictionId={predictionId} />
    </div>
  );
}
