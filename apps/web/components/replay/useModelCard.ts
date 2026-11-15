"use client";

import { useEffect, useState } from "react";
import { getIntegrity } from "@/lib/integrity";

/**
 * The configured replay model's card facts, as GET /api/integrity serves them in its
 * `model_contamination_disclosed` check (routes/integrity.py, from agents/model_cards.py). No other route serves
 * the model card yet; a dedicated field is a follow-up (#163). `null` fields are NOT AVAILABLE.
 */
export interface ModelCardFacts {
  model: string | null;
  /** "YYYY-MM" of the pretraining-data cutoff, verbatim. */
  knowledgeCutoff: string | null;
  release: string | null;
}

export type ModelCardLoad = { kind: "loading" } | { kind: "done"; card: ModelCardFacts | null; error: string | null };

const CHECK_ID = "model_contamination_disclosed";
const LABELS = {
  model: "Model",
  knowledgeCutoff: "Training data ends (model card)",
  release: "Public release (model card)",
} as const;

let cached: Promise<ModelCardLoad> | null = null;

function fact(facts: { label: string; value: string }[], label: string): string | null {
  const v = facts.find((f) => f.label === label)?.value;
  return v && v !== "NOT AVAILABLE" && v !== "None" ? v : null;
}

function load(): Promise<ModelCardLoad> {
  // One request per page session; a failure is not cached, so a later mount asks again.
  cached ??= getIntegrity({}).then((res): ModelCardLoad => {
    if (!res.ok) {
      cached = null;
      return { kind: "done", card: null, error: res.error };
    }
    const check = res.data.checks.find((c) => c.id === CHECK_ID);
    if (!check) return { kind: "done", card: null, error: `${CHECK_ID} not in the response` };
    return {
      kind: "done",
      card: {
        model: fact(check.facts, LABELS.model),
        knowledgeCutoff: fact(check.facts, LABELS.knowledgeCutoff),
        release: fact(check.facts, LABELS.release),
      },
      error: null,
    };
  });
  return cached;
}

export function useModelCard(): ModelCardLoad {
  const [state, setState] = useState<ModelCardLoad>({ kind: "loading" });
  useEffect(() => {
    let live = true;
    void load().then((s) => {
      if (live) setState(s);
    });
    return () => {
      live = false;
    };
  }, []);
  return state;
}
