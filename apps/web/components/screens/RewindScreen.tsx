"use client";

import Link from "next/link";
import { useState } from "react";
import { EvidenceDrawer } from "../EvidenceDrawer";
import { Field, Panel } from "../Panel";
import { ProvenanceBadge } from "../ProvenanceBadge";
import { CaseList } from "../replay/CaseList";
import { MarketAtCutoff, marketBadges } from "../replay/MarketAtCutoff";
import { NotYetPublic } from "../replay/NotYetPublic";
import { CutoffLine, FailureNote, Hash, InFlight, TextButton, caseProvenance } from "../replay/ReplayParts";
import { TimeMachine } from "../replay/TimeMachine";
import { Vault } from "../replay/Vault";
import { useCaseEvidence, useReplayCases, useReplayRoutes, useSelectedCase, type EvidenceState } from "../replay/hooks";
import m from "../replay/motion.module.css";
import { ScreenHeader } from "./ScreenHeader";
import { EVIDENCE_PATH_TEMPLATE, formatCutoffUtc, formatInstantUtc, type ReplayCasePublic } from "@/lib/replay";
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

      <TimeMachine key={selected ? `${selected.event_id}|${selected.as_of}` : "none"} c={selected} evidence={evidence} />

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

          <Panel
            code="A.5"
            title="Market at cutoff"
            provenance={selected ? marketBadges(selected, null, evidence) : "NOT AVAILABLE"}
          >
            <MarketAtCutoff c={selected} run={null} evidence={evidence} />
          </Panel>

          <Panel code="A.4" title="Sealed future" provenance="SEALED" bodyClassName="hatch">
            <div className="flex items-center gap-4" data-testid="sealed-vault">
              <Vault key={selected?.event_id ?? "none"} className="size-12 shrink-0 text-risk" />
              <div className="min-w-0">
                <p className="font-mono text-lg uppercase tracking-[0.14em] text-risk">Sealed future</p>
                <p className="mt-0.5 text-sm text-text">Sealed: the outcome is locked until reveal</p>
              </div>
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

/** Hostname of a served source URL, for the card's source line. Display only. */
function sourceHost(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

/**
 * A.2: the documents the temporal gate admitted at the cutoff. Each card flies in once the evidence response has
 * landed (never before), in served order; the sealed placeholders after them are counts only.
 */
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
  const byId = new Map((served?.items ?? []).map((e) => [e.evidence_id, e]));
  // Cards wait for the A.0 scrub to land (about 1.7 s), so the documents arrive "at" the cutoff.
  const base = 900;
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
        <ol className="flex flex-col gap-2" data-testid="known-evidence">
          {c.evidence_ids.map((id, i) => {
            const doc = byId.get(id);
            return (
              <li
                key={`${id}-${served ? "doc" : "id"}`}
                className={`flex items-start gap-3 rounded-md border border-line bg-bg/40 px-3.5 py-3 ${served ? m.flyIn : ""}`}
                style={served ? { animationDelay: `${base + i * 130}ms` } : undefined}
              >
                <span className="num mt-0.5 text-xs text-accent">[{i + 1}]</span>
                <span className="min-w-0 flex-1">
                  <span className="block text-sm leading-snug text-text">
                    {doc?.title ?? (
                      <span className="font-mono text-[11px] uppercase tracking-[0.1em] text-muted">
                        Document not available
                      </span>
                    )}
                  </span>
                  <span className="num mt-1 block break-all text-[11px] text-muted">
                    {id}
                    {doc ? (
                      <>
                        {" "}
                        · available {formatInstantUtc(doc.available_at) ?? "NOT AVAILABLE"} · {sourceHost(doc.source_url)}
                      </>
                    ) : null}
                  </span>
                  {doc ? (
                    <span className="mt-1.5 block sm:hidden">
                      <ProvenanceBadge kind={doc.provenance} />
                    </span>
                  ) : null}
                </span>
                {doc ? (
                  <span className="hidden shrink-0 sm:block">
                    <ProvenanceBadge kind={doc.provenance} />
                  </span>
                ) : null}
              </li>
            );
          })}
        </ol>
      )}

      <div className="border-t border-line pt-4">
        <NotYetPublic evidence={evidence} delayMs={base + c.evidence_ids.length * 130} />
      </div>

      <p className="font-mono text-[10px] leading-relaxed text-muted">
        Ids as served by GET /api/cases: only the items the temporal gate admits at the cutoff
        (EvidenceStore.public_case). Documents and exclusion counts from GET /api/cases/{"{case_id}"}/evidence.
      </p>
      <div>
        <TextButton onClick={onOpen} aria-haspopup="dialog">
          Open evidence drawer
        </TextButton>
      </div>
    </div>
  );
}
