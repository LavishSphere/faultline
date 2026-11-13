import { Field, NotAvailable, Panel } from "./Panel";

/**
 * Thesis Court (SPEC §7): four public research perspectives, filtered to what was published by the cutoff.
 * Firm names are fixed by the spec; every thesis, date, link and stance comes from GET /api/vc-lenses.
 * This is RESEARCH CONTEXT: not a forecast attributed to any firm, and not a competitive score.
 */
const FIRMS = [
  { code: "E.1", name: "Link Ventures" },
  { code: "E.2", name: "a16z" },
  { code: "E.3", name: "Sequoia Capital" },
  { code: "E.4", name: "Bessemer Venture Partners" },
] as const;

export function ThesisCourt() {
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
      {FIRMS.map((f) => (
        <Panel key={f.name} code={f.code} title="Research context" provenance="NOT AVAILABLE">
          <h3 className="display text-3xl text-text md:text-4xl">{f.name}</h3>
          <dl className="mt-5">
            <Field label="Source" />
            <Field label="Published" />
            <Field label="Valid at cutoff" />
            <Field label="Claim type" />
            <Field label="Model agrees" />
          </dl>
          <div className="mt-4">
            <NotAvailable size="sm" endpoint="vcLenses" />
          </div>
        </Panel>
      ))}
    </div>
  );
}
