import { PROVENANCE_KINDS, ProvenanceBadge, WIRE_PROVENANCE, type ProvenanceInput } from "../../ProvenanceBadge";

/**
 * Badges for the chat. MODEL-WRITTEN is chat-specific (the reply's words are the model's; its numbers come from
 * engine tools), so it is drawn here in the ProvenanceBadge style: text + glyph + colour, never colour alone.
 */
export function ModelWrittenBadge() {
  return (
    <span
      className="inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-sm border border-dashed border-accent/60 px-1.5 py-[3px] font-mono text-[10px] font-medium uppercase leading-none tracking-[0.1em] text-accent-hover"
      title="Words written by the model. Every number in it came from an engine tool the server ran; the browser does not recompute it."
      data-provenance="MODEL-WRITTEN"
    >
      <span aria-hidden="true">✎</span>
      <span>MODEL-WRITTEN</span>
    </span>
  );
}

const KNOWN = new Set<string>([...PROVENANCE_KINDS, ...Object.keys(WIRE_PROVENANCE)]);

/** A provenance string exactly as the API sent it: a known label gets its badge, anything else is shown verbatim. */
export function WireBadge({ value }: { value: string }) {
  if (KNOWN.has(value)) return <ProvenanceBadge kind={value as ProvenanceInput} />;
  return (
    <span
      className="inline-flex max-w-full items-center gap-1.5 truncate rounded-sm border border-line-strong px-1.5 py-[3px] font-mono text-[10px] uppercase leading-none tracking-[0.1em] text-text-2"
      title="Provenance label as the API sent it"
      data-provenance={value}
    >
      {value || "NO LABEL"}
    </span>
  );
}
