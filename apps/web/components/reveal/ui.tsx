import type { ReactNode } from "react";
import type { BenchmarkFailure } from "@/lib/benchmark";

/**
 * Small display helpers for the REVEAL screen. Formatting only: values are API numbers rounded for display; the full
 * value is in the `title` tooltip. Nothing here derives a new number.
 */

/** Fixed 4 decimals (Brier, log loss, accuracy fraction). */
export function fmt4(x: number): string {
  return x.toFixed(4);
}

/** Fixed 4 decimals with an explicit sign (U+2212 minus), for Δ values and interval ends. */
export function fmtSigned(x: number): string {
  if (x === 0) return "0.0000";
  return `${x < 0 ? "−" : "+"}${Math.abs(x).toFixed(4)}`;
}

export function Num({ value, signed = false, className = "" }: { value: number; signed?: boolean; className?: string }) {
  return (
    <span className={`num ${className}`} title={String(value)}>
      {signed ? fmtSigned(value) : fmt4(value)}
    </span>
  );
}

export function Tag({ children, className = "", title }: { children: ReactNode; className?: string; title?: string }) {
  return (
    <span
      title={title}
      className={`inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-sm border px-1.5 py-[3px] font-mono text-[10px] font-medium uppercase leading-none tracking-[0.1em] ${className}`}
    >
      {children}
    </span>
  );
}

export function Missing({ children = "Not available" }: { children?: ReactNode }) {
  return <span className="font-mono uppercase tracking-[0.08em] text-muted">{children}</span>;
}

export const BUTTON_PRIMARY =
  "rounded-md border border-accent/70 bg-accent-soft px-4 py-2.5 font-mono text-[11px] uppercase tracking-[0.14em] text-text transition-colors hover:bg-accent/20 disabled:cursor-not-allowed disabled:border-dashed disabled:border-line-strong disabled:bg-transparent disabled:text-muted";

export const BUTTON_SECONDARY =
  "rounded-md border border-line px-3 py-1.5 font-mono text-[11px] uppercase tracking-[0.12em] text-text-2 transition-colors hover:border-line-strong hover:bg-hover";

const FAILURE_HEADLINE: Record<BenchmarkFailure["kind"], string> = {
  route_pending: "Not available: route pending (#44)",
  not_revealable: "Not revealable",
  outcome_not_available: "Outcome not available",
  validation: "Request rejected",
  http: "Request failed",
  malformed: "Not available: response did not match the contract",
  network: "API unreachable",
  timeout: "API did not respond",
  aborted: "Request cancelled",
};

const FAILURE_NOTE: Partial<Record<BenchmarkFailure["kind"], string>> = {
  route_pending: "This API build does not serve the route yet. Nothing is shown in its place.",
  not_revealable:
    "The API refuses to unseal this outcome: the prediction is not persisted, or its stored prompt, snapshot or record hash no longer matches.",
  outcome_not_available: "The API has no sealed outcome file for this event, so there is nothing to reveal or score.",
  malformed: "The body is not rendered; no value is patched up or defaulted.",
  network: "Start the API (make api) or check NEXT_PUBLIC_API_BASE.",
};

/** Honest failure report: headline by kind, server message verbatim, status/code and the exact request. */
export function FailureReport({ failure }: { failure: BenchmarkFailure }) {
  const tone =
    failure.kind === "not_revealable" || failure.kind === "http" || failure.kind === "validation"
      ? "border-fail/50 text-fail"
      : "border-line-strong text-muted";
  return (
    <div role="alert" className={`flex flex-col gap-2 rounded-md border border-dashed px-4 py-3 ${tone}`}>
      <p className="font-mono text-sm font-medium uppercase tracking-[0.08em]">
        {FAILURE_HEADLINE[failure.kind]}
        {failure.status ? <span className="num"> · HTTP {failure.status}</span> : null}
        {failure.code ? <span> · {failure.code}</span> : null}
      </p>
      {FAILURE_NOTE[failure.kind] ? (
        <p className="text-xs leading-relaxed text-muted">{FAILURE_NOTE[failure.kind]}</p>
      ) : null}
      <p className="whitespace-pre-wrap break-words font-mono text-[11px] leading-relaxed text-text-2">
        <span className="text-muted">API message: </span>
        {failure.message}
      </p>
      <p className="break-all font-mono text-[10.5px] text-muted">{failure.request}</p>
    </div>
  );
}
