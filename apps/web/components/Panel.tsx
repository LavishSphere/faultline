import type { ReactNode } from "react";
import { PENDING_ENDPOINTS, type PendingEndpoint } from "@/lib/api";
import { ProvenanceBadge, type ProvenanceInput } from "./ProvenanceBadge";

/**
 * Flat terminal panel: hairline border, no drop shadow. Every panel declares its provenance,
 * so there is no way to render a data surface without a label.
 */
export function Panel({
  title,
  code,
  provenance,
  provenanceDetail,
  children,
  className = "",
  bodyClassName = "",
}: {
  title: string;
  /** Short mono code shown before the title, e.g. "A.1". */
  code?: string;
  provenance: ProvenanceInput;
  provenanceDetail?: string;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
}) {
  return (
    <section className={`flex min-w-0 flex-col rounded-lg border border-line bg-elevated ${className}`}>
      <header className="flex min-h-11 flex-wrap items-center justify-between gap-x-3 gap-y-1.5 border-b border-line px-5 py-2.5">
        <h2 className="flex items-baseline gap-2 font-mono text-[11px] uppercase tracking-[0.14em] text-text-2">
          {code ? <span className="text-muted">{code}</span> : null}
          <span>{title}</span>
        </h2>
        <ProvenanceBadge kind={provenance} detail={provenanceDetail} />
      </header>
      <div className={`flex-1 p-5 ${bodyClassName}`}>{children}</div>
    </section>
  );
}

/** Honest empty state: names the endpoint that would supply this panel. */
export function NotAvailable({
  endpoint,
  note,
  size = "md",
}: {
  endpoint?: PendingEndpoint;
  note?: string;
  size?: "sm" | "md" | "lg";
}) {
  const sizeClass = size === "lg" ? "text-2xl md:text-3xl" : size === "sm" ? "text-sm" : "text-lg";
  return (
    <div className="flex flex-col gap-1.5">
      <p className={`font-mono font-medium uppercase tracking-[0.08em] text-muted ${sizeClass}`}>Not available</p>
      {endpoint ? (
        <p className="font-mono text-[11px] text-muted">
          Requires <code className="text-text-2">{PENDING_ENDPOINTS[endpoint]}</code> (not wired)
        </p>
      ) : null}
      {note ? <p className="text-xs leading-relaxed text-muted">{note}</p> : null}
    </div>
  );
}

/** Label / value row used in readout lists. A missing value renders NOT AVAILABLE, never a default. */
export function Field({
  label,
  value,
  preserveCase = false,
}: {
  label: string;
  value?: ReactNode;
  /** Keep the label's case, e.g. when it contains symbols such as n or Δ. */
  preserveCase?: boolean;
}) {
  return (
    <div className="flex items-baseline justify-between gap-4 border-b border-line/70 py-2 last:border-b-0">
      <dt className={`text-xs text-muted ${preserveCase ? "tracking-[0.02em]" : "uppercase tracking-[0.12em]"}`}>
        {label}
      </dt>
      <dd className="num text-right text-sm text-text">
        {value ?? <span className="font-mono uppercase tracking-[0.08em] text-muted">Not available</span>}
      </dd>
    </div>
  );
}
