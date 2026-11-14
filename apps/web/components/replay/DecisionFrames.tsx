import { Field, Panel } from "../Panel";
import type { Decision } from "@/lib/replay";

/**
 * ACT / WAIT / HEDGE split view placeholder (SPEC §2 Screen B, MATH_MODEL §8).
 *
 * The frames (shock if yes / if no, and each policy's ActionPlan with all fees, fixed ex ante) are #45's
 * `decision_frames.json`; their payoffs come from `core.decision.evaluate_policies` (#35). No route serves either
 * yet, so every figure is NOT AVAILABLE. The only served value used here is the forecast's own `decision`, to mark
 * which path the model chose.
 */
const BRANCHES: readonly { key: Decision; label: string; code: string; gist: string }[] = [
  { key: "act", label: "Act", code: "B.4", gist: "Commit now, before the outcome is known." },
  { key: "wait", label: "Wait", code: "B.5", gist: "Hold until more information arrives." },
  { key: "hedge", label: "Hedge", code: "B.6", gist: "Limit exposure on both outcomes." },
];

export const DECISION_FRAMES_ENDPOINT = "GET /api/decision-frames/{case_id} (proposed; frames from #45)";

export function DecisionFrames({ chosen }: { chosen: Decision | null }) {
  return (
    <div className="flex flex-col gap-3">
      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        {BRANCHES.map((b) => {
          const isChosen = chosen === b.key;
          return (
            <Panel
              key={b.key}
              code={b.code}
              title={b.key.toUpperCase()}
              provenance={isChosen ? ["NOT AVAILABLE", "FORECAST"] : "NOT AVAILABLE"}
              provenanceDetail="payoffs"
              className={isChosen ? "border-accent" : ""}
            >
              <div className="flex items-baseline justify-between gap-3">
                <p className="display text-5xl italic text-text md:text-6xl">{b.label}</p>
                {isChosen ? (
                  <span className="font-mono text-[10px] uppercase tracking-[0.14em] text-accent">Model chose</span>
                ) : null}
              </div>
              <p className="mt-3 text-sm leading-relaxed text-muted">{b.gist}</p>
              <dl className="mt-5">
                <Field label="Policy (ActionPlan, all fees)" />
                <Field label="V(a, YES) · min cash" preserveCase />
                <Field label="V(a, NO) · min cash" preserveCase />
                <Field label="E[V | a] at forecast p" preserveCase />
                <Field label="Feasible in both states" />
              </dl>
            </Panel>
          );
        })}
      </div>
      <p className="font-mono text-[11px] leading-relaxed text-muted">
        Decision frames pending #45 (data/decision_frames.json, SYNTHETIC business, ILLUSTRATIVE policies). Needs{" "}
        <code className="text-text-2">{DECISION_FRAMES_ENDPOINT}</code> returning each policy&apos;s V(a, y) and
        E[V | a] from core.decision (MATH_MODEL §8) at the forecast p. No payoff is computed in the browser.
      </p>
    </div>
  );
}
