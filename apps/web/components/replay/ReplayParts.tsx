import type { ButtonHTMLAttributes, ReactNode } from "react";
import { ProvenanceBadge, type ProvenanceInput } from "../ProvenanceBadge";
import { formatCutoffUtc, type ReplayCasePublic, type ReplayFailure } from "@/lib/replay";

/** Badges for a served case: AS-OF (it is a cutoff view) plus the case's own provenance, exactly as served. */
export function caseProvenance(c: ReplayCasePublic): ProvenanceInput[] {
  const kinds: ProvenanceInput[] = ["AS-OF", c.provenance];
  // A case flagged synthetic is always labeled so, even if its provenance field says otherwise.
  if (c.synthetic && c.provenance !== "SYNTHETIC") kinds.push("SYNTHETIC");
  return kinds;
}

export function CaseBadges({ c }: { c: ReplayCasePublic }) {
  return (
    <span className="flex flex-wrap items-center gap-1.5">
      {caseProvenance(c).map((k, i) => (
        <ProvenanceBadge key={`${k}-${i}`} kind={k} />
      ))}
    </span>
  );
}

/** `Knowledge cutoff: YYYY-MM-DD HH:MM UTC` (SPEC §2 Screen A), from the served `as_of`. */
export function CutoffLine({ asOf, className = "" }: { asOf: string; className?: string }) {
  const text = formatCutoffUtc(asOf);
  return (
    <p className={`num text-text ${className}`}>
      <span className="text-muted">Knowledge cutoff: </span>
      {text ?? <span className="uppercase text-muted">not available</span>}
    </p>
  );
}

/** 422 headlines by `models.ErrorCode`: each one means there is no forecast and nothing was saved. */
const VALIDATION_HEADLINES: Record<string, string> = {
  VALIDATION_ERROR: "Request rejected",
  INSUFFICIENT_DATA: "Insufficient data",
  PROMPT_TOO_LONG: "Prompt too long: refused",
  PROMPT_NOT_VERIFIED: "Prompt not verified: answer discarded",
  MODEL_OUTPUT_INVALID: "No valid forecast",
};

/** What the presenter should read for each failure. `pendingIssue` names the issue that adds a missing route. */
export function failureHeadline(f: ReplayFailure, pendingIssue?: string): { title: string; tone: string } {
  switch (f.kind) {
    case "route_missing":
      return { title: pendingIssue ? `Route pending (${pendingIssue})` : "Route not served", tone: "text-muted" };
    case "pending":
      return { title: "Not available", tone: "text-muted" };
    case "network":
    case "timeout":
      return { title: "API unreachable", tone: "text-fail" };
    case "aborted":
      return { title: "Request cancelled", tone: "text-muted" };
    case "admin_required":
      return { title: "Disabled on the public demo", tone: "text-risk" };
    case "model_unavailable":
      return { title: "Local model unavailable", tone: "text-risk" };
    case "not_found":
      return { title: "Not found", tone: "text-risk" };
    case "conflict":
      return { title: "Not saved: prediction exists", tone: "text-risk" };
    case "data_invalid":
      return { title: "Failed a data check", tone: "text-fail" };
    case "validation":
      return { title: (f.code && VALIDATION_HEADLINES[f.code]) || "Request rejected", tone: "text-risk" };
    case "leak":
      return { title: "Refused: outcome-like data pre-reveal", tone: "text-fail" };
    case "malformed":
      return { title: "Response did not match the contract", tone: "text-fail" };
    default:
      return { title: `Request failed${f.status ? ` (HTTP ${f.status})` : ""}`, tone: "text-fail" };
  }
}

/** Honest failure / not-available block: headline, the exact request, and the server's own message. */
export function FailureNote({
  failure,
  pendingIssue,
  note,
  size = "md",
  action,
  headline,
}: {
  failure: ReplayFailure;
  pendingIssue?: string;
  note?: ReactNode;
  size?: "sm" | "md" | "lg";
  action?: ReactNode;
  /** Replaces the default headline (e.g. a run that got no answer is not "API unreachable"). */
  headline?: { title: string; tone: string };
}) {
  const { title, tone } = headline ?? failureHeadline(failure, pendingIssue);
  const sizeClass = size === "lg" ? "text-2xl md:text-3xl" : size === "sm" ? "text-sm" : "text-lg";
  return (
    <div className="flex flex-col gap-1.5" role={failure.kind === "leak" ? "alert" : undefined}>
      <p className={`font-mono text-[11px] uppercase tracking-[0.12em] text-muted`}>Not available</p>
      <p className={`font-mono font-medium uppercase tracking-[0.06em] ${tone} ${sizeClass}`}>{title}</p>
      <p className="break-words font-mono text-[11px] text-muted">
        <code className="text-text-2">{failure.request}</code>
        {failure.status ? ` → HTTP ${failure.status}` : ""}
        {failure.code ? ` · ${failure.code}` : ""}
      </p>
      {failure.message ? (
        <p className="whitespace-pre-line break-words text-xs leading-relaxed text-muted">{failure.message}</p>
      ) : null}
      {note ? <div className="text-xs leading-relaxed text-muted">{note}</div> : null}
      {action ? <div className="mt-2">{action}</div> : null}
    </div>
  );
}

/** Real in-flight state: names the request, invents no progress. */
export function InFlight({ request, note }: { request: string; note?: string }) {
  return (
    <div className="flex flex-col gap-1.5" aria-live="polite">
      <p className="font-mono text-sm uppercase tracking-[0.12em] text-text-2">
        <span aria-hidden="true" className="mr-2 inline-block size-1.5 rounded-full bg-accent align-middle motion-safe:animate-pulse" />
        Waiting for response
      </p>
      <p className="font-mono text-[11px] text-muted">
        <code className="text-text-2">{request}</code>
      </p>
      {note ? <p className="text-xs text-muted">{note}</p> : null}
    </div>
  );
}

export function TextButton({
  children,
  onClick,
  disabled,
  variant = "quiet",
  ...rest
}: {
  children: ReactNode;
  onClick?: () => void;
  disabled?: boolean;
  variant?: "quiet" | "primary";
} & Omit<ButtonHTMLAttributes<HTMLButtonElement>, "onClick" | "disabled" | "children">) {
  const base =
    "inline-flex items-center gap-2 rounded-md border px-3 py-2 font-mono text-[11px] uppercase tracking-[0.14em] transition-colors disabled:cursor-not-allowed disabled:opacity-50";
  const look =
    variant === "primary"
      ? "border-accent bg-accent-soft text-text hover:bg-accent hover:text-bg disabled:hover:bg-accent-soft disabled:hover:text-text"
      : "border-line-strong text-text-2 hover:border-accent hover:text-text";
  return (
    <button type="button" onClick={onClick} disabled={disabled} className={`${base} ${look}`} {...rest}>
      {children}
    </button>
  );
}

/** A SHA-256 shown short, with the full value available to copy/select and to screen readers. */
export function Hash({ value }: { value: string }) {
  const hex = value.replace(/^sha256:/, "");
  return (
    <span className="num break-all text-text-2" title={value}>
      <span aria-hidden="true">{hex.slice(0, 12)}…{hex.slice(-6)}</span>
      <span className="sr-only">{value}</span>
    </span>
  );
}
