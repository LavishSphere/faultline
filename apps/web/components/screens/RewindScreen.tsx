"use client";

import Link from "next/link";
import { useState } from "react";
import { EvidenceDrawer } from "../EvidenceDrawer";
import { Field, Panel } from "../Panel";
import { ProvenanceBadge } from "../ProvenanceBadge";
import { CaseList } from "../replay/CaseList";
import { CaseBadges, CutoffLine, FailureNote, Hash, InFlight, TextButton, caseProvenance } from "../replay/ReplayParts";
import { useCaseEvidence, useReplayCases, useReplayRoutes, useSelectedCase, type EvidenceState } from "../replay/hooks";
import { ScreenHeader } from "./ScreenHeader";
import { EVIDENCE_PATH_TEMPLATE, formatCutoffUtc, type ReplayCasePublic } from "@/lib/replay";
import type { Step } from "@/lib/steps";

/**
 * Screen A: REWIND (SPEC §2). Case list from GET /api/cases, the knowledge cutoff, the evidence known by then, and
 * the SEALED FUTURE. Every value is a served field; with no cases the screen says NOT AVAILABLE and names why.
 */
export function RewindScreen({ step }: { step: Step }) {
  const { load, retry } = useReplayCases();
  const { selected, select } = useSelectedCase(load);
  const routes = useReplayRoutes();
  const evidence = useCaseEvidence(selected, routes);
  const [drawer, setDrawer] = useState(false);

  return (
    <div className="flex flex-col gap-8">
      <ScreenHeader
        step={step}
        aside={
          selected ? (
            <Link
              href="/decision"
              className="inline-flex items-center gap-2 self-start rounded-md border border-accent px-3 py-2 font-mono text-[11px] uppercase tracking-[0.14em] text-text hover:bg-accent hover:text-bg lg:self-end"
            >
              Continue to the decision <span aria-hidden="true">→</span>
            </Link>
          ) : null
        }
      />

      <CaseTimeline c={selected} />

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-12">
        <Panel
          code="A.1"
          title="Replay cases"
          provenance={load.kind === "done" && load.result.ok && load.result.data.items.length ? "AS-OF" : "NOT AVAILABLE"}
          className="xl:col-span-4"
        >
          <CaseList load={load} retry={retry} selectedId={selected?.event_id ?? null} onSelect={select} />
        </Panel>

        <Panel
          code="A.2"
          title="Known by cutoff"
          provenance={evidenceServed(evidence) ? "AS-OF" : "NOT AVAILABLE"}
          provenanceDetail={selected && !evidenceServed(evidence) ? "documents" : undefined}
          className="xl:col-span-5"
        >
          {selected ? (
            <KnownByCutoff c={selected} evidence={evidence} onOpen={() => setDrawer(true)} />
          ) : (
            <NoCase />
          )}
        </Panel>

        <div className="flex flex-col gap-6 xl:col-span-3">
          <Panel code="A.3" title="Knowledge cutoff" provenance={selected ? caseProvenance(selected) : "NOT AVAILABLE"}>
            {selected ? <Cutoff c={selected} /> : <NoCase />}
          </Panel>

          <Panel code="A.4" title="Sealed future" provenance="SEALED" bodyClassName="hatch">
            <div className="flex items-center gap-3">
              <span aria-hidden="true" className="inline-block size-3 rounded-sm border border-risk bg-risk/30" />
              <p className="font-mono text-lg uppercase tracking-[0.14em] text-risk">Sealed future</p>
            </div>
            <p className="mt-3 text-xs leading-relaxed text-text-2">
              The outcome is not in agent input and is not served by any pre-reveal endpoint. It unlocks on REVEAL,
              only after a forecast has been persisted.
            </p>
            <p className="mt-2 font-mono text-[11px] leading-relaxed text-muted">
              {selected
                ? "This case payload carries no outcome-like key (the browser refuses any response that does)."
                : "No case selected."}
            </p>
          </Panel>
        </div>
      </div>

      {selected ? (
        <EvidenceDrawer open={drawer} onClose={() => setDrawer(false)} replayCase={selected} evidence={evidence} />
      ) : null}
    </div>
  );
}

function evidenceServed(e: EvidenceState): boolean {
  return e.kind === "done" && e.result.ok;
}

function NoCase() {
  return (
    <div className="flex flex-col gap-1.5">
      <p className="font-mono text-lg font-medium uppercase tracking-[0.08em] text-muted">Not available</p>
      <p className="text-xs text-muted">No case selected. Pick one from the served list.</p>
    </div>
  );
}

/** A.0: the cutoff splits the strip; everything right of it is sealed. Dates are the served ones, not inferred. */
function CaseTimeline({ c }: { c: ReplayCasePublic | null }) {
  const cutoff = c ? formatCutoffUtc(c.as_of) : null;
  return (
    <section aria-labelledby="rewind-timeline" className="overflow-hidden rounded-lg border border-line bg-elevated">
      <div className="flex min-h-11 flex-wrap items-center justify-between gap-2 border-b border-line px-5 py-2.5">
        <h2 id="rewind-timeline" className="font-mono text-[11px] uppercase tracking-[0.14em] text-text-2">
          <span className="text-muted">A.0</span> Historical timeline
        </h2>
        {c ? <CaseBadges c={c} /> : <ProvenanceBadge kind="NOT AVAILABLE" detail="No case loaded" />}
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-[3fr_2fr] md:grid-cols-[2fr_1fr]">
        <div className="relative min-w-0 px-5 py-6">
          <p className="kicker">Known by cutoff</p>
          <div className="mt-4 h-px bg-line-strong" aria-hidden="true" />
          {c ? (
            <>
              <p className="display mt-4 text-3xl leading-tight text-text md:text-4xl">{c.title}</p>
              <p className="mt-3 font-mono text-[11px] uppercase tracking-[0.12em] text-muted">
                {c.evidence_ids.length} evidence {c.evidence_ids.length === 1 ? "id" : "ids"} on the case record
              </p>
            </>
          ) : (
            <p className="mt-3 font-mono text-[11px] uppercase tracking-[0.12em] text-muted">Dates not available</p>
          )}
        </div>
        <div className="hatch relative border-t border-risk/70 px-5 py-6 sm:border-l sm:border-t-0">
          <span
            aria-hidden="true"
            className="absolute -top-[4.5px] left-5 size-2 rounded-full border border-risk bg-bg sm:-left-[4.5px] sm:top-[2.9rem]"
          />
          <p className="kicker text-risk">Sealed future</p>
          <div className="mt-4 h-px bg-risk/40" aria-hidden="true" />
          {c ? (
            <>
              <p className="num mt-4 text-sm text-text">
                <span className="text-muted">Cutoff </span>
                {cutoff ?? "not available"}
              </p>
              <p className="num mt-1 text-sm text-text-2">
                <span className="text-muted">Horizon </span>
                {c.horizon_days} days after cutoff
              </p>
            </>
          ) : null}
          <p className="mt-3 font-mono text-[11px] uppercase tracking-[0.12em] text-risk">Withheld until reveal</p>
        </div>
      </div>
    </section>
  );
}

function Cutoff({ c }: { c: ReplayCasePublic }) {
  const text = formatCutoffUtc(c.as_of);
  const [date, time] = text ? [text.slice(0, 10), text.slice(11)] : [null, null];
  return (
    <div className="flex flex-col gap-4">
      <div>
        <p className="kicker">As-of (UTC)</p>
        <p className="num mt-2 text-3xl font-medium leading-none tracking-tight text-text md:text-4xl">
          {date ?? "Not available"}
        </p>
        {time ? <p className="num mt-1 text-lg text-text-2">{time}</p> : null}
      </div>
      <CutoffLine asOf={c.as_of} className="text-xs" />
      <div>
        <p className="kicker">Question criteria</p>
        <p className="mt-1.5 text-xs leading-relaxed text-text-2">{c.question_criteria}</p>
        <p className="mt-1 font-mono text-[10px] uppercase tracking-[0.1em] text-muted">
          Settlement rule text, not the result
        </p>
      </div>
      <dl>
        <Field label="Horizon" value={`${c.horizon_days} d`} />
        <Field label="Market quote" value={c.market_quote_id ?? undefined} />
        <Field label="Snapshot" value={<Hash value={c.snapshot_hash} />} />
      </dl>
    </div>
  );
}

function KnownByCutoff({
  c,
  evidence,
  onOpen,
}: {
  c: ReplayCasePublic;
  evidence: EvidenceState;
  onOpen: () => void;
}) {
  const served = evidence.kind === "done" && evidence.result.ok ? evidence.result.data : null;
  const titles = new Map((served?.items ?? []).map((e) => [e.evidence_id, e.title]));
  return (
    <div className="flex flex-col gap-4">
      <CutoffLine asOf={c.as_of} className="text-sm" />
      {evidence.kind === "checking" || evidence.kind === "loading" ? (
        <InFlight request={evidence.kind === "checking" ? "GET /openapi.json" : `GET ${EVIDENCE_PATH_TEMPLATE}`} />
      ) : evidence.kind === "absent" ? (
        <FailureNote
          size="sm"
          failure={evidence.failure}
          note="Documents (title, source, available_at, text) need GET /api/cases/{case_id}/evidence. The ids below are the case record's."
        />
      ) : evidence.kind === "done" && !evidence.result.ok ? (
        <FailureNote size="sm" failure={evidence.result} />
      ) : null}

      {c.evidence_ids.length === 0 ? (
        <p className="font-mono text-sm uppercase tracking-[0.08em] text-muted">No evidence ids on this case.</p>
      ) : (
        <ol className="flex flex-col">
          {c.evidence_ids.map((id, i) => (
            <li key={id} className="flex items-baseline gap-4 border-b border-line/70 py-2.5 last:border-b-0">
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
              </span>
            </li>
          ))}
        </ol>
      )}

      <p className="font-mono text-[10px] leading-relaxed text-muted">
        Ids as served by GET /api/cases: only the items the temporal gate admits at the cutoff
        (EvidenceStore.public_case). Titles from GET /api/cases/{"{case_id}"}/evidence.
      </p>
      <div>
        <TextButton onClick={onOpen} aria-haspopup="dialog">
          Open evidence drawer
        </TextButton>
      </div>
    </div>
  );
}
