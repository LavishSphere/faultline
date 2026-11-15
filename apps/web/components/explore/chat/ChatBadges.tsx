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

/**
 * The hero's single provenance chip: one compact control that opens the four labels this screen uses, each with a
 * one-line definition. Every reply and panel still carries its own badge; this is the key to them.
 */
export function ProvenanceKey() {
  return (
    <details className="group relative shrink-0" data-testid="chat-provenance-key">
      <summary
        className="flex cursor-pointer list-none items-center gap-1.5 rounded-sm border border-line-strong px-2 py-1 font-mono text-[10.5px] uppercase tracking-[0.1em] text-text-2 transition-colors hover:border-accent/60 hover:text-text [&::-webkit-details-marker]:hidden"
        aria-label="Provenance labels on this screen"
      >
        <span aria-hidden="true">◎</span>
        <span>Provenance</span>
        <span aria-hidden="true" className="text-muted transition-transform group-open:rotate-180">
          ▾
        </span>
      </summary>
      <div className="absolute right-0 top-full z-30 mt-2 w-[min(24rem,calc(100vw-2rem))] rounded-lg border border-line bg-elevated/95 p-3 shadow-xl backdrop-blur-[12px]">
        <dl className="flex flex-col gap-2.5">
          <div className="flex flex-col gap-1">
            <dt>
              <ProvenanceBadge kind="LIVE EXPLORE" />
            </dt>
            <dd className="text-[13px] leading-snug text-text-2">Run now on current data. Not point-in-time; never used by the Blind Replay.</dd>
          </div>
          <div className="flex flex-col gap-1">
            <dt>
              <ModelWrittenBadge />
            </dt>
            <dd className="text-[13px] leading-snug text-text-2">The words are the model&apos;s. It does no arithmetic of its own.</dd>
          </div>
          <div className="flex flex-col gap-1">
            <dt>
              <ProvenanceBadge kind="SIMULATED" detail="engine numbers" />
            </dt>
            <dd className="text-[13px] leading-snug text-text-2">Computed by FAULTLINE&apos;s engine on the server, not by the model.</dd>
          </div>
          <div className="flex flex-col gap-1">
            <dt>
              <ProvenanceBadge kind="SYNTHETIC" detail="demo business" />
            </dt>
            <dd className="text-[13px] leading-snug text-text-2">The stress-test company is a made-up demo business, not a real one.</dd>
          </div>
        </dl>
      </div>
    </details>
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
