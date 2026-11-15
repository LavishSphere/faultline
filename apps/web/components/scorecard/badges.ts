import type { Scorecard } from "@/lib/benchmark";
import type { ProvenanceInput } from "../ProvenanceBadge";

/** A synthetic card, by the API's provenance or case-set tag. */
export function isSynthetic(card: Scorecard): boolean {
  return card.provenance === "SYNTHETIC" || card.case_set === "synthetic";
}

/** Provenance badges of a recorded scorecard, from its own fields (shared by the D.2 cards and the results chart). */
export function cardBadges(card: Scorecard): ProvenanceInput[] {
  const out: ProvenanceInput[] = ["RECORDED RUN"];
  if (card.provenance) out.push(card.provenance);
  if (card.case_set === "synthetic" && card.provenance !== "SYNTHETIC") out.push("SYNTHETIC");
  if (isSynthetic(card) || card.label.startsWith("ILLUSTRATIVE")) out.push("ILLUSTRATIVE");
  if (card.verdict === "INSUFFICIENT DATA") out.push("INSUFFICIENT DATA");
  return out;
}
