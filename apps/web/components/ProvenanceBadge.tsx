/**
 * Provenance / state badge. Text + glyph + color; the label text always carries the meaning,
 * so the badge reads correctly in grayscale and to screen readers (never color alone).
 */

export const PROVENANCE_KINDS = [
  "AS-OF",
  "SEALED",
  "VERIFIED",
  "FORECAST",
  "REVEALED",
  "SIMULATED",
  "SYNTHETIC",
  "RECORDED RUN",
  "REAL HISTORICAL",
  "ILLUSTRATIVE",
  "NOT AVAILABLE",
  "INSUFFICIENT DATA",
] as const;

export type ProvenanceKind = (typeof PROVENANCE_KINDS)[number];

/**
 * Canonical provenance values as the backend sends them (Pydantic enum in services/api/models.py, issue #1).
 * The UI accepts these directly and shows the spaced display label.
 */
export const WIRE_PROVENANCE = {
  REAL_HISTORICAL: "REAL HISTORICAL",
  SYNTHETIC: "SYNTHETIC",
  RECORDED_RUN: "RECORDED RUN",
  SIMULATED: "SIMULATED",
  ILLUSTRATIVE: "ILLUSTRATIVE",
} as const satisfies Record<string, ProvenanceKind>;

export type WireProvenance = keyof typeof WIRE_PROVENANCE;

/** Anything a badge accepts: a display label or a backend wire value. */
export type ProvenanceInput = ProvenanceKind | WireProvenance;

export function toProvenanceKind(value: ProvenanceInput): ProvenanceKind {
  return value in WIRE_PROVENANCE ? WIRE_PROVENANCE[value as WireProvenance] : (value as ProvenanceKind);
}

interface BadgeStyle {
  glyph: string;
  className: string;
  description: string;
}

const STYLES: Record<ProvenanceKind, BadgeStyle> = {
  "AS-OF": {
    glyph: "◷",
    className: "border-line-strong text-text-2",
    description: "Value as known at the stated knowledge cutoff",
  },
  SEALED: {
    glyph: "■",
    className: "border-risk/60 text-risk bg-risk/10",
    description: "Withheld until reveal; not available to the agent",
  },
  VERIFIED: {
    glyph: "✓",
    className: "border-viable/60 text-viable",
    description: "Checked against a cited, timestamped source",
  },
  FORECAST: {
    glyph: "◇",
    className: "border-info/60 text-info",
    description: "A probability or projection, not an observed fact",
  },
  REVEALED: {
    glyph: "□",
    className: "border-viable/60 text-viable bg-viable/10",
    description: "Historical outcome unsealed after the prediction was persisted",
  },
  SIMULATED: {
    glyph: "∿",
    className: "border-info/60 text-info bg-info/10",
    description: "Computed by the deterministic simulator or optimizer",
  },
  SYNTHETIC: {
    glyph: "◌",
    className: "border-risk/50 border-dashed text-risk",
    description: "Fictional demo data, not a real company",
  },
  "RECORDED RUN": {
    glyph: "●",
    className: "border-accent/60 text-accent-hover bg-accent-soft",
    description: "A cached, reproducible run with prompt and snapshot hashes",
  },
  "REAL HISTORICAL": {
    glyph: "▲",
    className: "border-viable/50 text-viable",
    description: "Genuine dated historical record",
  },
  ILLUSTRATIVE: {
    glyph: "△",
    className: "border-line-strong border-dotted text-muted",
    description: "Structure only, not data",
  },
  "NOT AVAILABLE": {
    glyph: "∅",
    className: "border-line-strong border-dashed text-muted",
    description: "No data served by the API for this panel yet",
  },
  "INSUFFICIENT DATA": {
    glyph: "∅",
    className: "border-risk/50 border-dashed text-risk",
    description: "Not enough valid cases for a comparison",
  },
};

export function ProvenanceBadge({
  kind: input,
  detail,
  className = "",
}: {
  /** Display label or backend wire value (e.g. "RECORDED_RUN"). */
  kind: ProvenanceInput;
  /** Optional qualifier rendered after the label, e.g. "No valid comparison". */
  detail?: string;
  className?: string;
}) {
  const kind = toProvenanceKind(input);
  const style = STYLES[kind];
  return (
    <span
      className={`inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-sm border px-1.5 py-[3px] font-mono text-[10px] font-medium uppercase leading-none tracking-[0.1em] ${style.className} ${className}`}
      title={style.description}
      data-provenance={kind}
    >
      <span aria-hidden="true">{style.glyph}</span>
      <span>
        {kind}
        {detail ? <span>: {detail}</span> : null}
      </span>
    </span>
  );
}
