import { Field, NotAvailable, Panel } from "./Panel";

/**
 * ACT / WAIT / HEDGE split view (SPEC §2 Screen B, MATH_MODEL §8).
 * Payoffs come from the deterministic simulator; until it is wired every branch is NOT AVAILABLE.
 */
const BRANCHES = [
  { key: "ACT", label: "Act", code: "B.4", gist: "Commit now, before the outcome is known." },
  { key: "WAIT", label: "Wait", code: "B.5", gist: "Hold until more information arrives." },
  { key: "HEDGE", label: "Hedge", code: "B.6", gist: "Limit exposure on both outcomes." },
] as const;

export function DecisionBranches() {
  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
      {BRANCHES.map((b) => (
        <Panel key={b.key} code={b.code} title={b.key} provenance="NOT AVAILABLE">
          <p className="display text-5xl italic text-text md:text-6xl">{b.label}</p>
          <p className="mt-3 text-sm leading-relaxed text-muted">{b.gist}</p>
          <dl className="mt-5">
            <Field label="Expected cash impact" />
            <Field label="Worst-case min cash" />
            <Field label="Feasible" />
          </dl>
          <div className="mt-4">
            <NotAvailable size="sm" endpoint="simulate" />
          </div>
        </Panel>
      ))}
    </div>
  );
}
