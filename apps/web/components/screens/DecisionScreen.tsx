"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { EvidenceDrawer } from "../EvidenceDrawer";
import { FinancialReadout } from "../FinancialReadout";
import { IntegrityPanel } from "../integrity/IntegrityPanel";
import { Field, Panel } from "../Panel";
import { SplitView } from "../decision/SplitView";
import { MarketAtCutoff, marketSource } from "../replay/MarketAtCutoff";
import { ModelReadiness } from "../replay/ModelReadiness";
import { CaseBadges, CutoffLine, FailureNote, Hash, InFlight, TextButton } from "../replay/ReplayParts";
import { useCaseEvidence, useReplayCases, useReplayRoutes, useSelectedCase, type EvidenceState } from "../replay/hooks";
import { useReplayRun, type RunState } from "../replay/useReplayRun";
import { ScreenHeader } from "./ScreenHeader";
import {
  CASES_PATH,
  RECORDED_RUNS_PENDING,
  REPLAY_RUN_PATH,
  RUN_VARIANTS,
  formatInstantUtc,
  isSyntheticQuote,
  runStore,
  savedAfterReveal,
  skepticRejected,
  type ForecastVariant,
  type ReplayCasePublic,
  type ReplayFailure,
  type ReplayRoutes,
  type ReplayRun,
} from "@/lib/replay";
import type { Step } from "@/lib/steps";

/**
 * Screen B: THE DECISION (SPEC §2). The local model's forecast for the selected case via POST /api/replay/run
 * (routes/replay.py), its cited point-in-time evidence, and the market-implied probability at the same cutoff.
 *
 * A run happens only when the presenter clicks Run; every failure (public-mode admin gate, model down, refused
 * prompt, rejected answer) is shown as what it is, never as a canned forecast. A run the server flags as saved after a
 * reveal carries a visible "not blind" caveat. ACT / WAIT / HEDGE payoffs come from POST /api/decision (#55).
 */
export function DecisionScreen({ step }: { step: Step }) {
  const { load, retry } = useReplayCases();
  const { cases, selected, select } = useSelectedCase(load);
  const routes = useReplayRoutes();
  const evidence = useCaseEvidence(selected, routes);
  const [variant, setVariant] = useState<ForecastVariant>("agent_only");
  // `caseId` / `predictionId` are served ids (predictionId is null before a run) for the INTEGRITY panel (#81).
  const { state, start, cancel, busy, busyWith, priorRun, caseId, predictionId } = useReplayRun(selected, variant);
  const [drawer, setDrawer] = useState<{ open: boolean; focus: string | null }>({ open: false, focus: null });

  const run = state.kind === "done" ? state.run : null;
  const rejected = run ? skepticRejected(run.skeptic.problems) : false;
  const valid = run && !rejected ? run : null;
  const forecastBadges = valid ? (["FORECAST", valid.prediction.provenance] as const) : ("NOT AVAILABLE" as const);

  return (
    <div className="flex flex-col gap-8">
      <ScreenHeader
        step={step}
        aside={
          selected ? (
            <div className="flex flex-col gap-1.5 lg:items-end">
              <p className="text-sm text-text">{selected.title}</p>
              <CutoffLine asOf={selected.as_of} className="text-xs" />
              <CaseBadges c={selected} />
            </div>
          ) : null
        }
      />

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-12">
        <Panel code="B.0" title="Agent decision" provenance={forecastBadges} className="xl:col-span-5">
          <div className="flex flex-col gap-5">
            <CasePicker
              load={load}
              retry={retry}
              cases={cases}
              selected={selected}
              onSelect={(id) => select(id)}
            />
            <div className="border-t border-line pt-5">
              <ModelReadiness />
            </div>
            <RunControls
              c={selected}
              routes={routes}
              variant={variant}
              onVariant={setVariant}
              state={state}
              busy={busy}
              busyWith={busyWith}
              priorRun={priorRun}
              onRun={start}
              onCancel={cancel}
            />
            <div className="border-t border-line pt-5">
              <p className="kicker">Chosen path</p>
              <div className="mt-2">
                <ChosenPath state={state} rejected={rejected} />
              </div>
            </div>
          </div>
        </Panel>

        <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 xl:col-span-7 xl:content-start">
          <Panel code="B.1" title="Agent probability" provenance={forecastBadges}>
            <FinancialReadout
              label="P(YES) · forecast"
              value={valid ? valid.prediction.p_yes : null}
              format="probability"
              provenance="FORECAST"
              sublabel={valid ? `${valid.prediction.agent_model} · ${valid.prediction.variant}` : undefined}
            />
            {valid && savedAfterReveal(valid) ? (
              <p className="mt-3 font-mono text-[11px] uppercase tracking-[0.1em] text-risk">
                Saved after a reveal: not blind
              </p>
            ) : null}
            {!valid ? (
              <p className="mt-3 font-mono text-[11px] text-muted">
                {rejected
                  ? "Rejected by the skeptic: not displayed as a valid forecast."
                  : `From ${REPLAY_RUN_PATH} after a run.`}
              </p>
            ) : null}
          </Panel>

          <Panel
            code="B.2"
            title="Market at cutoff"
            provenance={marketBadge(selected, run, evidence)}
          >
            <MarketAtCutoff c={selected} run={run} evidence={evidence} />
          </Panel>

          <Panel
            code="B.3"
            title="Evidence citations"
            provenance={valid ? "AS-OF" : "NOT AVAILABLE"}
            className="sm:col-span-2"
          >
            <Citations
              run={valid}
              c={selected}
              evidence={evidence}
              onOpen={(id) => setDrawer({ open: true, focus: id })}
            />
          </Panel>

          <Panel
            code="B.7"
            title="Run record"
            provenance={run ? run.prediction.provenance : "NOT AVAILABLE"}
            className="sm:col-span-2"
          >
            <RunRecord run={run} />
          </Panel>
        </div>
      </div>

      <section aria-labelledby="branches-heading" className="flex flex-col gap-3">
        <h2 id="branches-heading" className="kicker">
          Alternative strategies · ACT / WAIT / HEDGE
        </h2>
        <SplitView
          eventId={selected ? selected.event_id : null}
          chosen={valid ? valid.prediction.decision : null}
          agent={valid ? { p: valid.prediction.p_yes, label: "agent p (forecast)" } : null}
          market={marketInput(selected, run, evidence)}
        />
      </section>

      <IntegrityPanel code="B.8" caseId={caseId} predictionId={predictionId} />

      {selected ? (
        <EvidenceDrawer
          open={drawer.open}
          focusId={drawer.focus}
          onClose={() => setDrawer({ open: false, focus: null })}
          replayCase={selected}
          evidence={evidence}
        />
      ) : null}
    </div>
  );
}

/** The market-implied p the API served for this case (run baseline, else the evidence route), or null. */
function marketInput(c: ReplayCasePublic | null, run: ReplayRun | null, evidence: EvidenceState) {
  const m = c ? marketSource(run, evidence)?.market : undefined;
  if (!m || m.status !== "AVAILABLE" || m.p_yes === null) return null;
  const synthetic = isSyntheticQuote(m, c);
  return { p: m.p_yes, label: synthetic ? "market p (SYNTHETIC price)" : "market p (market-implied, price-derived)" };
}

function marketBadge(c: ReplayCasePublic | null, run: ReplayRun | null, evidence: EvidenceState) {
  const m = c ? marketSource(run, evidence)?.market : undefined;
  if (!m || m.status !== "AVAILABLE") return "NOT AVAILABLE" as const;
  // A synthetic-venue price, or any quote on a synthetic case, is always badged SYNTHETIC.
  if (isSyntheticQuote(m, c)) return ["AS-OF", "SYNTHETIC"] as const;
  return m.provenance ? (["AS-OF", m.provenance] as const) : ("AS-OF" as const);
}

function CasePicker({
  load,
  retry,
  cases,
  selected,
  onSelect,
}: {
  load: ReturnType<typeof useReplayCases>["load"];
  retry: () => void;
  cases: ReplayCasePublic[];
  selected: ReplayCasePublic | null;
  onSelect: (id: string) => void;
}) {
  if (load.kind === "loading") return <InFlight request={`GET ${CASES_PATH}`} />;
  if (!load.result.ok) {
    return <FailureNote size="sm" failure={load.result} action={<TextButton onClick={retry}>Retry</TextButton>} />;
  }
  if (cases.length === 0) {
    return (
      <div className="flex flex-col gap-1.5">
        <p className="font-mono text-lg font-medium uppercase tracking-[0.08em] text-muted">No replay case</p>
        {load.result.data.notes.map((n) => (
          <p key={n} className="text-xs leading-relaxed text-text-2">
            {n}
          </p>
        ))}
        <p className="text-xs text-muted">Real cases pending #20; synthetic fallback pending #48.</p>
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-2">
      <label htmlFor="decision-case" className="kicker">
        Case
      </label>
      <select
        id="decision-case"
        value={selected?.event_id ?? ""}
        onChange={(e) => onSelect(e.target.value)}
        className="w-full rounded-md border border-line-strong bg-bg px-3 py-2 text-sm text-text"
      >
        {selected ? null : <option value="">Select a case…</option>}
        {cases.map((c) => (
          <option key={c.event_id} value={c.event_id}>
            {c.title}
          </option>
        ))}
      </select>
      {selected ? null : (
        <p className="text-xs text-muted">
          Or pick one on{" "}
          <Link href="/rewind" className="text-text-2 underline underline-offset-4 hover:text-link-hover">
            Rewind
          </Link>
          .
        </p>
      )}
    </div>
  );
}

/** Shown under Cancel while a run is in flight, and after a timeout or cancel (#117 A). */
const NO_ANSWER_NOTE =
  "The server may still finish and save this forecast; it is not shown here. Do not re-run before checking.";
const SECOND_FORECAST_NOTE =
  "A second saved forecast for this case and variant excludes it from the benchmark (multiple_predictions).";

function RunControls({
  c,
  routes,
  variant,
  onVariant,
  state,
  busy,
  busyWith,
  priorRun,
  onRun,
  onCancel,
}: {
  c: ReplayCasePublic | null;
  routes: ReplayRoutes | null;
  variant: ForecastVariant;
  onVariant: (v: ForecastVariant) => void;
  state: RunState;
  /** Any run in flight (any case, any variant): Run stays disabled. */
  busy: boolean;
  busyWith: { caseId: string; variant: ForecastVariant } | null;
  /** A forecast for this case + variant was saved here, or a request for it got no answer. */
  priorRun: "saved" | "unanswered" | null;
  onRun: () => void;
  onCancel: () => void;
}) {
  const absent = routes?.replayRun === "absent";
  const running = state.kind === "running";
  const elsewhere = busy && !running ? busyWith : null;
  // The confirmation belongs to one case + variant; switching either drops it.
  const key = c ? runStore.key(c.event_id, variant) : "";
  const [confirmKey, setConfirmKey] = useState<string | null>(null);
  const confirming = confirmKey !== null && confirmKey === key && !busy;
  const keepRef = useRef<HTMLButtonElement | null>(null);
  useEffect(() => {
    if (confirming) keepRef.current?.focus();
  }, [confirming]);

  function requestRun() {
    if (priorRun) setConfirmKey(key);
    else onRun();
  }
  return (
    <div className="flex flex-col gap-4">
      <fieldset className="flex flex-col gap-2">
        <legend className="kicker mb-2">Variant</legend>
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          {RUN_VARIANTS.map((v) => (
            <label
              key={v.id}
              className={`flex cursor-pointer flex-col gap-1 rounded-md border px-3 py-2 transition-colors has-[:focus-visible]:outline has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-accent ${
                variant === v.id ? "border-accent bg-accent-soft" : "border-line hover:border-line-strong"
              }`}
            >
              <span className="flex items-center gap-2">
                <input
                  type="radio"
                  name="replay-variant"
                  value={v.id}
                  checked={variant === v.id}
                  onChange={() => onVariant(v.id)}
                  className="sr-only"
                />
                <span aria-hidden="true" className={`size-2 rounded-full border ${variant === v.id ? "border-accent bg-accent" : "border-line-strong"}`} />
                <span className="font-mono text-[11px] uppercase tracking-[0.14em] text-text">{v.label}</span>
              </span>
              <span className="text-[11px] leading-snug text-muted">{v.detail}</span>
            </label>
          ))}
        </div>
      </fieldset>

      {absent ? (
        <FailureNote
          failure={{
            ok: false,
            kind: "route_missing",
            message: "This API build does not register the replay-run route (checked /openapi.json). No forecast is shown.",
            request: `POST ${REPLAY_RUN_PATH}`,
          }}
        />
      ) : (
        <div className="flex flex-col gap-3">
          <div className="flex flex-wrap items-center gap-3">
            <TextButton
              variant="primary"
              onClick={requestRun}
              disabled={!c || routes === null || busy || confirming}
              aria-describedby={elsewhere ? "run-busy-note" : undefined}
            >
              {state.kind === "done" || priorRun ? "Run again" : "Run sealed forecast"}
            </TextButton>
            {busy ? <TextButton onClick={onCancel}>Cancel</TextButton> : null}
            <p className="font-mono text-[11px] text-muted">
              {routes === null
                ? "Checking routes (GET /openapi.json)"
                : `POST ${REPLAY_RUN_PATH} · persists the prediction before any reveal`}
            </p>
          </div>
          {elsewhere ? (
            <p id="run-busy-note" className="font-mono text-[11px] leading-relaxed text-risk">
              A run for <span className="break-all text-text-2">{elsewhere.caseId}</span> · {elsewhere.variant} is in
              flight. Run stays disabled until it answers or is cancelled.
            </p>
          ) : null}
          {busy ? (
            <p className="text-[11px] leading-relaxed text-muted" data-testid="cancel-note">
              Cancel only stops waiting in this browser. {NO_ANSWER_NOTE}
            </p>
          ) : null}
          {confirming ? (
            <div
              role="alertdialog"
              aria-labelledby="run-confirm-title"
              aria-describedby="run-confirm-body"
              className="flex flex-col gap-2 rounded-md border border-risk/60 bg-risk/10 px-3 py-2.5"
            >
              <p id="run-confirm-title" className="font-mono text-[11px] uppercase tracking-[0.12em] text-risk">
                Save a second forecast?
              </p>
              <div id="run-confirm-body" className="flex flex-col gap-1 text-xs leading-relaxed text-text-2">
                <p>{SECOND_FORECAST_NOTE}</p>
                {priorRun === "unanswered" ? (
                  <p className="text-muted">
                    The last request for this case and variant got no answer; the server may have saved it.
                  </p>
                ) : null}
              </div>
              <div className="flex flex-wrap gap-2 pt-1">
                <TextButton
                  onClick={() => {
                    setConfirmKey(null);
                    onRun();
                  }}
                >
                  Run anyway
                </TextButton>
                <button
                  ref={keepRef}
                  type="button"
                  onClick={() => setConfirmKey(null)}
                  className="inline-flex items-center gap-2 rounded-md border border-accent bg-accent-soft px-3 py-2 font-mono text-[11px] uppercase tracking-[0.14em] text-text transition-colors hover:bg-accent hover:text-bg"
                >
                  Don&apos;t run
                </button>
              </div>
            </div>
          ) : null}
        </div>
      )}

      <div className="flex flex-col gap-1 border-l border-line pl-3">
        <p className="font-mono text-[11px] uppercase tracking-[0.12em] text-muted">Recorded run: not available</p>
        <p className="text-[11px] leading-relaxed text-muted">
          {RECORDED_RUNS_PENDING.message} <code className="text-text-2">{RECORDED_RUNS_PENDING.request}</code>
        </p>
      </div>
    </div>
  );
}

const DECISION_LABEL = { act: "Act", wait: "Wait", hedge: "Hedge" } as const;

function ChosenPath({ state, rejected }: { state: RunState; rejected: boolean }) {
  if (state.kind === "idle") {
    return (
      <div className="flex flex-col gap-1.5">
        <p className="font-mono text-2xl font-medium uppercase tracking-[0.08em] text-muted md:text-3xl">Not available</p>
        <p className="text-xs leading-relaxed text-muted">
          No run in this session. A real local run, or a cached run labeled RECORDED RUN with prompt and snapshot
          hashes. Never a canned response.
        </p>
      </div>
    );
  }
  if (state.kind === "running") {
    return <InFlight request={state.request} note="A local model can take a while. Nothing is shown until it answers." />;
  }
  if (state.kind === "failed") {
    const f = state.failure;
    if (f.kind === "timeout" || f.kind === "aborted") {
      // No answer is not "API unreachable": the request reached the server, which may still save the forecast.
      return (
        <FailureNote
          size="lg"
          failure={f}
          headline={{
            title: f.kind === "timeout" ? "No answer received" : "Cancelled: no answer received",
            tone: "text-risk",
          }}
          note={
            <span data-testid="no-answer-note">
              No answer received in {state.waitedSeconds ?? "NOT AVAILABLE"} s. {NO_ANSWER_NOTE}
            </span>
          }
        />
      );
    }
    return <FailureNote size="lg" failure={f} note={failureNote(f)} />;
  }
  const { prediction, skeptic } = state.run;
  return (
    <div className="flex flex-col gap-4">
      <RevealCaveat run={state.run} />
      {rejected ? (
        <div className="flex flex-col gap-1.5" role="alert">
          <p className="font-mono text-2xl font-medium uppercase tracking-[0.06em] text-fail md:text-3xl">
            Rejected by skeptic
          </p>
          <p className="text-xs text-muted">Error-level problems below; this output is not a valid forecast.</p>
        </div>
      ) : (
        <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
          <p className="display text-6xl italic text-accent md:text-7xl">{DECISION_LABEL[prediction.decision]}</p>
          <span className="font-mono text-[11px] uppercase tracking-[0.14em] text-muted">
            decision: {prediction.decision}
          </span>
        </div>
      )}
      <div>
        <p className="kicker">Rationale</p>
        <p className="mt-1.5 whitespace-pre-line text-sm leading-relaxed text-text-2">{prediction.rationale}</p>
      </div>
      <SkepticList problems={skeptic.problems} />
    </div>
  );
}

/** What to tell the presenter for each failed run. Every case means: no forecast, nothing shown in its place. */
function failureNote(f: ReplayFailure): string | undefined {
  switch (f.kind) {
    case "admin_required":
      return "Running a forecast is disabled on the public demo; run it locally (make api, with the local model).";
    case "model_unavailable":
      return "Nothing was saved and no substitute answer is shown. The simulator and optimizer on CASCADE still work without the model.";
    case "conflict":
      return "Nothing was saved. Running again requests a fresh prediction id.";
    case "data_invalid":
      return "Nothing was saved.";
    case "validation":
      if (f.code === "INSUFFICIENT_DATA") return "Agent + market needs a market quote at the cutoff. Agent only still works.";
      if (f.code === "MODEL_OUTPUT_INVALID") return "The model's answer was rejected (output check or skeptic) and not saved.";
      if (f.code === "PROMPT_TOO_LONG" || f.code === "PROMPT_NOT_VERIFIED") return "No answer was kept and nothing was saved.";
      return undefined;
    default:
      return undefined;
  }
}

/**
 * The server's own audit flags: a forecast saved after a reveal (this event's, or any in the store) is not blind and
 * can never count toward an OFFICIAL scorecard. Shown whenever either flag is true, with the server's note verbatim.
 */
function RevealCaveat({ run }: { run: ReplayRun }) {
  if (!savedAfterReveal(run)) return null;
  return (
    <div role="alert" className="flex flex-col gap-1.5 rounded-md border border-risk/60 bg-risk/10 px-3 py-2.5">
      <p className="font-mono text-[11px] uppercase tracking-[0.12em] text-risk">
        Saved after a reveal: not blind, can&apos;t count as OFFICIAL
      </p>
      {run.audit_note ? <p className="text-xs leading-relaxed text-text-2">{run.audit_note}</p> : null}
      <p className="num font-mono text-[11px] text-muted">
        persist_seq {run.persist_seq}
        {run.persisted_after_event_reveal
          ? ` · this event first revealed at seq ${run.event_first_reveal_seq ?? "NOT AVAILABLE"}`
          : ""}
        {run.persisted_after_any_reveal
          ? ` · store first reveal at seq ${run.store_first_reveal_seq ?? "NOT AVAILABLE"}`
          : ""}
      </p>
    </div>
  );
}

function SkepticList({ problems }: { problems: ReplayRun["skeptic"]["problems"] }) {
  if (problems.length === 0) {
    return <p className="font-mono text-[11px] uppercase tracking-[0.1em] text-viable">Skeptic: no problems reported</p>;
  }
  return (
    <div>
      <p className="kicker">Skeptic</p>
      <ul className="mt-1.5 flex flex-col gap-1.5">
        {problems.map((p, i) => (
          <li key={`${p.code}-${i}`} className="text-xs leading-relaxed">
            <span
              className={`mr-2 font-mono text-[10px] uppercase tracking-[0.1em] ${
                p.severity === "error" ? "text-fail" : "text-risk"
              }`}
            >
              {p.severity} · {p.code}
            </span>
            <span className="text-text-2">{p.message}</span>
            {p.evidence_id ? <span className="num ml-1 text-muted">({p.evidence_id})</span> : null}
          </li>
        ))}
      </ul>
    </div>
  );
}

function Citations({
  run,
  c,
  evidence,
  onOpen,
}: {
  run: ReplayRun | null;
  c: ReplayCasePublic | null;
  evidence: EvidenceState;
  onOpen: (id: string | null) => void;
}) {
  if (!run) {
    return (
      <div className="flex flex-col gap-3">
        <p className="font-mono text-sm uppercase tracking-[0.08em] text-muted">Not available</p>
        <p className="font-mono text-[11px] text-muted">
          Citations are the run&apos;s own evidence_ids from its point-in-time snapshot (available_at ≤ as_of).
        </p>
        {c ? (
          <div>
            <TextButton onClick={() => onOpen(null)} aria-haspopup="dialog">
              Open evidence drawer
            </TextButton>
          </div>
        ) : null}
      </div>
    );
  }
  const served = evidence.kind === "done" && evidence.result.ok ? evidence.result.data.items : [];
  const titles = new Map(served.map((e) => [e.evidence_id, e.title]));
  const ids = run.prediction.evidence_ids;
  if (ids.length === 0) {
    return <p className="font-mono text-sm uppercase tracking-[0.08em] text-risk">The run cited no evidence.</p>;
  }
  return (
    <ol className="flex flex-col">
      {ids.map((id, i) => (
        <li key={id} className="border-b border-line/70 last:border-b-0">
          <button
            type="button"
            onClick={() => onOpen(id)}
            aria-haspopup="dialog"
            className="flex w-full items-baseline gap-4 rounded-sm py-2.5 text-left hover:bg-hover"
          >
            <span className="num text-xs text-muted">[{i + 1}]</span>
            <span className="min-w-0 flex-1">
              <span className="num block break-all text-xs text-text-2">{id}</span>
              <span className="block text-sm text-text">
                {titles.get(id) ?? (
                  <span className="font-mono text-[11px] uppercase tracking-[0.1em] text-muted">
                    Document not available
                  </span>
                )}
              </span>
              {c && !c.evidence_ids.includes(id) ? (
                <span className="mt-0.5 block font-mono text-[11px] text-risk">Not in the case&apos;s evidence list</span>
              ) : null}
            </span>
            <span aria-hidden="true" className="font-mono text-[11px] text-muted">
              open →
            </span>
          </button>
        </li>
      ))}
    </ol>
  );
}

function RunRecord({ run }: { run: ReplayRun | null }) {
  if (!run) {
    return (
      <dl className="grid grid-cols-1 gap-x-8 md:grid-cols-2">
        <Field label="Prediction id" />
        <Field label="Model" />
        <Field label="Prompt sha256" />
        <Field label="Snapshot sha256" />
      </dl>
    );
  }
  const p = run.prediction;
  return (
    <dl className="grid grid-cols-1 gap-x-8 md:grid-cols-2">
      <Field label="Prediction id" value={<span className="break-all">{p.prediction_id}</span>} />
      <Field label="Model" value={<span className="break-all">{p.agent_model}</span>} />
      <Field label="Model digest" value={p.model_digest ? <Hash value={p.model_digest} /> : undefined} />
      <Field label="Variant" value={p.variant} />
      <Field label="Prompt sha256 (as answered)" value={<Hash value={p.prompt_sha256} />} />
      <Field
        label="Gated prompt sha256"
        value={p.gated_prompt_sha256 ? <Hash value={p.gated_prompt_sha256} /> : undefined}
      />
      <Field label="Snapshot sha256" value={<Hash value={p.snapshot_sha256} />} />
      <Field label="Transcript sha256" value={p.transcript_sha256 ? <Hash value={p.transcript_sha256} /> : undefined} />
      <Field label="Attempts" value={p.attempts === null ? undefined : String(p.attempts)} />
      <Field label="Temperature" value={String(p.temperature)} />
      <Field label="Seed" value={p.seed === null ? undefined : String(p.seed)} />
      <Field
        label="Context / answer tokens"
        value={p.num_ctx === null || p.num_predict === null ? undefined : `${p.num_ctx} / ${p.num_predict}`}
      />
      <Field label="As-of" value={formatInstantUtc(p.as_of) ?? undefined} />
      <Field label="Recorded at" value={formatInstantUtc(p.recorded_at) ?? undefined} />
      <Field label="Persisted at" value={formatInstantUtc(run.persisted_at) ?? undefined} />
      <Field label="Persist seq (audit log)" value={String(run.persist_seq)} />
      <Field label="Record sha256" value={<Hash value={run.record_sha256} />} />
      <Field
        label="Saved after a reveal"
        value={
          savedAfterReveal(run) ? (
            <span className="text-risk">yes: not blind, not OFFICIAL</span>
          ) : (
            "no (before any reveal in this store)"
          )
        }
      />
    </dl>
  );
}
