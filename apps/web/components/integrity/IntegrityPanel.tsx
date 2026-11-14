"use client";

import { useEffect, useId, useState, type FormEvent } from "react";
import {
  INTEGRITY_REQUEST,
  getIntegrity,
  getIntegrityCases,
  type CheckStatus,
  type IntegrityCaseOption,
  type IntegrityCheck,
  type IntegrityResponse,
} from "@/lib/integrity";
import type { ApiResult } from "@/lib/api";
import { Panel } from "../Panel";
import { WIRE_PROVENANCE, type ProvenanceInput, type WireProvenance } from "../ProvenanceBadge";
import { useSelectedCaseId } from "../replay/hooks";

/**
 * INTEGRITY panel (issue #81): what the AI was NOT allowed to see, and which guarantees held, for the selected
 * replay case and run. Every ✓ / ✗ is the API's own status for that check (GET /api/integrity recomputes them on
 * each request from the gate, the hashes, the audit log and an import scan). This component never decides a
 * check passed; a check the API could not run shows NOT AVAILABLE.
 */

const STATUS_STYLE: Record<CheckStatus, { glyph: string; className: string; sr: string }> = {
  PASS: { glyph: "✓", className: "border-viable/60 text-viable", sr: "passed" },
  FAIL: { glyph: "✗", className: "border-fail/60 bg-fail/10 text-fail", sr: "failed" },
  "NOT AVAILABLE": { glyph: "∅", className: "border-dashed border-line-strong text-muted", sr: "could not run" },
};

const SCOPE_LABEL: Record<IntegrityCheck["scope"], string> = {
  case: "This case",
  run: "This run",
  system: "The system",
};

function StatusMark({ status }: { status: CheckStatus }) {
  const s = STATUS_STYLE[status];
  return (
    <span
      className={`inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-sm border px-1.5 py-[3px] font-mono text-[10px] font-medium uppercase leading-none tracking-[0.1em] ${s.className}`}
      data-status={status}
    >
      <span aria-hidden="true">{s.glyph}</span>
      <span>{status}</span>
    </span>
  );
}

function wireProvenance(value: string | null): ProvenanceInput | null {
  return value !== null && value in WIRE_PROVENANCE ? (value as WireProvenance) : null;
}

function CheckRow({ check }: { check: IntegrityCheck }) {
  return (
    <li className="flex flex-col gap-2 border-b border-line/70 py-4 last:border-b-0" data-check={check.id}>
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1.5">
        <h3 className="flex min-w-0 items-baseline gap-3 text-sm font-medium text-text">
          <StatusMark status={check.status} />
          <span className="min-w-0">{check.title}</span>
        </h3>
        <span className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted">{SCOPE_LABEL[check.scope]}</span>
      </div>
      <p className="text-xs leading-relaxed text-text-2">{check.explanation}</p>
      {check.facts.length > 0 ? (
        <dl className="grid grid-cols-1 gap-x-6 gap-y-1 sm:grid-cols-2">
          {check.facts.map((f, i) => (
            <div key={`${f.label}-${i}`} className="flex min-w-0 items-baseline justify-between gap-3 border-b border-line/40 py-1">
              <dt className="text-[11px] text-muted">{f.label}</dt>
              <dd className="num min-w-0 break-all text-right font-mono text-[11px] text-text">{f.value}</dd>
            </div>
          ))}
        </dl>
      ) : null}
      <details className="text-[11px] text-muted">
        <summary className="cursor-pointer font-mono uppercase tracking-[0.12em]">Enforced by</summary>
        <ul className="mt-1.5 flex flex-col gap-0.5 font-mono">
          {check.enforced_by.map((e) => (
            <li key={e} className="break-all">
              {e}
            </li>
          ))}
        </ul>
      </details>
    </li>
  );
}

type Load<T> = { key: string; result: ApiResult<T> } | null;

export function IntegrityPanel({
  code,
  caseId: caseIdProp,
  predictionId: predictionIdProp,
}: {
  code?: string;
  /** Selected case from the screen, when it has one; otherwise the panel offers its own picker. */
  caseId?: string | null;
  /** Persisted forecast id from a replay run, when the screen has one. */
  predictionId?: string | null;
}) {
  const ids = useId();
  const [cases, setCases] = useState<ApiResult<IntegrityCaseOption[]> | null>(null);
  /** undefined until the presenter uses this panel's own picker; null = "System checks only". */
  const [pickedCase, setPickedCase] = useState<string | null | undefined>(undefined);
  /** The case chosen on REWIND / DECISION (shared selection, #157): the default when no case is passed or picked. */
  const [sharedCase] = useSelectedCaseId();
  const [predictionDraft, setPredictionDraft] = useState("");
  const [appliedPrediction, setAppliedPrediction] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);
  const [load, setLoad] = useState<Load<IntegrityResponse>>(null);

  useEffect(() => {
    const controller = new AbortController();
    void getIntegrityCases(controller.signal).then((res) => {
      if (!controller.signal.aborted) setCases(res);
    });
    return () => controller.abort();
  }, []);

  const caseOptions = cases?.ok ? cases.data : [];
  const onlyCase = caseOptions.length === 1 ? caseOptions[0]!.event_id : null;
  const sharedServed = sharedCase !== null && caseOptions.some((c) => c.event_id === sharedCase) ? sharedCase : null;
  const caseId = caseIdProp ?? (pickedCase !== undefined ? pickedCase : (sharedServed ?? onlyCase));
  const predictionId = predictionIdProp ?? appliedPrediction;
  const casesSettled = caseIdProp != null || cases !== null;
  const key = `${caseId ?? ""}|${predictionId ?? ""}|${nonce}`;

  useEffect(() => {
    if (!casesSettled) return;
    const controller = new AbortController();
    void getIntegrity({ caseId, predictionId }, controller.signal).then((result) => {
      if (!controller.signal.aborted) setLoad({ key, result });
    });
    return () => controller.abort();
    // `key` captures caseId, predictionId and the re-run nonce.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, casesSettled]);

  const current = load && load.key === key ? load.result : null;
  const data = current?.ok ? current.data : null;
  const provenance: ProvenanceInput[] = [];
  const caseProv = wireProvenance(data?.case_provenance ?? null);
  const runProv = wireProvenance(data?.prediction_provenance ?? null);
  if (caseProv) provenance.push(caseProv);
  if (runProv) provenance.push(runProv);
  if (provenance.length === 0) provenance.push("NOT AVAILABLE");

  const onApply = (e: FormEvent) => {
    e.preventDefault();
    setAppliedPrediction(predictionDraft.trim() || null);
  };

  return (
    <Panel code={code} title="Integrity · what the AI could not see" provenance={provenance}>
      <div className="flex flex-col gap-5">
        <form onSubmit={onApply} className="flex flex-col gap-3 lg:flex-row lg:items-end">
          {caseIdProp == null ? (
            <label className="flex min-w-0 flex-1 flex-col gap-1.5" htmlFor={`${ids}-case`}>
              <span className="kicker">Replay case</span>
              <select
                id={`${ids}-case`}
                className="min-w-0 rounded-md border border-line bg-bg px-3 py-2 font-mono text-xs text-text"
                value={caseId ?? ""}
                onChange={(e) => setPickedCase(e.target.value || null)}
                disabled={!cases?.ok || caseOptions.length === 0}
              >
                <option value="">{caseOptions.length === 0 ? "No replay cases served" : "System checks only"}</option>
                {caseOptions.map((c) => (
                  <option key={c.event_id} value={c.event_id}>
                    {c.event_id}: {c.title}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
          {predictionIdProp == null ? (
            <label className="flex min-w-0 flex-1 flex-col gap-1.5" htmlFor={`${ids}-pred`}>
              <span className="kicker">Prediction id (from a replay run)</span>
              <input
                id={`${ids}-pred`}
                className="min-w-0 rounded-md border border-line bg-bg px-3 py-2 font-mono text-xs text-text"
                value={predictionDraft}
                onChange={(e) => setPredictionDraft(e.target.value)}
                placeholder="pred_…"
                spellCheck={false}
                autoComplete="off"
              />
            </label>
          ) : null}
          <div className="flex gap-2">
            {predictionIdProp == null ? (
              <button
                type="submit"
                className="rounded-md border border-line-strong px-3 py-2 font-mono text-[11px] uppercase tracking-[0.14em] text-text-2 hover:bg-hover"
              >
                Apply
              </button>
            ) : null}
            <button
              type="button"
              onClick={() => setNonce((n) => n + 1)}
              className="rounded-md border border-line-strong px-3 py-2 font-mono text-[11px] uppercase tracking-[0.14em] text-text-2 hover:bg-hover"
            >
              Re-run checks
            </button>
          </div>
        </form>
        {cases && !cases.ok ? (
          <p className="font-mono text-[11px] text-muted">Case list NOT AVAILABLE: {cases.error}</p>
        ) : null}

        {current === null ? (
          <p className="font-mono text-xs uppercase tracking-[0.12em] text-muted" aria-live="polite">
            Requesting {INTEGRITY_REQUEST}…
          </p>
        ) : !current.ok ? (
          <div className="flex flex-col gap-1.5" aria-live="polite">
            <p className="font-mono text-lg font-medium uppercase tracking-[0.08em] text-muted">Not available</p>
            <p className="font-mono text-[11px] text-muted">
              {INTEGRITY_REQUEST}: {current.error}
            </p>
            <p className="text-xs leading-relaxed text-muted">No check is shown as passed when the API did not report it.</p>
          </div>
        ) : (
          <IntegrityBody data={current.data} />
        )}
      </div>
    </Panel>
  );
}

function IntegrityBody({ data }: { data: IntegrityResponse }) {
  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-baseline gap-x-6 gap-y-2" aria-live="polite">
        <p className="num text-sm text-text">
          <span className="text-viable">{data.counts.passed} passed</span>
          <span className="mx-2 text-line-strong">·</span>
          <span className={data.counts.failed > 0 ? "text-fail" : "text-text-2"}>{data.counts.failed} failed</span>
          <span className="mx-2 text-line-strong">·</span>
          <span className="text-muted">{data.counts.not_available} not available</span>
        </p>
        <p className="font-mono text-[11px] text-muted">
          {data.case_id ? <>case {data.case_id}</> : <>no case selected</>}
          {data.prediction_id ? <> · run {data.prediction_id}</> : null}
          {data.as_of ? <> · cutoff {data.as_of}</> : null} · computed {data.computed_at}
        </p>
      </div>

      {data.case_id ? (
        <div>
          <p className="kicker">Withheld from the model by the temporal gate</p>
          {data.excluded.length === 0 ? (
            <p className="mt-2 font-mono text-[11px] text-muted">Nothing withheld for this case (0 items).</p>
          ) : (
            <ul className="mt-2 flex flex-wrap gap-2">
              {data.excluded.map((x) => (
                <li
                  key={`${x.kind}-${x.reason}`}
                  className="rounded-sm border border-line px-2 py-1 font-mono text-[11px] text-text-2"
                >
                  <span className="num text-text">{x.count}</span> {x.kind} · {x.reason.replaceAll("_", " ")}
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : null}

      <ol className="flex flex-col">
        {data.checks.map((c) => (
          <CheckRow key={c.id} check={c} />
        ))}
      </ol>

      {data.notes.length > 0 ? (
        <ul className="flex flex-col gap-1 text-xs text-muted">
          {data.notes.map((n) => (
            <li key={n}>{n}</li>
          ))}
        </ul>
      ) : null}

      <details className="rounded-md border border-line px-4 py-3">
        <summary className="cursor-pointer font-mono text-[11px] uppercase tracking-[0.14em] text-text-2">
          What these checks do not guarantee
        </summary>
        <ul className="mt-2 flex list-disc flex-col gap-1.5 pl-4 text-xs leading-relaxed text-muted">
          {data.limits.map((l) => (
            <li key={l}>{l}</li>
          ))}
        </ul>
      </details>
    </div>
  );
}
